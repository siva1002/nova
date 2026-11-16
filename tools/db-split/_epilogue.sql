-- Loaded LAST into every service database (hand-written, not generated).
-- 1) version trigger on every table that has version + updated_at
-- 2) row-level security on every table with a NOT NULL workspace_id (plan/tech/09-security.md)
-- Contract: through PgBouncer in transaction mode, every transaction starts with
--   SELECT set_config('app.workspace_id', '<uuid>', true);   -- true = this transaction only
-- A session-level SET would leak to the next client of the pooled connection, so it is forbidden.

DO $$
DECLARE r record;
BEGIN
  FOR r IN
    SELECT c.table_name
    FROM information_schema.columns c
    JOIN information_schema.columns v ON v.table_schema = c.table_schema AND v.table_name = c.table_name AND v.column_name = 'updated_at'
    JOIN information_schema.tables t ON t.table_schema = c.table_schema AND t.table_name = c.table_name AND t.table_type = 'BASE TABLE'
    WHERE c.table_schema = current_schema() AND c.column_name = 'version'
      AND NOT EXISTS (SELECT 1 FROM pg_trigger g WHERE g.tgrelid = (quote_ident(c.table_name))::regclass AND g.tgname = c.table_name || '_bump_version')
  LOOP
    EXECUTE format('CREATE TRIGGER %I BEFORE UPDATE ON %I FOR EACH ROW EXECUTE FUNCTION bump_version()',
                   r.table_name || '_bump_version', r.table_name);
  END LOOP;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'app_user') THEN CREATE ROLE app_user NOLOGIN; END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'app_worker') THEN CREATE ROLE app_worker NOLOGIN BYPASSRLS; END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'app_migrator') THEN CREATE ROLE app_migrator NOLOGIN; END IF;
END $$;

DO $$
DECLARE t record;
BEGIN
  FOR t IN
    SELECT c.relname
      FROM pg_class c
      JOIN pg_namespace n ON n.oid = c.relnamespace AND n.nspname = current_schema()
      JOIN pg_attribute a ON a.attrelid = c.oid AND a.attname = 'workspace_id' AND NOT a.attisdropped
     WHERE c.relkind IN ('r','p') AND NOT c.relispartition AND a.attnotnull
       AND c.relname NOT IN ('outbox','inbox')        -- written by the app, read only by Debezium / the consumer itself
       AND coalesce(obj_description(c.oid, 'pg_class'), '') NOT LIKE 'rls:exempt%'   -- global services mark routing tables
  LOOP
    EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY', t.relname);
    EXECUTE format('ALTER TABLE %I FORCE ROW LEVEL SECURITY', t.relname);
    EXECUTE format('DROP POLICY IF EXISTS workspace_isolation ON %I', t.relname);
    EXECUTE format('CREATE POLICY workspace_isolation ON %I USING (workspace_id = current_workspace()) WITH CHECK (workspace_id = current_workspace())', t.relname);
  END LOOP;
END $$;

GRANT USAGE ON SCHEMA public TO app_user, app_worker;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO app_user, app_worker;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO app_user, app_worker;
-- Tables with a nullable workspace_id (built-in rows) are not covered above; services add their own policy.
-- hierarchy: status_templates (built-ins have NULL workspace_id)
DO $$ BEGIN
  IF to_regclass('status_templates') IS NOT NULL THEN
    EXECUTE 'ALTER TABLE status_templates ENABLE ROW LEVEL SECURITY';
    EXECUTE 'DROP POLICY IF EXISTS status_templates_read ON status_templates';
    EXECUTE 'DROP POLICY IF EXISTS status_templates_write ON status_templates';
    EXECUTE 'CREATE POLICY status_templates_read ON status_templates FOR SELECT USING (workspace_id IS NULL OR workspace_id = current_workspace())';
    EXECUTE 'CREATE POLICY status_templates_write ON status_templates FOR ALL USING (workspace_id = current_workspace()) WITH CHECK (workspace_id = current_workspace())';
  END IF;
  -- audit: append-only for the app roles
  IF to_regclass('audit_log') IS NOT NULL THEN
    EXECUTE 'REVOKE UPDATE, DELETE, TRUNCATE ON audit_log, security_events, data_access_log FROM app_user, app_worker';
  END IF;
END $$;
