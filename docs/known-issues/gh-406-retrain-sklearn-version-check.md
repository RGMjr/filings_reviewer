---
id: 406
source: gh
slug: retrain-sklearn-version-check
title: retrain_image_triage.py should enforce sklearn version match against requirements.lock
status: resolved
severity: low
autonomy: n/a
estimated: —
touches: []
discovered: 2026-05-01
updated: 2026-05-01
gh_issue: 406
pr_refs:
  - 420
note: silent unpickle failure on Render when local-venv sklearn major drifts from requirements.lock pin (1.8.0)
---

### Problem

`scripts/retrain_image_triage.py` writes `data/image_model/relevance_model.joblib` using whatever sklearn version is in the operator's local venv. The Render runtime is pinned to `scikit-learn==1.8.0` via `requirements.lock`. A version-mismatched joblib unpickles silently into None on Render — `predict_relevance()` returns None, the "Model score" sort produces no observable reordering, and no error is raised.

Discovered while implementing the model-score sort UI (PR for image-model-sort, 2026-05-01). Manually verified local venv ran 1.8.0 before committing.

### Next Steps

- At the top of `scripts/retrain_image_triage.py`, exit with a clear error if `sklearn.__version__` doesn't match the version in `requirements.lock`. Print installed, expected, and the suggested `pip install -r requirements.lock` fix.
- Same check belongs in the worker-spawned retrain when gh-400 (queue + worker pattern) lands.
- Optionally gate behind `--allow-version-mismatch` for experimental local runs that don't intend to ship the artifact to prod.

### Resolution

Added two helpers to `scripts/retrain_image_triage.py`:

- `_read_pinned_sklearn_version()` — reads the pin from `requirements.lock` at runtime (single source of truth; no hardcoded version in the script).
- `check_sklearn_version(*, allow_mismatch: bool = False)` — imports sklearn, compares `sklearn.__version__` against the pin, and calls `sys.exit(1)` on mismatch with a clear operator message (installed, expected, and fix command). Logs a warning instead when `allow_mismatch=True`.

Added `--allow-version-mismatch` argparse flag to `main()` for local experimentation. The guard is called in `main()` after `configure_logging()` and before the database URL validation, so it fires early before any expensive work.

The `sys.exit(1)` path is captured by the existing `except SystemExit` block in run-id mode (line 232), so the `model_training_runs` row is correctly marked `failed`. The guard covers all production invocation paths (CLI and web endpoint via `_spawn_retrain_runner`) — no change to `train_image_relevance_model.py` or `api_unified.py` was needed.

When gh-400 (retrain queue + worker pattern) lands, the orchestrator script still runs as a subprocess from the worker, so the guard placement remains valid.

Tests added at `tests/unit/scripts/test_retrain_image_triage.py` (4 cases: semver sanity, match passes, mismatch exits, allow_mismatch warns-not-exits).
