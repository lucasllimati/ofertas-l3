# ADR 0001: MVP com publicação só no Telegram

**Status:** aceito · 2026-10-22

## Contexto
A especificação prevê Instagram, TikTok, lojas e vários agentes. Instagram exige conta profissional ligada a página do Facebook, mídia em URL pública e app da Meta; TikTok exige auditoria do app para publicar em público. Nada disso fica pronto num dia.

## Decisão
A versão 0.1 fecha o ciclo completo de receita só com Telegram: coleta → score → conteúdo → aprovação → publicação → clique → conversão → relatório. Instagram/TikTok continuam na configuração com `enabled: false`, e o validador recusa `enabled: true` até existir publicador.

## Consequências
Primeira comissão possível no mesmo dia. O modelo de dados (`content_item.channel`, `sub_id` com canal) já suporta os outros canais.
