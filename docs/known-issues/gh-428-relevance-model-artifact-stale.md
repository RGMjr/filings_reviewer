---
id: 428
source: gh
slug: relevance-model-artifact-stale
title: Image relevance model artifact stale — disk joblib trained on 808 samples while CSV has 1,499
status: archived
severity: medium
autonomy: review
estimated: S
touches:
  - data/image_model/relevance_model.joblib
  - models/image_relevance/latest_run_id.txt
discovered: '2026-05-02'
updated: '2026-05-04'
gh_issue: 428
pr_refs:
  - 438
note: PR #438 retrained on 1,614 samples; data/image_model/model_report.txt confirms num_training_rows=1614. Dev-disk artifact is current. Prod R2 pointer freshness is an operator action (trigger UI retrain after gh-437 fix shipped via PR #439) — track separately if it doesn't get triggered.
---

### Problem

The deployed image-relevance model is out of date relative to the labels reviewers have produced. Side finding from the gh-405 audit (`docs/analysis/gh-405-chart-classifier-overflag-audit.md`, §"Side findings"):

> Disk relevance model is stale. `data/image_model/relevance_model.joblib` was trained on 808 samples; the CSV on disk has 1,499. A retrain has not been run.

Disk evidence (2026-05-02):

| Artifact | Samples | Relevant | AUC | `is_chart_classification` |
|---|---|---|---|---|
| `data/image_model/model_report.txt` (2026-04-25) | 808 | 85 (10.5%) | 0.824 | +0.142 |
| `data/image_model/model_report_gh405_repro.txt` (2026-05-02) | 1,499 | 80 (5.3%) | 0.829 | −2.178 |

The headline coefficient flipped sign between the two reports, so the gap is material — the deployed model isn't just marginally stale, it's scoring with materially different feature behavior than current labels would produce.

When `R2_BUCKET` is set (prod / staging), `src/shared/image_features._load_model` reads `models/image_relevance/latest_run_id.txt` from R2 and materializes the joblib that pointer references. We have not yet verified which run that pointer points at; if it's the 808-sample artifact, prod scoring under `USE_LEARNED_TRIAGE=true` is using a model that hasn't seen the last ~700 reviewer decisions. If it's a newer artifact, this issue narrows to "dev-only on-disk file is stale" and drops in priority.

In dev (`R2_BUCKET` unset), the loader reads `data/image_model/relevance_model.joblib` directly — that file is the 808-sample stale artifact.

### Next Steps

1. Verify R2 state: read `models/image_relevance/latest_run_id.txt` and look up the matching `model_training_runs` row to confirm `num_training_rows`. If already current, close as not-applicable to prod.
2. If stale in prod: trigger `POST /api/v2/models/image-classifier/retrain`. The web endpoint wraps `scripts/retrain_image_triage.py`, runs on the `filings-onboarding-runner` worker (gh-400), and is single-writer-safe via the concurrency gate in `src/web/routes/api_unified.py::trigger_image_classifier_retrain`.
3. After retrain: optionally retune `LEARNED_TRIAGE_MIN` (currently `0.4`, `src/extraction_v2/stages/image_triage.py:46`) against the new precision-recall curve. The fresh report shows precision @ 80% recall = 0.106 at threshold 0.319 — the existing 0.4 gate is on the higher-precision side of that curve; the trade-off is worth a deliberate look once a retrain lands.
4. Refresh the dev-disk artifact: pull the new joblib into `data/image_model/` so contributors running locally without `R2_BUCKET` see consistent scoring.

### Verification

- New `model_training_runs` row with `status='succeeded'`, `num_training_rows ≈ 1499`, `num_positive_rows ≈ 80`, `model_path` of the form `models/image_relevance/<new_run_id>/relevance_model.joblib`.
- `models/image_relevance/latest_run_id.txt` advanced to the new run id.
- Worker cold-start picks up the new joblib (in-memory cache is keyed on run-id, so the first scoring call after the pointer flip pulls the new model).
- Spot-check `predicted_relevance` distribution on a sample of `v2_image_assets` rows pre/post.
