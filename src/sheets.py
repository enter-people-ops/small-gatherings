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

def _norm(s: str) -> str:
    s = "".join(c for c in unicodedata.normalize("NFKD", s or "") if not unicodedata.combining(c))
    return s.strip().lower()

def read_leaders_csv(csv_url: str) -> list[dict]:
    r = requests.get(csv_url, timeout=30); r.raise_for_status()
    rows = list(csv.DictReader(io.StringIO(r.text)))
    out = []
    for row in rows:
        low = {(_norm(k)): (v or "").strip() for k, v in row.items()}
        nome = low.get("nome") or low.get("name") or low.get("líder") or low.get("lider")
        if not nome:
            continue
        out.append({"name": nome, "email": low.get("email") or None,
                    "slack_id": low.get("slack_id") or low.get("slack") or None})
    return out

def mark_leaders(people: list[dict], leaders: list[dict]) -> list[dict]:
    """Casa líderes (por nome normalizado) com os ativos do Convenia e seta is_leader."""
    idx = {_norm(l["name"]): l for l in leaders}
    for p in people:
        l = idx.get(_norm(p["name"]))
        p["is_leader"] = l is not None
        if l:
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
