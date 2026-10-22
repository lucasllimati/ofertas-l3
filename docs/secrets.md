# Inventário de segredos

Só nomes e metadados. **Nunca** coloque valores aqui. Preencha "Criado em" e "Expira em" (AAAA-MM-DD) ao cadastrar;
o `security.yml` avisa 7 dias antes da expiração. Rotação padrão: 90 dias (procedimento em [runbook.md](runbook.md#rotacionar-um-segredo)).

| Nome | Para que serve | Onde fica | Escopo mínimo | Criado em | Expira em | Rotação |
|---|---|---|---|---|---|---|
| `DATABASE_URL` | Conexão do pipeline com o Postgres | GitHub Actions secret | Usuário `garimpo_pipeline` no papel `app_writer` (sem DDL) | - | - | Trocar senha do usuário no Supabase e atualizar o secret |
| `TELEGRAM_BOT_TOKEN` | Bot que envia prévias e publica nos canais | GitHub Actions secret | Bot admin só dos canais Garimpo, com permissão "postar mensagens" | - | - | BotFather → /revoke e atualizar o secret |
| `TELEGRAM_ADMIN_CHAT_ID` | Chat privado onde chegam prévias e alertas | GitHub Actions secret | Não é credencial; é segredo para não expor seu chat | - | - | - |
| `TELEGRAM_ADMIN_USER_IDS` | Únicos usuários que podem aprovar e mandar comandos | GitHub Actions secret | Seu user id numérico (vírgula para mais de um) | - | - | - |
| `APPROVAL_HMAC_SECRET` | Assina os botões Aprovar/Rejeitar | GitHub Actions secret | 32+ bytes aleatórios | - | - | Trocar invalida prévias pendentes (reenvie) |
| `TG_CASA_CHAT_ID` | Canal do nicho casa (`@garimpocasa` ou id -100...) | GitHub Actions secret | - | - | - | - |
| `TG_PET_CHAT_ID` | Canal do nicho pet | GitHub Actions secret | - | - | - | - |
| `TG_GERAL_CHAT_ID` | Canal geral (nicho pausado) | GitHub Actions secret | - | - | - | - |
| `SHOPEE_APP_ID` | Shopee Affiliate Open API | GitHub Actions secret | App de afiliado (leitura de ofertas, links, relatórios) | - | - | Painel de afiliados → regenerar secret |
| `SHOPEE_APP_SECRET` | Assinatura das chamadas da Shopee | GitHub Actions secret | idem | - | - | idem |
| `ANTHROPIC_API_KEY` | Copy e revisão com Claude (opcional) | GitHub Actions secret | Workspace dedicado com limite de gasto mensal | - | - | Console Anthropic → criar nova, apagar antiga |
| `CF_API_TOKEN` | Gravar links no KV e ler cliques no D1 (opcional) | GitHub Actions secret | Token com só "Workers KV Storage: Edit" e "D1: Edit" na sua conta | - | - | Cloudflare → API Tokens → Roll |
| `CF_ACCOUNT_ID` | Conta Cloudflare | GitHub Actions secret | Não é credencial | - | - | - |
| `CF_KV_NAMESPACE_ID` | Namespace KV `LINKS` do Worker | GitHub Actions secret | Não é credencial | - | - | - |
| `CF_D1_DATABASE_ID` | Banco D1 `garimpo-clicks` | GitHub Actions secret | Não é credencial | - | - | - |
| `REDIRECT_BASE_URL` | URL pública do Worker (`https://go.garimpo.com.br`) | GitHub Actions secret | Não é credencial | - | - | - |
