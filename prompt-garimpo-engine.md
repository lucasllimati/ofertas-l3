# Prompt — Garimpo Engine (para colar no Claude Code)

> Repositório: **`garimpo-engine`** (privado) · Marca: **Garimpo**

> Cole este prompt inteiro no Claude Code, na raiz do repositório.
> Ele constrói o projeto **por fases** e para para sua revisão ao final de cada uma.

## Estado atual (leia antes de tudo)

As **versões 0.1 a 0.3 já estão implementadas e testadas** neste repositório (histórico em `CHANGELOG.md`; agentes e status em `docs/agentes.md`; índice da documentação em `docs/README.md`): fundação e segurança, dados
(Shopee API + CSV manual, bronze/silver/gold, score), conteúdo (copy template/Claude, arte, regras de
conformidade), aprovação no Telegram, publicação no Telegram, rastreio (`subIds`, Worker `/go`, D1),
conversões e relatório diário. Veja `README.md`, `ARQUITETURA.md` e as decisões em `docs/adr/`.

Ao continuar, **não reescreva o que existe**: leia o código, rode `uv run pytest` e
`uv run python -m src.run --demo --steps all`, e siga a partir da próxima fase pendente em
"Fases e critérios de aceite". Decisões já tomadas que divergem do texto original:

- Arte do feed com Pillow, não Playwright (ADR 0003). Playwright/FFmpeg só para story e vídeo.
- Aprovação lida por `getUpdates` no início de cada execução (ADR 0002). Webhook no Worker é fase futura.
- Pipeline em passos determinísticos (`src/run.py`) sobre `content_item`; a fila `agent_event` entra
  quando houver agentes assíncronos de verdade (cupons, mercado, concorrentes).
- SQL portátil Postgres/SQLite com datas em TEXT; schema `garimpo` no Postgres (ADR 0004).
- Cliques no D1, mapa de links no KV (ADR 0005).
- Produção só roda commit verde em `ci` e `security` (job `verify`, ADR 0006); backup semanal próprio e cifrado (ADR 0007).
- Regras de anúncio já no código: copy limpa de links/@/telefone, "de/por" só verificado, #publi na 1ª linha (ver `docs/security-review.md`). Mantenha-as ao criar canais novos (Instagram, TikTok, lojas).

---

## Papel

Você é um engenheiro de software, dados e segurança sênior. Vai construir comigo, do zero, um sistema de afiliados automatizado chamado **Garimpo Engine** (repositório privado `garimpo-engine`), sob a marca guarda-chuva **Garimpo**, que opera **vários nichos ao mesmo tempo** (cada um com loja, Instagram, TikTok e canal de Telegram próprios) sobre um **único processo comum**.

Trabalhe em fases, com commits pequenos, testes e documentação. **Pare ao final de cada fase**, mostre o que foi feito, como testar, o que eu preciso configurar e o resultado do checklist de segurança da fase. Só continue quando eu aprovar.

## Objetivo do sistema

1. Coletar diariamente ofertas via **APIs oficiais de afiliado** (Shopee primeiro; Mercado Livre e Amazon depois), para todos os nichos ativos.
2. Guardar snapshots diários e calcular vendas em janelas de 1, 7, 15 e 30 dias, comissão estimada, qualidade e desempenho em cada canal.
3. Rankear produtos **por nicho** com score configurável e manter cada loja sempre ordenada.
4. Gerar conteúdo (arte de feed, story, story de cupom, vídeo vertical, legendas) com a identidade visual de cada nicho.
5. Enviar prévias para minha aprovação no Telegram e publicar nos canais **do nicho** após aprovação.
6. Rastrear cliques e conversões por nicho e por canal, realimentando o score.
7. Descobrir **novos nichos e produtos** (Analista de mercado) e **cupons** (Caçador de cupons).
8. Enviar relatórios diários consolidados e por nicho, alertas de oportunidade e sugestões de melhoria.

## Restrições inegociáveis

