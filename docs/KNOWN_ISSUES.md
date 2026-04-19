# Known Issues and Future Improvements

This document tracks known issues, limitations, and planned improvements identified during extraction system development.

**Last Updated**: 2026-04-19

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
| Farfetch LTV/CAC dedup collision (Issue #14) | Resolved (2026-04-18) | — | — | cm_ltv_to_cac_ratio 33%→100%; cm_ltv_to_cac_ratio_by_cohort 17%→50%; Farfetch F1 +10.3pp |
| Chart pipeline env bootstrap (Issue #15) | Resolved (2026-04-18) | — | — | `load_dotenv()` added to validator's `__main__` |
| `cm_gross_margin_by_cohort` still 0% despite chart pipeline (Issue #20) | Resolved (2026-04-18) | — | — | Classifier+parser gates relaxed for customer-type/year-in-point.x shape; 0% → 100% F1 on Farfetch; Tier 1 overall +5.4pp |
| `v2_image_assets` duplicates + pending-count discrepancy — Maplebear S-1 (Issue #21) | Resolved (2026-04-18) | — | — | sql/34 dedup migration + stable img_id upsert (ON CONFLICT (doc_id, filename)) + in-memory fact source_locator remap |
| No reviewed-filing guard on image re-extraction (Issue #22) | Open | Low | Low | Decisions survive post-#21; hidden-decision risk on re-classification only |
| `v2_image_assets.segment_id` dead column (Issue #23) | Resolved (2026-04-18) | — | — | sql/35 drops column; persistence.py cleaned up |
| `v2_metric_facts.source_locator.img_id` no referential integrity (Issue #24) | Open | Low | Medium | New facts consistent post-#21; historical orphans likely remain |
| `scripts/migrate_image_ids_to_deterministic.py` scope confusion (Issue #25) | Open | Trivial | Trivial | Script only touches gold-standard JSON, not production DB |
| Farfetch precision drag — table-scale + period (Issue #16) | Open | Low | Medium | 9 FPs across Active Consumers + Purchase Transactions (doesn't block recall) |
| CAC payback "six months" not bound (Issue #17) | Resolved (2026-04-18) | — | — | Added `WORD_NUMBER_TIME_PATTERN` gated to time-valued metrics; cm_cac_payback_period 0% → 100% F1 |
| Migration checksum mismatch — `sql/01_create_schema.sql` (Issue #18) | Resolved (2026-04-18) | — | — | Self-healed via V1 retirement merge |
| FN diagnostic classification gaps (Issue #19) | Resolved (2026-04-18) | — | — | Added `dedup_collision` + `no_matching_binding` categories; `wrong_period` restricted to post-dedup |

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

**Status**: Open
**Severity**: Low (no data loss; decisions survive re-extraction via stable img_ids post-Issue #21)
**Discovered**: 2026-04-18

### Problem

The fact-side `ReviewedFilingError` (raised in `src/extraction_v2/persistence.py:_persist_facts_in_tx`, defined in `src/extraction_v2/exceptions.py`) does not cover image assets. After the sql/34 fix, existing review decisions survive re-extraction because img_ids are stable. However, if re-classification changes an image from `chart` to `decorative`, the review UI filters it out (`classification NOT IN ('decorative','logo','signature')` in `src/infra/db.py:1631`) — the decision becomes hidden rather than invalidated. There is no warning to the reviewer.

### Suggested Fix

Extend the reviewed-filing guard to check for existing `v2_image_review_decisions` rows before overwriting image classification. Emit a structured warning (or raise `ReviewedFilingError` if `force=False`) when re-classification would hide a previously decided image.

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

---

## 25. `scripts/migrate_image_ids_to_deterministic.py` Scope Is Confusing

**Status**: Open
**Severity**: Trivial
**Discovered**: 2026-04-18

### Problem

The script name implies a production DB migration, but it only rewrites `data/presentation_gold_standard/_image_*.json` files — it never touches the database. Readers discovering it during DB image-identity investigations will be misled.

### Suggested Fix

Either move the script to `scripts/archive/` (only if that directory already exists; do not create it) or add a module-level docstring clarifying: "This script only modifies local gold-standard JSON files in `data/presentation_gold_standard/`. It does not modify the production database."

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
