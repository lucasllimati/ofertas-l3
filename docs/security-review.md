# Revisão de segurança: 2026-10-23

Revisão completa do Garimpo com base no OWASP Top 10:2025, com foco em quatro coisas:

1. **seus dados**: tokens, banco, histórico;
2. **suas vendas**: comissões, atribuição e números confiáveis;
3. **o processo**: aprovação, publicação, execução automática;
4. **as regras dos anúncios**: CONAR, CDC e termos dos programas de afiliado.

Política geral e modelo de ameaças: [SECURITY.md](../SECURITY.md).

## Como foi feita

Cada entrada não confiável foi rastreada até onde é usada. No Garimpo, as entradas são:

| Entrada | Quem controla | Onde chega |
|---|---|---|
| Título, preço, "de", foto e nota do produto (API da Shopee) | **O vendedor** na Shopee | Legenda, arte, prompt do LLM, score |
| CSV de ofertas manuais | Você | Mesmos lugares |
| Mensagens e botões no bot | **Qualquer pessoa** no Telegram | Aprovação, comandos, auditoria |
| Cliques em `/go` | **Qualquer pessoa** na internet | D1 → métricas → score |
| Saída do LLM | Influenciável pelo vendedor (via título) | Legenda |
| Relatório de conversões | Shopee | Vendas atribuídas |
| Entradas do Run workflow | Quem tem escrita no repositório | Argumentos do programa |
| Arquivo de backup | Você (ou quem o adulterar) | Restauração no banco |

## Achados e correções

Os 13 achados abaixo foram **corrigidos e testados nesta revisão**. Os testes ficam em [tests/test_hardening.py](../tests/test_hardening.py), em [worker/test/lib.test.ts](../worker/test/lib.test.ts) e nos testes de conteúdo.

| # | Gravidade | Categoria | Onde | Problema | Correção |
|---|---|---|---|---|---|
| 1 | **Alta** | A05 Injeção / A06 Design | [copy.py](../src/content/copy.py), [caption.py](../src/content/caption.py) | O título do produto é escrito pelo **vendedor** e ia direto para a legenda (template) ou para o LLM. Um título com `bit.ly/...`, `@perfil` ou telefone virava link clicável no **seu** canal: desvio de comissão ou golpe com a sua marca | Todo texto de copy (template e LLM) passa por `clean_text`, que remove links, domínios, @perfis, telefones e preços. A checagem final da legenda recusa qualquer link, @perfil ou telefone visível e exige exatamente um link (o "Ver oferta" gerado pelo código) |
| 2 | **Alta** | Regras de anúncio (CDC art. 37) | [content.py](../src/pipeline/content.py), [approval.py](../src/approval.py) | O preço riscado e o selo "-38%" vinham do desconto **declarado pelo vendedor**. Inflar o "de" antes da promoção é o golpe mais comum, e divulgar "de/por" falso é publicidade enganosa, com risco para você | O "de" só aparece se o sistema **viu** o produto custando esse valor (tolerância de 2%) nos últimos 30 dias. A arte usa o mesmo valor verificado, gravado em `content_item.price_original_shown` |
| 3 | **Alta** | A08 Integridade de dados | [run.py](../src/run.py) | `--demo` herdava o `DATABASE_URL` do ambiente. Com a variável exportada no terminal (o guia ensinava isso para a migration), a demo gravava produtos falsos e marcava posts falsos como publicados **no banco de produção**, corrompendo métricas e vendas | A demo usa só `DEMO_DATABASE_URL` ou o SQLite local; nunca o `DATABASE_URL`. Teste com uma URL de produção falsa no ambiente |
| 4 | **Alta** | Perda de dados | Infra / [backup.py](../src/backup.py) | **O Supabase Free não faz backup automático** (a documentação anterior dizia que fazia). Um erro, a exclusão do projeto ou uma invasão apagariam todo o histórico de vendas | Novo passo `backup` semanal: exporta o histórico, criptografa com AES-256 (`BACKUP_PASSPHRASE`), guarda como artefato privado por 90 dias e apaga o arquivo aberto. Sem a senha, não roda. Restauração com [scripts/restore_backup.py](../scripts/restore_backup.py), que aceita só tabelas e colunas conhecidas (backup adulterado não vira SQL) |
| 5 | **Média** | A10 Condições excepcionais | [approval.py](../src/approval.py) | Se uma única atualização do Telegram desse erro (comando cuja resposta falha, botão de nicho removido do YAML), o offset não avançava: a mesma atualização falhava para sempre e **nenhuma aprovação passava mais** | Cada atualização é isolada: o erro é registrado (`update_failed`), você recebe "toque de novo" e a fila segue |
| 6 | **Média** | A01 Controle de acesso | [0004_append_only.pg.sql](../sql/migrations/0004_append_only.pg.sql) | O usuário do pipeline podia apagar vendas, cliques, posts e auditoria. Com o `DATABASE_URL` vazado, alguém apagaria a prova das comissões e o rastro da invasão | `app_writer` sem `DELETE` em `conversion`, `click_event`, `content_item` e `audit_log`; `audit_log` somente-inclusão. Testado em Postgres |
| 7 | **Média** | A04 Falhas criptográficas | [db.py](../src/common/db.py) | O padrão do driver é `sslmode=prefer`, que aceita cair para conexão **sem criptografia** se alguém no meio do caminho interferir | Fora de localhost, `sslmode=require` (a não ser que a URL já defina outro modo) |
| 8 | **Média** | Regras de anúncio | [copy.py](../src/content/copy.py) | O template escrevia "Muito vendido no marketplace" para qualquer produto com vendas, até 5 | Só com número real e arredondado **para baixo**: "Mais de 1.000 vendidos na loja" (a partir de 100) |
| 9 | **Média** | Regras de anúncio | [copy.py](../src/content/copy.py) | Promessas do vendedor ("frete grátis", "envio imediato", "promoção", "últimas unidades", "cupom") apareciam no post sem verificação | Removidas do texto pelo `clean_text` |
| 10 | **Média** | Regras de anúncio (CONAR) | [caption.py](../src/content/caption.py) | "#publi · link de afiliado" ficava na última linha, depois do link | Identificação na **primeira linha**; a checagem reprova legenda sem ela no topo. A arte mantém o "#publi" no rodapé |
| 11 | **Baixa** | A06 Design (fraude de clique) | [worker/src/lib.ts](../worker/src/lib.ts) | Robôs, geradores de prévia e requisições HEAD contavam como clique, inflando o EPC e distorcendo o score | Clique só é contado em GET de navegador; robôs são redirecionados sem contar. O user-agent é lido em memória e nunca gravado |
| 12 | **Baixa** | A09 Alertas | [reports/daily.py](../src/reports/daily.py) | Tentativas de terceiros (botão, comando, assinatura inválida) eram registradas, mas ninguém era avisado | O relatório diário tem um bloco "🔐 Segurança (24 h)" com a contagem por tipo |
| 13 | **Baixa** | A02 Configuração / A04 | [render.py](../src/content/render.py), [logging.py](../src/common/logging.py) | A foto do vendedor podia redirecionar para HTTP ou ser uma "bomba" de descompressão; variáveis `*PASSPHRASE*` não eram mascaradas nos logs | Redirecionamento final precisa ser HTTPS; limite de 40 MP por imagem; `PASSPHRASE` entra no filtro de redação |

