# ADR 0005: cliques no D1, mapa de links no KV

**Status:** aceito · 2026-10-22

## Contexto
O KV grátis aceita só 1 mil escritas por dia; cada clique é uma escrita.

## Decisão
O Worker lê o destino no KV (`go:<content_id>`, gravado pelo pipeline: ≈ 10 escritas/dia) e grava o clique no D1 (100 mil escritas/dia grátis), sem IP e sem user-agent. O passo `clicks` copia para `click_event` no Postgres e apaga do D1 o que tiver mais de 7 dias.

## Consequências
O redirecionador é opcional: sem ele, a atribuição de vendas por post continua via `subIds` da Shopee.
