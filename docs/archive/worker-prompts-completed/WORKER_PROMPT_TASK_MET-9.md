# Worker Prompt: MET-9 - Add Tests for Dropdown Ordering

## Task Overview

| Field | Value |
|-------|-------|
| Task ID | MET-9 |
| Task Name | Add Tests for Dropdown Ordering |
| Size | S (30 min - 2 hours) |
| Priority | Medium |
| Dependencies | MET-7, MET-8 |
| Blocking | MET-11 |

## Objective

Add unit tests for the dropdown ordering functionality, specifically:
1. `METRIC_DISPLAY_ORDER` dict completeness
2. `_get_unique_metrics_for_filing()` sorting behavior
3. `_get_active_metrics()` ordering behavior

## Background

The following code was added without test coverage:

1. `METRIC_DISPLAY_ORDER` dict (lines 1019-1052) - defines ordering for all metrics
2. `_get_unique_metrics_for_filing()` (lines 1055-1072) - sorts filter dropdown by semantic order

Currently, `grep` finds no tests referencing these:
```
grep -r "METRIC_DISPLAY_ORDER\|_get_unique_metrics_for_filing" tests/
# Returns empty
```

## Requirements

### R1: Test METRIC_DISPLAY_ORDER Completeness

Create test to verify all active metrics have an ordering defined:

```python
# tests/unit/web/test_review_routes.py

def test_metric_display_order_covers_all_active_metrics(app):
    """Verify METRIC_DISPLAY_ORDER includes all metrics that could appear in dropdown."""
    from src.web.routes.review import METRIC_DISPLAY_ORDER

    # Get all known metric IDs from YAML
    from src.extraction.keyword_config import get_all_metric_ids
    all_metrics = get_all_metric_ids()

    # Check each metric has an ordering (or is deprecated/experimental)
    missing = []
    for metric_id in all_metrics:
        if metric_id not in METRIC_DISPLAY_ORDER:
            # Check if it's deprecated (acceptable to be missing)
            # For now, just collect missing ones
            missing.append(metric_id)

    # Allow some metrics to be missing (deprecated ones)
    deprecated = {'cm_gmv', 'cm_bookings', 'cm_billings', 'cm_acv', 'cm_tcv',
                  'cm_gross_margin_overall', 'cm_deferred_revenue'}
    unexpected_missing = set(missing) - deprecated

    assert not unexpected_missing, f"Metrics missing from METRIC_DISPLAY_ORDER: {unexpected_missing}"
```

### R2: Test _get_unique_metrics_for_filing Ordering

```python
def test_get_unique_metrics_for_filing_semantic_order():
    """Verify filter dropdown uses semantic ordering, not alphabetical."""
    from src.web.routes.review import _get_unique_metrics_for_filing

    # Create mock candidates with metrics from different categories
    candidates = [
        {"suggested_metric_id": "cm_arr"},  # Revenue (21)
        {"suggested_metric_id": "cm_customers_period_end"},  # Customer Count (1)
        {"suggested_metric_id": "cm_net_revenue_retention"},  # Retention (31)
        {"suggested_metric_id": "cm_customer_acquisition_cost"},  # Unit Economics (42)
    ]

    result = _get_unique_metrics_for_filing(candidates)

    # Should be ordered by category, not alphabetically
    assert result == [
        "cm_customers_period_end",  # Category 1
        "cm_arr",  # Category 3
        "cm_net_revenue_retention",  # Category 4
        "cm_customer_acquisition_cost",  # Category 5
    ]


def test_get_unique_metrics_for_filing_unknown_metric_at_end():
    """Unknown metrics should sort to end (order 99)."""
    from src.web.routes.review import _get_unique_metrics_for_filing

    candidates = [
        {"suggested_metric_id": "cm_unknown_metric"},
        {"suggested_metric_id": "cm_customers_period_end"},
    ]

    result = _get_unique_metrics_for_filing(candidates)

    assert result[0] == "cm_customers_period_end"
    assert result[-1] == "cm_unknown_metric"


def test_get_unique_metrics_for_filing_deduplicates():
    """Verify duplicate metric IDs are removed."""
    from src.web.routes.review import _get_unique_metrics_for_filing

    candidates = [
        {"suggested_metric_id": "cm_arr"},
        {"suggested_metric_id": "cm_arr"},
        {"suggested_metric_id": "cm_arr"},
    ]

    result = _get_unique_metrics_for_filing(candidates)

    assert result == ["cm_arr"]
    assert len(result) == 1
```

### R3: Test Category Ordering Invariants

```python
def test_metric_display_order_category_ranges():
    """Verify metrics are in correct category ranges."""
    from src.web.routes.review import METRIC_DISPLAY_ORDER

    # Define expected category ranges
    customer_count = range(1, 10)
    transactions = range(11, 20)
    revenue = range(21, 30)
    retention = range(31, 40)
    unit_economics = range(41, 50)

    # Verify specific metrics are in expected categories
    assert METRIC_DISPLAY_ORDER["cm_customers_period_end"] in customer_count
    assert METRIC_DISPLAY_ORDER["cm_active_customers_total"] in customer_count
    assert METRIC_DISPLAY_ORDER["cm_purchase_transactions_overall"] in transactions
    assert METRIC_DISPLAY_ORDER["cm_arr"] in revenue
    assert METRIC_DISPLAY_ORDER["cm_net_revenue_retention"] in retention
    assert METRIC_DISPLAY_ORDER["cm_customer_acquisition_cost"] in unit_economics
```

### R4: Test No Duplicate Order Values

```python
def test_metric_display_order_no_duplicate_values():
    """Verify no two metrics have the same sort order."""
    from src.web.routes.review import METRIC_DISPLAY_ORDER

    orders = list(METRIC_DISPLAY_ORDER.values())
    assert len(orders) == len(set(orders)), "Duplicate order values found"
```

## File to Create/Modify

Add tests to: `tests/unit/web/test_review_routes.py`

If the file doesn't exist or tests don't fit, create: `tests/unit/web/test_dropdown_ordering.py`

## Verification Commands

```bash
# Run the new tests
TEST_DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis_test" python3 -m pytest tests/unit/web/test_review_routes.py -v -k "metric_display_order or unique_metrics"

# Run all web unit tests to ensure no regressions
TEST_DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis_test" python3 -m pytest tests/unit/web/ -v --tb=short

# Check coverage of the new code
TEST_DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis_test" python3 -m pytest tests/unit/web/ --cov=src/web/routes/review --cov-report=term-missing
```

## Deliverables

1. **New tests**: At least 5 tests covering ordering functionality
2. **All tests pass**: Including existing tests
3. **Coverage**: `METRIC_DISPLAY_ORDER` and `_get_unique_metrics_for_filing` have test coverage

## Out of Scope

- Testing `_get_active_metrics()` database interaction (integration test territory)
- Modifying the ordering logic itself
- Adding integration tests for actual dropdown rendering

## Completion Checklist

- [ ] Create test for METRIC_DISPLAY_ORDER completeness
- [ ] Create test for _get_unique_metrics_for_filing ordering
- [ ] Create test for unknown metric handling
- [ ] Create test for deduplication
- [ ] Create test for category ranges
- [ ] Create test for no duplicate order values
- [ ] Run verification commands (all tests pass)
- [ ] Update PROJECT_TASK_INVENTORY.md to mark MET-9 complete
- [ ] Archive this worker prompt to `docs/archive/worker-prompts-completed/`
