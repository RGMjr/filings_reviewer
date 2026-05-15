-- Migration 202605141809: text_pattern_ship_runs
--
-- Track D of the simulate-and-ship flow. One row per "Ship to PR" click —
-- captures which accepted recommendations are being shipped, which
-- simulation gated the ship, and the resulting GitHub PR.
--
-- Drained by the worker daemon (src/universe/onboarding_runner.py via
-- src/ml/retrain_runner.py::claim_next_queued_ship_pr) — same FOR UPDATE
-- SKIP LOCKED pattern as the image-classifier retrain queue.
--
-- Idempotent: re-running the migration against a partially-applied DB is
-- a no-op (CREATE TABLE / INDEX IF NOT EXISTS).

BEGIN;

CREATE TABLE IF NOT EXISTS text_pattern_ship_runs (
    id                          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    status                      TEXT NOT NULL
        CHECK (status IN ('queued', 'running', 'succeeded', 'failed')),
    -- Worker lock: NOW() + lock_ttl on queued→running transition. The
    -- stale-row sweep (status='running' AND run_lock_until < NOW()) on the
    -- endpoint's entry path catches SIGKILL/OOM cases.
    run_lock_until              TIMESTAMPTZ,
    -- Array of recommendation_decision UUIDs being shipped in this PR.
    -- JSONB so the worker can read them in one column without joining.
    recommendation_decision_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
    -- The succeeded simulation run that gated this ship. Audit trail back
    -- to the safety check. SET NULL on delete so a sim-run cleanup doesn't
    -- cascade-delete the ship row.
    simulation_run_id           UUID
        REFERENCES text_pattern_simulation_runs(id) ON DELETE SET NULL,
    -- Populated by scripts/open_pattern_recommendation_pr.py once the
    -- corresponding artefact exists.
    branch_name                 TEXT,
    pr_number                   INTEGER,
    pr_url                      TEXT,
    -- reviewer_id from the POST body that enqueued this row.
    triggered_by                TEXT,
    started_at                  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at                TIMESTAMPTZ,
    error                       TEXT,
    created_at                  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Used by the worker claim (status='queued') and the stale-row sweep
-- (status='running' AND run_lock_until < NOW()).
CREATE INDEX IF NOT EXISTS idx_tpship_status_started
    ON text_pattern_ship_runs (status, started_at DESC);

COMMIT;
