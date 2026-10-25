# Segurança

Segurança é requisito funcional deste projeto. Achou um problema? Não abra issue pública: fale direto com o dono do repositório.

Última revisão completa, com achados, correções e riscos que continuam: [docs/security-review.md](docs/security-review.md).

## Modelo de ameaças

| Ativo | Ameaça | Controle implementado |
|---|---|---|
| Tokens (Telegram, Shopee, Cloudflare, banco, Anthropic) | Vazamento em commit, log, prompt ou build | Só em GitHub Secrets; `gitleaks` no pre-commit e no CI (histórico completo); logger JSON com redação por valor e por padrão ([logging.py](src/common/logging.py)); erros do cliente Telegram nunca carregam a URL com token; nada de segredo em prompt de LLM |
| Contas de afiliado e canais | Suspensão por violar termos | Só APIs oficiais; limites diários por canal; circuit breaker pausa o canal após 3 falhas seguidas |
| Redirecionador `/go` | Open redirect para phishing | Destino só do KV, conferido contra o nicho da URL e a allowlist ([allowed_domains.json](config/allowed_domains.json)); só `https`, sem credenciais na URL; query string ignorada; testes em [worker/test](worker/test/lib.test.ts) |
| Aprovação e comandos do bot | Terceiro aprovar post ou pausar canal | `callback_data` assinado com HMAC-SHA256 e comparação em tempo constante; só ids em `TELEGRAM_ADMIN_USER_IDS`; comandos só no chat de admin; prévia expira em 72 h; tudo em `audit_log`; tentativas de terceiros contadas no relatório diário |
| Fila de aprovação | Uma atualização com erro travar todas as aprovações | Cada atualização é isolada; erro registrado (`update_failed`) e aviso "toque de novo" |
| Texto do vendedor (título, "de", promessas) | Link, @perfil ou telefone de terceiro no seu canal; "de/por" inflado; promessa não verificada | `clean_text` em toda copy (template e LLM); legenda com exatamente um link (o do código); "de" só se observado no histórico de 30 dias; promessas do vendedor removidas |
| Métricas de vendas e cliques | Robôs inflando cliques; demo gravando no banco de produção | Worker só conta GET de navegador; demo nunca usa `DATABASE_URL` |
| Banco | Acesso indevido, SQL injection, perda de dados | Tabelas no schema `garimpo` (fora da API pública do Supabase); papel `app_writer` sem DDL; `app_reader` só em views e com `statement_timeout`; RLS em todas as tabelas; `anon`/`authenticated` sem acesso; 100% das queries parametrizadas; TLS obrigatório (`sslmode=require`); pipeline sem `DELETE` em vendas, cliques, posts e auditoria (`audit_log` somente-inclusão); backup semanal próprio criptografado com AES-256 (o Supabase Free não faz backup) |
| Agentes com LLM | Prompt injection via título de produto | Dados externos delimitados em `<dados_produto>` com instrução de ignorar comandos; LLM só escreve título/bullets em JSON validado por schema; preço, link e avisos são montados pelo código; revisão por regras + segundo modelo; LLM sem ferramentas e sem acesso a banco ou publicação |
| Conteúdo publicado | HTML injetado a partir de dado externo | Legenda montada com `html.escape` em todo campo externo; sinais `< >` removidos da copy |
| Regras de anúncio | Publicidade sem identificação ou enganosa (CONAR, CDC) | "#publi · link de afiliado" na 1ª linha, checado antes de publicar; preço com data e "sujeito a alteração"; afirmação de vendas só com número real arredondado para baixo; termos proibidos bloqueados |
| Pipeline de CI | Supply chain, action comprometida | Actions fixadas por SHA; `permissions: contents: read`; `persist-credentials: false`; sem `pull_request_target`; segredos só via `env`; `uv.lock` com hashes; `npm ci --ignore-scripts`; Dependabot; `pip-audit`, `npm audit` e semgrep semanais |
| Dados de clique | LGPD | Sem IP, sem user-agent; só nicho, canal, post, horário e país; IP usado apenas em memória para rate limit |

## Verificação automática (sempre)

Três barreiras rodam sozinhas e não dependem de você lembrar:

| Quando | O quê | Se falhar |
|---|---|---|
| Todo PR e todo push na `main` | `ci`: lint, schema, checagem de workflows, **todos os testes em SQLite e em Postgres** (`REQUIRE_POSTGRES=1`: teste de banco pulado vira falha), demo ponta a ponta, testes do Worker | PR fica vermelho |
| Todo PR, todo push na `main` e toda segunda | `security`: gitleaks no histórico, pip-audit, npm audit, semgrep, checagem de workflows, inventário de segredos e a **suíte de segurança e de regras de anúncio** (`pytest -m security`) em SQLite e em Postgres real | PR fica vermelho; a falha semanal avisa sobre CVE nova ou segredo perto de expirar |
| **Toda execução de produção** (`garimpo.yml`) | Job `verify`: confere pela API do GitHub que **o commit exato** passou em `ci` e `security` (espera até 12 min se ainda estiverem rodando) | Produção não roda. Nada é coletado, aprovado ou publicado com código não verificado |

O `check_workflows.py` recusa um `garimpo.yml` sem o job `verify`, então a trava não pode ser removida por engano.

Para incluir um teste novo na suíte de segurança, ponha-o em `tests/test_security.py`, `tests/test_hardening.py` ou `tests/test_production.py`, ou use no nome uma das palavras de `SECURITY_KEYWORDS` em [tests/conftest.py](tests/conftest.py). Para rodar localmente: `uv run pytest -m security`.

## Regras do repositório

- Repositório privado e 2FA obrigatório. `main` protegida (PR + checks `python`, `worker` e `scan` verdes, sem force push nem deleção) quando a conta tiver GitHub Pro; no plano Free o GitHub não permite proteção em repositório privado, então a regra é seguida por processo: tudo entra por PR com os 3 checks verdes.
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

## Checklist de segurança: revisão de 2026-10-23

Detalhes em [docs/security-review.md](docs/security-review.md).

- [x] 13 achados corrigidos (texto do vendedor no canal, "de/por" não verificado, demo no banco de produção, falta de backup, fila de aprovação travável, exclusão de vendas pelo pipeline, TLS opcional, afirmações de venda e promessas não verificadas, identificação publicitária no fim, cliques de robô, alertas de segurança, imagem e redação de logs)
- [x] RLS em todas as tabelas e bloqueio de `DELETE`/`UPDATE` indevido testados em Postgres real
- [x] Backup criptografado testado de ponta a ponta (gerar → cifrar → decifrar → restaurar)
- [x] `gitleaks` limpo (histórico e arquivos), semgrep 0 achados, `pip-audit` e `npm audit` sem vulnerabilidades
- [x] 86 testes Python passando (mais 2 só de Postgres, que passaram em Postgres real) e 8 do Worker, mais a demo ponta a ponta
