-- ============================================================================
-- Migration: Create v2_image_review_decisions
-- Purpose: Phase B — V2-native decisions table keyed on v2_image_assets.img_id.
--          Mirrors the V1 image_review_decisions shape (sql/09_create_image_review_schema.sql
--          + sql/15_rename_cohort_heatmap_to_parfait.sql) so the migrate_image_decisions_to_v2
--          script (Phase B2) can copy existing V1 decisions without schema translation.
-- ============================================================================

CREATE TABLE IF NOT EXISTS v2_image_review_decisions (
    image_decision_id BIGSERIAL PRIMARY KEY,

    img_id UUID NOT NULL UNIQUE
        REFERENCES v2_image_assets(img_id) ON DELETE CASCADE,

    decision TEXT NOT NULL,

    chart_type TEXT,

    rejection_reason TEXT,

    reviewer_id TEXT,
    reviewer_notes TEXT,
    review_time_seconds INT,

    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT check_v2_image_decision CHECK (
        decision IN ('relevant', 'not_relevant')
    ),
    CONSTRAINT check_v2_image_chart_type CHECK (
        chart_type IS NULL OR
        chart_type IN (
            'cohort_table',
            'cohort_parfait',
            'line_chart',
            'bar_chart',
            'stacked_bar',
            'other_chart',
            'mixed'
        )
    ),
    CONSTRAINT check_v2_image_rejection_reason CHECK (
        rejection_reason IS NULL OR
        rejection_reason IN (
            'decorative',
            'not_a_chart',
            'wrong_subject',
            'duplicate',
            'unreadable',
            'other'
        )
    ),
    CONSTRAINT check_v2_image_relevant_has_chart_type CHECK (
        decision != 'relevant' OR chart_type IS NOT NULL
    ),
    CONSTRAINT check_v2_image_not_relevant_has_reason CHECK (
        decision != 'not_relevant' OR rejection_reason IS NOT NULL
    )
);

CREATE INDEX IF NOT EXISTS idx_v2_image_decisions_decision
    ON v2_image_review_decisions(decision);

CREATE INDEX IF NOT EXISTS idx_v2_image_decisions_chart_type
    ON v2_image_review_decisions(chart_type)
    WHERE chart_type IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_v2_image_decisions_rejection
    ON v2_image_review_decisions(rejection_reason)
    WHERE rejection_reason IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_v2_image_decisions_created
    ON v2_image_review_decisions(created_at);

CREATE INDEX IF NOT EXISTS idx_v2_image_decisions_reviewer
    ON v2_image_review_decisions(reviewer_id)
    WHERE reviewer_id IS NOT NULL;

COMMENT ON TABLE v2_image_review_decisions IS
    'Human classification decisions on v2_image_assets (V2-native; replaces V1 image_review_decisions).';
COMMENT ON COLUMN v2_image_review_decisions.img_id IS
    'Image being decided. UNIQUE — one decision per image.';
