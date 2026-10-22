# Segurança

Segurança é requisito funcional deste projeto. Achou um problema? Não abra issue pública: fale direto com o dono do repositório.

## Modelo de ameaças

| Ativo | Ameaça | Controle implementado |
|---|---|---|
| Tokens (Telegram, Shopee, Cloudflare, banco, Anthropic) | Vazamento em commit, log, prompt ou build | Só em GitHub Secrets; `gitleaks` no pre-commit e no CI (histórico completo); logger JSON com redação por valor e por padrão ([logging.py](src/common/logging.py)); erros do cliente Telegram nunca carregam a URL com token; nada de segredo em prompt de LLM |
| Contas de afiliado e canais | Suspensão por violar termos | Só APIs oficiais; limites diários por canal; circuit breaker pausa o canal após 3 falhas seguidas |
| Redirecionador `/go` | Open redirect para phishing | Destino só do KV, conferido contra o nicho da URL e a allowlist ([allowed_domains.json](config/allowed_domains.json)); só `https`, sem credenciais na URL; query string ignorada; testes em [worker/test](worker/test/lib.test.ts) |
| Aprovação e comandos do bot | Terceiro aprovar post ou pausar canal | `callback_data` assinado com HMAC-SHA256 e comparação em tempo constante; só ids em `TELEGRAM_ADMIN_USER_IDS`; comandos só no chat de admin; prévia expira em 72 h; tudo em `audit_log` |
| Banco | Acesso indevido, SQL injection, perda de dados | Tabelas no schema `garimpo` (fora da API pública do Supabase); papel `app_writer` sem DDL; `app_reader` só em views e com `statement_timeout`; RLS em todas as tabelas; `anon`/`authenticated` sem acesso; 100% das queries parametrizadas; backup diário do provedor |
| Agentes com LLM | Prompt injection via título de produto | Dados externos delimitados em `<dados_produto>` com instrução de ignorar comandos; LLM só escreve título/bullets em JSON validado por schema; preço, link e avisos são montados pelo código; revisão por regras + segundo modelo; LLM sem ferramentas e sem acesso a banco ou publicação |
| Conteúdo publicado | HTML injetado a partir de dado externo | Legenda montada com `html.escape` em todo campo externo |
| Pipeline de CI | Supply chain, action comprometida | Actions fixadas por SHA; `permissions: contents: read`; `persist-credentials: false`; sem `pull_request_target`; segredos só via `env`; `uv.lock` com hashes; `npm ci --ignore-scripts`; Dependabot; `pip-audit`, `npm audit` e semgrep semanais |
| Dados de clique | LGPD | Sem IP, sem user-agent; só nicho, canal, post, horário e país; IP usado apenas em memória para rate limit |

## Regras do repositório

- Repositório privado, 2FA obrigatório, `main` protegida (PR + CI verde, sem force push).
- `pre-commit install` antes do primeiro commit (gitleaks, ruff, arquivos grandes, chaves privadas).
- Segredos novos: entrada em [docs/secrets.md](docs/secrets.md) com escopo mínimo e data de expiração. O `security.yml` falha se algum segredo usado não estiver no inventário ou se algum expirar em 7 dias.
- Rotação a cada 90 dias e procedimento de vazamento: [docs/runbook.md](docs/runbook.md#vazamento-de-chave).

## Checklist de segurança: versão 0.1 (fases 1 e 2 + publicação no Telegram)

- [x] Nenhum segredo no diff nem no histórico: `gitleaks git` limpo; `gitleaks dir` sem achados fora de `.venv`/`node_modules`
- [x] Segredos documentados em `docs/secrets.md` com escopo mínimo (`scripts/check_secrets_inventory.py` passa)
- [x] Tabelas com RLS e grants por papel (testado: usuário `app_writer` roda o pipeline inteiro e recebe `InsufficientPrivilege` em DDL)
- [x] Entradas externas validadas (Pydantic, allowlist de domínios, parse defensivo) e conteúdo externo nunca tratado como instrução
- [x] Logs sem dados sensíveis (testes de redação em `tests/test_logging.py`)
- [x] Dependências auditadas: `pip-audit` sem vulnerabilidades; `npm audit` sem altas (wrangler atualizado para 4.149.0 por CVE no `sharp`)
- [x] Idempotência e falha isolada por nicho testadas (`tests/test_pipeline.py`, `tests/test_run.py`, `tests/test_approval_publish.py`), em SQLite e em Postgres
