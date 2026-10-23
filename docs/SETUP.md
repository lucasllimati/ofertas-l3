# Guia de configuração: contas, tokens, arquivos e nichos

Este guia junta tudo o que precisa ser cadastrado, gerado ou editado para o Garimpo funcionar, e onde cada coisa fica. Siga as partes na ordem na primeira vez; depois use como consulta.

- **Parte 1** – mapa: o que cada arquivo e pasta configura
- **Parte 2** – ferramentas na sua máquina
- **Parte 3** – contas e credenciais, uma a uma (como gerar, nome, onde colocar, como testar)
- **Parte 4** – onde colocar os segredos (GitHub e `.env`)
- **Parte 5** – ajustes do dia a dia (palavras-chave, horários, limites, ofertas manuais)
- **Parte 6** – adicionar um nicho novo para monitorar e depois ativá-lo
- **Parte 7** – renovar e trocar credenciais
- **Parte 8** – checklist final

> Regra de ouro: **valor de segredo nunca vai para arquivo versionado**. No repositório só ficam *nomes* de variáveis. Valores ficam nos Secrets do GitHub (produção) ou no `.env` da sua máquina, que o git ignora.

---

## Parte 1 · Mapa do projeto: onde cada coisa é configurada

| Arquivo ou pasta | O que configura | Quando mexer |
|---|---|---|
| [config/niches.yaml](../config/niches.yaml) | **Tudo dos nichos**: status, palavras-chave, filtros, horários, limites, pesos do score, canais, modelos e orçamento de LLM | Sempre que mudar nicho, palavra-chave, horário ou limite |
| [config/niches.schema.json](../config/niches.schema.json) | Schema gerado (autocompletar no editor) | Nunca à mão: rode `uv run python -m src.config.validate --write-schema` |
| `config/brands/<nicho>.json` | Cores, emoji, hashtags e nome que aparecem na arte e na legenda | Ao criar nicho ou mudar a identidade visual |
| [config/brands/base.json](../config/brands/base.json) | Marca comum (tom de voz, tagline, cores padrão, fontes) | Raramente |
| `config/offers/<nicho>.csv` | Ofertas coladas à mão (Shopee sem API, Mercado Livre, Amazon) | Sempre que quiser postar um link seu |
| [config/allowed_domains.json](../config/allowed_domains.json) | Domínios para onde os links podem apontar (pipeline e Worker) | Ao entrar uma loja nova (ex.: Magalu) |
| [.github/workflows/_run.yml](../.github/workflows/_run.yml) | Quais segredos chegam ao programa no GitHub | Ao criar nicho ativo (linha `TG_<NICHO>_CHAT_ID`) |
| [.github/workflows/daily.yml](../.github/workflows/daily.yml), [publish.yml](../.github/workflows/publish.yml), [report.yml](../.github/workflows/report.yml) | **Horários** das execuções automáticas (cron em UTC) | Ao mudar `publish_slots` no YAML |
| [docs/secrets.md](secrets.md) | Inventário dos segredos (nomes, escopo, validade) | Ao criar ou rotacionar segredo; o CI confere |
| [worker/wrangler.toml](../worker/wrangler.toml) | Ids do KV e do D1 do redirecionador `/go` | Uma vez, ao configurar a Cloudflare |
| [sql/migrations/](../sql/migrations/) | Estrutura do banco | Só ao evoluir o código |
| `.env` (você cria a partir de [.env.example](../.env.example)) | Segredos para rodar **na sua máquina** | Uso local |
| GitHub → Settings → Secrets and variables → Actions | Segredos para rodar **no GitHub Actions** | Produção |

---

## Parte 2 · Ferramentas na sua máquina

