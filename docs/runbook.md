# Runbook

Comandos locais usam `uv run python -m src.run ...` com o `.env` preenchido. No GitHub, os mesmos passos estão nos workflows `daily`, `publish`, `report` e `healthcheck` (Actions → Run workflow).

## Criar o usuário do pipeline no Postgres

Rode uma vez no SQL Editor do Supabase (ou `psql` como dono), **depois** de `--steps migrate`. Escolha a senha na hora; ela nunca vai para o git.

```sql
CREATE ROLE garimpo_pipeline LOGIN PASSWORD 'gere-uma-senha-forte-aqui' IN ROLE app_writer;
ALTER ROLE garimpo_pipeline SET search_path = garimpo, public;
```

No Supabase, o usuário do pooler fica `garimpo_pipeline.<project-ref>`. Use essa connection string no secret `DATABASE_URL`. Esse usuário lê e escreve dados, mas não cria nem apaga tabelas.

Novas migrations: rode `--steps migrate` com o usuário dono (localmente), não com o do pipeline.

## Reprocessar um dia ou um nicho

```bash
uv run python -m src.run --steps daily --run-date 2026-10-20
uv run python -m src.run --steps daily --run-date 2026-10-20 --niche casa
```

É idempotente: snapshots, score e conteúdo do dia são substituídos ou mantidos, nunca duplicados. Posts já publicados não são reenviados. Observação: a Shopee devolve a oferta **de hoje**, então reprocessar um dia passado com a API grava os dados atuais naquela data. Para corrigir só o score, rode `--steps transform,score`.

## Pausar e retomar

- Pelo bot: `/pausar casa telegram` e `/retomar casa telegram`.
- Nicho inteiro: em `config/niches.yaml`, `status: paused` e PR.

## Adicionar um nicho

1. Bloco novo em `config/niches.yaml` (comece como `candidate`); se tiver marca, `config/brands/<nicho>.json`.
2. `uv run python -m src.config.validate --write-schema`.
3. Para virar `active`: crie o canal, adicione o bot como admin, cadastre o secret `<REF>_CHAT_ID`, inclua a linha `<REF>_CHAT_ID: ${{ secrets.<REF>_CHAT_ID }}` em `.github/workflows/_run.yml` e a entrada em `docs/secrets.md`.
4. PR. O CI valida o YAML, o schema e o inventário de segredos.

## Rotacionar um segredo

1. Gere o novo valor no provedor (BotFather `/revoke`, painel da Shopee, Console Anthropic, Cloudflare "Roll", senha do usuário no Supabase).
2. Atualize o secret no GitHub.
3. Rode o workflow **healthcheck**.
4. Revogue o valor antigo, se o provedor não fez isso.
5. Atualize "Criado em" / "Expira em" em `docs/secrets.md`.

`APPROVAL_HMAC_SECRET`: trocar invalida botões de prévias pendentes; elas expiram sozinhas em 72 h.

## Alertas e o que fazer

| Alerta | Ação |
|---|---|
| `Falhas na execução ...` | Veja o log do workflow. Cada nicho falha isolado; os outros seguiram. Corrija e reprocesse o dia/nicho. |
| `N falhas seguidas no Telegram. Canal pausado.` | Bot removido do canal, canal renomeado ou `TG_*_CHAT_ID` errado. Corrija e `/retomar <nicho> telegram`. Os posts voltaram para a fila. |
| `não sei se o post X saiu` | Erro de rede no envio. Confira o canal. Se não saiu e você quiser publicar, no SQL: `UPDATE garimpo.content_item SET status = 'approved' WHERE id = 'X';` |
| `todas as palavras-chave da Shopee falharam` | Credencial da Shopee inválida/expirada, limite de chamadas ou API fora. Rode o healthcheck; se for credencial, rotacione. |
| `ofertas inválidas: verifique a fonte` | Mais da metade das ofertas veio quebrada. Provável mudança de campo na API: confira no explorador GraphQL e ajuste `src/sources/shopee.py`. |
| `orçamento diário de LLM atingido` | Normal em dia de muito conteúdo; a copy cai para template. Aumente o teto no YAML se valer a pena. |
| `getUpdates ... Conflict` | Existe um webhook configurado no bot. `https://api.telegram.org/bot<TOKEN>/deleteWebhook` (no navegador, sem compartilhar a URL). |

## Supabase pausou o projeto

Projetos grátis pausam após 7 dias sem uso. O `daily` diário evita isso; se pausar (Actions desligado, por exemplo), reative no painel e rode o `daily`.

## Vazamento de chave

1. **Revogue imediatamente** no provedor (não espere o PR).
2. Gere a nova, atualize o secret no GitHub, rode o healthcheck.
3. Verifique uso indevido: posts estranhos nos canais, gasto no Console Anthropic, logs da Cloudflare, conexões no Supabase.
4. Se o valor foi parar no git: rotacionar já resolve. Reescrever o histórico é opcional e não substitui a rotação.
5. Registre no `audit_log`:
   ```sql
   INSERT INTO garimpo.audit_log (id, ts, actor, action, target, detail)
   VALUES (gen_random_uuid()::text, now()::text, 'voce', 'secret_leak', 'NOME_DO_SECRET', '{"acao":"revogado e rotacionado"}');
   ```

## Consultas úteis

```sql
-- desempenho por post (últimos 30 dias)
SELECT * FROM garimpo.v_content_performance WHERE run_date >= to_char(now() - interval '30 days', 'YYYY-MM-DD')
ORDER BY commission DESC LIMIT 20;

-- top do dia por nicho
SELECT s.rank, p.title, p.price, s.score FROM garimpo.product_score s
JOIN garimpo.product p ON p.id = s.product_id
WHERE s.niche_id = 'casa' AND s.run_date = to_char(now(), 'YYYY-MM-DD') AND s.eligible = 1
ORDER BY s.rank LIMIT 20;
```
