---
id: 392
source: gh
slug: stale-running-training-runs
title: Stale 'running' rows in model_training_runs after SIGKILL/OOM
status: archived
severity: low
autonomy: skip
estimated: —
touches: []
discovered: 2026-05-01
updated: 2026-05-01
gh_issue: 392
note: resolved — endpoint now sweeps stale running rows (>1h) before the concurrency check, so leaked rows from SIGKILL/OOM no longer permanently block future retrains
---

### Problem

The Phase-3 retrain endpoint relies on a try/except around the script `main()` to flip the `model_training_runs` row to `status='failed'` if a Python exception fires. SIGKILL and OOM bypass that — Python never re-enters after the signal — so the row stays `status='running'` forever. The concurrency guard then blocks every future retrain.

### Resolution

`trigger_image_classifier_retrain` runs a stale-row sweep before the concurrency check on every attempt: `UPDATE model_training_runs SET status='failed', error='auto-cleanup: stale running row (>1h, gh-392)' WHERE model_type='image_relevance' AND status='running' AND started_at < NOW() - INTERVAL '1 hour'`. A leaked row from a SIGKILL'd subprocess no longer permanently blocks future retrains; at worst the operator waits an hour and re-clicks. The same SQL remains usable as the manual escape hatch (scope to a specific id with `WHERE id = '<uuid>'`) when the operator does not want to wait. See `.claude/rules/web.md` for the documented contract; tests in `tests/unit/web/test_models_retrain.py::TestStaleRowSweep`.

### Not addressed (deliberately)

- Heartbeat-based detection (script touches `started_at` every 30s; endpoint considers stale if last touch > 5 min). Significantly more invasive — needs a script-side change. Re-evaluate if the 1-hour window proves too coarse in practice.
- Cron-based nightly cleanup. Now redundant given the on-demand sweep — every button click is the cleanup trigger.
- Same fix on `text_decision_analysis_runs` (parallel surface with the same fragility per `.claude/rules/web.md`). Worth doing, but separate concern; file as a follow-up if the text-analysis button starts getting stuck.