| Ferramenta | Para quê | Como instalar | Teste |
|---|---|---|---|
| Git | Versionar e enviar ao GitHub | [git-scm.com](https://git-scm.com) | `git --version` |
| Python 3.12 | Rodar o pipeline | [python.org](https://www.python.org/downloads/) | `python --version` |
| uv | Instalar dependências com lockfile | `pip install uv` | `uv --version` |
| Node.js 24 | Só para o Worker `/go` (opcional) | [nodejs.org](https://nodejs.org) | `node --version` |
| pre-commit | Bloquear segredo antes do commit | `uv tool install pre-commit` | `pre-commit --version` |

Na pasta do projeto, uma vez:

```bash
uv sync                      # cria .venv e instala tudo (Python)
pre-commit install           # ativa gitleaks e ruff antes de cada commit
uv run pytest                # deve passar tudo
uv run python -m src.run --demo --steps all   # demo sem nenhuma conta
```

---

## Parte 3 · Contas e credenciais

Cada item diz: **o que é**, **como gerar**, **nome da variável**, **onde colocar** e **como testar**. Os obrigatórios para o primeiro dia são 3.1, 3.2 e 3.3 (ou 3.4 no lugar da 3.3) e 3.8.

### 3.1 Telegram (obrigatório)

Precisa de 5 tipos de valor.

**a) Token do bot → `TELEGRAM_BOT_TOKEN`**
1. No Telegram, abra [@BotFather](https://t.me/BotFather) e envie `/newbot`.
2. Nome de exibição: `Garimpo`. Usuário: algo terminado em `bot`, ex.: `garimpo_achados_bot`.
3. O BotFather responde com o token (formato `123456789:AA...`). Guarde.
4. Recomendado: `/setjoingroups` → Disable (o bot não deve entrar em grupos de terceiros).

**b) Seu id de usuário → `TELEGRAM_ADMIN_USER_IDS`**
1. Abra [@userinfobot](https://t.me/userinfobot) e envie qualquer mensagem.
2. Copie o número em `Id` (ex.: `123456789`). Só esse(s) id(s) podem aprovar posts e mandar comandos. Mais de um admin: separe por vírgula.

**c) Chat de admin → `TELEGRAM_ADMIN_CHAT_ID`**
1. Abra o seu bot e envie `/start` (sem isso o bot não consegue te escrever).
2. No chat privado, o id do chat é **igual ao seu id de usuário**. Use o mesmo número do item b.

**d) Canais dos nichos → `TG_CASA_CHAT_ID`, `TG_PET_CHAT_ID`, ...**
1. Crie o canal: Telegram → Novo canal → público → link `t.me/garimpocasa`.
2. Canal → Administradores → Adicionar → procure o seu bot → permita **Publicar mensagens**.
3. O valor da variável é o `@` do canal: `@garimpocasa`.
4. Canal **privado**: o valor é um número `-100...`. Para descobrir, publique algo no canal e abra no navegador `https://api.telegram.org/bot<TOKEN>/getUpdates` (não compartilhe essa URL: ela contém o token). Procure `"chat":{"id":-100...`.

O nome da variável sai do `channel_ref` do nicho no YAML: `channel_ref: TG_CASA` → variável `TG_CASA_CHAT_ID`.

**e) Segredo dos botões → `APPROVAL_HMAC_SECRET`**

Gere um valor aleatório na sua máquina:

```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

**Testar:** depois de cadastrar tudo (Parte 4), rode o workflow **healthcheck** ou `uv run python -m src.run --steps healthcheck`. Deve chegar "✅ Garimpo healthcheck ok" no seu chat.

> O bot **não pode ter webhook configurado** (o sistema lê as respostas por `getUpdates`). Se aparecer erro `Conflict`, veja o [runbook](runbook.md#alertas-e-o-que-fazer).

### 3.2 Banco de dados no Supabase (obrigatório) → `DATABASE_URL`

1. Crie a conta em [supabase.com](https://supabase.com) → **New project**.
   - Nome: `garimpo` · Região: **South America (São Paulo)** · Senha do banco: gere uma forte e guarde no gerenciador de senhas.
2. Pegue a connection string: botão **Connect** → aba **Session pooler** → copie a URI. Formato:
   `postgresql://postgres.<project-ref>:<SENHA>@aws-0-sa-east-1.pooler.supabase.com:5432/postgres`
   - Use **Session pooler**. A "Direct connection" é só IPv6 e não funciona no GitHub Actions.
3. **Crie as tabelas** (uma vez, com o usuário dono), na sua máquina:
   ```bash
   # Linux/macOS/Git Bash
   DATABASE_URL="postgresql://postgres.<ref>:<SENHA>@aws-0-sa-east-1.pooler.supabase.com:5432/postgres" uv run python -m src.run --steps migrate
   ```
   ```powershell
   # PowerShell
   $env:DATABASE_URL="postgresql://postgres.<ref>:<SENHA>@aws-0-sa-east-1.pooler.supabase.com:5432/postgres"; uv run python -m src.run --steps migrate
   ```
