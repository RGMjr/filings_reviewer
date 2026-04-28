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
updated: '2026-04-28'
pr_refs:
  - 198
note: >
  benchmark_vision.py --build-corpus now UNIONs v2_image_review_decisions +
  v2_image_metric_confirmations (same dedup rules as export_image_training_data.py).
  Deferred: chart_type schema extension on v2_image_metric_confirmations — confirmation-
  derived rows emit chart_type=NULL; stratifier treats NULL as unknown stratum.
  That deferred decision is a stakeholder call (schema change vs. accepted feature loss).
---

### Problem

After PR #192 (per-metric A/R/C/Add/Skip via `v2_image_metric_confirmations`)
and PR #151 (the original confirmations schema), reviewer image-review work no
longer lands in `v2_image_review_decisions`. The ML triage training/scoring/
benchmarking pipeline still reads only from the legacy table.

### Resolution status — PR #198 (first slice)

`scripts/export_image_training_data.py` now UNIONs both reviewer surfaces.
Per-metric confirmations aggregate to image-level using:

- `relevant`     — any confirmation in `{accept, correct, add}`
- `not_relevant` — at least one confirmation, all rejects
- excluded       — only `skip` decisions, or zero confirmations

Legacy rows take precedence when the same `img_id` appears in both surfaces.
Smoke against Neon prod: 851 legacy rows + 1 confirmation-derived row.

### Resolution status — this PR (second slice)

`scripts/benchmark_vision.py --build-corpus` is now ported off the legacy-only
corpus query. The `--build-corpus` mode UNIONs both reviewer surfaces using the
same aggregation and dedup rules as `export_image_training_data.py`:

- `_CORPUS_QUERY_LEGACY` reads `v2_image_review_decisions` (frozen historical rows).
- `_CORPUS_QUERY_CONFIRMATIONS` reads `v2_image_metric_confirmations`, aggregated
  to image-level `relevant` / `not_relevant` via `bool_or()`.
- Legacy rows take precedence on duplicate `img_id`.
- Confirmation-derived rows emit `chart_type=NULL`; the stratifier passes `None`
  through to `stratum_label()` / `is_tier1_image()` / `is_hard_ocr_image()`,
  which already handle `None` gracefully.

A unit test (`tests/unit/scripts/test_benchmark_vision_bakeoff.py`,
`TestCorpusQuery`) asserts the UNION+dedup behaviour with three fixture scenarios
(legacy-only, confirmation-only, overlap with legacy winning).

### Still open (deferred — stakeholder decision)

- **`chart_type` schema extension** — `v2_image_metric_confirmations` has no
  `chart_type` column. Confirmation-derived rows emit `chart_type=NULL`; tier-1
  and hard-OCR stratification strata will show fewer members as confirmation data
  grows. Two options: (a) add `chart_type` column to `v2_image_metric_confirmations`
  (migration required, reviewer surface change), or (b) accept permanent NULL
  stratification for confirmation-derived rows and document it as known feature
  loss. This is a product decision, not an autonomous fix.

### Resolution

Training export (`export_image_training_data.py`, PR #198) and benchmark corpus
build (`benchmark_vision.py --build-corpus`, this PR) both now read both reviewer
surfaces. The `retrain_image_triage.py` orchestrator delegates to the export
script and requires no changes. The `chart_type` deferred decision is noted above.
