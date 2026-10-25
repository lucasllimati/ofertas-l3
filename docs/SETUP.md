# Guia completo de configuração

Passo a passo para criar **todas** as contas, credenciais e configurações do Garimpo, do zero até o primeiro post publicado. Cada seção diz o que é, como criar, qual nome usar, onde colocar e como testar.

Repositório: `lucasllimati/ofertas-l3` (privado).

## Sumário

| # | Seção | Obrigatório? | Tempo |
|---|---|---|---|
| 0 | [Visão geral e ordem](#0-visão-geral-e-ordem) | — | 2 min |
| 1 | [Critérios de segurança](#1-critérios-de-segurança-leia-antes) | Sim | 10 min |
| 2 | [Ferramentas na sua máquina](#2-ferramentas-na-sua-máquina) | Sim | 10 min |
| 3 | [GitHub](#3-github) | Sim | 10 min |
| 4 | [Telegram: bot, ids e canais](#4-telegram-bot-ids-e-canais) | Sim | 15 min |
| 5 | [Banco de dados (Supabase)](#5-banco-de-dados-supabase) | Sim | 15 min |
| 6 | [Shopee Afiliados e Open API](#6-shopee-afiliados-e-open-api) | Sim (API ou links manuais) | 10 min + análise da Shopee |
| 7 | [Mercado Livre Afiliados](#7-mercado-livre-afiliados) | Não | 10 min |
| 8 | [Amazon Associados](#8-amazon-associados) | Não | 10 min |
| 9 | [Claude (Anthropic)](#9-claude-anthropic) | Não | 5 min |
| 10 | [Cloudflare: redirecionador e cliques](#10-cloudflare-redirecionador-e-cliques) | Não | 20 min |
| 11 | [Domínio](#11-domínio) | Não | 10 min |
| 12 | [Cadastrar os segredos](#12-cadastrar-os-segredos) | Sim | 5 min |
| 13 | [Primeira execução](#13-primeira-execução) | Sim | 10 min |
| 14 | [Mapa de arquivos de configuração](#14-mapa-de-arquivos-de-configuração) | Consulta | — |
| 15 | [Ajustes do dia a dia](#15-ajustes-do-dia-a-dia) | Consulta | — |
| 16 | [Adicionar um nicho novo](#16-adicionar-um-nicho-novo) | Consulta | — |
| 17 | [Renovar e trocar credenciais](#17-renovar-e-trocar-credenciais) | Consulta | — |
| 18 | [Problemas comuns](#18-problemas-comuns) | Consulta | — |
| 19 | [Checklist final](#19-checklist-final) | Sim | — |

---

## 0. Visão geral e ordem

```
Você (Telegram) ◄── prévias e relatório ──┐
       │ aprovar                           │
       ▼                                   │
GitHub Actions (garimpo.yml) ── lê/grava ──► Supabase (Postgres)
       │        │
       │        └── busca ofertas ──► Shopee Open API  (ou CSV com links da Shopee/ML/Amazon)
       │
       └── publica ──► Canais do Telegram ──► clique ──► loja ──► venda ──► comissão
                                     (opcional: passa pelo Worker /go na Cloudflare para contar cliques)
```

**Ordem recomendada** (cada etapa depende da anterior): segurança → ferramentas → GitHub → Telegram → Supabase → Shopee (ou CSV) → segredos → primeira execução. Mercado Livre, Amazon, Claude, Cloudflare e domínio podem vir depois.

**Mínimo para rodar hoje:** Telegram + Supabase + GitHub + ofertas em CSV (enquanto a API da Shopee não sai).

---

## 1. Critérios de segurança (leia antes)

Estas regras valem para todas as seções. O sistema mexe com dinheiro (comissões) e com canais públicos: um token vazado permite que outra pessoa publique golpes no seu canal.

### 1.1 Regras de ouro

1. **Valor de segredo nunca vai para arquivo versionado.** No repositório ficam só *nomes* de variáveis. Valores ficam nos Secrets do GitHub (produção) ou no `.env` da sua máquina (o git ignora esse arquivo).
2. **Nunca cole token em:** chat, issue, PR, commit, print de tela, planilha compartilhada, e-mail ou mensagem para "suporte".
3. **Nunca rode `echo` de segredo** em terminal gravado nem em workflow.
4. **Menor permissão possível:** cada token só com o escopo necessário (cada seção diz qual).
5. **Tudo com validade e rotação:** registre criação e expiração em [docs/secrets.md](secrets.md) e troque a cada 90 dias.
6. **Vazou? Revogue primeiro**, investigue depois ([runbook](runbook.md#vazamento-de-chave)).

### 1.2 Contas

| Item | O que fazer |
|---|---|
| Gerenciador de senhas | Use um (Bitwarden, 1Password, KeePassXC). Guarde **todas** as senhas e tokens deste guia lá, um item por credencial |
| E-mail | Use um e-mail com 2FA ativo. Opcional: um e-mail dedicado ao projeto (ex.: `garimpo.achados@...`) para cadastros de afiliado e newsletters |
| 2FA em tudo | GitHub, Supabase, Cloudflare, Anthropic, Shopee, Mercado Livre, Amazon, e-mail. Prefira app autenticador (não SMS) |
| Telegram | Ative a **Verificação em duas etapas** (Configurações → Privacidade e Segurança → Verificação em duas etapas). Quem invadir seu Telegram consegue aprovar posts |
| Senhas | Mínimo de 16 caracteres, geradas pelo gerenciador, uma por serviço |

### 1.3 Como gerar valores aleatórios seguros

```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

Use para `APPROVAL_HMAC_SECRET` e para as senhas do banco.

### 1.4 O que o próprio projeto já faz

- `gitleaks` no pre-commit e no CI bloqueia token no git.
- Logs mascaram tokens e senhas automaticamente.
- Botões de aprovação são assinados (HMAC); só o seu usuário do Telegram aprova.
- Banco: usuário do pipeline sem permissão de criar/apagar tabelas; RLS em todas as tabelas; schema fora da API pública do Supabase.
- Links só podem apontar para domínios permitidos ([config/allowed_domains.json](../config/allowed_domains.json)).

Detalhes: [SECURITY.md](../SECURITY.md).

---

## 2. Ferramentas na sua máquina

| Ferramenta | Para quê | Instalar | Testar |
|---|---|---|---|
| Git | Versionar e enviar ao GitHub | [git-scm.com](https://git-scm.com) | `git --version` |
| Python 3.12 | Rodar o pipeline | [python.org](https://www.python.org/downloads/) (marque "Add to PATH") | `python --version` |
| uv | Dependências Python com lockfile | `pip install uv` | `uv --version` |
| GitHub CLI | Cadastrar secrets e rodar workflows pelo terminal | [cli.github.com](https://cli.github.com) e depois `gh auth login` | `gh auth status` |
| Node.js 24 | Só para o Worker da Cloudflare (seção 10) | [nodejs.org](https://nodejs.org) | `node --version` |
| pre-commit | Bloquear segredo antes do commit | `uv tool install pre-commit` (passo abaixo) | `pre-commit --version` |

O `pre-commit` não vem com o projeto: instale uma vez como ferramenta do `uv`:

```powershell
uv tool install pre-commit
pre-commit --version          # deve mostrar a versão, ex.: pre-commit 4.7.0
```

Se aparecer "O termo 'pre-commit' não é reconhecido", a pasta de ferramentas do `uv` não está no PATH. Rode `uv tool update-shell`, **feche e abra o terminal** e teste de novo. A pasta é a que `uv tool dir --bin` mostra (no Windows, `C:\Users\<você>\.local\bin`).

Na pasta do projeto, uma vez:

```bash
uv sync                                       # instala dependências
pre-commit install                            # ativa gitleaks e ruff antes de cada commit
pre-commit run --all-files                    # primeira vez: baixa os ganchos (alguns minutos); tudo deve dar Passed
uv run pytest                                 # todos os testes devem passar
uv run python -m src.run --demo --steps all   # demo sem nenhuma conta; veja out/demo/
uv run python -m src.doctor --offline         # o que falta configurar (ver abaixo)
```

### 2.1 Assistente de verificação (`doctor`)

Rode a qualquer momento do setup, quantas vezes quiser. Ele testa cada peça separadamente e diz qual seção deste guia resolve cada falha. Não publica nada, não altera o banco e nunca mostra valores de segredo.

```powershell
uv run python -m src.doctor                        # tudo (usa a rede: Telegram, banco, Shopee, Claude, Cloudflare, GitHub)
uv run python -m src.doctor --only telegram,banco  # só alguns grupos
uv run python -m src.doctor --offline              # só o que não usa rede
```

Exemplo de saída:

```
✅ telegram · bot: @garimpo_achados_bot
❌ telegram · canal pet: TG_PET_CHAT_ID: o bot não é admin com 'Publicar mensagens' em @garimpopet → SETUP §4.3
⚠️  banco · usuário: esta URL é do DONO (pode alterar tabelas). No GitHub use a do garimpo_pipeline → SETUP §5.4
⏭  claude · API: opcional: sem chave a copy sai do template

Resumo: 9 ok · 1 avisos · 1 falhas · 3 pulados
Comece por: telegram · canal pet (SETUP §4.3)
```

Grupos: `config`, `segredos`, `telegram`, `banco`, `shopee`, `claude`, `cloudflare`, `monitor`, `github`. Termina com código 1 se houver falha (dá para usar em script).

---

## 3. GitHub

O repositório `lucasllimati/ofertas-l3` já existe. Confira:

1. **Privado:** Settings → General → Danger Zone → deve estar "Private".
2. **2FA na sua conta:** foto do perfil → Settings → Password and authentication → Two-factor authentication.
3. **Actions habilitado:** aba **Settings do repositório** (engrenagem no topo, na linha de Code/Issues/Pull requests; não é o Settings do seu perfil) → menu da esquerda, grupo **Code and automation** → **Actions** → **General** → "Allow all actions and reusable workflows" (ou "Allow actions created by GitHub" + as listadas no repositório). O projeto fixa todas as actions por SHA.
4. **Permissão padrão do token do Actions:** na mesma página (Settings → Actions → General), role **até o fim** → seção **Workflow permissions** → **Read repository contents and packages permissions** (o padrão mais seguro; os workflows já declaram o que precisam). Deixe desmarcado "Allow GitHub Actions to create and approve pull requests". Conferir pelo terminal:
   ```powershell
   gh api repos/lucasllimati/ofertas-l3/actions/permissions/workflow
   # esperado: "default_workflow_permissions":"read", "can_approve_pull_request_reviews":false
   ```
5. **Apagar branch após merge:** Settings → General → Pull Requests → "Automatically delete head branches" (já ativado).
6. **Proteção da `main`:** em repositório privado exige **GitHub Pro** (US$ 4/mês); no plano Free o GitHub recusa. Com Pro: Settings → Rules → Rulesets → New branch ruleset → branch padrão → marque *Restrict deletions*, *Block force pushes*, *Require a pull request* (0 aprovações) e *Require status checks*: `python`, `worker`, `scan`. **Sem Pro:** faça tudo por PR e só faça merge com os 3 checks verdes.
7. **Dependabot:** já configurado em [.github/dependabot.yml](../.github/dependabot.yml). Ele abre PRs às segundas; faça merge quando os 3 checks estiverem verdes.

Os segredos são cadastrados na [seção 12](#12-cadastrar-os-segredos), depois de criar todas as contas.

---

## 4. Telegram: bot, ids e canais

São 5 tipos de valor.

| Variável | O que é | Exemplo |
|---|---|---|
| `TELEGRAM_BOT_TOKEN` | Senha do bot | `123456789:AAH...` |
| `TELEGRAM_ADMIN_USER_IDS` | Seu id numérico (quem pode aprovar) | `123456789` |
| `TELEGRAM_ADMIN_CHAT_ID` | Chat onde chegam prévias e alertas | `123456789` (igual ao seu id) |
| `TG_CASA_CHAT_ID`, `TG_PET_CHAT_ID` | Canais de cada nicho | `@garimpocasa` |
| `APPROVAL_HMAC_SECRET` | Chave que assina os botões | 43 caracteres aleatórios |

### 4.1 Criar o bot → `TELEGRAM_BOT_TOKEN`

1. No Telegram, abra [@BotFather](https://t.me/BotFather) (confira o selo azul de verificado).
2. Envie `/newbot`.
3. **Nome de exibição:** `Garimpo`.
4. **Usuário:** precisa terminar em `bot`, ex.: `garimpo_achados_bot`.
5. O BotFather responde com o token (`123456789:AA...`). **Guarde no gerenciador de senhas** e não mande para ninguém.
6. Endureça o bot:
   - `/setjoingroups` → escolha o bot → **Disable** (não deixa ninguém pôr o bot em grupos).
   - `/setprivacy` → **Enable**.
7. Opcional, menu de comandos: `/setcommands` → escolha o bot → envie:
   ```
   status - fila de conteúdo por nicho
   top - 10 melhores produtos de um nicho (ex.: /top casa)
   pausar - pausa um canal (ex.: /pausar casa telegram)
   retomar - retoma um canal (ex.: /retomar casa telegram)
   cupons - cupons válidos agora
   mercado - qual nicho ativar a seguir
   horarios - melhores horários de um nicho (ex.: /horarios casa)
   imposto - imposto estimado do mês (ex.: /imposto 2026-10)
   fechamento - fechamento do mês com CSV para o contador
   ```

> Quem tem o token controla o bot e publica nos seus canais. Se vazar: `/revoke` no BotFather na hora (seção 17).

### 4.2 Seu id → `TELEGRAM_ADMIN_USER_IDS` e `TELEGRAM_ADMIN_CHAT_ID`

1. Abra o **seu bot** (procure pelo usuário criado) e envie `/start`. Sem isso o bot não pode te escrever.
2. Abra [@userinfobot](https://t.me/userinfobot) e envie qualquer mensagem.
3. Copie o número em **Id**, por exemplo `123456789`.
4. Use esse número nas duas variáveis:
   - `TELEGRAM_ADMIN_USER_IDS` = `123456789` (mais de um admin: `123456789,987654321`)
   - `TELEGRAM_ADMIN_CHAT_ID` = `123456789` (o chat privado com o bot tem o mesmo id que você)

### 4.3 Canais dos nichos → `TG_CASA_CHAT_ID`, `TG_PET_CHAT_ID`

Repita para cada nicho ativo (`casa` e `pet`):

1. Telegram → lápis/menu → **Novo canal**.
2. Nome: `Garimpo Casa`. Descrição: algo como "Achadinhos de casa e cozinha com preço bom. Contém links de afiliado."
3. Tipo **Público**, link `t.me/garimpocasa` (o Telegram avisa se o nome estiver ocupado).
4. No canal → nome do canal → **Administradores** → **Adicionar administrador** → procure o seu bot → deixe só **Publicar mensagens** (e "Editar mensagens", se quiser) → Salvar.
5. Valor da variável: `TG_CASA_CHAT_ID` = `@garimpocasa`.

**Canal privado** (sem @): o valor é um número que começa com `-100`. Para descobrir:
1. Publique qualquer mensagem no canal.
2. Rode na sua máquina (o token fica só na variável, não aparece na tela):
   ```powershell
   # PowerShell
   $env:TELEGRAM_BOT_TOKEN = Read-Host "token"
   $url = "https://api.telegram.org/bot$env:TELEGRAM_BOT_TOKEN/getUpdates?allowed_updates=%5B%22channel_post%22%5D"
   (Invoke-RestMethod $url).result | ForEach-Object { $_.channel_post.chat } | Select-Object id, title -Unique
   ```
   O parâmetro `allowed_updates` é necessário: o Garimpo pede ao Telegram só mensagens e botões, e o Telegram guarda esse filtro. A próxima execução do Garimpo restaura o filtro dele.
3. Use o `id` (ex.: `-1001234567890`). Se a lista vier vazia, publique outra mensagem no canal e rode de novo.

O nome da variável sai do `channel_ref` do nicho em [config/niches.yaml](../config/niches.yaml): `channel_ref: TG_CASA` → `TG_CASA_CHAT_ID`.

### 4.4 Segredo dos botões → `APPROVAL_HMAC_SECRET`

```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

Guarde o resultado. Se trocar no futuro, os botões das prévias pendentes deixam de valer (elas expiram em 72 h de qualquer forma).

### 4.5 Testar o bot

```powershell
# PowerShell: deve mostrar o usuário do bot
(Invoke-RestMethod "https://api.telegram.org/bot$env:TELEGRAM_BOT_TOKEN/getMe").result
```

> **Não configure webhook no bot.** O Garimpo lê as respostas por `getUpdates`; com webhook o Telegram devolve erro 409 `Conflict`.

---

## 5. Banco de dados (Supabase)

Postgres gerenciado e grátis. São criados **dois usuários**: o dono (só na sua máquina, para criar tabelas) e o do pipeline (no GitHub, sem permissão de criar ou apagar tabelas).

### 5.1 Criar o projeto

1. Acesse [supabase.com](https://supabase.com) → **Start your project** → entre com o GitHub ou e-mail.
2. Ative o 2FA: avatar → Account preferences → Security → Multi-factor authentication.
3. **New project:**
   - Organization: a sua (plano Free).
   - Name: `garimpo`.
   - Database Password: gere com o gerenciador (16+ caracteres, **sem** `@`, `:`, `/`, `?`, `#`, para não precisar escapar na URL). Esta é a **senha do dono**.
   - Region: **South America (São Paulo)**.
4. Aguarde ~2 minutos até o projeto ficar verde.

### 5.2 Pegar a connection string

1. No projeto, botão **Connect** (topo da página).
2. Aba **Connection string** → tipo **URI** → modo **Session pooler**.
3. Copie. Formato:
   ```
   postgresql://postgres.<project-ref>:<SENHA_DO_DONO>@aws-0-sa-east-1.pooler.supabase.com:5432/postgres
   ```
   - `<project-ref>` é o código do projeto (aparece na URL do painel).
   - Use **Session pooler**. A "Direct connection" é só IPv6 e não funciona no GitHub Actions.

> **Atalho para 5.3 e 5.4:** depois de 5.1 e 5.2, rode `uv run python scripts/bootstrap_db.py`. Ele pede a URL do dono (a digitação não aparece), aplica as migrations, cria o usuário `garimpo_pipeline` com uma senha aleatória forte, testa que ele lê as tabelas e **não** consegue alterá-las, e grava a `DATABASE_URL` do pipeline no seu `.env`. A senha não aparece na tela. Para trocar a senha depois: `--rotate`. Os passos manuais abaixo continuam valendo se preferir.

### 5.3 Criar as tabelas (uma vez, como dono)

Na pasta do projeto:

```powershell
# PowerShell
$env:DATABASE_URL = Read-Host "URL do dono (session pooler)"
uv run python -m src.run --steps migrate
Remove-Item Env:DATABASE_URL
```

```bash
# Git Bash / Linux / macOS
read -rs DATABASE_URL && export DATABASE_URL
uv run python -m src.run --steps migrate
unset DATABASE_URL
```

O log deve mostrar `migrate ok` com as migrations aplicadas (`0001_core.sql`, `0002_security.pg.sql` e as seguintes). Isso cria o schema `garimpo`, as tabelas, os papéis `app_writer` e `app_reader`, as views de relatório e liga o RLS em todas as tabelas.

**Atualização do projeto com migration nova** (ex.: `0005_agents.sql`): repita este passo como dono depois do merge. O usuário do pipeline não altera tabelas, de propósito; se houver migration pendente, a execução para antes de fazer qualquer coisa e o alerta no Telegram diz exatamente isso ("migration pendente: ... rode migrate com a URL do dono").

### 5.4 Criar o usuário do pipeline → `DATABASE_URL`

1. Gere outra senha forte (sem `@ : / ? #`).
2. Supabase → **SQL Editor** → New query → cole e rode (troque a senha):
   ```sql
   CREATE ROLE garimpo_pipeline LOGIN PASSWORD 'SENHA_DO_PIPELINE' IN ROLE app_writer;
   ALTER ROLE garimpo_pipeline SET search_path = garimpo, public;
   ```
3. Monte o `DATABASE_URL` de produção. No pooler, o usuário leva o `project-ref`:
   ```
   postgresql://garimpo_pipeline.<project-ref>:SENHA_DO_PIPELINE@aws-0-sa-east-1.pooler.supabase.com:5432/postgres
   ```
4. Guarde as duas URLs no gerenciador, identificando **dono** e **pipeline**. Só a do **pipeline** vai para o GitHub.

### 5.5 Endurecer o Supabase

| Onde | O que fazer | Por quê |
|---|---|---|
| Project Settings → API (ou Data API) | Confirme que `garimpo` **não** está em "Exposed schemas". Se não usa a API REST para nada, desative a Data API | As tabelas não devem ser acessíveis pela API pública |
| Project Settings → API Keys | Nunca use nem copie a `service_role` para este projeto | Ela ignora RLS |
| — | **O plano Free não faz backup automático.** O projeto faz um backup semanal próprio, criptografado (seção [12.5](#125-backup-semanal--backup_passphrase)) | Recuperar vendas e histórico |
| Organization → Members | Só você | — |

### 5.6 Testar

```powershell
$env:DATABASE_URL = Read-Host "URL do pipeline"
uv run python -c "from src.common.db import Database; import os; print(Database(os.environ['DATABASE_URL']).scalar('SELECT count(*) FROM content_item'))"
```

Deve imprimir `0`. Para conferir que o usuário do pipeline **não** consegue criar tabelas:

```powershell
uv run python -c "from src.common.db import Database; import os; Database(os.environ['DATABASE_URL']).execute('CREATE TABLE garimpo.x (a int)')"
```

Deve dar erro `InsufficientPrivilege`, e é isso que se quer.

> Projetos Free pausam após 7 dias sem uso. O `daily` roda todo dia e evita isso. Se pausar, reative no painel.

---

## 6. Shopee Afiliados e Open API

A Shopee é a fonte principal: com a API, o sistema busca ofertas sozinho, gera o link de afiliado de cada post e importa as vendas.

### 6.1 Cadastro no programa de afiliados

1. Acesse [affiliate.shopee.com.br](https://affiliate.shopee.com.br) e entre com sua conta Shopee (crie uma se não tiver; ative o 2FA na conta).
2. Preencha o cadastro de afiliado: dados pessoais (CPF) ou da empresa (CNPJ), redes sociais onde vai divulgar (informe os canais do Telegram e, depois, Instagram/TikTok) e dados para receber.
3. Aguarde a aprovação (e-mail da Shopee).

### 6.2 Pedir acesso à Open API → `SHOPEE_APP_ID`, `SHOPEE_APP_SECRET`

1. No painel de afiliados, procure a área **Open API** (o nome do menu pode variar; também costuma estar em "Ferramentas").
2. Solicite o acesso, descrevendo o uso: busca de ofertas, geração de links com sub IDs e relatório de conversões para canais próprios. A análise pode levar dias.
3. Liberado, o painel mostra:
   - **AppID** → `SHOPEE_APP_ID`
   - **Secret** → `SHOPEE_APP_SECRET` (trate como senha; guarde no gerenciador)
4. **Confira os campos no explorador/playground GraphQL** do painel. O código usa as queries `productOfferV2`, `generateShortLink` e `conversionReport`, com os campos listados em [src/sources/shopee.py](../src/sources/shopee.py) (constantes `PRODUCT_FIELDS` e `CONVERSION_FIELDS`). Se algum nome for diferente no explorador, ajuste ali e rode `uv run pytest tests/test_shopee.py`.

### 6.3 Configurar no projeto

Em [config/niches.yaml](../config/niches.yaml), nos nichos ativos:

```yaml
    platforms:
      shopee:
        mode: api                 # api = usa a Open API
        limit_per_keyword: 30     # produtos por palavra-chave (1–50)
        keywords: [organizador cozinha, porta temperos, mop giratório]
```

Os sub IDs que vão no link (nicho, canal, post) são montados automaticamente a partir de `tracking.sub_id`.

### 6.4 Enquanto a API não sai: links manuais

1. Em [config/niches.yaml](../config/niches.yaml), troque `mode: api` por `mode: off` em `casa` e `pet`. Os nichos `candidate` podem ficar em `api`: sem credencial eles são pulados com aviso, sem alerta.
2. No painel de afiliados da Shopee, use o gerador de link (**Link personalizado** ou similar): cole o link do produto e copie o link de afiliado (`https://s.shopee.com.br/...`).
3. Cole no CSV do nicho (formato na [seção 7.3](#73-formato-do-csv-de-ofertas-vale-para-shopee-ml-e-amazon)), com `platform` = `shopee`.

### 6.5 Testar

Depois de cadastrar os segredos (seção 12):

```bash
uv run python -m src.run --steps daily --niche casa
```

O log deve ter `ingest ok` com `offers` maior que 0 e `content ok` com `created` maior que 0.

---

## 7. Mercado Livre Afiliados

O Mercado Livre não tem, neste projeto, API de geração de link de afiliado: você gera o link no painel e cola no CSV. As vendas entram por CSV exportado do painel.

### 7.1 Cadastro

1. Procure **"Programa de Afiliados Mercado Livre"** (página oficial do Mercado Livre) e entre com sua conta (ative o 2FA em Minha conta → Segurança).
2. Complete o cadastro: dados pessoais ou de empresa, canais de divulgação (informe os canais do Telegram) e dados de pagamento.
3. Aguarde a aprovação.

### 7.2 Gerar o link de afiliado

1. Logado como afiliado, abra a página do produto no Mercado Livre.
2. Use a **barra de afiliados** (aparece no topo da página) → **Compartilhar / Gerar link**.
3. Copie o link curto (`https://meli.la/...` ou `https://mercadolivre.com/sec/...`).
4. Escolha produtos com muitas vendas, boa reputação do vendedor e nota alta.

### 7.3 Formato do CSV de ofertas (vale para Shopee, ML e Amazon)

Arquivo: `config/offers/<nicho>.csv` (ex.: [config/offers/casa.csv](../config/offers/casa.csv)). Uma oferta por linha; o cabeçalho já existe:

```csv
platform,item_id,title,price,price_original,image_url,affiliate_url,rating,reviews,sales_total,commission_rate,category
mercadolivre,MLB123,Organizador de Gaveta 6 Divisórias,39.90,59.90,https://http2.mlstatic.com/foto.jpg,https://meli.la/abc123,4.8,1200,,0.08,organização
```

| Coluna | Obrigatória | Como preencher |
|---|---|---|
| `platform` | Sim | `shopee`, `mercadolivre` ou `amazon` |
| `item_id` | Não | Código do anúncio (ex.: `MLB123`). Vazio = gerado a partir do link |
| `title` | Sim | Nome curto e claro do produto |
| `price` | Sim | Preço atual (`39.90` ou `39,90`) |
| `price_original` | Não | Preço "de" (riscado). Só preencha se for real |
| `image_url` | Não | Botão direito na foto do produto → "Copiar endereço da imagem" (precisa ser `https`) |
| `affiliate_url` | Sim | Link de afiliado gerado no painel (`https`, domínio permitido) |
| `rating` | Não | Nota (0 a 5) |
| `reviews` | Não | Número de avaliações |
| `sales_total` | Não | Vendidos (ajuda no ranking) |
| `commission_rate` | Não | Comissão do produto: `0.08` = 8% |
| `category` | Não | Texto livre (usado nos filtros de categoria bloqueada) |

- Linhas começando com `#` são ignoradas.
- Link fora de [allowed_domains.json](../config/allowed_domains.json) ou sem `https` é descartado (aparece no log).
- Depois de editar: commit + push (o GitHub Actions lê o arquivo do repositório).

### 7.4 Importar vendas do Mercado Livre

1. No painel de afiliados, exporte o relatório de vendas/comissões (CSV).
2. Ajuste para estas colunas:
   ```csv
   platform,order_id,item_id,purchase_time,status,amount,commission,sub_id
   mercadolivre,2000123,MLB123,2026-10-20T15:00:00+00:00,paid,39.90,3.19,casa-tg
   ```
   Valores aceitam vírgula decimal e `R$` (`"R$ 39,90"`); datas em ISO ou `dd/mm/aaaa [hh:mm]` (horário de Brasília). Se uma linha estiver inválida, nada é importado e o erro diz o número da linha.
   `sub_id` = `<sub_id do nicho>-<canal>`, e opcionalmente `-<id do post>` (ex.: `casa-tg-ab12cd34ef`). O id do post aparece no link `/go` ou na tabela `content_item`.
3. Importe:
   ```bash
   uv run python -m src.run --steps conversions --import-conversions vendas-ml.csv
   ```

---

## 8. Amazon Associados

1. Cadastre-se em [associados.amazon.com.br](https://associados.amazon.com.br) com sua conta Amazon (ative o 2FA em Sua conta → Login e segurança).
2. Preencha site/canais (informe os canais do Telegram), perfil e dados fiscais e de pagamento.
3. **Atenção às regras do programa:** a Amazon exige vendas qualificadas nos primeiros meses para manter a conta e para liberar a API de produtos. Até lá, use links manuais.
4. **Gerar link:** logado, abra o produto na Amazon → barra **SiteStripe** (topo) → **Obter link** → **Texto** → link curto `https://amzn.to/...`.
5. Cole no CSV do nicho com `platform` = `amazon` ([seção 7.3](#73-formato-do-csv-de-ofertas-vale-para-shopee-ml-e-amazon)).
6. Vendas: exporte o relatório do painel e importe como na [seção 7.4](#74-importar-vendas-do-mercado-livre), com `platform` = `amazon`.

---

## 9. Claude (Anthropic)

Opcional. Sem a chave, a legenda sai de um template, sem erro. Com ela, o Claude Sonnet escreve o título e os bullets e o Claude Haiku revisa. Preço, link e avisos legais são sempre montados pelo código.

1. Crie a conta em [console.anthropic.com](https://console.anthropic.com) e ative o 2FA.
2. **Billing:** adicione créditos (US$ 5 a 10 duram bastante: cerca de US$ 0,01 por post).
3. **Settings → Workspaces → Create workspace** → nome `garimpo` → defina um **limite de gasto mensal** (ex.: US$ 10).
4. **API Keys → Create Key** → escolha o workspace **`garimpo`** → nome `garimpo-actions` → copie a chave (`sk-ant-...`, mostrada uma única vez) → `ANTHROPIC_API_KEY`.
5. Tetos e modelos em [config/niches.yaml](../config/niches.yaml):
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
6. **Testar:** rode `daily`. Na prévia aparece `copy LLM`, e o relatório da noite mostra "Custo de LLM hoje".

---

## 10. Cloudflare: redirecionador e cliques

Opcional. Sem isto, as vendas continuam atribuídas a cada post pelos sub IDs da Shopee; você só não vê a contagem de cliques. Com isto, os links das legendas viram `https://.../go/casa/tg/<id>`: o Worker conta o clique (sem IP) e redireciona para a loja.

### 10.1 Conta e login

1. Crie a conta em [dash.cloudflare.com](https://dash.cloudflare.com) (plano Free) e ative o 2FA (My Profile → Authentication).
2. Na pasta `worker/`:
   ```bash
   cd worker
   npm ci --ignore-scripts
   npx wrangler login        # abre o navegador para autorizar
   ```

### 10.2 Criar KV e D1 e publicar o Worker

```bash
npx wrangler kv namespace create LINKS      # mostra um id    → cole em kv_namespaces.id no wrangler.toml
npx wrangler d1 create garimpo-clicks       # mostra database_id → cole em d1_databases.database_id
npm run d1:schema                           # cria a tabela de cliques no D1
npm test                                    # testes do redirecionador
npx wrangler deploy                         # publica; mostra https://garimpo-go.<sua-conta>.workers.dev
```

Arquivo editado: [worker/wrangler.toml](../worker/wrangler.toml). Os ids de KV e D1 não são segredos, mas são da sua conta; por isso o repositório fica privado.

**Testar:** abra `https://garimpo-go.<sua-conta>.workers.dev/health`. Deve responder `ok`.

### 10.3 Token de API e variáveis

| Variável | Onde achar |
|---|---|
| `CF_ACCOUNT_ID` | Dashboard → **Workers & Pages** → coluna da direita, "Account ID" |
| `CF_KV_NAMESPACE_ID` | O mesmo id do KV colocado no `wrangler.toml` |
| `CF_D1_DATABASE_ID` | O mesmo id do D1 colocado no `wrangler.toml` |
| `REDIRECT_BASE_URL` | URL do deploy (`https://garimpo-go.<conta>.workers.dev`) ou `https://go.garimpo.com.br` com domínio próprio |
| `CF_API_TOKEN` | Ver abaixo |

**Criar o `CF_API_TOKEN` (permissão mínima):**
1. My Profile → **API Tokens** → **Create Token** → **Create Custom Token**.
2. Nome: `garimpo-pipeline`.
3. Permissões (tipo **Account**):
   - `Workers KV Storage` → **Edit**
   - `D1` → **Edit**
4. Account Resources: **Include → sua conta** (só ela).
5. TTL: defina uma **data de expiração** (ex.: 90 dias) e anote em [docs/secrets.md](secrets.md).
6. Opcional: Client IP Address Filtering fica vazio (os IPs do GitHub Actions mudam).
7. **Continue to summary → Create Token** → copie (mostrado uma única vez).

**Testar:** depois do próximo `daily`, a legenda usa o link `/go`. Clique: deve abrir a loja. No relatório da noite, "Cliques" deixa de ser 0.

---

## 11. Domínio

Opcional. Só é necessário para `/go` com domínio próprio e, no futuro, para as lojas.

1. Verifique e registre em [registro.br](https://registro.br) (ex.: `garimpo.com.br`, ≈ R$ 40/ano). Ative o 2FA na conta do registro.br.
2. Na Cloudflare: **Add a domain** → plano Free → anote os 2 nameservers indicados.
3. No registro.br: domínio → **DNS** → **Alterar servidores DNS** → coloque os da Cloudflare. A propagação pode levar algumas horas.
4. No [worker/wrangler.toml](../worker/wrangler.toml), descomente:
   ```toml
   routes = [{ pattern = "go.garimpo.com.br", custom_domain = true }]
   ```
5. `npx wrangler deploy` e troque o secret `REDIRECT_BASE_URL` para `https://go.garimpo.com.br`.

---

## 12. Cadastrar os segredos

### 12.1 Lista completa

| Variável | Obrigatória? | Seção |
|---|---|---|
| `DATABASE_URL` (usuário do **pipeline**) | Sim | [5.4](#54-criar-o-usuário-do-pipeline--database_url) |
| `TELEGRAM_BOT_TOKEN` | Sim | [4.1](#41-criar-o-bot--telegram_bot_token) |
| `TELEGRAM_ADMIN_USER_IDS` | Sim | [4.2](#42-seu-id--telegram_admin_user_ids-e-telegram_admin_chat_id) |
| `TELEGRAM_ADMIN_CHAT_ID` | Sim | [4.2](#42-seu-id--telegram_admin_user_ids-e-telegram_admin_chat_id) |
| `APPROVAL_HMAC_SECRET` | Sim | [4.4](#44-segredo-dos-botões--approval_hmac_secret) |
| `TG_CASA_CHAT_ID`, `TG_PET_CHAT_ID` | Sim (um por nicho ativo) | [4.3](#43-canais-dos-nichos--tg_casa_chat_id-tg_pet_chat_id) |
| `TG_GERAL_CHAT_ID` | Só ao ativar `geral-ml` | [4.3](#43-canais-dos-nichos--tg_casa_chat_id-tg_pet_chat_id) |
| `SHOPEE_APP_ID`, `SHOPEE_APP_SECRET` | Só com `mode: api` em nicho ativo | [6.2](#62-pedir-acesso-à-open-api--shopee_app_id-shopee_app_secret) |
| `BACKUP_PASSPHRASE` | Recomendado (sem ele o backup semanal não roda) | [12.5](#125-backup-semanal--backup_passphrase) |
| `ANTHROPIC_API_KEY` | Não | [9](#9-claude-anthropic) |
| `CF_API_TOKEN`, `CF_ACCOUNT_ID`, `CF_KV_NAMESPACE_ID`, `CF_D1_DATABASE_ID`, `REDIRECT_BASE_URL` | Não (todas juntas) | [10.3](#103-token-de-api-e-variáveis) |
| `HEARTBEAT_URL` | Recomendado (avisa se o sistema parar) | [13.2](#132-aviso-de-o-sistema-parou--heartbeat_url) |
| `GARIMPO_REHEARSAL` (*variable*, não secret) | Só na primeira semana | [13.1](#131-modo-ensaio-primeira-semana) |

### 12.2 No GitHub (produção)

**Do `.env` para o GitHub de uma vez** (recomendado): preencha o `.env` (12.3) e rode

```powershell
uv run python scripts/push_secrets.py --dry-run   # mostra o que vai enviar (só nomes)
uv run python scripts/push_secrets.py             # pede confirmação e envia
```

Ele só envia nomes do projeto, recusa a URL do **dono** do banco e valores de exemplo, manda cada valor pela entrada padrão do `gh` (nunca aparece na tela nem no histórico) e preenche as datas em [docs/secrets.md](secrets.md) (faça commit depois). Para enviar só alguns: `--only TELEGRAM_BOT_TOKEN,TG_CASA_CHAT_ID`. Confira no fim com `uv run python -m src.doctor --only github`.

**Um por um pelo terminal** (o valor é digitado escondido e não fica no histórico):

```bash
gh secret set DATABASE_URL            --repo lucasllimati/ofertas-l3
gh secret set TELEGRAM_BOT_TOKEN      --repo lucasllimati/ofertas-l3
gh secret set TELEGRAM_ADMIN_USER_IDS --repo lucasllimati/ofertas-l3
gh secret set TELEGRAM_ADMIN_CHAT_ID  --repo lucasllimati/ofertas-l3
gh secret set APPROVAL_HMAC_SECRET    --repo lucasllimati/ofertas-l3
gh secret set TG_CASA_CHAT_ID         --repo lucasllimati/ofertas-l3
gh secret set TG_PET_CHAT_ID          --repo lucasllimati/ofertas-l3
# quando tiver:
gh secret set SHOPEE_APP_ID           --repo lucasllimati/ofertas-l3
gh secret set SHOPEE_APP_SECRET       --repo lucasllimati/ofertas-l3
gh secret set ANTHROPIC_API_KEY       --repo lucasllimati/ofertas-l3
gh secret set BACKUP_PASSPHRASE       --repo lucasllimati/ofertas-l3
gh secret set HEARTBEAT_URL           --repo lucasllimati/ofertas-l3   # seção 13.2
gh secret list                        --repo lucasllimati/ofertas-l3   # confere os nomes (nunca mostra valores)
```

**Pelo site:** Settings → Secrets and variables → Actions → **New repository secret** → Name exatamente como na tabela → Secret → Add secret.

Para chegar ao programa, cada segredo também precisa estar no bloco `env` de [.github/workflows/garimpo.yml](../.github/workflows/garimpo.yml). Os da tabela já estão. O projeto não usa `secrets: inherit`: cada segredo é passado pelo nome, e o CI recusa `secrets: inherit`.

### 12.3 Na sua máquina (`.env`)

```powershell
Copy-Item .env.example .env     # Git Bash: cp .env.example .env
```

Preencha o `.env`. Ele é carregado automaticamente por `python -m src.run` e nunca vai para o git (está no `.gitignore`; o gitleaks também bloqueia). Confira o que falta:

```bash
uv run python -m src.config.validate --check-secrets
```

A saída mostra só os **nomes** que faltam.

### 12.4 Registrar no inventário

Para cada segredo, preencha "Criado em" e "Expira em" (AAAA-MM-DD) em [docs/secrets.md](secrets.md). O `security.yml` falha 7 dias antes da expiração, para lembrar de rotacionar.

### 12.5 Backup semanal → `BACKUP_PASSPHRASE`

O Supabase Free **não** guarda backup. Todo domingo às 03:17 (Brasília), o workflow exporta o histórico (vendas, cliques, posts, auditoria, produtos e scores), criptografa com AES-256 usando esta senha e guarda o arquivo `.gpg` como artefato privado do GitHub por 90 dias. O arquivo sem criptografia é apagado na hora. Sem a senha cadastrada, o backup **não roda**, para nunca ser salvo em texto puro.

1. Gere a senha: `python -c "import secrets; print(secrets.token_urlsafe(32))"`.
2. Guarde **no gerenciador de senhas**. Sem ela o backup não pode ser aberto, e ela não fica em nenhum outro lugar recuperável.
3. Cadastre: `gh secret set BACKUP_PASSPHRASE --repo lucasllimati/ofertas-l3`.
4. Teste já: Actions → **garimpo** → Run workflow → `backup`. No fim da execução aparece o artefato `backup-<número>`.
5. Para restaurar: [runbook → Restaurar backup](runbook.md#restaurar-backup).

Dica: uma vez por mês, baixe o artefato mais recente e guarde fora do GitHub (um drive seu). Ele já está criptografado.

---

## 13. Primeira execução

Antes: `uv run python -m src.doctor` sem nenhum ❌ (seção [2.1](#21-assistente-de-verificação-doctor)).

Tudo pelo GitHub: **Actions → garimpo → Run workflow** e escolha o passo. Pelo terminal: `gh workflow run garimpo.yml -f steps=<passo> --repo lucasllimati/ofertas-l3`.

| # | Passo | O que esperar |
|---|---|---|
| 1 | `healthcheck` | Chega "✅ Garimpo healthcheck ok · bot @... · canais ok: casa, pet" no seu Telegram. Ele confere o banco, o bot e se o bot é admin com "Publicar mensagens" em cada canal ativo; se falhar, a mensagem de erro diz qual canal corrigir |
| 2 | `daily` | Chegam até 5 prévias por nicho, com arte, legenda e botões ✅ ❌ ⏭ |
| 3 | Aprovar | Toque em ✅ nas prévias que gostar. O botão é processado na próxima execução |
| 4 | `publish` | Os aprovados com horário vencido saem nos canais. Depois disso o publish roda sozinho às 08:07, 12:07, 19:07 e 21:07 |
| 5 | `report` | Relatório no seu Telegram. Roda sozinho às 22:37; aos domingos traz também mercado, horários e A/B; no dia 5, o fechamento do mês |
| 6 | `close` (opcional) | Fechamento do mês anterior (Conciliador + Contador) com o CSV para a contabilidade. Também pelo comando `/fechamento` |

Execução automática (horário de Brasília): `daily` 05:07 · `publish` 08:07, 12:07, 19:07 e 21:07 · `report` 22:37 · `backup` domingo 03:17.

Para reprocessar um dia ou um nicho, use os campos `run_date` e `niche` do Run workflow.

Toda execução começa pelo job **verify**: ele só deixa a produção rodar se o commit atual passou em `ci` e `security`. Logo depois de um merge, ele espera esses workflows terminarem (até 12 min). Se algum falhou, a execução para e nada é publicado: corrija e faça merge de novo.

### 13.1 Modo ensaio (primeira semana)

Tudo funciona de verdade (Shopee, banco, prévias, aprovação, Vigia de preço, relatório), mas **o que iria para os canais chega só no seu chat**, precedido de "🎭 Ensaio: a mensagem abaixo iria para @garimpocasa". Nada sai em público enquanto você confere preço, arte, texto e horários.

1. Ligar: GitHub → Settings → Secrets and variables → Actions → aba **Variables** → **New repository variable** → `GARIMPO_REHEARSAL` = `1`. Pelo terminal: `gh variable set GARIMPO_REHEARSAL --body 1 --repo lucasllimati/ofertas-l3`.
2. O relatório da noite e o healthcheck lembram que o ensaio está ativo.
3. Desligar (quando estiver satisfeito): apague a variável (`gh variable delete GARIMPO_REHEARSAL --repo lucasllimati/ofertas-l3`). A próxima execução publica nos canais.

Na sua máquina: `uv run python -m src.run --rehearsal --steps daily` (ou `GARIMPO_REHEARSAL=1` no `.env`). Os posts do ensaio contam como publicados no banco (entram no relatório e no intervalo de repetição de 7 dias).

### 13.2 Aviso de "o sistema parou" → `HEARTBEAT_URL`

O alerta de falha chega pelo Telegram, mas, se o sistema nem rodar (GitHub Actions fora, minutos do mês esgotados, workflow desativado, Supabase pausado), ninguém avisa. Um monitor externo resolve: cada execução manda um "estou vivo"; se ele parar de chegar, o monitor avisa você.

1. Crie a conta grátis em [healthchecks.io](https://healthchecks.io) e ative o 2FA.
2. **Add Check** → nome `garimpo` → **Schedule**: Period **8 hours**, Grace Time **1 hour** (a maior pausa entre execuções é 22:37 → 05:07).
3. **Integrations**: o e-mail já vem ligado; adicione **Telegram** para receber no celular.
4. Copie a **Ping URL** (`https://hc-ping.com/<uuid>`) e cadastre: `gh secret set HEARTBEAT_URL --repo lucasllimati/ofertas-l3`.
5. Rode o `healthcheck` pelo Run workflow: o check fica verde. Execução com falha manda `/fail` e o check fica vermelho na hora.

Trate a Ping URL como segredo (quem tem ela consegue fingir que o sistema está vivo), mas ela não dá acesso à sua conta.

---

## 14. Mapa de arquivos de configuração

| Arquivo ou pasta | O que configura | Quando mexer |
|---|---|---|
| [config/niches.yaml](../config/niches.yaml) | **Tudo dos nichos**: status, palavras-chave, filtros, horários, limites, pesos do score, canais, modelos e orçamento de LLM | Sempre que mudar nicho, palavra-chave, horário ou limite |
| [config/niches.schema.json](../config/niches.schema.json) | Schema para autocompletar no editor | Nunca à mão: `uv run python -m src.config.validate --write-schema` |
| [config/brands/base.json](../config/brands/base.json) | Marca comum: tom de voz, tagline, cores padrão, fontes | Raramente |
| `config/brands/<nicho>.json` | Cores, emoji, hashtags e nome do nicho na arte e na legenda | Ao criar nicho ou mudar identidade |
| `config/offers/<nicho>.csv` | Ofertas coladas à mão (Shopee sem API, ML, Amazon) | Sempre que quiser postar um link seu |
| [config/allowed_domains.json](../config/allowed_domains.json) | Domínios permitidos para links (pipeline e Worker) | Ao entrar uma loja nova |
| [config/calendar.yaml](../config/calendar.yaml) | Calendário sazonal: datas de pico, palavras-chave extras, volume e selo | Antes de cada data comercial (Black Friday, Natal...) |
| [config/coupons.csv](../config/coupons.csv) | Cupons válidos que entram nas legendas | Sempre que pegar cupom novo no painel ou newsletter |
| [config/finance.yaml](../config/finance.yaml) | Regime tributário, alíquotas, plano de divisão do dinheiro (Contador) | Com o contador e todo janeiro |
| [.github/workflows/garimpo.yml](../.github/workflows/garimpo.yml) | Horários (cron em UTC) e segredos que chegam ao programa | Ao mudar `publish_slots` ou ativar nicho |
| [.github/workflows/security.yml](../.github/workflows/security.yml) | Varreduras de segurança | Raramente |
| [.github/dependabot.yml](../.github/dependabot.yml) | Atualização automática de dependências | Raramente |
| [docs/secrets.md](secrets.md) | Inventário de segredos (nomes, escopo, validade) | Ao criar ou rotacionar segredo |
| [worker/wrangler.toml](../worker/wrangler.toml) | Ids do KV e D1 e domínio do `/go` | Uma vez (seção 10) |
| [sql/migrations/](../sql/migrations/) | Estrutura do banco | Só ao evoluir o código |
| `.env` | Segredos para rodar na sua máquina | Uso local |
| GitHub → Settings → Secrets and variables → Actions | Segredos de produção | Seção 12 |

---

## 15. Ajustes do dia a dia

Todos em [config/niches.yaml](../config/niches.yaml), salvo indicação. Depois de editar: `uv run python -m src.config.validate`, commit, PR e merge.

| Quero... | Onde | Exemplo |
|---|---|---|
| Mudar palavras-chave de um nicho | `niches[].platforms.shopee.keywords` | `[mop giratório, porta temperos]` |
| Coletar mais ou menos produtos por palavra | `niches[].platforms.shopee.limit_per_keyword` (1–50) | `30` |
| Mais ou menos posts por dia | `limits.new_content_per_day` (criados) e `limits.posts_per_day.telegram` (publicados) | `5` e `8` |
| Faixa de preço | `filters.price_min` / `filters.price_max` no nicho | `15` / `400` |
| Exigir nota ou comissão mínima | `defaults.filters.min_rating`, `min_commission_rate` | `4.5`, `0.05` |
| Bloquear um tipo de produto | `filters.blocked_categories` no nicho (soma às dos defaults; ignora acento) | `[vermífugo]` |
| Mudar o peso do ranking | `defaults.score_weights` ou por nicho | `commission: 0.30` |
| Explorar mais produtos novos | `exploration_rate` (0 a 1) | `0.30` |
| Não repetir produto por mais tempo | `global.repost_cooldown_days` | `14` |
| Aprovação automática num nicho maduro | `approval: auto_above_score` + `auto_approve_min_score` no nicho | `0.80` |
| Mudar horários de publicação | `publish_slots` **e** o cron de publish em [garimpo.yml](../.github/workflows/garimpo.yml) (ver abaixo) | `["09:07", "18:07"]` |
| Mudar cores, emoji ou hashtags | `config/brands/<nicho>.json` | `"accent": "#1F8A7A"` |
| Permitir links de outra loja | [config/allowed_domains.json](../config/allowed_domains.json) | `"magazineluiza.com.br"` |
| Pausar um canal na hora | Telegram: `/pausar casa telegram` (volta com `/retomar casa telegram`) | — |
| Pausar um nicho de vez | `status: paused` no nicho | — |
| Desligar um agente num nicho | `agents:` em `defaults` ou no nicho | `price_guard: {enabled: false}`, `ab_test: false` |
| Tolerância do Vigia de preço | `agents.price_guard.tolerance_pct` | `5` (só pede reaprovação se o preço mudar mais de 5%) |
| Mais ou menos campeões reciclados | `agents.recycle.max_share` (0 a 0,5) | `0.10` |
| Adicionar uma data de pico | [config/calendar.yaml](../config/calendar.yaml) (ver abaixo) | — |
| Pôr um cupom nas legendas | [config/coupons.csv](../config/coupons.csv) (ver abaixo) | — |
| Ajustar o cálculo de imposto | [config/finance.yaml](../config/finance.yaml) (ver abaixo) | `regime: simples` |

**Horários: YAML e cron precisam combinar.** `publish_slots` está no horário de Brasília; o cron do GitHub está em **UTC** (Brasília + 3h). Se trocar os slots para `09:07` e `18:07`, as linhas de publish do `garimpo.yml` viram uma só:

```yaml
schedule:
  - cron: "7 8 * * *"        # daily   05:07 BRT (não mude o texto)
  - cron: "7 12,21 * * *"    # publish 09:07 e 18:07 BRT
  - cron: "37 1 * * *"       # report  22:37 BRT (não mude o texto)
```

Slot depois das 21:00 BRT cai no dia seguinte em UTC (21:07 BRT = `7 0 * * *`). O workflow usa o texto exato dos crons de daily (`7 8 * * *`), report (`37 1 * * *`) e backup (`17 6 * * 0`) para saber o que rodar; qualquer outro cron vira publish. O daily precisa rodar antes do primeiro slot.

O Otimizador de horários sugere os slots e o cron já em UTC no relatório de domingo e no comando `/horarios <nicho>`.

### 15.1 Calendário sazonal (`config/calendar.yaml`)

Cada evento tem `id`, `name`, `start` e `end` (inclusivos, horário de Brasília), `niches` (vazio = todos), `extra_keywords` por nicho, `content_multiplier` (1 a 3: multiplica posts criados e publicados no dia), `badge` (selo na arte e na legenda) e `heads_up_days` (aviso no relatório antes de começar). O arquivo já traz 11.11, Esquenta Black Friday, Black Friday (27–30/11/2026), 12.12, Natal e Dia das Mães 2027. Confira as datas de cada ano e rode o `validate`.

### 15.2 Cupons (`config/coupons.csv`)

```csv
platform,code,description,discount_pct,discount_brl,min_purchase,valid_until,niches
shopee,ACHADO10,10% em casa e decoração,10,,50,2026-11-30 23:59,casa
mercadolivre,PET20,R$ 20 off,,20,"99,90",30/11/2026 23:59,pet;casa
```

- Preencha `discount_pct` **ou** `discount_brl`; `min_purchase` e `niches` são opcionais (`niches` separados por `;`, vazio = todos).
- Só entra na legenda o cupom que passa nas regras `coupons` do nicho em `niches.yaml`: desconto de pelo menos `min_discount_pct` (10%) **ou** `min_discount_brl` (R$ 20) e pelo menos `min_hours_valid` (6 h) de validade.
- Valores aceitam vírgula decimal; datas em ISO ou `dd/mm/aaaa hh:mm` (Brasília).
- Use só cupons que você confirmou no painel de afiliado: o código vai literalmente para o canal.
- O cupom vencido sai da legenda sozinho; o relatório avisa os que vencem em 24 h; `/cupons` lista os válidos.

### 15.3 Contador e finanças (`config/finance.yaml`)

> ⚠️ Estimativas para planejamento. Não substitui contador.

| Campo | O que é | Faça |
|---|---|---|
| `regime` | `simples`, `mei` ou `pf` | Confirme com o contador |
| `mei_permitido` | Libera a comparação com o MEI | Deixe `false` até o contador confirmar que a sua ocupação cabe no MEI (afiliado costuma não caber) |
| `simples.anexo` | `iii`, `v` ou `fator_r` | O contador diz qual |
| `simples.folha_12m` | Pró-labore e salários pagos nos últimos 12 meses | Atualize quando começar a pagar pró-labore |
| `custos_fixos_mensais` | Contador, domínio, ferramentas (R$/mês) | Preencha |
| `planejamento` | Margem da reserva de impostos, % de reinvestimento e de caixa, retirada desejada | Ajuste ao seu plano |
| `dia_fechamento` | Dia do mês do fechamento automático | Padrão 5 |
| Tabelas (`simples`, `irpf`, `pro_labore`, `mei`, `dividendos`) | Alíquotas e tetos de 2026, com fontes no fim do arquivo | Revise todo janeiro e atualize `atualizado_em` (o Contador avisa se passar de 1 ano) |

Comandos: `/imposto [AAAA-MM]` (estimativa do mês, parcial se for o mês atual) e `/fechamento [AAAA-MM]` (fechamento com CSV). Explicação completa e exemplo de R$ 50 mil: [agentes.md](agentes.md#23-conciliador--contador-trabalham-com-o-financeiro).

---

## 16. Adicionar um nicho novo

O nicho entra em duas etapas: primeiro **candidate** (só coleta e ranqueia, sem posts e sem segredo novo) e, quando os números forem bons, **active**.

### 16.1 Monitorar (status `candidate`)

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

**3. Commit, PR e merge.** A partir do próximo `daily`, o nicho é coletado e ranqueado.

**4. Acompanhe:**
- No Telegram: `/top papelaria` mostra os 10 melhores produtos do dia.
- No banco (Supabase → SQL Editor):
  ```sql
  SELECT * FROM garimpo.v_daily_niche WHERE niche_id = 'papelaria' ORDER BY run_date DESC;
  ```

O candidato precisa da **API da Shopee** (`mode: api`) para ter dados; sem a credencial, ele é pulado com aviso. Com `manual_offers`, ele também coleta do CSV.

**Quando promover:** compare com os ativos por pelo menos 2 semanas: produtos elegíveis, vendas em 7 dias (`sales_7d` em `product_score.components`) e comissão média. Critério sugerido em [ARQUITETURA.md](../ARQUITETURA.md): crescimento de vendas e comissão média acima das dos nichos ativos.

### 16.2 Ativar (status `active`)

1. **Canal no Telegram:** crie `@garimpopapelaria` e adicione o bot como admin com permissão de publicar ([4.3](#43-canais-dos-nichos--tg_casa_chat_id-tg_pet_chat_id)).
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
4. **Ofertas manuais (opcional):** copie `config/offers/casa.csv` para `config/offers/papelaria.csv`.
5. **Segredo:** `gh secret set TG_PAPELARIA_CHAT_ID --repo lucasllimati/ofertas-l3` com valor `@garimpopapelaria`.
6. **Workflow:** em [.github/workflows/garimpo.yml](../.github/workflows/garimpo.yml), no bloco `env` do passo `garimpo`, adicione:
   ```yaml
             TG_PAPELARIA_CHAT_ID: ${{ secrets.TG_PAPELARIA_CHAT_ID }}
   ```
7. **Inventário:** adicione a linha de `TG_PAPELARIA_CHAT_ID` em [docs/secrets.md](secrets.md). O CI falha se faltar.
8. **Valide:**
   ```bash
   uv run python -m src.config.validate --write-schema
   uv run python scripts/check_secrets_inventory.py
   uv run pytest
   ```
   O teste `test_repo_config_is_valid` lista os nichos ativos esperados: atualize-o para incluir `papelaria`.
9. **Commit, PR e merge.** Rode Actions → **garimpo** → Run workflow → `daily` para ver as primeiras prévias.

> Minutos do GitHub Actions: cada nicho ativo soma ≈ 30–60 min/mês. Com 2.000 min grátis, cabem com folga 8–10 nichos.

---

## 17. Renovar e trocar credenciais

| Credencial | Validade | Onde gerar a nova | Onde atualizar |
|---|---|---|---|
| `TELEGRAM_BOT_TOKEN` | Não expira | @BotFather → `/revoke` → escolha o bot (gera outro e invalida o antigo) | GitHub secret + `.env` |
| `APPROVAL_HMAC_SECRET` | Não expira | `python -c "import secrets; print(secrets.token_urlsafe(32))"` | GitHub secret + `.env` |
| `DATABASE_URL` (senha do pipeline) | Não expira | Supabase SQL Editor: `ALTER ROLE garimpo_pipeline PASSWORD 'nova-senha';` | GitHub secret + `.env` |
| Senha do dono do banco | Não expira | Supabase → Project Settings → Database → Reset database password | Só no gerenciador de senhas |
| `SHOPEE_APP_SECRET` | Ver painel | Painel de afiliados → Open API → regenerar | GitHub secret + `.env` |
| `ANTHROPIC_API_KEY` | Até revogar | Console → API Keys → criar nova; depois apagar a antiga | GitHub secret + `.env` |
| `CF_API_TOKEN` | Data definida na criação | Cloudflare → My Profile → API Tokens → **Roll** | GitHub secret + `.env` |

Depois de trocar:
1. Rode Actions → **garimpo** → `healthcheck`.
2. Atualize as datas em [docs/secrets.md](secrets.md).
3. Rotação recomendada: a cada 90 dias.

**Vazou alguma?** Siga [runbook.md → Vazamento de chave](runbook.md#vazamento-de-chave): revogue primeiro, depois troque, verifique uso indevido e registre.

---

## 18. Problemas comuns

| Sintoma | Causa provável | Solução |
|---|---|---|
| `'pre-commit' não é reconhecido` | Ferramenta não instalada ou fora do PATH | `uv tool install pre-commit`; se persistir, `uv tool update-shell` e reabra o terminal (seção 2) |
| `segredos ausentes: ...` | Secret não cadastrado ou nome diferente | `gh secret list`; o nome precisa ser idêntico ao da tabela 12.1 |
| `Shopee API não configurada` num nicho ativo | `mode: api` sem `SHOPEE_APP_ID`/`SHOPEE_APP_SECRET` | Cadastre os secrets ou troque para `mode: off` + CSV |
| `todas as palavras-chave da Shopee falharam` | Credencial inválida, limite de chamadas ou API fora | Confira AppID/Secret; rode de novo mais tarde |
| `connection refused` / timeout no banco | URL de conexão direta (IPv6) ou projeto pausado | Use o **Session pooler**; reative o projeto no Supabase |
| `password authentication failed` | Usuário sem o `.<project-ref>` no pooler ou senha com caractere especial | Usuário `garimpo_pipeline.<project-ref>`; senha sem `@ : / ? #` |
| `permission denied for schema garimpo` | Migration não rodada ou usuário criado antes dela | Rode `--steps migrate` como dono e recrie o usuário (seção 5.4) |
| Healthcheck: `o bot não é admin com 'Publicar mensagens' em @canal` ou `canal ... inacessível` | Bot fora do canal, sem permissão de publicar, ou `TG_*_CHAT_ID` errado | Canal → Administradores → bot com "Publicar mensagens"; confira o `@` no secret |
| `Forbidden: bot is not a member of the channel chat` | Bot não é admin do canal | Adicione o bot como admin com "Publicar mensagens" |
| `chat not found` | `TG_*_CHAT_ID` errado | Use `@canal` (público) ou o id `-100...` (privado) |
| Prévia não chega | Você não mandou `/start` ao bot ou `TELEGRAM_ADMIN_CHAT_ID` errado | Envie `/start`; confira o id no @userinfobot |
| `Conflict: terminated by other getUpdates` / webhook | Webhook configurado no bot | No navegador (sem compartilhar a URL): `https://api.telegram.org/bot<TOKEN>/deleteWebhook` |
| Botão aprovado não publica | Aprovação só é lida na próxima execução | Espere o próximo horário ou rode `publish` manualmente |
| Oferta do CSV não aparece | Link fora da allowlist, sem `https` ou sem preço | Veja o log do `daily` ("oferta manual ignorada") |
| `copy template` mesmo com chave do Claude | Orçamento diário atingido, chave inválida ou `llm.enabled: false` | Confira o saldo e o limite no console e os tetos no YAML |
| Workflow agendado não roda | Agendamentos só rodam a partir da `main`. O GitHub também pode desativar um workflow (ex.: repositório público sem atividade por 60 dias) ou atrasar o cron em horários de pico | Faça merge na `main`; em Actions → garimpo, veja se aparece "This workflow was disabled" e reative. O aviso de parada (13.2) avisa se acontecer |
| `migration pendente: 0005_... rode migrate com a URL do dono` | Atualização do projeto trouxe tabela ou coluna nova; o usuário do pipeline não altera o schema | Rode a seção 5.3 (ou `scripts/bootstrap_db.py`) como dono e repita a execução |
| `doctor`: `esta URL é do DONO` | O `.env` está com a URL do dono do banco | Na sua máquina serve para o `migrate`; no GitHub vai a do `garimpo_pipeline` (o `push_secrets` recusa a do dono) |
| Job `verify` falhou: "não passou em ci e security" | O commit atual da `main` tem CI ou security vermelho (ou foi um push direto que ainda não rodou) | Abra o `ci`/`security` daquele commit, corrija via PR; a próxima execução agendada volta sozinha |
| `security` vermelho no PR | Segredo no código, dependência vulnerável ou workflow fora do padrão | Abra o log do job `scan`; ele diz o passo e o arquivo |

Mais casos e procedimentos: [docs/runbook.md](runbook.md).

---

## 19. Checklist final

**Segurança**
- [ ] Gerenciador de senhas com todas as credenciais
- [ ] 2FA em GitHub, Telegram, Supabase, Shopee, Mercado Livre, Amazon, Cloudflare, Anthropic e e-mail
- [ ] `pre-commit install` feito
- [ ] `.env` só na sua máquina (nunca commitado)

**Contas e credenciais**
- [ ] Bot criado, endurecido (`/setjoingroups` Disable) e `/start` enviado
- [ ] Bot admin dos canais `@garimpocasa` e `@garimpopet`, só com "Publicar mensagens"
- [ ] Supabase criado em São Paulo, `--steps migrate` rodado, usuário `garimpo_pipeline` criado e testado
- [ ] Shopee: `mode: api` com AppID/Secret **ou** `mode: off` + ofertas no CSV dos nichos ativos
- [ ] (Opcional) Mercado Livre e Amazon aprovados e links no CSV
- [ ] (Opcional) Claude com workspace e limite de gasto
- [ ] (Opcional) Worker `/go` publicado e variáveis `CF_*` + `REDIRECT_BASE_URL`

**GitHub**
- [ ] Repositório privado, Actions habilitado, permissão padrão "Read"
- [ ] Segredos obrigatórios cadastrados (`gh secret list`)
- [ ] Datas preenchidas em `docs/secrets.md`
- [ ] `BACKUP_PASSPHRASE` cadastrado e no gerenciador de senhas; `backup` rodado uma vez com sucesso

**Primeira execução**
- [ ] `uv run python -m src.doctor` sem ❌
- [ ] (Recomendado) `HEARTBEAT_URL` cadastrado e check verde no healthchecks.io
- [ ] (Recomendado) Primeira semana em modo ensaio (`GARIMPO_REHEARSAL=1`); depois apagar a variável
- [ ] `healthcheck` verde e mensagem recebida
- [ ] `daily` com prévias recebidas e aprovadas
- [ ] `publish` publicou nos canais
- [ ] `report` chegou à noite
