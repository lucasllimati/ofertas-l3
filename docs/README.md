# Documentação

Qual documento ler para cada necessidade.

| Quero... | Leia |
|---|---|
| Entender o negócio e a arquitetura | [ARQUITETURA.md](../ARQUITETURA.md) |
| Ver o que já funciona e testar em 2 minutos | [README.md](../README.md) |
| Criar as contas, tokens e colocar no ar | [SETUP.md](SETUP.md) |
| Saber o que cada agente faz (e ideias de novos) | [agentes.md](agentes.md) |
| Operar no dia a dia: reprocessar, pausar, restaurar backup, responder a alertas | [runbook.md](runbook.md) |
| Saber onde cada dado fica e o ciclo de vida de um post | [dados.md](dados.md) |
| Mudar o código com segurança | [desenvolvimento.md](desenvolvimento.md) |
| Conhecer as regras de segurança e a verificação automática | [SECURITY.md](../SECURITY.md) |
| Ver a última revisão de segurança (achados e riscos que continuam) | [security-review.md](security-review.md) |
| Ver o inventário de segredos | [secrets.md](secrets.md) |
| Entender por que algo foi feito de um jeito | [adr/](adr/) |
| Ver o que mudou em cada versão | [CHANGELOG.md](../CHANGELOG.md) |
| Continuar construindo com o Claude Code (especificação das fases) | [prompt-garimpo-engine.md](../prompt-garimpo-engine.md) |

## Decisões de arquitetura (ADRs)

| ADR | Decisão |
|---|---|
| [0001](adr/0001-mvp-telegram-primeiro.md) | MVP publica só no Telegram |
| [0002](adr/0002-aprovacao-por-polling.md) | Aprovação lida por `getUpdates`, não por webhook (por enquanto) |
| [0003](adr/0003-arte-com-pillow.md) | Arte com Pillow, não Playwright |
| [0004](adr/0004-sql-portavel-e-sqlite-na-demo.md) | SQL portátil Postgres/SQLite |
| [0005](adr/0005-cliques-no-d1.md) | Cliques no D1, mapa de links no KV |
| [0006](adr/0006-trava-de-producao.md) | Produção só roda commit verde em `ci` e `security` |
| [0007](adr/0007-backup-proprio-criptografado.md) | Backup semanal próprio e criptografado |

`docs/archive/` guarda versões antigas da especificação, só para histórico; não use como referência.
