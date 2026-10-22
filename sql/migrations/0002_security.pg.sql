-- Só Postgres. Papéis sem login (grupos) + RLS em todas as tabelas.
-- Os usuários de login são criados à mão (docs/runbook.md), nunca com senha versionada.

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'app_writer') THEN
        CREATE ROLE app_writer NOLOGIN;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'app_reader') THEN
        CREATE ROLE app_reader NOLOGIN;
    END IF;
END
$$;

GRANT USAGE ON SCHEMA garimpo TO app_writer, app_reader;

-- Pipeline: leitura e escrita em tudo do schema.
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA garimpo TO app_writer;
ALTER DEFAULT PRIVILEGES IN SCHEMA garimpo GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO app_writer;

-- Leitura restrita a views de relatório (sem audit_log, kv_state, niche.config_json).
CREATE OR REPLACE VIEW garimpo.v_daily_niche AS
SELECT ps.run_date, ps.niche_id,
       count(*) AS products_scored,
       sum(ps.eligible) AS products_eligible,
       max(ps.score) AS best_score
FROM garimpo.product_score ps
GROUP BY ps.run_date, ps.niche_id;

CREATE OR REPLACE VIEW garimpo.v_content_performance AS
SELECT c.id AS content_id, c.niche_id, c.channel, c.run_date, c.status, c.score, c.pick_reason,
       p.title, p.price, p.commission_rate,
       (SELECT count(*) FROM garimpo.click_event e WHERE e.content_id = c.id) AS clicks,
       (SELECT count(*) FROM garimpo.conversion v WHERE v.content_id = c.id) AS orders,
       (SELECT coalesce(sum(v.commission), 0) FROM garimpo.conversion v WHERE v.content_id = c.id) AS commission
FROM garimpo.content_item c
JOIN garimpo.product p ON p.id = c.product_id;

GRANT SELECT ON garimpo.v_daily_niche, garimpo.v_content_performance TO app_reader;
ALTER ROLE app_reader SET statement_timeout = '5s';

-- RLS em todas as tabelas; só app_writer tem política. O dono (migrator) não é afetado.
DO $$
DECLARE t record;
BEGIN
    FOR t IN SELECT tablename FROM pg_tables WHERE schemaname = 'garimpo' LOOP
        EXECUTE format('ALTER TABLE garimpo.%I ENABLE ROW LEVEL SECURITY', t.tablename);
        IF NOT EXISTS (
            SELECT 1 FROM pg_policies
            WHERE schemaname = 'garimpo' AND tablename = t.tablename AND policyname = 'app_writer_all'
        ) THEN
            EXECUTE format(
                'CREATE POLICY app_writer_all ON garimpo.%I FOR ALL TO app_writer USING (true) WITH CHECK (true)',
                t.tablename
            );
        END IF;
    END LOOP;
END
$$;

-- No Supabase, garante que os papéis da API pública não enxergam nada deste schema.
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'anon') THEN
        REVOKE ALL ON SCHEMA garimpo FROM anon;
        REVOKE ALL ON ALL TABLES IN SCHEMA garimpo FROM anon;
    END IF;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'authenticated') THEN
        REVOKE ALL ON SCHEMA garimpo FROM authenticated;
        REVOKE ALL ON ALL TABLES IN SCHEMA garimpo FROM authenticated;
    END IF;
END
$$;
