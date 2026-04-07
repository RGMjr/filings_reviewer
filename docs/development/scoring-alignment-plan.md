# Plan: Scoring Discrepancy Investigation, Image Opt-In, and V2 Regression Fixes

**Created**: 2026-04-04
**Status**: Not started

## Context

Before making V1-to-V2 cutover decisions, we need confidence in our scoring. Two validators report wildly different V1 F1 scores (75.6% vs 47.5%) for the same companies. Additionally, V2-full (with images) underperforms V2-text-only, and Slack/Torrid show V2 regressions. This plan sequences investigation and fixes so each phase builds on validated conclusions from the prior one.

## Dependency Graph

```
Phase 1 (Scoring Alignment) ─┬─> Phase 2 (Slack — likely closes as artifact)
                              └─> Phase 3 (Torrid FP rules + baseline)
                                      └─> Phase 4 (Per-company image opt-in)
                                              └─> Phase 5 (Final validation)
```

Phases 2 and 3 can run in parallel after Phase 1.

---

## Phase 1: Align Scoring Methodology

**Goal**: Make `validate_against_gold_standard.py` use the same matching logic as `unified_comparison.py` so we have one source of truth.

### Root Cause Summary

| Difference | `validate_against_gold_standard.py` | `unified_comparison.py` |
|---|---|---|
| Match threshold | `score >= 2` (metric-only counts) | `score >= 4` (metric AND value required) |
| % normalization | `"15%" -> 0.15` | `"15%" -> 15.0` |
| Value tolerance | 1% (`< 0.01`) | 2% (`<= 0.02`) |
| Recall denominator | Unique recall (forgives duplicate gold entries post-hoc) | Strict recall on pre-deduplicated gold |
| FP scope | All unmatched candidates | Only metric-in-scope candidates |

### Changes

**File: `scripts/validate_against_gold_standard.py`**

1. **Match threshold** (line 460-461): Change `if score >= 2:` to `if score >= 4:`. This is the biggest driver of the gap -- metric-only matches are not true positives.

2. **Percentage normalization** (line 144-145): Change `return float(cleaned) / 100` to `return float(cleaned)` so `"15%"` becomes `15.0`, matching `v2_validator.normalize_value`.

3. **Value tolerance** (line 439): Change `< 0.01` to `<= 0.02`.

4. **Recall calculation** (line 536-539): Keep the existing unique_recall approach (Option A). It is mathematically equivalent to pre-deduplication when done correctly. No change needed.

5. **FP scoping** (line 502): Change from `len(candidates) - true_positives` to count only candidates whose `metric_id` appears in the gold set. Add a `gold_metric_ids` set computed from `gold_entries_with_values`.

### Verification

- Run both validators on the full gold standard cohort, compare per-company P/R/F1.
- Expected: V1 score drops from ~75.6% to roughly the 47-55% range. Both tools should agree within ~1-2% after alignment.
- Update `data/gold_standard/baseline_metrics.json` with re-scored V1 numbers.

---

## Phase 2: Investigate Slack "Regression"

**Goal**: Confirm whether Slack regression is real or a scoring artifact.

### Findings So Far

- V1 baseline: F1=94.6%, V2 baseline: F1=96.9% -- **V2 already beats V1** in the strict validator.
- The "regression" was likely observed using the lenient validator where metric-only matches inflated V1's score.

### Steps

1. After Phase 1, re-run `validate_against_gold_standard.py` for Slack with the aligned scoring.
2. Compare against V2 baseline (96.9%).
3. **If V2 >= V1**: Close this issue -- no code changes needed.
4. **If V2 < V1**: Investigate specific FN metrics (DAU values, NRR near dollar-threshold text). But this is unlikely given the V2 baseline data.

### Expected Outcome

No code changes. The regression is a scoring artifact.

---

## Phase 3: Fix Torrid V2 Regression

**Goal**: Port targeted V1 FP rules for LTV/CAC metrics and add Torrid to V2 baseline.

### Root Causes

1. **Torrid absent from V2 baseline** -- added to V1 gold standard on April 4, V2 baseline last updated April 3.
2. **V1 FP rules not ported**: `_check_metric_specific_fp()` in `src/review/candidate_generator.py` has Torrid-specific rules for LTV/CAC that V2 lacks.
3. **V2 unit_compatibility too permissive**: `cm_ltv_to_cac_ratio` in `_RATIO_METRICS` allows `Unit.PERCENT` -- V1 blocks this.
4. **V2 magnitude threshold too high**: `cm_ltv_to_cac_ratio` max is 100 in V2 vs 50 in V1.
5. **12 of 40 Torrid gold values are chart-sourced** -- unreachable without OPENAI_API_KEY. This caps text-only recall at ~70%.

