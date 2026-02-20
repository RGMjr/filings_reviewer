# Analysis Results: Chart Extraction Live Validation & V2 Gold Standard Integration

**Date**: 2026-02-11
**Branch**: v2-rewrite

---

## TASK-1: Live Farfetch Chart Extraction — SUCCESS

### nearby_text fix verified

The `_get_nearby_text()` parent-sibling fallback works correctly on the Farfetch filing. For the chart image `g607688g12o45.jpg` (embedded as `<P><IMG/></P>`), it captures **958 characters** of context from sibling `<P>` elements, including:

- "GMV from our Marketplace by consumer cohort"
- "Existing consumers generated 55.6%"
- "new consumers as those who placed their first order"

### GPT-4o annotation extraction verified

Live GPT-4o call on the Farfetch stacked area chart returned:

| Field | Value |
|---|---|
| chart_type | `area` |
| title | (empty) |
| y_axis_label | `Marketplace GMV (USDm)` |
| series | 0 (no data-point labels — correct) |
| annotations | **2** |
| confidence | 0.90 |

**Annotations extracted:**

| text | value | unit | category | period |
|---|---|---|---|---|
| "44.4% New Consumers in 2017" | 44.4 | percent | New Consumers | 2017 |
| "55.6% Existing Consumers in 2017" | 55.6 | percent | Existing Consumers | 2017 |

### Candidate generation verified

| metric_id | match_text | confidence | source |
|---|---|---|---|
| `cm_new_customers_acquired` | "New Consumers" | 0.700 | annotation text |
| `cm_revenue_by_cohort` | "GMV from our Marketplace by consumer cohort" | 0.650 | nearby_text (-0.05 penalty) |

### Value binding verified

`cm_revenue_by_cohort` bound to 2 annotation values:
- 44.4% (New Consumers, chart_annotation, conf=0.765)
- 55.6% (Existing Consumers, chart_annotation, conf=0.765)

### Pipeline gap: local image resolution

The **full V2 pipeline** cannot extract from Farfetch charts because:
1. Ingestion discovers images but only stores `filename`, not `file_path`
2. `_download_missing_images()` needs real CIK/accession to fetch from SEC EDGAR
3. Gold standard metadata has placeholder CIK/accession (`"0000000000"`)
4. The chart image exists at `data/gold_standard/Farfetch_Limited/g607688g12o45.jpg` but the pipeline has no mechanism to resolve images relative to the filing HTML path

**Action needed**: Add local image resolution to the V2 pipeline.

---

## TASK-2: V2 Gold Standard Baseline (Text-Only)

### Results

| Company | V2 Precision | V2 Recall | V2 F1 | V1 Precision | V1 Recall | V1 F1 |
|---|---|---|---|---|---|---|
| Slack Technologies | 2.8% | 87.5% | 5.4% | 100% | 91.7% | 95.7% |
| Farfetch Limited | 2.8% | 30.6% | 5.2% | 83.3% | 70.0% | 76.1% |
| Snowflake Inc | 4.0% | 49.5% | 7.4% | 96.3% | 26.0% | 40.9% |
| **Overall** | **3.2%** | **52.6%** | **6.1%** | **90.8%** | **53.7%** | **67.5%** |

### Analysis

**V2 recall is comparable to V1** (52.6% vs 53.7%).

**V2 precision is catastrophically low** (3.2% vs 90.8%) because the V2 pipeline outputs **all** bound values as MetricFacts (3,299 FP), while V1 uses aggressive FP filtering in `CandidateGenerator`.

**Root cause**: The V2 validator treats every MetricFact as a positive prediction regardless of confidence. In production, only facts above `min_confidence_auto_accept` (0.90) would be auto-accepted.

**Action needed**: V2 gold standard validator must filter by confidence threshold before computing precision.

### Samsara Vision Inc. missing

Company directory name mismatch not resolved by `_find_filing_path()`.

---

## TASK-3: Gold Standard Gap Analysis for Charts

### Current chart entries

Only **2 entries** across 229 gold standard rows are chart-sourced:

| Company | metric_id | raw_value | segment_type |
|---|---|---|---|
| Farfetch | `cm_revenue_by_cohort` | `chart` | chart |
| Slack | `cm_arr` | `chart` | chart |

Both have `raw_value = "chart"` — no numeric values. They are skipped as definition-only by the validator.

### What's needed for chart gold standard

**Minimum viable changes:**