- **Custo de infraestrutura: R$ 0.** Apenas planos gratuitos: GitHub Actions (repositório privado), Postgres gerenciado gratuito (Supabase ou Neon), Cloudflare (Pages, Workers, KV, R2). O único custo aceito é a API de LLM, com teto diário global e por nicho.
- **Somente APIs oficiais.** Proibido scraping de marketplaces, automação de navegador para simular humano, rodízio de IP, contas falsas ou leitura automatizada de canais de terceiros com conta de usuário. O que não tiver API oficial vira fluxo manual ou semi-manual.
- **Segurança por padrão** (ver seção "Segurança"): nenhum segredo no código, no histórico do git, em logs, no site ou em prompts de LLM.
- **Idempotência em tudo.** Reexecutar o mesmo dia (`RUN_DATE`) não duplica dados, posts nem mensagens.
- **Humano no loop.** Nada é publicado sem minha aprovação até eu ativar autoaprovação por nicho na configuração.
- **Conformidade:** todo post contém `#publi` ou "link de afiliado" (validado antes de publicar); preço na arte com data e "sujeito a alteração"; links de afiliado com `rel="sponsored nofollow"`; cliques sem IP nem dado pessoal (LGPD).
- **Economia de minutos do Actions:** um único job processa todos os nichos em sequência (sem `matrix` por nicho, que multiplica o consumo). Sem polling frequente: o pipeline diário esvazia a fila de eventos na mesma execução, e a publicação roda só nos horários configurados. Documente o consumo estimado de minutos por mês em função do número de nichos.

## Stack

| Camada | Tecnologia |
|---|---|
| Linguagem | Python 3.12 (`uv`, lockfile com hashes), TypeScript nos Workers e no site |
| Banco | Postgres (Supabase/Neon), migrations versionadas em `sql/migrations` |
| Orquestração | GitHub Actions (cron + `workflow_dispatch` com inputs `run_date` e `niche`) |
| Fila de eventos | Tabela `agent_event` no Postgres com `FOR UPDATE SKIP LOCKED` |
| Lojas | Um projeto Astro; um build e um projeto Cloudflare Pages por nicho (subdomínio `<nicho>.garimpo.com.br`, domínio a confirmar) |
| Redirecionador e webhook | Um Cloudflare Worker para todos os nichos (mapa de links no KV, cliques no D1: o KV grátis só aceita 1 mil escritas/dia) |
| Mídia | Cloudflare R2, prefixo por nicho |
| Imagem / vídeo | Pillow para a arte do feed (implementado); template HTML/CSS + Playwright e FFmpeg para story e vídeo |
| LLM | SDK da Anthropic; modelo pequeno para classificação e validação, intermediário para copy e análise |
| Configuração | `config/niches.yaml` validado por Pydantic + JSON Schema gerado |

## Marca e nichos iniciais

**Estratégia de marca: guarda-chuva.** Uma marca (**Garimpo**), um domínio, uma loja por subdomínio e perfis com o mesmo padrão de @ em todas as redes. Isso simplifica identidade visual, domínio e confiança do público.

| Item | Padrão |
|---|---|
| Repositório | `garimpo-engine` (privado) |
| Domínio | `garimpo.com.br` (alternativas se ocupado: `garimpodiario.com.br`, `garimpoachados.com.br`) |
| Loja por nicho | `<nicho>.garimpo.com.br` (ex.: `casa.garimpo.com.br`, `pet.garimpo.com.br`) |
| Instagram / TikTok | `@garimpo.<nicho>` (ex.: `@garimpo.casa`, `@garimpo.pet`) |
| Telegram | `@garimpo<nicho>` (ex.: `@garimpocasa`, `@garimpopet`); canal geral `@garimpodiario` |
| Página de links | `<nicho>.garimpo.com.br/bio` |
| Identidade visual | `config/brands/base.json` (logo, fontes, tom de voz comuns) + `config/brands/<nicho>.json` (cor de destaque, ícone, emojis do nicho) |

Antes de fixar nomes, eu confiro manualmente a disponibilidade do @ no Instagram, TikTok e Telegram e do domínio no registro.br. O código deve tratar todos esses valores como configuração, sem nada fixo no código.

**Nichos iniciais**

