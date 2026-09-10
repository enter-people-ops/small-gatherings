# Enter · Encontros — contexto para o Claude Code

Automação mensal que forma grupos de integração ("coffee roulette") na Enter,
gera um artefato web pesquisável e envia mensagens no Slack. Roda no Railway,
agendada pelo Make (dia 1º às 09:00). Base: ~229 pessoas ativas.

---

## 1. O que o sistema faz (pipeline mensal)
1. Busca em `/employees` do Convenia os ATIVOS + admitidos no mês (paginado,
   enriquecido em paralelo por `/employees/{id}`).
2. Lê a planilha de líderes (Google Sheets publicado como CSV) e casa cada
   líder com um ativo do Convenia (por e-mail primeiro, depois por nome).
3. Forma os grupos respeitando as regras (seção 2).
4. Gera `data/index.html` — artefato pesquisável com a identidade visual da Enter.
5. Monta e envia no Slack: msg geral, msg de líderes, uma DM por líder e um
   relatório de conformidade das regras.

## 2. Regras de formação (decisões já tomadas)
- Cada grupo tem >=1 líder (líderes vêm da planilha).
- Mistura por **gênero**, **time** e **tempo de casa** (diversidade).
- Minimiza repetição de pares vs histórico (novidade).
- **Grupo do Mateus** (líder por e-mail `ANNIVERSARY_LEADER_EMAIL`, default
  `mateus@getenter.ai`) é SEMPRE o primeiro e reúne os **aniversariantes de casa
  do mês** (6 meses e depois qualquer aniversário anual, sem teto).
- **Líderes que fazem aniversário continuam liderando** seus grupos — NÃO são
  puxados para o grupo do Mateus (só não-líderes vão).
- **>=2 mulheres por grupo**, EXCETO o grupo do Mateus (`GROUP_MIN_WOMEN`, default 2).
- Tamanho de grupo adaptativo ao headcount (faixa `GROUP_MIN`..`GROUP_MAX`, 4–6).
  Regra de bolso: nº de líderes ≈ headcount/6 (grupos de 6) a headcount/4 (de 4–5).
  Hoje há ~22 líderes p/ 229 pessoas → grupos de ~10.

## 3. Particularidades dos dados do Convenia (aprendidas na prática)
- **E-mail corporativo NÃO vem do Convenia** — casar Slack usa `users.list`
  (e-mail exato > convenção `nome.sobrenome@getenter.ai` > tokens do nome).
- Campos como team/gender/department às vezes vêm como objeto aninhado
  (`{"name": ...}`) — `_as_text()` achata tudo para string.
- **Senioridade por cargo vinha quase toda "N/D"** → substituída por
  **faixa de tempo de casa** derivada de `hiring_date`
  (Novato <6m, Recente 6m–1a, Casa 1–2a, Veterano 2–4a, Antigo 4a+).
- **Gênero vazio no Convenia p/ ~79%** → inferido pelo primeiro nome
  (`gender_infer.py`: dicionário de nomes BR + heurística de terminação),
  só preenchendo os vazios; togglável por `INFER_GENDER`. Relatório avisa a inferência.
- Nomes na planilha de líderes costumam ser apelidos/curtos ("Banduk", "cezar",
  "Mike Mac-Vicar") — por isso o casamento é por tokens de e-mail e depois nome.

## 4. Arquitetura / arquivos
```
src/grouping.py     motor de formação (seed + busca local; testado)
src/convenia.py     cliente Convenia v3 + tempo de casa + inferência de gênero
src/gender_infer.py inferência de gênero por nome (BR)
src/sheets.py       leitura de líderes (CSV) + histórico + casamento por tokens
src/slack_msgs.py   match Convenia→Slack + 3 mensagens + relatório
src/render.py       gera index.html a partir de groups.json + hotspots.json
src/main.py         run_api (pipeline), build_groups (grupo do Mateus),
                    _send (roteamento TESTE), diagnose, work_anniversaries
src/server.py       Flask: GET / (artefato), GET /fonts, POST /run, GET /debug, GET /health
data/hotspots.json  sugestões de SP (editável manualmente por mês)
data/fonts/         Geist (auto-hospedada, identidade Enter)
data/logo-enter.svg logo oficial
Procfile            gunicorn (timeout 300, threads 4)
requirements.txt    requests, flask, gunicorn
.env.example        todas as variáveis com instruções
```