1. **Replace** existing Farfetch `cm_revenue_by_cohort` entry with 2 annotation-level rows:
   - `cm_revenue_by_cohort | 44.4 | percent | 2017 | chart_annotation`
   - `cm_revenue_by_cohort | 55.6 | percent | 2017 | chart_annotation`

2. **Add `source_type` column** (or encode in segment_type) to distinguish `text`, `table`, `chart_annotation`, `table_image`

3. **Fix local image resolution** so pipeline can process gold standard images

4. **Add confidence thresholding** to V2 validator

---

## TASK-4: V2 Precision Improvement (2026-02-16)

### Objective

Improve V2 gold standard precision from 58% toward 90% while maintaining recall.

### Baseline (after confidence thresholding at 0.50)

| Metric | Value |
|---|---|
| Precision | 58.0% |
| Recall | 54.1% |
| F1 | 55.9% |
| TP / FP / FN | 80 / 58 / 68 |

### FP Diagnostic Findings

Added `FalsePositiveDiagnostic` instrumentation to `v2_validator.py`. FP breakdown:
- **value_mismatch**: 51 (88%) — wrong numbers near keywords
- **duplicate_value**: 3 (5%) — same value extracted from multiple sources
- **no_match**: 2 (3%) — metric not in gold standard
- **scale_factor**: 2 (3%) — table "(In thousands)" not applied

By source: 41 text FPs, 11 table FPs.

### Fixes Applied

| Fix | Change | Impact |
|---|---|---|
| **C: Same-sentence priority** | Text binding: keep all same-sentence matches, only closest for out-of-sentence | -6 FPs, 0 TP loss |
| **C.1: Proximity window 250→100** | Tighter text proximity window | -6 FPs, -2 TPs |
| **D: Table scale detection** | Detect "(In thousands/millions)" in headers, apply to currency only | Neutral (mixed tables) |
| **F: Percent-only unit tightening** | Remove Unit.OTHER from percent-only metrics; add percent range (>500) and garbage value (>10B) FP rules | **-14 FPs**, -2 TPs |

### Fixes Attempted & Reverted

| Fix | Issue |
|---|---|
| **A: Fuzzy period dedup** | Collapsed legitimate same-value/different-period facts. P=44%, R=24%. |
| **H: Scale COUNT metrics** | Financial tables mix dollar and count columns under one scale header. Broke Snowflake (-4 TPs, +7 FPs). |
| **E: Confidence threshold >0.50** | Recall cliff at 0.55 (R drops from 53% to 20%). No viable threshold above 0.50. |

### Final Results

| Metric | Before | After | Delta |
|---|---|---|---|
| **Precision** | 58.0% | **70.1%** | **+12.1 pts** |
| **Recall** | 54.1% | 51.7% | -2.4 pts |
| **F1** | 55.9% | **59.5%** | **+3.6 pts** |
| **FPs** | 58 | 32 | **-26 eliminated** |

### Per-Company Breakdown

| Company | Before P | After P | TPs | FPs | FNs |
|---|---|---|---|---|---|
| Snowflake | 77% | **91%** | 31 | 3 | 18 |
| Samsara | 100% | **100%** | 2 | 0 | 0 |
| Slack | 58% | **68%** | 28 | 13 | 16 |
| Farfetch | 47% | **47%** | 14 | 16 | 36 |

### Remaining 32 FPs (Harder to Fix)

- **11 Farfetch table FPs**: Scale factor for count metrics in mixed financial/count tables — can't distinguish columns
- **5 duplicate values**: Same value from multiple source types (dedup too aggressive when attempted)
- **5 NRR text FPs**: Values 8-351 near NRR keyword (within valid percent range)
- **4 revenue_concentration**: Wrong percentages near keyword (34%, 36%, 37% vs gold 10%, 47%)
- **7 other text FPs**: Small numbers (20, 30, 65) near keywords; AOV value mismatches

### Files Modified

- `src/extraction_v2/stages/value_binding.py` — proximity window, same-sentence priority, table scale detection
- `src/extraction_v2/stages/false_positive_filter.py` — percent range + garbage value FP rules
- `src/extraction_v2/unit_compatibility.py` — removed Unit.OTHER from percent-only metrics
- `src/extraction_v2/stages/deduplication.py` — fuzzy period methods added (not called)
- `src/gold_standard/v2_validator.py` — FP diagnostic infrastructure
- `tests/unit/extraction_v2/test_value_binding.py` — updated for new proximity window
- `tests/unit/extraction_v2/test_unit_compatibility.py` — updated for stricter percent-only units

