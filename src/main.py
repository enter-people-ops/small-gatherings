"""
Orquestrador mensal. Roda no dia 1 de cada mês.

Passos:
  1. Busca elegíveis no Convenia (ativos + admitidos no mês).
  2. Lê líderes na planilha e marca is_leader.
  3. Forma os grupos (diversidade + novidade vs histórico).
  4. Gera o artefato HTML e (opcional) publica.
  5. Monta as 3 mensagens do Slack.
  6. Envia (se --send) e persiste o histórico.

Variáveis de ambiente:
  CONVENIA_TOKEN, SLACK_BOT_TOKEN, LEADERS_CSV_URL, ARTIFACT_URL,
  EMAIL_DOMAIN (default getenter.ai)

Uso:
  python main.py --dry-run          # não envia nada, só gera artefato + previews
  python main.py --send             # envia as mensagens de fato
"""
from __future__ import annotations
import os, sys, json, argparse, datetime as dt

import convenia, sheets, render, slack_msgs as S
from grouping import Person, Config, make_groups

def _load_env(path: str = "../.env"):
    """Carrega um .env simples (KEY=VALUE) para os.environ, se existir.
    No Railway as variáveis já vêm do ambiente, então isto é só p/ uso local."""
    if not os.path.exists(path):
        return
    for line in open(path, encoding="utf-8"):
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())

_load_env()

MONTHS_PT = ["", "Janeiro","Fevereiro","Março","Abril","Maio","Junho","Julho",
             "Agosto","Setembro","Outubro","Novembro","Dezembro"]

def month_label(d: dt.date) -> str:
    return f"{MONTHS_PT[d.month]}/{d.year}"

def to_person(p: dict) -> Person:
    def s(v, default="?"):
        if v is None or v == "":
            return default
        return v if isinstance(v, str) else str(v)
    return Person(id=str(p.get("id","")), name=s(p.get("name"), "—"),
                  gender=s(p.get("gender")), team=s(p.get("team")),
                  department=s(p.get("department")), seniority=s(p.get("seniority")),
                  is_leader=bool(p.get("is_leader", False)))

def run(send: bool):
    ref = dt.date.today()
    label = month_label(ref)

    people = convenia.fetch_eligible(os.environ["CONVENIA_TOKEN"], ref)
    leaders = sheets.read_leaders_csv(os.environ["LEADERS_CSV_URL"])
    people = sheets.mark_leaders(people, leaders)

    by_id = {p["id"]: p for p in people}
    persons = [to_person(p) for p in people]
    history = sheets.load_history()
    groups, score = make_groups(persons, history, Config(target_size=int(os.environ.get("GROUP_SIZE","5"))))

    # volta para dicts ricos (com slack_id/email da planilha)
    groups_d = [[{**by_id[p.id], "is_leader": p.is_leader} for p in g] for g in groups]

    payload = {"month": label, "generated_at": ref.isoformat(), "groups": groups_d}
    json.dump(payload, open("../data/groups.json","w",encoding="utf-8"), ensure_ascii=False, indent=2)
    render.main("../data/groups.json","../data/hotspots.json","../data/index.html")

    artifact_url = os.environ.get("ARTIFACT_URL","(defina ARTIFACT_URL)")
    msgs = S.build_all(groups_d, artifact_url, label, token=os.environ.get("SLACK_BOT_TOKEN",""))

    print(f"== {label} == grupos={len(groups)} score={score:.1f} nao_resolvidos_slack={len(msgs['unresolved'])}")
    if not send:
        print("\n[DRY-RUN] Mensagens NÃO enviadas. Preview:")
        print("\n--- GERAL ---\n"+msgs["geral"])
        print("\n--- LÍDERES ---\n"+msgs["lideres"])
        print("\n--- DMs ---")
        for dm in msgs["dms"]:
            print(f"[para {dm['leader']['name']} / {dm['slack_id']}]\n{dm['text']}\n")
        return

    _send(msgs)
    sheets.append_history([[p.id for p in g] for g in groups])
    print("Enviado e histórico atualizado.")

