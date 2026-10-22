# ADR 0003: arte com Pillow em vez de HTML + Playwright

**Status:** aceito · 2026-10-22

## Contexto
A especificação sugere template HTML/CSS renderizado com Playwright. Instalar o Chromium custa ≈ 1 min e ≈ 150 MB por execução no Actions, o recurso mais escasso do plano grátis.

## Decisão
A arte do post (1080×1350) é desenhada com Pillow, com cores e nome da marca vindos de `config/brands/*.json`. A prévia sobe a imagem uma vez; o publicador reaproveita o `file_id` do Telegram, sem renderizar de novo nem guardar mídia.

## Consequências
Render em milissegundos, sem navegador. Layouts mais sofisticados (stories, vídeo) podem usar Playwright/FFmpeg na fase de Instagram/TikTok, num workflow separado.
