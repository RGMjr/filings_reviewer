-- ============================================================================
-- Migration 18: Add 'presentation' to check_detection_tier constraint
-- Purpose: Allow image candidates discovered from presentation filings to use
--          'presentation' as their detection_tier value
-- Date: 2026-04-06
-- ============================================================================

ALTER TABLE image_review_candidates
    DROP CONSTRAINT check_detection_tier;

ALTER TABLE image_review_candidates
    ADD CONSTRAINT check_detection_tier CHECK (
        detection_tier IS NULL OR
        detection_tier IN ('tier_1_cohort', 'tier_2_large', 'tier_3_all', 'seed_list', 'presentation')
    );
