# ADR 0007: backup semanal próprio e criptografado

**Status:** aceito · 2026-10-23

## Contexto
O Supabase Free não faz backup automático (só os planos pagos). O histórico de vendas e de posts é a base do score e a prova das comissões.

## Decisão
Passo `backup` todo domingo às 03:17 (Brasília):
- exporta as tabelas de histórico em JSON Lines comprimido, sem os snapshots brutos, que são recoletáveis;
- cifra com `gpg` AES-256 usando `BACKUP_PASSPHRASE`;
- guarda o `.gpg` como artefato privado do GitHub por 90 dias;
- apaga o arquivo aberto.

Sem a senha, o backup não roda, para nunca ser salvo em texto puro. A restauração ([scripts/restore_backup.py](../../scripts/restore_backup.py)) aceita só tabelas e colunas conhecidas e não sobrescreve linhas existentes.

## Consequências
- Recuperação possível de até 90 dias para trás, sem custo.
- O backup fica na mesma conta do GitHub: se a conta for perdida, o backup vai junto. Mitigação: baixar um artefato por mês e guardar fora (já vem cifrado).
- Perder a `BACKUP_PASSPHRASE` torna os backups ilegíveis: ela deve ficar no gerenciador de senhas.
