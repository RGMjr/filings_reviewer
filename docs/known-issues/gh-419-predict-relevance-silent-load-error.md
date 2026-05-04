---
id: 419
source: gh
slug: predict-relevance-silent-load-error
title: predict_relevance() silently swallows joblib load errors — runtime failure indistinguishable from model absent
status: resolved
severity: low
autonomy: skip
estimated: —
touches: []
discovered: 2026-05-01
updated: 2026-05-04
gh_issue: 419
pr_refs:
  - 425
note: src/shared/image_features._materialize_from_storage now distinguishes FileNotFoundError (warning) from other load failures (logged at WARNING/ERROR), shipped as part of PR #425's R2 model-storage rewrite. Silent degradation path is closed.
---

### Problem

`src/shared/image_features.py::_load_model()` catches all exceptions on `joblib.load()` and returns `None`. `predict_relevance()` treats `None` as "no model trained" and falls back to heuristic scoring. This makes a corrupt artifact, failed R2 download, or unexpected joblib format produce no observable error — the image sort silently degrades to heuristic without any log signal.

Surfaced while adding the sklearn version guard in `scripts/retrain_image_triage.py` (gh-406). The new guard prevents version mismatch at train time, but other load failure modes at runtime remain silent.

### Next Steps

- Add a specific `except` clause distinguishing "file not found" (model absent, expected) from other load failures (unexpected — should warn or raise).
- Log at `WARNING` or `ERROR` level when load fails for a reason other than missing file so operators can detect silent degradation.
- Consider a startup or health-check validation that confirms the artifact loads cleanly when `USE_LEARNED_TRIAGE=true`.
