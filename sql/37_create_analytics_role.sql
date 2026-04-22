-- Migration 37: Create read-only analytics role for BI tooling (Metabase, etc.)
--
-- Why: The Flask app connects as the owner/superuser role. A separate role with
-- SELECT-only privileges is the primary safeguard that lets us point a browser-
-- based query UI (Metabase) at the database without risk of writes or runaway
-- queries. The statement_timeout guardrails protect Neon compute budget.
--
-- Operator note: The password is NOT stored in this migration. Set it via:
--     ALTER ROLE metabase_ro PASSWORD '<value from env METABASE_DB_PASSWORD>';
-- immediately after applying. Rotate by repeating that ALTER.
--
-- cluster-ddl-ok: CREATE/ALTER ROLE hits cluster-scoped pg_authid; under
-- pytest-xdist this serialises via the Postgres advisory lock in
-- tests/integration/conftest.py::_apply_migrations_to_test_db. See also
-- scripts/pre-commit-cluster-ddl-guard.sh.

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'metabase_ro') THEN
        CREATE ROLE metabase_ro LOGIN PASSWORD 'change_me_immediately';
    END IF;
END
$$;

-- Connection privileges. Dynamic SQL so this works on any DB name
-- (filings_analysis locally, whatever Neon uses in prod).
DO $$
BEGIN
    EXECUTE format('GRANT CONNECT ON DATABASE %I TO metabase_ro', current_database());
END
$$;
GRANT USAGE ON SCHEMA public TO metabase_ro;

-- Read-only on all current tables + views
GRANT SELECT ON ALL TABLES IN SCHEMA public TO metabase_ro;

-- Read-only on anything created in the future (new analytics views, etc.)
ALTER DEFAULT PRIVILEGES IN SCHEMA public
    GRANT SELECT ON TABLES TO metabase_ro;

-- Query guardrails: kill runaway queries and stuck idle transactions.
-- These are per-role defaults; any session can still tighten further.
ALTER ROLE metabase_ro SET statement_timeout = '30s';
ALTER ROLE metabase_ro SET idle_in_transaction_session_timeout = '60s';
ALTER ROLE metabase_ro SET lock_timeout = '5s';

COMMENT ON ROLE metabase_ro IS
    'Read-only role for external BI tools (Metabase). Query/idle timeouts enforced.';
