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


def match_by_name(people: list[dict], directory: list[dict]) -> dict[str, str | None]:
    """Casa Convenia->Slack por e-mail (se houver) e por nome normalizado."""
    by_email = {_strip_accents(u["email"]).lower(): u["id"] for u in directory if u["email"]}
    by_name = {}
    for u in directory:
        for key in (u["real_name"], u["display_name"]):
            if key:
                by_name.setdefault(_strip_accents(key).lower().strip(), u["id"])
    out = {}
    for p in people:
        sid = None
        em = (p.get("email") or "").lower()
        if em and _strip_accents(em) in by_email:
            sid = by_email[_strip_accents(em)]
        if not sid:
            sid = by_name.get(_strip_accents(p["name"]).lower().strip())
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


def mention(p: dict, ids: dict[str, str | None]) -> str:
    sid = ids.get(p["id"])
    return f"<@{sid}>" if sid else f"*{p['name']}*"


# ---------------------------------------------------------------------------
# As 3 mensagens
# ---------------------------------------------------------------------------
def msg_geral(artifact_url: str, month_label: str) -> str:
    return (
        f":coffee: *Grupos de {month_label} estão no ar!*\n"
        f"Todo mês formamos grupos novos pra galera se misturar entre times e senioridades. "
        f"Descubra o seu grupo, quem são os colegas e sugestões de rolê pra marcarem:\n"
        f":point_right: {artifact_url}\n\n"
        f"É só pesquisar seu nome. Bom encontro! :sparkles:"
    )


def msg_lideres(artifact_url: str, month_label: str) -> str:
    return (
        f":busts_in_silhouette: *Líderes de {month_label} — vocês conduzem o encontro deste mês!*\n"
        f"Cada um de vocês recebeu (na DM) a lista do seu grupo com os @ de todos. Passo a passo:\n"
        f"1. Crie um *canal ou grupo no Slack* com as pessoas do seu grupo.\n"
        f"2. Proponham 2–3 opções de data/horário e *fechem um encontro* (café, almoço, happy hour…).\n"
        f"3. Precisando de ideias de lugar, tem sugestões no artefato: {artifact_url}\n\n"
        f"Meta: todo mundo reunido pelo menos uma vez até o fim do mês. Valeu! :rocket:"
    )


def msg_dm_lider(lider: dict, membros: list[dict], ids: dict[str, str | None],
                 month_label: str) -> str:
    linhas = "\n".join(f"• {mention(m, ids)} — {m.get('team','?')} / {m.get('seniority','?')}"
                       for m in membros)
    return (
        f"Oi {mention(lider, ids)}! :wave: Você é o líder de um grupo em *{month_label}*.\n"
        f"Seu grupo:\n{linhas}\n\n"
        f"Sugestão: cria um grupo no Slack com todo mundo e propõe um encontro. Qualquer dúvida, chama o People. :coffee:"
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
        "unresolved": [p["name"] for p in flat if ids.get(p["id"]) is None],
    }
