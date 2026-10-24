# Guia de desenvolvimento

Como o código está organizado, como uma execução funciona por dentro e como mudar o projeto sem quebrar segurança nem produção.

## Preparar a máquina

```bash
uv sync                      # Python 3.12 + dependências (uv.lock com hashes)
uv tool install pre-commit   # uma vez
pre-commit install           # gitleaks + ruff antes de cada commit
uv run pytest                # tudo verde
uv run python -m src.run --demo --steps all
```

Para o Worker: `cd worker && npm ci --ignore-scripts && npm test`.

## Mapa do código

| Caminho | Responsabilidade |
|---|---|
| [src/run.py](../src/run.py) | Entrada: lê argumentos, monta o contexto, expande atalhos (`daily`, `publish`, `report`, `all`) e roda os passos com falha isolada por nicho |
| [src/context.py](../src/context.py) | `AppContext`: tudo que um passo recebe (config, banco, data, relógio, clientes externos) |
| [src/config/](../src/config/) | Modelos Pydantic do `niches.yaml`, merge de defaults, validador e JSON Schema |
| [src/common/](../src/common/) | Banco (Postgres/SQLite), logging com redação, cliente do Telegram, segredos, utilitários |
| [src/sources/](../src/sources/) | Fontes de ofertas: Shopee API, CSV manual, fonte falsa |
| [src/pipeline/](../src/pipeline/) | Rastreador (`ingest`), Analista (`transform`, `score`), Editor de pauta (`content`) |
| [src/content/](../src/content/) | Marca, copy (template/LLM), legenda e regras, arte |
| [src/approval.py](../src/approval.py), [src/commands.py](../src/commands.py) | Porteiro: prévias, botões, respostas e comandos |
| [src/publishers/](../src/publishers/) | Publicador do Telegram |
| [src/tracking/](../src/tracking/) | Cloudflare (KV/D1), cliques e conversões |
| [src/reports/](../src/reports/) | Relatório diário |
| [src/backup.py](../src/backup.py) | Backup e restauração |
| [worker/](../worker/) | Redirecionador `/go` (TypeScript, Cloudflare) |
| [scripts/](../scripts/) | Checagem de workflows, inventário de segredos, restauração de backup |
| [sql/migrations/](../sql/migrations/) | Schema; `*.pg.sql` só roda em Postgres |
| [tests/](../tests/) | Testes (sem rede; fakes para Shopee, Telegram e LLM) |

Responsabilidade de cada agente: [agentes.md](agentes.md). Tabelas: [dados.md](dados.md).

## Como uma execução funciona

1. `main` carrega o `.env` (exceto na demo), valida o `niches.yaml` e monta o `AppContext`. Sem segredo obrigatório, para e mostra **só os nomes** que faltam.
2. `expand_steps` transforma o atalho em passos e coloca `migrate` no começo (idempotente).
3. `run_steps` roda cada passo:
   - passos **por nicho** (`ingest`, `transform`, `score`, `content`, `preview`, `publish`) rodam uma vez para cada nicho no status certo;
   - cada execução de passo é registrada em `pipeline_run`;
   - uma exceção marca aquele passo/nicho como `failed` e **o resto continua**.
4. No fim, se houve falha: alerta no Telegram e saída com código 1 (o GitHub marca a execução em vermelho).

No GitHub, o workflow [garimpo.yml](../.github/workflows/garimpo.yml) roda o `verify` (commit verde em `ci` e `security`) e só então o passo do horário.

## Convenções (o CI cobra a maioria)

| Regra | Por quê |
|---|---|
| Nenhum `if nicho == "..."`; comportamento vem do `niches.yaml` | Adicionar nicho é configuração, não código |
| SQL sempre com parâmetros `?`; nomes no SQL só de constantes do código | SQL injection |
| SQL portátil (TEXT/INTEGER/REAL, `ON CONFLICT`); o que é só do Postgres vai em `*.pg.sql` | Mesmos testes em SQLite e Postgres |
| Toda tabela nova com RLS (a migration `0002` liga para as existentes; tabela nova precisa de `ENABLE ROW LEVEL SECURITY` + política) | `test_every_table_has_rls` reprova o CI |
| Escrita idempotente (ids determinísticos, `ON CONFLICT`, transições com `WHERE status = ...`) | Reexecutar o dia não duplica nada |
| Todo acesso externo atrás de uma interface, com fake nos testes | Testes sem rede e determinísticos |
| Texto externo (título, saída do LLM) passa por `clean_text` e `html.escape`; legenda passa por `compliance_issues` | Golpe e regras de anúncio |
| LLM: JSON com schema, dados delimitados, teto de custo, fallback sem LLM; nunca decide preço, link, ranking nem publicação | Custo e prompt injection |
| Segredo só por nome (`<REF>_TOKEN`); nunca em log, prompt, URL logada ou arquivo versionado | Vazamento |
| Actions fixadas por SHA, `permissions` mínimas, sem `secrets: inherit` | Supply chain (`check_workflows.py`) |
| Teste de segurança novo: em `test_security.py`/`test_hardening.py` ou com palavra de `SECURITY_KEYWORDS` no nome | Entra no `pytest -m security` |

