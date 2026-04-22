---
autonomy: skip
discovered: '2026-04-22'
estimated: M
id: 77
note: 'Second layer of #72 — R2 chart-image bytes missing/mis-keyed for HOOD S-1;
  needs R2 head-object check + migration or re-ingest'
severity: high
slug: r2-chart-image-bytes-missing-for-hood-s-1-second-layer-of-72
source: legacy
status: open
title: 'R2 Chart-Image Bytes Missing for HOOD S-1 (Second Layer of #72)'
touches: []
updated: '2026-04-22'
---

### Problem

After PR #87 restored `boto3` to `pyproject.toml`/`uv.lock`, `uv run python scripts/batch_v2_extraction.py --filing-id 1545 --chart-only --force-reextract` runs the full V2 pipeline on HOOD's S-1 (22 images parsed, 16 text/html_table facts produced) — but **all 17 chart-classified images** then fail in the OCR stage with:

```
FileNotFoundError: Image file not found: 1783879/000162828021019902/hood-20211008_g<N>.jpg
```

for `N` in `{2, 3, 5, 6, 7, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20}`. All 17 images end the run marked `processed=True` but with `ocr_text IS NULL` and `chart_data IS NULL`, so `cm_revenue_by_cohort` and `cm_balance_by_cohort` remain at 0/0/0 P/R/F1 on HOOD. This is the reason Issue #72's Tier 1 regression persists even after #87.

### Two candidate causes (not yet distinguished)

1. **Bytes never uploaded to R2 for HOOD S-1.** HOOD S-1 (`filing_id=1545`) was ingested before PR #34's R2 migration landed. Ingestion of pre-R2 filings may not have re-uploaded image bytes to R2 under the new `v2_image_assets.file_path` keys.
2. **Key-format divergence.** `.claude/rules/infrastructure.md` documents the canonical storage key as `pipeline/<cik>/<accession>/<filename>`. The keys actually stored in `v2_image_assets.file_path` for HOOD's S-1 omit the `pipeline/` prefix — the failed lookups are at `1783879/000162828021019902/hood-20211008_g<N>.jpg`. If bytes are in R2 at the prefixed keys but the DB/lookup path is missing the prefix (or vice versa), a backfill write won't help until the mismatch is reconciled.

### Evidence from Neon (2026-04-22)

| Fact | Observation |
|---|---|
| Cohort image `img_id=e5f65961-f33f-44db-9fd0-5f3b61dae987` | `classification='chart', relevance_score=0.66, processed=True` (post-#87 re-run); `ocr_text IS NULL`, `chart_data IS NULL`, `file_path='1783879/000162828021019902/hood-20211008_g6.jpg'` |
| Cumulative-Net-Deposits image `img_id=44e035d8-2302-40bb-ab40-01c8fec41665` | Same state; `file_path='1783879/000162828021019902/hood-20211008_g5.jpg'`. Also has a human `relevant` decision in `v2_image_review_decisions`. |
| 15 other chart-classified images on `doc_id=1545` | All `processed=True`, 0 OCR, 0 chart_data, `file_path` without `pipeline/` prefix |
| Pre-#87 chart fact `$130 cm_revenue_by_cohort` | Orphan — references `img_id=c8da02f5-227c-4830-94d9-c45944d45e7f` which does not exist in `v2_image_assets`. Stranded from a pre-`d94acab` run. Preserved by chart-only mode's reviewer-guard path (did not get deleted in the #87 verification run because 0 new chart facts were produced). |

### Why this matters

- **Blocks Issue #72 closure and Tier-1 baseline refresh.** PR #87 is a *partial* fix — it restores the ability to run the pipeline, but HOOD chart recall cannot recover without image bytes reaching the OCR stage.
- **Blocks any merge commit against current main.** The pre-commit Tier-1 guard keeps firing on HOOD until `cm_revenue_by_cohort` recovers.
- **Risk of quietly affecting other pre-R2 filings** beyond HOOD — worth checking whether any non-S-1 filings with chart-sourced gold standard values show the same `FileNotFoundError` pattern when their chart stage runs.

### Next Steps

1. **Reproduce and classify.** Try a direct R2 `HeadObject` via the AWS CLI / boto3 on both `1783879/000162828021019902/hood-20211008_g6.jpg` and `pipeline/1783879/000162828021019902/hood-20211008_g6.jpg`. Whichever (if either) exists tells us whether we have a key-format issue (rename / rewrite `file_path` values) vs. a missing-upload issue (backfill).
2. **Case A — bytes present under `pipeline/` prefix**: write a one-shot migration that updates `v2_image_assets.file_path` for the affected rows (or fix the R2 lookup path to prepend `pipeline/`, whichever is canonical per the architecture doc). Reconcile `infrastructure.md` with the actual code path.
3. **Case B — bytes not present anywhere**: re-run ingestion for HOOD S-1 from source HTML so the modern ingestion path re-fetches + re-uploads images. If the R2 write is wired into `SECClient.fetch_image` / `OCRExtractionStage._download_missing_images`, this will populate the bucket. Requires `--force-reextract` on HOOD S-1 but chart-only mode still preserves the 9 text-review + 3 image-review decisions.
4. **Scope check.** Query `v2_image_assets` for other filings with `classification='chart'`, `processed=False OR chart_data IS NULL`, and a `file_path` not starting with `pipeline/`. If there's a broader pre-migration cohort, the remediation should cover them in one pass rather than one-filing-at-a-time.
5. **Refresh the v2 gold-standard baseline** once HOOD `cm_revenue_by_cohort` + `cm_balance_by_cohort` recover chart facts. **Only then** do the regression deltas return to the pre-scrub 0.3143 recall target.
6. **Hygiene follow-up**: consider adding a CI smoke that runs the chart stage on at least one fixture filing end-to-end under `uv run` against a mock R2 (`moto[s3]` is already in `requirements-dev.txt`). Would have caught both the boto3-missing case AND a hypothetical key-format regression.

Cross-references: #34 (R2 migration, Phases 1+3), #72 (overall regression tracking), #42 (resolved — `_download_missing_images` double-write collapse). PR #87 fix commit `8713f51`.