## 5. Endpoints (protegidos por header `X-Run-Key: <RUN_KEY>`)
- `GET  /`                serve o artefato do mês (URL pública fixa).
- `POST /run?send=false`  ensaio: gera tudo e devolve payloads, NÃO envia.
- `POST /run?send=true`   executa e envia pelo Slack (respeita TEST_MODE).
- `GET  /debug`           diagnóstico do casamento de líderes (rápido, sem enrich).
- `GET  /health`          `{"ok": true}`.

## 6. Variáveis de ambiente (Railway → Settings → Variables)
```
CONVENIA_TOKEN=            # Convenia > Config > API
SLACK_BOT_TOKEN=          # api.slack.com/apps > OAuth > Bot token (xoxb-)
LEADERS_CSV_URL=          # Sheets > Publicar na web > CSV
ARTIFACT_URL=            # URL pública do Railway (definir após 1º deploy)
RUN_KEY=small-gatherings-2026   # senha do header X-Run-Key
SLACK_GENERAL_CHANNEL=C0C0A6B9J2K
SLACK_LEADERS_CHANNEL=C0C0RG4EX3L
REPORT_CHANNEL=C0C0WJTSYLE       # recebe o relatório (sempre)
TEST_MODE=true                   # true = tudo vai p/ TEST_CHANNEL
TEST_CHANNEL=C0C0V7FHLHJ
ANNIVERSARY_LEADER_EMAIL=mateus@getenter.ai
GROUP_SIZE=5
GROUP_MIN=4
GROUP_MAX=6
GROUP_MIN_WOMEN=2
INFER_GENDER=true
EMAIL_DOMAIN=getenter.ai
```
Scopes do bot Slack: `chat:write`, `users:read`, `users:read.email`.

## 7. Planilha de líderes (Google Sheets → Publicar na web → CSV)
Colunas (nomes flexíveis): `nome` (obrigatório), `email` (recomendado — resolve
apelidos), `slack_id` (opcional, override definitivo do @). O `email` casa o líder
com o Convenia mesmo quando o nome é apelido. Se um líder ficar `ambiguous` (nome
curto casa com >1 pessoa), acrescente sobrenome; se `not_found`, corrija a grafia
ou ponha o slack_id.

## 8. Modo TESTE
Com `TEST_MODE=true`: msg geral + líderes + todas as DMs vão para o `TEST_CHANNEL`
(rotuladas `[TESTE]`), sem tocar a empresa; o relatório sempre vai para o
`REPORT_CHANNEL`. Virar `TEST_MODE=false` só quando for para produção.

## 9. Setup do zero (passo a passo)
1. Suba este repositório no GitHub e conecte no Railway (New Project > Deploy
   from GitHub). O Railway detecta o `Procfile`.
2. Em Variables, preencha tudo da seção 6 (menos `ARTIFACT_URL`).
3. Settings > Networking > Generate Domain → copie a URL → defina `ARTIFACT_URL`
   com ela → redeploy.
4. Publique a planilha de líderes como CSV e cole em `LEADERS_CSV_URL`.
5. Crie o app Slack, instale, copie o bot token e os IDs de canal.
6. Teste (seção 10). Quando ok, monte/ative o Make (seção 11).

Rodar local: `pip install -r requirements.txt`; copie `.env.example` -> `.env` e
preencha; `cd src && python main.py --dry-run` (ou `--send`). O `.env` é carregado
automaticamente por `_load_env()`.

