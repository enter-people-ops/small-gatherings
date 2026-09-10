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

import convenia, sheets, render, hotspots, slack_msgs as S
from grouping import Person, Config, make_groups

DEFAULT_OFFICE_ADDRESS = "Rua Capote Valente, 839 - Pinheiros, São Paulo - SP, 05409-002"

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
    return MONTHS_PT[d.month]

def _gbucket(g: str) -> str:
    import unicodedata
    s = "".join(c for c in unicodedata.normalize("NFKD", str(g or "")) if not unicodedata.combining(c)).lower()
    if not s or s in ("?", "n/d"):
        return "?"
    if s == "f" or "fem" in s or "mulher" in s:
        return "F"
    if s == "m" or "masc" in s or "homem" in s:
        return "M"
    return "Outro"


def to_person(p: dict) -> Person:
    def s(v, default="?"):
        if v is None or v == "":
            return default
        return v if isinstance(v, str) else str(v)
    return Person(id=str(p.get("id","")), name=s(p.get("name"), "—"),
                  gender=_gbucket(p.get("gender")), team=s(p.get("team")),
                  department=s(p.get("department")), seniority=s(p.get("seniority")),
                  is_leader=bool(p.get("is_leader", False)))

def run(send: bool):
    """CLI: delega para run_api (fonte única). --dry-run só imprime as prévias."""
    if send:
        r = run_api(send=True)
        print(f"== {r['month']} == grupos={r['n_groups']} score={r['score']} "
              f"test_mode={r['test_mode']} enviado.")
        return
    r = run_api(send=False)
    print(f"== {r['month']} == grupos={r['n_groups']} score={r['score']} "
          f"test_mode={r['test_mode']} aniversariantes={r['anniversaries_this_month']} "
          f"nao_resolvidos={len(r['unresolved'])}")
    print("\n[DRY-RUN] Nada enviado. Prévias:")
    print("\n--- GERAL ---\n"+r["general_msg"])
    print("\n--- LÍDERES ---\n"+r["leaders_msg"])
    print("\n--- RELATÓRIO ---\n"+r["report_msg"])
    print("\n--- DMs ---")
    for dm in r["dms"]:
        print(f"[para {dm['name']} / {dm['slack_id']}]\n{dm['text']}\n")

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


def convenia_report() -> dict:
    """Diagnóstico read-only: o que a API do Convenia realmente devolve (sem
    filtrar elegibilidade) — pra investigar divergência de headcount com o
    painel do Convenia."""
    return convenia.raw_report(os.environ["CONVENIA_TOKEN"], dt.date.today())


def _parse_date(s):
    if not s:
        return None
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%Y-%m-%dT%H:%M:%S"):
        try:
            return dt.datetime.strptime(str(s)[:19], fmt).date()
        except ValueError:
            continue
    return None

# aniversário de casa: a partir de 1 ano, QUALQUER aniversário anual (sem teto)
def _anniversary_label(months: int) -> str | None:
    if months >= 12 and months % 12 == 0:
        anos = months // 12
        return f"{anos} ano" if anos == 1 else f"{anos} anos"
    return None

def work_anniversaries(people: list[dict], ref: dt.date) -> dict:
    """Retorna {id: rótulo} de quem faz aniversário de casa (6m ou N anos) no mês de ref."""
    out = {}
    for p in people:
        d = _parse_date(p.get("hiring_date"))
        if not d:
            continue
        months = (ref.year - d.year) * 12 + (ref.month - d.month)
        lbl = _anniversary_label(months)
        if lbl:
            out[p["id"]] = lbl
    return out


def _diversity_pick(pool: list, group: list, k: int) -> list:
    """Escolhe k pessoas do pool que mais aumentam a diversidade do grupo (guloso)."""
    chosen = []
    cur = list(group)
    for _ in range(min(k, len(pool))):
        best, best_gain = None, -1
        for p in pool:
            if p in chosen:
                continue
            gain = 0
            for attr in ("gender", "team", "seniority"):
                if getattr(p, attr) not in {getattr(x, attr) for x in cur}:
                    gain += 1
            if gain > best_gain:
                best_gain, best = gain, p
        if best is None:
            break
        chosen.append(best); cur.append(best)
    return chosen


