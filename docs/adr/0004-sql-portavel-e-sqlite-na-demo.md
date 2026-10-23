# ADR 0004: SQL portátil (Postgres e SQLite)

**Status:** aceito · 2026-10-22

## Contexto
Testes não podem depender de rede nem de Postgres instalado, e a demo precisa rodar sem conta nenhuma.

## Decisão
O schema comum (`sql/migrations/*.sql`) usa só TEXT/INTEGER/REAL. Datas são `TEXT` (`AAAA-MM-DD`) e instantes são ISO-8601 UTC, que ordenam corretamente como texto. Ids são gerados no código (determinísticos quando a idempotência pede). O que é só do Postgres (papéis, RLS, views) fica em `*.pg.sql`. Em produção as tabelas ficam no schema `garimpo`, fora do `public` exposto pela API do Supabase.

## Consequências
Os mesmos testes rodam em SQLite (local) e em Postgres (CI, job com serviço `postgres:16`). Perde-se tipagem forte de data no banco; a validação acontece no código.
