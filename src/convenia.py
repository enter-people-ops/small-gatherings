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
                   enrich: bool = True) -> list[dict]:
    """
    Retorna dicts normalizados: id, name, gender, team, department,
    seniority, job, hiring_date, active, email(if any).
    Inclui ATIVOS + admitidos no mês de referência.
    """
    ref = ref_month or dt.date.today()
    raw = _iter_all_employees(token)
    people = []
    for e in raw:
        eid = str(e.get("id") or e.get("employee_id") or e.get("uuid"))
        summary = _normalize(e)
        # decide elegibilidade sem enriquecer, quando possível
        active = summary["active"]
        this_month = _in_reference_month(summary["hiring_date"], ref)
        if not (active or this_month):
            continue
        if enrich:
            try:
                detail = _get(f"/employees/{eid}", token=token)
                d = detail.get("data", detail)
                summary.update({k: v for k, v in _normalize(d).items() if v not in (None, "", "?")})
                time.sleep(0.1)
            except requests.HTTPError:
                pass
        people.append(summary)
    return people


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

    name = " ".join(filter(None, [g("name"), g("last_name")])) or g("social_name") or "—"
    status = (g("status", "situation", default="") or "").lower()
    active = g("active", default=None)
    if active is None:
        active = status in ("", "ativo", "active", "trabalhando") or "ativo" in status
    return {
        "id": str(g("id", "employee_id", "uuid", default="")),
        "name": name.strip(),
        "email": g("email", "corporate_email", "work_email"),  # normalmente ausente
        "gender": (g("gender", "gender_identity.name") or "?"),
        "team": (g("team.name", "team") or "?"),
        "department": (g("department.name", "department") or "?"),
        "job": g("job.name", "job", "role") or "",
        "seniority": classify_seniority(g("job.name", "job", "role")),
        "hiring_date": g("hiring_date", "admission_date", "start_date"),
        "active": bool(active),
    }