4. **Crie o usuário do pipeline** (privilégio mínimo): Supabase → **SQL Editor** → rode:
   ```sql
   CREATE ROLE garimpo_pipeline LOGIN PASSWORD 'OUTRA-SENHA-FORTE' IN ROLE app_writer;
   ALTER ROLE garimpo_pipeline SET search_path = garimpo, public;
   ```
5. O `DATABASE_URL` de produção usa **esse** usuário. No pooler do Supabase o nome leva o `project-ref`:
   `postgresql://garimpo_pipeline.<project-ref>:OUTRA-SENHA-FORTE@aws-0-sa-east-1.pooler.supabase.com:5432/postgres`

**Testar:** healthcheck. **Futuras migrations:** rode `--steps migrate` com a URL do usuário dono (passo 3), não com a do pipeline.

### 3.3 Shopee Afiliados + Open API → `SHOPEE_APP_ID`, `SHOPEE_APP_SECRET`

1. Cadastre-se no programa de afiliados em [affiliate.shopee.com.br](https://affiliate.shopee.com.br) (CPF ou CNPJ, dados bancários para receber).
2. Com a conta aprovada, procure no painel a área **Open API** e solicite acesso. A aprovação pode levar dias, e o nome do menu pode mudar.
3. Liberado, o painel mostra o **AppID** → `SHOPEE_APP_ID` e o **Secret** → `SHOPEE_APP_SECRET`.
4. Ainda no painel, abra o **explorador/playground GraphQL** e confira se as queries `productOfferV2`, `generateShortLink` e `conversionReport` têm os campos usados em [src/sources/shopee.py](../src/sources/shopee.py) (constantes `PRODUCT_FIELDS` e `CONVERSION_FIELDS`). Se algum nome for diferente, ajuste ali.
5. Em [config/niches.yaml](../config/niches.yaml), nos nichos ativos, deixe `shopee: { mode: api, ... }`.

**Enquanto a API não sai:** troque `mode: api` por `mode: off` nos nichos **ativos** (`casa`, `pet`) e use os CSVs (3.4). Os nichos `candidate` podem ficar em `api`: sem credencial eles são pulados com um aviso, sem gerar alerta.

**Testar:** `uv run python -m src.run --steps daily --niche casa` → deve logar `ingest ok` com `offers` > 0.

### 3.4 Links manuais: Shopee (sem API), Mercado Livre e Amazon → `config/offers/<nicho>.csv`

Aqui não há token: você gera o link de afiliado no painel de cada loja e cola no CSV do nicho.

| Loja | Onde gerar o link | Formato típico |
|---|---|---|
| Shopee | Painel de afiliados → "Link personalizado"/gerador de links | `https://s.shopee.com.br/...` |
| Mercado Livre | Cadastro em [afiliados.mercadolivre.com.br](https://afiliados.mercadolivre.com.br); logado, na página do produto use "Compartilhar/Gerar link" da barra de afiliados | `https://meli.la/...` ou `mercadolivre.com/sec/...` |
| Amazon | Cadastro no [Associados Amazon](https://associados.amazon.com.br); na página do produto use a barra **SiteStripe** → Texto | `https://amzn.to/...` |

Uma linha por oferta (o cabeçalho já está no arquivo):

```csv
platform,item_id,title,price,price_original,image_url,affiliate_url,rating,reviews,sales_total,commission_rate,category
mercadolivre,MLB123,Organizador de Gaveta 6 Divisórias,39.90,59.90,https://http2.mlstatic.com/foto.jpg,https://meli.la/abc123,4.8,1200,,0.08,organização
```

- **Obrigatórios:** `platform` (`shopee`, `mercadolivre` ou `amazon`), `title`, `price`, `affiliate_url`.
- `affiliate_url` precisa ser `https` e de um domínio de [allowed_domains.json](../config/allowed_domains.json); senão a linha é ignorada (aparece no log).
- `image_url`: clique com o botão direito na foto do produto → "Copiar endereço da imagem". Sem ela, a arte sai com o selo da marca.
- `rating`, `reviews` e `commission_rate` (0.08 = 8%) melhoram o score e os filtros.
- Linhas começando com `#` são ignoradas.
- O nicho precisa ter `manual_offers: config/offers/<nicho>.csv` no YAML (casa, pet e geral-ml já têm).

Depois de editar: commit + push (o GitHub Actions lê o arquivo do repositório).

**Vendas de ML/Amazon** (não têm API de conversão aqui): exporte o relatório no painel, ajuste para estas colunas e importe:

```csv
platform,order_id,item_id,purchase_time,status,amount,commission,sub_id
mercadolivre,2000123,MLB123,2026-10-20T15:00:00+00:00,paid,39.90,3.19,casa-tg-ab12cd34ef
```

```bash
uv run python -m src.run --steps conversions --import-conversions vendas.csv
```

`sub_id` é `<sub_id do nicho>-<canal>-<id do post>`. Se não souber o id do post, use só `casa-tg`: a venda entra no nicho, sem o post.

### 3.5 Claude, opcional → `ANTHROPIC_API_KEY`

Sem esta chave, a legenda sai por template, sem erro.

1. Crie a conta em [console.anthropic.com](https://console.anthropic.com) e adicione créditos.
2. **Settings → Workspaces** → crie `garimpo` e defina um **limite de gasto mensal** (ex.: US$ 10).
3. **API Keys** → Create Key **dentro do workspace `garimpo`** → copie (começa com `sk-ant-`).
4. Modelos e tetos ficam em [config/niches.yaml](../config/niches.yaml):
   ```yaml
   global:
     llm_budget_usd_per_day: 1.00      # teto somando todos os nichos
   defaults:
     limits:
       llm_budget_usd_per_day: 0.30    # teto por nicho
     llm:
       enabled: true
       copy_model: claude-sonnet-5-5   # escreve
       review_model: claude-haiku-5-5  # revisa
   ```

**Testar:** rode `daily`. Na prévia aparece `copy LLM`, e o relatório mostra o custo do dia.

### 3.6 Cloudflare: redirecionador `/go` e cliques, opcional

Sem isto o sistema funciona: as vendas continuam atribuídas por post via `subIds` da Shopee. Você só não vê a contagem de cliques.

**a) Conta e login**
1. Crie a conta em [dash.cloudflare.com](https://dash.cloudflare.com) (plano Free).
2. Na pasta `worker/`:
   ```bash
   npm ci --ignore-scripts
   npx wrangler login
   ```

**b) KV e D1 → [worker/wrangler.toml](../worker/wrangler.toml)**
```bash
npx wrangler kv namespace create LINKS        # mostra um id → cole em kv_namespaces.id
npx wrangler d1 create garimpo-clicks         # mostra database_id → cole em d1_databases.database_id
npm run d1:schema                             # cria a tabela de cliques
npx wrangler deploy                           # publica; mostra a URL https://garimpo-go.<conta>.workers.dev
```

**c) Variáveis para o pipeline**

| Variável | Onde achar |
|---|---|
| `CF_ACCOUNT_ID` | Dashboard → **Workers & Pages** → coluna direita "Account ID" |
| `CF_KV_NAMESPACE_ID` | O id do KV (mesmo do `wrangler.toml`) |
| `CF_D1_DATABASE_ID` | O id do D1 (mesmo do `wrangler.toml`) |
| `REDIRECT_BASE_URL` | URL do deploy (`https://garimpo-go.<conta>.workers.dev`) ou `https://go.garimpo.com.br` com domínio próprio |
| `CF_API_TOKEN` | **My Profile → API Tokens → Create Token → Custom token** com só duas permissões de conta: **Workers KV Storage: Edit** e **D1: Edit**; Account Resources: só a sua conta; defina uma data de expiração |

**d) Domínio próprio (opcional):** com o domínio na Cloudflare, descomente `routes` no `wrangler.toml`, rode `npx wrangler deploy` e troque `REDIRECT_BASE_URL`.

**Testar:** depois do próximo `daily`, os links das legendas passam a ser `.../go/casa/tg/<id>`. Clique em um: deve abrir a loja. No `report`, a linha "Cliques" deixa de ser 0.

### 3.7 Domínio, opcional

Registre em [registro.br](https://registro.br) (≈ R$ 40/ano). Só é necessário para `/go` com domínio próprio e para as lojas (fase futura). Para apontar para a Cloudflare: Cloudflare → Add site → troque os servidores DNS no registro.br pelos que a Cloudflare indicar.

### 3.8 GitHub (obrigatório)

1. Crie o repositório **privado** `garimpo-engine` em [github.com/new](https://github.com/new).
2. Envie o código:
   ```bash
   git remote add origin https://github.com/<seu-usuario>/garimpo-engine.git
   git push -u origin feat/garimpo-v0.1
   ```
   Abra o PR para `main` e faça o merge. Os workflows agendados só rodam a partir da `main`.
3. **Segredos:** Settings → Secrets and variables → Actions → **New repository secret**, um por variável (lista na Parte 4).
4. **Proteção:** Settings → Branches → Add rule para `main`: exigir PR, exigir status checks (`ci`, `security`), bloquear force push.
5. **Conta:** Settings (do seu perfil) → Password and authentication → ative 2FA.
6. **Actions:** aba Actions → habilite os workflows, se pedir.
7. Rode **healthcheck** (Actions → healthcheck → Run workflow) e depois **daily**.

---

## Parte 4 · Onde colocar os segredos

### Lista completa

| Variável | Obrigatória? | Seção |
|---|---|---|
| `DATABASE_URL` | Sim | 3.2 |
| `TELEGRAM_BOT_TOKEN` | Sim | 3.1a |
| `TELEGRAM_ADMIN_USER_IDS` | Sim | 3.1b |
| `TELEGRAM_ADMIN_CHAT_ID` | Sim | 3.1c |
| `APPROVAL_HMAC_SECRET` | Sim | 3.1e |
| `TG_CASA_CHAT_ID`, `TG_PET_CHAT_ID` | Sim (um por nicho ativo) | 3.1d |
| `TG_GERAL_CHAT_ID` | Só se ativar `geral-ml` | 3.1d |
| `SHOPEE_APP_ID`, `SHOPEE_APP_SECRET` | Só com `mode: api` em nicho ativo | 3.3 |
| `ANTHROPIC_API_KEY` | Não | 3.5 |
| `CF_API_TOKEN`, `CF_ACCOUNT_ID`, `CF_KV_NAMESPACE_ID`, `CF_D1_DATABASE_ID`, `REDIRECT_BASE_URL` | Não (todas juntas) | 3.6 |

### No GitHub (produção)

Settings → Secrets and variables → Actions → New repository secret. O nome é exatamente o da tabela. Para um segredo chegar ao programa, ele também precisa estar listado em [.github/workflows/_run.yml](../.github/workflows/_run.yml) (os da tabela já estão).

### Na sua máquina (`.env`)

```bash
cp .env.example .env        # PowerShell: Copy-Item .env.example .env
```

Preencha o `.env`; ele é carregado automaticamente por `python -m src.run` e nunca vai para o git (está no `.gitignore`). Confira o que falta:

```bash
uv run python -m src.config.validate --check-secrets
```

A saída mostra só os **nomes** que faltam, nunca valores.

### Registre no inventário

Para cada segredo cadastrado, preencha "Criado em" e "Expira em" em [docs/secrets.md](secrets.md). O `security.yml` avisa 7 dias antes de expirar.

---

## Parte 5 · Ajustes do dia a dia

Todos em [config/niches.yaml](../config/niches.yaml), salvo indicação. Depois de editar: `uv run python -m src.config.validate`, commit e push.

| Quero... | Onde | Exemplo |
|---|---|---|
| Mudar palavras-chave de um nicho | `niches[].platforms.shopee.keywords` | `[mop giratório, porta temperos]` |
| Coletar mais ou menos produtos por palavra | `niches[].platforms.shopee.limit_per_keyword` (1–50) | `30` |
| Mais ou menos posts por dia | `limits.new_content_per_day` (criados) e `limits.posts_per_day.telegram` (publicados) | `5` e `8` |
| Faixa de preço | `filters.price_min` / `filters.price_max` no nicho | `15` / `400` |
| Exigir nota/comissão mínima | `defaults.filters.min_rating`, `min_commission_rate` | `4.5`, `0.05` |
| Bloquear um tipo de produto | `filters.blocked_categories` no nicho (soma às dos defaults; sem diferença de acento) | `[vermífugo]` |
| Mudar o peso do ranking | `defaults.score_weights` ou por nicho | `commission: 0.30` |
| Explorar mais produtos novos | `exploration_rate` (0 a 1) | `0.30` |
| Não repetir produto por mais tempo | `global.repost_cooldown_days` | `14` |
| Aprovação automática num nicho maduro | `approval: auto_above_score` + `auto_approve_min_score` no nicho | `0.80` |
| Mudar horários de publicação | `publish_slots` **e** o cron de [publish.yml](../.github/workflows/publish.yml) (ver abaixo) | `["09:07", "18:07"]` |
| Mudar cores/emoji/hashtags | `config/brands/<nicho>.json` | `"accent": "#1F8A7A"` |
| Permitir links de outra loja | [config/allowed_domains.json](../config/allowed_domains.json) | `"magazineluiza.com.br"` |
| Pausar um canal na hora | Telegram: `/pausar casa telegram` (volta com `/retomar`) | — |
| Pausar um nicho de vez | `status: paused` no nicho | — |

**Horários: YAML e cron precisam combinar.** `publish_slots` está no horário de Brasília; o cron do GitHub está em **UTC** (Brasília + 3h). Se trocar os slots para `09:07` e `18:07`, o `publish.yml` fica:

```yaml
schedule:
  - cron: "7 12,21 * * *"   # 09:07 e 18:07 BRT
```

Slot depois das 21:00 BRT cai no dia seguinte em UTC (21:07 BRT = `7 0 * * *`). O `daily` (coleta) deve rodar antes do primeiro slot: hoje é 05:07 BRT (`7 8 * * *` em [daily.yml](../.github/workflows/daily.yml)).

---

## Parte 6 · Adicionar um nicho novo

O nicho entra em duas etapas: primeiro **candidate** (só coleta e ranqueia, sem posts, sem segredo novo) e, quando os números forem bons, **active**.

### 6.1 Monitorar (status `candidate`)

**1. Adicione o bloco** no fim da lista `niches:` em [config/niches.yaml](../config/niches.yaml). Exemplo para papelaria:

```yaml
  - id: papelaria                 # minúsculas, números e hífen; 2–20 caracteres; único
    name: Garimpo Papelaria       # nome que aparece nos relatórios e na arte
    status: candidate             # só monitora
    platforms:
      shopee:
        mode: api
        limit_per_keyword: 30
        keywords: [caderno inteligente, caneta gel, planner 2027, marca texto pastel]
    filters: { price_min: 10, price_max: 150 }
    tracking: { sub_id: papelaria }   # só [a-z0-9], 2–20, único (vai no link da Shopee)
```

Regras: `id` e `sub_id` não podem repetir os de outro nicho; qualquer campo de `defaults` (filtros, limites, pesos) pode ser sobrescrito dentro do nicho.

**2. Valide e regenere o schema:**

```bash
uv run python -m src.config.validate --write-schema
uv run pytest tests/test_config.py
```

**3. Commit + push** (PR para `main`). A partir do próximo `daily`, o nicho é coletado e ranqueado.

**4. Acompanhe:**
- No Telegram: `/top papelaria` mostra os 10 melhores produtos do dia.
- No banco (Supabase → SQL Editor):
  ```sql
  SELECT * FROM garimpo.v_daily_niche WHERE niche_id = 'papelaria' ORDER BY run_date DESC;
  ```

Candidato precisa da **API da Shopee** (`mode: api`) para ter dados. Sem a credencial, ele é pulado com aviso. Com `manual_offers`, ele também coleta do CSV.

**Quando promover:** compare com os ativos por pelo menos 2 semanas: produtos elegíveis, vendas em 7 dias (`sales_7d` em `product_score.components`) e comissão média. Critério sugerido em [ARQUITETURA.md](../ARQUITETURA.md): crescimento de vendas e comissão média acima dos nichos ativos.

### 6.2 Ativar (status `active`)

1. **Canal no Telegram:** crie `@garimpopapelaria`, adicione o bot como admin com permissão de publicar (3.1d).
2. **Complete o bloco do nicho:**
   ```yaml
     - id: papelaria
       name: Garimpo Papelaria
       status: active
       platforms:
         shopee:
           mode: api
           keywords: [caderno inteligente, caneta gel, planner 2027, marca texto pastel]
       manual_offers: config/offers/papelaria.csv
       filters: { price_min: 10, price_max: 150 }
       store: { subdomain: papelaria, brand: config/brands/papelaria.json }
       channels:
         telegram: { channel_ref: TG_PAPELARIA, enabled: true }
         instagram: { account_ref: IG_PAPELARIA, enabled: false }
         tiktok: { account_ref: TIKTOK_PAPELARIA, enabled: false }
       competitors:
         instagram: []
       tracking: { sub_id: papelaria }
   ```
3. **Marca:** crie `config/brands/papelaria.json` (copie `pet.json` e troque nome, cores, emoji e hashtags).
4. **Ofertas manuais (opcional):** copie `config/offers/casa.csv` para `config/offers/papelaria.csv` e apague as linhas de exemplo.
5. **Segredo:** no GitHub crie `TG_PAPELARIA_CHAT_ID` = `@garimpopapelaria`.
6. **Workflow:** em [.github/workflows/_run.yml](../.github/workflows/_run.yml), no bloco `env`, adicione:
   ```yaml
          TG_PAPELARIA_CHAT_ID: ${{ secrets.TG_PAPELARIA_CHAT_ID }}
   ```
7. **Inventário:** adicione a linha de `TG_PAPELARIA_CHAT_ID` em [docs/secrets.md](secrets.md) (o CI falha se faltar).
8. **Valide:**
   ```bash
   uv run python -m src.config.validate --write-schema
   uv run python scripts/check_secrets_inventory.py
   uv run pytest
   ```
   O teste `test_repo_config_is_valid` lista os nichos ativos esperados: atualize-o para incluir `papelaria`.
9. **Commit + PR + merge.** Rode **daily** manualmente para ver as primeiras prévias.

> Minutos do GitHub Actions: cada nicho ativo soma ≈ 30–60 min/mês. Com 2.000 min grátis, cabem com folga 8–10 nichos.

---

## Parte 7 · Renovar e trocar credenciais

| Credencial | Validade | Onde gerar a nova | Onde atualizar |
|---|---|---|---|
| `TELEGRAM_BOT_TOKEN` | Não expira | @BotFather → `/revoke` (gera outro e invalida o antigo) | GitHub secret + `.env` |
| `APPROVAL_HMAC_SECRET` | Não expira | `python -c "import secrets; print(secrets.token_urlsafe(32))"` | GitHub secret + `.env` (prévias pendentes perdem os botões; expiram em 72 h) |
| `DATABASE_URL` (senha) | Não expira | Supabase SQL Editor: `ALTER ROLE garimpo_pipeline PASSWORD '...'` | GitHub secret + `.env` |
| `SHOPEE_APP_SECRET` | Ver painel | Painel de afiliados → Open API → regenerar | GitHub secret + `.env` |
| `ANTHROPIC_API_KEY` | Até você revogar | Console → API Keys → criar nova, depois apagar a antiga | GitHub secret + `.env` |
| `CF_API_TOKEN` | A data que você definiu | Cloudflare → API Tokens → **Roll** | GitHub secret + `.env` |

Depois de trocar: rode o **healthcheck** e atualize as datas em [docs/secrets.md](secrets.md). Rotação recomendada: a cada 90 dias. Vazou alguma? Siga [runbook.md → Vazamento de chave](runbook.md#vazamento-de-chave): **revogue primeiro**, depois troque.

---

## Parte 8 · Checklist final

- [ ] `uv sync`, `pre-commit install`, `uv run pytest` ok
- [ ] Bot criado, `/start` enviado, bot admin dos canais `@garimpocasa` e `@garimpopet`
- [ ] Supabase criado, `--steps migrate` rodado, usuário `garimpo_pipeline` criado
- [ ] Shopee: `mode: api` com AppID/Secret **ou** `mode: off` + CSV com ofertas nos nichos ativos
- [ ] Repositório privado, código na `main`, 2FA e proteção de branch ativos
- [ ] Segredos obrigatórios cadastrados (Parte 4) e datas em `docs/secrets.md`
- [ ] Workflow **healthcheck** verde e mensagem recebida no Telegram
- [ ] Workflow **daily** rodado e prévias aprovadas
- [ ] Workflow **publish** publicou nos canais
- [ ] (Opcional) `ANTHROPIC_API_KEY` com limite de gasto
- [ ] (Opcional) Worker `/go` publicado e variáveis `CF_*` + `REDIRECT_BASE_URL` cadastradas
