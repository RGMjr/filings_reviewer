# Implementation Plan: Metric Evaluation Decisions

**Source**: `docs/analysis/metric-value-evaluation.md` (Decision Log)
**Branch**: `claude/evaluate-metrics-xX17n`

---

## Wave 1: YAML Config Changes (tier promotions + deprecations)

Touches only `config/metric_keywords.yaml`. Can be validated with `pytest -x -q`.

### 1a. Promote 3 metrics to Tier 1

| Metric | File | Line | Change |
|--------|------|------|--------|
| cm_new_customers_acquired | `config/metric_keywords.yaml` | 66 | `tier: 2` -> `tier: 1` |
| cm_large_customers_period_end | `config/metric_keywords.yaml` | 211 | `tier: 2` -> `tier: 1` |
| cm_customers_period_end_by_tenure | `config/metric_keywords.yaml` | 249 | `tier: 2` -> `tier: 1` |

### 1b. Deprecate 3 metrics in YAML

For each metric, add `status: deprecated` and a deprecation comment. Keep patterns for historical interpretation (same pattern as existing deprecated metrics like cm_gmv).

| Metric | File | Line | Change |
|--------|------|------|--------|
| cm_arr | `config/metric_keywords.yaml` | 532 | Add `status: deprecated` after tier line |
| cm_mrr | `config/metric_keywords.yaml` | 542 | Add `status: deprecated` after tier line |
| cm_expansion_revenue | `config/metric_keywords.yaml` | 550 | Add `status: deprecated` after tier line |

### 1c. Update ACTIVE_METRICS in transcript_metrics.py

Remove the 3 deprecated metrics from the `ACTIVE_METRICS` frozenset.

| File | Lines | Change |
|------|-------|--------|
| `src/gold_standard/transcript_metrics.py` | 16, 25, 33 | Remove `"cm_arr"`, `"cm_expansion_revenue"`, `"cm_mrr"` |

Update the docstring count from 27 to 24.

### Wave 1 Verification

```bash
pytest -x -q
# Confirm no import/config loading errors
python3 -c "from src.shared.keyword_config import get_active_metrics, get_metric_tiers; print(len(get_active_metrics()), 'active'); t1 = [m for m,t in get_metric_tiers().items() if t == 1]; print(len(t1), 'tier 1:', sorted(t1))"
# Expected: 25 active, 15 tier 1 (13 original - cm_expansion_revenue + cm_large_customers_period_end + cm_new_customers_acquired + cm_customers_period_end_by_tenure)
```

**Commit**: `feat: promote 3 metrics to Tier 1, deprecate cm_arr/cm_mrr/cm_expansion_revenue`

---

## Wave 2: Source Code Cleanup (deprecated metric references)

Remove deprecated metrics from runtime code. Does NOT touch test files.

### 2a. Web display order dicts

Remove cm_arr, cm_mrr, cm_expansion_revenue entries from METRIC_DISPLAY_ORDER.

| File | Lines | Remove |
|------|-------|--------|
| `src/web/routes/_metrics.py` | 54, 55, 59 | `"cm_arr": 21`, `"cm_mrr": 22`, `"cm_expansion_revenue": 26` |
| `src/web/routes/review.py` | 701, 702, 706 | Same 3 entries |

### 2b. Confidence scoring format expectations

Remove deprecated metrics from METRIC_EXPECTED_FORMATS dict.

| File | Lines | Remove |
|------|-------|--------|
| `src/review/confidence_scoring.py` | 143, 144, 153 | `"cm_arr"`, `"cm_mrr"`, `"cm_expansion_revenue"` entries |

### 2c. Unit compatibility lists

Remove deprecated metrics from DOLLAR_TYPE_METRICS.

| File | Lines | Remove |
|------|-------|--------|
| `src/extraction_v2/unit_compatibility.py` | 41, 42 | `"cm_arr"`, `"cm_mrr"` |

Note: cm_expansion_revenue is NOT in this list (it uses a different compatibility path).

### 2d. V1 FP filter DOLLAR_ONLY_METRICS

Remove deprecated metrics.

| File | Lines | Remove |
|------|-------|--------|
| `src/review/false_positive_filter.py` | 374, 375 | `'cm_arr'`, `'cm_mrr'` |

### 2e. Annotation taxonomy config

Add `status: deprecated` to the 3 metrics.

| File | Lines |
|------|-------|
| `config/transcript_annotation_taxonomy.yaml` | ~133, ~154, ~256 |

### Wave 2 Verification

