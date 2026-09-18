"""
Líderes (por ID do Convenia, painel admin) e persistência do histórico.

Líderes: desde set/2026 vivem em data/leaders.json (ou LEADERS_PATH),
editados pelo painel /admin — ver mark_leaders_by_id() e CLAUDE.md seção 17.
`read_leaders_csv`/`match_leaders` continuam aqui só pra migração única a
partir da antiga planilha (Google Sheets publicado como CSV), usada pelo
endpoint POST /admin/api/leaders/import-from-sheet — não fazem mais parte
do pipeline mensal.

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



# ---- líderes por ID (painel admin) ----
# LEADERS_PATH aponta pro arquivo real (ex.: um Volume do Railway, pra
# sobreviver a redeploys — mesmo espírito de HISTORY_PATH). Sem a env var,
# cai no caminho antigo dentro do repo.
def _leaders_path(path: str | None = None) -> str:
    return path or os.environ.get("LEADERS_PATH", "../data/leaders.json")


def load_leaders(path: str | None = None) -> list[dict]:
    """Cada item: {"id": <id do Convenia>, "slack_id": opcional,
    "is_anniversary_leader": opcional} — ver group_admin.py/seção 17."""
    path = _leaders_path(path)
    if not os.path.exists(path):
        return []
    return json.load(open(path, encoding="utf-8")).get("leaders", [])


def save_leaders(leaders: list[dict], path: str | None = None) -> None:
    path = _leaders_path(path)
    json.dump({"leaders": leaders}, open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=2)


def mark_leaders_by_id(people: list[dict], leaders: list[dict]) -> tuple[list[dict], list[str]]:
    """Marca is_leader a partir da lista de líderes por ID do Convenia
    (substitui o casamento por nome/e-mail da antiga planilha — sem mais
    'ambiguous'/'not_found' por apelido, porque o ID já veio de uma escolha
    direta no painel). Retorna (people, missing_ids): missing_ids são
    líderes cadastrados que não estão elegíveis no Convenia este mês (ex.:
    desligados) e por isso não puderam ser marcados."""
    by_id = {p["id"]: p for p in people}
    for p in people:
        p["is_leader"] = False
    missing = []
    for l in leaders:
        p = by_id.get(l["id"])
        if p is None:
            missing.append(l["id"])
            continue
        p["is_leader"] = True
        if l.get("slack_id"):
            p["slack_id"] = l["slack_id"]
    return people, missing


# ---- histórico ----
# HISTORY_PATH aponta pro arquivo real (ex.: um Volume do Railway montado fora
# de /app/data, pra sobreviver a redeploys). Sem a env var, cai no caminho
# antigo dentro do repo (não persiste entre deploys sem Volume).
def _history_path(path: str | None = None) -> str:
    return path or os.environ.get("HISTORY_PATH", "../data/history.json")

def load_history(path: str | None = None) -> list[list[list[str]]]:
    path = _history_path(path)
    if not os.path.exists(path):
        return []
    return json.load(open(path, encoding="utf-8"))

def append_history(groups_ids: list[list[str]], path: str | None = None,
                   keep_last: int = 6) -> None:
    path = _history_path(path)
    hist = load_history(path)
    hist.append(groups_ids)
    hist = hist[-keep_last:]  # janela deslizante (histórico recente pesa mais mesmo)
    json.dump(hist, open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)


def replace_last_history(groups_ids: list[list[str]], path: str | None = None,
                         keep_last: int = 6) -> None:
    """Substitui a última rodada do histórico (em vez de acrescentar uma nova).
    Usado pelo painel admin: a rodada deste mês já foi registrada por
    append_history no /run?send=true; isto só corrige o snapshot pra refletir
    a composição final depois de reatribuições manuais, pra não confundir o
    cálculo de novidade do mês seguinte."""
    path = _history_path(path)
    hist = load_history(path)
    if hist:
        hist[-1] = groups_ids
    else:
        hist.append(groups_ids)
    hist = hist[-keep_last:]
    json.dump(hist, open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
