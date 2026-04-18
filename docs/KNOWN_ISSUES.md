# Known Issues and Future Improvements

This document tracks known issues, limitations, and planned improvements identified during extraction system development.

**Last Updated**: 2026-04-18

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

- Upsert Snap with correct CIK `0001564408` and add to gold standard (separate task, not blocking)

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
| `cm_ltv_to_cac_ratio` | T1 | 100% | 33% | 50% | 2 FNs — dedup collision (see #14) |
| `cm_ltv_to_cac_ratio_by_cohort` | T1 | 100% | 17% | 29% | 2 FNs — dedup collision (see #14) |
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
5. **Layout-table dedup collision** — new root cause: see #14.
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

## Summary

| Issue | Status | Priority | Effort | Impact |
|-------|--------|----------|--------|--------|
| Low Farfetch Recall (Issue #2) | Re-diagnosed umbrella | Medium | — | Superseded by sub-issues #14–#19; P=50% R=37% F1=42% on 2026-04-18 |
| Gold Standard Methodology | Resolved | — | — | Spec doc created |
| Spelled-Out Number Limits | Open | Low | High | Edge case coverage |
| Revenue Synonym Gating | Monitor | N/A | N/A | Working as designed |
| Gold Standard Coverage Tests (Issue #11) | Partially resolved | Low | Medium | 11/12 pass; 1 remaining (now linked to Issue #10 re-scope) |
| Snap Filing Mislabeled (Issue #9) | Partially resolved | Low | Low | Snap not in gold standard; validation DB no longer required |
| `test_candidate_generation_finds_active_consumers` (Issue #10) | Re-scoped | Low | Low | Original CMS-1 hypothesis disproven; real root cause TBD |
| `test_image_crop.py` pollutes `data/` (Issue #12) | Resolved (2026-04-18) | — | — | `make_png_in_data_dir` fixture cleans up on teardown |
| V2 metric facts identity index drift (Issue #13) | Migration prepared (sql/33) | Low | Low | DB index 8 cols; sql/33 recreates 9-col index; pending prod apply |
| Farfetch LTV/CAC dedup collision (Issue #14) | Open | Medium | High | 4 T1 FNs from layout-table misclassification → shared cohort_def → identity collision |
| Chart pipeline env bootstrap (Issue #15) | Resolved (2026-04-18) | — | — | `load_dotenv()` added to validator's `__main__` |
| `cm_gross_margin_by_cohort` still 0% despite chart pipeline (Issue #20) | Open | Medium | Medium | 10 Farfetch T1 FNs; 2026-04-17 chart fix didn't lift metric; needs chart_fact_bridge investigation |
| Farfetch precision drag — table-scale + period (Issue #16) | Open | Low | Medium | 9 FPs across Active Consumers + Purchase Transactions (doesn't block recall) |
| CAC payback "six months" not bound (Issue #17) | Open | Low | Low | Bare word-number + time unit isn't parsed (1 FN on Farfetch + likely others) |
| Migration checksum mismatch — `sql/01_create_schema.sql` (Issue #18) | Open | Low | Low | Blocks pytest gold standard; v2_validator module path works |
| FN diagnostic classification gaps (Issue #19) | Open | Low | Low | 3 of 3 investigated categories misclassified on 2026-04-18 |

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

**Status**: Migration prepared; pending prod apply (`sql/33_fix_identity_index.sql`)
**Severity**: Low (application-layer dedup in `MetricFact.identity_tuple()` still distinguishes `source_type`; no observed duplicate-row incidents)
**Discovered**: 2026-04-18

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

### References

- `sql/33_fix_identity_index.sql` — fix migration (pending prod apply)
- `docs/architecture/data-model.md` — "Known Discrepancies" section
- `sql/23_chart_source_dedup.sql` — original 9-column DDL intent
- `src/extraction_v2/models.py::MetricFact.identity_tuple` — 9-element tuple
- `src/extraction_v2/persistence.py` — delete-then-insert persistence (lines 663–726)

---

## 10. `test_candidate_generation_finds_active_consumers` — Root Cause Unclear

**Status**: Re-scoped 2026-04-18 (original description was inaccurate)
**Severity**: Low
**Discovered**: 2026-03-26
**Re-diagnosed**: 2026-04-18

### Problem

`tests/integration/test_gold_standard_coverage.py::TestCandidateGeneration::test_candidate_generation_finds_active_consumers` fails. Original report claimed this was CMS-1 suppression assigning Active Consumers to `cm_customers_period_end`.

### 2026-04-18 Re-Diagnosis

The CMS-1 suppression hypothesis is **not supported by data**:

- `config/metric_keywords.yaml:120-212` shows `cm_customers_period_end` has **no "Active Consumers" pattern**. Only `cm_active_customers_total` (lines 325, 355) matches `\bactive\s+consumers?\b`.
- Pipeline-level validation (`python3 -m src.gold_standard.v2_validator --companies "Farfetch Limited" --fn-diagnostics`) shows `cm_active_customers_total` recall = **100%** for Farfetch. No misassignment occurring at the pipeline level.
- The integration test failure is at the **candidate-generation layer** (not full pipeline), which may use different matching rules than what the pipeline eventually resolves.

### Remaining Question

Why does `test_candidate_generation_finds_active_consumers` still fail if pipeline recall is 100%? Hypotheses:
- Candidate-generation-only path has a CMS-1 behavior that the downstream pipeline overrides.
- The test's expectation differs from what the pipeline produces (e.g., checks candidate metric assignment directly).
- Some other keyword (not "Active Consumers" itself) triggers a cross-metric suppression that later stages resolve.

### Next Steps

- Re-run the failing test with debug logging to see what candidate(s) it actually produces.
- Compare that against what the full pipeline emits for the same segment.
- If the full pipeline is correct and only the unit test is stale, update the test assertion (not the pipeline).
- Until re-diagnosed, the test remains skipped/xfail; this does NOT affect Farfetch recall (Issue #2).

---

## 14. Farfetch LTV/CAC Dedup Collision on Layout Tables

**Status**: Open
**Severity**: Medium (4 Tier 1 FNs on Farfetch)
**Discovered**: 2026-04-18

### Problem

Farfetch's LTV/CAC cohort values (1.42, 1.53, 1.77) are all correctly extracted pre-dedup but collapse to a single surviving fact (1.77) per metric, producing 4 Tier 1 FNs on `cm_ltv_to_cac_ratio` + `cm_ltv_to_cac_ratio_by_cohort`.

### Root Cause Chain

1. The filing has a bullet-point rendered via HTML `<TABLE>` used purely for layout (indent + `&#149;` + prose `<TD>`). No semantic data table.
2. `table_reconstruction` classifies this layout table as a data table; extracts "1.42, 1.53, 1.77" as three cells; uses the whole prose sentence "Six month LTV/CAC ratio for the years ended December 31, 2015, 2016 and 2017 cohorts was 1.42, 1.53 and 1.77, respectively" as `header_path`.
3. `fact_construction.py:441 _extract_cohort_def` parses the prose as an "acquisition" cohort label (matches year pattern) → assigns the **entire sentence** as `cohort_def` for all 3 facts.
4. All 3 facts share an identical 9-column identity tuple (metric + period=2015-12-31 + unit + scope + same cohort_def + customer_type + source_type). Value is NOT part of identity.
5. `deduplication.py:375 _collapse_post_transfer_collisions` enforces the DB unique index (`sql/23_chart_source_dedup.sql`). Drops 2 of 3; keeps 1.77 (highest value_raw tie-break).

Confirmed 2026-04-18 via `/tmp/diag_farfetch_ltvcac.py`: pre-dedup has 6 LTV/CAC facts; post-dedup has 2.

### Fix Options

- **(a) Layout-table detection** in `table_reconstruction`: skip reconstruction when the table has a single row, no header row, and a cell containing `&#149;` or long prose. Correct but architectural; affects many filings.
- **(b) "Respectively" pattern parser** for `cohort_def`: when the header is a long prose sentence containing parallel number-list + cohort-list ("A, B, C respectively for X, Y, Z"), extract per-position cohort year. Targeted but pattern-specific; FP risk.
- **(c) Add `value` to DB unique index** + relax dedup collision logic. Highest blast radius; needs migration.

Not fixing this session. Tracked for future layout-table-detection work.

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

**Status**: Open
**Severity**: Low (1 Farfetch T2 FN; likely also affects other filings)
**Discovered**: 2026-04-18

### Problem

Farfetch gold expects `cm_cac_payback_period = 6` (unit: months) from the prose "the payback period on CAC has been consistently less than six months." The pipeline generates the correct candidate (match="payback period on CAC") but produces **0 value bindings**.

### Root Cause

`value_binding.py:152-161 WORD_NUMBER_PATTERN` requires a scale suffix (`million`/`billion`/`trillion`/`thousand`). Bare word-numbers followed by a time unit (e.g., "six months", "twelve weeks") are not matched. So "six" isn't parsed as 6.

### Historical Note

KNOWN_ISSUES.md previously claimed this was fixed via "Spelled-out number support added to handle 'six'". The claim was **inaccurate** — support was added only for scaled forms (e.g., "six million"), not for bare word-numbers followed by time units.

### Fix Options

- **Narrow regex**: add `WORD_NUMBER_TIME_PATTERN` for `(one|...|twelve)\s+(days?|weeks?|months?|years?|quarters?)`. Small diff.
- **FP risk**: bare word-numbers elsewhere in prose could bind to unrelated candidates ("the past six months" as a period reference could get bound as a value).
- **Mitigation**: either (a) gate this parser to specific metrics that expect time-unit values, or (b) add an FP rule that rejects time-unit-word-numbers when they appear in period contexts.

Not fixing this session.

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

**Status**: Open
**Severity**: Medium (10 Tier 1 FNs on Farfetch; likely blocks other chart-heavy companies)
**Discovered**: 2026-04-18

### Problem

With `OPENAI_API_KEY` properly loaded (Issue #15 resolved) and chart/vision stages running, `cm_gross_margin_by_cohort` shows **P=0%, R=0%, F1=0%** on Farfetch's 9 chart-sourced gold rows — unchanged from the pre-chart-pipeline state.

### Context

`.claude/rules/v2-pipeline.md` states:
> `cm_gross_margin_by_cohort` — F1=0% pre-fix. GS: 9 FTCH rows, all chart images. Previously blocked by malformed vision JSON; fix applied 2026-04-17 (JSON mode + truncation-repair fallback). Re-measure GS to confirm lift.

The 2026-04-18 baseline refresh (23 chart facts produced end-to-end) **is** that re-measurement. The fix did not lift `cm_gross_margin_by_cohort` for Farfetch.

### Working Hypotheses (not yet diagnosed)

1. The Farfetch Order Contribution Margin charts are tagged by the chart classifier to a different metric (e.g., none, or `cm_revenue_by_cohort` which did gain F1 26.3%).
2. The vision OCR returns data but the chart_fact_bridge rejects or reassigns it (see `chart_fact_bridge.py`).
3. Axis range multiplier rejection (`chart_axis_range_multiplier: 10.0`) or review threshold drops facts.
4. Farfetch charts fail `chart_image_min_confidence` (0.6).

### Next Steps

- Run `python3 -m src.gold_standard.v2_validator --companies "Farfetch Limited" --fn-diagnostics --workers 1` with vision enabled and inspect the FN categories for `cm_gross_margin_by_cohort`.
- Add temporary debug logging to `chart_fact_bridge.py` to trace which stage drops/reassigns the facts.
- Cross-check against HOOD (`cm_balance_by_cohort` F1=57% with chart pipeline) to understand why HOOD charts bridge successfully but Farfetch's don't.

---

## 19. FN Diagnostic Classification Gaps

**Status**: Open (diagnostic tool quality)
**Severity**: Low (misleads investigation but doesn't affect production)
**Discovered**: 2026-04-18

### Problem

The FN root-cause analysis in `src/gold_standard/v2_validator.py` (lines 900–1040) classified three Farfetch FNs into misleading categories during 2026-04-18 diagnosis:

1. **`cm_ltv_to_cac_ratio` classified as `wrong_period`**. Actual root cause: dedup collision from shared `cohort_def` (Issue #14). The category fires because the diagnostic's `all_metric_facts` set includes pre-dedup facts — so the "value matches but period doesn't" check hits even when the matching fact was later dropped by dedup.
2. **`cm_revenue_by_cohort` classified as `fp_filtered`**. Actual root cause: the 2 removed bindings were date fragments (`31`, `2017`) from a different candidate; the expected 44.4%/55.6% values were never bound to any candidate at all (chart-sourced, blocked by API key).
3. **`cm_cac_payback_period`** would likely misclassify as well (candidate exists with 0 bindings — either `no_value_binding` or similar), but the diagnostic for this case is less critical.

### Impact

Each misleading classification cost ~30 minutes of investigation time that could have been avoided with more precise categorization.

### Next Steps

- `wrong_period` category: only emit when the matched fact is in `deduplicated_facts` (not in pre-dedup `context.facts`). If the fact was dropped by dedup, emit a `dedup_collision` category instead.
- `fp_filtered` category: check that the removed bindings' values actually match the expected value before emitting this classification. If they don't, emit `wrong_candidate_binding` or `value_not_bound`.
- Consider adding a `candidate_count_by_value` check so "expected value X but no candidate bound near X" is distinguished from "candidate bound X to wrong metric".

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
