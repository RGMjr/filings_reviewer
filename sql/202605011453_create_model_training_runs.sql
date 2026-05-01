-- Migration 202605011453: create model_training_runs
--
-- Tracks training runs of the image relevance classifier (data/image_model/
-- relevance_model.joblib). Each row anchors "decisions since last update"
-- counters surfaced on the Metric Analytics Summary tab and gates the
-- (Phase 3) Update Image Classifier button by counting v2_image_metric_
-- confirmations created after the most recent successful run.
--
-- Idempotency: CREATE TABLE IF NOT EXISTS + CREATE INDEX IF NOT EXISTS.

BEGIN;

CREATE TABLE IF NOT EXISTS model_training_runs (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    model_type          TEXT NOT NULL,                              -- 'image_relevance' for now
    started_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at        TIMESTAMPTZ,
    status              TEXT NOT NULL DEFAULT 'running'
                        CHECK (status IN ('running', 'succeeded', 'failed')),
    num_training_rows   INTEGER,
    num_positive_rows   INTEGER,
    model_path          TEXT,
    report_path         TEXT,
    triggered_by        TEXT,                                       -- reviewer_id, 'cli', or 'cron'
    error               TEXT
);

CREATE INDEX IF NOT EXISTS idx_mtr_model_type_completed
    ON model_training_runs(model_type, completed_at DESC);

COMMIT;
