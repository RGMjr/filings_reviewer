-- Migration 15: Rename chart_type value 'cohort_heatmap' to 'cohort_parfait'
--
-- Safe to run: no existing decisions use cohort_heatmap (verified 2026-03-29).
-- Drops and recreates the check_chart_type constraint on image_review_decisions.

ALTER TABLE image_review_decisions
    DROP CONSTRAINT check_chart_type;

ALTER TABLE image_review_decisions
    ADD CONSTRAINT check_chart_type CHECK (
        chart_type IS NULL OR
        chart_type IN ('cohort_table', 'cohort_parfait', 'line_chart', 'bar_chart', 'stacked_bar', 'other_chart', 'mixed')
    );

COMMENT ON COLUMN image_review_decisions.chart_type IS 'Type of chart if relevant: cohort_table, cohort_parfait, line_chart, bar_chart, stacked_bar, other_chart, mixed';
