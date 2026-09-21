---
autonomy: n/a
discovered: '2026-04-22'
estimated: M
id: 77
note: 'Resolved end-to-end. Root cause was Case A (bytes never uploaded — _download_missing_images
  wrote to local disk but never called storage.put_bytes). PR #102 fixed the code
  path; manual HOOD prod backfill on 2026-04-22 populated R2 and repopulated chart_data
  for the two cohort charts.'
pr_refs:
- 102
severity: high
slug: r2-chart-image-bytes-missing-for-hood-s-1-second-layer-of-72
source: legacy
status: archived
title: 'R2 Chart-Image Bytes Missing for HOOD S-1 (Second Layer of #72)'
touches: []
updated: '2026-04-22'
---

**Resolved**: 2026-04-22 — PR #102 wired `storage.put_bytes` into `OCRExtractionStage._download_missing_images` (the existing call mirrors the correct pattern at `ingestion.py:956-969`). Manual HOOD prod backfill on 2026-04-22 via `uv run python scripts/batch_v2_extraction.py --filing-id 1545 --chart-only --force-reextract`: no `FileNotFoundError`, 17 chart images processed, 2 cohort charts populated `chart_data` (`e5f65961` Annual Revenue by Annual Cohort, `44e035d8` Cumulative Net Deposits by Annual Cohort), 12 chart facts persisted. Case A confirmed — no `pipeline/` prefix divergence; unprefixed keys are the live convention. Unblocks Issue #72 (closed same day).

### Problem

After PR #87 restored `boto3` to `pyproject.toml`/`uv.lock`, `uv run python scripts/batch_v2_extraction.py --filing-id 1545 --chart-only --force-reextract` runs the full V2 pipeline on HOOD's S-1 (22 images parsed, 16 text/html_table facts produced) — but **all 17 chart-classified images** then fail in the OCR stage with:

```
FileNotFoundError: Image file not found: 1783879/000162828021019902/hood-20211008_g<N>.jpg
```

for `N` in `{2, 3, 5, 6, 7, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20}`. All 17 images end the run marked `processed=True` but with `ocr_text IS NULL` and `chart_data IS NULL`, so `cm_revenue_by_cohort` and `cm_balance_by_cohort` remain at 0/0/0 P/R/F1 on HOOD. This is the reason Issue #72's Tier 1 regression persists even after #87.

### Root cause confirmed (one concrete writer-without-upload bug; second cause still open)

**Confirmed (2026-04-22, this PR's investigation):**

`OCRExtractionStage._download_missing_images()` at `src/extraction_v2/stages/ocr_extraction.py:199-274` calls `SECClient.fetch_image()` (which writes bytes to the local disk cache rooted at `image_cache_dir()`), assigns `asset.file_path = key` (the cache-relative path), and increments `downloaded` — but **never calls `storage.put_bytes(key, bytes)` to upload those bytes to the active storage backend**. In dev (`LocalFilesystemStorage` rooted at `image_cache_dir()`), this is invisible because the disk write IS the storage write. In prod (`R2Storage`), the bytes never leave the local disk; the DB row's `file_path` then points at an R2 key that was never PUT, and downstream `process_chart_image` / `process_table_image` calls fail with `FileNotFoundError`. Compare with the correct upload pattern at `src/extraction_v2/stages/ingestion.py:956-969`, which DOES call `storage.put_bytes` after assigning the key.

This applies to **every** prod filing that went through `_download_missing_images` since PR #34 — not just HOOD. HOOD is the most visible victim (Tier 1 chart-only metrics).

**Still open:** the original entry's Case A (key-format divergence between `pipeline/<cik>/<accession>/<filename>` per docs vs. `<cik>/<accession>/<filename>` per DB rows) is **separate** from the writer-without-upload bug. My investigation surfaced that `data/image_cache/pipeline/` exists locally as a legacy layout, suggesting the `pipeline/` prefix WAS used by some other code path historically. Whether any prod R2 keys live under the `pipeline/` prefix is unverified — distinguishing requires R2 `HeadObject` against both layouts (deferred to manual prod op; see Next Steps).

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

### Status

- **Code fix landed** in this PR (`src/extraction_v2/stages/ocr_extraction.py` adds `storage.put_bytes` mirroring `ingestion.py:956-969`). New unit test `tests/unit/extraction_v2/test_image_pipeline_integration.py::TestImageDownloading::test_uploads_bytes_to_storage` locks in the invariant.
- **Prod backfill still pending.** From now on, any new prod filing that goes through `_download_missing_images` will upload bytes to R2 correctly. But the historical filings (including HOOD's 17 chart images) are still in the broken state — their bytes need to be re-uploaded via a chart-only re-extract or a targeted backfill script.

### Next Steps (deferred to a separate manual prod operation)

1. **R2 `HeadObject` against both prefix variants** — `1783879/000162828021019902/hood-20211008_g6.jpg` AND `pipeline/1783879/000162828021019902/hood-20211008_g6.jpg`. Distinguishes the writer-without-upload bug (this PR's fix) from any residual Case A key-format divergence. Requires real R2 credentials.
2. **HOOD chart backfill** — `python3 scripts/batch_v2_extraction.py --filing-ids-file <one-line file with HOOD's filing_id> --chart-only` against prod (Neon `$DATABASE_URL` + R2 creds). With this PR's fix, `_download_missing_images` will re-fetch from EDGAR and upload to R2 in the same run. Pre-flight: confirm `chart_decision_count` for HOOD chart facts is zero (otherwise add `--force-reextract` only after explicit confirmation, since it purges reviewer decisions).
3. **Repo-wide audit** — `scripts/check_image_referential_integrity.py` against prod (Neon) DB, looking for class-C violations beyond HOOD. Every filing routed through `_download_missing_images` since PR #34 likely has the same orphan-key state. Decide between bulk chart-only re-extract vs. a targeted backfill script that walks `v2_image_assets` rows + uploads from local cache where present.
4. **Refresh the v2 gold-standard baseline** once HOOD `cm_revenue_by_cohort` + `cm_balance_by_cohort` recover chart facts. **Only then** do the regression deltas return to the pre-scrub 0.3143 recall target.
5. **Investigate Case A (`pipeline/` prefix)** — `data/image_cache/pipeline/` exists locally as a legacy layout, but no live writer code constructs `pipeline/`-prefixed keys. Either dead-code cleanup or a third-party prod path; needs a `git log -S "pipeline/"` archaeology pass. Reconcile `infrastructure.md` and `src/infra/image_storage.py:8` docstrings with whichever convention is canonical (probably remove the `pipeline/` prefix from docs since live code never uses it).
6. **Hygiene follow-up**: add a CI smoke that runs the chart stage on at least one fixture filing end-to-end under `uv run` against a mock R2 (`moto[s3]` is already in `requirements-dev.txt`). Would have caught both the boto3-missing case AND this writer-without-upload regression at PR-time.

Cross-references: #34 (R2 migration, Phases 1+3), #72 (overall regression tracking), #42 (resolved — `_download_missing_images` double-write collapse). PR #87 fix commit `8713f51`.