**Automação permanente (14):** a suíte `pytest -m security` roda em todo PR, todo push e toda semana, em SQLite e em Postgres real (pular teste de banco é falha), e o workflow de produção só executa um commit que passou em `ci` e `security` (job `verify`). Detalhes em [SECURITY.md → Verificação automática](../SECURITY.md#verificação-automática-sempre).

Também passaram a ser testados no CI: **RLS ligado em todas as tabelas**, para que uma migration nova sem RLS reprove o CI, e que o usuário do pipeline **não consegue** apagar vendas, alterar a auditoria nem dropar tabelas.

## O que já estava correto (verificado)

| Área | Verificação |
|---|---|
| A05 SQL injection | 100% das queries com parâmetros; os únicos nomes montados no SQL vêm de constantes do código |
| A05 HTML na legenda | Todo texto externo passa por `html.escape`; a URL do link também |
| A01 Open redirect (`/go`) | Destino só do KV, conferido contra o nicho da URL e a allowlist de domínios; só HTTPS, sem usuário/senha na URL; query string ignorada |
| A01/A07 Aprovação | Botões assinados com HMAC-SHA256 (comparação em tempo constante); só `TELEGRAM_ADMIN_USER_IDS`; comandos só no chat de admin; prévia expira em 72 h; sem admin configurado, nada é aceito (fail-closed) |
| A04 Segredos | Nenhum no código nem no histórico (gitleaks); logs mascaram tokens, senhas, assinaturas e URLs de banco; o erro do cliente do Telegram nunca carrega a URL com o token |
| A03 Supply chain | Actions fixadas por SHA; `uv.lock` com hashes; `npm ci --ignore-scripts`; gitleaks por binário com checksum; pip-audit, npm audit e semgrep no CI; Dependabot agrupado |
| CI | `permissions: contents: read`; sem `pull_request_target` nem `secrets: inherit`; entradas do Run workflow vão por `env` (sem injeção no shell) e são validadas pelo programa |
| Publicação | Reivindicação atômica (`approved → publishing`) antes de enviar: reexecução não duplica; erro ambíguo não é reenviado; circuit breaker pausa o canal após 3 falhas |
| LLM | Dados do produto delimitados; o modelo nunca recebe preço, link nem segredo; saída em JSON com schema; revisão por regras + segundo modelo; teto de custo por nicho e global; qualquer falha cai no template |
| LGPD (cliques) | Sem IP e sem user-agent gravados; só nicho, canal, post, horário e país |

Categorias sem superfície no projeto: **A07** login/senha de usuário (não há login próprio) e **A08** desserialização insegura (só JSON e `yaml.safe_load`).

## Regras dos anúncios: o que o código garante e o que é com você

| Regra | Garantido pelo código | Sua responsabilidade |
|---|---|---|
| Identificar publicidade (CONAR) | "#publi · link de afiliado" na 1ª linha de todo post; "#publi" na arte | Manter a descrição do canal dizendo que há links de afiliado |
| Preço e "de/por" verdadeiros (CDC art. 37) | Preço da consulta, com data e "sujeito a alteração"; "de" só se observado em 30 dias | Não editar posts à mão com preço ou desconto não verificado |
| Não prometer o que o produto não entrega | Termos de saúde, cura, emagrecimento, "original" e "garantido" bloqueados; promessas do vendedor removidas; LLM só com fatos dos dados | Revisar as prévias. A aprovação humana é a última barreira |
| Produtos proibidos | `blocked_categories` por palavra no título/categoria (sem diferença de acento) | Ampliar a lista do nicho. A checagem é por palavra, e um título sem a palavra passa |
| Termos da Shopee, ML e Amazon | Só APIs oficiais; links com sub IDs do seu cadastro; sem automação de navegador | Postar só em canais **seus**; não fazer spam em grupos de terceiros; não comprar pelo próprio link; não anunciar com a marca da loja como se fosse a loja |
| Golpes no seu canal | Nenhum link, @perfil ou telefone de terceiro chega à legenda | Não colar no CSV links que não sejam do seu painel |
| LGPD | Nenhum dado de quem segue o canal é coletado | Se no futuro coletar e-mail ou WhatsApp, publicar uma política de privacidade |

## Riscos que continuam (e como reduzir)

| Risco | Por que continua | O que fazer |
|---|---|---|
| Invasão da sua conta do **Telegram** | Quem entra nela aprova posts | Ative a verificação em duas etapas do Telegram (SETUP §1.2) |
| Invasão da sua conta do **GitHub** | Dá acesso aos secrets e aos workflows | 2FA com app autenticador; revise Settings → Sessions |
| `main` sem proteção | O GitHub Free não permite em repositório privado | GitHub Pro (US$ 4/mês) ou disciplina de PR com os 3 checks verdes |
| Aprovação automática (`auto_above_score`) | Tira o humano da última barreira | Use só em nicho maduro e acompanhe o bloco de segurança do relatório |
| Fraude de clique por robô sofisticado | Robôs que se passam por navegador não são detectáveis só pelo user-agent | Avalie o EPC pelas **vendas** (Shopee), não só pelos cliques; o score usa comissão real |
| Categoria proibida com título "limpo" | A checagem é por palavra | Revisar prévias; ampliar `blocked_categories` |
| Rate limit do Worker por isolate | Limite em memória, por instância da Cloudflare | Se houver abuso, ativar uma regra de rate limiting no painel da Cloudflare (Security → WAF) |
| Ferramentas de varredura sem lockfile (semgrep via `uvx`) | Instalado na hora, numa versão fixa, mas com dependências livres | Roda sem secrets e só com leitura; risco baixo |
| Backup no próprio GitHub | Se a conta cair, o backup vai junto | Baixe o artefato mensalmente e guarde fora (já vem criptografado) |
| Telegram ids de terceiros no `audit_log` | São registrados nas tentativas bloqueadas | Dado mínimo e necessário para segurança; não é compartilhado |

## O que não foi possível verificar daqui

| Item | Como verificar |
|---|---|
| Configuração real do Supabase (Data API, schemas expostos, membros) | SETUP §5.5: confira `garimpo` fora de "Exposed schemas" e só você em Members |
| Campos reais da API da Shopee | Explorador GraphQL do painel (SETUP §6.2) |
| Permissões reais dos tokens criados (Cloudflare, Anthropic) | Revise cada token no painel conforme SETUP §9 e §10 |
| Configurações da conta do GitHub (2FA, sessões, apps autorizados) | Settings → Password and authentication e Settings → Applications |
| Comportamento em produção do backup | Rode `backup` manualmente uma vez e restaure num banco de teste (runbook) |

Não existe sistema "seguro"; existe o que foi verificado. Esta revisão cobre o código e a configuração do repositório na data acima.
