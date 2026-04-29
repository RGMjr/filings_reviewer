---
autonomy: review
discovered: '2026-04-24'
estimated: M
gh_issue: 196
id: 196
severity: medium
slug: ml-triage-feed-from-legacy-image-decisions
source: gh
status: resolved
title: ML image-triage training pipeline reads legacy v2_image_review_decisions
touches:
  - scripts/export_image_training_data.py
  - scripts/retrain_image_triage.py
  - scripts/benchmark_vision.py
  - src/llm/vision_client.py
  - src/gold_standard/image_eval.py
updated: '2026-04-29'
pr_refs:
  - 198
  - 287
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

### Resolution (chart_type extension — this PR)

The previously-deferred `chart_type` schema extension is resolved via Option A1-narrow
(see `docs/analysis/chart-type-decision.md`):

- Migration `202604291500_add_reviewer_chart_type_to_v2_image_assets.sql` adds
  `reviewer_chart_type TEXT NULL` to `v2_image_assets` with the legacy 7-value
  CHECK constraint (`cohort_table, cohort_parfait, line_chart, bar_chart,
  stacked_bar, other_chart, mixed`) and a one-shot backfill from
  `v2_image_review_decisions`.
- `CONFIRMATIONS_SEC_QUERY` in `scripts/export_image_training_data.py` now reads
  `v.reviewer_chart_type` instead of emitting `NULL::text`.
- `_CORPUS_QUERY_CONFIRMATIONS` in `scripts/benchmark_vision.py` has the same change.
- `LEGACY_SEC_QUERY` / `_CORPUS_QUERY_LEGACY` are unchanged (they already read
  `d.chart_type` from `v2_image_review_decisions` directly).
- Tests in `TestCorpusQuery` cover both populated and NULL `reviewer_chart_type` paths.

The UI chart-type capture endpoint (optional reviewer dropdown) is deferred — reviewers
can set `reviewer_chart_type` via future work; the column is NULL-tolerant in the
meantime, consistent with the stratifier's existing None-handling.
