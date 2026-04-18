-- ============================================================================
-- Migration 31: Drop V1 review tables + source_segments; create v2_audit_log.
-- Purpose: Final V1 retirement. Drops six V1 tables (review_candidates,
--          review_decisions, suppressed_candidates, review_audit_log,
--          learned_patterns, source_segments). Replaces review_audit_log with
--          v2_audit_log (no candidate_id FK). Drops V1 → source_segments FKs
--          on V2 tables.
--
-- PRODUCTION PREREQUISITE:
--   1. Confirm database backup snapshot is complete.
--   2. Export labeled review data for archive:
--        pg_dump "$DATABASE_URL" -t review_decisions \
--          --data-only --column-inserts \
--          > data/archive/review_decisions_pre_drop_2026-04-18.sql
--        pg_dump "$DATABASE_URL" -t review_candidates \
--          --data-only --column-inserts \
--          > data/archive/review_candidates_pre_drop_2026-04-18.sql
--   3. Deploy the code changes (Phase 3) and let them run for at least one
--      deploy cycle before applying this migration so stale requests do not
--      hit deleted methods.
-- ============================================================================

-- 1. Drop V2 → V1 FKs that still reference source_segments.
ALTER TABLE v2_image_assets DROP CONSTRAINT IF EXISTS v2_image_assets_segment_id_fkey;
ALTER TABLE v2_tables       DROP CONSTRAINT IF EXISTS v2_tables_segment_id_fkey;

-- 2. Drop V1 analysis views that depend on V1 tables (CASCADE covers these
--    too, but explicit drops keep intent clear).
DROP VIEW IF EXISTS v_review_progress_by_filing;
DROP VIEW IF EXISTS v_decision_stats_by_metric;
DROP VIEW IF EXISTS v_rejection_reasons;

-- 3. Drop V1 tables (dependents first; CASCADE sweeps remaining FKs/indices).
DROP TABLE IF EXISTS suppressed_candidates CASCADE;
DROP TABLE IF EXISTS learned_patterns CASCADE;
DROP TABLE IF EXISTS review_decisions CASCADE;
DROP TABLE IF EXISTS review_audit_log CASCADE;
DROP TABLE IF EXISTS review_candidates CASCADE;
DROP TABLE IF EXISTS source_segments CASCADE;

-- 4. Create v2_audit_log — replaces review_audit_log without the candidate_id
--    FK (V1 candidates are gone). Schema mirrors the V1 columns we still use.
CREATE TABLE v2_audit_log (
    log_id          BIGSERIAL PRIMARY KEY,
    timestamp       TIMESTAMPTZ NOT NULL DEFAULT now(),
    session_id      VARCHAR(255),
    ip_address      INET,
    user_agent      TEXT,
    route_name      VARCHAR(100) NOT NULL,
    http_method     VARCHAR(10) NOT NULL,
    url_path        TEXT NOT NULL,
    filing_id       BIGINT REFERENCES filings(filing_id) ON DELETE SET NULL,
    query_params    JSONB,
    response_status INT NOT NULL,
    response_time_ms INT,
    CONSTRAINT check_v2_audit_http_method
        CHECK (http_method IN ('GET', 'POST', 'PUT', 'DELETE', 'PATCH')),
    CONSTRAINT check_v2_audit_response_status
        CHECK (response_status >= 100 AND response_status < 600)
);

CREATE INDEX idx_v2_audit_log_timestamp ON v2_audit_log(timestamp DESC);
CREATE INDEX idx_v2_audit_log_session   ON v2_audit_log(session_id) WHERE session_id IS NOT NULL;
CREATE INDEX idx_v2_audit_log_route     ON v2_audit_log(route_name);
CREATE INDEX idx_v2_audit_log_filing    ON v2_audit_log(filing_id) WHERE filing_id IS NOT NULL;

COMMENT ON TABLE  v2_audit_log IS 'Audit trail for V2 review/api_unified routes (replaces V1 review_audit_log).';
COMMENT ON COLUMN v2_audit_log.route_name IS 'Flask endpoint name (e.g., review_unified.review_filing).';
COMMENT ON COLUMN v2_audit_log.response_time_ms IS 'Server-side response time in milliseconds.';

-- 5. Verification.
DO $$
DECLARE
    surviving_tables TEXT[];
BEGIN
    SELECT array_agg(table_name ORDER BY table_name)
    INTO surviving_tables
    FROM information_schema.tables
    WHERE table_schema = 'public'
      AND table_name IN (
          'review_candidates',
          'review_decisions',
          'suppressed_candidates',
          'review_audit_log',
          'learned_patterns',
          'source_segments'
      );

    IF surviving_tables IS NOT NULL THEN
        RAISE EXCEPTION 'V1 tables still exist after migration 31: %', surviving_tables;
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM information_schema.tables
        WHERE table_name = 'v2_audit_log'
    ) THEN
        RAISE EXCEPTION 'v2_audit_log was not created';
    END IF;

    RAISE NOTICE 'Migration 31 complete: 6 V1 tables dropped; v2_audit_log created.';
END $$;
