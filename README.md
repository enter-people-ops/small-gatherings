# enter · encontros — grupos mensais automáticos

Todo dia 1º do mês: busca elegíveis no Convenia (ativos + admitidos no mês),
lê a planilha de líderes, forma grupos (diversidade de gênero/time/senioridade
+ evita repetir pares do histórico, sempre ≥1 líder por grupo), gera um artefato
HTML pesquisável (com sugestões de rolê em SP) e envia 3 mensagens no Slack.

## Arquitetura (Make.com + Railway)

O algoritmo de formação não cabe nos módulos visuais do Make, então o Python
roda hospedado no Railway — que também serve o artefato na mesma URL fixa.

    Make.com (agenda dia 1º)
        │  POST /run?send=false   (header X-Run-Key)
        ▼
    Railway: serviço Python (server.py)
        ├─ GET  /        → serve data/index.html  (URL fixa mensal do artefato)
        └─ POST /run     → Convenia → planilha líderes → grupos → render → payloads
        │  devolve JSON: {general_msg, leaders_msg, dms:[{slack_id,text}], unresolved}
        ▼
    Make.com envia no Slack:
        1) msg geral (canal geral)          = general_msg
        2) msg líderes (canal de líderes)   = leaders_msg
        3) iterator dms[] → DM p/ cada líder = text
        4) (opcional) se unresolved != []   → avisa People p/ corrigir a planilha

Alternativa mais enxuta: chamar `POST /run?send=true` e deixar o próprio
Python enviar tudo; o Make só agenda e checa o status.

## Cenário no Make (passo a passo)
1. **Schedule** → mensal, dia 1, ex. 09:00 (America/Sao_Paulo).
2. **HTTP > Make a request** → POST `https://<app>.up.railway.app/run?send=false`,
   header `X-Run-Key: <RUN_KEY>`, parse response = JSON.
3. **Slack > Create a Message** → canal geral, texto = `{{general_msg}}`.
4. **Slack > Create a Message** → canal de líderes, texto = `{{leaders_msg}}`.
5. **Iterator** sobre `{{dms}}` → **Slack > Create a Message**, canal = `{{item.slack_id}}`, texto = `{{item.text}}`.
6. (Opcional) **Router**: se `length(unresolved) > 0`, posta a lista no canal do People.

## Planilha de líderes (Google Sheets publicado como CSV)
Arquivo > Compartilhar > Publicar na web > CSV. Colunas (flexível):
- `nome`     — obrigatório; casado com o nome do Convenia.
- `slack_id` — opcional; **override autoritativo** do @ (para homônimos / nomes fora do padrão).
- `email`    — opcional; ajuda o match automático.

O @ dos NÃO-líderes vem do match automático com o diretório do Slack
(`users.list`), por e-mail e nome. A planilha só precisa conter as EXCEÇÕES
que o match não resolver (aparecem em `unresolved`).

## Tamanho de grupo (sempre balanceado)
Nº de grupos (fora o do Mateus) = nº de líderes disponíveis (1 grupo por líder);
o tamanho de cada grupo é `(headcount - grupo do Mateus) / (nº de líderes - Mateus)`,
distribuído o mais uniformemente possível. Não há mais tamanho fixo configurável.

## Variáveis de ambiente (Railway)
    CONVENIA_TOKEN, SLACK_BOT_TOKEN, LEADERS_CSV_URL, ARTIFACT_URL,
    SLACK_GENERAL_CHANNEL, SLACK_LEADERS_CHANNEL, RUN_KEY,
    GROUP_MIN_WOMEN=2, EMAIL_DOMAIN=getenter.ai

Scopes do bot Slack: chat:write, users:read, users:read.email.

## Persistência do histórico
`data/history.json` é append-only com janela deslizante. No Railway, use um
**Volume** montado em `data/` (o filesystem some a cada deploy). Alternativa:
gravar o histórico numa aba da própria planilha / no Drive (conectores já ativos).

## Rodar local
    pip install -r requirements.txt
    export CONVENIA_TOKEN=... SLACK_BOT_TOKEN=... LEADERS_CSV_URL=... ARTIFACT_URL=...
    export SLACK_GENERAL_CHANNEL=C123 SLACK_LEADERS_CHANNEL=C456
    cd src && python main.py --dry-run   # gera artefato + preview das mensagens
    cd src && python main.py --send      # envia de fato e grava histórico

## Estrutura
    src/grouping.py   motor de formação (testado; núcleo)
    src/convenia.py   cliente Convenia v3 + classificação de senioridade
    src/sheets.py     líderes (CSV) + histórico
    src/slack_msgs.py match Convenia→Slack (users.list + override planilha) + 3 mensagens
    src/render.py     gera index.html a partir de groups.json + hotspots.json
    src/main.py       orquestrador (CLI --dry-run/--send + run_api p/ o servidor)
    src/server.py     Flask: GET / (artefato) e POST /run (Make)
    data/hotspots.json  sugestões de SP do mês (editável / auto-atualizável)
    Procfile          start do Railway (gunicorn)

## Identidade visual (Enter Design System)
O artefato usa os tokens oficiais do Enter UI Design System: fonte **Geist**
(auto-hospedada em `data/fonts/`), cor de marca `rgb(255,174,53)`, superfícies
claras + superfície inversa oficial, bordas como anéis inset e o logo oficial.
O servidor serve as fontes em `/fonts/<arquivo>`. Para trocar o visual, edite
apenas o bloco `:root` em `src/render.py` (mapeado 1:1 com fig-tokens.css).