| Nicho (`id`) | Status inicial | Por quê | Cuidados |
|---|---|---|---|
| Casa e cozinha (`casa`) | `active` | Nicho campeão de achadinhos: visual, ticket baixo, público amplo | Concorrência alta; capriche no criativo |
| Pets (`pet`) | `active` | Público fiel e emocional, compra recorrente, ótimo em vídeo | Bloquear medicamentos e ração de prescrição |
| Beleza e maquiagem (`beauty`) | `candidate` | Engajamento altíssimo em Instagram e TikTok | Réplicas: filtro de LLM obrigatório |
| Gadgets e tech baratos (`tech`) | `candidate` | Viraliza em vídeo | Comissão tende a ser menor em eletrônicos |
| Automotivo (`auto`) | `candidate` | Pouca concorrência de achadinhos | Volume menor |
| Setup gamer (`gamer`) | `candidate` | Ticket maior, público ativo | Conversão por impulso menor |
| Bebê e maternidade (`bebe`) | `candidate` | Recorrente; grupos de Telegram ativos | Segurança do produto (certificação Inmetro quando aplicável) |
| Fitness em casa (`fitness`) | `candidate` | Bom em vídeo de demonstração | Sazonal |
| Geral Mercado Livre (`geral-ml`) | `paused` | Canal de ofertas gerais no Telegram | Ativar quando o fluxo de links ML estiver pronto |

Regra de promoção: um nicho `candidate` só vira `active` quando o Analista de mercado mostrar, por pelo menos 2 semanas, crescimento de vendas e comissão média acima das dos nichos ativos — e eu aprovar o PR.

## Multi-nicho: configuração declarativa

Todo comportamento específico de nicho vem de `config/niches.yaml`. O código nunca tem `if nicho == "pet"`. Adicionar um nicho = adicionar um bloco no YAML, cadastrar os segredos referenciados e abrir um PR.

**Regras do arquivo**

- Versionado no git e validado no CI (`python -m src.config.validate`); YAML inválido reprova o PR.
- **Nunca contém segredo.** Canais referenciam um prefixo (`account_ref: IG_PET`) e o código monta os nomes das variáveis (`IG_PET_USER_ID`, `IG_PET_TOKEN`). O validador falha se algum segredo referenciado por um nicho `active` não existir no ambiente.
- `defaults` vale para todos; cada nicho sobrescreve só o que precisar (merge profundo).
- Status do nicho: `candidate` (só monitora, sem loja nem posts), `active`, `paused`.
- Gere `config/niches.schema.json` a partir do modelo Pydantic para validação no editor.

**Arquivo real:** `config/niches.yaml` (já existe; é a fonte da verdade, não duplique aqui). Campos além do esboço original:

- `global`: teto global de LLM por dia e `repost_cooldown_days`.
- `defaults.exploration_rate` (0.20): fração do conteúdo diário reservada a produtos fora do topo (ε-greedy).
- `defaults.llm`: `copy_model` (Sonnet) e `review_model` (Haiku).
- `platforms.shopee.mode`: `api` | `off`; `manual_offers`: CSV com links colados (Shopee, ML, Amazon).
- Canais com `enabled`; Instagram e TikTok ficam `enabled: false` até existir publicador (o validador recusa).
- `tracking.sub_id` só com `[a-z0-9]` (vai como subId da Shopee): o nicho `geral-ml` usa `geralml`.
- `filters.blocked_categories` do nicho **soma** às dos defaults; as outras listas substituem.
- `publish_slots` em minutos quebrados (`08:07`, `12:07`...): o cron do Actions atrasa.

**Como o multi-nicho se reflete no sistema**

- Todas as tabelas de negócio têm `niche_id`. Um produto pode pertencer a mais de um nicho (`product_niche`), com score separado em cada um.
- Rastreio: o link da Shopee leva os `subIds` `[<sub_id do nicho>, <canal>, <content_id>]` (ex.: `pet`, `tg`, `ab12cd34ef`). A conversão é atribuída ao **post**, não só ao canal. Códigos de canal: `tg`, `ig`, `tt`.
- Um único bot do Telegram administra todos os canais; as prévias de aprovação chegam num chat privado com o nicho no título.
- Um único app na Meta e um no TikTok autorizam várias contas; cada conta tem seu token, referenciado pelo `account_ref`.
- Falha em um nicho não interrompe os outros: cada nicho roda isolado em `try/except`, com status próprio em `pipeline_run`.
- Teto de custo de LLM aplicado por nicho e globalmente; estourou, o nicho para de gerar conteúdo naquele dia e eu sou avisado.

