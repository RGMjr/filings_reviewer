-- Migration 202604291500: add_reviewer_chart_type_to_v2_image_assets
--
-- Adds a nullable `reviewer_chart_type` column to v2_image_assets so that
-- confirmation-derived corpus rows can carry the same chart-shape signal as
-- legacy v2_image_review_decisions rows.  This restores Tier-1 stratification
-- for the growing confirmation surface (gh-196, Option A1-narrow).
--
-- The CHECK constraint mirrors sql/29_create_v2_image_review_decisions.sql
-- (check_v2_image_chart_type) exactly — same 7 semantic values.
--
-- The one-shot backfill UPDATE copies chart_type from the legacy decisions
-- table for the ~851 rows that already have image-level review decisions.
-- Post-deploy, new rows are populated by the reviewer UI chart-type capture
-- endpoint (follow-up: deferred per gh-196 plan PR 2 scope).
--
-- Idempotency: ADD COLUMN IF NOT EXISTS is safe to re-run.
-- Constraint drop+add is wrapped in an existence-checked DO block.

BEGIN;

-- 1. Add the nullable column.
ALTER TABLE v2_image_assets
    ADD COLUMN IF NOT EXISTS reviewer_chart_type TEXT NULL;

-- 2. Add CHECK constraint (idempotent: drop if exists first).
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.table_constraints
        WHERE table_name = 'v2_image_assets'
          AND constraint_name = 'check_v2_image_assets_reviewer_chart_type'
    ) THEN
        ALTER TABLE v2_image_assets
            DROP CONSTRAINT check_v2_image_assets_reviewer_chart_type;
    END IF;

    ALTER TABLE v2_image_assets
        ADD CONSTRAINT check_v2_image_assets_reviewer_chart_type CHECK (
            reviewer_chart_type IS NULL OR
            reviewer_chart_type IN (
                'cohort_table',
                'cohort_parfait',
                'line_chart',
                'bar_chart',
                'stacked_bar',
                'other_chart',
                'mixed'
            )
        );
END $$;

-- 3. One-shot backfill from legacy image review decisions.
--    Copies chart_type for all images that already have a legacy decision
--    with a non-NULL chart_type.  Safe to re-run (UPDATE is idempotent here
--    because it only sets the column where the legacy decision agrees).
UPDATE v2_image_assets a
    SET reviewer_chart_type = d.chart_type
FROM v2_image_review_decisions d
WHERE d.img_id = a.img_id
  AND d.chart_type IS NOT NULL;

-- 4. Partial index for efficient corpus queries filtered on non-NULL values.
CREATE INDEX IF NOT EXISTS idx_v2_image_assets_reviewer_chart_type
    ON v2_image_assets (reviewer_chart_type)
    WHERE reviewer_chart_type IS NOT NULL;

COMMIT;
