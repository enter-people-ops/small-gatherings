"""
Resolução de identidade (Convenia -> Slack) e montagem das 3 mensagens.

O e-mail corporativo NÃO vem do Convenia (é provisionado internamente).
Estratégia de mapeamento, em ordem:
  1. Coluna 'slack_id' na planilha de líderes/pessoas, se existir (mais confiável).
  2. Convenção de e-mail nome.sobrenome@getenter.ai -> Slack users.lookupByEmail.
  3. Fallback: cita o nome sem @ (e loga para revisão manual).
"""
from __future__ import annotations
import os
import re
import unicodedata
import requests

SLACK_TOKEN = os.environ.get("SLACK_BOT_TOKEN", "")
EMAIL_DOMAIN = os.environ.get("EMAIL_DOMAIN", "getenter.ai")


def email_from_convention(name: str, domain: str = EMAIL_DOMAIN) -> str:
    parts = [p for p in _strip_accents(name).lower().split() if p]
    if len(parts) < 2:
        return f"{parts[0]}@{domain}" if parts else ""
    return f"{parts[0]}.{parts[-1]}@{domain}"


def _strip_accents(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))


def fetch_slack_directory(token: str = SLACK_TOKEN) -> list[dict]:
    """Puxa todos os usuários ativos do Slack (id, real_name, display_name, email)."""
    users, cursor = [], None
    while token:
        params = {"limit": 200}
        if cursor:
            params["cursor"] = cursor
        r = requests.get("https://slack.com/api/users.list",
                         headers={"Authorization": f"Bearer {token}"}, params=params, timeout=20)
        data = r.json()
        if not data.get("ok"):
            break
        for m in data.get("members", []):
            if m.get("deleted") or m.get("is_bot") or m.get("id") == "USLACKBOT":
                continue
            prof = m.get("profile", {})
            users.append({"id": m["id"],
                          "real_name": prof.get("real_name") or m.get("real_name") or "",
                          "display_name": prof.get("display_name") or "",
                          "email": prof.get("email") or ""})
        cursor = (data.get("response_metadata") or {}).get("next_cursor") or ""
        if not cursor:
            break
    return users


def match_by_name(people: list[dict], directory: list[dict],
                  email_domain: str = EMAIL_DOMAIN) -> dict[str, str | None]:
    """
    Casa Convenia->Slack em cascata:
      1) e-mail exato do Convenia (raro) contra e-mails do diretório;
      2) e-mail montado pela convenção nome.sobrenome@dominio contra o diretório;
      3) subconjunto de tokens do nome contra real_name/display_name do Slack,
         aceitando só quando houver UM único candidato (homônimo -> não resolve).
    """
    def toks(s):
        s = _strip_accents(s or "").lower().replace("-", " ").replace(".", " ")
        return {t for t in s.split() if t}

    by_email = {}
    dir_tokens = []
    for u in directory:
        if u.get("email"):
            by_email[_strip_accents(u["email"]).lower()] = u["id"]
        names = " ".join(filter(None, [u.get("real_name"), u.get("display_name")]))
        dir_tokens.append((u["id"], toks(names)))

    out = {}
    for p in people:
        sid = None
        em = _strip_accents((p.get("email") or "")).lower()
        if em and em in by_email:
            sid = by_email[em]
        if not sid:
            conv = _strip_accents(email_from_convention(p["name"], email_domain)).lower()
            if conv in by_email:
                sid = by_email[conv]
        if not sid:
            pt = toks(p["name"])
            if pt:
                cands = [uid for uid, ut in dir_tokens if pt <= ut]
                if len(cands) == 1:
                    sid = cands[0]
        out[p["id"]] = sid
    return out


def lookup_slack_id(email: str, token: str = SLACK_TOKEN) -> str | None:
    if not email or not token:
        return None
    r = requests.get("https://slack.com/api/users.lookupByEmail",
                     headers={"Authorization": f"Bearer {token}"},
                     params={"email": email}, timeout=15)
    data = r.json()
    return data["user"]["id"] if data.get("ok") else None


def resolve_ids(people: list[dict], token: str = SLACK_TOKEN,
                directory: list[dict] | None = None) -> dict[str, str | None]:
    """
    id_convenia -> slack_user_id (ou None).
    Prioridade: (1) slack_id vindo da planilha (override autoritativo);
                (2) match automático pelo diretório do Slack (users.list) por
                    e-mail/nome. Assim a planilha só precisa das exceções.
    """
    if directory is None and token:
        directory = fetch_slack_directory(token)
    auto = match_by_name(people, directory or [])
    out = {}
    for p in people:
        out[p["id"]] = p.get("slack_id") or auto.get(p["id"])
    return out


PEOPLE_MENTION = "<@U0AMR8525DE>"  # Gabriela Barbosa (contato do time de People)


def mention(p: dict, ids: dict[str, str | None]) -> str:
    sid = ids.get(p["id"])
    return f"<@{sid}>" if sid else f"*{p['name']}*"


