---
id: 391
source: gh
slug: image-model-r2-persistence
title: Persist data/image_model/ artifacts to R2 (Render disk is ephemeral)
status: open
severity: medium
autonomy: skip
estimated: —
touches: []
discovered: 2026-05-01
updated: 2026-05-01
gh_issue: 391
note: UI-triggered retrains land on ephemeral disk; will silently disappear on next deploy once USE_LEARNED_TRIAGE flips on
---

### Problem

The retrain endpoint added in Phase 3 of the Metric Analytics rollout writes to `data/image_model/` (model joblib + training CSV + report). On Render the disk is ephemeral; the next deploy wipes the artifact. Today this is harmless because `USE_LEARNED_TRIAGE=false` in prod (the model is not loaded at runtime), but the moment that flag flips on, retrains performed via the UI will silently disappear on the next deploy.

### Next Steps

- Add an R2 backend mirroring `src/infra/image_storage.py` for the `model_path` / `report_path` artifacts.
- Either keep `data/image_model/` as a write-through cache or read directly from R2 in `src/shared/image_features.predict_relevance()`.
- Block the UI retrain button on Render until R2 persistence is in (or document staging-only).
- Update `model_training_runs.model_path` / `report_path` to store the R2 key, not a local path.