### Test Results

4,374 passed, 17 skipped, 0 failures. 80.62% coverage (exceeds 75% minimum).

---

## Action Items (Priority Order)

| # | Action | Effort | Blocks |
|---|---|---|---|
| 1 | Add local image resolution in V2 pipeline ingestion/OCR | Small | Chart validation |
| 2 | ~~Fix V2 validator precision — confidence threshold~~ DONE (Task-4) | — | — |
| 3 | Add chart annotation rows to Farfetch gold standard | Small | Chart regression tests |
| 4 | ~~Fix Samsara directory lookup in V2 validator~~ DONE | — | — |
| 5 | Add `source_type` column to gold standard CSV | Medium | Clean schema |
| 6 | Run Slack chart through GPT-4o, add annotation rows | Small | Slack chart coverage |
| 7 | Re-save V2 baseline after validator fix | Tiny | Accurate V2 baseline |
| 8 | Farfetch table column-aware scale factors | Medium | Farfetch P improvement |
| 9 | Improve text FP filtering (NRR context, small-number filter) | Medium | Slack P improvement |

---

# WP-01: Slack Technologies FN/FP Analysis

**Date**: 2026-02-19
**Branch**: v2-rewrite
**Analyst**: Automated diagnostic run via `src/gold_standard/v2_validator.py`

---

## Score Summary

| Pipeline | Precision | Recall | F1 | TP | FP | FN |
|---|---|---|---|---|---|---|
| V1 (baseline, `baseline_metrics.json`) | 91.7% | 91.7% | 91.7% | — | — | — |
| V2 (stored, `v2_baseline.json`, 2026-02-18) | 68.3% | 63.6% | 65.9% | — | — | — |
| V2 (current run, 2026-02-19, min_conf=0.50) | 60.0% | 39.5% | 47.6% | 15 | 10 | 23 |

Gold standard entries evaluated: **38** (after skipping definition-only and chart-value entries).

**Regression**: V2 F1 (47.6%) is 44.1 percentage points below V1 (91.7%). Since the stored V2 baseline (65.9%) is also lower than the current run (47.6%), there is an additional 18.3 pt regression on the current branch vs. the Feb-18 baseline.

---

## False Negative Analysis (23 FNs)

The FN diagnostic tool (`fn_diagnostics=True`) was run on all 23 false negatives. The tool's `wrong_period` label requires reinterpretation: in every case where `wrong_period` was reported, the corrected root cause is `low_confidence` — the value IS correctly extracted but the deduplication stage retains a lower-confidence variant that falls below the 0.50 threshold used for `v2_facts`.

### FN Table

