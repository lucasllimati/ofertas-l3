# ADR 0002: aprovação lida por getUpdates em vez de webhook

**Status:** aceito (provisório) · 2026-10-22

## Contexto
O ideal é o webhook do Telegram cair no Worker e gravar a decisão no banco na hora. Isso exige Worker com acesso ao Postgres (driver HTTP ou Hyperdrive), papel `app_webhook` e validação do `X-Telegram-Bot-Api-Secret-Token`.

## Decisão
Nesta versão cada execução agendada começa com o passo `approvals`, que lê `getUpdates` com offset persistido em `kv_state`. Segurança: só `TELEGRAM_ADMIN_USER_IDS`, comandos só no chat de admin, `callback_data` assinado com HMAC (`APPROVAL_HMAC_SECRET`), prévia expira em 72 h, tudo em `audit_log`.

## Consequências
- O botão "responde" (marca ✅) só na próxima execução. O post aprovado sai no primeiro slot com horário ≤ agora.
- Não pode haver webhook configurado no bot (o Telegram devolve 409).
- Updates ficam no Telegram por 24 h; com execuções várias vezes por dia, nada se perde.
- Migrar para webhook depois não muda o modelo de dados.
