# WORKER PROMPT: Task UXI-2-TEST-F2 - E2E Test for Partial Match Search

```markdown
═══════════════════════════════════════════════════════════════════════════════
TASK ID:       UXI-2-TEST-F2
TASK NAME:     Add E2E test verifying partial match search behavior
WORKSTREAM:    Testing Improvements
SOURCE:        UXI-2-TEST completion evaluation - improvement suggestion #2
STATUS:        🟡 PENDING
COMPLETION:    N/A
TIME ESTIMATE: 30-45 min (test design 15 min, implementation 20 min, verification 10 min)
TIME ACTUAL:   N/A
RISK LEVEL:    None (additive tests only)
TASK SIZE:     XS
DEPENDS ON:    UXI-2-TEST (must be complete)
UNLOCKS:       None
BLOCKS:        None
PARALLEL WITH: UXI-2-TEST-F1, UXI-2-TEST-F3, UXI-2-TEST-F4
═══════════════════════════════════════════════════════════════════════════════
```

## Objective

Add an E2E test that verifies partial search matching works correctly (e.g., typing "cu" shows all metrics containing "customer").

**Business Rationale**: Users often type partial metric names. Verifying partial matching ensures the search is user-friendly and doesn't require exact keyword knowledge.

**Current Behavior**: No test explicitly verifies partial matching behavior.

**Desired Behavior**: E2E test confirms "cu" matches multiple customer-related metrics.

## Prerequisites

- UXI-2-TEST complete (tests/e2e/ directory exists)

## Files to Modify

1. **`tests/e2e/test_metric_dropdown_search.py`** - Add test_partial_match_filtering test

## Implementation Requirements

### Core Functionality

1. **Test Flow**
   - Navigate to review page with dropdown
   - Open reclassify dropdown
   - Type "cu" (partial for "customer")
   - Verify multiple metrics are visible (not just exact matches)

2. **Expected Matches for "cu"**
   - cm_customers_period_end (contains "cu")
   - cm_active_customers_total
   - cm_customer_churn_rate
   - cm_customer_retention_rate
   - cm_customer_acquisition_cost
   - Others containing "cu"

### Assertions

- Visible metric count > 5 (multiple matches)
- All visible metrics contain "cu" in metric_id OR display name
- Search is case-insensitive ("CU" = "cu")

## Test Requirements

### Test Categories (1-2 tests)

1. **Partial Match Test** (1 test)
   - `test_partial_match_filtering` - Type "cu", verify multiple customer metrics visible

2. **Optional: Multiple partial terms**
   - `test_partial_match_variations` - Try "rev" for revenue metrics, "ret" for retention

## Acceptance Criteria

- [ ] New test `test_partial_match_filtering` added
- [ ] Test documents expected match count (>5 metrics)
- [ ] Test verifies visible metrics contain search term

## Do NOT

- Modify production code
- Change search logic (this tests existing behavior)

## Verification Commands

```bash
# Verify test file syntax
python3 -c "import tests.e2e.test_metric_dropdown_search"
```

---

**Last Updated**: 2026-01-07
**Format Version**: 2.6