| # | metric_id | Expected Value | Period | Diag Label | Corrected Root Cause | Notes |
|---|---|---|---|---|---|---|
| 1 | `cm_arr` | chart | 31-Jan-19 | low_confidence | low_confidence | ARR is chart-only; max extracted conf=0.41 |
| 2 | `cm_customers_period_end` | 500,000 | 31-Jan-19 | wrong_period | low_confidence | conf=0.41 below 0.50 threshold |
| 3 | `cm_customers_period_end` | 500,000 | 31-Jan-19 | wrong_period | low_confidence (duplicate entry) | Second identical gold entry; same conf issue |
| 4 | `cm_customers_period_end` | 42,000 | 30-Apr-17 | wrong_period | low_confidence | conf=0.41; quarterly table row |
| 5 | `cm_customers_period_end` | 47,000 | 31-Jul-17 | wrong_period | low_confidence | conf=0.41; quarterly table row |
| 6 | `cm_customers_period_end` | 52,000 | 31-Oct-17 | wrong_period | low_confidence | conf=0.41; quarterly table row |
| 7 | `cm_customers_period_end` | 73,000 | 31-Jul-18 | wrong_period | low_confidence | conf=0.41; quarterly table row |
| 8 | `cm_customers_period_end` | 81,000 | 31-Oct-18 | wrong_period | low_confidence | conf=0.41; quarterly table row |
| 9 | `cm_large_customers_period_end` | 164 | 4/30/17 | wrong_period | low_confidence | conf=0.41; quarterly table row |
| 10 | `cm_large_customers_period_end` | 209 | 7/31/17 | wrong_period | low_confidence | conf=0.41; quarterly table row |
| 11 | `cm_large_customers_period_end` | 254 | 10/31/17 | wrong_period | low_confidence | conf=0.41; quarterly table row |
| 12 | `cm_large_customers_period_end` | 412 | 7/31/18 | wrong_period | low_confidence | conf=0.41; quarterly table row |
| 13 | `cm_large_customers_period_end` | 491 | 10/31/18 | wrong_period | low_confidence | conf=0.41; quarterly table row |
| 14 | `cm_net_revenue_retention` | 171% | 31-Jan-17 | wrong_period | low_confidence | conf=0.49 below 0.50 threshold |
| 15 | `cm_net_revenue_retention` | 152% | 31-Jan-18 | wrong_period | low_confidence | conf=0.49 below 0.50 threshold |
| 16 | `cm_net_revenue_retention` | 149% | 30-Apr-18 | wrong_period | low_confidence | conf=0.49 below 0.50 threshold |
| 17 | `cm_net_revenue_retention` | 171% | 31-Jan-17 | wrong_period | low_confidence (duplicate entry) | Second identical gold entry; same issue |
| 18 | `cm_net_revenue_retention` | 152% | 31-Jan-18 | wrong_period | low_confidence (duplicate entry) | Second identical gold entry; same issue |
| 19 | `cm_net_revenue_retention` | 156% | 30-Apr-17 | wrong_value | wrong_value (gold scale error) | Gold encodes as 1.56 (scaled); V2 extracts 156.0 |
| 20 | `cm_net_revenue_retention` | 153% | 31-Jul-17 | wrong_value | wrong_value (gold scale error) | Gold encodes as 1.53 (scaled); V2 extracts 153.0 |
| 21 | `cm_net_revenue_retention` | 151% | 31-Oct-17 | wrong_value | wrong_value (gold scale error) | Gold encodes as 1.51 (scaled); V2 extracts 151.0 |
| 22 | `cm_net_revenue_retention` | 146% | 31-Jul-18 | wrong_value | wrong_value (gold scale error) | Gold encodes as 1.46 (scaled); V2 extracts 146.0 |
| 23 | `cm_net_revenue_retention` | 144% | 31-Oct-18 | wrong_value | wrong_value (gold scale error) | Gold encodes as 1.44 (scaled); V2 extracts 144.0 |

### FN Root Cause Summary

| Root Cause | Count | % of FNs |
|---|---|---|
| **low_confidence** (value extracted at conf < 0.50) | 18 | 78% |
| **wrong_value** (gold standard scale encoding mismatch) | 5 | 22% |
| **no_candidate** | 0 | 0% |
| **no_value_binding** | 0 | 0% |
| **fp_filtered** | 0 | 0% |
| **dedup_removed** | 0 | 0% |

**Note on diagnostic label accuracy**: The `v2_validator.py` FN diagnostic reports 17 cases as `wrong_period`. These are actually `low_confidence` misclassifications. The diagnostic traces through pre-dedup context facts (which include facts at conf=0.41–0.49) and reaches the `wrong_period` branch because value-matched facts exist in context but not in the post-threshold `v2_facts` list. The diagnostic should add a confidence check step before the `wrong_period` branch.

---

## False Positive Analysis (10 FPs)

All 10 FPs fall into the `value_mismatch` mismatch category per the diagnostic tool. Root causes by type:

### FP Table

| # | metric_id | Extracted Value | Actual Context | Root Cause Category | Details |
|---|---|---|---|---|---|
| 1 | `cm_daily_active_users` | 500,000 | "more than 500,000 registered developers" (div[1109]) | wrong_metric_context | 500k is developer count, not DAU; true DAU is 10 million |
| 2 | `cm_customers_period_end` | 65 | "including more than 65 of the companies in the Fortune 100" (div[1243]) | wrong_entity | Fortune 100 company count, not paid customer count |
| 3 | `cm_customers_period_end` | 18 (from "018") | "fiscal years 2017, 2018, and 2019" (div[766]) | year_split_artifact | "018" extracted from "2018" by number regex; year-split bug |
| 4 | `cm_large_customers_period_end` | 18 (from "018") | Same as above (div[766]) | year_split_artifact | Same "018" from "2018" assigned to both CPE and large_CPE |
| 5 | `cm_large_customers_period_end` | 20 | "2019" year reference (div[1148]) | year_split_artifact | "20" extracted from "2019" by number regex; year-split bug |
| 6 | `cm_net_revenue_retention` | 298 | Large customers table row: "Paid Customers >$100,000: 135, 298, 575, 351, 645" (div[158]) | metric_confusion | NRR keyword captured a large_customers table value |
| 7 | `cm_net_revenue_retention` | 351 | Same large customers table (div[158]) | metric_confusion | Same table contamination, 351 = large_customers Q1-FY19 |
| 8 | `cm_revenue_concentration` | 34% | "international revenue representing 34%, 34%, and 36% of total revenue" (div[1150]) | wrong_metric_context | Geographic revenue mix, not customer revenue concentration |
| 9 | `cm_revenue_concentration` | 36% | Same sentence (div[1150]) | wrong_metric_context | Same: international revenue % |
| 10 | `cm_revenue_concentration` | 37% | Same sentence (div[1150]) | wrong_metric_context | "36% and 37% in the three months ended April 30, 2018 and 2019" |

