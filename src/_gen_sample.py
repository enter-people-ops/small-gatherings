import json, random, datetime as dt
from grouping import Person, Config, make_groups
import slack_msgs as S

rng = random.Random(3)
NOMES = ["Ana Souza","Bruno Lima","Carla Dias","Diego Alves","Elena Rocha","Felipe Costa",
"Gabriela Nunes","Henrique Melo","Isabela Prado","João Vieira","Karina Sá","Lucas Reis",
"Marina Teixeira","Nathan Gomes","Olívia Castro","Pedro Ramos","Queila Barros","Rafael Pinto",
"Sofia Moraes","Thiago Braga","Ursula Faria","Vitor Campos","Wanda Luz","Xavier Nobre",
"Yara Mendes","Zeca Pires","Alice Fonseca","Breno Duarte","Clara Viana","Davi Antunes",
"Erika Lopes","Fábio Guedes","Giovana Aragão","Hugo Bastos","Iris Camargo","Júlio Farias",
"Kelly Amaral","Leo Tavares","Mia Barbosa","Nina Correia","Otávio Freitas","Paula Nogueira",
"Rui Cardoso","Sara Bittencourt","Tomás Aguiar","Vera Quintana","William Sales","Zoe Martins"]
TEAMS=["Engenharia","Legal Strategy","AID","People","Finance","Produto","GTM"]
SEN=["Novato","Recente","Casa","Veterano","Antigo"]
TENURE_LABELS=["3 meses","8 meses","1 ano","1.5 anos","2 anos","3.2 anos","5 anos"]
GEN=["F","M","M","F","Outro"]

people=[]
tenure_by_id={}
for i,nome in enumerate(NOMES):
    people.append(Person(id=f"e{i:03d}",name=nome,gender=rng.choice(GEN),
        team=rng.choice(TEAMS),department=rng.choice(TEAMS),
        seniority=rng.choice(SEN),is_leader=False))
    tenure_by_id[f"e{i:03d}"]=rng.choice(TENURE_LABELS)
for idx in rng.sample(range(len(people)),9):
    p=people[idx]
    people[idx]=Person(p.id,p.name,p.gender,p.team,p.department,"Casa",True)

# histórico simulado
history=[]
for r in range(2):
    g,_=make_groups(people,history,Config(seed=r+5))
    history.append([[p.id for p in grp] for grp in g])

groups,score=make_groups(people,history,Config(seed=42,restarts=60))

# serializa para o artefato
def pdict(p):
    return {"id":p.id,"name":p.name,"gender":p.gender,"team":p.team,
            "department":p.department,"seniority":p.seniority,"is_leader":p.is_leader,
            "tenure_label":tenure_by_id[p.id]}
groups_d=[[pdict(p) for p in g] for g in groups]

month_label="Setembro/2026"
payload={"month":month_label,"generated_at":dt.date.today().isoformat(),
         "groups":groups_d}
with open("../data/groups.json","w") as f:
    json.dump(payload,f,ensure_ascii=False,indent=2)
print("groups.json salvo:",len(groups),"grupos")

# demo das mensagens (sem token -> usa fallback de nome)
msgs=S.build_all(groups_d,"https://grupos.getenter.ai","Setembro/2026",token="")
print("\n===== MSG GERAL =====\n"+msgs["geral"])
print("\n===== MSG LÍDERES =====\n"+msgs["lideres"])
print("\n===== EXEMPLO DM (1 líder) =====\n"+msgs["dms"][0]["text"])
print(f"\n(sem token Slack: {len(msgs['unresolved'])} nomes cairiam no fallback *Nome*)")
