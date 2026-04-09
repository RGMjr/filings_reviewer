-- Migration 20: Add 'auto_rejected' to image_review_candidates review_status constraint.
-- Auto-rejected candidates are those scored below the relevance threshold by the ML model;
-- they are excluded from the human review queue without requiring a manual decision.

ALTER TABLE image_review_candidates
    DROP CONSTRAINT check_review_status;

ALTER TABLE image_review_candidates
    ADD CONSTRAINT check_review_status CHECK (
        review_status IN ('pending', 'reviewed', 'skipped', 'auto_rejected')
    );
