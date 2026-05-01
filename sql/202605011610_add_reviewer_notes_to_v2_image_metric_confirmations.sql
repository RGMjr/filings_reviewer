-- Migration 202605011610: add reviewer_notes to v2_image_metric_confirmations
--
-- Mirrors v2_review_decisions.reviewer_notes (text-side). Captures free-text
-- observations on per-metric image decisions (accept / reject / correct /
-- add) so reviewers can record "why" alongside the categorical decision.
--
-- Phase 4 of the Metric Analytics rollout. The follow-up LLM-summarized
-- "Top Reviewer Themes" panel will read this column for image-side decisions
-- (Phase 4b PR, deferred).
--
-- Idempotency: ADD COLUMN IF NOT EXISTS.

BEGIN;

ALTER TABLE v2_image_metric_confirmations
    ADD COLUMN IF NOT EXISTS reviewer_notes TEXT;

COMMENT ON COLUMN v2_image_metric_confirmations.reviewer_notes IS
    'Free-text observation from the reviewer, max 1000 chars (validated at API '
    'layer). NULL when reviewer did not enter notes.';

COMMIT;
