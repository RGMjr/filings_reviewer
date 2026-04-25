---
autonomy: review
discovered: '2026-04-24'
estimated: M
gh_issue: 196
id: 196
severity: medium
slug: ml-triage-feed-from-legacy-image-decisions
source: gh
status: partially-resolved
title: ML image-triage training pipeline reads legacy v2_image_review_decisions
touches:
  - scripts/export_image_training_data.py
  - scripts/retrain_image_triage.py
  - scripts/benchmark_vision.py
  - src/llm/vision_client.py
  - src/gold_standard/image_eval.py
updated: '2026-04-24'
pr_refs:
  - 197
---

### Problem

After PR #192 (per-metric A/R/C/Add/Skip via `v2_image_metric_confirmations`)
and PR #151 (the original confirmations schema), reviewer image-review work no
longer lands in `v2_image_review_decisions`. The ML triage training/scoring/
benchmarking pipeline still reads only from the legacy table.

### Resolution status (this PR)

`scripts/export_image_training_data.py` now UNIONs both reviewer surfaces.
Per-metric confirmations aggregate to image-level using:

- `relevant`     — any confirmation in `{accept, correct, add}`
- `not_relevant` — at least one confirmation, all rejects
- excluded       — only `skip` decisions, or zero confirmations

Legacy rows take precedence when the same `img_id` appears in both surfaces.
Smoke against Neon prod: 851 legacy rows + 1 confirmation-derived row.

### Still open

- **`scripts/benchmark_vision.py`** — its corpus query reads `chart_type`
  heavily for tier-1 / hard-OCR stratification. `chart_type` is not captured
  in `v2_image_metric_confirmations`, so a clean port requires a product
  decision: (a) extend the confirmations schema to capture `chart_type`, or
  (b) accept the feature loss and rework stratification. Deferred until the
  bake-off harness next runs against new reviewer data.
- **Triage model `chart_type` feature** — confirmation-derived rows emit
  `chart_type=NULL`. The model treats it as missing; retraining quality
  will degrade if confirmations become the dominant surface and `chart_type`
  is not recovered.

### Next steps

- After ML team retrains with the unified feed, decide whether to capture
  `chart_type` in `v2_image_metric_confirmations` (schema change) or
  formalize stratification without it.
- Port `benchmark_vision.py` once the `chart_type` decision lands.
