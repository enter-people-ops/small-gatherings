"""
Motor de formação de grupos ("coffee roulette" mensal).

Objetivos (todos configuráveis por peso):
  - Cada grupo tem >= 1 líder.
  - Maximiza diversidade interna de gênero, time e senioridade.
  - Minimiza repetição de PARES que já ficaram juntos no histórico
    (penalidade maior para repetições recentes).

Abordagem: parte-se de uma semeadura (1 líder por grupo) + preenchimento
guloso randomizado, seguido de busca local por trocas (hill-climbing com
múltiplos restarts). Robusto e rápido para dezenas a algumas centenas de
pessoas.
"""
from __future__ import annotations
import random
from dataclasses import dataclass, field
from itertools import combinations
from typing import Iterable


@dataclass(frozen=True)
class Person:
    id: str
    name: str
    gender: str = "?"        # ex.: "F", "M", "Outro", "?"
    team: str = "?"          # team.name
    department: str = "?"    # department.name
    seniority: str = "?"     # derivada de job.name
    is_leader: bool = False


@dataclass
class Config:
    target_size: int = 5           # tamanho alvo (usado se size_min/max não definirem melhor)
    size_min: int = 4              # faixa aceitável de tamanho de grupo (headcount-adaptativo)
    size_max: int = 6
    # pesos das dimensões de diversidade (quanto maior, mais importa misturar)
    w_gender: float = 1.0
    w_team: float = 1.4
    w_seniority: float = 1.0
    # peso da penalidade por repetir pares do histórico
    w_history: float = 2.5
    # decaimento do histórico: uma repetição há N meses pesa recency**N
    history_recency: float = 0.6
    restarts: int = 40             # nº de reinícios aleatórios
    iterations: int = 4000         # trocas de busca local por restart
    seed: int | None = None


# ----------------------------------------------------------------------------
# Histórico: pares -> "peso de repetição" (mais recente = mais pesado)
# ----------------------------------------------------------------------------
def build_pair_penalty(history_rounds: list[list[list[str]]], recency: float) -> dict[frozenset, float]:
    """
    history_rounds: lista de rodadas, da MAIS ANTIGA para a MAIS RECENTE.
    Cada rodada é uma lista de grupos; cada grupo é uma lista de ids.
    Retorna {frozenset({a,b}): peso}. A rodada mais recente pesa 1.0,
    a anterior pesa `recency`, a anterior `recency**2`, etc.
    """
    penalty: dict[frozenset, float] = {}
    n = len(history_rounds)
    for idx, rnd in enumerate(history_rounds):
        # idx 0 = mais antiga -> expoente maior -> peso menor
        age = (n - 1) - idx
        weight = recency ** age
        for group in rnd:
            for a, b in combinations(sorted(group), 2):
                penalty[frozenset((a, b))] = penalty.get(frozenset((a, b)), 0.0) + weight
    return penalty


# ----------------------------------------------------------------------------
# Pontuação de um grupo
# ----------------------------------------------------------------------------
def _diversity(values: list[str]) -> float:
    """Fração de valores distintos (ignora '?'). 1.0 = todos diferentes."""
    known = [v for v in values if v and v != "?"]
    if len(known) <= 1:
        return 1.0
    return len(set(known)) / len(known)


def group_score(group: list[Person], cfg: Config, pair_pen: dict[frozenset, float]) -> float:
    if not group:
        return 0.0
    div = (
        cfg.w_gender * _diversity([p.gender for p in group])
        + cfg.w_team * _diversity([p.team for p in group])
        + cfg.w_seniority * _diversity([p.seniority for p in group])
    )
    hist = 0.0
    for a, b in combinations(group, 2):
        hist += pair_pen.get(frozenset((a.id, b.id)), 0.0)
    return div - cfg.w_history * hist


def total_score(groups: list[list[Person]], cfg: Config, pair_pen: dict[frozenset, float]) -> float:
    return sum(group_score(g, cfg, pair_pen) for g in groups)