## 10. Comandos de teste (curl)
```bash
BASE=https://small-gatherings-enter.up.railway.app
KEY=small-gatherings-2026

# está vivo?
curl "$BASE/health"

# diagnóstico do casamento de líderes (rápido)
curl "$BASE/debug" -H "X-Run-Key: $KEY" | python3 -m json.tool

# ensaio completo (NÃO envia) — ver grupos, relatório, unresolved, gender_distribution
curl -s -X POST "$BASE/run?send=false" -H "X-Run-Key: $KEY" | python3 -m json.tool

# só a lista de quem ficou sem @ no Slack:
curl -s -X POST "$BASE/run?send=false" -H "X-Run-Key: $KEY" \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['unresolved'])"

# envio REAL respeitando TEST_MODE (com TEST_MODE=true cai no canal de teste)
curl -X POST "$BASE/run?send=true" -H "X-Run-Key: $KEY"

# ver o artefato no navegador:
open "$BASE/"
```
Campos úteis no retorno do `/run`: `n_groups`, `score`, `test_mode`,
`anniversaries_this_month`, `gender_distribution`, `report_msg`, `unresolved`.

## 11. Agendamento no Make
Org **Enter**, team **People** (id 2265453), zona **us2.make.com**.
Cenário: **"Enter · Encontros — mensal (dia 1º)"**, id **6227802**.
- Um único módulo HTTP: POST `/run?send=true` com header `X-Run-Key`.
  (O Python faz todos os envios; o Make não precisa de conexão Slack.)
- Agendamento: monthly, dia 1, 09:00 (conferir fuso da conta = São Paulo).
- Estado atual: **INATIVO**. "Run once" testa (respeita TEST_MODE). Ativar o
  toggle só na hora de ir ao ar.
- Se trocar a `RUN_KEY` no Railway, atualize o header no módulo HTTP.

## 12. Troubleshooting (erros já enfrentados e correções)
- **500 no /run mas /health ok** → erro dentro do pipeline; ver traceback em
  Railway > Deployments > deploy ativo > View Logs.
- **`'list' object has no attribute 'strip'`** → linha da planilha com mais
  colunas que o cabeçalho; `read_leaders_csv` já ignora colunas extras.
- **`ValueError: Nenhum líder...`** → nenhum líder casou. Use `/debug`:
  `sheet_leaders_count=0` = URL não é CSV ou falta coluna `nome`;
  `unmatched`/`ambiguous` = ajustar e-mail/nome/slack_id na planilha.
- **WORKER TIMEOUT** → enriquecimento serial estourava 30s. Já corrigido:
  enrich paralelo + `Procfile` timeout 300 + `/debug` sem enrich.
- **`FileNotFoundError: hotspots.json`** → um Volume do Railway montado em
  `/app/data` escondeu os arquivos do repo. Solução aplicada: **remover o
  Volume**. (TODO: persistir histórico fora do FS efêmero, ex.: aba da planilha.)
- **`unhashable type: 'dict'`** → team/gender vinham como objeto aninhado;
  `_as_text()` já normaliza para string.
- **Gênero quase todo "?"** → campo vazio no Convenia; resolvido com inferência
  por nome (`gender_infer.py`).

## 13. Estado atual do deploy (set/2026)
- Railway: `small-gatherings-enter` no ar; volume REMOVIDO (usa `data/` do repo;
  histórico recriado a cada deploy — TODO migrar p/ persistência estável).
- Make: cenário 6227802 agendado dia 1 às 09:00, **INATIVO**.
- Último ensaio real (`send=true`, `TEST_MODE=true`): 22 grupos, gênero inferido
  ({"?":15,"F":52,"M":162}), grupo do Mateus com aniversariantes não-líderes,
  relatório OK, `sent:true` no canal de teste.

## 14. TODO / próximos passos
- Confirmar recebimento das msgs nos canais de teste.
- Resolver ~12 nomes em `unresolved` (sem @) — pôr slack_id na planilha.
- **Persistência do histórico** fora do FS efêmero do Railway (aba da planilha
  ou Drive), pra novidade vs histórico não zerar a cada deploy.
- Ir ao ar: `TEST_MODE=false` + ativar o cenário no Make.
- (Opcional) hotspots automáticos via busca; senioridade real se preencherem cargos.

## 15. Deploy
Repositório ligado ao Railway (auto-deploy no push da branch `main`).
Toda mudança em `src/` dispara redeploy automático.
