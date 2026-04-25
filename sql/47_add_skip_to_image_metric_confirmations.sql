-- Migration 47: Add 'skip' to v2_image_metric_confirmations.decision enum
--
-- Adds per-metric Skip to the reviewer decision surface so A/R/C/S/Add all
-- live at per-(image, metric) grain. Image-grain skip endpoint
-- (/image-candidates/<img_id>/skip) remains for "skip the whole image".
--
-- Migration number 47 matches the cross-pivot coordination memo
-- (docs/operations/text-pipeline-presence-pivot-plan.md, PR #183).
--
-- Idempotent: DROP CONSTRAINT IF EXISTS + ADD CONSTRAINT.

ALTER TABLE v2_image_metric_confirmations
    DROP CONSTRAINT IF EXISTS v2_image_metric_confirmations_decision_check;

ALTER TABLE v2_image_metric_confirmations
    ADD CONSTRAINT v2_image_metric_confirmations_decision_check CHECK (
        decision IN ('accept', 'reject', 'correct', 'add', 'skip')
    );
