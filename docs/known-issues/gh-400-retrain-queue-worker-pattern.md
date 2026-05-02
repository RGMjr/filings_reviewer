---
id: 400
source: gh
slug: retrain-queue-worker-pattern
title: Move image-classifier retrain off web subprocess onto background worker queue
status: resolved
severity: medium
autonomy: skip
estimated: —
touches: []
discovered: 2026-05-01
updated: 2026-05-01
gh_issue: 400
pr_refs:
  - 424
note: UI retrains spawned from gunicorn web workers die silently on Render container recycle; queue + worker mirrors filings-onboarding-runner pattern
---

### Problem

`POST /api/v2/models/image-classifier/retrain` spawns `scripts/retrain_image_triage.py` as a detached subprocess from the gunicorn web worker (`_spawn_retrain_runner` in `src/web/routes/api_unified.py`). Render web-service containers recycle on deploys, idle scale-down, and plan-level restarts — silently killing any spawned subprocess. The script never re-enters Python after SIGKILL, so the `model_training_runs` row stays `status='running'` forever and the concurrency guard then blocks every future retrain.

Repro: 2026-05-01 a UI-triggered retrain by RGM stuck in `running` for 67 minutes with no error. Underlying training data is tiny (~1.6k rows, peak memory <100MB) so this is not memory pressure — it's process-lifetime fragility.

Related: gh-392 (stuck-row sweep — symptom mitigation, can ship before this), gh-391 (R2 artifact persistence — required before UI retrains are actually useful since artifacts are wiped on next deploy today).

### Next Steps

- Mirror the `filings-onboarding-runner` pattern (`render.yaml`, `INGEST_SPAWN_SUBPROCESS=false`):
  - Web POST inserts `model_training_runs` row with `status='queued'` and skips `_spawn_retrain_runner` when env gate `RETRAIN_SPAWN_SUBPROCESS=false`.
  - Background worker polls `model_training_runs WHERE status='queued' AND model_type='image_relevance'`, claims via `UPDATE … SET status='running' RETURNING id`, then runs `retrain_image_triage.py --run-id <uuid>` in its own process.
- Decide between dedicated `filings-retrain-runner` worker vs. folding into existing `filings-onboarding-runner`. Retrains are infrequent (target monthly cadence), so folding likely wins on cost.
- Existing `GET /api/v2/models/training/<uuid:run_id>/status` polling endpoint already works — no client changes needed.
- Test coverage: unit test for the queue-claim race (two workers can't double-claim the same row).
- Concurrency guard in the POST endpoint should also count `status='queued'` rows, not just `status='running'`, to prevent two queued requests piling up.
