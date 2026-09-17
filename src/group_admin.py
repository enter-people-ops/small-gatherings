"""
Painel admin: reatribuição manual de pessoas entre os grupos já formados,
CRUD das sugestões de rolê e o botão de envio real das mensagens no Slack —
tudo sem depender de rodar o pipeline (/run) de novo.

Fluxo esperado a partir de set/2026: o Make (ou um /run manual) chama
POST /run?send=false, que só GERA os grupos/artefato e NUNCA envia nada.
Um humano revisa em /admin (move/adiciona/remove pessoas, ajusta as
sugestões de rolê) e só então clica em "Enviar mensagens", que dispara
send_now() abaixo. `POST /run?send=true` continua existindo como atalho
manual (gera E envia na mesma chamada, pulando a revisão) — não é mais o
caminho usado pelo agendamento do Make (ver CLAUDE.md seção 11).
"""
from __future__ import annotations
import datetime as dt
import json, os, time

import convenia
import main as pipeline
import render
import sheets
import slack_msgs as S

_ROSTER_TTL = 60
_roster_cache: dict = {"ts": 0.0, "people": None}


# ---------------------------------------------------------------------------
# grupos
# ---------------------------------------------------------------------------
def load_groups() -> dict:
    path = pipeline.groups_path()
    if not os.path.exists(path):
        raise FileNotFoundError(
            f"Nenhum groups.json encontrado em {path}. Rode POST /run?send=false pelo menos uma vez neste mês antes de editar."
        )
    return json.load(open(path, encoding="utf-8"))


def _is_female(gender: str | None) -> bool:
    return (gender or "").strip().upper() == "F"


def _team_overrides() -> dict:
    path = "../data/team_overrides.json"
    return json.load(open(path, encoding="utf-8")) if os.path.exists(path) else {}


def _all_eligible(force: bool = False) -> list[dict]:
    """Cache curto (60s) do /employees do Convenia, pra não bater a API a
    cada tecla digitada na busca de 'adicionar pessoa' do painel."""
    now = time.time()
    if force or _roster_cache["people"] is None or now - _roster_cache["ts"] > _ROSTER_TTL:
        people = convenia.fetch_eligible(os.environ["CONVENIA_TOKEN"], dt.date.today(), enrich=False)
        convenia.apply_team_overrides(people, _team_overrides())
        _roster_cache["people"] = people
        _roster_cache["ts"] = now
    return _roster_cache["people"]


def list_roster(query: str, limit: int = 30) -> list[dict]:
    """Gente elegível no Convenia que ainda NÃO está em nenhum grupo deste
    mês — candidatos a 'adicionar' no painel. `query` é obrigatório (>=2
    caracteres) pra não devolver a base toda de uma vez."""
    query = (query or "").strip()
    if len(query) < 2:
        return []
    data = load_groups()
    existing_ids = {p["id"] for g in data["groups"] for p in g}
    q = query.lower()
    out = [p for p in _all_eligible() if p["id"] not in existing_ids and q in p["name"].lower()]
    return [{"id": p["id"], "name": p["name"], "team": p.get("team"),
             "gender": p.get("gender"), "tenure_label": p.get("tenure_label")}
            for p in out[:limit]]


def _resolve_new_people(ids: set[str]) -> dict[str, dict]:
    """Busca os dados reais (Convenia) de gente sendo ADICIONADA a um grupo
    — nunca confia em nome/gênero/time que o front mande, só no ID."""
    by_id = {p["id"]: p for p in _all_eligible(force=True)}
    missing = ids - set(by_id)
    if missing:
        raise ValueError(
            f"ID(s) desconhecido(s) ou não elegível(is) no Convenia agora: {sorted(missing)}."
        )
    picked = [dict(by_id[i], is_leader=False) for i in ids]
    slack_ids, slack_names = S.resolve_ids_and_names(picked, token=os.environ.get("SLACK_BOT_TOKEN", ""))
    for p in picked:
        if slack_ids.get(p["id"]):
            p["slack_id"] = slack_ids[p["id"]]
        if slack_names.get(p["id"]):
            p["name"] = slack_names[p["id"]]
    return {p["id"]: p for p in picked}


def _group_warnings(groups: list[list[dict]]) -> list[dict]:
    """Avisos não-bloqueantes: a edição manual é um override consciente, então
    isto só informa quando uma regra de formação (seção 2 do CLAUDE.md) ficou
    quebrada — não impede salvar. O grupo 0 (grupo do Mateus) é isento da
    regra de mínimo de mulheres, igual na formação automática."""
    min_women = int(os.environ.get("GROUP_MIN_WOMEN", "2"))
    warnings = []
    for i, g in enumerate(groups):
        issues = []
        if not g:
            issues.append("grupo vazio")
        else:
            if i != 0:
                women = sum(1 for p in g if _is_female(p.get("gender")))
                if women < min_women:
                    issues.append(f"{women} mulher(es) (mínimo {min_women})")
            if not any(p.get("is_leader") for p in g):
                issues.append("sem líder")
        if issues:
            warnings.append({"group_index": i, "issues": issues})
    return warnings


