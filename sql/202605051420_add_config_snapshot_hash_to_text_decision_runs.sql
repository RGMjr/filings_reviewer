-- Migration 202605051420: add config snapshot hash to text decision runs
--
-- Adds config_snapshot_hash TEXT to text_decision_analysis_runs so the
-- stats page can display a freshness badge when the keyword/FP-filter
-- config has changed since the run was captured. NULL for legacy rows
-- (pre-this-migration runs) — the render layer treats NULL as no drift.
--
-- Idempotency: ALTER TABLE ... ADD COLUMN IF NOT EXISTS is safe to re-run.

BEGIN;

ALTER TABLE text_decision_analysis_runs
    ADD COLUMN IF NOT EXISTS config_snapshot_hash TEXT;

COMMIT;
