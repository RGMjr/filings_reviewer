-- Migration 202605012350: add_queued_status_and_lock_to_model_training_runs
--
-- Adds the 'queued' status and a run_lock_until column to model_training_runs
-- so retrain rows can be claimed by a long-lived worker (filings-onboarding-runner)
-- via the same lock-TTL pattern used by v2_ingest_batches. Mirrors the queue+worker
-- pattern shipped for ingest in render.yaml so the web POST no longer has to
-- spawn a detached subprocess from gunicorn (gh-400).
--
-- Idempotent: re-runnable against partially-applied databases.

BEGIN;

ALTER TABLE model_training_runs DROP CONSTRAINT IF EXISTS model_training_runs_status_check;
ALTER TABLE model_training_runs
    ADD CONSTRAINT model_training_runs_status_check
    CHECK (status IN ('queued', 'running', 'succeeded', 'failed'));

ALTER TABLE model_training_runs ADD COLUMN IF NOT EXISTS run_lock_until TIMESTAMPTZ;

CREATE INDEX IF NOT EXISTS idx_mtr_queued_runs
    ON model_training_runs (model_type, started_at)
    WHERE status = 'queued';

COMMIT;
