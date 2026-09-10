import random
from itertools import combinations
from grouping import Person, Config, make_groups, build_pair_penalty

rng = random.Random(7)
TEAMS = ["Engenharia", "Legal Strategy", "AID", "People", "Finance", "Produto", "GTM"]
SEN = ["Estagiário", "Júnior", "Pleno", "Sênior", "Staff", "Lead", "Manager"]
GEN = ["F", "M", "M", "F", "Outro"]  # leve desbalanceamento realista

def synth(n=48, n_leaders=9):
    people = []
    for i in range(n):
        people.append(Person(
            id=f"e{i:03d}", name=f"Pessoa {i:03d}",
            gender=rng.choice(GEN), team=rng.choice(TEAMS),
            department=rng.choice(TEAMS), seniority=rng.choice(SEN),
            is_leader=False))
    # marca líderes (garante distribuídos)
    for idx in rng.sample(range(n), n_leaders):
        p = people[idx]
        people[idx] = Person(p.id, p.name, p.gender, p.team, p.department,
                             rng.choice(["Lead", "Manager", "Sênior"]), True)
    return people

def repeated_pairs(groups, pair_pen):
    rep = 0; total = 0
    for g in groups:
        for a, b in combinations(g, 2):
            total += 1
            if frozenset((a.id, b.id)) in pair_pen:
                rep += 1
    return rep, total

def diversity_report(groups):
    def frac(vals):
        v = [x for x in vals if x and x != "?"]
        return len(set(v))/len(v) if len(v) > 1 else 1.0
    gd = sum(frac([p.gender for p in g]) for g in groups)/len(groups)
    td = sum(frac([p.team for p in g]) for g in groups)/len(groups)
    sd = sum(frac([p.seniority for p in g]) for g in groups)/len(groups)
    return gd, td, sd

people = synth()
print(f"Pessoas: {len(people)} | Líderes: {sum(p.is_leader for p in people)}")

# --- simula 3 rodadas históricas anteriores + a nova ---
history = []
for r in range(3):
    cfg = Config(seed=r+10)
    groups, _ = make_groups(people, history, cfg)
    history.append([[p.id for p in g] for g in groups])

# rodada nova, considerando as 3 anteriores
cfg = Config(seed=99, restarts=60, iterations=5000)
groups, score = make_groups(people, history, cfg)

print(f"\nGrupos formados: {len(groups)} | tamanhos: {[len(g) for g in groups]}")
print(f"Todos com líder? {all(any(p.is_leader for p in g) for g in groups)}")
print(f"Todos alocados 1x? {sum(len(g) for g in groups)==len(people) and len({p.id for g in groups for p in g})==len(people)}")

gd, td, sd = diversity_report(groups)
print(f"\nDiversidade média (0-1, maior=melhor): gênero={gd:.2f} time={td:.2f} senioridade={sd:.2f}")

pen = build_pair_penalty(history, cfg.history_recency)
rep, total = repeated_pairs(groups, pen)
print(f"Pares repetidos do histórico: {rep}/{total} ({100*rep/total:.1f}%)")

# baseline aleatório p/ comparar
def random_groups(people, g):
    pool = people[:]; rng.shuffle(pool)
    caps = [len(people)//g + (1 if i < len(people)%g else 0) for i in range(g)]
    out, k = [], 0
    for c in caps:
        out.append(pool[k:k+c]); k += c
    return out
rg = random_groups(people, len(groups))
rgd, rtd, rsd = diversity_report(rg)
rrep, rtotal = repeated_pairs(rg, pen)
print(f"\n[baseline aleatório] diversidade gênero={rgd:.2f} time={rtd:.2f} sen={rsd:.2f} | repetidos={100*rrep/rtotal:.1f}%")

print("\nExemplo de 2 grupos:")
for g in groups[:2]:
    for p in g:
        tag = " (LÍDER)" if p.is_leader else ""
        print(f"  - {p.name}: {p.gender} | {p.team} | {p.seniority}{tag}")
    print()
