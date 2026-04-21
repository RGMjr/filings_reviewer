# Known Issues and Future Improvements

This document tracks known issues, limitations, and planned improvements identified during extraction system development.

**Last Updated**: 2026-04-20 (#46 opened for stale `apply_all_migrations.py`; #47 opened for `data/audit/` not gitignored; #34 Phase 3 resolved — ImageStorage abstraction + Cloudflare R2 backend live; `v2_image_assets.file_path` now stores opaque storage keys validated via `validate_key()`; 7 call sites migrated; #35 fully unblocked — chart-fact backfill viable on both dev and prod)

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

### Remaining (Issue #10)

`test_candidate_generation_finds_active_consumers` still fails due to CMS-1 cross-metric suppression.
The "Active Consumers" keyword matches both `cm_active_customers_total` and `cm_customers_period_end`;
the CMS-1 tie-breaker assigns it to `cm_customers_period_end`. The gold standard expects
`cm_active_customers_total`. Resolving this requires an extraction logic decision — see Issue #10 below.

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

## 46. `scripts/apply_all_migrations.py` Stale — Stops at Migration 31

**Status**: Open
**Severity**: Low
**Discovered**: 2026-04-20

### Problem

`scripts/apply_all_migrations.py` maintains its own `MIGRATION_ORDER` list that
ends at `31_drop_v1_review_tables.sql`. It also runs a
`check_unregistered_migrations` guard that aborts with an error if any `sql/*.sql`
file is missing from the list. That means anyone invoking this variant today
will hit a confusing failure because files 32–38 are unregistered there, while
the canonical runner (`scripts/apply_migrations.py`) handles them correctly.

### Next Steps

- Either bring `apply_all_migrations.py` into sync with `apply_migrations.py`
  and keep both in lockstep, or
- Delete `apply_all_migrations.py` entirely if the canonical runner is
  sufficient. The two scripts overlap substantially in behavior.

---

## 47. `data/audit/` Not Gitignored

**Status**: Open
**Severity**: Low
**Discovered**: 2026-04-20

### Problem

Runtime audit output (e.g. `data/audit/issue_30_applied_*.jsonl`) accumulates
in the working tree as untracked files. Other runtime subpaths under `data/`
are already listed in `.gitignore` (`data/filings/`, `data/image_cache/`,
`data/llm_cache.db`, etc.), but `data/audit/` was missed.

### Next Steps

- Add `data/audit/` to `.gitignore` alongside the existing `data/*` entries.
- Confirm no historical `data/audit/` contents are expected to be versioned.

---

## Summary

| Issue | Status | Priority | Effort | Impact |
|-------|--------|----------|--------|--------|
| Low Farfetch Recall (Issue #2) | Re-diagnosed umbrella | Medium | — | Superseded by sub-issues #14–#19; P=50% R=37% F1=42% on 2026-04-18 |
| Gold Standard Methodology | Resolved | — | — | Spec doc created |
| Spelled-Out Number Limits | Open | Low | High | Edge case coverage |
| Revenue Synonym Gating | Monitor | N/A | N/A | Working as designed |
| Gold Standard Coverage Tests (Issue #11) | Partially resolved | Low | Medium | 11/12 pass; 1 remaining (now linked to Issue #10 re-scope) |
| Snap Filing Mislabeled (Issue #9) | Partially resolved | Low | Low | Snap not in gold standard; validation DB no longer required |
| `test_candidate_generation_finds_active_consumers` (Issue #10) | Resolved (2026-04-19) | — | — | Resolved-by-deletion in commit `03a8a20` (V1 retirement); test module retired |
| `test_image_crop.py` pollutes `data/` (Issue #12) | Resolved (2026-04-18) | — | — | `make_png_in_data_dir` fixture cleans up on teardown |
| V2 metric facts identity index drift (Issue #13) | Resolved (2026-04-19) | — | — | Prod `pg_indexes` read confirms 9-col (including `source_type`); local + prod now agree; `apply_migrations.py:68-74` comment remains accurate |
| Farfetch LTV/CAC dedup collision (Issue #14) | Resolved (2026-04-18) | — | — | cm_ltv_to_cac_ratio 33%→100%; cm_ltv_to_cac_ratio_by_cohort 17%→50%; Farfetch F1 +10.3pp |
| Chart pipeline env bootstrap (Issue #15) | Resolved (2026-04-18) | — | — | `load_dotenv()` added to validator's `__main__` |
| `cm_gross_margin_by_cohort` still 0% despite chart pipeline (Issue #20) | Resolved (2026-04-18) | — | — | Classifier+parser gates relaxed for customer-type/year-in-point.x shape; 0% → 100% F1 on Farfetch; Tier 1 overall +5.4pp |
| `v2_image_assets` duplicates + pending-count discrepancy — Maplebear S-1 (Issue #21) | Resolved (2026-04-18) | — | — | sql/34 dedup migration + stable img_id upsert (ON CONFLICT (doc_id, filename)) + in-memory fact source_locator remap |
| No reviewed-filing guard on image re-extraction (Issue #22) | Resolved (2026-04-18) | — | — | `_persist_images_in_tx` raises `ReviewedFilingError(context="image classifications")` on visible→hidden re-classification |
| `v2_image_assets.segment_id` dead column (Issue #23) | Resolved (2026-04-18) | — | — | sql/35 drops column; persistence.py cleaned up |
| `v2_metric_facts.source_locator.img_id` no referential integrity (Issue #24) | Open | Low | Medium | Diagnostic script added 2026-04-19; 9 orphan facts in local DB across 4 docs; cleanup + FK promotion still open |
| `cm_new_customers_acquired` 2.71x chart FP on Farfetch LTV/CAC (Issue #29) | Resolved (2026-04-19) | Low | Low | New `_rule_ratio_suffix_on_count_metric` in FP filter; 6 regression tests; Farfetch GS confirms `2.71x` FP eliminated |
| `scripts/migrate_image_ids_to_deterministic.py` scope confusion (Issue #25) | Resolved (2026-04-18) | — | — | Docstring expanded to clarify JSON-only scope |
| Farfetch precision drag — table-scale + period (Issue #16) | Open | Low | Medium | 9 FPs across Active Consumers + Purchase Transactions (doesn't block recall) |
| CAC payback "six months" not bound (Issue #17) | Resolved (2026-04-18) | — | — | Added `WORD_NUMBER_TIME_PATTERN` gated to time-valued metrics; cm_cac_payback_period 0% → 100% F1 |
| Migration checksum mismatch — `sql/01_create_schema.sql` (Issue #18) | Resolved (2026-04-18) | — | — | Self-healed via V1 retirement merge |
| FN diagnostic classification gaps (Issue #19) | Resolved (2026-04-18) | — | — | Added `dedup_collision` + `no_matching_binding` categories; `wrong_period` restricted to post-dedup |
| Images Tab Playwright assertions fail (Issue #27) | Partially resolved (2026-04-19) | Low | Low | 1 test fixed via `img_id` mock update; 2 stale assertions `test.skip`-ed with TODOs; CI green |
| Mock-server / template-contract coupling (Issue #28) | Open | Low | Medium | Smoke spec catches the symptom class; root coupling between `tests/ui/test_server.py` and production templates remains |
| Audit log DNS error in tests (Issue #31) | Resolved (2026-04-19) | — | — | Both async (`review_unified.py`) and sync (`middleware.py`) paths log DEBUG under `TESTING=True`; commit `366d9dd` closes the sync-path gap |
| Image cache rooted in TMPDIR (Issue #34) | Resolved (Phases 1 + 3, 2026-04-19) | Medium | — | `ImageStorage` abstraction + Cloudflare R2 backend; `v2_image_assets.file_path` stores opaque storage keys; validated via `validate_key()`; 7 call sites migrated |
| Pre-2026-04-17 filings missing chart facts (Issue #35) | Unblocked (2026-04-19) | Medium | Medium | `batch_v2_extraction.py --force-reextract` now viable on both dev and prod; 38 filings to queue |
| `populate` has no `--limit` (Issue #36) | Resolved (2026-04-19) | — | — | `build_universe(limit=)` + `populate --limit N` land in commit `366d9dd`; regression-guarded |
| `classify_first_time_issuer=True` for 10-K filers (Issue #37) | Resolved (2026-04-19) | — | — | `_process_filing` gates the classifier to S-1/F-1; non-applicable filings land with `is_first_time_issuer=NULL`; commit `366d9dd` |
| `v2_metric_facts.doc_id` misleading name (Issue #38) | Open | Low | Medium | BIGINT referencing `filings.filing_id` despite name; cost one prod SQL failure (commit `c353e83`); rename needs migration + caller sweep |
| `is_in_scope_phase1` misnomer post-10-K (Issue #39) | Open | Low | Medium | Column name implies "in active universe" but means "Phase 1 IPO candidate"; confusing with 10-Ks present; needs rename or form-aware companion column |
| 10-K/A supersession semantics undefined (Issue #40) | Open | Low | Low | `mark_superseded_filings()` is S-1/F-1-scoped; both 10-K and 10-K/A survive; analytic intent not validated with stakeholders |
| Review-UI sticky header offset mismatch + narrow-width pill overlap (Issue #41) | Resolved (2026-04-19) | — | — | `--navbar-height: 48px`, compact navbar, `.review-pill-row` flex-wrap; three badges dropped; deployed Render build verified visually |
| `_download_missing_images` writes bytes twice (Issue #42) | Open | Low | Low | SECClient already caches the fetched bytes; pipeline writes a second copy that `asset.file_path` references. Point `file_path` at SECClient cache + drop pipeline write |
| `apply_all_migrations.py` stale (Issue #46) | Open | Low | Low | MIGRATION_ORDER list stops at 31; unregistered-guard aborts on files 32-38. Canonical runner is `apply_migrations.py`; resolve by syncing or deleting the stale variant |
| `data/audit/` not gitignored (Issue #47) | Open | Low | Low | Runtime JSONL audit output accumulates as untracked files; peer `data/*` subpaths are already gitignored. One-line `.gitignore` addition |

---

## 12. `test_image_crop.py` Pollutes Working Tree with Test PNGs

**Status**: ✅ Resolved (2026-04-18)
**Severity**: Low (test hygiene; no runtime impact)
**Discovered**: 2026-04-17

### Problem

`tests/unit/web/test_image_crop.py` wrote `data/test_chart.png`, `data/test_chart2.png`, and
`data/test_chart3.png` into the real project `data/` directory on every run, leaving them
untracked in the working tree after the suite finished.

### Root Cause

The `/v2/review/image_crop/` endpoint has a security guard that resolves image paths relative to
`<project_root>/data/`. To satisfy that guard the tests wrote their fixture PNGs to the real
`data/` dir (not `tmp_path`), and there was no teardown.

### Resolution

Added a `make_png_in_data_dir` fixture in `tests/unit/web/test_image_crop.py` that writes the
PNG, tracks the path, and deletes it on teardown. The three `TestImageCropSuccess` tests now use
the fixture instead of calling `_make_test_png(data_dir, ...)` directly. Verified: after
`pytest tests/unit/web/test_image_crop.py` the working tree is clean.

---

## 13. V2 Metric Facts Identity Index Drift

**Status**: ✅ Resolved (2026-04-19) — prod verified 9-col
**Severity**: Low (application-layer dedup in `MetricFact.identity_tuple()` still distinguishes `source_type`; no observed duplicate-row incidents)
**Discovered**: 2026-04-18
**Resolved**: 2026-04-19

### Problem

`sql/23_chart_source_dedup.sql` drops and recreates `idx_v2_metric_facts_identity_unique` as a 9-column partial UNIQUE index including `source_type`. The live database index has only 8 columns (no `source_type`). `MetricFact.identity_tuple()` in `src/extraction_v2/models.py` returns a 9-tuple with `source_type` at position 9.

`23_chart_source_dedup.sql` is recorded in `schema_migrations`, so the migration ran at least once — but the live DDL does not reflect the 9-column shape.

### Verified evidence (2026-04-18)

```bash
source .env && psql "$DATABASE_URL" -c \
  "SELECT indexdef FROM pg_indexes WHERE indexname='idx_v2_metric_facts_identity_unique'"
# Returns: CREATE UNIQUE INDEX ... (doc_id, canonical_metric_id,
#   COALESCE(period_start,'1900-01-01'), COALESCE(period_end,'1900-01-01'),
#   unit, scope, COALESCE(cohort_def,''), COALESCE(customer_type,''))
# — 8 columns, source_type absent.

source .env && psql "$DATABASE_URL" -c \
  "SELECT id FROM schema_migrations WHERE id='23_chart_source_dedup.sql'"
# Returns 1 row — migration is recorded as applied.
```

### Impact

- **DB layer:** a chart-sourced fact and a text-sourced fact for the same `(doc_id, metric, period, cohort, customer_type, unit, scope)` slot would be treated as conflicting rows by the 8-column index, even though the application treats them as distinct via `source_type`.
- **Application layer:** `MetricFact.identity_tuple()` includes `source_type`, so in-memory deduplication preserves CHART + TEXT/TABLE as separate facts. Persistence upserts via `ON CONFLICT DO UPDATE` against the 8-column index — a CHART fact may therefore overwrite a prior TEXT fact (or vice versa) on the same slot.
- **Observed incidents:** none to date.

### Root Cause (2026-04-18)

Migration 23 ran at least once (recorded in `schema_migrations`), but the live DB index reverted to 8 columns. Best hypothesis: the DB was recreated from a pg_dump schema snapshot that predated sql/23, so the `schema_migrations` ledger recorded the migration as applied while the actual DDL was replaced with the older snapshot shape. Because `schema_migrations` tracks applied/checksum per file rather than inspecting live DDL, the drift went undetected.

Secondary finding: `_persist_facts_in_tx` in `src/extraction_v2/persistence.py` (lines 706–722) uses a delete-then-insert pattern (not `ON CONFLICT`), so no live silent-overwrite occurs per pipeline run. However, the Python-side in-memory dedup key (lines 710–719) also omits `source_type`, meaning two facts differing only by `source_type` could silently collapse within a single run. This is a separate issue not addressed here.

### Resolution

`sql/33_fix_identity_index.sql` idempotently drops `idx_v2_metric_facts_identity_unique` and recreates it with all 9 columns including `source_type`. Pure DDL; no code deploy required. See `docs/operations/cloud-deployment-runbook.md` Pending Production Rollouts for apply instructions.

### Status reconciliation (2026-04-19)

Settled 2026-04-19 via direct prod read:

```bash
source .env && psql "$DATABASE_URL" -c \
  "SELECT indexdef FROM pg_indexes WHERE indexname='idx_v2_metric_facts_identity_unique'"
# CREATE UNIQUE INDEX ... (doc_id, canonical_metric_id,
#   COALESCE(period_start,'1900-01-01'), COALESCE(period_end,'1900-01-01'),
#   unit, scope, COALESCE(cohort_def,''), COALESCE(customer_type,''),
#   source_type)  — 9 columns, source_type present.
```

Prod is healed: the 9-column index includes `source_type`. The `scripts/apply_migrations.py:68-74` comment is accurate (sql/33 was applied out-of-band) and stays in place so `--test` runs don't re-apply it on fresh test DBs. Local test DB and prod now agree.

### References

- `sql/33_fix_identity_index.sql` — fix migration
- `scripts/apply_migrations.py:68-74` — registration comment claiming prod already applied
- `docs/architecture/data-model.md` — "Known Discrepancies" section
- `sql/23_chart_source_dedup.sql` — original 9-column DDL intent
- `src/extraction_v2/models.py::MetricFact.identity_tuple` — 9-element tuple
- `src/extraction_v2/persistence.py` — delete-then-insert persistence (lines 663–726)

---

## 10. `test_candidate_generation_finds_active_consumers` — Root Cause Unclear

**Status**: ✅ Resolved-by-deletion (2026-04-19)
**Severity**: Low
**Discovered**: 2026-03-26

### Resolution

`tests/integration/test_gold_standard_coverage.py` was deleted in commit `03a8a20` ("refactor(v1): retire review_candidates + source_segments + suppressed_candidates"). The failing test no longer exists — the entire candidate-generation coverage module was retired alongside the V1 review tables. Pipeline-level recall for `cm_active_customers_total` remains 100% on Farfetch, so no replacement test is needed at this time.

If candidate-generation coverage is later reintroduced (e.g., for V2-native candidate paths), any new test should assert against `src/gold_standard/v2_validator.py` output rather than the retired V1 candidate-generation module.

---

## 14. Farfetch LTV/CAC Dedup Collision on Layout Tables

**Status**: ✅ Resolved (2026-04-18) — respectively-parser priority + `cohort_hint` plumbing
**Severity**: Medium (was 4 Tier 1 FNs on Farfetch)
**Discovered**: 2026-04-18
**Resolved**: 2026-04-18

### Problem (historical)

Farfetch's LTV/CAC cohort values (1.42, 1.53, 1.77) were all correctly extracted pre-dedup but collapsed to a single surviving fact (1.77) per metric, producing 4 Tier 1 FNs on `cm_ltv_to_cac_ratio` + `cm_ltv_to_cac_ratio_by_cohort`. Pre-fix GS numbers on Farfetch:
- `cm_ltv_to_cac_ratio`: P=100%, R=33.3%, F1=50.0% (2 FNs: 1.42, 1.53)
- `cm_ltv_to_cac_ratio_by_cohort`: P=100%, R=16.7%, F1=28.6% (2 text FNs + 4 chart FNs)

### Root Cause Chain

1. The filing has a bullet-point rendered via HTML `<TABLE>` used purely for layout (indent + `&#149;` + prose `<TD>`). No semantic data table.
2. `table_reconstruction` classifies this layout table as a data table; extracts "1.42, 1.53, 1.77" as three cells; uses the whole prose sentence "Six month LTV/CAC ratio for the years ended December 31, 2015, 2016 and 2017 cohorts was 1.42, 1.53 and 1.77, respectively" as `header_path`.
3. `fact_construction.py:441 _extract_cohort_def` parses the prose as an "acquisition" cohort label (matches year pattern) → assigns the **entire sentence** as `cohort_def` for all 3 facts.
4. All 3 facts share an identical 9-column identity tuple (metric + period=2015-12-31 + unit + scope + same cohort_def + customer_type + source_type). Value is NOT part of identity.
5. `deduplication.py:375 _collapse_post_transfer_collisions` enforces the DB unique index (`sql/23_chart_source_dedup.sql`). Drops 2 of 3; keeps 1.77 (highest value_raw tie-break).

Confirmed 2026-04-18 via `/tmp/diag_farfetch_ltvcac.py`: pre-dedup has 6 LTV/CAC facts; post-dedup has 2. FN diagnostic (post-#19) correctly classifies all 4 as `dedup_collision`.

### Partial Infrastructure Already in Place

A `respectively_parser` module (`src/review/respectively_parser.py`) exists and **correctly parses the Farfetch LTV/CAC prose** — verified 2026-04-18 by calling `detect_respectively_pattern()` directly on the text, which returns the correct associations `[(1.42, 2015), (1.53, 2016), (1.77, 2017)]` with confidence 0.9.

However, the parser is **only invoked as a fallback** (`value_binding.py:787` and `:1119`) when no other bindings exist for the candidate. For Farfetch LTV/CAC, the layout-table-as-data-table extraction already produces 3 bindings, so the respectively-parser fallback never fires — the parser's per-cohort associations are never applied.

### Resolution (2026-04-18)

Combined options (b) + (c) from the original fix menu:

1. **Respectively-parser priority in `_bind_prose_cell`** (`src/extraction_v2/stages/value_binding.py`). When the prose cell contains "respectively" AND `detect_respectively_pattern(text, min_confidence=0.8)` returns a match, Strategy 6 now routes bindings through `_bind_respectively_pattern` directly instead of letting `_find_numbers_in_proximity` win.
2. **Cohort-intent detection in `_bind_respectively_pattern`**. If the cell text contains `\bcohorts?\b`, the year strings returned by the parser are surfaced as `BoundValue.cohort_hint` (e.g. `"2015 cohort"`) and `period_hint` is left empty. Otherwise the existing `period_hint` behaviour is retained.
3. **`cohort_hint` field on `BoundValue`** (`src/extraction_v2/models.py`). New dataclass field mirroring `period_hint`; default `""`.
4. **Fact construction prefers `bv.cohort_hint`** over `_extract_cohort_def(evidence)` in `_construct_fact` (`src/extraction_v2/stages/fact_construction.py:223`).
5. **Defensive prose-length guard in `_extract_cohort_def`**. Skips header/stub labels longer than 80 chars to prevent prose sentences (which `.search()` can partially match) from becoming cohort_def.

### Post-fix GS Results

Farfetch (2026-04-18 baseline refresh):
- `cm_ltv_to_cac_ratio`: R 33.3% → **100%** (all 3 text rows TP).
- `cm_ltv_to_cac_ratio_by_cohort`: R 16.7% → **50.0%** (text FNs cleared; 3 chart FNs remain under Issue #20).
- Farfetch overall: F1 47.3% → **57.6%** (+10.3pp).
- Full gold standard: F1 +1.0pp; Tier 1 F1 55.6% → 57.3%. `--fail-on-regression` gate passes.

### Tests

6 new tests covering the fix:
- `tests/unit/extraction_v2/test_value_binding.py::TestProseRespectivelyPriority` (4 cases: cohort sentence routes through parser; cohort_hint populated; period sentence keeps period_hint; confidence-gate fallthrough to proximity).
- `tests/unit/extraction_v2/test_fact_construction.py::test_cohort_hint_on_bv_overrides_extract_cohort_def` + `::test_prose_length_guard_skips_long_header_label`.
- Updated `test_bind_respectively_pattern_ltv_cac` to assert the new cohort_hint semantics on the Farfetch sentence.

### Follow-ups (not in this fix)

- Apply the same cohort-intent detection to `_bind_text_candidate` respectively fallback (`value_binding.py:1117-1144`) — no observed GS bug in the text path today.
- Option (d) (add `value` to DB unique index + relax dedup logic) remains available if similar collisions arise from other root causes.

---

## 15. Chart Pipeline Env Bootstrap

**Status**: ✅ Resolved (2026-04-18) — validator now auto-loads `.env`
**Severity**: Medium (was blocking local re-measurement)
**Discovered**: 2026-04-18
**Resolved**: 2026-04-18

### Problem

Running `python3 -m src.gold_standard.v2_validator` without exported `OPENAI_API_KEY` caused Stages 4 and 5 to be disabled silently (warning printed but easy to miss). `source .env` alone wasn't sufficient because shell variables aren't exported to Python by default. Affected metrics (when key was absent): `cm_gross_margin_by_cohort`, `cm_revenue_by_cohort` (chart gold rows), and other chart-sourced Tier 1 metrics.

### Resolution

Added `load_dotenv()` to `src/gold_standard/v2_validator.py` `__main__` block (line 1908). Mirrors existing pattern in `tests/integration/conftest.py:327` and `tests/performance/conftest.py:17`. `load_dotenv()` defaults to NOT overriding existing env, so shell-set values still take precedence — safe addition.

Chart stages now run automatically when `.env` contains `OPENAI_API_KEY`. Verified via fresh baseline refresh: 23 chart facts produced, 0 "API key not set" warnings in output.

### Follow-Up

See Issue #20 for remaining chart-pipeline gaps uncovered by the now-functioning chart stages (specifically `cm_gross_margin_by_cohort` still at 0% on Farfetch despite chart extraction running).

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

## 17. CAC Payback "Six Months" — Bare Word-Number Not Bound

**Status**: ✅ Resolved (2026-04-18)
**Severity**: Low (was 1 Farfetch T2 FN; likely also affected other filings)
**Discovered**: 2026-04-18
**Resolved**: 2026-04-18

### Problem

Farfetch gold expects `cm_cac_payback_period = 6` (unit: months) from the prose "the payback period on CAC has been consistently less than six months." The pipeline generated the correct candidate but produced **0 value bindings** because `WORD_NUMBER_PATTERN` required a scale suffix (million/billion/etc.) and didn't handle time-unit followers.

### Resolution

Added a narrow gated parser for word-number + time-unit:

1. **`src/extraction_v2/stages/value_binding.py`** — new `WORD_NUMBER_TIME_PATTERN` regex matching `(one|...|twelve)\s+(days?|weeks?|months?|years?|quarters?)` with word-boundary anchors. Gated via `TIME_UNIT_VALUED_METRICS = {"cm_cac_payback_period"}` so bare word-numbers in other filings (e.g., "the past six months" as period reference) don't bind to unrelated candidates. `_find_numbers_in_proximity` takes an optional `metric_id` kwarg; callers pass `candidate.metric_id`.
2. **`src/extraction_v2/stages/false_positive_filter.py`** — added `_V1_SPELLED_OUT_OVERRIDE_METRICS = {"cm_cac_payback_period"}` to bypass the V1 `spelled_out_no_magnitude` rule (which would otherwise reject the binding) for time-valued metrics only.
3. **Tests** — 6 new unit tests in `tests/unit/extraction_v2/test_value_binding.py::TestWordNumberTimeUnitParsing` covering: binding for time-valued metric, skip for non-time metric, skip without metric_id (backwards compat), "twelve weeks" parses to 12, bare "six" alone does not match, and "sixth" word-boundary check.

### Result

`cm_cac_payback_period` on Farfetch: **0% → 100% F1** in the 2026-04-18 post-fix baseline run. No Tier 1 regression (validator confirmed F1 +0.4pp).

---

## 18. Migration Checksum Mismatch on `sql/01_create_schema.sql`

**Status**: ✅ Resolved (2026-04-18) — self-healed via V1 retirement merge
**Severity**: Low (blocks pytest-based gold standard; v2_validator module path works)
**Discovered**: 2026-04-18

### Problem

Running `pytest -m gold_standard --gold-standard-mode=fresh` errors during session fixture setup:

```
RuntimeError: Checksum mismatch for 01_create_schema.sql: expected 38c41050…, got 01538bd6….
Migration file was modified after it was applied.
```

The `schema_migrations` ledger in the local test DB has a stale checksum for `01_create_schema.sql`. All 14 gold-standard-tagged pytest tests error out at setup.

### Workaround (used 2026-04-18)

Use `python3 -m src.gold_standard.v2_validator` directly. This bypasses pytest fixtures entirely and does not require the test DB. Also aligns with the updated `.claude/rules/gold-standard.md` which now recommends the v2_validator module.

### Next Steps

- Reconcile the local test DB's `schema_migrations` row for `01_create_schema.sql` (either re-apply or update the recorded checksum).
- Verify no actual schema drift between the checksum-recorded version and the current file.
- Consider adding a helper script (e.g., `scripts/sync_test_db_checksums.py --dry-run`) for this recurring scenario.

---

## 20. `cm_gross_margin_by_cohort` Still 0% on Farfetch Despite Chart Pipeline Active

**Status**: ✅ Resolved (2026-04-18)
**Severity**: Medium (was 10 Tier 1 FNs on Farfetch)
**Discovered**: 2026-04-18
**Resolved**: 2026-04-18

### Problem

With `OPENAI_API_KEY` loaded and chart/vision stages running end-to-end, `cm_gross_margin_by_cohort` remained **P=0%, R=0%, F1=0%** on Farfetch's 9 chart-sourced gold rows. The 2026-04-17 vision JSON-mode + truncation-repair fix did not lift this metric.

### Root Cause (diagnosed 2026-04-18 via DB inspection of persisted chart_data)

The vision pipeline for `g607688g09d00.jpg` ("Marketplace Order Contribution Margin") DID extract the correct 9 values at `confidence=0.9`, but with a specific output shape the classifier couldn't handle:

```json
{
  "title": "", "x_axis_label": "", "y_axis_label": "",
  "series": [
    {"name": "Existing Consumers",      "points": [{"x": "2015", "y": 45.0, "label": "45%"}, ...]},
    {"name": "All Consumers - Blended", "points": [{"x": "2015", "y": 33.0, "label": "33%"}, ...]},
    {"name": "New Consumers",           "points": [{"x": "2015", "y": 23.0, "label": "23%"}, ...]}
  ]
}
```

Three independent gates in `src/extraction_v2/chart/metric_classifier.py` + `src/extraction_v2/chart/cohort_parser.py` all relied on signals absent from this shape:

1. **`_cohort_gate`** only scanned series `name` for year markers and title/axes for "cohort"/"vintage" — none present. Year info was in `points[].x`, not checked.
2. **`_metric_gate` for `cm_gross_margin_by_cohort`** only scanned `y_axis_label` for `%|margin|contribution\s+margin` — empty. `%` signal was in `points[].label`, not checked.
3. **`_score_metric`** only scored title/axes/annotations/nearby_text for YAML patterns; with all four signals empty or out of window, the FTCH chart scored 0.36, below the 0.6 threshold.
4. **`CohortParser._parse_series_year_regime`** required a year in `series.name`; the Farfetch chart has customer-type segmentation (year lives in `points[].x` instead).

Chart-fact-bridge silently skipped the image at `chart_fact_bridge.py:101` (`metric_id is None or score < 0.6`). No log, no counter increment.

### Resolution

Four targeted changes (all within `src/extraction_v2/chart/`):

1. **`metric_classifier.py::_cohort_gate`** — accept charts where ≥2 distinct years live in `points[].x` AND at least one series name matches a customer-type descriptor (new/existing/blended/etc. + consumer/customer/member/subscriber/user/buyer/account/client).
2. **`metric_classifier.py::_metric_gate(cm_gross_margin_by_cohort)`** — fallback when `y_axis_label` is empty: require margin/contribution keyword in title/axes/series-names/nearby_text AND a `%` signal in axis or point labels.
3. **`metric_classifier.py::_score_metric`** — (a) when `chart.title` is empty, use `nearby_text[:200]` as effective title for specific+patterns scoring; (b) structural bonus of +5.5 raw for `cm_gross_margin_by_cohort` when all three signals present (% point labels + ≥2 distinct years in point.x + customer-type series names). The bonus alone clears the 0.6 threshold since this shape is distinctive.
4. **`cohort_parser.py::_parse_customer_type_regime`** — new regime invoked after series-year and elapsed-period regimes. Fires when `series.name` has no year AND matches customer-type keywords AND `point.x` contains a year within filing-date ±20/+2 years. Returns `CohortPeriod` with `cohort_def = series.name`, `period_start/end` from the year in `point.x`, `confidence=0.65`, `requires_review=True`.

Classifier signature change: `_metric_gate` gained an optional `nearby_text` parameter, threaded from `ChartMetricClassifier.classify`. All five `_SUPPORTED_METRICS` metric gates are backward-compatible (parameter defaults to `""`).

### Results

**Farfetch** (`--companies "Farfetch Limited"`):
- `cm_gross_margin_by_cohort`: **0% → 100% F1** (9/9 gold rows recovered)
- Tier 1 F1: **55.6% → 86.5%** (+30.9pp on Farfetch)

**Full V2 baseline**:
- Overall F1: **53.7% → 56.9%** (+3.2pp; validator reports "F1 +2.2pp — no regression")
- Tier 1 F1: **55.6% → 61.0%** (+5.4pp)
- No Tier 1 regression on any metric vs. baseline

### Tests

- `tests/extraction_v2/chart/test_chart_metric_classifier.py::test_empty_axes_cohort_margin_chart_classifies_via_point_years` — regression test using the real OCR shape (empty title/axes, real-shape nearby_text without pattern match); asserts `cm_gross_margin_by_cohort` classification with score ≥ 0.6.
- `tests/extraction_v2/chart/test_chart_metric_classifier.py::test_non_cohort_empty_axes_chart_still_rejected` — regional revenue chart with empty axes + years in x but non-customer-type series returns `None`.
- `tests/extraction_v2/chart/test_cohort_parser.py` — 4 new tests for `_parse_customer_type_regime` (FTCH shape, "Blended" series, regional rejection, year-in-name rejection, out-of-range year rejection).

### Out of scope (flagged during diagnosis, not fixed here)

- `cm_new_customers_acquired` receives a chart fact `"2.71 x"` from the FTCH LTV/CAC chart `g607688g54x53.jpg` — a separate classifier mis-tag. 1 FP per Farfetch baseline.
- The Farfetch Order Contribution Margin OCR output has empty title/axes. Upstream OCR prompt hardening could populate these labels directly, making the classifier fallback unnecessary; out of scope for this session.

---

## 19. FN Diagnostic Classification Gaps

**Status**: ✅ Resolved (2026-04-18)
**Severity**: Low (misleads investigation but doesn't affect production)
**Discovered**: 2026-04-18
**Resolved**: 2026-04-18

### Problem

The FN root-cause analysis in `src/gold_standard/v2_validator.py` (lines 900–1040) classified two Farfetch FNs into misleading categories during 2026-04-18 diagnosis:

1. **`cm_ltv_to_cac_ratio` classified as `wrong_period`**. Actual root cause: dedup collision from shared `cohort_def` (Issue #14). The category fired because `wrong_period`'s value-match check used `all_metric_facts = context_facts ∪ metric_facts`, which included pre-dedup facts — so it matched a fact that was later collapsed by dedup.
2. **`cm_revenue_by_cohort` classified as `fp_filtered`**. Actual root cause: the 2 removed bindings were date fragments (`31`, `2017`) from a different candidate; the expected 44.4%/55.6% values were never bound to any candidate at all (chart-sourced, blocked by API key). The `fp_filtered` rule fired on any removed binding without checking whether its value matched the gold expectation.

### Resolution

`src/gold_standard/v2_validator.py`:

1. **`wrong_period` → `dedup_collision`** (new category). Added Step 5b that emits `dedup_collision` when a value-matching fact existed pre-dedup but no value-matching fact survived in `deduplicated_facts`. Distinct from `dedup_removed` (whole-metric wipe) — `dedup_collision` catches sibling-value collapse (e.g., LTV/CAC 1.42/1.53/1.77 collapsed to 1.77).
2. **`wrong_period` restricted to post-dedup facts**. Step 7's value-match check now uses only `deduplicated_facts`, not the pre-dedup union. Pre-dedup value matches that were later collapsed are caught by `dedup_collision` above.
3. **`fp_filtered` → `no_matching_binding`** (new category). The `fp_filtered` classification now requires at least one FP-removed binding to have value matching the gold expected value. If removed bindings existed but none matched (date fragments, scale components, etc.), the new `no_matching_binding` category is emitted instead.

### Tests

4 new unit tests in `tests/unit/gold_standard/test_v2_validator.py::TestDiagnosefalseNegative`:
- `test_no_matching_binding` — FP-removed bindings with non-matching values
- `test_dedup_collision` — value-matching fact collapsed into sibling post-dedup
- `test_wrong_period_uses_dedup_facts_only` — regression test ensuring wrong_period requires a post-dedup value match
- Existing `test_fp_filtered` updated to set a matching value on the binding (its original assertion was value-ambiguous under the old rule).

All 164 `test_v2_validator.py` tests pass (was 158 before these additions).

---

## 21. `v2_image_assets` Duplicates + Pending-Count Discrepancy (Maplebear S-1)

**Status**: ✅ Resolved (2026-04-18) — dedup migration + stable-img_id upsert + in-memory fact remap
**Severity**: Medium (UI showed 220 pending images; all appeared already-reviewed when clicked)
**Discovered**: 2026-04-18
**Resolved**: 2026-04-18

### Problem

The Maplebear S-1 review UI displayed 220 pending images in the progress counter, but every image opened as already-reviewed. Zero images appeared in the review queue despite the non-zero pending count.

### Root Cause

Two coupled defects:

1. **Random UUID on every re-extraction.** `ImageAsset.img_id` is generated via `uuid.uuid4()` per pipeline run. The upsert in `_persist_images_in_tx` used `ON CONFLICT (img_id)` — a conflict that never fires because each run produces a new UUID. Every re-extraction inserts a fresh row with `review_status='pending'`, leaving the original (decided) row orphaned in the table.

2. **Asymmetric deduplication.** `get_image_review_progress_v2` (`src/infra/db.py`) counts `review_status='pending'` rows without deduping by `(doc_id, filename)`, so it counts all duplicate rows. The review-list query uses `DISTINCT ON (filename)` to surface only one row per image — which happens to be the row with a decision. Result: counter = 220, queue = 0.

### Resolution

1. **`sql/34_dedup_v2_image_assets.sql`** — collapses duplicate `(doc_id, filename)` groups: preserves the decided row (or highest `review_status` rank), consolidates `review_status` / `predicted_relevance` / `detected_keywords`, then adds `UNIQUE (doc_id, filename)` constraint.
2. **`src/extraction_v2/persistence.py:_persist_images_in_tx`** — changes `ON CONFLICT (img_id)` to `ON CONFLICT (doc_id, filename) DO UPDATE`, preserves the existing `img_id` on conflict, and returns an old→stable `img_id` map.
3. **`src/extraction_v2/persistence.py:persist_pipeline_result`** — uses the map to rewrite `source_locator.img_id` in-memory before fact persistence, keeping metric-fact provenance consistent with the stable DB row.
4. **`scripts/apply_migrations.py` and `scripts/apply_all_migrations.py`** — `sql/34_dedup_v2_image_assets.sql` registered in `MIGRATIONS` / `MIGRATION_ORDER`.

### Remaining

None — the four related out-of-scope issues are tracked separately in Issues #22–#25 below.

---

## 22. No Reviewed-Filing Guard on Image Re-Extraction

**Status**: ✅ Resolved (2026-04-18)
**Severity**: Low (no data loss; decisions survive re-extraction via stable img_ids post-Issue #21)
**Discovered**: 2026-04-18
**Resolved**: 2026-04-18

### Problem

The fact-side `ReviewedFilingError` (raised in `src/extraction_v2/persistence.py:_persist_facts_in_tx`, defined in `src/extraction_v2/exceptions.py`) did not cover image assets. After the sql/34 fix, existing review decisions survive re-extraction because img_ids are stable. However, if re-classification changed an image from `chart` to `decorative`, the review UI filtered it out (`classification NOT IN ('decorative','logo','signature')` in `src/infra/db.py:1631`) — the decision became hidden rather than invalidated. There was no warning to the reviewer.

### Resolution

Narrow image-side guard added to `_persist_images_in_tx` in `src/extraction_v2/persistence.py`. Guard trigger: for each incoming `ImageAsset`, fires only when ALL of these hold:

1. An existing `v2_image_assets` row with the same `(doc_id, filename)` exists.
2. That row has a decision in `v2_image_review_decisions`.
3. The existing `classification` is in `{'chart', 'table_image', 'unknown'}` (visible set).
4. The incoming `classification` is in `{'decorative', 'logo', 'signature'}` (hidden set).

Behaviour:

- `force=False` (default): raises `ReviewedFilingError(context="image classifications")`. Transaction aborts before any write.
- `force=True`: logs `force-reextract hiding reviewed images: filing_id=X hidden_image_count=N filenames=[…]` and proceeds.

The `context` kwarg was added to `ReviewedFilingError` (default `"facts"` preserves the existing fact-guard message). Re-classifications within the visible set, or re-classifications of an already-hidden image, are not blocked (guard focuses exclusively on new hiding).

### Tests

5 new integration tests in `tests/integration/extraction_v2/test_persistence_guard.py::TestGuardOnPersistImages`:
- `test_reclassification_to_hidden_raises_without_force`
- `test_reclassification_to_hidden_force_warns_and_proceeds`
- `test_same_classification_passes`
- `test_unreviewed_image_passes`
- `test_already_hidden_reclassification_passes`

`_cleanup` fixture also extended to purge `v2_image_review_decisions` + `v2_image_assets` rows.

### Follow-up (out of scope here)

`scripts/ingest_presentations.py:327` calls `persist_pipeline_result` without threading `force`. With the new guard, that path will now raise on re-ingestion of a filing whose images would be re-classified into the hidden set. This is the intended behaviour (fail loudly rather than silently hide); adding a `--force-reextract` flag there is a separate task if an operator workflow needs it.

---

## 23. `v2_image_assets.segment_id` Is a Dead Column

**Status**: ✅ Resolved (2026-04-18)
**Severity**: Trivial (cosmetic)
**Discovered**: 2026-04-18
**Resolved**: 2026-04-18

### Problem

`src/extraction_v2/persistence.py` set `segment_id` to NULL with the comment "FKs to V1 source_segments; not used in V2". The V1 `source_segments` table was dropped in `sql/31_drop_v1_review_tables.sql`. The column was never read or written with a meaningful value.

### Resolution

1. **`sql/35_drop_v2_image_assets_segment_id.sql`** — idempotent `ALTER TABLE v2_image_assets DROP COLUMN IF EXISTS segment_id`. FK was already dropped in sql/31; no explicit DROP CONSTRAINT needed. Applied to Neon prod + local test DB 2026-04-18.
2. **`src/extraction_v2/persistence.py`** — removed `segment_id` from INSERT column list, VALUES, DO UPDATE SET, and params dict in `_persist_images_in_tx`.
3. **`scripts/apply_migrations.py`** — registered sql/35 in `MIGRATIONS` list.

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

## 25. `scripts/migrate_image_ids_to_deterministic.py` Scope Is Confusing

**Status**: ✅ Resolved (2026-04-18)
**Severity**: Trivial
**Discovered**: 2026-04-18
**Resolved**: 2026-04-18

### Problem

The script name implied a production DB migration, but it only rewrites `data/presentation_gold_standard/_image_*.json` files — it never touches the database. Readers discovering it during DB image-identity investigations could be misled.

### Resolution

Expanded the module-level docstring in `scripts/migrate_image_ids_to_deterministic.py` to open with explicit scope: "One-time transformation of local gold-standard JSON files. Scope: … Does NOT modify the production database or any `v2_image_assets` rows — the word 'migration' in the filename refers to a JSON-format upgrade, not a DB schema migration." `scripts/archive/` does not exist on disk; per the original suggestion, the docstring-only fix is applied instead of a move.

---

## 26. Review UI — Lost SEC + Image Links for Investor Presentations

**Status**: ✅ Resolved (2026-04-19)
**Severity**: Medium — all 166 investor-presentation filings rendered with no "View source" anchor and 404-ing image thumbnails (507 image assets affected)
**Discovered**: 2026-04-19

### Problem

`scripts/ingest_presentations.py:_upsert_presentation_filing` inserted filings rows without `cik` or `sec_html_url`, encoding the SEC location inside `accession_number` as `presentation:<cik>/<accession>/<filename>`. The review UI consumed this in two places:

- `src/web/routes/review_unified.py:335-342` set `sec_filing_url = filing["sec_html_url"]` (NULL) then fell back to `_build_sec_directory_url(filing["cik"], ...)` only if `filing["cik"]` was truthy (NULL). Template guard `{% if sec_filing_url %}` dropped the anchor.
- `src/infra/db.py:_V2_IMAGE_CANDIDATE_SELECT` built `/images/cache/<cik>/<REPLACE(accession,'-','')>/<filename>`. For encoded accessions this produced a four-segment path that did not match the three-segment Flask route.

Eighth link breakage in four months — the recurrence driver is that URL construction was duplicated across routes, templates, SQL projections, and ingest scripts, so every new filing shape required patching all of them.

### Resolution

Seven-part fix centralising URL construction and closing the detection gap:

- `sql/36_backfill_presentation_urls.sql` — one-time `UPDATE` backfill for the 166 rows (idempotent; format verified 166/166 rows match).
- `scripts/ingest_presentations.py:_upsert_presentation_filing` — writes `cik` and `sec_html_url` on INSERT/UPDATE and raises `ValueError` inside the transaction if the returned row still has either as NULL.
- `src/infra/db.py:_V2_IMAGE_CANDIDATE_SELECT` — `CASE` expression strips the `presentation:<cik>/` prefix and trailing `/<filename>` from `accession_number` before building image URLs (defence in depth).
- `src/web/url_builders.py` (new) — single `resolve_sec_filing_url()` / `build_image_cache_url()` / `build_sec_directory_url()` helpers used by all route code.
- `src/web/routes/review_unified.py` — inline URL logic replaced with helper calls; `_build_sec_directory_url` local helper deleted.
- `tests/unit/web/test_review_link_integrity.py` (new) — real Flask `test_client` renders `/v2/review/<id>` for each document_type and asserts `<a>` and `<img src>` HTML matches the route regex. Closes the gap where `tests/unit/web/test_review_v2_routes.py` mocks `render_template`.
- `tests/unit/web/test_url_for_resolves.py` (new) — smoke test that every route name referenced by the unified templates resolves via `url_for` (catches the typo class historically responsible for one of the eight incidents).
- `scripts/validate_database_urls.py` — gained `--fail-on-errors` / `--document-type`; wired into CI `integration-tests` job as a post-migration link-integrity gate.
- `.claude/rules/web.md` — codified "URL construction goes through `src/web/url_builders.py`" to keep future filing shapes landing in one place.

### Related — not patched in this resolution

`scripts/ingest_specific_presentations.py:100-133` has the same INSERT pattern without `cik` or `sec_html_url`. Not in scope for this fix, but will be caught by the post-ingest invariant as soon as it's updated to match `ingest_presentations.py`, and the CI link-integrity gate will flag any rows it produces.

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

## 29. `cm_new_customers_acquired` Receives `2.71x` Chart Fact From Farfetch LTV/CAC Chart

**Status**: ✅ Resolved (2026-04-19) — value-level FP rule; confirmed via Farfetch GS
**Severity**: Low (1 Farfetch FP; does not block recall)
**Discovered**: 2026-04-18 (flagged in Issue #20 "Out of scope"); filed as its own issue 2026-04-19
**Resolved**: 2026-04-19

### Problem

FTCH's LTV/CAC tenure chart `g607688g54x53.jpg` emits chart point labels `"2.71x"`, `"1.81x"`, `"2.04x"` that get bound to `cm_new_customers_acquired` (a count metric). Surfaces as a `NO_MATCH` FP on the Farfetch gold-standard run (1 of 12 FPs on 2026-04-19 baseline). The correct home for these values is `cm_ltv_to_cac_ratio_by_cohort`.

### Root Cause (diagnosed 2026-04-19 via DIAG print in `_scan_chart`)

The chart_data for `g54x53` is:

```
title=''  y_axis=''  x_axis=''  annotations=[]
series=[
  ('2015 Cohort', [('LTV / CAC after 6 months',  1.42, '1.42 x'),
                    ('LTV / CAC after 12 months', 1.53, '1.53 x'),
                    ('LTV / CAC after 24 months', 1.77, '1.77 x')]),
  ('2016 Cohort', [..., ('LTV / CAC after 24 months', 2.04, '2.04 x')]),
  ('2017 Cohort', [('LTV / CAC after 24 months', 2.71, '2.71x')])
]
```

`combined_text` (built from title/axes/series.name/annotation.text) is just `'2015 Cohort 2016 Cohort 2017 Cohort'` — no customer-type keywords. A yaml-level exclusion on chart combined_text would not help here.

The mis-classification enters via `_scan_chart`'s **second pass** against `nearby_text` (`candidate_generation.py:459-485`). Farfetch's prose around this image reads: *"as we have managed to lower our CAC and increase our LTV of acquired consumers over time. This has allowed us to increase total consumer acquisition spend, and as a result, increase our number of new Marketplace consumers."* → legitimately matches `\bnew\s+consumers?\b` / `\bconsumers?\s+acquired\b` for `cm_new_customers_acquired`. A candidate is created; value binding then attaches the chart point.label `2.71` to it. Similar paths exist for `cm_customer_acquisition_cost` (currency), `cm_lifetime_value_per_customer` (currency), etc.

### Resolution

Added `_rule_ratio_suffix_on_count_metric` to `src/extraction_v2/stages/false_positive_filter.py`, mirroring the existing `_rule_revenue_concentration_ratio_suffix`. Whitelists ratio metrics (`cm_ltv_to_cac_ratio`, `cm_ltv_to_cac_ratio_by_cohort`) implicitly by not listing them; rejects any `N.NNx` / `N.NN×` raw value bound to count / currency / rate / time metrics in `_RATIO_SUFFIX_COUNT_METRICS` (18 metrics). Registered in `_FP_RULES` immediately after `revenue_concentration_ratio_suffix`.

### Validation

- 6 new unit tests in `tests/unit/extraction_v2/test_false_positive_filter_stage.py::TestRatioSuffixOnCountMetric` covering: `2.71x` blocked on `cm_new_customers_acquired`; `1.81x` blocked on `cm_active_customers_total`; unicode `×` variant; legitimate `500` count not blocked; `2.71x` allowed on `cm_ltv_to_cac_ratio_by_cohort`; `2.71x` allowed on `cm_ltv_to_cac_ratio`.
- Full unit-test run: **2233 pass, 11 skip, 0 fail** (`pytest tests/unit/review/ tests/unit/extraction_v2/ tests/extraction_v2/chart/`).
- Farfetch GS validator (`python3 -m src.gold_standard.v2_validator --companies "Farfetch Limited"`): the `2.71x` `NO_MATCH` FP on `cm_new_customers_acquired` is **eliminated**. Total Farfetch FP count unchanged at 12 — see note below.

### Note on observed dedup-displacement side effect

Removing the `2.71x` binding unmasks a pre-existing sibling FP: `cm_new_customers_acquired: 54.0 (raw='54%')` now appears in the Farfetch `NO_MATCH` slot. This is a **separate, pre-existing** candidate previously tiebroken-away by `2.71x` during dedup. Root cause: a percent value from elsewhere in the filing binding to `cm_new_customers_acquired` with `unit=COUNT` (so `_rule_percent_on_count_metric` skips it — that rule requires `unit=PERCENT`). **Not fixed here** per CLAUDE.md scope discipline; should be filed as its own issue if it persists after broader percent-on-count hardening.

---

## 30. 15 Filings With CIK / sec_html_url Mismatch

**Status**: ✅ Resolved (2026-04-19) — reviewer-facing URL column corrected on all 15 rows. Latent cached-HTML residue logged as Issue #43.
**Severity**: Medium — the review UI's "View source" link on these 15 filings pointed to the wrong SEC document; reviewers could attribute facts to the wrong filing
**Discovered**: 2026-04-19 (surfaced by new `scripts/validate_database_urls.py --fail-on-errors` gate while resolving Issue #26)
**Resolved**: 2026-04-19

### Problem

15 filings in the production DB had a `sec_html_url` that pointed at CIK `0001725792` / `d745640ds1a.htm` (the Uber S-1/A path) while their own `filings.cik` held a different value. Fallout from pre-Issue-#6 FilingFetcher exhibit-pattern-matching incidents (Dec 2025): the fetcher saved one filing's content across many rows, and the URL never got corrected.

### Root Cause (discovered during audit)

The 15 rows are **not** 15 independent corruptions. They are **one SEC filing co-registered by 15 affiliated entities** — Spectrum Brands + 14 subsidiaries (accession `0001193125-19-149408`, a 2019 S-1/A for debt securities). SEC archives the same primary document at 15 distinct CIK-keyed paths (one per co-registrant), which is normal for multi-entity registrations. The pre-#6 fetcher saved the wrong HTML once at `data/filings/0001725792/000119312519149408/primary.htm` (Uber CIK dir, Spectrum accession) and every co-registrant row ended up pointing at that stale URL + shared storage file.

Affected `filing_id`s: 902, 903, 904, 905, 906, 907, 908, 909, 910, 911, 913, 914, 915, 916, 919 (earlier estimate "904–912 + 5 more" was inexact).

### Resolution

**Audit → Path A fix → verify**, per plan at `.claude/plans/let-s-tackle-known-issue-agile-pearl.md`.

1. `scripts/audit_filing_url_mismatch.py` enumerated affected rows, resolved the correct per-CIK URL via `SECClient.resolve_primary_document_url(cik, accession)`, sniffed on-disk + `html_content` column for Uber fingerprints, and counted `v2_metric_facts` / `v2_review_decisions` / `v2_image_review_decisions` per row. All 15 returned `facts=0, reviews=0, img_reviews=0`.
2. `scripts/repair_filing_url_mismatch.py --path A --include-path-c --apply` executed per-row `UPDATE filings SET sec_html_url = <per-CIK URL>` statements, optimistic-locked on `(filing_id, old_url)`. 15 applied, 0 skipped. Apply log preserved at `data/audit/issue_30_applied_20260419T210109Z.jsonl`.
3. Re-ran audit: 0 affected rows. Reviewer-facing "View source" links now open each co-registrant's own SEC URL (same underlying document, different CIK in the path).

The audit did NOT refetch the cached HTML file, which still contains Uber content at the shared `html_storage_path`. Since `facts=0` and no extraction has run, this is a latent (not active) issue — filed as **Issue #43** so a future re-fetch is explicit rather than implicit.

### Classifier note

The audit's path-classifier pessimistically downgraded all 15 to Path C because `accession_collides_in_scope=True` and `html_storage_path_shared_with≠[]` — guards designed to prevent double-writes in `FilingFetcher._update_database` (which filters by `WHERE accession_number`). In this case the collision is legitimate SEC multi-entity co-registration, not corruption. Added `--include-path-c` flag to the repair script for cases where a human has confirmed safety (requires `facts=0 AND reviews=0 AND img_reviews=0`, re-asserted as a backstop in `_eligible_rows`). Classifier refinement filed as **Issue #44**.

---

## 31. Audit Log Spams DNS Error in Test / Dev

**Status**: ✅ Resolved (2026-04-19) — both async and sync paths covered
**Severity**: Low (cosmetic — tests pass, UI works, log noise only)
**Discovered**: 2026-04-19 (observed during Issue #26 test-suite runs)
**Resolved**: 2026-04-19

### Problem

Two audit-log paths logged `ERROR` on every test-suite request when `DATABASE_URL` was a testing sentinel like `postgresql://test`:
- `src/web/routes/review_unified.py:102` (async, thread-closure path).
- `src/web/middleware.py:114` (synchronous, `insert_audit_log_entry`).

Errors were swallowed — responses unaffected — but the noise polluted pytest output and could mask real audit-log failures.

### Resolution

Both paths now capture `testing = bool(current_app.config.get("TESTING"))` and downgrade the `except` log to `DEBUG` when `testing` is true; `ERROR` preserved otherwise so real failures remain visible in production.

- `src/web/routes/review_unified.py:97-109` — async path (landed 2026-04-19).
- `src/web/middleware.py:87-120` — sync path (commit `366d9dd`, 2026-04-19); covered by `tests/unit/web/test_middleware.py::TestAuditLogFailureLogging` (DEBUG-under-TESTING + ERROR-otherwise).

---

## 32. `src/shared/html_segmenter.py` Has 0% Test Coverage (761 LOC)

**Status**: Open
**Severity**: Medium — blocks CI coverage gate (current coverage 74–75% hovers at the 75% threshold; any regression tips it back red)
**Discovered**: 2026-04-19 (surfaced while fixing the CI coverage failure — see Issue #30's neighbour)

### Problem

`src/shared/html_segmenter.py` is 761 lines of live V2 code (imported by `src/extraction_v2/stages/ingestion.py`) with **zero test coverage**. It is by far the single largest contributor to CI coverage being parked near the 75% threshold. Small companion modules (`src/shared/extraction_exceptions.py`, `src/shared/models.py`, `src/shared/segment_validators.py`) have been covered as part of this fix-wave, which is enough to get CI green — but only by a narrow margin.

### Why it was deferred

The cheap wins (delete `src/web/table_html_extractor.py` + `src/web/utils.py`, cover the three small `src/shared/*` files) were executed in commits addressing the original red-CI incident. Testing `html_segmenter.py` requires:

- A representative minimal SEC HTML fixture under `tests/fixtures/html/` (doesn't exist yet — existing integration tests use `data/sec_html/` which is gitignored).
- Understanding of the segmenter's public API (`SECHTMLSegmenter` class, primary parse entrypoint) to decide which paths are worth pinning down first.
- Decisions about which internal helpers (table-truncation, encoding fallback, context-prefix detection) deserve direct tests vs. end-to-end coverage via the main entrypoint.

Rough sizing: a single happy-path test that parses a trimmed 10-K excerpt and asserts segment count + types would cover 20–30% of the module (150–230 LOC), pushing total coverage to ~76–77% and giving headroom.

### Plan when taken up

1. Capture a minimal SEC HTML fixture (~5–10 KB) by trimming `data/sec_html/<filing>.htm` to one section containing prose + a table + a footnote. Commit to `tests/fixtures/html/`.
2. Write `tests/unit/shared/test_html_segmenter.py` with:
   - One happy-path test calling the primary entrypoint on the fixture; assert returned `SourceSegment` list is non-empty and has expected `segment_type` values.
   - One test per error branch: malformed HTML → `HTMLParsingError`; bad encoding → `EncodingError`; invalid filing_id → `ValidationError`.
   - One test for table-truncation behaviour with an oversized inline table.
3. Target 30%+ coverage of `html_segmenter.py` in the first pass. Not 100% — the SEC-specific quirks (broken encodings, nested CDATA, etc.) are better covered by integration tests against real filings.

### Prevent another coverage crisis

Once `html_segmenter.py` is meaningfully covered, consider raising `fail_under` from 75 to 80 in `pyproject.toml` so future dead/untested code can't re-park CI at the threshold. Track under a separate follow-up — see Issue #33.

---

## 33. Raise Coverage Threshold to 80% After Issue #32

**Status**: Open (blocked on #32)
**Severity**: Low — prevention
**Discovered**: 2026-04-19 (follow-up from the CI red-state drift incident)

After `html_segmenter.py` is covered (Issue #32), raise `fail_under` from 75 to 80 in `pyproject.toml` `[tool.coverage.report]`. The 75% floor is where the original incident parked — any new 0%-coverage module dropped the total back under the gate. A higher floor forces the fix at contribution time rather than letting dead code accumulate. Trivial edit (one number) once #32 lands.

---

## 34. `v2_image_assets.file_path` Rooted in TMPDIR (Purged by OS)

**Status**: ✅ Resolved (Phase 1: 2026-04-19, Phase 3: 2026-04-20)
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

**Status**: Open
**Severity**: Medium — Tier-1 recall gap on chart-native metrics (38 filings affected)
**Discovered**: 2026-04-19 (Phase 1 of the "missing Chart Evidence" investigation, commit `d1430d9`)

### Problem

The 2026-04-17 chart-OCR fix (`VisionClient.analyze_image()` now forces `response_format={"type": "json_object"}` and `_parse_chart_json` has a truncation-repair fallback — see `.claude/rules/v2-pipeline.md`) resolved malformed-JSON responses from gpt-4o going forward. Filings extracted before that fix can retain chart images (`v2_image_assets` rows with `classification='chart'`) but zero `source_type='chart'` facts, because the chart bridge silently dropped the malformed OCR output.

`scripts/diagnostic_chart_evidence_coverage.py` Class (E) reports **38 affected filings** on the local dev DB, with chart-image counts ranging from 14 to 22 per filing. Tier-1 chart-native metrics (`cm_revenue_by_cohort`, `cm_balance_by_cohort`, `cm_gross_margin_by_cohort`) take the brunt of the recall hit since those values typically live only in charts.

### Suggested Fix

Issue #34 Phase 3 (R2 backend) landed on 2026-04-19 — this backfill is now viable on both local dev and prod. Queue the 38 filings for re-extraction with `scripts/batch_v2_extraction.py --force-reextract` in a backfill window. The reviewed-filing guard (`V2PersistenceAdapter._persist_facts_in_tx`) must be honoured; any filings with prior reviewer decisions need explicit handling before re-extraction wipes `v2_review_decisions` via CASCADE.

Prod count is unknown — run the diagnostic against Neon before sizing the backfill.

### Cross-References

- `.claude/rules/v2-pipeline.md` — chart-OCR fix dated 2026-04-17 (the inflection point)
- Issue #34 — Phases 1 + 3 resolved 2026-04-19 (R2 backend live)
- Issue #24 — any backfill must also clear the 9 Class (B) orphan refs
- CLAUDE.md Core Design Principle #6 — reviewed-filing guard on re-extraction

---

## 36. `onboard_tickers.py populate` Has No `--limit`

**Status**: ✅ Resolved (2026-04-19, commit `366d9dd`)
**Severity**: Low — safety / operator footgun
**Discovered**: 2026-04-19 (during Issue #7 implementation)
**Resolved**: 2026-04-19

### Resolution

`UniverseBuilder.build_universe` gained an optional `limit: int | None = None` kwarg; the filing loop breaks once `limit` in-scope upserts are recorded. `scripts/onboard_tickers.py::cmd_populate` threads a new `--limit N` argparse flag into the kwarg. Default `None` preserves unbounded behaviour. Covered by `tests/unit/universe/test_universe_builder.py::test_limit_stops_after_n_in_scope_upserts`.

### Problem

`scripts/onboard_tickers.py populate --year YYYY [--form-type 10k]` wraps
`UniverseBuilder.build_universe` over every matching filing in the SEC
daily index for the year. With `--form-type 10k`, a single year is ~5–10k
filings at ~100ms per CIK (`get_company_info` submissions-API lookup) plus
daily-index reads — ~15 minutes of SEC traffic. There is no `--limit`
flag to cap the sweep.

An operator experimenting with onboarding can accidentally trigger a full
year-scale run; the only brake is Ctrl+C.

### Suggested Fix

Add `--limit N` to `cmd_populate` and thread an optional `limit: int | None`
kwarg into `UniverseBuilder.build_universe` (break out of the `for filing in
filings` loop after N in-scope upserts). Non-default parameter; default
preserves existing unbounded behavior.

Estimated ~20 LOC + 1 test. Independent of all other open issues.

### Cross-References

- `src/universe/universe_builder.py:51-108` (`build_universe`)
- `scripts/onboard_tickers.py::cmd_populate`
- Issue #7 — landed `--form-type` parameterization without `--limit` coverage

---

## 37. `classify_first_time_issuer` Reports `True` for Non-S-1/F-1 Filers

**Status**: ✅ Resolved (2026-04-19, commit `366d9dd`)
**Severity**: Low — misleading DB values, no functional impact today
**Discovered**: 2026-04-19 (during Issue #7 implementation)
**Resolved**: 2026-04-19

### Resolution

Option 1 from the suggested fix menu: `_process_filing` in `src/universe/universe_builder.py:176-189` now gates the `classify_first_time_issuer` call on `filing.form_type in DEFAULT_FORM_TYPES_S1F1`. Non-S-1/F-1 filings land with `is_first_time_issuer=NULL` and `fti_method="not_applicable"`; the classifier module itself is unchanged. Covered by `tests/unit/universe/test_universe_builder.py::test_10k_filing_has_null_first_time_issuer`.

### Problem

`classify_first_time_issuer(cik, filing_date, previous_ipo_date)` in
`src/universe/classifiers.py:92-128` is form-agnostic in its code: it
returns `(True, 'heuristic')` whenever `previous_ipo_date is None`, and
`get_first_ipo_filing_date(cik)` returns `None` for any CIK without a
prior S-1 in the DB — which is almost always the case when populating
10-Ks via `populate --form-type 10k`. Result: `filings.is_first_time_issuer`
is set to `TRUE` for 10-Ks where the concept is nonsensical.

Harmless at runtime because `is_in_scope_phase1(form_type=...)` gates on
form type first (classifiers.py:832-834) and returns `False` for 10-K
regardless of FTI. But the column has misleading data that would confuse
any downstream analytic query joining on `is_first_time_issuer`.

### Suggested Fix

Two options, in order of preference:

1. **Gate the call in `_process_filing`:** only invoke
   `classify_first_time_issuer` for `form_type in DEFAULT_FORM_TYPES_S1F1`;
   set `is_first_time_issuer=None` otherwise. Preserves classifier
   function's signature. ~10 LOC.
2. **Widen the classifier:** accept `form_type` and return `(None,
   'not_applicable')` for non-S-1/F-1 forms. Touches every caller.

Either approach: add a unit test asserting `filings.is_first_time_issuer
IS NULL` after a 10-K upsert.

### Cross-References

- `src/universe/classifiers.py:92-128` — `classify_first_time_issuer`
- `src/universe/universe_builder.py:165-173` — call site in `_process_filing`
- Issue #7 — introduced 10-K populate path that surfaces this

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

## 41. Review-UI Sticky Header Offset Mismatch + Narrow-Width Overlap Unverified

**Status**: ✅ Resolved (2026-04-19) — verified on deployed Render build
**Severity**: Low — cosmetic
**Discovered**: 2026-04-19 (during review-UI sticky-header work, commit `ba35424`)
**Resolved**: 2026-04-19

### Resolution

Shared `--navbar-height` CSS custom property introduced in `:root` (`src/web/static/css/review.css`) and applied to both `.sticky-top-below-nav` and `.review-sticky-header`. Compact-navbar styling (`.navbar.sticky-top` padding-y 0.25rem, `--navbar-height: 48px`) and a `.review-pill-row` flex-wrap class keep stat-pill badges from colliding with the "Next filing F" button at narrow widths. `unified_review.html:58` stat-pill row now uses `.review-pill-row`; `accepted`, `rejected`, and `img reviewed` badges removed to reduce horizontal load. Sticky-header vertical padding trimmed to absorb `container.mt-4` for a tighter gap under the navbar. Badge font size shrunk to 0.7rem.

Deployed Render build verified visually 2026-04-19 — sticky-header, pill-wrap, and navbar calibration land as intended. Code in commit `366d9dd`.

### Problem

Two related visual calibration items from the sticky review-UI landing:

1. **Sticky offset mismatch between old and new patterns.** The existing
   `.sticky-top-below-nav` class (`src/web/static/css/review.css:58-62`) —
   used by `.image-thumbnail-sidebar` and `.image-context-panel` on the
   images tab — uses `top: 70px`. The new `.review-sticky-header`
   introduced in `ba35424` uses `top: 56px` (Bootstrap `navbar-expand-lg`
   default). The navbar itself is now `sticky-top` as of `ba35424`. If
   the navbar renders at ~56px, the old sticky children have a ~14px gap
   between their top and the navbar bottom. If it renders at ~70px, the
   new sticky-header overlaps the navbar bottom by ~14px. Only one offset
   can be correct.

2. **Narrow-width responsive behavior not tested.** At viewport widths
   around 1024px, the stat-pill row in the review-page sticky header
   (`unified_review.html:44-72`) may wrap such that pills collide with
   the "Next filing F" button. Not verified in a browser; the user-chosen
   "three tighter rows" mockup implicitly relied on pills wrapping
   cleanly.

### Suggested Fix

Once the correct navbar rendered height is confirmed in production
DevTools:

1. Introduce a shared `--navbar-height` CSS custom property in `:root`
   (`review.css:9-53`) set to the measured value.
2. Update both `.sticky-top-below-nav` and `.review-sticky-header` to
   reference `top: var(--navbar-height);` so they stay aligned.
3. Resize the review page to ~1024px and adjust flex-wrap / pill styling
   in `unified_review.html:44-72` (or hide non-essential pills below a
   breakpoint) if pills overlap the "Next filing F" button.

Lightweight — <20 LOC of CSS, no template restructure.

### Cross-References

- `src/web/static/css/review.css:58-62` — existing `.sticky-top-below-nav`
- `src/web/static/css/review.css` (appended in `ba35424`) —
  `.review-sticky-header`
- `src/web/templates/base.html:21` — navbar `sticky-top`
- `src/web/templates/unified_review.html:44-72` — stat-pill row
- Commit `ba35424` — review-UI sticky compact top matter

---

## 42. `_download_missing_images` Writes Image Bytes Twice

**Status**: Open
**Severity**: Low — tech debt, not user-visible
**Discovered**: 2026-04-19 (noted while fixing Issue #34)

### Problem

`OCRExtractionStage._download_missing_images` (`src/extraction_v2/stages/ocr_extraction.py:199-263`) calls `SECClient.fetch_image()`, which already writes the bytes to `<image_cache_dir>/<cik_stripped>/<accession_no_dashes>/<filename>` via `SECClient._get_image_cache_path` (`src/infra/sec_client.py:880-889`). The pipeline then writes a second copy to `<image_cache_dir>/pipeline/<cik>/<accession>/<filename>` and stores that path on `asset.file_path`. Two on-disk copies per image, two path layouts, and the only reason `asset.file_path` doesn't point at SECClient's cache is historical — the flat `pipeline/<filename>` layout pre-dated SECClient caching and was never consolidated.

### Next Steps

1. Update `_download_missing_images` to call `self._sec_client._get_image_cache_path(cik, accession, filename)` (or a public equivalent) and assign the result to `asset.file_path` directly, skipping the pipeline `write_bytes` call.
2. Delete the now-unused `cache_dir = image_cache_dir() / "pipeline" / ...` construction.
3. Update `tests/unit/extraction_v2/test_image_pipeline_integration.py::TestImageDownloading` to assert `asset.file_path` is under the SECClient cache layout.
4. `image_cache_dir()` continues to be the single canonical root; just one layout underneath.

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

See Issue #30 resolution notes for full audit trail. Apply log at `data/audit/issue_30_applied_20260419T210109Z.jsonl`.

---

## 44. `audit_filing_url_mismatch.py` Classifier Over-Rotates on Legitimate Co-Registrant Sharing

**Status**: Open
**Severity**: Low — cosmetic/ergonomic; a human-in-the-loop confirms the override via `--include-path-c`
**Discovered**: 2026-04-19 (audit for Issue #30 classified all 15 rows as Path C when Path A was safe)

### Problem

`scripts/audit_filing_url_mismatch.py::_classify_path` treats `accession_collides_in_scope=True` OR `html_storage_path_shared_with≠[]` as a Path-C trigger. The logic was defensive: `FilingFetcher._update_database` filters `WHERE accession_number = %s`, so two rows sharing an accession would double-update during Path B refetch. That's correct for Path B.

But Path A is a per-row `UPDATE sec_html_url ... WHERE filing_id=%s` — collision-safe. And legitimate SEC multi-entity co-registrations (one filing, N co-registrants, N filings rows with identical accession_number) are the normal case, not corruption. The classifier's blanket downgrade to C pushes humans into using `--include-path-c` for a pattern that should just be Path A by default.

### Next Steps

Refine the classifier's decision tree:

```
if html_content_is_uber == False:
    return "A"                       # URL-only is sufficient
if reviews > 0 or img_reviews > 0 or in_gold_standard:
    return "C"                       # reviewer work at risk
if facts == 0 and no reviews:
    return "A"                       # URL-only safe; cached-HTML residue is latent — log follow-up
# else: facts > 0 and reviews == 0
if accession_collides or storage_shared:
    return "B_coordinated"           # one refetch, N row updates — new sub-path
return "B"                           # force-reextract in place
```

The `B_coordinated` sub-path is the correct design for the Spectrum Brands pattern *when* facts exist and need regeneration. For Issue #30 it wasn't needed because `facts=0`, but the classifier should know about it.

### Acceptance

- Rerunning the Issue #30 audit post-fix would classify the 15 rows as Path A automatically, without `--include-path-c`.
- A synthetic test case with `facts>0` AND shared accession/storage would classify as `B_coordinated`, not C.

---

## 45. `scripts/validate_database_urls.py` Missing `load_dotenv()`

**Status**: Open
**Severity**: Low — cosmetic (confusing UX); the script has a working connection path when the shell already exports `DATABASE_URL`
**Discovered**: 2026-04-19 (attempted verification run during Issue #30 resolution fell back to `localhost:5432` / non-existent `filings_analysis` DB)

### Problem

`scripts/validate_database_urls.py` does not call `load_dotenv()` before reading `DATABASE_URL`. Running it via `python3 scripts/validate_database_urls.py` in a shell that hasn't pre-exported `DATABASE_URL` (common during ad-hoc ops work) fails with a confusing `psycopg.OperationalError: connection to server at "127.0.0.1", port 5432 failed: FATAL: database "filings_analysis" does not exist` — psycopg's default-connect-without-DSN behavior.

Other scripts in the project (`batch_v2_extraction.py:48-53`, the new `audit_filing_url_mismatch.py`, `repair_filing_url_mismatch.py`) load the project's `.env` automatically.

### Fix

Add `from dotenv import load_dotenv` import and `load_dotenv()` call before the `DatabaseAdapter(db_url)` construction. ~3 lines.

Keep the error message when `DATABASE_URL` is still unset after `load_dotenv()` — that branch exists and is correct; this fix just populates the var first when a `.env` is present.

---

## Archive (Resolved Issues)

### Issue #1: Metric ID Mismatch Between Gold Standard and System

**Status**: ✅ Resolved (2026-03-16)

Gold standard CSV (`data/gold_standard/golden_set_251218.csv`) aligned to system taxonomy in `config/metric_keywords.yaml`. No remaining ID mismatches. See git log (2026-03-16) for full resolution details.

### Issue #6: FilingFetcher Downloads Directory Index Instead of Primary Document

**Status**: ✅ Resolved (2026-03-16)

`FilingFetcher` defaulted `sec_client` to `None` and guarded URL resolution behind `if self.sec_client:`, causing directory-index pages to be saved instead of actual filings. Fixed in `src/filing_fetcher/filing_fetcher.py` (lines 81, 295). 78 cloud-fetched filings need re-fetching on Render. See git log (2026-03-16) for full details.

### Issues #7 and #8: Test Deadlock and Connection Pool Exhaustion

**Status**: ✅ Resolved (2026-03-26)

Root cause: `DatabaseAdapter` had no `close()` method; test fixtures were session-scoped with no teardown and no connection pool, so every `get_connection()` call created a new TCP connection.

Fixes applied:
- Added `DatabaseAdapter.close()` to `src/infra/db.py`
- Converted `test_db_adapter` fixtures in `tests/integration/conftest.py` and `tests/integration/extraction/conftest.py` from `return` to `yield` with pool (`max_size=5`) and teardown
- Added `command: ["postgres", "-c", "max_connections=200"]` to `docker-compose.yml`

### Issue #3: Gold Standard Methodology Questions

**Status**: ✅ Resolved (2026-03-26)

Created `docs/GOLD_STANDARD_SPECIFICATION.md` covering: metric ID alignment, value normalization rules, chart vs text classification, period format, negative examples, and duplicate group handling.

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
