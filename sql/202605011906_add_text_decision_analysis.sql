-- Migration 202605011906: add_text_decision_analysis
--
-- Adds three tables that back the "Update Text Pattern Analysis" surface on
-- /v2/review/stats. Mirrors the model_training_runs / image-classifier flow
-- but for rule-based text extraction (no trained model — the output is a
-- structured pattern report that informs manual edits to
-- config/metric_keywords.yaml + src/extraction_v2/stages/false_positive_filter.py).
--
-- text_decision_analysis_runs   — one row per analyze-text-decisions invocation
-- text_decision_metric_summary  — per-(run, metric) decision counts +
--                                 rejection_category histogram + top correction targets
-- text_decision_phrase_findings — per-(run, metric, phrase) high-incidence
--                                 root-cause phrases mined from rejection_reason,
--                                 reviewer_notes, and a window of segment_text

BEGIN;

CREATE TABLE IF NOT EXISTS text_decision_analysis_runs (
    id                       UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    started_at               TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at             TIMESTAMPTZ,
    status                   TEXT NOT NULL DEFAULT 'running'
        CHECK (status IN ('running', 'succeeded', 'failed')),
    num_decisions_analyzed   INTEGER,
    num_metrics_analyzed     INTEGER,
    triggered_by             TEXT,
    error                    TEXT
);

CREATE INDEX IF NOT EXISTS idx_tdar_completed
    ON text_decision_analysis_runs (completed_at DESC);

CREATE INDEX IF NOT EXISTS idx_tdar_status
    ON text_decision_analysis_runs (status);

CREATE TABLE IF NOT EXISTS text_decision_metric_summary (
    run_id                  UUID NOT NULL
        REFERENCES text_decision_analysis_runs(id) ON DELETE CASCADE,
    metric_id               TEXT NOT NULL,
    total_decisions         INTEGER NOT NULL,
    accept_count            INTEGER NOT NULL,
    reject_count            INTEGER NOT NULL,
    correct_count           INTEGER NOT NULL,
    rejection_categories    JSONB NOT NULL,
    top_correction_targets  JSONB NOT NULL,
    PRIMARY KEY (run_id, metric_id)
);

CREATE TABLE IF NOT EXISTS text_decision_phrase_findings (
    id                  BIGSERIAL PRIMARY KEY,
    run_id              UUID NOT NULL
        REFERENCES text_decision_analysis_runs(id) ON DELETE CASCADE,
    metric_id           TEXT NOT NULL,
    decision_type       TEXT NOT NULL CHECK (decision_type IN ('reject', 'correct')),
    phrase              TEXT NOT NULL,
    phrase_ngram_size   SMALLINT NOT NULL,
    source_field        TEXT NOT NULL
        CHECK (source_field IN ('rejection_reason', 'reviewer_notes', 'segment_text')),
    occurrence_count    INTEGER NOT NULL,
    pct_of_decisions    NUMERIC(5,2) NOT NULL,
    examples            JSONB NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_tdpf_run_metric
    ON text_decision_phrase_findings (run_id, metric_id, decision_type, occurrence_count DESC);

COMMIT;
