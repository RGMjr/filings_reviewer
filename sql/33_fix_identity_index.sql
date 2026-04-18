-- ============================================================================
-- Migration 33: Fix idx_v2_metric_facts_identity_unique to include source_type
-- ============================================================================
--
-- ISSUE #13 — V2 metric facts identity index drift (diagnosed 2026-04-18)
--
-- Root Cause:
--   sql/23_chart_source_dedup.sql correctly defines a 9-column partial UNIQUE
--   index that includes `source_type`. However, the live Neon prod DB still
--   carries the original 8-column index (no `source_type`) despite migration 23
--   being recorded in schema_migrations as applied.
--
--   Best hypothesis: the index was restored to 8-column shape via a pg_dump
--   schema snapshot that pre-dated sql/23 (or an early sql/09_v2_schema.sql
--   snapshot without the sql/23 change), or the migration was applied, then the
--   DB was recreated from a snapshot taken before sql/23 ran. Because
--   schema_migrations stores only file-level applied/checksum records (not DDL
--   state), there is no automatic way to detect that the index reverted.
--
-- Impact:
--   With an 8-column index, a CHART-sourced fact and a TEXT-sourced fact for
--   the same (doc_id, metric, period, cohort, customer_type, unit, scope) slot
--   are NOT independently unique at the DB layer. The persistence layer uses
--   delete-then-insert (not ON CONFLICT), so in practice no silent overwrite
--   occurs per-run, but the missing column means the uniqueness contract relied
--   upon by migration 25 (cross-source confirmation) is not enforced at the DB
--   level. Phase 3 cross-source confirmation depends on chart and text facts
--   being independently unique.
--
-- Fix:
--   Idempotently drop and recreate the index with all 9 columns. Because the
--   persistence layer uses DELETE-then-INSERT (not ON CONFLICT) for facts, this
--   migration is safe to apply at any time — no INSERT conflict resolution path
--   depends on the old 8-column shape.
--
-- Safety:
--   - DROP INDEX IF EXISTS is safe; the index will be rebuilt immediately.
--   - No data is modified. Pure DDL.
--   - No code deploy required before or after — the persistence layer already
--     passes source_type as a column value; the index shape has no effect on
--     INSERT column lists.
--   - Idempotent: running this migration twice drops and rebuilds the same index.
--
-- References:
--   docs/KNOWN_ISSUES.md Issue #13 (diagnosed 2026-04-18)
--   docs/architecture/data-model.md Known Discrepancies
--   sql/23_chart_source_dedup.sql  — original 9-col DDL intent
--   sql/25_cross_source_confirmation.sql — depends on independent CHART+TEXT slots
--   src/extraction_v2/models.py::MetricFact.identity_tuple — 9-element identity
-- ============================================================================

BEGIN;

-- Drop current 8-column index (or 9-column if somehow already correct)
DROP INDEX IF EXISTS idx_v2_metric_facts_identity_unique;

-- Recreate with all 9 identity columns, matching MetricFact.identity_tuple() and
-- the original intent of sql/23_chart_source_dedup.sql.
-- The partial predicate (no WHERE clause) covers all rows — full-table unique.
CREATE UNIQUE INDEX idx_v2_metric_facts_identity_unique
ON v2_metric_facts (
    doc_id,
    canonical_metric_id,
    COALESCE(period_start,   '1900-01-01'::date),
    COALESCE(period_end,     '1900-01-01'::date),
    unit,
    scope,
    COALESCE(cohort_def,     ''),
    COALESCE(customer_type,  ''),
    source_type
);

COMMIT;
