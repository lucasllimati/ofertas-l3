-- Só Postgres. RLS e grants da tabela nova da 0005 (a 0002 só cobre as tabelas que existiam na época).
ALTER TABLE garimpo.compliance_check ENABLE ROW LEVEL SECURITY;
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_policies
        WHERE schemaname = 'garimpo' AND tablename = 'compliance_check' AND policyname = 'app_writer_all'
    ) THEN
        CREATE POLICY app_writer_all ON garimpo.compliance_check FOR ALL TO app_writer USING (true) WITH CHECK (true);
    END IF;
END
$$;
GRANT SELECT, INSERT, UPDATE, DELETE ON garimpo.compliance_check TO app_writer;
