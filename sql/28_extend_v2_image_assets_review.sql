-- ============================================================================
-- Migration: Extend v2_image_assets with review columns
-- Purpose: Phase B of V1 image review retirement — adds review_status and
--          predicted_relevance columns so the V2 unified review UI can read
--          directly from v2_image_assets without the V1 bridge.
-- ============================================================================

ALTER TABLE v2_image_assets
    ADD COLUMN IF NOT EXISTS review_status TEXT NOT NULL DEFAULT 'pending';

ALTER TABLE v2_image_assets
    ADD COLUMN IF NOT EXISTS predicted_relevance NUMERIC(5,4);

-- CHECK constraint mirrors V1 image_review_candidates (sql/09_create_image_review_schema.sql
-- + sql/20_add_auto_rejected_status.sql) so the review-queue semantics are preserved.
ALTER TABLE v2_image_assets
    DROP CONSTRAINT IF EXISTS check_v2_image_assets_review_status;

ALTER TABLE v2_image_assets
    ADD CONSTRAINT check_v2_image_assets_review_status CHECK (
        review_status IN ('pending', 'reviewed', 'skipped', 'auto_rejected')
    );

CREATE INDEX IF NOT EXISTS idx_v2_image_assets_review_status
    ON v2_image_assets(review_status);

CREATE INDEX IF NOT EXISTS idx_v2_image_assets_predicted_relevance
    ON v2_image_assets(predicted_relevance)
    WHERE predicted_relevance IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_v2_image_assets_filing_pending
    ON v2_image_assets(doc_id, review_status)
    WHERE review_status = 'pending';

COMMENT ON COLUMN v2_image_assets.review_status IS
    'Review queue status: pending / reviewed / skipped / auto_rejected.';
COMMENT ON COLUMN v2_image_assets.predicted_relevance IS
    'ML-scored relevance (0-1). Distinct from relevance_score (heuristic, set at extraction time).';
