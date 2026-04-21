# Known Issues and Future Improvements

This document tracks known issues, limitations, and planned improvements identified during extraction system development.

**Last Updated**: 2026-04-21, #65 opened for secret-leak guard on mis-named env duplicates (Five-issue follow-up bundle landed in commit `7848605` — #42 `_download_missing_images` double-write collapsed; #50 new `tests/unit/web/test_api_unified_auth.py` covers blueprint-wide 401 path; #51 grep-the-source tests rewritten as behavioral mock-cursor assertions; #52 new `scripts/check_pg_client_version.py` pre-flight; #54 new `chart_metric_min_confidence` operator knob, default 0.60 to avoid Tier 1 regression. #64 opened — chart classifier Tier 1 boundary sensitivity (HOOD `cm_balance_by_cohort` scores 0.6024, 0.0024 above gate). Archive cleanup collapsed 29 resolved issues into Archive section; rewrote Summary table to foreground open items. Also landed (from `origin/main` Wave B/C/D batch-ingest-ui follow-ups): #58 for 8-K Exhibit 99.1 fetching; #59 for 8-K section classifier patterns; #60 for `detect_universe_gaps` SIC-blindness; #61 for `/ingest/preview` integration coverage; #62 for local-dev stuck-batch recovery runbook; #63 for cancel-during-populate integration test.)

---

## Summary

### Open — High Severity

_(none currently)_

### Open — Medium Severity