### FP Root Cause Summary

| Root Cause Category | Count | % of FPs |
|---|---|---|
| **year_split_artifact** (number regex extracting year fragments "018", "20" from "2018", "2019") | 3 | 30% |
| **wrong_metric_context** (correct metric type, wrong semantic context) | 4 | 40% |
| **metric_confusion** (NRR keyword proximity to large_customers table) | 2 | 20% |
| **wrong_entity** (numerically plausible but wrong entity) | 1 | 10% |

---

## Top 3 Root Cause Categories by Count

1. **low_confidence** (18 FNs, 78% of all FNs): The V2 confidence scoring awards 0.41 to facts extracted from tables with period dates inferred from column headers (e.g. quarterly Slack tables). Annual facts in the same table structure receive 0.57. The quarterly-table confidence score is systematically below the 0.50 validation threshold, causing all quarterly customer metric values (42k–95k paid customers, 164–645 large customers) and all NRR values except the most-recent period to be filtered out.

2. **wrong_value / gold_scale_mismatch** (5 FNs, 22% of all FNs): Five quarterly NRR entries in `golden_set_251218.csv` are stored with `scaled_value=1.56` and `unit=%` (rows for Apr-17 through Oct-18), while the other NRR entries are stored as `scaled_value=156%` (already as percent). The `normalize_value()` function in `v2_validator.py` returns 1.56 for the former and 156.0 for the latter. V2 correctly extracts the integer 156 from the document, but cannot match the gold-standard value of 1.56 (99x scale difference). This is a data entry inconsistency in the gold standard CSV, not a V2 pipeline defect.

3. **wrong_metric_context / year_split_artifact** (tied, 3-4 FPs each): Two separate FP patterns — (a) geographic/developer counts being extracted because their numeric value appears near a customer metric keyword, and (b) year numbers like "2018" or "2019" being partially parsed as "018" or "20" by the number extraction regex pattern. Both were previously noted as known issues (the year-split bug was supposedly fixed in commit 879f752 but appears to recur).

---

## Specific Recommendations

### Fix 1 (High Priority): Increase confidence for quarterly table extractions