def save_assignments(assignments: dict) -> dict:
    """`assignments`: {person_id: group_index} com o estado FINAL desejado.
    IDs que já estavam nos grupos e somem daqui são removidos da rodada; IDs
    novos precisam existir no Convenia agora (ver _resolve_new_people) e
    entram como membros não-líderes."""
    data = load_groups()
    n_groups = len(data.get("groups", []))
    if n_groups == 0:
        raise ValueError("Não há grupos formados neste mês.")
    for pid, gi in assignments.items():
        if not isinstance(gi, int) or not (0 <= gi < n_groups):
            raise ValueError(f"group_index inválido para {pid}: {gi!r} (esperado 0..{n_groups - 1}).")

    by_id = {p["id"]: p for g in data["groups"] for p in g}
    existing_ids = set(by_id)
    given_ids = set(assignments)
    new_ids = given_ids - existing_ids
    removed_ids = existing_ids - given_ids

    if new_ids:
        by_id.update(_resolve_new_people(new_ids))

    new_groups: list[list[dict]] = [[] for _ in range(n_groups)]
    for pid, gi in assignments.items():
        new_groups[gi].append(by_id[pid])
    data["groups"] = new_groups

    gpath = pipeline.groups_path()
    json.dump(data, open(gpath, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    render.main(gpath, pipeline.hotspots_path(), pipeline.artifact_path())

    # só corrige o histórico se esta rodada JÁ tinha sido enviada antes desta
    # edição — se a edição acontece ANTES do primeiro envio (fluxo normal
    # agora, com o gate de aprovação), o histórico será gravado do zero em
    # send_now(), com a composição final certa.
    if data.get("sent_at"):
        sheets.replace_last_history([[p["id"] for p in g] for g in new_groups])

    return {"ok": True, "n_groups": len(new_groups), "added": sorted(new_ids),
            "removed": sorted(removed_ids), "warnings": _group_warnings(new_groups)}


# ---------------------------------------------------------------------------
# envio (gate de aprovação)
# ---------------------------------------------------------------------------
def send_now(force: bool = False) -> dict:
    """Monta as 3 mensagens a partir do groups.json ATUAL (já com as edições
    do painel) e envia de verdade pelo Slack — só isto dispara mensagens.
    Bloqueado se esta rodada já tiver sido enviada, a menos que force=True
    (evita reenvio acidental por duplo clique)."""
    data = load_groups()
    if data.get("sent_at") and not force:
        raise ValueError(
            f"Este mês já foi enviado em {data['sent_at']}. Mande force=true se quiser reenviar mesmo assim."
        )
    groups = data.get("groups") or []
    if not groups or not any(groups):
        raise ValueError("Não há ninguém nos grupos deste mês pra enviar.")

    flat = [p for g in groups for p in g]
    ids = {p["id"]: p.get("slack_id") for p in flat}
    artifact_url = os.environ.get("ARTIFACT_URL", "")
    msgs = S.build_all(groups, artifact_url, data.get("month", ""),
                       token=os.environ.get("SLACK_BOT_TOKEN", ""), ids=ids)
    test_mode = os.environ.get("TEST_MODE", "true").lower() == "true"

    pipeline._send(msgs, test_mode)
    sheets.append_history([[p["id"] for p in g] for g in groups])

    data["sent_at"] = dt.datetime.now().isoformat(timespec="seconds")
    json.dump(data, open(pipeline.groups_path(), "w", encoding="utf-8"), ensure_ascii=False, indent=2)

    return {"ok": True, "sent_at": data["sent_at"], "test_mode": test_mode,
            "unresolved": msgs["unresolved"]}


# ---------------------------------------------------------------------------
# sugestões de rolê (hotspots)
# ---------------------------------------------------------------------------
def load_hotspots() -> dict:
    path = pipeline.hotspots_path()
    if not os.path.exists(path):
        return {"items": []}
    return json.load(open(path, encoding="utf-8"))


def _clean_hotspot(it: dict) -> dict | None:
    name = (it.get("name") or "").strip()
    if not name:
        return None
    maps_url = (it.get("maps_url") or "").strip()
    if maps_url and not (maps_url.startswith("http://") or maps_url.startswith("https://")):
        raise ValueError(f"maps_url inválido em '{name}': precisa começar com http:// ou https://.")
    return {
        "cat": (it.get("cat") or "").strip() or "Outros",
        "name": name,
        "area": (it.get("area") or "").strip(),
        "note": (it.get("note") or "").strip(),
        "maps_url": maps_url,
    }


def save_hotspots(items: list) -> dict:
    if not isinstance(items, list):
        raise ValueError("'items' precisa ser uma lista.")
    cleaned = [c for c in (_clean_hotspot(it) for it in items if isinstance(it, dict)) if c]

    path = pipeline.hotspots_path()
    json.dump({"items": cleaned}, open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=2)

    # só regenera o artefato se já existir groups.json deste mês (senão não
    # há o que renderizar ainda — o hotspots pode ser editado antes do /run)
    gpath = pipeline.groups_path()
    if os.path.exists(gpath):
        render.main(gpath, path, pipeline.artifact_path())

    return {"ok": True, "n_items": len(cleaned)}
