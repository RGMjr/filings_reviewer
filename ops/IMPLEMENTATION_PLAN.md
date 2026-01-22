# Implementation Plan

**Created**: 2026-01-22
**Purpose**: Implement fixes for Slack validation regression
**Mode**: Ralph autonomous loop

---

## Instructions

1. Process ONE implementation task per iteration
2. Write code changes and run tests
3. Mark `[x]` when complete with test results
4. Commit changes after each task
5. Exit to allow fresh context for next task

---

## Implementation Tasks

### Phase 1: High-Impact Fixes

- [x] FIX-1 | Deprecate cm_billings | Set status: deprecated in config/metric_keywords.yaml - eliminates 49 FP
  - Added `status: deprecated` and `deprecation_reason` to cm_billings in YAML
  - Added `is_metric_deprecated()` and `get_active_metrics()` to keyword_config.py
  - Updated keyword_matching.py to filter deprecated metrics from METRIC_KEYWORDS, EXCLUSIONS, and REQUIRED_CONTEXT
  - Result: P=57.1% (was 28.6%), R=63.6% (unchanged), F1=60.2% (was 39.4%)
  - Tests: pytest tests/unit/review/test_keyword_matching.py PASSED (91 tests)
- [ ] FIX-2 | Add cm_mrr to DOLLAR_ONLY_METRICS | In src/review/false_positive_filter.py - eliminates 4 FP
- [ ] FIX-3 | Add cm_customers_period_end exclusions | Add "languages", "months", "countries" exclusions in YAML

### Phase 2: Table Parsing Fix

- [ ] FIX-4 | Investigate table parsing | Debug why only rightmost 2 columns extracted from multi-period tables
- [ ] FIX-5 | Fix table value extraction | Ensure ALL data cells in table rows are extracted

### Phase 3: Validation Matching Fix

- [ ] FIX-6 | Implement two-pass optimal matching | Sort matches by score before assignment in validate_against_gold_standard.py

### Phase 4: Validation

- [ ] FIX-7 | Run gold standard validation | Verify improvements with pytest -m gold_standard

---

## Completed

<!-- Tasks move here after implementation -->

---

## Statistics

| Metric | Count |
|--------|-------|
| Total Tasks | 7 |
| Completed | 1 |
| Remaining | 6 |
