-- ============================================================================
-- Migration 44: Extend rejection_reason enum with 'table_handled_elsewhere'
-- Purpose: classify stage needs to distinguish "this image is a table —
--          a different pipeline extracts its data" from the legacy "other"
--          bucket. Previously the harness (metric-classify bake-off) mapped
--          both to 'other', making reviewer audits noisier than necessary.
-- Closes: known-issue #93 (legacy-093-rejection-reason-enum-lacks-table-handled-elsewhere)
--
-- Idempotent: DROP CONSTRAINT IF EXISTS + ADD CONSTRAINT.
-- ============================================================================

ALTER TABLE v2_image_review_decisions
    DROP CONSTRAINT IF EXISTS check_v2_image_rejection_reason;

ALTER TABLE v2_image_review_decisions
    ADD CONSTRAINT check_v2_image_rejection_reason CHECK (
        rejection_reason IS NULL OR
        rejection_reason IN (
            'decorative',
            'not_a_chart',
            'wrong_subject',
            'duplicate',
            'unreadable',
            'table_handled_elsewhere',
            'other'
        )
    );
