# Changelog

Mudanças relevantes para quem opera o Garimpo. Detalhes técnicos em cada PR.

## [0.4.0] · 2026-10-25: 11 agentes novos e o Contador

### Adicionado
- **Vigia de preço e estoque:** reconsulta o produto na Shopee logo antes de publicar. Preço mudou mais que `tolerance_pct` → legenda e arte refeitas e nova prévia para reaprovação; esgotado → `unavailable`, não publica.
- **Calendário sazonal** ([config/calendar.yaml](config/calendar.yaml)): 11.11, Esquenta Black Friday, Black Friday (27–30/11/2026), 12.12, Natal e Dia das Mães. Palavras-chave extras, até 3× posts no dia, selo na arte e aviso prévio no relatório.
- **Classificador de conformidade** (Claude Haiku, opcional): barra remédio, réplica, adulto, arma e tabaco/álcool com título "limpo"; veredito guardado em `compliance_check`.
- **Caçador de cupons** ([config/coupons.csv](config/coupons.csv)): melhor cupom válido na legenda; cupom vencido sai antes de publicar; `/cupons`.
- **Sentinela** (posts 🔥 e 💤 no relatório) e **Reciclador** (campeões voltam depois do cooldown, até 20% das vagas).
- **Detector de link quebrado** nos posts dos últimos 30 dias.
- **Analista de mercado** (`/mercado`), **Otimizador de horários** (`/horarios <nicho>`) e **Laboratório A/B de copy**, no relatório de domingo.
- **Conciliador + Contador** ([config/finance.yaml](config/finance.yaml)): fechamento mensal automático no dia 5 com CSV para a contabilidade; imposto estimado e comparação Simples III/V/Fator R, MEI e pessoa física com as regras de 2026; divisão do dinheiro (reserva, reinvestimento, caixa, retirada); otimizações e riscos. Comandos `/imposto` e `/fechamento`, passo `close`.
- Bloco `agents:` no `niches.yaml` para ligar, desligar e ajustar cada agente por nicho; `validate` confere também calendário, cupons e finanças.
- Migrations `0005_agents.sql` e `0006_agents_security.pg.sql` (RLS e permissões da tabela nova).

### Mudado
- Chamadas de LLM centralizadas em `LlmGateway` (teto de custo compartilhado entre Copywriter e Classificador).
- Relatório dividido em várias mensagens quando passa do limite do Telegram.
- Atalho `publish` roda `approvals → publish → preview`: o post refeito pelo Vigia de preço já sai como prévia na mesma execução.

## [0.3.0] · 2026-10-24: revisão geral e documentação

### Corrigido
- **Alerta de falha que não chegava:** o texto do erro ia sem escape no HTML do Telegram; um erro com `<` fazia a mensagem inteira ser recusada.
- **Importação de vendas por CSV (ML/Amazon):** aceita vírgula decimal (`39,90`), `R$` e datas `dd/mm/aaaa [hh:mm]`; uma linha inválida recusa o arquivo inteiro, com o número da linha.
- **Publicador:** falha ao gerar a arte antes do envio volta o post para a fila, em vez de marcá-lo como "não sei se saiu".
- **Cliente do Telegram:** resposta que não é JSON (ex.: 502 do gateway) vira erro tratável, em vez de quebrar o passo.
- **`undici` vulnerável** (3 advisories, via wrangler/miniflare): fixado na 7.30.1 com `overrides`.

### Adicionado
- **Healthcheck dos canais:** confere se o bot é admin com "Publicar mensagens" em cada canal ativo, antes da primeira publicação.
- **Alerta "⛔ Produção bloqueada"** no Telegram quando a trava `verify` impede uma execução.
- Documentação nova: [agentes](docs/agentes.md) (responsabilidades e ideias), [dicionário de dados](docs/dados.md), [guia de desenvolvimento](docs/desenvolvimento.md), [índice](docs/README.md), ADRs 0006 e 0007 e este CHANGELOG.

## [0.2.0] · 2026-10-23: segurança e regras de anúncio

### Adicionado
- **Trava de produção** (`verify`): só roda commit verde em `ci` e `security` ([ADR 0006](docs/adr/0006-trava-de-producao.md)).
- **Backup semanal criptografado** (AES-256, 90 dias) e restauração ([ADR 0007](docs/adr/0007-backup-proprio-criptografado.md)).
- Suíte `pytest -m security` em SQLite e Postgres, em todo PR, push e semanalmente.
- Bloco "🔐 Segurança" no relatório diário.

### Mudado
- Texto do vendedor e do LLM limpo de links, @perfis, telefones, preços e promessas não verificadas.
- "De/por" só aparece se o preço cheio foi observado nos últimos 30 dias.
- "#publi · link de afiliado" na primeira linha da legenda.
- "Mais de N vendidos" com número real, arredondado para baixo.
- Usuário do pipeline sem `DELETE` em vendas, cliques, posts e auditoria; TLS obrigatório no Postgres.
- Worker não conta cliques de robôs nem HEAD.
- Workflow único `garimpo.yml`, sem `secrets: inherit`; gitleaks por binário com checksum; Dependabot agrupado.

### Corrigido
- Fila de aprovação travava para sempre com uma única atualização com erro.
- Demo podia gravar dados falsos no banco de produção.

Relatório completo: [docs/security-review.md](docs/security-review.md).

## [0.1.0] · 2026-10-22: primeira versão

- Configuração multi-nicho validada (`config/niches.yaml`).
- Coleta pela Shopee Affiliate Open API e por CSV manual (Shopee, Mercado Livre, Amazon).
- Bronze → silver → gold, histórico de preço, vendas em 1/7/15/30 dias e score por nicho.
- Seleção diária com exploração, copy por template ou Claude, arte, prévia com botões assinados.
- Publicação no Telegram com limites, circuit breaker e sem duplicação.
- SubIds por post, redirecionador `/go` (Cloudflare), conversões e relatório diário.
- CI, `security.yml`, RLS no Postgres, demo sem contas.
