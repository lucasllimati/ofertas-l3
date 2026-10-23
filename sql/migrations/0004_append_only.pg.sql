-- Só Postgres. Histórico de vendas, cliques, posts e auditoria não pode ser apagado pelo pipeline:
-- um DATABASE_URL vazado não consegue destruir a prova das comissões nem a trilha de auditoria.
-- O pipeline nunca apaga essas tabelas (só staging e score do dia), então nada quebra.
REVOKE DELETE ON garimpo.conversion, garimpo.click_event, garimpo.content_item, garimpo.audit_log FROM app_writer;
-- audit_log é somente-inclusão.
REVOKE UPDATE ON garimpo.audit_log FROM app_writer;