# ---------------------------------------------------------------------------
# As 3 mensagens
# ---------------------------------------------------------------------------
def msg_geral(artifact_url: str, month_label: str) -> str:
    return (
        f":coffee: *Small Gatherings de {month_label} estão no ar!*\n"
        f"Todos os meses a gente mistura o time da Enter para que mais pessoas se conheçam "
        f"para além do escritório. Descubra o seu grupo e sugestões de encontros para "
        f"marcarem <{artifact_url}|aqui>.\n\n"
        f"Lembrem-se de sempre mandar suas fotos de small gathering em nosso grupo de "
        f"whatsapp (Black Pearl). Bons encontros!\n\n"
        f"Qualquer dúvida, falem com o time de {PEOPLE_MENTION}."
    )


def msg_lideres(artifact_url: str, month_label: str) -> str:
    return (
        f":busts_in_silhouette: *Capitães, os Small Gatherings de {month_label} estão no ar!*\n"
        f"Cada um de vocês recebeu (na DM) a lista do seu grupo com os @ de todos. Vocês "
        f"também podem descobrir o seu grupo e ver sugestões de encontros para marcarem "
        f"<{artifact_url}|aqui>.\n\n"
        f"1. Crie um *canal no Slack* com as pessoas do seu small gathering.\n"
        f"2. Proponham 2–3 opções de data/horário e *fechem um encontro* (café, almoço, happy hour…).\n\n"
        f"Lembrem-se de sempre mandar suas fotos de small gathering em nosso grupo de "
        f"whatsapp (Black Pearl). Bons encontros!\n\n"
        f"Qualquer dúvida, falem com o time de {PEOPLE_MENTION}."
    )


def _member_line(idx: int, m: dict, ids: dict[str, str | None]) -> str:
    meta = " • ".join(p for p in (m.get("team") or "", m.get("tenure_label") or "") if p)
    line = f"{idx}. {mention(m, ids)}"
    return f"{line} — {meta}" if meta else line


def msg_dm_lider(lider: dict, membros: list[dict], ids: dict[str, str | None],
                 month_label: str) -> str:
    linhas = "\n".join(_member_line(i, m, ids) for i, m in enumerate(membros, 1))
    return (
        f"Oi {mention(lider, ids)}! :wave: Você é o capitão de um small gathering em {month_label}\n\n"
        f"{linhas}\n\n"
        f"Qualquer dúvida, fale com o time de {PEOPLE_MENTION}."
    )


def _gender_bucket(g: str) -> str:
    s = _strip_accents(g or "").lower()
    if not s or s in ("?", "n/d"):
        return "?"
    if s == "f" or "fem" in s or "mulher" in s:
        return "F"
    if s == "m" or "masc" in s or "homem" in s:
        return "M"
    return "Outro"


def _distinct(vals):
    v = [x for x in vals if x and x not in ("?", "N/D")]
    return len(set(v))


def msg_relatorio(groups: list[list[dict]], month_label: str) -> str:
    n = len(groups); total = sum(len(g) for g in groups)
    men = [sum(1 for p in g if _gender_bucket(p.get("gender","")) == "M") for g in groups]
    women = [sum(1 for p in g if _gender_bucket(p.get("gender","")) == "F") for g in groups]
    avg_m = sum(men)/n if n else 0
    avg_f = sum(women)/n if n else 0
    tot_m, tot_f = sum(men), sum(women)
    ratio = f"{tot_m/tot_f:.2f} : 1" if tot_f else "—"
    avg_teams = sum(_distinct(p.get("team","?") for p in g) for g in groups)/n if n else 0
    avg_sen = sum(_distinct(p.get("seniority","?") for p in g) for g in groups)/n if n else 0

    return (
        f":bar_chart: *Relatório dos grupos — {month_label}*\n"
        f"Grupos: *{n}* · Pessoas: *{total}*\n\n"
        f"• *Gênero* — média por grupo: *{avg_m:.1f}* homens / *{avg_f:.1f}* mulheres "
        f"(proporção geral H:M = *{ratio}*)\n"
        f"• *Times distintos* por grupo (média): *{avg_teams:.1f}*\n"
        f"• *Faixas de tempo de casa* distintas por grupo (média): *{avg_sen:.1f}*\n\n"
        f"_Obs.: gênero parcialmente inferido pelo primeiro nome quando ausente no Convenia._"
    )


def build_all(groups: list[list[dict]], artifact_url: str, month_label: str,
              token: str = SLACK_TOKEN) -> dict:
    """Retorna estrutura pronta para envio (sem enviar nada)."""
    flat = [p for g in groups for p in g]
    ids = resolve_ids(flat, token)
    dms = []
    for g in groups:
        leader = next((p for p in g if p.get("is_leader")), g[0])
        members = [p for p in g if p["id"] != leader["id"]]
        dms.append({"leader": leader, "slack_id": ids.get(leader["id"]),
                    "text": msg_dm_lider(leader, members, ids, month_label)})
    return {
        "geral": msg_geral(artifact_url, month_label),
        "lideres": msg_lideres(artifact_url, month_label),
        "dms": dms,
        "relatorio": msg_relatorio(groups, month_label),
        "unresolved": [p["name"] for p in flat if ids.get(p["id"]) is None],
    }
