# Garimpo Engine

Sistema de afiliados multi-nicho. Todo dia ele coleta ofertas, ranqueia por nicho, gera post com arte e legenda, manda a prévia para você aprovar no Telegram, publica no canal do nicho nos horários certos e mede cliques, pedidos e comissão.

**Guia de configuração completo** (contas, tokens, onde fica cada arquivo, como adicionar nicho): [docs/SETUP.md](docs/SETUP.md).

Arquitetura e modelo de negócio: [ARQUITETURA.md](ARQUITETURA.md). Especificação completa (todas as fases): [prompt-garimpo-engine.md](prompt-garimpo-engine.md).

## O que já funciona (versão 0.1)

| Parte | Estado |
|---|---|
| Configuração multi-nicho (`config/niches.yaml`) validada, com JSON Schema | ✅ |
| Coleta: Shopee Affiliate Open API + ofertas coladas em CSV (Shopee, Mercado Livre, Amazon) | ✅ |
| Bronze → silver → gold: snapshots, histórico de preço (SCD2), vendas em 1/7/15/30 dias, score por nicho | ✅ |
| Seleção diária com 20% de exploração e sem repetir produto por 7 dias | ✅ |
| Copy por template ou por Claude (Sonnet escreve, Haiku revisa), com teto de custo diário | ✅ |
| Arte 1080×1350 com a marca do nicho | ✅ |
| Prévia no Telegram com botões Aprovar / Rejeitar / Próximo horário (assinados com HMAC) | ✅ |
| Publicação no canal do Telegram por horário, limite diário, circuit breaker, sem duplicar | ✅ |
| Link com `subIds` (nicho, canal, post) → conversão atribuída a cada post | ✅ |
| Redirecionador `/go` (Cloudflare Worker) com allowlist + cliques no D1 | ✅ (opcional) |
| Importação de conversões (Shopee API e CSV) e relatório diário no Telegram | ✅ |
| Comandos `/status`, `/top <nicho>`, `/pausar`, `/retomar` | ✅ |
| CI, `security.yml`, gitleaks, pip-audit, npm audit, semgrep, Dependabot, RLS no Postgres | ✅ |
| Instagram, TikTok, lojas Astro, Caçador de cupons, Analista de mercado, concorrentes | ⏳ próximas fases ([roadmap](#próximas-fases)) |

## Teste em 2 minutos (sem nenhuma conta)

Precisa de Python 3.12 e do [uv](https://docs.astral.sh/uv/) (`pip install uv`).

```bash
uv sync
uv run python -m src.run --demo --steps all
```

A demo usa SQLite, uma Shopee falsa e um Telegram falso. Ela simula o dia inteiro: coleta, score, 5 posts por nicho, aprovação automática, publicação e relatório. Veja:

- `out/demo/telegram_outbox.jsonl`: tudo o que seria enviado ao Telegram (prévias, posts, relatório);
- `out/demo/media/<data>/<nicho>/*.png`: as artes.

Rode de novo com `--run-date` de outro dia para ver as janelas de vendas funcionando.

## Colocar no ar hoje (≈ 1 hora)

O caminho mais rápido para a primeira comissão é **Telegram + links colados à mão**, enquanto a Shopee analisa seu pedido de acesso à API.

### 1. Telegram (10 min)

1. No Telegram, fale com o [@BotFather](https://t.me/BotFather): `/newbot` → guarde o token (vai virar `TELEGRAM_BOT_TOKEN`).
2. Crie os canais públicos `@garimpocasa` e `@garimpopet` (confira se o @ está livre). Adicione o bot como **administrador** de cada canal, com permissão de postar.
3. Mande `/start` para o seu bot (sem isso ele não pode te escrever).
4. Descubra seu id numérico com o [@userinfobot](https://t.me/userinfobot). Ele vale para `TELEGRAM_ADMIN_USER_IDS` **e** para `TELEGRAM_ADMIN_CHAT_ID` (o chat privado com o bot tem o mesmo id que você).
5. Gere o segredo dos botões: `python -c "import secrets; print(secrets.token_urlsafe(32))"` → `APPROVAL_HMAC_SECRET`.

### 2. Banco Postgres grátis no Supabase (10 min)

1. Crie um projeto em [supabase.com](https://supabase.com) (região São Paulo).
2. Em **Connect**, copie a connection string do **Session pooler**. Ela funciona em IPv4; a conexão direta é só IPv6 e não funciona no GitHub Actions.
3. Na sua máquina, crie as tabelas uma vez com o usuário dono do banco:
   ```bash
   DATABASE_URL="postgresql://postgres.xxxx:SENHA@aws-0-sa-east-1.pooler.supabase.com:5432/postgres" \
     uv run python -m src.run --steps migrate
   ```
4. Crie o usuário de privilégio mínimo do pipeline ([runbook](docs/runbook.md#criar-o-usuário-do-pipeline-no-postgres)) e use **ele** no `DATABASE_URL` do GitHub.

### 3. Ofertas (15 min)

- **Sem API da Shopee ainda:** em `config/niches.yaml`, troque `mode: api` por `mode: off` em `casa` e `pet`. Cole ofertas em `config/offers/casa.csv` e `config/offers/pet.csv`, uma por linha, com o link de afiliado gerado no painel da Shopee, do Mercado Livre ou da Amazon. Escolha produtos com nota alta e muitas vendas.
- **Com a API liberada:** crie o app no painel de afiliados da Shopee, cadastre `SHOPEE_APP_ID` e `SHOPEE_APP_SECRET` e volte para `mode: api`. Antes de confiar nos números, confira os campos no explorador GraphQL do painel (as queries estão isoladas em [src/sources/shopee.py](src/sources/shopee.py)).

### 4. GitHub (15 min)

1. Crie o repositório **privado** `garimpo-engine` e envie este código.
2. Em **Settings → Secrets and variables → Actions**, cadastre os segredos de [docs/secrets.md](docs/secrets.md): no mínimo `DATABASE_URL`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_ADMIN_CHAT_ID`, `TELEGRAM_ADMIN_USER_IDS`, `APPROVAL_HMAC_SECRET`, `TG_CASA_CHAT_ID` (`@garimpocasa`) e `TG_PET_CHAT_ID` (`@garimpopet`).
3. Proteja a `main` (Settings → Branches): PR obrigatório, CI verde, sem force push. Ative 2FA na conta.
4. Em Actions → **garimpo** → Run workflow, escolha `healthcheck`. Deve chegar "✅ Garimpo healthcheck ok" no seu Telegram.
5. Rode de novo escolhendo `daily`. As prévias chegam no seu chat. Aprove algumas.
6. Rode escolhendo `publish` (ou espere o próximo horário). Os posts aprovados saem nos canais.

A partir daí roda sozinho: `daily` às 05:07, `publish` às 08:07, 12:07, 19:07 e 21:07, `report` às 22:37 (horário de Brasília).

### 5. Opcional

- **Copy com Claude:** cadastre `ANTHROPIC_API_KEY`. Teto padrão: US$ 0,30 por nicho por dia e US$ 1,00 no total (`config/niches.yaml`). Sem a chave, usa template.
- **Contagem de cliques (`/go`):** veja [Redirecionador](#redirecionador-opcional). Sem ele, as conversões continuam atribuídas por post via `subIds` da Shopee; você só não vê os cliques.

## Rodando localmente

```bash
cp .env.example .env      # preencha; .env nunca vai para o git
uv run python -m src.run --steps healthcheck
uv run python -m src.run --steps daily
uv run python -m src.run --steps publish
uv run python -m src.run --steps report
uv run python -m src.run --steps daily --run-date 2026-10-20 --niche casa   # reprocessar
uv run python -m src.run --steps conversions --import-conversions vendas-ml.csv
uv run python -m src.config.validate --check-secrets
uv run pytest
```

Passos disponíveis: `migrate, sync-niches, healthcheck, approvals, ingest, purge, transform, score, content, preview, publish, clicks, conversions, report`. Atalhos: `daily`, `publish`, `report`, `all`.

## Sua rotina

| Quando | O quê |
|---|---|
| Manhã (≈ 5 min) | Aprovar as prévias no Telegram. O botão responde na próxima execução (até a hora do próximo slot). |
| Quando quiser | Colar novas ofertas no CSV (ML/Amazon) e fazer commit. |
| Noite | Ler o relatório: cliques, pedidos, comissão e **EPC** (comissão por clique) por nicho. |
| Semanal | Exportar conversões do Mercado Livre/Amazon e importar com `--import-conversions`. |

Comandos no chat com o bot: `/status`, `/top casa`, `/pausar casa telegram`, `/retomar casa telegram`.

Quando um nicho estiver maduro, troque `approval: manual` por `approval: auto_above_score` nele para pular a aprovação dos posts com score alto.

## Redirecionador (opcional)

```bash
cd worker
npm ci --ignore-scripts
npx wrangler login
npx wrangler kv namespace create LINKS          # copie o id para wrangler.toml
npx wrangler d1 create garimpo-clicks           # copie o id para wrangler.toml
npm run d1:schema
npm test && npx wrangler deploy
```

Depois cadastre `CF_API_TOKEN` (só "Workers KV Storage: Edit" e "D1: Edit"), `CF_ACCOUNT_ID`, `CF_KV_NAMESPACE_ID`, `CF_D1_DATABASE_ID` e `REDIRECT_BASE_URL` (a URL do Worker, ou `https://go.garimpo.com.br` com domínio próprio).

## Custos

| Item | Custo |
|---|---|
| GitHub Actions (repo privado) | Grátis até 2.000 min/mês. Uso estimado: 6 execuções/dia × ~1,5–3 min ≈ **300–450 min/mês** com 2 nichos; cada nicho a mais soma ≈ 30–60 min/mês |
| Supabase / Cloudflare | Grátis nos limites de [ARQUITETURA.md §5](ARQUITETURA.md#5-orçamento-do-plano-gratuito) |
| Claude (opcional) | ≈ US$ 0,01 por post (Sonnet + Haiku); teto configurável |
| Domínio `.com.br` | ≈ R$ 40/ano (só quando for usar `/go` ou lojas com domínio próprio) |

## Estrutura

```
config/            niches.yaml, schema, marcas, ofertas manuais (CSV), domínios permitidos
src/run.py         ponto de entrada (passos, isolamento de falha por nicho, modo demo)
src/config/        modelos Pydantic, merge de defaults, validador
src/common/        banco (Postgres/SQLite), logging com redação, Telegram, segredos
src/sources/       Shopee API, CSV manual, fonte falsa
src/pipeline/      ingest (bronze), transform (silver), score (gold), content (seleção + copy)
src/content/       marca, copy (template/Claude), legenda + conformidade, arte
src/approval.py    prévias, botões assinados, respostas; src/commands.py: comandos do bot
src/publishers/    publicador do Telegram
src/tracking/      KV/D1 da Cloudflare, cliques e conversões
src/reports/       relatório diário
sql/migrations/    schema (comum) + segurança (só Postgres: papéis e RLS)
worker/            redirecionador /go (TypeScript)
.github/workflows/ ci, security, daily, publish, report, healthcheck
docs/              runbook, secrets, ADRs
```

## Suposições

- Horário de Brasília (`America/Sao_Paulo`) e domínio `garimpo.com.br` ainda a confirmar; tudo é configuração.
- Nichos ativos: `casa` e `pet`; os demais são `candidate` (coletados e ranqueados, sem posts).
- Publicação só no Telegram nesta versão; Instagram e TikTok ficam `enabled: false` até a próxima fase.
- O campo `sales` da Shopee é tratado como contador acumulado; se ele for uma janela móvel, o score cai no nível de vendas (ver [score.py](src/pipeline/score.py)).

## Próximas fases

Seguindo o roadmap de [ARQUITETURA.md §8](ARQUITETURA.md#8-roadmap-orientado-a-receita):

1. Instagram (feed, reels, stories) e TikTok (rascunho), com mídia no R2.
2. Lojas Astro por nicho (`/bio`, `/ofertas`, SEO).
3. Caçador de cupons e story de cupom.
4. Analista de mercado (PR automático para nichos) e Monitor de concorrentes.
5. Webhook do Telegram no Worker, para o botão responder na hora ([ADR 0002](docs/adr/0002-aprovacao-por-polling.md)).
