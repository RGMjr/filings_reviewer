-- Migration 19: Add predicted_relevance column to image_review_candidates
--
-- Stores the output of the image relevance model (0.0-1.0) for each candidate.
-- NULL means the candidate has not been scored yet.
-- Used to sort review queue so likely-relevant images appear first.

ALTER TABLE image_review_candidates
    ADD COLUMN IF NOT EXISTS predicted_relevance NUMERIC(5,4);

CREATE INDEX IF NOT EXISTS idx_image_candidates_predicted_relevance
    ON image_review_candidates (predicted_relevance DESC NULLS LAST)
    WHERE review_status = 'pending';

COMMENT ON COLUMN image_review_candidates.predicted_relevance IS
    'Predicted probability of relevance from image relevance model (0.0-1.0). NULL = not yet scored.';
