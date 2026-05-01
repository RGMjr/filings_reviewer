---
id: 406
source: gh
slug: retrain-sklearn-version-check
title: retrain_image_triage.py should enforce sklearn version match against requirements.lock
status: open
severity: low
autonomy: skip
estimated: —
touches: []
discovered: 2026-05-01
updated: 2026-05-01
gh_issue: 406
note: silent unpickle failure on Render when local-venv sklearn major drifts from requirements.lock pin (1.8.0)
---

### Problem

`scripts/retrain_image_triage.py` writes `data/image_model/relevance_model.joblib` using whatever sklearn version is in the operator's local venv. The Render runtime is pinned to `scikit-learn==1.8.0` via `requirements.lock`. A version-mismatched joblib unpickles silently into None on Render — `predict_relevance()` returns None, the "Model score" sort produces no observable reordering, and no error is raised.

Discovered while implementing the model-score sort UI (PR for image-model-sort, 2026-05-01). Manually verified local venv ran 1.8.0 before committing.

### Next Steps

- At the top of `scripts/retrain_image_triage.py`, exit with a clear error if `sklearn.__version__` doesn't match the version in `requirements.lock`. Print installed, expected, and the suggested `pip install -r requirements.lock` fix.
- Same check belongs in the worker-spawned retrain when gh-400 (queue + worker pattern) lands.
- Optionally gate behind `--allow-version-mismatch` for experimental local runs that don't intend to ship the artifact to prod.