# ----------------------------------------------------------------------------
# Construção e otimização
# ----------------------------------------------------------------------------
def choose_group_count(n: int, n_leaders: int, cfg: Config) -> int:
    """
    Escolhe o nº de grupos de forma adaptativa ao headcount:
      - tamanhos de grupo dentro da faixa [size_min, size_max];
      - no máximo 1 grupo por líder (cada grupo precisa de >=1 líder);
      - entre as opções válidas, prefere a que deixa os tamanhos mais próximos
        de target_size (mais equilibrados).
    """
    if n_leaders == 0:
        raise ValueError("Nenhum líder na lista de ativos — impossível garantir 1 líder por grupo.")
    lo = max(1, (n + cfg.size_max - 1) // cfg.size_max)   # menos grupos => grupos maiores
    hi = max(1, n // cfg.size_min)                        # mais grupos  => grupos menores
    hi = min(hi, n_leaders)                               # não exceder nº de líderes
    if lo > hi:                                           # faixa impossível (poucos líderes p/ a faixa)
        return max(1, min(n_leaders, round(n / cfg.target_size)) or 1)
    # dentre [lo, hi], escolhe g cujo tamanho médio fica mais perto de target_size
    return min(range(lo, hi + 1), key=lambda g: abs((n / g) - cfg.target_size))


def _n_groups(people: list[Person], cfg: Config) -> int:
    leaders = [p for p in people if p.is_leader]
    return choose_group_count(len(people), len(leaders), cfg)


def _seed(people: list[Person], g: int, rng: random.Random) -> list[list[Person]]:
    leaders = [p for p in people if p.is_leader]
    others = [p for p in people if not p.is_leader]
    rng.shuffle(leaders)
    rng.shuffle(others)
    groups: list[list[Person]] = [[leaders[i]] for i in range(g)]
    # líderes excedentes viram membros normais no pool
    pool = leaders[g:] + others
    rng.shuffle(pool)
    # preenchimento guloso: cada pessoa vai ao grupo (com vaga) que mais ganha score
    caps = _capacities(len(people), g)
    for person in pool:
        best_i, best_gain = None, float("-inf")
        for i, grp in enumerate(groups):
            if len(grp) >= caps[i]:
                continue
            gain = _marginal_gain(grp, person)
            if gain > best_gain:
                best_gain, best_i = gain, i
        if best_i is None:  # todos cheios (fallback): abre vaga no menor
            best_i = min(range(g), key=lambda i: len(groups[i]))
        groups[best_i].append(person)
    return groups


def _capacities(n: int, g: int) -> list[int]:
    base, extra = divmod(n, g)
    return [base + (1 if i < extra else 0) for i in range(g)]


def _marginal_gain(group: list[Person], person: Person) -> float:
    """Heurística leve p/ semeadura: novos valores de diversidade que a pessoa traz."""
    gain = 0.0
    for attr in ("gender", "team", "seniority"):
        vals = {getattr(p, attr) for p in group}
        if getattr(person, attr) not in vals:
            gain += 1.0
    return gain


def _has_leader(group: list[Person]) -> bool:
    return any(p.is_leader for p in group)


def optimize(people: list[Person], cfg: Config) -> tuple[list[list[Person]], float]:
    rng = random.Random(cfg.seed)
    history = getattr(cfg, "_pair_pen", {})
    g = _n_groups(people, cfg)
    best_groups, best_val = None, float("-inf")

    for _ in range(cfg.restarts):
        groups = _seed(people, g, rng)
        val = total_score(groups, cfg, history)
        # busca local: trocas entre dois grupos, aceitas se melhoram e preservam >=1 líder
        for _ in range(cfg.iterations):
            i, j = rng.randrange(g), rng.randrange(g)
            if i == j or not groups[i] or not groups[j]:
                continue
            pi, pj = rng.randrange(len(groups[i])), rng.randrange(len(groups[j]))
            a, b = groups[i][pi], groups[j][pj]
            # simula troca
            groups[i][pi], groups[j][pj] = b, a
            if not (_has_leader(groups[i]) and _has_leader(groups[j])):
                groups[i][pi], groups[j][pj] = a, b  # desfaz
                continue
            new_val = total_score(groups, cfg, history)
            if new_val >= val:
                val = new_val
            else:
                groups[i][pi], groups[j][pj] = a, b  # desfaz
        if val > best_val:
            best_val, best_groups = val, [list(g) for g in groups]

    return best_groups, best_val


def make_groups(people: list[Person],
                history_rounds: list[list[list[str]]] | None = None,
                cfg: Config | None = None) -> tuple[list[list[Person]], float]:
    cfg = cfg or Config()
    pair_pen = build_pair_penalty(history_rounds or [], cfg.history_recency)
    cfg._pair_pen = pair_pen  # type: ignore[attr-defined]
    return optimize(people, cfg)