def build_groups(persons: list, history, cfg, special_leader_id: str | None,
                 anniversary_ids: set) -> tuple[list, float]:
    """
    Forma os grupos garantindo que o grupo do líder especial (Mateus) seja o
    PRIMEIRO e contenha todos os aniversariantes de casa do mês. O restante é
    otimizado normalmente (diversidade + novidade vs histórico).
    """
    special = next((p for p in persons if p.id == special_leader_id and p.is_leader), None)
    if special is None:
        return make_groups(persons, history, cfg)  # sem líder especial: fluxo normal

    # aniversariantes vão pro grupo do Mateus, MAS líderes continuam liderando
    # seus próprios grupos (não são puxados) — exceto o próprio Mateus.
    aniv = [p for p in persons
            if p.id in anniversary_ids and p.id != special.id and not p.is_leader]
    reserved = {special.id} | {p.id for p in aniv}
    rest = [p for p in persons if p.id not in reserved]

    special_group = [special] + aniv
    # tamanho-alvo do grupo do Mateus = média balanceada dos demais grupos
    # (colaboradores restantes / líderes restantes), pra ficar parecido em tamanho
    rest_leaders = [p for p in rest if p.is_leader]
    avg_size = round(len(rest) / len(rest_leaders)) if rest_leaders else len(special_group)
    need = avg_size - len(special_group)
    if need > 0:
        non_leaders = [p for p in rest if not p.is_leader]
        extra = _diversity_pick(non_leaders, special_group, need)
        special_group += extra
        rest = [p for p in rest if p not in extra]

    rest_groups, score = make_groups(rest, history, cfg)
    return [special_group] + rest_groups, score


def run_api(send: bool) -> dict:
    """Versão para o servidor/Make: roda o pipeline e devolve os payloads.
    Se send=True, envia pelo Slack aqui mesmo. Se False, o Make envia."""
    ref = dt.date.today(); label = month_label(ref)
    people = convenia.fetch_eligible(os.environ["CONVENIA_TOKEN"], ref)
    leaders = sheets.read_leaders_csv(os.environ["LEADERS_CSV_URL"])
    people = sheets.mark_leaders(people, leaders)
    by_id = {p["id"]: p for p in people}

    # aniversários de casa do mês + líder especial (Mateus) por e-mail
    anniversaries = work_anniversaries(people, ref)
    special_email = os.environ.get("ANNIVERSARY_LEADER_EMAIL", "mateus@getenter.ai").lower()
    special = next((p for p in people if (p.get("email") or "").lower() == special_email
                    and p.get("is_leader")), None)
    special_id = special["id"] if special else None

    persons = [to_person(p) for p in people]
    history = sheets.load_history()
    cfg = Config(min_women=int(os.environ.get("GROUP_MIN_WOMEN","2")),
                 female_token="F")
    groups, score = build_groups(persons, history, cfg, special_id, set(anniversaries))

    groups_d = [[{**by_id[p.id], "is_leader": p.is_leader} for p in g] for g in groups]

    # resolve slack_id/nome ANTES de gerar o artefato, pra exibir o nome do
    # Slack (não o nome completo do Convenia) no artefato e nas mensagens
    flat_for_slack = [p for g in groups_d for p in g]
    slack_ids, slack_names = S.resolve_ids_and_names(flat_for_slack, token=os.environ.get("SLACK_BOT_TOKEN",""))
    for p in flat_for_slack:
        if slack_names.get(p["id"]):
            p["name"] = slack_names[p["id"]]

    payload = {"month": label, "generated_at": ref.isoformat(), "groups": groups_d}
    json.dump(payload, open("../data/groups.json","w",encoding="utf-8"), ensure_ascii=False, indent=2)

    # sugestões de rolê via OpenStreetMap (raio de 5km do escritório); se a
    # busca falhar, mantém o hotspots.json existente
    fresh_hotspots, hotspots_error = hotspots.fetch_hotspots(
        os.environ.get("OFFICE_ADDRESS", DEFAULT_OFFICE_ADDRESS), label)
    if fresh_hotspots:
        json.dump(fresh_hotspots, open("../data/hotspots.json","w",encoding="utf-8"), ensure_ascii=False, indent=2)

    render.main("../data/groups.json","../data/hotspots.json","../data/index.html")
    artifact_url = os.environ.get("ARTIFACT_URL","")
    msgs = S.build_all(groups_d, artifact_url, label, token=os.environ.get("SLACK_BOT_TOKEN",""), ids=slack_ids)

    test_mode = os.environ.get("TEST_MODE", "true").lower() == "true"
    from collections import Counter
    gender_dist = Counter((p.get("gender") or "(vazio)") for p in people)
    result = {"month": label, "n_groups": len(groups), "score": round(score,2),
              "test_mode": test_mode, "artifact_url": artifact_url,
              "anniversaries_this_month": len(anniversaries),
              "special_leader": (special["name"] if special else None),
              "gender_distribution": dict(gender_dist.most_common()),
              "general_channel": os.environ.get("CANAL_TESTE_GERAL") if test_mode else os.environ.get("CANAL_GERAL"),
              "leaders_channel": os.environ.get("CANAL_TESTE_LIDERES") if test_mode else os.environ.get("CANAL_LIDERES"),
              "report_target": os.environ.get("CANAL_TESTE_RELATORIO") if test_mode else os.environ.get("DM_RELATORIO"),
              "hotspots_updated": bool(fresh_hotspots), "hotspots_error": hotspots_error,
              "general_msg": msgs["geral"], "leaders_msg": msgs["lideres"],
              "report_msg": msgs["relatorio"],
              "dms": [{"slack_id": d["slack_id"], "name": d["leader"]["name"], "text": d["text"]} for d in msgs["dms"]],
              "unresolved": msgs["unresolved"], "sent": send}
    if send:
        _send(msgs, test_mode)
        sheets.append_history([[p.id for p in g] for g in groups])
    return result


