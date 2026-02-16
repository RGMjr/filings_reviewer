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
