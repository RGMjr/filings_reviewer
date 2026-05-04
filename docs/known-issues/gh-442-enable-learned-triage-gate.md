---
id: 442
source: gh
slug: enable-learned-triage-gate
title: Enable learned-triage gate in prod (USE_LEARNED_TRIAGE=true) and tune LEARNED_TRIAGE_MIN
status: resolved
severity: medium
autonomy: review
estimated: S
touches:
  - render.yaml
discovered: '2026-05-04'
updated: '2026-05-04'
gh_issue: 442
pr_refs:
  - 462
note: relevance model serves UI sort but does not gate extraction; flip the gate, threshold-tune from new PR curve; blocked on gh-419 (silent load-error observability)
---

### Problem

The retrained image-relevance model (run `cba5e60f`, 1713 rows / 76 positive, AUC 0.843) is serving the UI model-score sort (#407) but is **not gating extraction**. `USE_LEARNED_TRIAGE` is unset across all Render services in `render.yaml`, defaulting to `false` per `src/extraction_v2/stages/image_triage.py:46`. So `predict_relevance()` is never called during extraction; `v2_image_assets.predicted_relevance` stays NULL on every new image.

Flipping the gate would:
- Write per-image scores to `v2_image_assets.predicted_relevance` going forward
- Drop images scoring below `LEARNED_TRIAGE_MIN` from the OCR/Vision pipeline (the actual gating effect)

The current default `LEARNED_TRIAGE_MIN=0.4` was calibrated against the prior 808-sample model. The new model's PR curve has the 80%-recall threshold around 0.32. Keeping 0.4 trades coverage for precision; dropping to ~0.32 recovers ~15% more positives.

### Prerequisite

**Block on gh-419** (silent load-error in `_load_joblib_into_cache`). Without that fix, a corrupt R2 joblib or sklearn drift would silently fall back to the heuristic with no metric or alert. gh-419 is a 5-line addition; it is the prereq observability for operating this gate safely.

### Next Steps

1. Confirm gh-419 is merged and live before starting.
2. Read the new model's PR curve from `models/image_relevance/<run_id>/model_report.txt` in R2 (current run is `cba5e60f`). Pick a deliberate `LEARNED_TRIAGE_MIN` value based on the recall-vs-precision trade-off for the corpus.
3. Add `USE_LEARNED_TRIAGE=true` (and the chosen `LEARNED_TRIAGE_MIN` if non-default) to `render.yaml` on `filings-extraction`.
4. Plan a short A/B comparison: before/after per-filing accept rates from `v2_image_metric_confirmations`. Baseline N most-recent batches before flip; first N batches after flip; confirm signal-to-noise improvement.

### Verification

- After deploy: new image rows have non-NULL `v2_image_assets.predicted_relevance`.
- Per-batch image-candidate count drops by approximately the threshold's expected coverage loss (e.g. 10-20% if threshold 0.4 captures 80-90% recall).
- A/B accept rate: post-flip per-filing accept rate at least matches pre-flip; ideally better.
- gh-419 metric/alert: zero "learned triage model failed to load" events (confirms the gate is actually active, not silently no-op).

### Resolution

Resolved by PR #462 (commit `82714038`, 2026-05-04). gh-419 merged at `b165ae31` (PR #451) cleared the prereq. `render.yaml` filings-extraction service now has `USE_LEARNED_TRIAGE=true` and `LEARNED_TRIAGE_MIN=0.32`. Threshold chosen from the `cba5e60f-9a99-4231-82e0-fe232c9a9792` model report: AUC 0.843, AP 0.409, 80%-recall threshold 0.341 — picked 0.32 to capture ~82% recall with a small noise margin.