def _send(msgs: dict, test_mode: bool = True):
    """Envia no Slack. Em TEST_MODE=true: tudo vai pros canais de teste
    (CANAL_TESTE_GERAL, CANAL_TESTE_LIDERES, CANAL_TESTE_DM_LIDERES,
    CANAL_TESTE_RELATORIO), rotulado. Em TEST_MODE=false: geral e líderes vão
    pros canais reais (CANAL_GERAL, CANAL_LIDERES), as DMs vão de fato pro
    Slack ID de cada líder, e o relatório vai como DM pro Slack ID em
    DM_RELATORIO (não um canal)."""
    import requests
    tok = os.environ["SLACK_BOT_TOKEN"]
    hdr = {"Authorization": f"Bearer {tok}", "Content-Type": "application/json; charset=utf-8"}
    def post(channel, text):
        return requests.post("https://slack.com/api/chat.postMessage", headers=hdr,
                             json={"channel": channel, "text": text}).json()

    def env(name):
        val = os.environ.get(name)
        if not val:
            raise ValueError(f"Variável de ambiente '{name}' não configurada (necessária para enviar no Slack).")
        return val

    if test_mode:
        post(env("CANAL_TESTE_GERAL"), msgs["geral"])
        post(env("CANAL_TESTE_LIDERES"), msgs["lideres"])
        test_dm_ch = env("CANAL_TESTE_DM_LIDERES")
        for dm in msgs["dms"]:
            post(test_dm_ch, dm["text"])
        post(env("CANAL_TESTE_RELATORIO"), msgs["relatorio"])
    else:
        post(env("CANAL_GERAL"), msgs["geral"])
        post(env("CANAL_LIDERES"), msgs["lideres"])
        for dm in msgs["dms"]:
            if dm["slack_id"]:
                post(dm["slack_id"], dm["text"])
        post(env("DM_RELATORIO"), msgs["relatorio"])

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--send", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    run(send=a.send and not a.dry_run)
