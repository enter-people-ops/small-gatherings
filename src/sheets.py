"""
Leitura da planilha de líderes e persistência do histórico.

Líderes: planilha Google publicada como CSV (Arquivo > Compartilhar >
Publicar na web > CSV) OU via Sheets API. Colunas esperadas (flexível):
  - nome        (obrigatório; casado com o nome do Convenia)
  - email       (opcional; ajuda no mapeamento Slack)
  - slack_id    (opcional; mapeamento Slack mais confiável)

Histórico: JSON append-only (data/history.json) — cada rodada é uma lista
de grupos (listas de ids). Da mais antiga para a mais recente.
"""
from __future__ import annotations
import csv, io, json, os, unicodedata
import requests

def _norm(s) -> str:
    s = "".join(c for c in unicodedata.normalize("NFKD", str(s or "")) if not unicodedata.combining(c))
    return s.strip().lower()

def read_leaders_csv(csv_url: str) -> list[dict]:
    r = requests.get(csv_url, timeout=30); r.raise_for_status()
    rows = list(csv.DictReader(io.StringIO(r.text)))
    out = []
    for row in rows:
        low = {}
        for k, v in row.items():
            if k is None:            # colunas extras além do cabeçalho (restkey)
                continue
            if isinstance(v, list):  # célula sobrando vira lista -> junta como texto
                v = " ".join(str(x) for x in v)
            low[_norm(k)] = str(v or "").strip()
        nome = low.get("nome") or low.get("name") or low.get("líder") or low.get("lider")
        if not nome:
            continue
        out.append({"name": nome, "email": low.get("email") or None,
                    "slack_id": low.get("slack_id") or low.get("slack") or None})
    return out

def _tokens(name: str) -> set:
    """Tokens normalizados do nome (hífen/ponto contam como separador)."""
    n = _norm(name).replace("-", " ").replace(".", " ")
    return {t for t in n.split() if t}


def _email_tokens(email: str) -> set:
    """Tokens da parte local do e-mail (antes do @): normalmente nome.sobrenome."""
    if not email or "@" not in email:
        return set()
    local = email.split("@", 1)[0]
    for sep in (".", "_", "-", "+"):
        local = local.replace(sep, " ")
    return {t for t in _norm(local).split() if t and not t.isdigit()}


def match_leaders(people: list[dict], leaders: list[dict]) -> dict:
    """
    Casa cada líder com um ativo do Convenia (nome completo) por SUBCONJUNTO de
    tokens. Tenta primeiro pelos tokens do E-MAIL (nome.sobrenome, mais confiável
    que apelido), depois pelo NOME da planilha. Único candidato => casa.
    Retorna {nome_planilha: {"id", "status": ok|ambiguous|not_found, "via", ...}}.
    """
    ppl = [(p, _tokens(p["name"])) for p in people]

    def unique_subset(keys: set):
        cands = [p for p, pt in ppl if keys and keys <= pt]
        return cands

    out = {}
    for l in leaders:
        tried_ambiguous = False
        result = None
        for via, keys in (("email", _email_tokens(l.get("email") or "")),
                          ("nome", _tokens(l["name"]))):
            if not keys:
                continue
            cands = unique_subset(keys)
            if len(cands) == 1:
                result = {"id": cands[0]["id"], "status": "ok", "via": via, "leader": l}
                break
            if len(cands) > 1:
                tried_ambiguous = True
                amb = {"id": None, "status": "ambiguous", "via": via, "leader": l,
                       "candidates": [c["name"] for c in cands][:5]}
        if result is None:
            result = amb if tried_ambiguous else {"id": None, "status": "not_found", "leader": l}
        out[l["name"]] = result
    return out


def mark_leaders(people: list[dict], leaders: list[dict]) -> list[dict]:
    """Casa líderes com os ativos do Convenia e seta is_leader + slack_id/email."""
    by_id = {p["id"]: p for p in people}
    matches = match_leaders(people, leaders)
    for p in people:
        p["is_leader"] = False
    for m in matches.values():
        if m["status"] == "ok" and m["id"] in by_id:
            p = by_id[m["id"]]
            p["is_leader"] = True
            l = m["leader"]
            if l.get("slack_id"): p["slack_id"] = l["slack_id"]
            if l.get("email"): p["email"] = l["email"]
    return people

# ---- histórico ----
def load_history(path: str = "../data/history.json") -> list[list[list[str]]]:
    if not os.path.exists(path):
        return []
    return json.load(open(path, encoding="utf-8"))

def append_history(groups_ids: list[list[str]], path: str = "../data/history.json",
                   keep_last: int = 6) -> None:
    hist = load_history(path)
    hist.append(groups_ids)
    hist = hist[-keep_last:]  # janela deslizante (histórico recente pesa mais mesmo)
    json.dump(hist, open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