## Modelo de dados (mínimo)

- `niche` (espelho do YAML, sincronizado a cada execução).
- `raw_offer_snapshot` (bronze): `run_date`, `platform`, `item_id`, `payload jsonb`. PK (`run_date`, `platform`, `item_id`). Retenção de 60 dias.
- `product`, `product_niche`, `product_variant` (`attrs jsonb`, `affiliate_url`, `is_separate_listing`), `product_daily`, `price_history` (SCD2), `coupon` (`source`, `code`, `discount`, `min_purchase`, `valid_until`, `scope`, `niche_ids`).
- `product_score` (gold, por nicho), `seed_keyword` (por nicho), `niche_opportunity` (saída do Analista de mercado).
- `raw_offer_niche` (de qual nicho/palavra-chave veio cada oferta do dia).
- `click_event` (sem IP; copiado do D1), `conversion`, `content_item` (`niche_id`, `channel`, `status`, `external_id`, `scheduled_for`, `media_file_id`), `experiment`.
- `channel_state` (pausa e circuit breaker por nicho e canal), `kv_state` (offset do Telegram, marca d'água dos cliques).
- `agent_event`, `agent_run` (tokens, custo US$, latência, `niche_id`), `pipeline_run`, `audit_log` (ações administrativas: aprovações, pausas, mudanças de config).

Vendas por janela = `sales_total` de hoje − `sales_total` de N dias atrás.

## Agentes (eventos, não chat livre)

Cada agente consome tipos de evento, executa, grava em `agent_run` e publica os próximos eventos na mesma transação em que conclui o atual. Todo evento carrega `niche_id` e `correlation_id`. Contrato: entrada e saída validadas com Pydantic, lista fechada de ferramentas, teto de custo, até 3 tentativas com backoff, depois `dead` + alerta.

| Agente | LLM | Escopo | Consome | Publica |
|---|---|---|---|---|
| Rastreador | não | por nicho | cron | `snapshot_concluido` |
| Analista de dados | só resumo | por nicho | `snapshot_concluido` | `produto_em_alta` |
| Pesquisador + Copywriter | sim (JSON) | por nicho | `produto_em_alta`, `lacuna_encontrada` | `copy_pronta` |
| Revisor (regras + LLM) | sim | por nicho | `copy_pronta` | `copy_aprovada` / `copy_rejeitada` (máx. 2 voltas) |
| Designer | não | por nicho | `copy_aprovada` | `midia_pronta` |
| Lojista | não | por nicho | `copy_aprovada` | `loja_atualizada` |
| Publicador | não | por nicho | aprovação + mídia + loja | `post_publicado` |
| Sentinela | não | por nicho | cliques e conversões | `alerta_patrocinar` (só notifica) |
| **Caçador de cupons** | sim (classificação) | global → roteia para nichos | cron 3×/dia | `cupom_valido` → story de cupom no(s) nicho(s) |
| **Analista de mercado** | sim | global | cron semanal | `nicho_sugerido`, `produto_novo_sugerido` |
| Monitor de concorrentes | sim | por nicho | cron diário | `lacuna_encontrada` |
| Financeiro | só resumo | global + por nicho | cron 22h | `relatorio_diario` |
| Consultor | sim | global + por nicho | `relatorio_diario`, semanal | `sugestoes` |

O LLM nunca decide ranking nem inventa dados: recebe só os campos do produto e deve recusar afirmações ausentes da entrada.

**Caçador de cupons**

- Fontes permitidas: cupons e ofertas expostos pelas APIs oficiais de afiliado; cupons do painel de afiliados do Mercado Livre lançados por mim (comando `/cupom` no bot ou planilha); newsletters oficiais de lojas recebidas num e-mail dedicado e lidas via API oficial do provedor de e-mail (sem login automatizado em sites).
- Para cada cupom: normaliza (código, tipo, valor, mínimo, validade, escopo), valida regras de `defaults.coupons`, deduplica, cruza com os produtos do top de cada nicho e decide para quais nichos ele "compensa".
- Gera story de cupom por nicho e entra na fila de aprovação com prioridade alta. Cupom vencido sai do site e da fila automaticamente.

**Analista de mercado**

- Semanalmente, para cada categoria das plataformas com API oficial, calcula: crescimento de vendas (7d vs. 30d) dos produtos mais vendidos, comissão média, ticket médio, dispersão de preço e volume de ofertas.
- Inclui nichos `candidate` do YAML e propõe novas palavras-chave e categorias a partir dos produtos que mais convertem nos nichos ativos.
- Saída: `niche_opportunity` com nota e justificativa baseada em números, e uma mensagem no Telegram com o ranking de oportunidades.
- Ao eu aprovar um nicho sugerido, abre automaticamente um **pull request** adicionando o bloco ao `config/niches.yaml` com `status: candidate`. Nunca faz commit direto na `main`.

**Monitor de concorrentes**

- Produtos similares aos meus (mesma categoria e título semelhante via embeddings) que vendem mais na mesma plataforma; produtos em alta no nicho que ainda não tenho.
- Perfis de Instagram concorrentes (contas profissionais, lista definida por nicho no YAML) via Business Discovery da Graph API: posts recentes e engajamento público.
- Não tenta obter vendas de outros afiliados (não é visível) nem ler canais de terceiros com conta de usuário.

## Segurança

Trate segurança como requisito funcional. Crie `SECURITY.md` com o modelo de ameaças abaixo e o checklist, e um workflow `security.yml`.

**Ativos e ameaças principais**

| Ativo | Ameaça | Controle |
|---|---|---|
| Tokens de Instagram, TikTok, Telegram, Shopee, Cloudflare, banco, LLM | Vazamento em commit, log, build do site ou prompt | Secrets só no GitHub/Cloudflare, `gitleaks`, redação de segredos no logger, nada de segredo no build do site |
| Contas de afiliado e redes | Suspensão por violar termos | Somente API oficial, limites de postagem, circuit breaker |
| Redirecionador `/go` | Open redirect usado para phishing | Redirecionar só para URLs do KV e de domínios em allowlist (shopee, mercadolivre, amazon e seus encurtadores oficiais) |
| Aprovação e comandos do bot | Alguém aprovar posts ou disparar comandos | Hoje (polling): `callback_data` assinado com HMAC, allowlist de `user_id`, comandos só no chat de admin, expiração em 72 h, `audit_log`. Com webhook (futuro): também `X-Telegram-Bot-Api-Secret-Token` e papel `app_webhook` que só insere em aprovação e `audit_log` |
| Banco | Acesso indevido, SQL injection, perda de dados | Papéis separados, queries parametrizadas, RLS, backup |
| Agentes com LLM | Prompt injection vindo de títulos, avaliações, posts de concorrentes e e-mails | Conteúdo externo tratado como dado; agentes de LLM sem ferramentas de escrita; saída validada por schema; publicação só pelo Publicador determinístico |
| Pipeline de CI | Supply chain, action comprometida | Actions fixadas por SHA, `permissions` mínimas, Dependabot, lockfile com hashes |

**Repositório e GitHub**

- Repositório privado; 2FA obrigatório na conta; branch `main` protegida (PR obrigatório, CI verde obrigatório, sem force push).
- `pre-commit` com `gitleaks`, `ruff` e verificação de arquivos grandes; o mesmo `gitleaks` roda no CI sobre todo o histórico.
- `.gitignore` cobrindo `.env*` (exceto `.env.example`), `*.pem`, `*.key`, `credentials*.json`, saídas de mídia e dumps de banco.
- Workflows com `permissions: contents: read` por padrão; escrita só no job que precisa. Nunca usar `pull_request_target`. Sem `echo` de variáveis de ambiente.
- Dependabot para pip, npm e GitHub Actions.

**Segredos**

- Inventário em `docs/secrets.md`: nome, para que serve, onde está guardado, escopo mínimo, data de criação, data de expiração, procedimento de rotação. Nunca o valor.
- Tokens com o menor escopo possível (ex.: token da Cloudflare limitado à conta e aos recursos usados; usuário de banco por papel).
- Rotação a cada 90 dias, com lembrete automático no Telegram 7 dias antes; tokens com expiração própria (Instagram) renovados por workflow.
- Logger com filtro que mascara qualquer valor que coincida com um segredo carregado ou com padrões de token.
- O processo falha na inicialização se faltar segredo exigido por um nicho ativo, mostrando apenas o nome da variável.

**Banco de dados**

- Papéis: `app_writer` (pipeline), `app_reader` (comando `/pergunta`, só views permitidas, `statement_timeout` de 5 s, sem acesso a `audit_log` e tabelas de configuração sensível), `migrator` (só para migrations; hoje é o dono do banco) e, quando o webhook existir, `app_webhook` (só `INSERT` em aprovação e `audit_log`).
- No Supabase: RLS habilitado em todas as tabelas, nenhuma chave `service_role` fora do servidor, API REST pública desabilitada ou sem tabelas expostas.
- Conexão sempre com TLS; backup diário do provedor e exportação semanal criptografada para o R2.

**Worker e site**

- Worker: validação estrita de parâmetros, allowlist de domínios de destino, rate limit por IP em memória sem persistir o IP, respostas sem detalhes internos.
- Site: headers de segurança (CSP restritiva, HSTS, `X-Content-Type-Options`, `Referrer-Policy`, `Permissions-Policy`) via `_headers` do Pages; nenhuma chave no JavaScript do cliente; formulários inexistentes ou protegidos.

**Agentes de LLM**

- Prompts separam claramente instruções de dados externos; dados externos vão delimitados e com instrução de não seguir comandos contidos neles.
- Agentes de LLM não chamam APIs de publicação, não escrevem no banco diretamente e não executam SQL arbitrário; o `/pergunta` usa SQL gerado validado (somente `SELECT`, somente views da allowlist, `LIMIT` obrigatório) e o papel `app_reader`.
- Nenhum segredo, token ou dado pessoal entra em prompt.

**Workflow `security.yml` (semanal + em todo PR)**

- `gitleaks` no histórico completo.
- `pip-audit` e `npm audit --audit-level=high`.
- Semgrep (regras community para Python, TypeScript e GitHub Actions).
- Verificação dos workflows: actions fixadas por SHA, `permissions` declaradas, ausência de `pull_request_target`.
- Teste do redirecionador contra open redirect e do webhook contra requisição sem token.
- Script `scripts/check_secrets_inventory.py`: compara segredos referenciados no YAML e no código com `docs/secrets.md` e alerta sobre itens perto da expiração.
- Resultado resumido no Telegram; falha crítica abre issue no repositório.

**Checklist de segurança ao fim de cada fase** (inclua o resultado no seu relatório da fase)

- [ ] Nenhum segredo no diff nem no histórico (`gitleaks` limpo)
- [ ] Novos segredos documentados em `docs/secrets.md` com escopo mínimo
- [ ] Novas tabelas com RLS e grants corretos por papel
- [ ] Entradas externas validadas; conteúdo externo nunca tratado como instrução
- [ ] Logs revisados sem dados sensíveis
- [ ] Dependências novas auditadas
- [ ] Testes de idempotência e de falha isolada por nicho passando

## Estrutura do repositório

```
garimpo-engine/
├── .github/workflows/      # ci, security, garimpo (daily/publish/report/healthcheck; segredos explícitos, sem secrets: inherit); depois market, token-refresh
├── config/
│   ├── niches.yaml
│   ├── niches.schema.json  # gerado
│   └── brands/             # identidade visual por nicho
├── src/
│   ├── config/             # modelos Pydantic, merge de defaults, validador
│   ├── common/             # db, logging com redação, llm com teto de custo, telegram, security
│   ├── sources/            # shopee.py, manual.py (CSV), fake.py (demo/testes); depois coupons/
│   ├── pipeline/           # ingest, transform (com checagens de qualidade), score, content (seleção)
│   ├── agents/             # (futuro) agentes assíncronos: cupons, mercado, concorrentes
│   ├── content/            # brand, copy (template/Claude), caption (+ conformidade), render (Pillow)
│   ├── publishers/         # telegram.py; depois instagram.py, tiktok.py
│   ├── tracking/           # cloudflare.py (KV/D1), sync.py (cliques e conversões)
│   ├── reports/            # daily.py
│   ├── approval.py         # prévias, botões assinados, respostas
│   ├── commands.py         # /status, /top, /pausar, /retomar
│   └── run.py              # python -m src.run --steps ... --run-date ... --niche ...
├── sql/migrations/
├── site/                   # Astro, build parametrizado por nicho
├── worker/                 # redirect /go + KV + D1 (webhook depois)
├── scripts/
├── tests/
├── docs/                   # README, ADRs, runbook, secrets.md, dicionário de dados
├── SECURITY.md
├── .env.example
└── README.md
```

## Fases e critérios de aceite

Ordem orientada a receita (ARQUITETURA.md §8): o ciclo post → clique → venda fecha primeiro no Telegram.

**Fase 1 — Fundação e segurança** ✅ *feito na v0.1*
- `uv`, `ruff`, `pytest`, pre-commit com `gitleaks`, `ci.yml`, `security.yml`, Dependabot, `SECURITY.md`, `docs/secrets.md`.
- Configuração multi-nicho validada + JSON Schema; logging JSON com redação; migrations com papéis e RLS.
- Aceite: `python -m src.run --steps healthcheck` passa; `security.yml` verde.

**Fase 2 — Dados + Telegram + medição** ✅ *feito na v0.1*
- Cliente da Shopee (assinatura, rate limit, backoff; confirmar campos no explorador GraphQL), CSV manual.
- Bronze → silver → gold por nicho, com checagens de qualidade; seleção com exploração de 20%.
- Copy (template ou Claude + revisor), arte, prévia com botões, publicador do Telegram com circuit breaker.
- `subIds` com `content_id`, Worker `/go` com allowlist e cliques no D1, importação de conversões
  (`conversionReport` e CSV), relatório diário, comandos do bot.
- Aceite: dois dias seguidos geram `product_score`; reprocessar não altera contagens; falha forçada num nicho não
  afeta os outros; posts publicados sem duplicação.

**Fase 3 — Instagram e TikTok** ⏳ *próxima*
- Mídia no R2 (URL pública para a Graph API); feed, reels e stories no Instagram; TikTok como **rascunho** por padrão
  (app não auditado só publica privado), com o passo manual documentado.
- Story e vídeo vertical (Playwright/FFmpeg num workflow separado para poupar minutos).
- Limites do YAML por canal, circuit breaker por nicho e canal, `token-refresh.yml` para o token do Instagram.
- Aceite: posts nas contas certas de cada nicho, sem duplicação em reexecução.

**Fase 4 — Lojas**
- Build do Astro por nicho, um projeto Pages por nicho, Schema.org `Product`, `/ofertas`, `/bio`, páginas legais,
  sitemap, headers de segurança, Lighthouse ≥ 90; links `rel="sponsored nofollow"` passando pelo `/go` com canal
  `bio`/`site`.
- Aceite: deploy automático de todas as lojas ativas.

**Fase 5 — Cupons, webhook e experimentos**
- Caçador de cupons; Sentinela; Consultor com `experiment`; `/pergunta <texto>` com `app_reader`.
- Webhook do Telegram no Worker (resposta imediata aos botões) com `app_webhook`.

**Fase 6 — Mercado e concorrentes**
- Analista de mercado com `niche_opportunity` e abertura de PR para nicho aprovado; Monitor de concorrentes por nicho.
- Aceite: relatório semanal de oportunidades no Telegram e PR gerado ao aprovar uma sugestão.

## Padrões de código

- Funções pequenas e tipadas; nenhuma lógica de negócio dentro de YAML de workflow; nenhum `if` por nome de nicho.
- Todo acesso externo atrás de uma interface, com fakes nos testes; nenhuma chamada de rede nos testes unitários.
- Documente decisões relevantes como ADR em `docs/adr/`.
- `docs/runbook.md`: reprocessar um dia ou um nicho, pausar nicho ou canal, adicionar nicho, rotacionar segredo, responder a cada tipo de alerta, o que fazer em caso de vazamento de chave (revogar, rotacionar, verificar uso, registrar).

## Antes de começar

Faça no máximo 3 perguntas, apenas se forem bloqueantes (ex.: domínio confirmado, credenciais disponíveis). Marca e nichos iniciais já estão definidos acima. Para o resto, assuma valores razoáveis, liste as suposições no README e siga para a próxima fase pendente.
