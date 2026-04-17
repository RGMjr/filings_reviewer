BEGIN;

-- Pre-flight: hard-block if any collisions exist under the new index definition
DO $$
DECLARE
    v_collision_count INTEGER;
BEGIN
    SELECT COUNT(*) INTO v_collision_count
    FROM (
        SELECT 1
        FROM v2_metric_facts
        GROUP BY
            doc_id,
            canonical_metric_id,
            COALESCE(period_start, '1900-01-01'::date),
            COALESCE(period_end,   '1900-01-01'::date),
            unit,
            scope,
            COALESCE(cohort_def,     ''),
            COALESCE(customer_type,  ''),
            source_type
        HAVING COUNT(*) > 1
    ) collisions;

    IF v_collision_count > 0 THEN
        RAISE EXCEPTION
            'Migration 23 blocked: % row group(s) collide under the new unique index. '
            'Resolve duplicates before applying this migration.',
            v_collision_count;
    END IF;
END $$;

-- Drop old index (was 8-column, without source_type)
DROP INDEX IF EXISTS idx_v2_metric_facts_identity_unique;

-- Create new 9-column unique index including source_type
CREATE UNIQUE INDEX idx_v2_metric_facts_identity_unique
ON v2_metric_facts (
    doc_id,
    canonical_metric_id,
    COALESCE(period_start, '1900-01-01'::date),
    COALESCE(period_end,   '1900-01-01'::date),
    unit,
    scope,
    COALESCE(cohort_def,    ''),
    COALESCE(customer_type, ''),
    source_type
);

COMMIT;
