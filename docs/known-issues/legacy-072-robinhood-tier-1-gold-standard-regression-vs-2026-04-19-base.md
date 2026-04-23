---
autonomy: n/a
discovered: '2026-04-21'
estimated: S
id: 72
note: 'Resolved end-to-end via PR #87 (boto3) + PR #102 (R2 upload) + manual HOOD
  Neon backfill on 2026-04-22. Validator: HOOD recall 0.486 (baseline 0.3143), Tier
  1 F1 0.686. Residual `cm_revenue_by_cohort` 10% recall tracked as #85.'
pr_refs:
- 87
- 102
severity: high
slug: robinhood-tier-1-gold-standard-regression-vs-2026-04-19-base
source: legacy
status: resolved
title: Robinhood Tier 1 Gold-Standard Regression vs. 2026-04-19 Baseline
touches: []
updated: '2026-04-22'
---

**Resolved**: 2026-04-22 — chart pipeline produces facts end-to-end on HOOD's S-1. Validator against Neon (post-backfill): HOOD **recall=0.486, F1=0.586** (vs baseline 0.3143 / 0.4231 — +15pp recall above baseline). Tier-1: **P=92.3%, R=54.5%, F1=68.6%**. `cm_balance_by_cohort` at 100/100/100. `cm_revenue_by_cohort` at 50/10/16.7 — residual gap tracked as Issue #85 (dedup stage collapses chart-sourced cohort facts at the fact-construction boundary); orthogonal to the original infra regression. Path to close: PR #87 restored `boto3` in `pyproject.toml`/`uv.lock` (unblocked ingestion); PR #102 wired `storage.put_bytes` into `_download_missing_images` (unblocked R2 chart-image reads); chart-only re-extract + R2 upload executed against prod Neon on 2026-04-22 — 12 new chart facts persisted, 17 chart images processed cleanly. Chart-only mode preserved 16 text-review + 20 image-review decisions on HOOD.

### Problem

Baseline at pre-scrub `cdc831f` (2026-04-19) recorded Robinhood `recall=0.3143, f1=0.4231`. Current main state: `recall=0.171, f1=0.255` (-14pp on HOOD, -0.009 overall). Per-metric diagnostics:

| Metric | Tier | Current P/R/F1 | Notes |
|---|---|---|---|
| `cm_balance_by_cohort` | T1 | 0% / 0% / 0% | Same chart-pipeline failure mode as `cm_revenue_by_cohort` (both chart-only metrics on the same filing). Issue #64 — chart classifier boundary sensitivity — is a separate, narrower concern already resolved |
| `cm_customer_acquisition_cost` | T1 | 100% / 50% / 66.7% | 1 FN — dedup collision (`20.0` collapsed into sibling with different value) |
| `cm_revenue_by_cohort` | T1 | 0% / 0% / 0% | 10 FNs — chart pipeline never ran on source image (see below) |

### Diagnosis (2026-04-22, against Neon `filing_id=1545`)

HOOD S-1 has 21 images, 17 classified as charts, **0 with `ocr_text`, 0 with `chart_data`** before this PR. The "Annual Revenue by Annual Cohort ($mm)" image — the single source of all 10 gold per-cohort values ($17/$62/$44/$56/$87/$45/$130/$186/$175/$326) — is `img_id=e5f65961-f33f-44db-9fd0-5f3b61dae987`, classified `chart`, `processed=False`, no linked facts. The lone `$130` chart fact in the DB references `img_id=c8da02f5-227c-4830-94d9-c45944d45e7f` which no longer exists in `v2_image_assets` — an orphan from a pre-`d94acab` img_id stabilisation run. The `$102,034.8` text fact flagged as an FP is an unrelated period-`2026-Q1` mis-bind.

### Root cause: PR #34 dropped `boto3` from the uv-managed manifest

`src/infra/image_storage.py` routes chart/image storage to R2 (prod) or local filesystem (dev) based on whether `R2_BUCKET` is set. The R2 backend calls `import boto3` lazily inside `R2Storage.__init__`. PR #34 (`9aeb454 feat(image-cache): migrate to Cloudflare R2 via ImageStorage abstraction`) added `boto3>=1.34.0` to `requirements.txt` but **not to `pyproject.toml`/`uv.lock`**. Any extraction launched via `uv run …` in an R2-configured environment therefore crashes at the ingestion stage with `ModuleNotFoundError: No module named 'boto3'` before any chart processing runs.

### What the earlier framing got wrong

- **Not a scale bug.** There is no `$33,421.5` anywhere in HOOD's facts. Extraction wasn't binding a quarterly total — it wasn't binding the cohort chart at all.
- **Not caused by #52.** `24bfd6b` (re-hashed post-scrub to `5c44a4b`) is a 3-file persistence refactor with commit body "No behavioral change; 3630 tests pass." Zero value-binding or chart-stage code is touched.
- **"Only extraction-touching commit in the window" was wrong.** The real extraction-touching commits in the window include `d94acab` (#21, img_id stabilisation), `9aeb454`/`cf0c756` (#34, R2 migration), `1d7c204` + `8cd3b4d` (#50, chart_only persistence).

### Why this landed on main

CI installs from `requirements.txt`, which has `boto3` pinned — so CI never reproduced the missing-dep crash. The `uv`-managed path that developers and the nightly sweeper use diverges silently. The dual-manifest layout (pip + pyproject) can drift any time only one is updated.

### Fix in this PR

- Add `boto3>=1.34.0` to `pyproject.toml` dependencies; regenerate `uv.lock`.
- Proved locally against Neon: `uv run python scripts/batch_v2_extraction.py --filing-id 1545 --chart-only --force-reextract` now runs the full pipeline (2215 segments, 137 tables, 22 images parsed; 16 text/html_table facts produced). Previously died at stage 1.
- **No data loss.** Chart-only mode safely skipped the fact-DELETE when 0 new chart facts were produced; 9 text-review + 3 image-review decisions on HOOD S-1 remain intact.

### Second layer still open (new follow-up needed)

After the boto3 fix, all 17 HOOD chart images now run through OCR but fail with `FileNotFoundError: Image file not found: 1783879/000162828021019902/hood-20211008_g*.jpg`. The R2 bucket does not have bytes at those keys. Two possible explanations: (a) the canonical storage-key format changed (infrastructure.md's example uses a `pipeline/` prefix that's absent from the DB's `file_path` values), or (b) the bytes were never uploaded for the HOOD S-1 filing after the R2 migration.

### Next Steps

1. Merge this PR to unblock `uv run` extraction for everyone.
2. Resolve the R2 image-bytes layer — tracked as Issue #77.
3. **Do NOT refresh the baseline until the R2 layer is resolved** — refreshing over zero chart recall locks in the bug.
4. Consider adding a CI job that exercises `uv sync` + a smoke extraction so pip/pyproject manifest drift gets caught pre-merge.
5. Blocks: PR merge commits against current main will keep failing the pre-commit Tier-1 guard until HOOD chart recall recovers (both this fix AND the R2 fix are required).