def diagnose() -> dict:
    """Diagnóstico read-only: por que os líderes não bateram? Não envia nada."""
    ref = dt.date.today()
    people = convenia.fetch_eligible(os.environ["CONVENIA_TOKEN"], ref, enrich=False)
    leaders = sheets.read_leaders_csv(os.environ["LEADERS_CSV_URL"])
    matches = sheets.match_leaders(people, leaders)
    ok = [n for n, m in matches.items() if m["status"] == "ok"]
    via_email = sum(1 for m in matches.values() if m["status"] == "ok" and m.get("via") == "email")
    ambiguous = {n: m.get("candidates") for n, m in matches.items() if m["status"] == "ambiguous"}
    not_found = [n for n, m in matches.items() if m["status"] == "not_found"]
    return {
        "convenia_count": len(people),
        "sheet_leaders_count": len(leaders),
        "matched_leaders": len(ok),
        "matched_via_email": via_email,
        "matched_via_name": len(ok) - via_email,
        "ambiguous": ambiguous,          # nome/email que bate com >1 pessoa -> desambiguar
        "not_found": not_found,          # não bate com ninguém -> corrigir grafia/apelido
        "hint": ("ok = casados (por email ou nome). ambiguous = adicione sobrenome na planilha. "
                 "not_found = grafia/apelido nao bate com nenhum ativo do Convenia."),
    }


def run_api(send: bool) -> dict:
    """Versão para o servidor/Make: roda o pipeline e devolve os payloads.
    Se send=True, envia pelo Slack aqui mesmo. Se False, o Make envia."""
    ref = dt.date.today(); label = month_label(ref)
    people = convenia.fetch_eligible(os.environ["CONVENIA_TOKEN"], ref)
    leaders = sheets.read_leaders_csv(os.environ["LEADERS_CSV_URL"])
    people = sheets.mark_leaders(people, leaders)
    by_id = {p["id"]: p for p in people}
    persons = [to_person(p) for p in people]
    history = sheets.load_history()
    groups, score = make_groups(persons, history,
                                Config(target_size=int(os.environ.get("GROUP_SIZE","5")),
                                       size_min=int(os.environ.get("GROUP_MIN","4")),
                                       size_max=int(os.environ.get("GROUP_MAX","6"))))
    groups_d = [[{**by_id[p.id], "is_leader": p.is_leader} for p in g] for g in groups]
    payload = {"month": label, "generated_at": ref.isoformat(), "groups": groups_d}
    json.dump(payload, open("../data/groups.json","w",encoding="utf-8"), ensure_ascii=False, indent=2)
    render.main("../data/groups.json","../data/hotspots.json","../data/index.html")
    artifact_url = os.environ.get("ARTIFACT_URL","")
    msgs = S.build_all(groups_d, artifact_url, label, token=os.environ.get("SLACK_BOT_TOKEN",""))
    result = {"month": label, "n_groups": len(groups), "score": round(score,2),
              "artifact_url": artifact_url,
              "general_channel": os.environ.get("SLACK_GENERAL_CHANNEL"),
              "leaders_channel": os.environ.get("SLACK_LEADERS_CHANNEL") or os.environ.get("SLACK_GENERAL_CHANNEL"),
              "general_msg": msgs["geral"], "leaders_msg": msgs["lideres"],
              "dms": [{"slack_id": d["slack_id"], "name": d["leader"]["name"], "text": d["text"]} for d in msgs["dms"]],
              "unresolved": msgs["unresolved"], "sent": send}
    if send:
        _send(msgs)
        sheets.append_history([[p.id for p in g] for g in groups])
    return result


def _send(msgs: dict):
    import requests
    tok = os.environ["SLACK_BOT_TOKEN"]
    hdr = {"Authorization": f"Bearer {tok}", "Content-Type": "application/json; charset=utf-8"}
    def post(channel, text):
        r = requests.post("https://slack.com/api/chat.postMessage", headers=hdr,
                          json={"channel": channel, "text": text}); return r.json()
    general_ch = os.environ["SLACK_GENERAL_CHANNEL"]
    leaders_ch = os.environ.get("SLACK_LEADERS_CHANNEL", general_ch)
    post(general_ch, msgs["geral"])
    post(leaders_ch, msgs["lideres"])
    for dm in msgs["dms"]:
        if dm["slack_id"]:
            post(dm["slack_id"], dm["text"])  # DM: channel = user id

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--send", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    run(send=a.send and not a.dry_run)
