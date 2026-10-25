# Garimpo Engine

Sistema de afiliados multi-nicho. Todo dia ele:
1. coleta ofertas;
2. ranqueia por nicho;
3. gera post com arte e legenda;
4. manda a prévia para você aprovar no Telegram;
5. publica no canal do nicho nos horários certos;
6. mede cliques, pedidos e comissão por post.

**Comece por aqui:** [índice da documentação](docs/README.md) · [guia de configuração](docs/SETUP.md) · [agentes](docs/agentes.md) · [arquitetura e negócio](ARQUITETURA.md).

## O que já funciona (v0.4)

| Parte | Estado |
|---|---|
| Configuração multi-nicho (`config/niches.yaml`) validada, com JSON Schema | ✅ |
| Coleta: Shopee Affiliate Open API + ofertas coladas em CSV (Shopee, Mercado Livre, Amazon) | ✅ |
| Bronze → silver → gold: snapshots, histórico de preço, vendas em 1/7/15/30 dias, score por nicho | ✅ |
| Seleção diária com 20% de exploração e sem repetir produto por 7 dias | ✅ |
| Copy por template ou por Claude (Sonnet escreve, Haiku revisa), com teto de custo | ✅ |
| Regras de anúncio: #publi no topo, "de/por" só verificado, sem link/@/telefone de terceiros | ✅ |
| Arte 1080×1350 com a marca do nicho | ✅ |
| Prévia no Telegram com botões ✅ ❌ ⏭ assinados (HMAC) e comandos `/status`, `/top`, `/pausar`, `/retomar`, `/cupons`, `/mercado`, `/horarios`, `/imposto`, `/fechamento` | ✅ |
| Publicação no Telegram por horário, limite diário, circuit breaker, sem duplicar | ✅ |
| SubIds por post (nicho, canal, post) → venda atribuída a cada post | ✅ |
| Redirecionador `/go` (Cloudflare) com allowlist e contagem de cliques humanos | ✅ (opcional) |
| Conversões (Shopee API e CSV) e relatório diário com EPC e eventos de segurança | ✅ |
| Backup semanal criptografado e restauração | ✅ |
| Trava de produção: só roda commit verde em `ci` e `security` | ✅ |
| **Vigia de preço e estoque** antes de publicar (preço mudou → reaprovação; esgotado → não publica) | ✅ |
| **Calendário sazonal** (11.11, Black Friday 27/11/2026, 12.12, Natal): mais posts, palavras extras, selo | ✅ |
| **Classificador de conformidade** (Haiku): barra remédio, réplica, adulto, arma com título "limpo" | ✅ |
| **Caçador de cupons** (`config/coupons.csv`) na legenda, com saída automática do cupom vencido | ✅ |
| **Sentinela + Reciclador**: posts 🔥 e 💤 no relatório; campeões voltam depois do cooldown | ✅ |
| **Detector de link quebrado**, **Analista de mercado**, **Otimizador de horários**, **Laboratório A/B** | ✅ |
| **Conciliador + Contador**: fechamento mensal, CSV para a contabilidade, imposto estimado, divisão do dinheiro, riscos | ✅ |
| Instagram, TikTok, lojas, monitor de concorrentes | ⏳ [próximas fases](#próximas-fases) |

## Teste em 2 minutos (sem nenhuma conta)

Precisa de Python 3.12 e do [uv](https://docs.astral.sh/uv/) (`pip install uv`).

```bash
uv sync
uv run python -m src.run --demo --steps all
```

A demo usa SQLite, uma Shopee falsa e um Telegram falso, e simula o dia inteiro: coleta, score, 5 posts por nicho, aprovação, publicação e relatório. Resultados:
- `out/demo/telegram_outbox.jsonl`: tudo o que seria enviado ao Telegram;
- `out/demo/media/<data>/<nicho>/*.png`: as artes.

Rode de novo com `--run-date 2026-10-21` para ver as janelas de venda funcionando. A demo **nunca** usa o banco de produção, mesmo com `DATABASE_URL` no ambiente.

## Colocar no ar

Passo a passo completo, com segurança e testes de cada etapa: **[docs/SETUP.md](docs/SETUP.md)**. Em resumo:

1. **Telegram:** criar o bot e os canais, pôr o bot como admin, pegar seu id (SETUP §4).
2. **Supabase:** criar o projeto, rodar `--steps migrate` com o usuário dono, criar o usuário `garimpo_pipeline` (SETUP §5).
3. **Ofertas:** Shopee Open API ou, enquanto ela não sai, `mode: off` e links colados em `config/offers/<nicho>.csv` (SETUP §6–8).
4. **Secrets no GitHub:** `gh secret set ...` para cada um (SETUP §12), incluindo `BACKUP_PASSPHRASE`.
5. **Primeira execução:** Actions → **garimpo** → Run workflow → `healthcheck`, depois `daily` e `publish` (SETUP §13).

Depois disso roda sozinho (horário de Brasília):

| Quando | O quê |
|---|---|
| 05:07 | `daily`: coleta, score, posts do dia e prévias para você |
| 08:07, 12:07, 19:07, 21:07 | `publish`: lê suas aprovações e publica o que chegou no horário |
| 22:37 | `report`: cliques, vendas e relatório no Telegram |
| Domingo 03:17 | `backup`: histórico criptografado |

## Sua rotina

| Quando | O quê |
|---|---|
| Manhã (≈ 5 min) | Aprovar as prévias no Telegram. O botão confirma na próxima execução |
| Quando quiser | Colar novas ofertas no CSV (ML/Amazon) e fazer commit |
| Noite | Ler o relatório: cliques, pedidos, comissão, **EPC** (comissão por clique), posts 🔥 da Sentinela, links quebrados e cupons vencendo |
| Quando pegar cupom | Colar em `config/coupons.csv` e fazer commit |
| Domingo | Relatório semanal: Analista de mercado (qual nicho ativar), Otimizador de horários e Laboratório A/B |
| Semanal | Importar vendas do ML/Amazon: `--steps conversions --import-conversions vendas.csv` |
| Mensal (dia 5) | Fechamento automático: Conciliador + Contador + CSV. Leve ao contador. Baixe o backup mais recente e guarde fora do GitHub |
| Antes de cada data de pico | Conferir `config/calendar.yaml` (o relatório avisa com antecedência) |

Nicho maduro? Troque `approval: manual` por `approval: auto_above_score` nele para pular a aprovação dos posts com score alto.

## Rodando localmente

```bash
cp .env.example .env      # preencha; .env nunca vai para o git
uv run python -m src.run --steps healthcheck
uv run python -m src.run --steps daily
uv run python -m src.run --steps daily --run-date 2026-10-20 --niche casa   # reprocessar
uv run python -m src.config.validate --check-secrets
uv run pytest                    # todos os testes
uv run pytest -m security        # só a suíte de segurança
```

Passos: `migrate, sync-niches, healthcheck, approvals, ingest, purge, transform, score, content, preview, publish, clicks, conversions, report, backup`. Atalhos: `daily`, `publish`, `report`, `all`.

## Estrutura

```
config/              niches.yaml (+ schema), marcas, ofertas manuais (CSV), domínios permitidos,
                     calendar.yaml, coupons.csv, finance.yaml (agentes)
src/run.py           ponto de entrada: passos, falha isolada por nicho, modo demo
src/config/          modelos do niches.yaml, merge de defaults, validador
src/common/          banco (Postgres/SQLite), logging com redação, Telegram, segredos, LLM (teto de custo), utilitários
src/sources/         Shopee API, CSV manual, fonte falsa
src/pipeline/        ingest (bronze), transform (silver), score (gold), content (pauta + copy)
src/content/         marca, copy (template/Claude), legenda + regras, arte
src/approval.py      prévias e botões · src/commands.py: comandos do bot
src/publishers/      publicador do Telegram
src/tracking/        Cloudflare (KV/D1), cliques e conversões
src/reports/         relatório diário, semanal (domingo) e fechamento mensal
src/agents/          calendário, vigia de preço, conformidade, cupons, sentinela/reciclador, links,
                     mercado/horários/A-B (insights) e conciliador/contador (finance)
src/backup.py        backup e restauração
sql/migrations/      schema (comum) + segurança (só Postgres: papéis, RLS, sem DELETE)
worker/              redirecionador /go (TypeScript, Cloudflare)
scripts/             checagem de workflows, inventário de segredos, restauração de backup
tests/               testes sem rede (fakes); `-m security` para a suíte de segurança
.github/workflows/   ci, security, garimpo (produção: verify + daily/publish/report/backup)
docs/                SETUP, agentes, dados, desenvolvimento, runbook, segredos, segurança, ADRs
```

## Custos

| Item | Custo |
|---|---|
| GitHub Actions (repo privado) | Grátis até 2.000 min/mês. Uso estimado com 2 nichos: ≈ 6 execuções/dia × 1,5–3 min + trava ≈ **350–500 min/mês**; cada nicho a mais soma ≈ 30–60 min/mês |
| Supabase / Cloudflare | Grátis nos limites de [ARQUITETURA.md §5](ARQUITETURA.md#5-orçamento-do-plano-gratuito) |
| Claude (opcional) | ≈ US$ 0,01 por post (Sonnet + Haiku); teto configurável |
| Domínio `.com.br` | ≈ R$ 40/ano (só para `/go` ou lojas com domínio próprio) |
| GitHub Pro (opcional) | US$ 4/mês, só para proteger a `main` em repositório privado |

## Suposições

- Horário de Brasília (`America/Sao_Paulo`); marca, domínio e @ ainda a confirmar (tudo é configuração).
- Nichos ativos: `casa` e `pet`; os outros 6 são `candidate` (coletados e ranqueados, sem posts).
- Publicação só no Telegram nesta versão; Instagram e TikTok ficam `enabled: false`.
- O campo `sales` da Shopee é tratado como contador acumulado; se for uma janela móvel, o score cai no nível de vendas ([score.py](src/pipeline/score.py)).
- Os campos da Shopee Open API devem ser conferidos no explorador GraphQL do painel antes de confiar nos números ([shopee.py](src/sources/shopee.py)).

## Próximas fases

Do roadmap ([ARQUITETURA.md §8](ARQUITETURA.md#8-roadmap-orientado-a-receita)) e das ideias de [agentes](docs/agentes.md#ideias-de-agentes-futuros):

1. Instagram (feed, reels, stories) e TikTok (rascunho).
2. Lojas por nicho (Lojista) e Monitor de concorrentes.
3. Consultor: experimentos sugeridos em linguagem natural a partir dos números da Sentinela, do Analista e do A/B.
4. Webhook do Telegram, para o botão responder na hora ([ADR 0002](docs/adr/0002-aprovacao-por-polling.md)).

Histórico de mudanças: [CHANGELOG.md](CHANGELOG.md).