```bash
pytest -x -q
```

**Commit**: `refactor: remove deprecated cm_arr/cm_mrr/cm_expansion_revenue from runtime code`

---

## Wave 3: FP Rule Cleanup

Remove FP rules that are now dead code (they only fire for deprecated metrics). This is the biggest maintenance win from deprecating cm_arr.

### 3a. V2 false_positive_filter.py

Remove or simplify rules that ONLY apply to cm_arr:
- `_rule_revenue_as_arr` (~line 884): Entire function only fires for cm_arr
- `_rule_arr_tier_threshold` (~line 1110): Entire function only fires for cm_arr
- Remove cm_arr from DOLLAR_ONLY_METRICS lists (~lines 348, 814, 1456)
- Remove cm_expansion_revenue from any metric-specific logic (~lines 698, 707, 809, 814)

**Approach**: Search for every `cm_arr`, `cm_mrr`, `cm_expansion_revenue` reference in this file. For functions that ONLY serve these metrics, remove the entire function + its registration. For shared lists, just remove the metric IDs.

| File | Estimated lines removed |
|------|------------------------|
| `src/extraction_v2/stages/false_positive_filter.py` | ~80-120 lines |

### 3b. V1 candidate_generator.py

Remove cm_arr-specific FP rules (~lines 879-948, ~line 1231):
- arr_tier_threshold block
- arr_magnitude_cap block
- arr_tam_context block
- arr_average_not_total block
- arr_capital_not_arr block
- arr zero-value block (~line 1231)

| File | Estimated lines removed |
|------|------------------------|
| `src/review/candidate_generator.py` | ~70-80 lines |

### Wave 3 Verification

```bash
pytest -x -q
# Specifically run FP filter tests:
pytest tests/unit/extraction_v2/test_false_positive_filter_stage.py -x -q
pytest tests/unit/review/test_candidate_generator.py -x -q
```

**Commit**: `refactor: remove ~150 lines of cm_arr/cm_expansion_revenue FP rules`

---

## Wave 4: SQL Seed Changes

### 4a. Promote cm_lifetime_value_per_customer

| File | Line | Change |
|------|------|--------|
| `sql/04_seed_metrics_taxonomy.sql` | 402 | `'future'` -> `'extended'` (metric_class) |
| `sql/04_seed_metrics_taxonomy.sql` | 405 | `'experimental'` -> `'active'` (status) |

### 4b. Promote cm_ltv_to_cac_ratio

Same treatment (also currently `experimental`):

| File | Line | Change |
|------|------|--------|
| `sql/04_seed_metrics_taxonomy.sql` | 414 | `'future'` -> `'extended'` (metric_class) |
| `sql/04_seed_metrics_taxonomy.sql` | 417 | `'experimental'` -> `'active'` (status) |

### 4c. Deprecate cm_arr, cm_mrr, cm_expansion_revenue in SQL

Update status from `'active'` to `'deprecated'` and add deprecation comments.

| File | Lines | Change |
|------|-------|--------|
| `sql/04_seed_metrics_taxonomy.sql` | ~239 | cm_arr: status -> `'deprecated'` |
| `sql/04_seed_metrics_taxonomy.sql` | ~251 | cm_mrr: status -> `'deprecated'` |
| `sql/04_seed_metrics_taxonomy.sql` | ~263 | cm_expansion_revenue: status -> `'deprecated'` |

### 4d. cm_deferred_revenue -- NO ACTION

Already `status: 'deprecated'` in SQL (line 316). No changes needed.

### Wave 4 Verification

```bash
# Syntax check the SQL file
python3 -c "open('sql/04_seed_metrics_taxonomy.sql').read(); print('SQL file readable')"
pytest -x -q
```

**Commit**: `feat: promote LTV/CAC metrics to active, deprecate cm_arr/cm_mrr/cm_expansion_revenue in SQL`

---

## Wave 5: Test File Updates

