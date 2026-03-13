-- Remove duplicate v2_metric_facts rows before the unique identity index
-- is created by 10_v2_fact_identity_dedup.sql.
--
-- Keeps the row with the highest confidence per identity tuple
-- (ties broken by newest created_at).
--
-- The PARTITION BY uses the same COALESCE expressions as migration 10's
-- unique index to guarantee alignment.

-- Step 1: Identify rows to delete (all but the "winner" per identity group)
WITH doomed AS (
    SELECT fact_id
    FROM (
        SELECT fact_id,
               ROW_NUMBER() OVER (
                   PARTITION BY doc_id,
                                canonical_metric_id,
                                COALESCE(period_start, '1900-01-01'::date),
                                COALESCE(period_end, '1900-01-01'::date),
                                unit,
                                scope,
                                COALESCE(cohort_def, ''),
                                COALESCE(customer_type, '')
                   ORDER BY confidence DESC, created_at DESC NULLS LAST
               ) AS rn
        FROM v2_metric_facts
    ) ranked
    WHERE rn > 1
)
-- Step 2: Clear self-FK references to doomed rows (primary_fact_id has NO ACTION)
-- NOTE: cleared CTE executes unconditionally per PostgreSQL CTE semantics
, cleared AS (
    UPDATE v2_metric_facts
    SET primary_fact_id = NULL
    WHERE primary_fact_id IN (SELECT fact_id FROM doomed)
    RETURNING 1
)
-- Step 3: Delete the duplicates (v2_fact_evidence cascades via ON DELETE CASCADE)
DELETE FROM v2_metric_facts
WHERE fact_id IN (SELECT fact_id FROM doomed);
