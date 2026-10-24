# ADR 0006: produção só roda commit verde em `ci` e `security`

**Status:** aceito · 2026-10-23

## Contexto
No plano Free do GitHub, repositório privado não tem proteção de branch nem rulesets. Um push direto na `main`, ou um merge com check vermelho, iria para a produção no próximo cron sem verificação nenhuma.

## Decisão
O workflow de produção (`garimpo.yml`) tem um job `verify` antes de qualquer passo. Ele consulta a API do GitHub e só libera se **o commit exato** tem execuções com sucesso de `ci` e de `security`. Se elas ainda estiverem rodando, espera até 12 min. Se falhou, bloqueia e avisa no Telegram ("⛔ Produção bloqueada"). O `check_workflows.py` recusa um `garimpo.yml` sem o `verify` ou com job sem `needs: verify`.

## Consequências
- Código não verificado nunca coleta, aprova nem publica.
- Uma vulnerabilidade publicada depois do merge (ex.: o caso do `undici` em 2026-10-24) também para a produção até ser corrigida. É intencional: o alerta no Telegram garante que a parada não passe despercebida.
- Custo: cerca de 20 s por execução (≈ 60 min/mês de Actions).
