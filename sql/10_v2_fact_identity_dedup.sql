-- V2 Metric Facts: Identity-based deduplication constraint
--
-- Prevents duplicate accumulation across re-extractions by adding a UNIQUE
-- constraint on the identity tuple. Uses COALESCE for nullable fields so
-- NULLs are treated as equal (standard SQL NULL != NULL would break uniqueness).
--
-- The identity tuple matches MetricFact.identity_tuple():
--   (doc_id, canonical_metric_id, period_start, period_end, unit, scope, cohort_def, customer_type)
--
-- Note: value is NOT part of the identity constraint — the same metric/period/scope
-- combination should not appear twice even if values differ slightly.

-- Drop the old non-unique identity index (replaced by the unique index below)
DROP INDEX IF EXISTS idx_v2_metric_facts_identity;

-- Create a UNIQUE index using COALESCE for nullable fields
CREATE UNIQUE INDEX IF NOT EXISTS idx_v2_metric_facts_identity_unique
ON v2_metric_facts (
    doc_id,
    canonical_metric_id,
    COALESCE(period_start, '1900-01-01'::date),
    COALESCE(period_end, '1900-01-01'::date),
    unit,
    scope,
    COALESCE(cohort_def, ''),
    COALESCE(customer_type, '')
);

COMMENT ON INDEX idx_v2_metric_facts_identity_unique IS
    'Prevents duplicate facts across re-extractions. Uses COALESCE sentinels for nullable fields.';