### Changes

**File: `src/extraction_v2/unit_compatibility.py`** (lines 69-73, 87-91)

- Move `cm_ltv_to_cac_ratio` and `cm_ltv_to_cac_ratio_by_cohort` out of `_RATIO_METRICS`.
- Add new set `_RATIO_NO_PERCENT_METRICS` with allowed units `{Unit.RATIO, Unit.COUNT, Unit.OTHER}` (no `Unit.PERCENT`).
- Add corresponding loop to populate `METRIC_ALLOWED_UNITS`.

**File: `src/extraction_v2/stages/false_positive_filter.py`**

- Line 1017: Change `"cm_ltv_to_cac_ratio": 100` to `"cm_ltv_to_cac_ratio": 50` in `_METRIC_MAX_VALUE`.
- Add new rule `_rule_ltv_cac_unit_mismatch` that suppresses `$` and `%` candidates for `cm_ltv_to_cac_ratio` (porting V1's `ltv_cac_dollar_not_ratio` and `ltv_cac_percentage_not_ratio`). Note: the unit_compatibility change handles `%` at binding time; the FP rule adds a `$` check and is a safety net for edge cases.

**Baseline update:**

- Run V2 validator with Torrid included and update `data/gold_standard/v2_baseline.json`.

### Verification

- Run gold standard validation for Torrid: compare V2 P/R/F1 before and after changes.
- Run full gold standard suite to confirm no regressions on other companies.
- Expected: Torrid precision improves; recall ceiling is ~70% for text-only (chart values remain FNs without vision API).

---

## Phase 4: Per-Company Image Extraction Opt-In

**Goal**: Replace pipeline-wide image toggle with a per-company allow-list so only companies that benefit (Robinhood, Torrid) use image extraction.

### Root Cause of V2-Full Underperformance

- No chart-specific FP rules in `false_positive_filter.py`.
- `candidate_generation.py` falls back to `nearby_text` matching for images, creating duplicate candidates tagged as `SourceType.CHART` from surrounding prose.
- Vision API hallucinations pass through unfiltered.
- Only Robinhood (10 cohort data points) and Torrid (4 LTV values) benefit.

### Changes

**File: `src/extraction_v2/pipeline.py`** (~line 95)

- Add field to `PipelineConfig`:
  ```python
  image_extraction_companies: frozenset[str] = frozenset()
  ```
- In the pipeline's stage-building logic, when `image_extraction_companies` is non-empty, only enable image stages (`IMAGE_TRIAGE`, `OCR_CHART_EXTRACTION`) if the current company is in the set.
- When `image_extraction_companies` is empty and `enable_image_extraction` is True, behavior is unchanged (all companies get images -- backwards compatible).

**File: `src/gold_standard/unified_comparison.py`** (~line 766-782)

- When constructing the V2-full pipeline, pass the allow-list:
  ```python
  image_extraction_companies=frozenset({"Robinhood Markets, Inc.", "Torrid Holdings Inc."})
  ```

**File: `src/extraction_v2/stages/false_positive_filter.py`**

- Add rule `_rule_chart_nearby_text_only`: suppress chart-sourced candidates where the keyword match came only from `nearby_text` (not chart metadata like title/axis/series). Investigate `MetricCandidate` model first -- `source_type` and `source_locator` fields may already distinguish these cases. Only add a new field if existing fields are insufficient.

### Verification

- Run unified comparison with per-company image opt-in.
- Expected: V2-full with opt-in should beat V2-text-only (Robinhood/Torrid get their image TPs, other companies avoid image FPs).
- Compare against previous V2-full numbers (50.7%) -- should improve.

---

## Phase 5: Final Validation and Baseline Update

1. Run full gold standard validation with all changes:
   ```bash
   python3 scripts/validate_against_gold_standard.py --all --mode fresh --baseline
   ```
2. Run unified comparison to verify V1 vs V2 vs gold agreement:
   ```bash
   python3 -m src.gold_standard.unified_comparison
   ```
3. Update both baselines:
   - `data/gold_standard/baseline_metrics.json` (V1, with aligned scoring)
   - `data/gold_standard/v2_baseline.json` (V2, with Torrid added)
4. Run `pytest -x -q` to confirm no test regressions.

---

## Concurrency Notes

- **Phases 2 + 3**: Fully independent after Phase 1 -- run in parallel via separate subagents.
- **Within Phase 1**: All 5 changes are in the same file -- must be sequential (single implementer).
- **Within Phase 3**: `unit_compatibility.py` and `false_positive_filter.py` changes are independent -- can be parallelized.
- **Phase 4**: Depends on Phase 3 (need Torrid FP rules to measure image quality correctly).

## Tests That Will Break (Must Update)

Phase 3 changes to `unit_compatibility.py` will break these tests:

- `tests/unit/extraction_v2/test_unit_compatibility.py:141` -- `TestRatioMetrics.test_accepts_percent` for `cm_ltv_to_cac_ratio` and `cm_ltv_to_cac_ratio_by_cohort` (currently asserts PERCENT is accepted; must change to rejected)
- `tests/unit/extraction_v2/test_unit_compatibility.py:248-257` -- `test_ratio_metric_returns_percent_ratio_other_and_count` (asserts `Unit.PERCENT in allowed` and `len(allowed) == 4`; must update)
- `tests/unit/extraction_v2/test_value_binding.py:2997-3010` -- LTV/CAC prose cell tests use RATIO_METRICS list; verify these still pass since the test binds bare decimals (Unit.COUNT), not PERCENT

Phase 1 changes to `validate_against_gold_standard.py` may break:
- `tests/unit/scripts/test_validate_against_gold_standard.py` -- verify test expectations after threshold/normalization changes

## Risk Notes

- **Phase 1 will cause V1 baseline numbers to drop significantly** (~75% -> ~50%). This is not a regression -- it's honest measurement. The V1 pipeline hasn't changed; only how we score it.
- **Torrid chart values (12/40) remain FNs without OPENAI_API_KEY**. This caps Torrid text-only recall at ~70% regardless of code quality. Consider annotating chart-sourced gold entries with a flag so text-only runs can report a separate ceiling.
- **Phase 4 chart nearby_text FP rule**: Investigate `MetricCandidate` fields before assuming a model change is needed. The `source_type` and `source_locator` fields may already distinguish chart-metadata matches from nearby-text fallback matches. If not, adding a boolean field to `MetricCandidate` is low-risk but must not break existing tests.
- **Phase 3 unit_compatibility change is global**: Removing PERCENT from LTV/CAC affects all companies, not just Torrid. This is correct behavior (LTV/CAC should never be a percentage) but verify no gold standard entries expect PERCENT-unit LTV/CAC values.

## Pre-Implementation Gate

This plan touches 7+ files and involves extraction/config changes. Before writing code, complete the pre-flight checklist per CLAUDE.md:
1. ASSUMPTION AUDIT -- verify all line numbers and function signatures against current code
2. SCOPE CHECK -- confirm no out-of-scope changes
3. RULES COMPLIANCE -- re-read CLAUDE.md
4. RISK ASSESSMENT -- run the failing test check above
5. MINIMAL PATH -- confirm each change is necessary

## Files to Modify

| Phase | File | Change |
|-------|------|--------|
| 1 | `scripts/validate_against_gold_standard.py` | Align threshold, normalization, tolerance, FP scope |
| 1 | `tests/unit/scripts/test_validate_against_gold_standard.py` | Update test expectations |
| 3 | `src/extraction_v2/unit_compatibility.py` | Remove PERCENT from LTV/CAC allowed units |
| 3 | `src/extraction_v2/stages/false_positive_filter.py` | Lower LTV/CAC max to 50, add unit mismatch rule |
| 3 | `tests/unit/extraction_v2/test_unit_compatibility.py` | Update PERCENT assertions for LTV/CAC |
| 3 | `data/gold_standard/v2_baseline.json` | Add Torrid |
| 4 | `src/extraction_v2/pipeline.py` | Add `image_extraction_companies` field |
| 4 | `src/gold_standard/unified_comparison.py` | Pass allow-list to V2-full pipeline |
| 4 | `src/extraction_v2/stages/false_positive_filter.py` | Add chart nearby_text FP rule |
| 5 | `data/gold_standard/baseline_metrics.json` | Re-scored V1 baseline |