| Issue | Status | Notes |
|-------|--------|-------|
| Low Farfetch Recall (Issue #2) | Re-diagnosed umbrella | P=50% R=37% F1=42% on 2026-04-18; superseded by sub-issues #14–#19 |
| Secret-leak guard on mis-named env duplicates (Issue #65) | Open | `.gitignore` only matches `.env` exactly; a file named `" "` containing full env was untracked but not ignore-protected |

### Open — Low Severity

| Issue | Status | Notes |
|-------|--------|-------|
| Farfetch precision drag — table-scale + period (Issue #16) | Open | 9 FPs across Active Consumers + Purchase Transactions; doesn't block recall |
| `v2_metric_facts.source_locator.img_id` no referential integrity (Issue #24) | Open | 9 orphan facts in local DB; cleanup + FK promotion still open |
| Mock-server / template-contract coupling (Issue #28) | Open | Smoke spec catches the symptom class; root coupling remains |
| `v2_metric_facts.doc_id` misleading name (Issue #38) | Open | BIGINT referencing `filings.filing_id` despite name; rename needs migration + caller sweep |
| `is_in_scope_phase1` misnomer post-10-K (Issue #39) | Open | Column name implies "in active universe" but means "Phase 1 IPO candidate" |
| 10-K/A supersession semantics undefined (Issue #40) | Open | Stakeholder decision needed before first bulk 10-K onboard |
| Spectrum Brands co-registrant filings still have Uber HTML cached (Issue #43) | Open | Latent — no facts extracted yet; hazard only on re-extraction |
| Integration test DB flakiness under full-suite `pytest -x` (Issue #49) | Open | Undermines pre-commit gate; reproduces on clean main |
| Chart call limit (10) truncates OCR on high-chart filings (Issue #53) | Open | Tier 1 charts in positions 11+ invisible to the bridge |
| 28 stuck 8-K filings in Class (E) (Issue #55) | Open | Out-of-scope 8-Ks reached `v2_image_assets`; inflates Issue #35 baseline |
| 8-K fetcher ignores Exhibit 99.1 (Issue #58) | Open | Primary doc often a cover sheet; earnings content in Exhibit 99.1. Blocks 8-K recall in batch-ingest UI rollout |
| 8-K section classifier missing earnings patterns (Issue #59) | Open | Classifier only knows `Item 1A/7/8`; 8-K segments all fall through to COVER/FINANCIALS |
| `detect_universe_gaps` ignores SIC filter (Issue #60) | Open | Reports gaps on `(year, form_type)` only; can trigger needless populate runs |
| `/ingest/preview` integration-test gap (Issue #61) | Open | Preview path is unit-tested; no end-to-end assertion on bucket split + volume banner |
| Local-dev stuck-batch recovery is manual (Issue #62) | Open | No watcher runs locally; subprocess death leaves `status='running'` forever |
| Cancel-during-populate not integration-tested (Issue #63) | Open | Conditional `_BATCH_COMPLETE_SQL` unit-tested; no end-to-end race-condition test |
| Chart classifier Tier 1 boundary sensitivity (Issue #64) | Open | HOOD `cm_balance_by_cohort` scores 0.6024 — 0.0024 above the 0.6 gate; silent-regression risk |

### Partially Resolved

| Issue | Status | Notes |
|-------|--------|-------|
| Snap Filing (ID 32/33) — Mislabeled Data (Issue #9) | Partially resolved | Snap not yet in gold standard; validation DB no longer required |
| Gold Standard Coverage Tests (Issue #11) | Partially resolved | 11/12 pass; 1 remaining (linked to archived Issue #10) |
| Images Tab Playwright assertions fail (Issue #27) | Partially resolved | 1 test fixed; 2 stale assertions `test.skip`-ed with TODOs |
| Pre-2026-04-17 filings missing chart facts (Issue #35) | Partially resolved | `chart_only` mode landed (PR #50); full 8-filing backfill deferred (#53, #54) |

### Known Limitations

| Issue | Status | Notes |
|-------|--------|-------|
| Spelled-Out Number Limits (Issue #4) | Known limitation | Complex compound numbers not supported; edge case in SEC filings |
| Revenue Synonym Gating (Issue #5) | Working as designed | GMV/TCV/ACV/Bookings/Billings require cohort context to generate candidates |

### Cross-Referenced (keep body until dependents close)

| Issue | Notes |
|-------|-------|
| Image cache / R2 backend (Issue #34) | Cross-referenced by #24, #35, #42; body retained until those close |

---

## 9. Snap Filing (ID 32/33) — Mislabeled Data (Validation DB Dependency Resolved)

**Status**: Partially resolved — validation DB dependency eliminated; Snap CIK fix still pending
**Severity**: Low (Snap not yet in gold standard; gold standard validation no longer DB-dependent)
**Discovered**: 2025-12-27 (HRV-5)
**Investigated**: 2026-03-19
**Updated**: 2026-03-19

### Problem

Filing ID 33 (and later reorganized to ID 32 in `gi3_richness_analysis.py`) is labeled "Snap"
but the CIK on record (`0001644378`) belongs to **RMR Group Inc.** (a REIT management company),
confirmed via SEC EDGAR API.

The local dev DB validation dataset was found to be **empty** as of 2026-03-19. The backup file
`filings_backup.dump` contains only schema, not data.

### Confirmed Facts

- Filing 33 CIK `0001644378` = RMR Group Inc. (confirmed 2026-03-19 via SEC API)
- Snap's correct CIK = `0001564408`, form S-1/A, filed 2017-02-27, accession `0001193125-17-056992`
- `gi3_richness_analysis.py` FILING_MAP comment was stale (said "IDs 31/33" were wrong; actually
  IDs 32/34 had RLX Technology / Vodka Brands data per GR-FINAL_VALIDATION.md 2025-12-26)

### Root Cause

CIK `0001644378` was mistakenly used for Snap instead of `0001564408` when originally ingested.

### Resolution (2026-03-19)

The empty local validation DB is no longer a blocker. Gold standard validation now runs in
**fresh mode** (`pytest -m gold_standard --gold-standard-mode=fresh -v`), which re-extracts
candidates directly from locally cached HTML files without requiring a populated database.

`test_gold_standard_regression.py` now supports `--gold-standard-mode=fresh`, making the
validation reproducible without any database setup. The `*.dump` pattern is now in `.gitignore`
to prevent accidentally committing production database dumps.

### Remaining (Low Priority)

- Re-ingest the actual Snap S-1/A (CIK `0001564408`, accession `0001193125-17-056992`, filed 2017-02-27) and add to the gold standard. **This is not a simple `companies.cik` column update** — filing 32 in the local DB (labeled "Snap") contains RMR Group content, so changing the CIK alone would leave the extracted facts pointing at the wrong company. A correct fix deletes or archives the orphaned filing 32 row, then runs the normal ingestion pipeline against the real Snap S-1/A URL. Track this as a separate workstream; not blocking.

### Partial Fix Applied (2026-03-19)

- Corrected stale comment in `gi3_richness_analysis.py` FILING_MAP
- Added inline note on Snap CIK pending fix

---

## 11. Gold Standard Coverage Tests — Partially Resolved

**Status**: Partially resolved
**Severity**: Low (1 test remaining)
**Discovered**: 2026-03-19
**Updated**: 2026-03-31

### Original Problem

Two tests in `tests/integration/test_gold_standard_coverage.py` were failing:
- `test_candidate_generation_finds_active_consumers`
- `test_candidate_generation_finds_number_of_orders`

### Resolution (2026-03-31)

Diagnosed and fixed. The failures had two root causes unrelated to the Farfetch re-fetch:

1. **Wrong metric ID** — Test expected `cm_transactions_by_cohort` for "Number of Orders", but extraction
   maps this to `cm_purchase_transactions_overall`. Fixed in test assertions (lines 62, 67, 267).

2. **Broken import in `TestKeywordPatterns`** — Tests accessed `MetricClassifier.METRIC_KEYWORDS` which
   does not exist (only `GENERAL_METRIC_KEYWORDS` is on the class). Fixed to import
   `METRIC_KEYWORDS` from `src.review.keyword_matching`.

After fix: 11/12 tests in `test_gold_standard_coverage.py` pass.

### Remaining (archived Issue #10)

`test_candidate_generation_finds_active_consumers` originally failed due to CMS-1 cross-metric
suppression, but that test module was deleted in commit `03a8a20` (V1 retirement). The test no
longer exists. See the archive entry for Issue #10 for full resolution details.

---

## 2. Low Farfetch Recall

**Status**: Re-diagnosed 2026-04-18; umbrella issue superseded by sub-issues #14–#19 below.
**Severity**: Medium
**Discovered**: 2026-01-01
**Re-measured**: 2026-04-18

### Current Farfetch Metrics (2026-04-18)

Re-measured via `python3 -m src.gold_standard.v2_validator --companies "Farfetch Limited" --fn-diagnostics`:

- **Overall**: P=50.0%, R=36.7%, F1=42.3% (TP=11, FP=11, FN=19)
- **Tier 1**: P=100%, R=10%, F1=18.2%
- **Tier 2**: P=45%, R=90%, F1=60%

Original "12.5%" figure (1 of 8 non-chart) is stale. The gold standard grew from 8 to ~30 Farfetch rows (49 total, 32 non-chart, 17 chart) since this issue was filed.

### Per-Metric Breakdown

| Metric | Tier | P | R | F1 | Notes |
|---|---|---|---|---|---|
| `cm_gross_margin_by_cohort` | T1 | 0% | 0% | 0% | 10 FNs — chart (see #15) |
| `cm_ltv_to_cac_ratio` | T1 | 100% | 100% | 100% | ✓ (Issue #14 resolved 2026-04-18) |
| `cm_ltv_to_cac_ratio_by_cohort` | T1 | 100% | 50% | 67% | Text FNs cleared (#14); 3 chart FNs remain (#20) |
| `cm_revenue_by_cohort` | T1 | 0% | 0% | 0% | 2 FNs — chart (see #15) |
| `cm_active_customers_total` | T2 | 29% | **100%** | 44% | Recall fine; 5 FPs (see #16) |
| `cm_average_order_value` | T2 | 100% | 100% | 100% | ✓ |
| `cm_cac_payback_period` | T2 | 0% | 0% | 0% | 1 FN — bare word-number (see #17) |
| `cm_purchase_transactions_overall` | T2 | 25% | 100% | 40% | Recall fine; 4 FPs (see #16) |

### Contributing Factors (Updated)

1. ~~**Metric ID mismatch** (Issue #1)~~ — resolved
2. ~~**URL issue** (Issue #6)~~ — resolved
3. ~~**CAC Payback "six"**~~ — KNOWN_ISSUES.md previously claimed this was fixed; **claim was inaccurate**. Spelled-out number support was added only for scaled forms ("six million"), not for time-unit forms ("six months"). See #17.
4. ~~**Take Rate patterns**~~ — void: `cm_take_rate` was removed from taxonomy 2026-01-02 (not a customer metric).
5. ~~**Layout-table dedup collision**~~ — resolved 2026-04-18 via #14 (respectively-parser priority + cohort_hint).
6. **Chart extraction blocked locally** — no `OPENAI_API_KEY` means chart-sourced gold rows can't be tested/recovered locally. See #15.
7. **Table-scale + period precision drag** — see #16.

### Next Steps

Issue #2 is now an umbrella. Individual gaps are tracked in sub-issues #14–#19. Close or demote Issue #2 after those sub-issues are triaged.

---

## 4. Spelled-Out Number Parsing Limitations

**Status**: Known Limitation
**Severity**: Low (edge case)

### Current Support

The system correctly parses:
- Simple numbers: "six", "twenty", "ninety"
- Teen numbers: "eleven", "fifteen", "nineteen"
- Compound numbers: "twenty-one", "forty-five"
- Magnitude words: "five million", "two billion"
- Hundreds: "hundred", "one hundred", "two hundred"

### Not Supported

Complex numbers like:
- "one hundred twenty-three" (compound hundreds)
- "two thousand five hundred" (multi-magnitude)
- "four hundred and fifty" (with "and")

### Rationale

These complex spelled-out numbers are rare in SEC filings - companies typically use numeric format for precision. The current implementation handles the common cases (e.g., "six months" for CAC payback period).

---

## 5. Revenue Synonym Context Gating

**Status**: Working as Designed
**Severity**: N/A (architectural decision)

### Background

Revenue-related metrics (GMV, TCV, ACV, Bookings, Billings) only generate review candidates when cohort/per-customer context is present. This is intentional to reduce false positives.

### Current Behavior

- ARR/MRR: Always generate candidates (inherently customer-related)
- GMV/TCV/ACV/Bookings/Billings: Require context keywords within 1500 chars
- Context keywords: cohort, vintage, per customer, per user, by account, etc.

### Potential Issue

Some valid per-customer GMV values may not have context keywords nearby, causing them to be missed.

### Monitoring

Review rejection rates for revenue synonyms to determine if context gating is too strict.

---

## 16. Farfetch Precision Drag — Table-Scale + Period Attribution

**Status**: Open (not blocking recall)
**Severity**: Low (creates review-queue noise; doesn't block gold-standard TPs)
**Discovered**: 2026-04-18

### Problem

Two Tier 2 Farfetch metrics show high recall but low precision due to table-scale inference producing near-match FPs:

- `cm_active_customers_total`: P=29%, R=100%, 5 FPs. Examples:
  - raw `935.8` → 935,800 (table "in thousands" applied); gold=796,297 in same period → BOTH_MISMATCH
  - raw `1,118.0` → 1,118,000 in 2018-H1; gold=796,297 in 2017-H1 → period + value mismatch
- `cm_purchase_transactions_overall`: P=25%, R=100%, 4 FPs. Same pattern (raw `800.5` → 800,500, etc.).

### Root Cause

For each period (e.g., 2015, 2016, 2017 + H1), the system extracts ONE correct value and several near-match values from adjacent periods with slightly different scales. These produce period-mismatch or value-mismatch FPs rather than clean TPs.

### Next Steps

- Investigate whether period-attribution logic can be tightened to prefer the nearest-period match when multiple extracted values share a metric.
- Consider dedup-collapsing same-metric near-matches that share source-locator ancestors.
- Low priority; doesn't affect recall or Tier 1.

---

## 24. `v2_metric_facts.source_locator.img_id` Has No Referential Integrity

**Status**: Open
**Severity**: Low
**Discovered**: 2026-04-18

### Problem

`img_id` is stored as a value inside a JSONB `source_locator` column (`sql/09_v2_schema.sql:420`), not as a foreign key. After the sql/34 fix, new facts written by `persist_pipeline_result` use the stable DB img_id. However, historical facts written before the fix likely contain orphaned img_ids pointing to rows that were collapsed by the dedup migration.

### Suggested Fix

Add a scheduled integrity-check script, or promote `img_id` to a dedicated FK column on `v2_metric_facts`. The latter is the more robust fix but requires a migration and application-layer changes.

### Diagnostic Script (2026-04-19)

`scripts/check_image_referential_integrity.py` scans for orphan `img_id` values and exits non-zero when any are found. Baseline against the local dev DB on 2026-04-19: **9 orphan facts across 4 docs** (doc_id=1546: 4, doc_id=1545: 2, doc_id=1551: 2, doc_id=1539: 1). These are historical facts predating the `sql/34` dedup migration. Prod has not been scanned yet. Cleanup strategy (delete orphan facts vs. rewrite `source_locator.img_id` to NULL vs. leave as-is) is still open.

### Extended to Three Classes (2026-04-19, commit `d1430d9`)

The script now reports three classes and is wired into the integration-tests CI job (`.github/workflows/ci.yml`):

- **Class (A)** — `source_type='chart'` facts with null `source_locator.img_id`. **Blocking** (exit 1); baseline 0; protects the `ChartFactBridgeStage` invariant.
- **Class (B)** — orphaned `img_id` refs (this issue). Warning-only.
- **Class (C)** — asset rows with `file_path` outside `data/` or missing on disk. Warning-only; tracked under Issue #34.

`tests/unit/extraction_v2/test_chart_fact_bridge_invariants.py` locks the Class (A) invariant at unit-test level.

---

## 27. Images Tab Playwright Assertions Fail

**Status**: Partially resolved (2026-04-19) — 1 test fixed via mock update; 2 stale assertions skipped
**Severity**: Low (test-only; no production impact)
**Discovered**: 2026-04-19 (latent; visible once `ui-e2e` CI job runs)
**Updated**: 2026-04-19

### Problem

Three tests in the Images Tab group of `tests/ui/review.spec.js` fail against the current mock server:

- `review.spec.js:965` — "first thumbnail item is active (current image)"
- `review.spec.js:1037` — "keyword badges shown in context panel"
- `review.spec.js:1054` — "image position shown in context panel" (expects `.image-context-panel` to contain text `"Image 1 of 2"`)

Verified byte-identical to the pre-rename `unified_review.spec.js` at `HEAD` before commit `413b386`, so the failures predate the Playwright-consolidation work and were masked by the suite never running in CI.

### Likely Cause

Either (a) the mock server's `/images-tab` route does not populate the exact shape `unified_review.html` expects for the "active thumbnail" / "image 1 of 2" / "keyword badge" markup, or (b) the template markup changed after the tests were authored without updating the tests. Needs a DOM inspection of the rendered page vs. the assertions.

### Why This Matters Now

The `ui-e2e` CI job added in commit `413b386` will flag these three tests red on every PR. Without fixing or explicitly skipping them, developers will start ignoring the suite's red status — the exact failure mode the CI job was meant to prevent.

### Resolution (2026-04-19, partial)

Root causes diagnosed via DOM inspection of `/images-tab` on the local mock server:

1. **`review.spec.js:965` (thumbnail active)** — `unified_review.html:617` compares `candidate.img_id == current_image.img_id`; the two mock dicts in `tests/ui/test_server.py` lacked `img_id`, so both thumbnails matched (`None == None`) and `.thumbnail-item.active` resolved to 2 elements. **Fixed** by adding distinct `img_id` values (`img-pending-10`, `img-reviewed-11`) to `MOCK_IMAGE_CANDIDATE_PENDING` / `MOCK_IMAGE_CANDIDATE_REVIEWED`.
2. **`review.spec.js:1037` (`.keyword-badge`)** — template has no `.keyword-badge` element; assertion is stale. **Skipped** with `test.skip` + TODO(KNOWN_ISSUES #27).
3. **`review.spec.js:1054` ("Image 1 of 2")** — template renders "Image #N" in the main display (`unified_review.html:668`), not "Image N of M" in the context panel; assertion is stale. **Skipped** with `test.skip` + TODO(KNOWN_ISSUES #27).

Verified via `npx playwright test review.spec.js`: 142 pass, 2 skip, 0 fail.

### Remaining

If the "Image N of M" counter and keyword-badge visualisation are features that *should* exist in the context panel, re-introduce them in `unified_review.html` and unskip the two tests. Otherwise delete the skipped tests next time this module is touched. Tracked here because the product intent is unclear.

---

## 28. Mock-Server / Template-Contract Coupling

**Status**: Open
**Severity**: Low (smoke spec mitigates the most common breakage class)
**Discovered**: 2026-04-17 (symptom in commit `3e398fd`); follow-up surfaced 2026-04-19 during Playwright consolidation

### Problem

`tests/ui/test_server.py` must supply every template variable that production routes pass to `unified_review.html`. Whenever a new variable is introduced in `src/web/routes/review_unified.py` (e.g. `next_filing_url|tojson` in commit `3e398fd`), the mock server renders an `Undefined` and Jinja raises `TypeError` on filters like `|tojson`, returning 500 across every route.

Related surface: the mock also ships stubs for `POST /api/v2/decisions`, `DELETE /api/v2/decisions/<id>`, `POST /api/v2/image-decisions`, and `POST /api/v2/missed-metric`. Their response shapes are maintained in parallel with production; no contract check enforces parity.

### Mitigation Already In Place

Commit `413b386` added `tests/ui/smoke.spec.js` which iterates the 7 template-rendering routes and asserts HTTP 200 + no `pageerror` events. This catches the Apr 17 failure class (500 on render) in ~5 seconds before the functional suite runs.

### What the Mitigation Doesn't Catch

1. Template variable that is defined but wrong *shape* (e.g. string where list expected) — no 500, but functional tests fail with harder-to-read assertions.
2. Drift in the POST stub JSON response shape vs. production.
3. New production routes or template files that the mock server has not been updated to support.

### Possible Fixes (Pick One Later)

| Option | Effort | Robustness | Notes |
|---|---|---|---|
| Extend smoke spec to POST routes | Small | Low | Asserts 2xx on each stub endpoint; doesn't verify response shape against production |
| Declarative template-variable contract | Medium | Medium | Introduce a `mock_context.py` module listing all vars; add a unit test that imports the real route function and asserts the mock context is a superset |
| Swap mock server for real Flask app + seeded test DB | Large | High | Eliminates the parallel implementation entirely; requires DB setup in Playwright webServer command |

### Next Steps

Not urgent. Revisit if the smoke spec starts missing real breakages or if the mock server grows enough routes that the duplication becomes a regular drag.

---

## 34. `v2_image_assets.file_path` Rooted in TMPDIR (Purged by OS)

**Status**: Resolved (Phase 1: 2026-04-19, Phase 3: 2026-04-20)
**Severity**: Medium — was breaking Chart Evidence preview on ~30% of image rows (50 / 165 local; prod unscanned)
**Discovered**: 2026-04-19 (Phase 1 of the "missing Chart Evidence" investigation, commit `d1430d9`)
**Resolved**: 2026-04-19

### Problem

`v2_image_assets.file_path` was being written as `/var/folders/.../T/filings_image_cache/pipeline/<filename>.jpg` — macOS's TMPDIR. 158 of 165 asset rows on the local dev DB lived outside `<repo>/data/` entirely (the remaining 7 are a separate, presentation-pipeline root). The TMPDIR is purged by the OS on reboot and after long periods of inactivity, so `image_crop` (`src/web/routes/review_unified.py:521-581`) returned 404 for the majority of rows even when the asset row and the extracted chart fact were intact.

The endpoint's `resolved.relative_to(data_dir)` security check also rejects TMPDIR paths outright as a path-traversal precaution, so the 404 fires even when the file happens to still be present. Either way, the reviewer saw no chart preview.

This was the dominant root cause behind the Box Inc S-1/A `cm_revenue_by_cohort = $2.8M` case in the commit-`d1430d9` investigation. Template placeholders added in `d1430d9` surfaced the failure explicitly.

### Diagnostics

`scripts/check_image_referential_integrity.py` (Issue #24) reports Class (C) "asset rows with file_path outside data/ or missing on disk" alongside the Class (B) orphan check. Local baseline 2026-04-19: 158 / 165 rows (96%) outside `data/`, 50 / 165 absent on disk. Class (C) remains **warning-only** in CI; flip to blocking once any remaining TMPDIR rows are rewritten or reprocessed.

### Resolution (2026-04-19)

`src/extraction_v2/stages/ocr_extraction.py:199-227` was rooted in `tempfile.gettempdir()`. The fix introduces `src/infra/paths.py::image_cache_dir()`, an `lru_cache`'d helper that honors an `IMAGE_CACHE_DIR` env var and defaults to `<repo>/data/image_cache/`. The pipeline subdirectory was also restructured from a flat `pipeline/<filename>` to a collision-safe `pipeline/<cik>/<accession>/<filename>` layout — the flat layout would have become permanent cross-filing corruption under `batch_v2_extraction.py --workers N` once the cache was persistent (latent in TMPDIR because OS purges masked it).

`data/image_cache/` was added to `.gitignore`. Unit tests at `tests/unit/infra/test_paths.py` and the `TestImageDownloading` fixture in `tests/unit/extraction_v2/test_image_pipeline_integration.py` fence `IMAGE_CACHE_DIR` to `tmp_path` via a class-scoped autouse fixture, preventing test-time pollution of the real `data/image_cache/` tree.

Every subsequent re-extraction heals its own filing's rows; no one-shot migration is required. Historical rows surface via `d1430d9`'s Chart Evidence placeholder until their filing is re-extracted.

### Resolution — Phase 3 (2026-04-20)

**Option C adopted** (instead of A or B): introduced an `ImageStorage` abstraction with two backends — `LocalFilesystemStorage` (dev/test, defaults under `data/image_cache/`) and `R2Storage` (prod, backed by a private Cloudflare R2 bucket via `boto3`). Selected at runtime via the `R2_BUCKET` env var. `v2_image_assets.file_path` now stores an opaque storage key (e.g. `pipeline/<cik>/<accession>/<filename>`) rather than an absolute filesystem path; shape is validated by `src/infra/image_storage.py::validate_key`.

Seven call sites were migrated off direct `Path(file_path)` dereferencing (write in `ocr_extraction._download_missing_images` and `ingestion._extract_image_assets`; reads in `process_table_image`, `process_chart_image`, `fact_construction` evidence-screenshot copy, `image_crop`, and `_resolve_chart_image_status`). `check_image_referential_integrity.py` Class (C) now validates via `storage.exists()` and shape-check instead of `Path.resolve() / relative_to(data_dir)`. `image_crop` gained a `Cache-Control: private, max-age=3600` header to keep repeat clicks off R2.

Prod provisioning (user actions, completed 2026-04-19): Cloudflare R2 bucket `filings-reviewer-image-cache`, object-scoped API token, and four `R2_*` env vars on both Render web + cron services. Test-only dependency `moto[s3]>=5.0.0` (in `requirements-dev.txt`) mocks R2 for unit tests — no real R2 calls in CI.

Chosen over Option A (Render persistent disk) because R2's free tier (10 GB + 1M write ops + zero egress) covers current volume without paid infra, and over Option B (re-fetch-on-miss) because R2 is architecturally the same thing with fewer per-request latency surprises and sets up for multi-reviewer concurrency without OneDrive-style sync hazards. See `docs/architecture/image-storage.md`.

Legacy rows (pre-migration absolute paths) fail `validate_key` and return 404 via the review UI's placeholder path — identical user-facing behavior to the Phase 1 post-state. They heal naturally on re-extraction.

### Cross-References

- Issue #24 — JSONB img_id has no FK (the orphan class is a separate failure mode; this one is about the file system root)
- Issue #22 — reviewed-filing guard on image re-extraction (must be honoured by any backfill script)
- Issue #35 — now fully unblocked; 38-filing chart-fact backfill can proceed on both dev and prod
- `docs/architecture/image-storage.md` — detailed architecture reference

---

## 35. Pre-2026-04-17 Filings Missing Chart-Sourced Facts

**Status**: Partially resolved (2026-04-21) — mechanism landed, recall gain marginal
**Severity**: Low — Tier-1 recall gap was overstated; most in-scope filings don't have Tier 1 cohort/NRR charts
**Discovered**: 2026-04-19 (Phase 1 of the "missing Chart Evidence" investigation, commit `d1430d9`)
**Partial resolution**: 2026-04-21 (PR #50 landed `chart_only` surgical backfill mode)

### Update 2026-04-21 — investigation outcome

Backfill mechanism shipped via PR #50 (`V2PersistenceAdapter.persist_*(chart_only=True)` + `scripts/batch_v2_extraction.py --chart-only`). The mode scopes the DELETE-then-INSERT to `source_type='chart'` and the reviewed-filing guard to chart-fact decisions only, so text facts and their reviewer decisions are preserved — allowing surgical re-extraction on filings with accumulated reviewer work without CASCADE-destroying it.

Neon-prod quantification on 2026-04-21 revised the problem size sharply:

- 38 Class (E) filings total → **28 are stuck 8-K filings** in `processing_status='processing'` that shouldn't have been ingested (see Issue #55 below), and **10 are in-scope S-1/F-1** (8 non-reviewed + 2 reviewed) — the real backfill target is ≤10 filings, not 38.
- Of those ≤10, all 8 non-reviewed candidates have accumulated 81 reviewer decisions across them, making the guard's preservation the binding constraint (which `chart_only` solves).

Three smokes on Neon (1547 Samsara, 1541 Flywire, 1146 Chewy) confirmed:

- Mechanism is safe: reviewer decisions fully preserved across all three runs; text/html_table facts untouched.
- Recall gain is sparse: only 1 chart fact produced across 3 filings (Chewy), and that fact was a low-confidence (0.508) misbind of `cm_customer_acquisition_cost`=$3 — a reviewer-gated false positive.

Root cause of the sparse gain: the original 38-filing Class (E) baseline conflates (a) filings where pre-fix OCR dropped Tier 1 cohort/NRR chart data with (b) filings whose charts aren't Tier 1 metrics at all (market-size, process diagrams, photos). Only (a) recovers under re-extraction; most of the 38-filing set is (b).

### Remaining work

- Full 5-filing Phase 4' (1442, 1543, 1549 Snowflake, 1550 Tenable, 1146-remainder) deferred: expected recall gain doesn't justify the reviewer-curation overhead until Issues #53 and #54 (chart-call-limit truncation and chart-bridge low-confidence misbinds) are investigated.
- Class (E) diagnostic should narrow to S-1/F-1 form types (and exclude filings whose charts don't include Tier 1 metrics) to avoid overstating the gap in future audits.
- 2 reviewed filings (1542, 1543) still in Class (E) under chart_only's guard — acceptable; they preserve reviewer work.

### Cross-References

- `.claude/rules/v2-pipeline.md#chart-only-re-extraction-chart_onlytrue` — mechanism documentation
- Issue #34 — R2 backend (Phases 1 + 3 resolved 2026-04-19)
- Issue #24 — Class (B) orphan img_id refs (still open; independent of Issue #35 scope)
- Issue #53 — chart call limit (10) truncates OCR for high-chart filings
- Issue #54 — chart-bridge emits low-confidence misbinds on non-Tier-1 charts
- Issue #55 — 28 stuck 8-K filings in Class (E) (form-filter bypass during ingestion)
- PR #50 — `feat(persistence): add chart_only mode for surgical Issue #35 backfills`
- Session artifacts: `data/audit/issue_35_presmoke_snapshot.sql`, `data/audit/issue_35_presmoke_gs.txt`, `logs/issue_35_prod_smoke{,2,3}.log`

---

## 38. `v2_metric_facts.doc_id` Is Misleadingly Named

**Status**: Open
**Severity**: Low — tech debt; migration + multi-file rename required
**Discovered**: 2026-04-19 (prod SQL failure in `count_review_decisions`)

### Problem

`v2_metric_facts.doc_id` is `BIGINT REFERENCES filings(filing_id)` per
`sql/09_v2_schema.sql:18` — i.e., it's a `filing_id`, not a reference to
`v2_documents.doc_id` (which is a separate UUID primary key). The column
name suggests the latter.

This tripped me during Issue #7 hotfix work: `count_review_decisions` in
`scripts/onboard_tickers.py` originally joined
`v2_documents.doc_id (UUID) = v2_metric_facts.doc_id (BIGINT)`, producing
a runtime `operator does not exist: uuid = bigint` error that only fired
in production (fixed in commit `c353e83`). Any future developer writing
a cross-table query is likely to hit the same trap.

### Suggested Fix

Rename `v2_metric_facts.doc_id` → `filing_id` via a migration:

- `sql/NN_rename_metric_facts_doc_id.sql` — `ALTER TABLE v2_metric_facts
  RENAME COLUMN doc_id TO filing_id`.
- Update every caller in `src/` (look for `.doc_id` on fact objects or in
  raw SQL touching `v2_metric_facts`).
- Update `MetricFact` dataclass if the attribute is exposed.
- Identity-tuple logic in `src/extraction_v2/models.py` and
  `src/extraction_v2/persistence.py` references `doc_id` — check.

Not urgent (inline comment in `scripts/onboard_tickers.py` flags the
naming; `count_review_decisions` SQL correct). Queue when `v2_*` has a
broader cleanup window.

### Cross-References

- `sql/09_v2_schema.sql:18` — column definition
- `scripts/onboard_tickers.py::REVIEW_DECISIONS_SQL` — inline caveat comment
- commit `c353e83` — the bug that surfaced this

---

## 39. `is_in_scope_phase1` Is a Misnomer Post-Issue-#7

**Status**: Open
**Severity**: Low — naming / documentation, no functional bug
**Discovered**: 2026-04-19 (during Issue #7 implementation)

### Problem

`filings.is_in_scope_phase1` suggests "this filing is in the active
universe." Its actual semantic is stricter: "this is an S-1/F-1 filing
from a first-time non-SPAC non-investment-vehicle non-resource-extraction
issuer" (classifiers.py:832-834). With 10-K support (Issue #7) landed,
10-K rows correctly have `is_in_scope_phase1=FALSE` — but that reads as
"out of scope" to anyone browsing `filings`. The column and query-time
filter are now confusing.

### Suggested Fix

Two options:

1. **Rename column** → `is_phase1_ipo_candidate` (scoped to S-1/F-1 by
   design). Migration + updates to `filings` upserts, discovery SQL in
   `scripts/onboard_tickers.py::_build_discovery_sql`, gold-standard
   validator queries, any `WHERE is_in_scope_phase1 = ...` usage.
2. **Add a form-aware companion column** `is_customer_metric_candidate`
   that's true for S-1/F-1 FTI _and_ true for 10-K/10-K/A that pass basic
   filters (non-SPAC, non-investment-vehicle, non-resource-extraction).
   Leave `is_in_scope_phase1` as-is for historical callers.

Option 2 is less disruptive but adds DB surface area. Option 1 is
conceptually cleaner but requires a coordinated migration + code sweep.

Bundle with Issue #38 if tackled — both are column-name clarifications in
the same schema area.

### Cross-References

- `src/universe/classifiers.py:832-834` — `is_in_scope_phase1` definition
- `scripts/onboard_tickers.py::_build_discovery_sql` — already has a
  workaround (conditionally omits the Phase-1 filter for non-S-1/F-1
  form types)
- `docs/operations/TICKER_ONBOARDING.md` — "10-K onboarding semantics"
  section documents the current confusing behavior
- Issue #7 — introduced 10-K support that makes the misnomer visible

---

## 40. 10-K/A Supersession Semantics Undefined

**Status**: Open
**Severity**: Low — design decision, needs stakeholder input
**Discovered**: 2026-04-19 (during Issue #7 implementation)

### Problem

`UniverseBuilder` after-loop step `self.db.mark_superseded_filings()`
(universe_builder.py:107) demotes earlier S-1/S-1/A/F-1/F-1/A filings per
CIK — "only the latest amendment in scope." For 10-K/A (restatements),
the method is scoped to S-1/F-1 only; 10-K and 10-K/A rows are preserved
as separate in-scope entries.

Two defensible interpretations:

- **"Restatement replaces original":** 10-K/A is the corrected version —
  the original is misleading and should be marked superseded. Matches
  S-1/A semantics.
- **"Both are distinct fiscal-year events":** each row represents a
  point-in-time filing with different disclosures; analytics may want to
  compare pre- vs post-restatement. Current behavior.

Current behavior is option 2 (both survive). No one has validated this is
the intended operator workflow; no 10-Ks are in prod today (Issue #7 just
shipped the capability).

### Suggested Fix

Before the first operator bulk-onboards 10-Ks:

1. Decide which semantic matches the analytic use case (ask CMASB
   stakeholders).
2. If "restatement replaces": extend `mark_superseded_filings` to include
   10-K/A pairs, add a test, document in the runbook.
3. If "both distinct": document the decision in
   `docs/operations/TICKER_ONBOARDING.md` under "10-K onboarding semantics"
   so reviewers / analysts know what to expect.

Lightweight either way — <30 LOC + tests + doc line.

### Cross-References

- `src/universe/universe_builder.py:107` — `mark_superseded_filings` call
- `src/infra/db.py::mark_superseded_filings` — form-type scope
- `docs/operations/TICKER_ONBOARDING.md` — "10-K onboarding semantics"
- Issue #7 — landed 10-K support without resolving this

---

## 43. Spectrum Brands Co-Registrant Filings Still Have Uber HTML Cached on Disk

**Status**: Open
**Severity**: Low (latent — no facts extracted yet, no reviewer work affected; becomes a hazard only if extraction runs before the HTML is refreshed)
**Discovered**: 2026-04-19 (audit for Issue #30)

### Problem

Filing_ids 902, 903, 904, 905, 906, 907, 908, 909, 910, 911, 913, 914, 915, 916, 919 all point `html_storage_path` at `data/filings/0001725792/000119312519149408/primary.htm`. That file contains **Uber S-1/A content**, not the Spectrum Brands 2019 S-1/A content these rows represent (accession `0001193125-19-149408`, co-registered by 15 Spectrum Brands entities). Root cause is the same pre-Issue-#6 FilingFetcher mis-save that caused Issue #30 — the URL column was fixed by the #30 resolution, but the cached HTML file was not replaced.

### Why it's latent, not active

All 15 rows have `v2_metric_facts_count = 0`, `v2_review_decisions_count = 0`, `v2_image_review_decisions_count = 0`. No extraction has run on these filings, so no facts are derived from the wrong HTML. Reviewer-facing UI links point to the correct SEC documents (fixed in Issue #30). The problem would only surface if/when someone runs `scripts/batch_v2_extraction.py` against these filing_ids — they'd get Uber facts attributed to Spectrum Brands.

### Next Steps

Pick one:

1. **Refetch once, update all 15** (preferred): Call `FilingFetcher.fetch_filing()` for one co-registrant (e.g., the primary Spectrum Brands CIK `0001028985`) with the correct resolved URL, writing to a new storage path under `data/filings/0001028985/000119312519149408/primary.htm`. Then `UPDATE filings SET html_storage_path = <new path>, html_content = NULL WHERE filing_id IN (902, 903, ..., 919)`. Force-reextract not needed because `facts=0`.
2. **Delete the stale file + clear paths**: Just `UPDATE filings SET html_storage_path = NULL, html_content = NULL, html_fetched_at = NULL, processing_status = 'pending' WHERE filing_id IN (...)` and let the normal `FilingFetcher` flow re-download on next run. Simpler, but reverts processing_status.
3. **Remove from universe**: if Spectrum Brands debt-securities S-1/A is not actually in scope for customer-metrics analysis (these are consumer-goods entities, not tech/SaaS), consider deleting the 15 rows entirely — safe here because `facts=0 AND reviews=0`.

### Context

See Issue #30 resolution notes (now in archive) for full audit trail. Apply log at `data/audit/issue_30_applied_20260419T210109Z.jsonl`.

---

## 49. Integration Test DB Flakiness Under Full-Suite `pytest -x`

**Status**: Open
**Severity**: Low
**Discovered**: 2026-04-20

### Problem

Running `pytest -x -q` over the full suite (unit + integration) reproducibly
fails in the first integration test that hits the connection pool. Errors
observed: `AdminShutdown: terminating connection due to administrator
command`, `psycopg.OperationalError: the connection is lost`, and
`deadlock detected` in `ROLLBACK` during fixture teardown. The specific
test that trips varies run-to-run — during #48 work, both
`tests/integration/test_db_v2_image_methods.py::TestGetImageReviewCandidatesForFilingV2::test_returns_non_decorative_images_only`
and
`tests/integration/extraction_v2/test_batch_runner_db.py::TestBatchRunnerQueryFilings::test_query_filings_returns_expected_columns`
have surfaced. Each test passes individually. Reproduces on clean `main`
with in-flight changes stashed, so it predates #48. Distinct from resolved
issues #7/#8 (missing teardown); symptom here looks like cross-test pool
orchestration or a session-scoped fixture forcing a pool rebuild during
another test's open transaction.

The effect is that the "run `pytest -x -q` before committing" gate in
CLAUDE.md is undermined — operators have to know to fall back to
`pytest tests/unit -q` and separately exercise integration, or skip the
pre-commit check.

### Next Steps

- Reproduce deterministically: run `pytest -x -q` against the integration
  dir in isolation and bisect which test ordering triggers the admin
  shutdown.
- Inspect `tests/integration/conftest.py` `test_db_adapter` and
  `clean_db` fixtures for session-scoped lifetime vs. per-test pool use.
- Candidate fix: force `function`-scoped pools for integration tests, or
  ensure the `clean_db` fixture's `TRUNCATE` does not race with another
  test's open connection.

---

## 53. Chart Call Limit (10) Truncates OCR on High-Chart Filings

**Status**: Open
**Severity**: Low — undercuts Tier 1 chart-fact recall for filings with >10 chart images
**Discovered**: 2026-04-21 (surfaced during Issue #35 smoke on Chewy, filing_id=1146)

### Problem

`OCRExtractionStage` enforces a hard cap on per-filing chart OCR calls. During the Chewy smoke (`logs/issue_35_prod_smoke3.log`), only 10 of 20 queued chart/table images were OCR'd before:

```
WARNING:src.extraction_v2.stages.ocr_extraction:Chart call limit (10) reached
```

Filings with lots of charts (Chewy has 16 chart-classified images; Snowflake has 8; on-average-larger S-1s exceed 10 easily) silently lose extraction coverage on the trailing images. The skipped images never get queried, so any Tier 1 cohort/NRR chart in positions 11+ is invisible to the bridge regardless of whether the OCR would have succeeded.

### Next Steps

- Locate the limit in `src/extraction_v2/stages/ocr_extraction.py` (likely a module-level constant or `PipelineConfig` field) and either raise the default, convert to a per-filing override, or expose via CLI flag on `batch_v2_extraction.py`.
- Re-run the Chewy smoke with the cap raised to quantify the missed-recall impact.
- Consider prioritization: OCR charts in likely-Tier-1 sections first (MDA, financials) rather than HTML order.

---

## 55. 28 Stuck 8-K Filings in Class (E) from Form-Filter Bypass

**Status**: Open
**Severity**: Low — 8-K data is out-of-scope for this extraction system; inflates Class (E) baseline
**Discovered**: 2026-04-21 (Issue #35 Phase 1 Neon quantification)

### Problem

Of the 38 filings in `scripts/diagnostic_chart_evidence_coverage.py` Class (E) on Neon prod, **28 are 8-K filings** in `processing_status='processing'` with `html_storage_path IS NULL` and `html_content IS NULL`. The extraction system is designed for S-1/F-1 (see `DEFAULT_FORM_TYPES_S1F1` in `src/universe/universe_builder.py`), yet these 8-Ks reached ingestion far enough to have `v2_image_assets` chart-classified rows written, then stalled. This suggests a form-filter bypass somewhere in the ingestion path — possibly an early-path onboarding script, possibly a reviewer action, possibly a daily-cron edge case.

Seven of the 28 additionally have 2–3 reviewer decisions each on text/table facts, which is even more puzzling for an allegedly out-of-scope form type.

Filing ids captured in `data/audit/issue_35_prod_class_e_raw.txt` and the original target/exclusion lists.

### Next Steps

- Trace how these 8-K filings entered the pipeline: `git log` the ingestion path around the 2026-04-xx window, `grep` for any codepath that calls `FilingFetcher` or `V2Pipeline.process` without a form-type gate.
- Decide cleanup strategy: (a) retroactively delete the `filings` + `v2_image_assets` + `v2_metric_facts` rows for these 28 ids; or (b) reclassify to `processing_status='out_of_scope'` and update the Class (E) diagnostic to filter on `form_type IN ('S-1','S-1/A','F-1','F-1/A')`.
- If reviewer decisions on 8-Ks are intentional (user-directed review for some reason), skip the deletion option and go with (b).

---

## 58. 8-K Fetcher Returns Only Primary Doc; Earnings Content Lives in Exhibit 99.1

**Status**: Open
**Severity**: Medium — blocks 8-K recall in batch-ingest UI rollout
**Discovered**: 2026-04-20 (Phase 0 pre-flight for batch-ingest UI)

### Problem

`FilingFetcher.fetch_filing` (`src/filing_fetcher/filing_fetcher.py:263-365`) downloads only `primary.htm` resolved from the accession's directory URL. For many 8-K filings the primary doc is a ~10 KB cover page that points at Exhibit 99.1 (the actual press release / financial-highlights HTML). Pipeline ran cleanly on 4/5 Phase 0 candidates but Samsara (2025-08-21) produced 0 facts — the primary doc was 9,336 bytes of boilerplate; all customer-metric content sat in `exhibit991-2025x08x21.htm` which was never fetched.

### Next Steps

1. In `fetch_filing`, after downloading `primary.htm`, parse the index for `99.1` (or regex-matched variants like `ex-99-1`) and download the exhibit alongside the primary doc.
2. Decide whether the pipeline consumes only the exhibit, both docs concatenated, or runs twice and merges facts — prefer "concat with a section break" for the MVP to avoid invalidating `filing_id` uniqueness.
3. Add an integration test using the Samsara 8-K (or a fixture mirroring its structure) asserting >0 customer-metric facts.
4. Gate on this before enabling 8-K in the batch-ingest UI form-type selector.

---

## 59. 8-K Section Classifier Produces Only `COVER` / `FINANCIALS` Labels

**Status**: Open
**Severity**: Low — extraction still works; section-aware FP rules and UI navigation degrade
**Discovered**: 2026-04-20 (Phase 0 pre-flight for batch-ingest UI)

### Problem

`SectionClassificationStage.SECTION_PATTERNS` (`src/extraction_v2/stages/section_classification.py:104-138`) only knows S-1/10-K structural headings (`Item 1A`, `Item 7`, `Item 8`, etc.). 8-K earnings exhibits use narrative patterns like "Financial Highlights", "Key Business Metrics", "Q4 Highlights", "Results of Operations" that none of the existing patterns match. Phase 0 run: every segment on Chewy / DoorDash / Robinhood / Snowflake 8-Ks was classified as `COVER` or `FINANCIALS`. Candidate generation and value binding still produced correct facts, but sections-aware downstream logic (FP rules keyed on `section_type`, reviewer UI navigation, section-scoped metric scoring) is blind on 8-Ks.

### Next Steps

1. Add a new `SectionType` variant — e.g. `EARNINGS_HIGHLIGHTS` — or piggyback on `BUSINESS` if the existing type taxonomy already carries the right semantics.
2. Add pattern list entries for common 8-K headings: `Financial Highlights`, `Key Business Metrics`, `Q[1-4]\s*\d{4}\s*Highlights`, `Results of Operations`, `Business Highlights`.
3. Validate against the Phase 0 candidate set (Chewy, DoorDash, Robinhood, Snowflake 8-Ks) — expect >=30% of segments to land on non-COVER sections.
4. Audit existing FP rules for section-gated behavior that might fire differently once 8-K segments are correctly typed.

---

## 60. `detect_universe_gaps` Ignores SIC Filter When Reporting Populate Gaps

**Status**: Open
**Severity**: Low — correctness-neutral, efficiency issue
**Discovered**: 2026-04-20 (Phase 1 review of `src/universe/onboarding.py`)

### Problem

`src/universe/onboarding.py::detect_universe_gaps` reports a `(year, form_type)` gap whenever the `filings` table has zero rows for that combination in the query's year range, regardless of the query's SIC code set. A reviewer filtering the UI to e.g. grocery retail 8-Ks will see a "populate 2023" prompt even if 2023 already has thousands of non-grocery 8-K filings in `filings` — the SIC intersection with those is empty, but the year/form coverage exists. The populate run that follows will re-fetch an entire year of 8-K metadata unnecessarily.

### Next Steps

1. Change the gap query from `filings.form_type + filing_date` to `filings JOIN companies ON company_id` with `industry_code = ANY(%(sic_codes)s)` (or the equivalent once the companies.industry_code field is populated — check that first).
2. Alternatively, accept the over-populate behavior and document the trade-off in `src/universe/onboarding.py` at the function docstring — populate is idempotent, just bandwidth-wasteful.
3. Add a unit test covering the "filings exist but not for our SIC" case.

---

## 61. `/ingest/preview` Has No Integration-Test Coverage

**Status**: Open
**Severity**: Low — unit tests exist for the form-parsing layer; the end-to-end path is untested
**Discovered**: 2026-04-20 (Wave B Phase 4 review)

### Problem

`tests/integration/web/test_ingest_flow.py` covers `GET /ingest/`, `POST /ingest/start`, `GET /api/v2/ingest/batches/<id>/status`, `POST /cancel`, and auth. `POST /ingest/preview` — the middle step that runs `resolve_criteria` + `discover` + `classify_volume` + `count_reviewer_work` and renders the three-bucket candidate table — is only covered by unit tests on the form-parser helpers. No end-to-end assertion that a valid criteria submission renders a preview page with the correct bucket split + volume banner.

### Next Steps

1. Add an integration test that seeds two filings (one in `v2_documents`, one not) + a reviewed fact on the extracted one, POSTs `/ingest/preview` with criteria that match both, and asserts the three buckets render correctly.
2. Assert the volume banner class (`alert-success` / `alert-warning` / `alert-danger`) for each band.
3. Assert hidden-field snapshot survives re-render — `filing_id` hidden inputs must be present and match the discovered IDs.

---

## 62. Local-Dev Stuck-Batch Recovery Is Manual

**Status**: Open
**Severity**: Low — operational; no data loss, just operator inconvenience
**Discovered**: 2026-04-20 (Wave B Phase 3 review)

### Problem

On Render (Phase 7), a worker service with `--watch` mode will re-claim a batch whose `run_lock_until` has expired. On local dev there is no watcher — if the `onboarding_runner` subprocess dies mid-batch (kernel OOM, user kills the Flask server, etc.), the batch stays in `status='running'` forever. Currently recovery requires a hand-crafted `UPDATE v2_ingest_batches SET status='failed' WHERE batch_id=...` plus a cleanup of partially-processed `v2_ingest_batch_filings` rows.

### Next Steps

1. Document the manual recovery SQL in `docs/operations/TICKER_ONBOARDING.md` (or a new batch-ingest runbook) when that file lands in Phase 7.
2. Consider a `python3 -m src.universe.onboarding_runner --cleanup-stuck` admin flag that scans for batches with `run_lock_until < NOW() - INTERVAL '1 hour'` still in `running` state and either marks them failed or re-claims them.
3. Add a CLI log line to the runner on SIGTERM that tells the operator "batch <id> interrupted — run `... --cleanup-stuck` to recover".

---

## 63. Cancel-During-Populate Not Exercised by Integration Test

**Status**: Open
**Severity**: Low — behaviour is documented + the conditional SQL is unit-tested
**Discovered**: 2026-04-20 (Wave C / Phase 6 review)

### Problem

Wave C documents the cancel-during-populate flow (cancel flips `status='cancelled'`; runner respects it on natural completion via the new `WHERE status='running'` predicate on `_BATCH_COMPLETE_SQL`). The conditional SQL is unit-tested via string assertion (`tests/unit/universe/test_onboarding_runner.py::TestBatchCompleteConditional`), but no integration test simulates a runner mid-`build_universe` while cancel fires concurrently.

### Next Steps

1. Add an integration test in `tests/integration/universe/test_onboarding_runner_integration.py::TestPopulateCancellation` that: inserts a populate batch, monkey-patches `UniverseBuilder.build_universe` to flip the batch status to `cancelled` mid-run, calls `_run_populate`, asserts final status stays `cancelled` (not `complete`) and `finished_at IS NOT NULL`.
2. Optionally extend Phase 5's JS to render a "Cancellation pending — batch will stop after current operation completes" banner when `status='cancelled' AND finished_at IS NULL` (today the JS shows the cancelled banner immediately).

---

## 64. Chart Classifier Tier 1 Boundary Sensitivity

**Status**: Open
**Severity**: Low — monitoring / silent-regression risk
**Discovered**: 2026-04-21 (during Issue #54 implementation)

### Problem

`ChartMetricClassifier.classify` returns a score of **0.6024** for the `cm_balance_by_cohort` fixture used in `tests/extraction_v2/chart/test_chart_fact_bridge_stage.py::test_emits_facts_for_classified_chart` — a HOOD-style "Cumulative Net Deposits by Cohort" chart that is a legitimate Tier 1 match. That score is **0.0024 above the 0.6 classification gate**. Any small scoring shift (new keyword, weight rebalance, corpus tuning) could push this and similar Tier 1 matches below the gate and silently regress recall.

Discovered while implementing Issue #54: the issue's suggested default (`chart_metric_min_confidence = 0.70`) would have suppressed this fact. The landed fix set the default to 0.60 (no-op) and left 0.70 as an operator knob.

### Next Steps

- Measure the full distribution of classifier scores across current gold standard Tier 1 chart matches (Farfetch, HOOD, Flywire). Identify how many are within 0.05 of the 0.6 gate.
- If multiple Tier 1 matches sit at ~0.6, add a unit test that asserts "score floor - classification gate > 0.02" on the fixture set, so any future classifier change that narrows the margin fails loudly.
- Alternative: widen the classifier scoring function so legitimate Tier 1 matches comfortably exceed the gate, then raise the gate to 0.65+ without regression.

### Cross-References

- Issue #54 — landed `chart_metric_min_confidence` knob; forced to default 0.60 by this sensitivity.
- `src/extraction_v2/chart/metric_classifier.py::ChartMetricClassifier.classify`
- `tests/extraction_v2/chart/test_chart_fact_bridge_stage.py::test_emits_facts_for_classified_chart`

---

## 65. Secret-Leak Guard for Mis-Named Env File Duplicates

**Status**: Open
**Severity**: Medium
**Discovered**: 2026-04-21 (surfaced during branch-cleanup session)

### Problem

`.gitignore` matches `.env` by exact name only. During cleanup today a file literally named `" "` (single space) was found in the repo root — a 19-line subset of `.env` containing real production secrets (OpenAI key, Neon DB URL with creds, GitHub PAT, Brave/Gemini keys, `SECRET_KEY`, `FILINGS_API_KEY`). The file was untracked and never committed, but **`git check-ignore` confirms `.gitignore` does NOT protect it** — a `git add .` or `git add -A` would have caught it. Likely origin: a shell redirect typo like `cp .env " "`. No pre-commit hook scans staged blobs for secret patterns either.

### Next Steps

- Broaden `.gitignore` to cover env-variant filenames: add `.env*` and consider `!.env.template` / `!.env.example` allowlists.
- Add a `detect-private-key`-style pre-commit hook that scans staged content for known secret patterns: `sk-proj-*`, `github_pat_*`, `postgresql://*neon.tech`, `OPENAI_API_KEY=`, `SECRET_KEY=`, `FILINGS_API_KEY=`, R2 endpoint URLs.
- Evaluate `gitleaks` or `detect-secrets` as a belt-and-suspenders scan at commit-time and in CI.
- Audit `git log --all -S 'OPENAI_API_KEY='` / `sk-proj-` / `github_pat_` to confirm no secret was ever committed historically.

### Cross-References

- `.gitignore` line 2 (current `.env` entry)
- `.pre-commit-config.yaml` (hook location)

---

## Archive (Resolved Issues)

### Issue #1: Metric ID Mismatch Between Gold Standard and System

**Status**: Resolved (2026-03-16)

Gold standard CSV (`data/gold_standard/golden_set_251218.csv`) aligned to system taxonomy in `config/metric_keywords.yaml`. No remaining ID mismatches. See git log (2026-03-16) for full resolution details.

### Issue #6: FilingFetcher Downloads Directory Index Instead of Primary Document

**Status**: Resolved (2026-03-16)

`FilingFetcher` defaulted `sec_client` to `None` and guarded URL resolution behind `if self.sec_client:`, causing directory-index pages to be saved instead of actual filings. Fixed in `src/filing_fetcher/filing_fetcher.py` (lines 81, 295). 78 cloud-fetched filings need re-fetching on Render. See git log (2026-03-16) for full details.

### Issues #7 and #8: Test Deadlock and Connection Pool Exhaustion

**Status**: Resolved (2026-03-26)

Root cause: `DatabaseAdapter` had no `close()` method; test fixtures were session-scoped with no teardown and no connection pool, so every `get_connection()` call created a new TCP connection.

Fixes applied:
- Added `DatabaseAdapter.close()` to `src/infra/db.py`
- Converted `test_db_adapter` fixtures in `tests/integration/conftest.py` and `tests/integration/extraction/conftest.py` from `return` to `yield` with pool (`max_size=5`) and teardown
- Added `command: ["postgres", "-c", "max_connections=200"]` to `docker-compose.yml`

### Issue #3: Gold Standard Methodology Questions

**Status**: Resolved (2026-03-26)

Created `docs/GOLD_STANDARD_SPECIFICATION.md` covering: metric ID alignment, value normalization rules, chart vs text classification, period format, negative examples, and duplicate group handling.

### Issue #10: `test_candidate_generation_finds_active_consumers` — Root Cause Unclear

**Status**: Resolved-by-deletion (2026-04-19)

`tests/integration/test_gold_standard_coverage.py` was deleted in commit `03a8a20` ("refactor(v1): retire review_candidates + source_segments + suppressed_candidates"). The failing test no longer exists; pipeline-level recall for `cm_active_customers_total` remains 100% on Farfetch. See commit `03a8a20`.

### Issue #12: `test_image_crop.py` Pollutes Working Tree with Test PNGs

**Status**: Resolved (2026-04-18)

`make_png_in_data_dir` fixture added to `tests/unit/web/test_image_crop.py`; fixture writes the PNG, tracks the path, and deletes it on teardown. Working tree clean after suite run. See git log (2026-04-18) for details.

### Issue #13: V2 Metric Facts Identity Index Drift

**Status**: Resolved (2026-04-19)

`sql/33_fix_identity_index.sql` idempotently drops and recreates `idx_v2_metric_facts_identity_unique` with all 9 columns including `source_type`. Prod confirmed 9-col via direct `pg_indexes` read on 2026-04-19; local test DB and prod now agree. See `sql/33_fix_identity_index.sql` and `scripts/apply_migrations.py:68-74`.

### Issue #14: Farfetch LTV/CAC Dedup Collision on Layout Tables

**Status**: Resolved (2026-04-18)

Respectively-parser priority introduced in `value_binding.py::_bind_prose_cell`; `cohort_hint` field added to `BoundValue`; defensive 80-char prose guard in `_extract_cohort_def`. `cm_ltv_to_cac_ratio` R 33%→100%; `cm_ltv_to_cac_ratio_by_cohort` R 17%→50% (text FNs); Farfetch F1 +10.3pp. 6 regression tests added. See git log (2026-04-18).

### Issue #15: Chart Pipeline Env Bootstrap

**Status**: Resolved (2026-04-18)

`load_dotenv()` added to `src/gold_standard/v2_validator.py` `__main__` block. Chart stages now run automatically when `.env` contains `OPENAI_API_KEY`. See git log (2026-04-18).

### Issue #17: CAC Payback "Six Months" — Bare Word-Number Not Bound

**Status**: Resolved (2026-04-18)

`WORD_NUMBER_TIME_PATTERN` regex added to `value_binding.py`, gated to `TIME_UNIT_VALUED_METRICS = {"cm_cac_payback_period"}`; `_V1_SPELLED_OUT_OVERRIDE_METRICS` bypass added to `false_positive_filter.py`. `cm_cac_payback_period` 0%→100% F1 on Farfetch. 6 unit tests added. See git log (2026-04-18).

### Issue #18: Migration Checksum Mismatch on `sql/01_create_schema.sql`

**Status**: Resolved (2026-04-18)

Self-healed via V1 retirement merge (commit `03a8a20`); the gold-standard pytest fixtures that triggered the checksum guard were deleted along with the V1 review tables. No reconciliation action needed. See commit `03a8a20`.

### Issue #19: FN Diagnostic Classification Gaps

**Status**: Resolved (2026-04-18)

`dedup_collision` and `no_matching_binding` categories added to `src/gold_standard/v2_validator.py`; `wrong_period` restricted to post-dedup facts. 4 new unit tests in `tests/unit/gold_standard/test_v2_validator.py::TestDiagnosefalseNegative`. See git log (2026-04-18).

### Issue #20: `cm_gross_margin_by_cohort` Still 0% on Farfetch Despite Chart Pipeline Active

**Status**: Resolved (2026-04-18)

Four targeted changes in `src/extraction_v2/chart/`: `_cohort_gate` accepts ≥2 distinct years in `points[].x` + customer-type series names; `_metric_gate` fallback for empty `y_axis_label`; `_score_metric` nearby_text title fallback + structural bonus; `cohort_parser._parse_customer_type_regime` new regime. `cm_gross_margin_by_cohort` Farfetch 0%→100% F1 (9/9 rows); Tier 1 F1 +5.4pp overall. 7 regression tests added. See git log (2026-04-18).

### Issue #21: `v2_image_assets` Duplicates + Pending-Count Discrepancy (Maplebear S-1)

**Status**: Resolved (2026-04-18)

`sql/34_dedup_v2_image_assets.sql` collapses duplicate `(doc_id, filename)` groups and adds `UNIQUE (doc_id, filename)` constraint; `_persist_images_in_tx` upserts on `(doc_id, filename)` preserving stable `img_id`; `persist_pipeline_result` remaps in-memory `source_locator.img_id` before fact persistence. See `sql/34_dedup_v2_image_assets.sql` and git log (2026-04-18).

### Issue #22: No Reviewed-Filing Guard on Image Re-Extraction

**Status**: Resolved (2026-04-18)

Narrow image-side guard added to `_persist_images_in_tx` in `src/extraction_v2/persistence.py`: fires when a decided image would be re-classified from the visible set (`chart`/`table_image`/`unknown`) into the hidden set (`decorative`/`logo`/`signature`); `force=True` proceeds with structured warning. `ReviewedFilingError` gained optional `context` kwarg. 5 new tests in `tests/integration/extraction_v2/test_persistence_guard.py::TestGuardOnPersistImages`. See git log (2026-04-18).

### Issue #23: `v2_image_assets.segment_id` Is a Dead Column

**Status**: Resolved (2026-04-18)

`sql/35_drop_v2_image_assets_segment_id.sql` idempotently drops the column; `_persist_images_in_tx` cleaned up. See `sql/35_drop_v2_image_assets_segment_id.sql` and git log (2026-04-18).

### Issue #25: `scripts/migrate_image_ids_to_deterministic.py` Scope Is Confusing

**Status**: Resolved (2026-04-18)

Module-level docstring expanded to clarify the script only rewrites local gold-standard JSON files and does not modify the database. See git log (2026-04-18).

### Issue #26: Review UI — Lost SEC + Image Links for Investor Presentations

**Status**: Resolved (2026-04-19)

`sql/36_backfill_presentation_urls.sql` corrected 166 rows; `src/web/url_builders.py` introduced as single source for URL construction; `scripts/validate_database_urls.py` gained `--fail-on-errors` / `--document-type` and wired into CI. See `sql/36_backfill_presentation_urls.sql`, `src/web/url_builders.py`, and git log (2026-04-19).

### Issue #29: `cm_new_customers_acquired` Receives `2.71x` Chart Fact From Farfetch LTV/CAC Chart

**Status**: Resolved (2026-04-19)

`_rule_ratio_suffix_on_count_metric` added to `src/extraction_v2/stages/false_positive_filter.py`; rejects `N.NNx`/`N.NN×` raw values on count/currency/rate/time metrics. 6 unit tests. Farfetch GS confirms the `2.71x` FP eliminated. See git log (2026-04-19).

### Issue #30: 15 Filings With CIK / sec_html_url Mismatch

**Status**: Resolved (2026-04-19)

`scripts/audit_filing_url_mismatch.py` enumerated affected rows; `scripts/repair_filing_url_mismatch.py --path A --apply` corrected all 15 `sec_html_url` values. Apply log at `data/audit/issue_30_applied_20260419T210109Z.jsonl`. Latent cached-HTML residue tracked as Issue #43. See git log (2026-04-19).

### Issue #31: Audit Log Spams DNS Error in Test / Dev

**Status**: Resolved (2026-04-19)

Both async (`src/web/routes/review_unified.py:97-109`) and sync (`src/web/middleware.py:87-120`) audit-log paths downgrade `ERROR` to `DEBUG` when `TESTING=True`. Covered by `tests/unit/web/test_middleware.py::TestAuditLogFailureLogging`. See commit `366d9dd`.

### Issue #32: `src/shared/html_segmenter.py` Has 0% Test Coverage

**Status**: Resolved (2026-04-20)

Module deleted (2032 LOC) as dead code — zero production callers verified; smoke test also deleted. Coverage rose from 81.44% to 83.5%, enabling the #33 floor bump. Successor: `src/extraction_v2/stages/ingestion.py`. See git log `-- src/shared/html_segmenter.py`.

### Issue #33: Raise Coverage Threshold to 80% After Issue #32

**Status**: Resolved (2026-04-20)

`pyproject.toml` `[tool.coverage.report]` `fail_under` raised 75→80 in the same change as Issue #32; `.claude/rules/testing.md` updated to match. See git log (2026-04-20).

### Issue #36: `onboard_tickers.py populate` Has No `--limit`

**Status**: Resolved (2026-04-19)

`UniverseBuilder.build_universe` gained `limit: int | None = None` kwarg; `scripts/onboard_tickers.py populate --limit N` threads through. Covered by `tests/unit/universe/test_universe_builder.py::test_limit_stops_after_n_in_scope_upserts`. See commit `366d9dd`.

### Issue #37: `classify_first_time_issuer` Reports `True` for Non-S-1/F-1 Filers

**Status**: Resolved (2026-04-19)

`_process_filing` in `src/universe/universe_builder.py` gates `classify_first_time_issuer` on `filing.form_type in DEFAULT_FORM_TYPES_S1F1`; non-S-1/F-1 filings land with `is_first_time_issuer=NULL`. Covered by `tests/unit/universe/test_universe_builder.py::test_10k_filing_has_null_first_time_issuer`. See commit `366d9dd`.

### Issue #41: Review-UI Sticky Header Offset Mismatch + Narrow-Width Overlap

**Status**: Resolved (2026-04-19)

`--navbar-height: 48px` CSS custom property unifies sticky offsets in `src/web/static/css/review.css`; `.review-pill-row` flex-wrap prevents narrow-width badge overlap. Deployed Render build verified visually. See commit `366d9dd`.

### Issue #44: `audit_filing_url_mismatch.py` Classifier Over-Rotates on Legitimate Co-Registrant Sharing

**Status**: Resolved (2026-04-20)

`_classify_path` decision tree refined: `facts==0` short-circuits to Path A; `facts>0` + collision routes to new `B_coordinated` sub-path. `repair_filing_url_mismatch.py` warns on `B_coordinated` rows. 7 unit tests at `tests/unit/scripts/test_audit_filing_url_mismatch.py`. See git log (2026-04-20).

### Issue #45: `scripts/validate_database_urls.py` Missing `load_dotenv()`

**Status**: Resolved (2026-04-20)

`load_dotenv()` added before `DATABASE_URL` read; mirrors `scripts/apply_migrations.py:21` pattern. See git log (2026-04-20).

### Issue #46: `scripts/apply_all_migrations.py` Stale — Stops at Migration 31

**Status**: Resolved (2026-04-20)

`MIGRATION_ORDER` extended with migrations 32–38; `--dry-run` now reports 44 migrations; `check_unregistered_migrations` no longer aborts. Sync chosen over deletion (script referenced from 7 docs). See git log (2026-04-20).

### Issue #47: `data/audit/` Not Gitignored

**Status**: Resolved (2026-04-20)

`data/audit/` added to `.gitignore` (line 46) alongside peer `data/*` runtime entries. Verified via `git check-ignore -v`. See git log (2026-04-20).

### Issue #48: `image_crop` Endpoint Is Unauthenticated

**Status**: Resolved (2026-04-20)

`@require_api_key` decorator added to `image_crop` in `src/web/routes/review_unified.py`; `_verify_api_key()` module-level helper extracted from `register_api_auth` in `src/web/middleware.py`. Same-origin `Origin`/`Referer` bypass preserves embedded `<img>` loads from review pages. 5 auth tests in `tests/unit/web/test_image_crop.py::TestImageCropAuth`. See git log (2026-04-20) and `docs/architecture/image-storage.md`.

### Issue #56: `check_docs_sync.py --ci` Fails CI on Transitive-Import Warnings

**Status**: Resolved (2026-04-21)

`import_to_pkg` dict in `scripts/check_docs_sync.py` extended with `dateutil`, `botocore`, `PIL`; `README.md` updated with pipeline-stage class names and coverage line matching the `(\d+)%\s*overall` regex. `check_docs_sync.py --ci` now exits 0; PR #50 and all future PRs unblocked. See git log (2026-04-21).

### Issue #57: `unified_review.html` Missing Breadcrumb + Count Badges Broke 7 Playwright Tests

**Status**: Resolved (2026-04-21)

Bootstrap breadcrumb nav and `badge bg-success`/`badge bg-danger` accepted/rejected count spans added to `src/web/templates/unified_review.html`; 2 test selectors updated in `tests/ui/review.spec.js` (`.fact-metric-id` + `.fs-5.fw-bold`). All 151 UI tests pass. See git log (2026-04-21).

### Issue #42: `_download_missing_images` Writes Image Bytes Twice

**Status**: Resolved (2026-04-21)

`OCRExtractionStage._download_missing_images` no longer writes a second `pipeline/...` copy after `SECClient.fetch_image()` caches the bytes. New public `SECClient.get_image_cache_path` accessor; `asset.file_path` points at the SECClient cache key directly. `TestImageDownloading` updated. See commit `7848605`.

### Issue #50: No 401-Path Test Coverage for `api_unified_bp`

**Status**: Resolved (2026-04-21)

New `tests/unit/web/test_api_unified_auth.py` — 6 cases covering missing/wrong/correct key, query-arg + same-origin Referer bypass, and `API_KEY_REQUIRED`-without-`API_KEY` misconfig. Mirrors `TestImageCropAuth` shape. Target endpoint: `DELETE /api/v2/decisions/<decision_id>` with mocked DB. See commit `7848605`.

### Issue #51: Brittle Source-String Assertions in `test_persistence_sql.py`

**Status**: Resolved (2026-04-21)

4 grep-the-source tests in `test_persistence_sql.py` rewritten as behavioral mock-cursor assertions. `# fmt: skip` removed from `src/extraction_v2/persistence.py`; black reformatted the `or None` expression to its own line. Tests immune to future formatting changes. See commit `7848605`.

### Issue #52: `pg_dump` Version-Mismatch Silent Failure

**Status**: Resolved (2026-04-21)

New `scripts/check_pg_client_version.py` pre-flight that compares `pg_dump` major version against server major version and errors loudly on mismatch. `.claude/rules/infrastructure.md` gains a `### pg_dump client version` subsection documenting the PG16+ client requirement for Neon (PG15). Script confirmed the 14→15 mismatch on the reference machine. See commit `7848605`.

### Issue #54: Chart-Bridge Emits Low-Confidence Misbinds on Non-Tier-1 Charts

**Status**: Resolved (2026-04-21)

New `PipelineConfig.chart_metric_min_confidence` knob (Guard 6 on `ChartFactBridgeStage`). Default 0.60 matches the existing classification gate — no default behavior change — because Tier 1 `cm_balance_by_cohort` classifies at ~0.6024 and a 0.70 default would regress Tier 1 recall. Operators can tighten the knob during backfills to suppress weak top-match binds. 5 unit tests added as `TestGuard6MetricConfidenceFloor`. See commit `7848605` and companion Issue #64 for the boundary sensitivity follow-up.

---

## Change Log

- **2026-01-01**: Initial document created after VAL-1 validation
- **2026-01-01**: CAC payback period issue resolved (moved to "FIXED" section)
- **2026-03-16**: Added Issue #6 — FilingFetcher directory index bug
- **2026-03-16**: Issue #6 resolved — default SECClient creation + removed null guard; 78 cloud-fetched files need re-fetch
- **2026-03-16**: Issue #1 resolved — gold standard CSV updated to align with system taxonomy; no metric ID mismatches remain
- **2026-03-17**: Archived resolved Issues #1 and #6; updated Farfetch contributing factors to reflect resolutions
- **2026-03-19**: Added Issues #6–#8: Farfetch gold standard test failures, extraction pipeline deadlock, connection pool exhaustion
- **2026-03-19**: Issue #9 partially resolved — fresh mode validation eliminates DB dependency; `*.dump` added to `.gitignore`
- **2026-03-26**: Issues #7 and #8 resolved — DatabaseAdapter.close(), pool + yield teardown in test fixtures, max_connections=200
- **2026-03-26**: Issue #3 resolved — created docs/GOLD_STANDARD_SPECIFICATION.md
- **2026-03-26**: Issue #11 partially resolved — fixed wrong metric IDs and broken TestKeywordPatterns imports; 11/12 tests pass
- **2026-03-26**: Issue #2 partially resolved — fixed extract_fresh_batch company_names bug; recall gap requires keyword work
- **2026-03-26**: Added Issue #10 — CMS-1 suppression assigns Active Consumers to cm_customers_period_end instead of cm_active_customers_total
- **2026-03-27**: Removed duplicate main-body sections for Issues #3, #7, #8 — already archived; stale "Open"/"Needs Discussion" statuses were conflicting with archive entries
- **2026-04-07**: Removed orphaned summary table rows for Issues #7 and #8 (already in archive, no main body section); added Issue #10 cross-reference to Issue #2 remaining gaps
- **2026-04-18**: Added Issue #12 — `test_image_crop.py` writes PNGs into real `data/` dir with no teardown
- **2026-04-18**: Issue #12 resolved — `make_png_in_data_dir` fixture added; cleans up PNGs on teardown
- **2026-04-18**: Added Issue #13 — V2 metric facts identity index drift (live DB 8 columns, code + `sql/23` expect 9); documented during `docs/architecture/data-model.md` rewrite
- **2026-04-18**: Issue #2 re-diagnosed; re-measured Farfetch P=50% R=37% F1=42% via v2_validator; stale 12.5% figure replaced; umbrella superseded by sub-issues #14–#19; Take Rate bullet removed (metric was retired 2026-01-02); "CAC Payback FIXED" claim corrected (partial — see #17)
- **2026-04-18**: Issue #10 re-scoped — original CMS-1 suppression hypothesis disproven (`cm_customers_period_end` has no "Active Consumers" pattern; `cm_active_customers_total` recall is 100% at pipeline layer); real root cause for unit-test failure is TBD
- **2026-04-18**: Added Issue #14 — Farfetch LTV/CAC dedup collision on layout-table misclassification (4 T1 FNs)
- **2026-04-18**: Added Issue #15 — chart pipeline blocked locally by missing OPENAI_API_KEY
- **2026-04-18**: Added Issue #16 — Farfetch precision drag from table-scale + period attribution
- **2026-04-18**: Added Issue #17 — CAC payback bare word-number + time unit not bound
- **2026-04-18**: Added Issue #18 — migration checksum mismatch on `sql/01_create_schema.sql` (blocks pytest gold standard; v2_validator module workaround)
- **2026-04-18**: Added Issue #19 — FN diagnostic misclassified 3 of 3 categories investigated during 2026-04-18 Farfetch diagnosis
- **2026-04-18**: Issue #18 resolved — self-healed via V1 retirement merge (pytest gold_standard tests deleted in commit `03a8a20`); no reconciliation action needed
- **2026-04-18**: Issue #15 resolved — added `load_dotenv()` to `v2_validator.py` `__main__`; chart stages now run automatically when `.env` contains `OPENAI_API_KEY`
- **2026-04-18**: V2 baseline refreshed with chart pipeline active (P=64.1% R=45.6% F1=53.3%; Tier 1 F1 +1.4pp vs prior)
- **2026-04-18**: Added Issue #20 — `cm_gross_margin_by_cohort` still 0% on Farfetch despite chart extraction running end-to-end; 2026-04-17 JSON-mode fix did not lift this metric
- **2026-04-18**: Issue #13 — `sql/33_fix_identity_index.sql` prepared; root cause diagnosed as pg_dump snapshot restore overwriting the sql/23 DDL after migration was recorded; secondary finding: `_persist_facts_in_tx` in-memory dedup key (persistence.py:710–719) also omits `source_type` (tracked, not fixed here)
- **2026-04-18**: Issue #17 resolved — added `WORD_NUMBER_TIME_PATTERN` in `value_binding.py` gated to `TIME_UNIT_VALUED_METRICS={"cm_cac_payback_period"}`; added `_V1_SPELLED_OUT_OVERRIDE_METRICS` override in `false_positive_filter.py`; `cm_cac_payback_period` 0% → 100% F1 on Farfetch. No Tier 1 regression (F1 +0.4pp)
- **2026-04-18**: Issue #19 resolved — added `dedup_collision` + `no_matching_binding` FN diagnostic categories; `wrong_period` restricted to post-dedup facts; 4 new unit tests
- **2026-04-18**: V2 baseline refreshed post-#17/#19 (P=64.6% R=45.9% F1=53.7%; Tier 1 F1 unchanged at 55.6%)
- **2026-04-18**: Issue #14 resolved — added `cohort_hint` field to `BoundValue`; `_bind_prose_cell` prefers `detect_respectively_pattern` at min_confidence≥0.8 when "respectively" is present; `_bind_respectively_pattern` sets `cohort_hint` (and empties `period_hint`) when cell text mentions "cohort(s)"; `_construct_fact` prefers `bv.cohort_hint` over evidence scan; defensive 80-char prose guard in `_extract_cohort_def`. Farfetch: `cm_ltv_to_cac_ratio` R 33%→100%; `cm_ltv_to_cac_ratio_by_cohort` R 17%→50% (text); Farfetch F1 +10.3pp. Overall F1 +1.0pp; Tier 1 F1 55.6%→57.3%; no regressions
- **2026-04-18**: Issue #20 resolved — diagnosed via DB inspection: OCR for FTCH `g607688g09d00.jpg` returned valid 9-value chart data at confidence 0.9 but with empty title/axes; classifier + CohortParser both relied on signals the OCR output lacked. Fix (all in `src/extraction_v2/chart/`): `metric_classifier._cohort_gate` accepts ≥2 distinct years in `points[].x` + customer-type series names; `_metric_gate(cm_gross_margin_by_cohort)` fallback for empty y_axis (requires margin/contribution keyword + `%` signal); `_score_metric` nearby_text title fallback + +5.5 raw structural bonus (%/years/customer-type trio); `cohort_parser._parse_customer_type_regime` for year-in-point.x + customer-type-in-series.name shape. `cm_gross_margin_by_cohort` Farfetch 0% → 100% F1 (9/9 rows). Overall F1 53.7%→56.9% (+3.2pp); Tier 1 F1 55.6%→61.0% (+5.4pp); no regressions
- **2026-04-18**: Added Issue #21 — `v2_image_assets` duplicate rows on re-extraction (random UUID upsert key) + asymmetric dedup in progress counter vs. review-list query caused 220 pending / 0 queue discrepancy on Maplebear S-1
- **2026-04-18**: Issue #21 resolved — `sql/34_dedup_v2_image_assets.sql` collapses duplicates + adds UNIQUE (doc_id, filename); `_persist_images_in_tx` upserts on (doc_id, filename) preserving stable img_id; `persist_pipeline_result` remaps in-memory fact source_locator.img_id before fact insert
- **2026-04-18**: Added Issues #22–#25 — out-of-scope follow-ups surfaced during Issue #21 investigation: image re-extraction guard gap, dead segment_id column, img_id referential integrity, migrate_image_ids script scope confusion
- **2026-04-18**: Issue #23 resolved — `sql/35_drop_v2_image_assets_segment_id.sql` drops the dead column (applied to Neon prod + local test DB); `_persist_images_in_tx` in `src/extraction_v2/persistence.py` no longer references it; migration registered in `scripts/apply_migrations.py`
- **2026-04-18**: Issue #22 resolved — `_persist_images_in_tx` raises `ReviewedFilingError(context="image classifications")` when a decided image would be re-classified from the visible set (`chart`/`table_image`/`unknown`) into the hidden set (`decorative`/`logo`/`signature`); `force=True` proceeds with a structured warning; `ReviewedFilingError.__init__` gained an optional `context` kwarg (default `"facts"` preserves prior message shape); 5 new tests in `TestGuardOnPersistImages`; `_persist_images_in_tx` signature gains keyword-only `force: bool = False` (backwards compatible; `persist_pipeline_result` threads through)
- **2026-04-18**: Issue #25 resolved — expanded docstring on `scripts/migrate_image_ids_to_deterministic.py` to clarify the script only rewrites local gold-standard JSON files and does not modify the database
- **2026-04-19**: Issue #10 resolved-by-deletion — `tests/integration/test_gold_standard_coverage.py` was deleted in commit `03a8a20` (V1 retirement); re-diagnosis is no longer actionable against a non-existent test
- **2026-04-19**: Issue #9 scope clarified — the "remaining" follow-up is NOT a simple `companies.cik` column update. Filing 32 in the local DB contains RMR Group content, not Snap content; a correct fix requires re-ingesting the actual Snap S-1/A (accession `0001193125-17-056992`) as a separate workstream. Expanded inline comment in `scripts/gi3_richness_analysis.py:41-46` to match
- **2026-04-19**: Issue #24 diagnostic script added — `scripts/check_image_referential_integrity.py` scans `v2_metric_facts.source_locator.img_id` against `v2_image_assets`, reports orphans, exits non-zero when any found (suitable for nightly cron). Does not promote `img_id` to a FK column — that remains open
- **2026-04-19**: Added Issue #27 — 3 Images Tab assertions in `tests/ui/review.spec.js` fail pre-existing against the current mock server; latent since the suite never ran in CI. Commit `413b386` added a `ui-e2e` CI job that will now surface them on every PR
- **2026-04-19**: Added Issue #28 — Playwright mock server duplicates production template context; Apr 17 breakage (commit `3e398fd`) was the symptom class. Commit `413b386` added `tests/ui/smoke.spec.js` as a fast pre-flight to catch render-time failures, but the underlying duplicated-contract coupling remains
- **2026-04-19**: Issue #24 diagnostic baseline recorded — `scripts/check_image_referential_integrity.py` against the local dev DB reports 9 orphan facts across 4 docs (1546: 4, 1545: 2, 1551: 2, 1539: 1). Historical facts predating the `sql/34` dedup migration. Prod not yet scanned; cleanup strategy still open
- **2026-04-19**: Added Issue #29 — `cm_new_customers_acquired` receives `2.71x` chart fact from Farfetch LTV/CAC tenure chart `g607688g54x53.jpg`; 1 FP per Farfetch baseline. Filed as its own issue after originally being noted in Issue #20 "Out of scope"
- **2026-04-19**: Issue #31 partial resolution — `review_unified.py:97-109` captures `current_app.config["TESTING"]` into the worker-thread closure and logs `DEBUG` instead of `ERROR` when `TESTING=True`; production path unchanged. Related `src/web/middleware.py:114` synchronous path has the same pattern but was intentionally left for a separate fix (Issue #31 explicitly named only the async path)
- **2026-04-19**: Issue #27 partial resolution — `review.spec.js:965` passes after `img_id` added to `MOCK_IMAGE_CANDIDATE_PENDING` / `MOCK_IMAGE_CANDIDATE_REVIEWED` in `tests/ui/test_server.py`; `review.spec.js:1037` (`.keyword-badge`) and `review.spec.js:1054` ("Image 1 of 2") are stale assertions (no matching template elements) and now `test.skip` with TODO(KNOWN_ISSUES #27). Full Playwright suite 142 pass / 2 skip / 0 fail locally
- **2026-04-19**: Issue #13 docs reconciled — local test DB verified 9-col (includes `source_type`); `scripts/apply_migrations.py` comment asserts prod already applied out-of-band; this doc previously said "pending prod apply". Prod `pg_indexes` query still needed to settle the contradiction
- **2026-04-19**: Issue #29 resolved — root cause was NOT candidate-level (yaml exclusion didn't help: chart combined_text was just `'2015 Cohort 2016 Cohort 2017 Cohort'`, no customer-type keywords). The mis-classification entered via `_scan_chart`'s nearby_text second pass (Farfetch prose legitimately mentions "new Marketplace consumers" near the LTV/CAC chart); value binding then attached the chart point.label `2.71x` to the candidate. Fix: added `_rule_ratio_suffix_on_count_metric` in `false_positive_filter.py` mirroring the existing `_rule_revenue_concentration_ratio_suffix`, rejecting `N.NNx`/`N.NN×` raw values bound to count/currency/rate/time metrics (whitelists `cm_ltv_to_cac_ratio` + `cm_ltv_to_cac_ratio_by_cohort` implicitly). 6 new unit tests. Farfetch GS confirms the `2.71x` FP is eliminated; total Farfetch FP count unchanged at 12 because a pre-existing sibling FP (`54%` percent-on-count with `unit=COUNT`) was previously tiebroken-away by `2.71x` and now surfaces — separate, pre-existing issue, not fixed here
- **2026-04-19**: Issue #24 extended — `scripts/check_image_referential_integrity.py` now reports three classes (null-img_id on chart facts [blocking], orphaned img_id refs [warn], file_path outside data/ or missing on disk [warn]) and runs in the integration-tests CI job. `tests/unit/extraction_v2/test_chart_fact_bridge_invariants.py` locks the Class (A) invariant. Commit `d1430d9`
- **2026-04-19**: Added Issue #34 — `v2_image_assets.file_path` rooted in macOS TMPDIR on the local extraction host; 158/165 rows outside `data/`, 50/165 absent on disk. Dominant root cause behind the Box Inc S-1/A missing-Chart-Evidence case surfaced during the commit-`d1430d9` investigation
- **2026-04-19**: Added Issue #35 — 38 filings have chart images but zero `source_type='chart'` facts, consistent with pre-2026-04-17 chart-OCR JSON failures. Backfill via `batch_v2_extraction.py --force-reextract` pending Issue #34 fix
- **2026-04-19**: Added Issue #41 — review-UI sticky-header offset mismatch (`.sticky-top-below-nav` at 70px vs new `.review-sticky-header` at 56px) + narrow-width pill overlap with "Next filing F" button unverified. Opened during review-UI sticky compact top-matter work, commit `ba35424`
- **2026-04-19**: Issue #34 Phase 1 resolved — `src/infra/paths.py::image_cache_dir()` helper introduced (honors `IMAGE_CACHE_DIR` env override, defaults under `data/image_cache/`); `src/extraction_v2/stages/ocr_extraction.py` swapped from `tempfile.gettempdir()` to the helper with a collision-safe `pipeline/<cik>/<accession>/<filename>` layout; `data/image_cache/` added to `.gitignore`; tests in `tests/unit/infra/test_paths.py` + class-scoped autouse fixture in `tests/unit/extraction_v2/test_image_pipeline_integration.py::TestImageDownloading` fence `IMAGE_CACHE_DIR` to `tmp_path`. Phase 3 (Render persistent disk vs. re-fetch-on-miss) is a separate decision; prod remains ephemeral until chosen. Full suite: 3591 pass, 67 skip. Issue #35 is now unblocked on local dev
- **2026-04-19**: Issue #13 resolved — prod `pg_indexes` read confirms `idx_v2_metric_facts_identity_unique` has all 9 columns (including `source_type`). Local test DB and prod now agree; `scripts/apply_migrations.py:68-74` comment was accurate and stays in place
- **2026-04-19**: Issue #31 fully resolved — `src/web/middleware.py:87-120` synchronous audit-log path now mirrors the async pattern (captures `TESTING`, downgrades except-clause log to DEBUG when true). New `tests/unit/web/test_middleware.py::TestAuditLogFailureLogging` covers both cases. Commit `366d9dd`
- **2026-04-19**: Issue #36 resolved — `UniverseBuilder.build_universe` gained optional `limit: int | None` kwarg; `scripts/onboard_tickers.py populate --limit N` threads through. Default `None` preserves unbounded behaviour; regression test at `tests/unit/universe/test_universe_builder.py::test_limit_stops_after_n_in_scope_upserts`. Commit `366d9dd`
- **2026-04-19**: Issue #37 resolved — `_process_filing` in `src/universe/universe_builder.py` gates `classify_first_time_issuer` on `filing.form_type in DEFAULT_FORM_TYPES_S1F1`; non-applicable filings land with `is_first_time_issuer=NULL` and `fti_method="not_applicable"`. Mirror of the existing SPAC-SGML gate at line 163. Covered by `tests/unit/universe/test_universe_builder.py::test_10k_filing_has_null_first_time_issuer`. Commit `366d9dd`
- **2026-04-19**: Issue #41 resolved — `--navbar-height: 48px` CSS custom property in `src/web/static/css/review.css` unifies sticky offsets; `.navbar.sticky-top` padding-y compacted to 0.25rem; `.review-pill-row` flex-wrap class on the `unified_review.html:58` stat-pill row. Separately, `accepted`, `rejected`, and `img reviewed` badges dropped to reduce horizontal load; badge font-size shrunk to 0.7rem; sticky-header vertical padding trimmed to absorb container `mt-4`. Deployed Render build verified visually. Commit `366d9dd`
- **2026-04-20**: Added Issue #46 — `scripts/apply_all_migrations.py` `MIGRATION_ORDER` list stops at 31 and its unregistered-guard aborts on files 32-38; surfaced during analytics-UI phase 1 (sql/37 + sql/38) audit. Canonical runner is `scripts/apply_migrations.py`
- **2026-04-20**: Added Issue #47 — `data/audit/` runtime JSONL output is untracked but not gitignored; peer `data/*` subpaths are. Surfaced during analytics-UI phase 1 pre-commit `git status` review
- **2026-04-20**: Issue #44 resolved — `_classify_path` in `scripts/audit_filing_url_mismatch.py` now implements the four-outcome decision tree from the original Next Steps: `facts==0` short-circuits to Path A (eliminates Spectrum Brands false-positive Path C), `facts>0` + accession/storage collision routes to new `B_coordinated` sub-path. `scripts/repair_filing_url_mismatch.py::_eligible_rows` warns once per invocation when `B_coordinated` rows are present so they aren't silently dropped from existing A/B runs. 7 unit tests at `tests/unit/scripts/test_audit_filing_url_mismatch.py` cover every branch (loaded via `importlib.util` to avoid `scripts/__init__.py`)
- **2026-04-20**: Issue #45 resolved — `from dotenv import load_dotenv` + `load_dotenv()` added to `scripts/validate_database_urls.py` ahead of the `DATABASE_URL` read; mirrors `scripts/apply_migrations.py:21`. Existing fallback / error path retained for the case where `.env` has no `DATABASE_URL`
- **2026-04-20**: Issue #46 resolved — `MIGRATION_ORDER` in `scripts/apply_all_migrations.py` extended with `32_add_detected_keywords_to_v2_image_assets.sql`, `33_fix_identity_index.sql`, `34_dedup_v2_image_assets.sql`, `35_drop_v2_image_assets_segment_id.sql`, `36_backfill_presentation_urls.sql`, `37_create_analytics_role.sql`, `38_create_analytics_views.sql`. `--dry-run` now reports 44 migrations (31 pre-existing + 7 new); `check_unregistered_migrations` no longer aborts. Sync rather than delete (script still referenced from 7 docs); sql/33 included for fresh-DB-from-scratch semantics — migration is explicitly idempotent
- **2026-04-20**: Issue #47 resolved — `data/audit/` added to `.gitignore` line 46 alongside peer `data/*` runtime ignores (`data/filings/`, `data/image_cache/`). Verified via `git check-ignore -v`
- **2026-04-21**: Archive cleanup — collapsed 29 fully-resolved issues (#10, #12, #13, #14, #15, #17, #18, #19, #20, #21, #22, #23, #25, #26, #29, #30, #31, #32, #33, #36, #37, #41, #44, #45, #46, #47, #48, #56, #57) from main body into Archive section; rewrote Summary table to foreground open items; removed resolved rows from Summary table. Issue #11 cross-reference to #10 updated to point to archive entry.
- **2026-04-21**: Five-issue follow-up bundle landed in commit `7848605` — resolved #42 (double image-write collapsed via public `SECClient.get_image_cache_path`), #50 (new `tests/unit/web/test_api_unified_auth.py`), #51 (behavioral mock-cursor rewrite; `# fmt: skip` removed), #52 (new `scripts/check_pg_client_version.py` pre-flight + infrastructure.md doc section), #54 (new `chart_metric_min_confidence` knob with default 0.60 to avoid Tier 1 regression). Archive entries added. #64 opened — chart classifier Tier 1 boundary sensitivity: HOOD `cm_balance_by_cohort` scores 0.6024 (0.0024 above gate); surfaced while forcing #54's default down from the originally-proposed 0.70. (Renumbered from an earlier working #58 after merge from origin/main revealed issues #58–#63 had been claimed by the Wave B/C/D batch-ingest-ui follow-ups.)
