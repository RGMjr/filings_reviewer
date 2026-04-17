-- ============================================================================
-- Migration: Drop V1 image review tables
-- Purpose: Final step of Phase B V1 image-review retirement. V2-native
--          equivalents are v2_image_assets (review columns added in sql/28)
--          and v2_image_review_decisions (created in sql/29).
--
-- PRODUCTION PREREQUISITE: run `scripts/migrate_image_decisions_to_v2.py`
-- before applying this migration, so existing V1 decisions and review_status
-- values are copied into V2 first. The migration script is idempotent.
-- ============================================================================

DROP TABLE IF EXISTS image_review_decisions CASCADE;
DROP TABLE IF EXISTS image_review_candidates CASCADE;

-- Analysis views that depended on V1 tables were dropped via CASCADE:
--   v_image_review_progress_by_filing
--   v_image_decision_stats_by_tier
--   v_image_chart_type_distribution
--   v_image_rejection_reasons
