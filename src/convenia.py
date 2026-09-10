"""
Cliente Convenia (API v3) + normalização para o motor de grupos.

Auth: header `token`.  Base: https://public-api.convenia.com.br/api/v3
Padrão: lista /employees (resumo) e enriquece cada um em /employees/{id}.

Regra de elegibilidade do mês:
  incluir quem está ATIVO **ou** cuja data de admissão (hiring_date)
  cai no mês de referência.
"""
from __future__ import annotations
import os
import re
import time
import datetime as dt
from typing import Any
import requests

BASE = os.environ.get("CONVENIA_BASE", "https://public-api.convenia.com.br/api/v3")
TOKEN = os.environ.get("CONVENIA_TOKEN", "")

# ---- classificação de senioridade a partir de job.name ----------------------
_SENIORITY_RULES = [
    ("C-Level",    r"\b(ceo|cto|cfo|coo|cpo|c-level|chief)\b"),
    ("Diretoria",  r"\b(diretor|director|vp|vice)\b"),
    ("Gerência",   r"\b(gerente|manager|head|coordenador|coordinator)\b"),
    ("Lead",       r"\b(lead|líder|principal|staff)\b"),
    ("Sênior",     r"\b(s[êe]nior|sr\.?|iii)\b"),
    ("Pleno",      r"\b(pleno|pl\.?|mid|ii)\b"),
    ("Júnior",     r"\b(j[úu]nior|jr\.?|i)\b"),
    ("Estágio",    r"\b(estagi[áa]rio|intern|trainee|aprendiz)\b"),
]

def classify_tenure(hiring_date, ref=None) -> str:
    """Faixa de tempo de casa a partir da data de admissão (substitui a senioridade
    por cargo, que vinha quase toda 'N/D'). Usada na formação e no relatório."""
    import datetime as _dt
    ref = ref or _dt.date.today()
    d = None
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%Y-%m-%dT%H:%M:%S"):
        try:
            d = _dt.datetime.strptime(str(hiring_date)[:19], fmt).date(); break
        except (ValueError, TypeError):
            continue
    if not d:
        return "N/D"
    months = (ref.year - d.year) * 12 + (ref.month - d.month)
    if months < 6:   return "Novato"      # < 6 meses
    if months < 12:  return "Recente"     # 6m–1a
    if months < 24:  return "Casa"        # 1–2a
    if months < 48:  return "Veterano"    # 2–4a
    return "Antigo"                        # 4a+


def classify_seniority(job_name: str | None) -> str:
    j = (job_name or "").lower()
    for label, pat in _SENIORITY_RULES:
        if re.search(pat, j):
            return label
    return "N/D"


def _get(path: str, params: dict | None = None, token: str | None = None) -> dict:
    r = requests.get(f"{BASE}{path}",
                     headers={"token": token or TOKEN, "Accept": "application/json"},
                     params=params or {}, timeout=30)
    r.raise_for_status()
    return r.json()


def _iter_all_employees(token: str) -> list[dict]:
    """Percorre todas as páginas de /employees. Convenia costuma paginar com ?page="""
    out, page = [], 1
    while True:
        data = _get("/employees", {"page": page}, token)
        rows = data.get("data", data if isinstance(data, list) else [])
        if not rows:
            break
        out.extend(rows)
        meta = data.get("meta") or data.get("metadata") or {}
        last = meta.get("last_page") or meta.get("total_pages")
        if last and page >= last:
            break
        if not last and len(rows) == 0:
            break
        page += 1
        if page > 200:  # trava de segurança
            break
        time.sleep(0.15)
    return out


def _first_day_of_month(ref: dt.date) -> dt.date:
    return ref.replace(day=1)


def _in_reference_month(hiring_date: str | None, ref: dt.date) -> bool:
    if not hiring_date:
        return False
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%Y-%m-%dT%H:%M:%S"):
        try:
            d = dt.datetime.strptime(hiring_date[:19], fmt).date()
            return d.year == ref.year and d.month == ref.month
        except ValueError:
            continue
    return False


def fetch_eligible(token: str, ref_month: dt.date | None = None,
                   enrich: bool = True, max_workers: int = 12) -> list[dict]:
    """
    Retorna dicts normalizados: id, name, gender, team, department,
    seniority, job, hiring_date, active, email(if any).
    Inclui ATIVOS + admitidos no mês de referência.
    O enriquecimento (1 chamada por pessoa) é feito em paralelo p/ não estourar timeout.
    """
    ref = ref_month or dt.date.today()
    raw = _iter_all_employees(token)
    eligible = []
    for e in raw:
        summary = _normalize(e)
        if summary["active"] or _in_reference_month(summary["hiring_date"], ref):
            eligible.append(summary)

    if not enrich:
        return eligible

    def _enrich(summary):
        try:
            detail = _get(f"/employees/{summary['id']}", token=token)
            d = detail.get("data", detail)
            for k, v in _normalize(d).items():
                if v not in (None, "", "?"):
                    summary[k] = v
        except requests.RequestException:
            pass
        return summary

    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        eligible = list(ex.map(_enrich, eligible))
    return eligible


def _as_text(v) -> str:
    """Converte qualquer valor (str, dict aninhado, lista) em texto simples."""
    if v is None:
        return ""
    if isinstance(v, str):
        return v.strip()
    if isinstance(v, dict):
        for k in ("name", "title", "label", "value", "description", "text"):
            if v.get(k):
                return _as_text(v[k])
        return ""
    if isinstance(v, (list, tuple)):
        parts = [_as_text(x) for x in v]
        return ", ".join(p for p in parts if p)
    return str(v)


def _normalize(e: dict[str, Any]) -> dict:
    def g(*keys, default=None):
        for k in keys:
            v = e
            ok = True
            for part in k.split("."):
                if isinstance(v, dict) and part in v:
                    v = v[part]
                else:
                    ok = False; break
            if ok and v not in (None, ""):
                return v
        return default

    name = " ".join(filter(None, [_as_text(g("name")), _as_text(g("last_name"))])) \
        or _as_text(g("social_name")) or "—"
    status = _as_text(g("status", "situation", default="")).lower()
    active = g("active", default=None)
    if active is None:
        active = status in ("", "ativo", "active", "trabalhando") or "ativo" in status
    job_txt = _as_text(g("job.name", "job", "role"))
    hiring = _as_text(g("hiring_date", "admission_date", "start_date")) or None
    gender_raw = _as_text(g("gender.name", "gender", "gender_identity.name", "gender_identity")) or "?"
    if os.environ.get("INFER_GENDER", "true").lower() == "true":
        import gender_infer
        gender_raw = gender_infer.fill_gender(gender_raw, name)
    return {
        "id": str(g("id", "employee_id", "uuid", default="")),
        "name": name.strip(),
        "email": _as_text(g("email", "corporate_email", "work_email")) or None,
        "gender": gender_raw or "?",
        "team": _as_text(g("team.name", "team")) or "?",
        "department": _as_text(g("department.name", "department")) or "?",
        "job": job_txt,
        "seniority": classify_tenure(hiring),   # senioridade = faixa de tempo de casa
        "hiring_date": hiring,
        "active": bool(active),
    }