Update tests that reference deprecated metrics. Strategy: replace deprecated metric IDs with active ones in test fixtures (don't delete tests -- they test pipeline behavior, not specific metrics).

### Affected test files

| File | Estimated changes | Strategy |
|------|-------------------|----------|
| `tests/unit/extraction_v2/test_false_positive_filter_stage.py` | ~50 lines | Remove tests for deleted FP rules; update metric IDs in remaining tests |
| `tests/unit/extraction_v2/test_unit_compatibility.py` | ~4 lines | Remove cm_arr/cm_mrr from DOLLAR_TYPE expected sets |
| `tests/unit/review/test_candidate_generator.py` | ~20 lines | Remove ARR-specific FP suppression tests |
| `tests/unit/review/test_false_positive_filter.py` | ~2 lines | Update DOLLAR_ONLY_METRICS assertion |
| `tests/unit/review/test_confidence_scoring.py` | ~4 lines | Update expected format assertions |
| `tests/unit/web/test_review_routes.py` | ~10 lines | Update metric display order test data |
| `tests/performance/conftest.py` | ~2 lines | Replace cm_arr/cm_mrr in perf fixture |
| Other test files | ~20 lines | Replace metric IDs in fixture data |

### Wave 5 Verification

```bash
pytest -x -q
# Full test suite must pass
```

**Commit**: `test: update tests for deprecated cm_arr/cm_mrr/cm_expansion_revenue`

---

## Wave 6: Documentation Updates

### 6a. CLAUDE.md tier listing

Update the Metric Priority Tiers section (lines 39-47):

**New Tier 1 list** (remove cm_expansion_revenue, add 3 promotions):
```
**Tier 1 (must-not-miss):** Cohorted data, retention, LTV/CAC, revenue concentration, customer counts.
- `cm_customer_retention_rate`, `cm_net_revenue_retention`, `cm_gross_revenue_retention`
- `cm_revenue_by_cohort`, `cm_transactions_by_cohort`, `cm_balance_by_cohort`, `cm_gross_margin_by_cohort`
- `cm_revenue_concentration`
- `cm_lifetime_value_per_customer`, `cm_customer_acquisition_cost`, `cm_ltv_to_cac_ratio`, `cm_ltv_to_cac_ratio_by_cohort`
- `cm_large_customers_period_end`, `cm_new_customers_acquired`, `cm_customers_period_end_by_tenure`
```

**New Tier 2 list** (remove ARR mention):
```
**Tier 2 (nice-to-have):** Customer counts, engagement, unit economics.
- All other `cm_*` metrics (customer counts, MAU/DAU, ARPU, AOV, etc.)
```

### 6b. .claude/rules/v2-pipeline.md

Remove cm_expansion_revenue from the "Tier 1 recall gaps" section (it's being deprecated, not improved). No other changes needed.

### 6c. docs/development/metrics-taxonomy.md

Update metric definitions and tier listings to reflect the 3 deprecations and 3 promotions.

### 6d. docs/analysis/metric-value-evaluation.md

Update the executive summary to reflect the final implemented state.

### Wave 6 Verification

```bash
# Grep for stale references
grep -r "cm_expansion_revenue" CLAUDE.md .claude/rules/
grep -rn "ARR" CLAUDE.md | head -5  # Should not mention ARR as active metric
```

**Commit**: `docs: update tier listings and rules for metric evaluation decisions`

---

## Wave 7: MET-1 Alias Resolution (Verification Only)

The MET-1 alias contradiction is **already resolved in code**:
- YAML has both metrics as distinct (no aliases, comment at line 59-62 confirms)
- SQL has both as separate `active` metrics
- Gold standard data uses both IDs correctly
- `keyword_config.py` alias functions return empty (no aliases defined)

**Remaining action**: Close the MET-1 audit item. Update `docs/analysis/MET-1-metric-consistency-audit.md` status from "Awaiting User Review" to "Resolved" and note that Option A (keep as distinct) was implemented.

**Commit**: `docs: mark MET-1 alias contradiction as resolved`

---

## Summary

| Wave | Files touched | Risk | Estimated size |
|------|--------------|------|----------------|
| 1 | 2 config + 1 source | Low | ~15 line changes |
| 2 | 6 source files | Low | ~20 line removals |
| 3 | 2 source files | Medium (FP logic) | ~150 line removals |
| 4 | 1 SQL file | Low | ~10 line changes |
| 5 | ~8 test files | Medium (many files) | ~50-80 line changes |
| 6 | 4 docs/rules files | Low | ~20 line changes |
| 7 | 1 doc file | Low | Status update only |

**Total**: ~25 active metrics (15 Tier 1, 10 Tier 2), 8 deprecated metrics.

**Pre-flight notes**:
- Waves 1-2 are safe, independent, and easily reversible
- Wave 3 is the riskiest (deleting FP rule logic) -- run FP filter tests explicitly
- Wave 4 is SQL seeds only (no migration needed -- these are idempotent INSERT ON CONFLICT)
- Wave 5 depends on Waves 1-3 (tests may fail until fixtures are updated)
- Waves 6-7 are docs-only, can be done anytime