**Issue**: Quarterly customer metric rows extracted from summary tables (e.g. Slack's "Paid Customers by Quarter" table) receive conf=0.41, below the 0.50 threshold. Annual rows receive 0.57.
**File**: `src/extraction_v2/stages/fact_construction.py` or wherever confidence is computed for table-sourced facts.
**Action**: Audit what drives the 0.41 vs 0.57 difference for table facts. If quarterly table header binding scores lower than annual binding, adjust the scoring formula to reflect that quarterly column headers are equally valid indicators of a metric value.
**Expected impact**: Would recover ~13 FNs (all the low-confidence quarterly CPE and large_customers entries), increasing recall from 39.5% to approximately 73%.

### Fix 2 (Medium Priority): Repair year-split artifact in number regex

**Issue**: The number extraction regex parses "2018" as "2" + "018" or "2019" as "20" + "19", producing spurious low-value extractions (018, 20).
**File**: Likely `src/extraction_v2/stages/value_binding.py` or the number pattern regex in `src/extraction_v2/stages/candidate_generation.py`.
**Action**: Add a post-extraction filter that rejects numeric strings that are strict substrings of a year pattern (e.g., reject any value whose raw string is `\d{2,3}` if it appears inside a 4-digit year in the source text). Or fix the regex to require year boundaries.
**Expected impact**: Eliminates 3 FPs (018 x2 and 20).

### Fix 3 (Medium Priority): Add geographic-context FP rule for revenue_concentration

**Issue**: `cm_revenue_concentration` is triggering on sentences about international revenue percentage ("international revenue representing 34% of total revenue") rather than customer-level concentration.
**File**: `src/extraction_v2/stages/false_positive_filter.py`
**Action**: Add an FP suppression rule: if the surrounding sentence contains "international" or "geographic" adjacent to the keyword trigger for `cm_revenue_concentration`, suppress the extraction.
**Expected impact**: Eliminates 3 FPs (34%, 36%, 37%).

### Fix 4 (Medium Priority): Fix gold standard NRR scale encoding inconsistency

**Issue**: Five NRR entries (30-Apr-17 through 31-Oct-18) are stored with `scaled_value` as a decimal fraction (1.56, 1.53, etc.) while all other NRR entries use integer percent (138, 171, etc.). `normalize_value()` returns 1.56 for the former, 156.0 for the latter. This causes 5 guaranteed FNs regardless of V2 pipeline quality.
**File**: `data/gold_standard/golden_set_251218.csv` (rows for the 5 quarterly NRR entries: Apr-17, Jul-17, Oct-17, Jul-18, Oct-18)
**Action**: Update the 5 affected rows: change `scaled_value` from `1.56` to `156%` (and similarly for the other 4) to match the encoding convention used throughout the rest of the NRR rows.
**Expected impact**: Recovers 5 FNs at no precision cost — pure recall gain.

### Fix 5 (Low Priority): Add developer-count exclusion for DAU

**Issue**: "500,000 registered developers" is extracted as `cm_daily_active_users` because it appears in the same paragraph as the true DAU figure (10 million).
**File**: `src/extraction_v2/stages/false_positive_filter.py`
**Action**: Add context check: if the noun phrase immediately following the extracted count contains "developer" or "registered developer", suppress the fact (developers are not daily active users).
**Expected impact**: Eliminates 1 FP.

### Fix 6 (Low Priority): Add Fortune-100 exclusion for customers_period_end

**Issue**: "65 of the companies in the Fortune 100" is extracted as `cm_customers_period_end` because "customers" appears nearby.
**File**: `src/extraction_v2/stages/false_positive_filter.py`
**Action**: Add context check: if the extracted value is followed by "of the Fortune" or "Fortune 100", suppress the fact.
**Expected impact**: Eliminates 1 FP.

---

## Impact Assessment

If all fixes above were applied:

| Fix | FN reduction | FP reduction | Net F1 change (est.) |
|---|---|---|---|
| Fix 1 (quarterly confidence) | -13 FNs | 0 | +~25 pts recall |
| Fix 2 (year-split regex) | 0 | -3 FPs | +~3 pts precision |
| Fix 3 (geographic FP rule) | 0 | -3 FPs | +~3 pts precision |
| Fix 4 (gold standard NRR scale fix) | -5 FNs | 0 | +~8 pts recall |
| Fix 5 (developer count exclusion) | 0 | -1 FP | +~1 pt precision |
| Fix 6 (Fortune 100 exclusion) | 0 | -1 FP | +~1 pt precision |

Combined estimated improvement: Recall ~73%, Precision ~75%, F1 ~74% (up from current 47.6%). This would bring Slack V2 performance close to the V1 benchmark of 91.7% F1.

---

## WP-02 Post-Implementation Analysis (2026-02-19)

### Implemented Fixes

All planned fixes were implemented except Fix 2 (NUMBER_PATTERN lookbehind — skipped after analysis showed it doesn't address the real root cause):

- **Fix 1** (bare date pattern): Added `BARE_DATE_PATTERN` + `_try_parse_bare_date()` to `period_inference.py`. No FN recovery observed (see Root Cause Analysis below).
- **Fix 3** (geographic FP rule): Added `v2_geographic_revenue` rule with 200-char proximity check. Correctly suppresses `cm_revenue_concentration` near geographic context.
- **Fix 4** (NRR scale fix): 5 Slack NRR CSV rows fixed (Apr-17, Jul-17, Oct-17, Jul-18, Oct-18 changed from 1.56-decimal to 156%-format). Corrects `normalized_value` from ~1.5 to ~150.
- **Fix 5** (developer count): Added `v2_developer_count` rule with 150-char proximity check.
- **Fix 6** (Fortune subset): Added `v2_fortune_subset` rule with 100-char proximity check.
- **Fix 7** (year fragment): Added `v2_year_fragment` rule for leading-zero numbers (018, 019).

### Actual Results (Slack)

| Metric | Before WP-02 | After WP-02 |
|---|---|---|
| TP | 12 | 15 |
| FP | 10 | 4 |
| FN | 25 | 22 |
| Precision | 54.5% | 78.9% |
| Recall | 32.4% | 40.5% |
| F1 | 40.7% | 53.6% |

AC-2 (Slack F1 >= 80%) was **not met**. Root cause analysis follows.

### Root Cause Analysis: Why Fix 1 Didn't Recover Expected 13 FNs

**Finding**: 21 of 22 Slack FNs are classified as `wrong_period`. Investigation revealed the actual root cause is **text binding instead of table binding** for Slack's quarterly metrics table.

**Evidence** (from `retain_context=True` debug):
- ALL NRR and customer_count values have `binding_type=text_proximity` and `header_path=None`
- No values have `binding_type=table_header` or `binding_type=table_stub`
- NRR values: bc=0.40-0.50 (text), pc=0.70 (text_context), final conf=0.46-0.54
- Most quarterly NRR values land at conf=0.490 — just 0.010 below the 0.50 threshold

**Confidence math**: With text binding (bc=0.50) + same-sentence period (pc=0.70):
`conf = 0.50 * 0.80 + 0.70 * 0.20 = 0.40 + 0.14 = 0.54`

For values with bc=0.40 or period confidence below same-sentence:
`conf ≈ 0.490 < 0.50 threshold`

With TABLE binding (bc=0.60) + filing fallback period (pc=0.30):
`conf = 0.60 * 0.80 + 0.30 * 0.20 = 0.48 + 0.06 = 0.54` — above threshold even with worst-case period

**Root cause**: Slack's quarterly NRR and customer metrics table HTML structure is not being properly reconstructed by `TableReconstructionStage`. Metric keywords ("Net Dollar Retention Rate", "Paid Customers") are matched in narrative TEXT segments, not TABLE cells. This prevents table binding.

**Impact of bare date fix**: The bare date pattern only applies in `_parse_period_from_headers` (strategy 1: table header path). Since the values are TEXT-bound (no table_id → strategy 1 skipped), the bare date fix has no effect.

### Required Follow-Up: Slack Table Reconstruction

To recover the 21 remaining FNs, the Slack quarterly table needs to be TABLE-bound:

**Investigation needed**: Why does the V2 table reconstruction fail for Slack's quarterly data table?
- The table has 15 columns (5 time periods × 3 data columns)
- Column group headers: "As of January 31," over multiple columns with colspan
- The HTML uses inline styles without explicit thead/tbody structure

**Proposed fix**: Check `TableReconstructionStage` for handling of colspan/rowspan headers and verify that Slack's quarterly table structure generates proper `header_path` entries for each column.

---

## WP-06: Farfetch Recall Investigation

**Date**: 2026-02-19
**V2 scores (image extraction disabled)**: TP=10, FP=2, FN=24 — P=83.3%, R=29.4%, F1=43.5%

> Note: These scores are without image extraction (no OpenAI API key). Many Farfetch metrics are in chart figures; image extraction would significantly improve recall.

### FN Root Cause Summary (24 FNs)

| Diagnostic category | Count | Metrics |
|---|---|---|
| `fp_filtered` | 9 | cm_ltv_to_cac_ratio (3), cm_ltv_to_cac_ratio_by_cohort (6) |
| `no_value_binding` | 8 | cm_gross_margin_by_cohort (6), cm_cac_payback_period (1), cm_revenue_by_cohort (1) |
| `wrong_period` | 5 | cm_average_order_value |
| `no_candidate` | 2 | Empty metric_id rows in CSV |

### Actual Root Cause Analysis

**Important caveat**: The diagnostic categories are misleading for some FNs. Actual root causes differ from the reported categories in several cases.

#### Root Cause 1: LTV/CAC ratio values not bound (9 FNs — diagnostic: `fp_filtered`)

The Farfetch filing describes LTV/CAC in a text cell: *"Six month LTV/CAC ratio for the years ended December 31, 2015, 2016 and 2017 cohorts was 1.42, 1.53 and 1.77 respectively."*

- The keyword "LTV/CAC" matches in a table cell (table_id=e1011fdc, table-bound candidate)
- The value binding stage finds the **nearest** number to the keyword in the window
- "31" (from "December **31**") is closer to "LTV/CAC" than "1.42" in the text
- The binding for val=31, raw='31' is correctly FP-filtered by `part_of_date`
- This leaves zero post-filter bindings → diagnostic reports `fp_filtered`
- The actual values 1.42, 1.53, 1.77, 1.81, 2.04, 2.71 are never bound

**Root cause**: Value binding only picks the nearest number; comma-separated value lists further from the keyword are ignored.

**Fix required**: Multi-value extraction for comma-separated lists ("was 1.42, 1.53, and 1.77") in table cell text.

#### Root Cause 2: Cohort metrics in charts (6+1+1 FNs — diagnostic: `no_value_binding`)

- `cm_gross_margin_by_cohort` (6 FNs): Source text says *"The chart below illustrates the Order Contribution Margin..."* → values only in bar chart images
- `cm_revenue_by_cohort` (1 FN): Gold standard has `segment_type=chart` explicitly
- `cm_cac_payback_period` (1 FN): Text says "payback period on CAC has been consistently less than [X]" — the numeric value appears in a chart

**Root cause**: Chart-dependent data; not addressable without Vision API (OpenAI image extraction).

#### Root Cause 3: AOV values bound but low-confidence (5 FNs — diagnostic: `wrong_period`)

AOV values ($591.7, $622.1, $586.8, $583.6, $620.0) ARE being found and bound from table `c4f2ffc3`:
- Binding: bc=0.70 (table-bound), pc=0.00 (no period in header_path), period=None~None
- Confidence formula: `0.70 × 0.8 + 0.00 × 0.2 = 0.56` → should be **above** the 0.50 threshold

These facts should be matching. The diagnostic shows conf=0.410 for the "closest fact", suggesting a different binding is being selected (possible: text-bound $591.7 at bc=0.60, which gets FP-filtered, then a table-sourced scaled version from table `3950ef78` at val=591,700 is wrong by ×1000).

**Root cause (likely)**: Massive binding duplication (table `c4f2ffc3` appears in many candidates, producing hundreds of AOV bindings). The deduplication stage may be selecting the wrong deduplicated fact, or the value-matching in dedup is discarding the correct ones. Also, table `3950ef78` (which has "(in thousands)" scale) produces scaled values of $591,700 that don't match the expected $591.7.

**Immediate fix available**: Ensure the dedup stage retains the highest-confidence binding per (metric, value). Also investigate why table `c4f2ffc3` generates so many candidate bindings (n×m candidates × p bindings = explosive growth).

#### Root Cause 4: CSV data issue (2 FNs — diagnostic: `no_candidate`)

Two gold standard rows have empty `Standard Metric Name` (metric_id). The validator attempts to match these, fails to find candidates, and reports `no_candidate`. These rows (raw=' 44 ' and ' 57 ') should either be assigned a metric_id or removed from the CSV.

**Fix**: Remove or correct these two rows in `data/gold_standard/golden_set_251218.csv`.

### Chart vs Non-Chart Separation

| Category | FN count | Addressable without Vision API? |
|---|---|---|
| LTV/CAC comma-separated values not bound | 9 | **Yes** — multi-value extraction |
| Cohort charts (gross_margin, revenue, cac) | 8 | No — requires Vision API |
| AOV dedup/scaling issue | 5 | **Yes** — dedup + scale fix |
| Empty metric_id in CSV | 2 | **Yes** — CSV cleanup |

**Addressable FNs**: 9 + 5 + 2 = **16 of 24**
**Chart-only FNs**: 8 of 24

### False Positives (2 FPs)

Both FPs are for `cm_average_order_value` with values "$12.7 million" and "$15.4 million". These are likely non-AOV revenue figures near an AOV keyword. With image extraction enabled, more FPs may appear from chart annotations.

### Key Finding for WP-09

Three distinct addressable issues:
1. **Multi-value binding** (LTV/CAC): Value binding must extract comma-separated lists when the source text pattern matches "X was A, B, and C respectively"
2. **AOV binding explosion**: Too many candidates for AOV, leading to dedup problems. Investigate why table `c4f2ffc3` appears in so many candidate contexts
3. **Scale table contamination**: Table `3950ef78` has "(in thousands)" and incorrectly scales AOV values by ×1000

The highest-value target: fixing multi-value extraction would recover 9 FNs for LTV/CAC metrics alone.

**Expected recovery**: If table binding succeeds, bc rises from 0.40-0.50 to 0.60, pushing conf from 0.46-0.49 to 0.54-0.66, recovering ~18-20 FNs.
