-- Migration 202605121359: add_text_pattern_simulation_runs
--
-- Adds two tables for the simulate-and-ship flow on /v2/review/stats.
-- When an admin accepts an exclusion_pattern recommendation they can
-- click "Simulate accepted recommendations" to see per-metric R/P/F1
-- deltas and Tier-1 regression status before the change ships.
--
--   text_pattern_simulation_runs   — one row per button click
--   text_pattern_simulation_deltas — one row per (run, rec, metric_id)
--
-- Both FK to text_pattern_recommendation_decisions (must exist first,
-- created by 202605012056_add_recommendation_decisions.sql).

BEGIN;

CREATE TABLE IF NOT EXISTS text_pattern_simulation_runs (
    id                              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    status                          TEXT NOT NULL
        CHECK (status IN ('running', 'succeeded', 'failed')),
    started_at                      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at                    TIMESTAMPTZ,
    num_recs_simulated              INTEGER,
    num_companies_validated         INTEGER,
    tier1_presence_recall_baseline  NUMERIC(6,4),
    tier1_presence_recall_patched   NUMERIC(6,4),
    tier2_presence_recall_baseline  NUMERIC(6,4),
    tier2_presence_recall_patched   NUMERIC(6,4),
    tier1_regressed                 BOOLEAN NOT NULL DEFAULT FALSE,
    runs_agree                      BOOLEAN NOT NULL DEFAULT FALSE,
    config_snapshot_hash            TEXT,
    triggered_by                    TEXT,
    error                           TEXT,
    created_at                      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Used by the stale-row sweep (status='running' AND started_at < NOW()-1h)
-- and by status polling on the most-recent run.
CREATE INDEX IF NOT EXISTS idx_tpsr_status_started
    ON text_pattern_simulation_runs (status, started_at DESC);

CREATE TABLE IF NOT EXISTS text_pattern_simulation_deltas (
    id                        UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    run_id                    UUID NOT NULL
        REFERENCES text_pattern_simulation_runs(id) ON DELETE CASCADE,
    recommendation_decision_id UUID
        REFERENCES text_pattern_recommendation_decisions(id) ON DELETE SET NULL,
    metric_id                 TEXT NOT NULL,
    baseline_recall           NUMERIC(6,4),
    baseline_precision        NUMERIC(6,4),
    baseline_f1               NUMERIC(6,4),
    patched_recall            NUMERIC(6,4),
    patched_precision         NUMERIC(6,4),
    patched_f1                NUMERIC(6,4),
    coverage_filings          INTEGER,
    coverage_facts            INTEGER,
    created_at                TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_tpsd_run_id
    ON text_pattern_simulation_deltas (run_id);

COMMIT;
