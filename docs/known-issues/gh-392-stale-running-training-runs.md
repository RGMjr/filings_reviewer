---
id: 392
source: gh
slug: stale-running-training-runs
title: Stale 'running' rows in model_training_runs after SIGKILL/OOM
status: open
severity: low
autonomy: skip
estimated: —
touches: []
discovered: 2026-05-01
updated: 2026-05-01
gh_issue: 392
note: SIGKILL/OOM leaves the row 'running' forever; concurrency guard then blocks every future retrain until manual psql cleanup
---

### Problem

The Phase-3 retrain endpoint relies on a try/except around the script `main()` to flip the `model_training_runs` row to `status='failed'` if a Python exception fires. SIGKILL and OOM bypass that — Python never re-enters after the signal — so the row stays `status='running'` forever. The concurrency guard then blocks every future retrain.

### Next Steps

- Manual escape hatch (documented in `.claude/rules/web.md`): `psql -c "UPDATE model_training_runs SET status='failed', error='manual cleanup' WHERE status='running' AND started_at < NOW() - INTERVAL '1 hour'"`.
- Auto-detection options to evaluate: heartbeat row (script touches `started_at` every 30s; endpoint considers stale if last touch > 5 min); or a stale-window check on the endpoint that auto-marks `running` rows older than 1 hour as `failed` before INSERTing a new one.
- Alternative: a small cron that runs the cleanup query nightly.