Linha de até 120 colunas, `ruff` para lint e formatação. Links internos da documentação são conferidos no CI (`uv run python scripts/check_docs_links.py`).

## Tarefas comuns

### Adicionar um passo ou agente
1. Função `def meu_passo(ctx: AppContext, niche: Niche) -> dict` (ou sem `niche`, se for global) em `src/<área>/`.
2. Registre em `build_steps` ([src/run.py](../src/run.py)); se for por nicho, use `per_niche(fn, ACTIVE)` ou `MONITORED`.
3. Inclua no atalho certo em `ALIASES` ou crie um cron no `garimpo.yml`. Se criar cron, ajuste o `case` que escolhe o passo pelo texto do cron.
4. Retorne um dict pequeno com contagens: ele vai para o log e para `pipeline_run`.
5. Testes em `tests/`, documentação em [agentes.md](agentes.md).

### Mudar o banco
1. Arquivo novo em `sql/migrations/` com número seguinte (`0005_...sql`, ou `.pg.sql` se for só Postgres). Nunca edite migration já aplicada.
2. Rode os testes em Postgres (abaixo).
3. **Em produção**, rode `--steps migrate` com o usuário **dono** antes do merge: o usuário do pipeline não tem permissão de DDL e a execução agendada falharia.

### Adicionar uma fonte de ofertas
Implemente `search(keyword, limit) -> list[Offer]` (e, se houver, `short_link` e `conversions`) como em [sources/shopee.py](../src/sources/shopee.py), com teste usando `httpx.MockTransport`. Domínios novos de link vão em [config/allowed_domains.json](../config/allowed_domains.json), que vale para o pipeline e para o Worker.

## Testes

```bash
uv run pytest                    # tudo (SQLite)
uv run pytest -m security        # só a suíte de segurança e regras de anúncio
uv run pytest tests/test_pipeline.py -k idempotent
```

Testes em Postgres local: suba um Postgres (Docker: `docker run -e POSTGRES_PASSWORD=x -p 5432:5432 postgres:16`) e rode:

```bash
TEST_DATABASE_URL=postgresql://postgres:x@localhost:5432/postgres REQUIRE_POSTGRES=1 uv run pytest
```

| Arquivo | Cobre |
|---|---|
| `test_config.py` | `niches.yaml`, merge, validação, segredos exigidos, schema |
| `test_shopee.py`, `test_manual.py` | Fontes (assinatura, parse, retentativas, CSV) |
| `test_score.py`, `test_pipeline.py` | Score, janelas de venda, idempotência, falha isolada, SCD2, cooldown |
| `test_content.py` | Legenda, conformidade, LLM (fake), arte |
| `test_approval_publish.py` | Prévias, botões, autorização, publicação, limites, circuit breaker |
| `test_tracking_report.py` | Cliques, conversões, relatório, KV |
| `test_hardening.py`, `test_security.py` | Revisão de segurança, RLS e permissões (Postgres), backup, workflows |
| `test_operation.py` | Healthcheck dos canais, alertas, CSV de vendas, falhas do publicador |
| `test_run.py` | Atalhos, segredos ausentes, demo ponta a ponta |
| `worker/test/` | Redirecionador: open redirect, robôs, rate limit |

## Fluxo de mudança

1. Branch a partir da `main` (`git switch -c minha-mudanca`).
2. Commit (o pre-commit roda gitleaks e ruff).
3. PR → `ci` (testes em SQLite e Postgres, demo, Worker) e `security` (gitleaks, pip-audit, npm audit, semgrep, suíte de segurança).
4. Merge só com os 3 checks verdes. Sem GitHub Pro a `main` não é protegida: a disciplina é sua, mas a trava `verify` impede que um commit vermelho rode em produção.
5. Mudou algo que você usa no dia a dia? Atualize o [SETUP](SETUP.md), o [runbook](runbook.md) ou o [CHANGELOG](../CHANGELOG.md).
