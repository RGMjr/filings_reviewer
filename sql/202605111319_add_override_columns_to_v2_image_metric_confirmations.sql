-- Migration 202605111319: add_override_columns_to_v2_image_metric_confirmations
--
-- Adds two columns to support admin override provenance:
--   override_reason         TEXT   — free-text reason; non-null marks an admin row.
--   supersedes_confirmation_id UUID — FK to the confirmation row being reversed.
--
-- A CHECK constraint enforces that if supersedes_confirmation_id is set,
-- override_reason must also be set (ordinary reviewer rows leave both NULL).
-- Admin rows that review a suppressed image with no prior decision have
-- override_reason set but supersedes_confirmation_id NULL — that is intentional
-- and API-enforced, not database-enforced.
--
-- All existing rows have supersedes_confirmation_id IS NULL, so the CHECK
-- passes by definition for every pre-existing row.
--
-- Idempotency: ADD COLUMN IF NOT EXISTS + DROP CONSTRAINT IF EXISTS before
-- ADD CONSTRAINT so re-runs against a partially-applied DB succeed cleanly.

BEGIN;

ALTER TABLE v2_image_metric_confirmations
    ADD COLUMN IF NOT EXISTS override_reason TEXT;

ALTER TABLE v2_image_metric_confirmations
    ADD COLUMN IF NOT EXISTS supersedes_confirmation_id UUID
        REFERENCES v2_image_metric_confirmations(id);

ALTER TABLE v2_image_metric_confirmations
    DROP CONSTRAINT IF EXISTS v2_image_metric_confirmations_override_reason_required;

ALTER TABLE v2_image_metric_confirmations
    ADD CONSTRAINT v2_image_metric_confirmations_override_reason_required
    CHECK (supersedes_confirmation_id IS NULL OR override_reason IS NOT NULL);

CREATE INDEX IF NOT EXISTS idx_v2_image_metric_confirmations_supersedes
    ON v2_image_metric_confirmations (supersedes_confirmation_id)
    WHERE supersedes_confirmation_id IS NOT NULL;

COMMIT;
