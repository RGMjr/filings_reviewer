# Worker Prompt: MET-8 - Eliminate Dropdown Ordering DRY Violation

## Task Overview

| Field | Value |
|-------|-------|
| Task ID | MET-8 |
| Task Name | Eliminate Dropdown Ordering DRY Violation |
| Size | S (30 min - 2 hours) |
| Priority | Medium |
| Dependencies | None |
| Blocking | MET-9 |

## Objective

Eliminate the duplication where metric dropdown ordering is defined in both a SQL CASE statement AND a Python dictionary. Create a single source of truth.

## Background

The current implementation defines the same ordering in two places:

1. **SQL CASE statement** (`src/web/routes/review.py` lines 966-1010):
   ```sql
   ORDER BY
       CASE metric_id
           WHEN 'cm_customers_period_end' THEN 1
           WHEN 'cm_active_customers_total' THEN 2
           ...
       END
   ```

2. **Python dictionary** (`src/web/routes/review.py` lines 1019-1052):
   ```python
   METRIC_DISPLAY_ORDER: dict[str, int] = {
       "cm_customers_period_end": 1,
       "cm_active_customers_total": 2,
       ...
   }
   ```

If ordering changes, both must be updated manually. This violates DRY (Don't Repeat Yourself).

## Requirements

### R1: Choose Single Source of Truth

**Option A: Python dict as source (Recommended)**
- Define ordering in `METRIC_DISPLAY_ORDER` dict
- Generate SQL CASE dynamically from dict
- Pro: Python is easier to maintain, test, and document
- Pro: Can be reused across multiple queries

**Option B: SQL as source**
- Keep SQL CASE statement
- Remove Python dict, fetch and sort in Python after query
- Con: Requires fetching all metrics then sorting in Python

### R2: Implement Option A

Modify `_get_active_metrics()` to build SQL dynamically:

```python
def _get_active_metrics() -> list[MetricData]:
    """Get list of active metrics for dropdown, sorted by semantic grouping."""
    if "metrics" not in g:
        db = get_db()

        # Build CASE statement from METRIC_DISPLAY_ORDER
        case_clauses = "\n".join(
            f"WHEN '{metric_id}' THEN {order}"
            for metric_id, order in METRIC_DISPLAY_ORDER.items()
        )

        metrics_sql = f"""
            SELECT metric_id, display_name, metric_class, primary_concept
            FROM metrics
            WHERE status = 'active'
            ORDER BY
                CASE metric_id
                    {case_clauses}
                    ELSE 99
                END
        """
        g.metrics = db.query(metrics_sql)
    return g.metrics
```

### R3: Add Category Comments to Dict

Enhance the dict with clear category documentation:

```python
# Metric ordering for dropdowns - semantic grouping by business category
# This is the SINGLE SOURCE OF TRUTH for dropdown ordering.
# The SQL CASE statement is generated dynamically from this dict.
METRIC_DISPLAY_ORDER: dict[str, int] = {
    # Category 1: Customer Count Metrics (1-9)
    "cm_customers_period_end": 1,
    ...

    # Category 2: Transaction & Purchase Behavior (11-19)
    "cm_purchase_transactions_overall": 11,
    ...
}
```

### R4: Remove Hardcoded SQL CASE

Remove the duplicated CASE clauses from the SQL string literal.

### R5: Extract Helper Function (Required)

Create a helper function for building the ORDER BY clause. This improves testability and makes the pattern explicit:

```python
def _build_metric_order_clause() -> str:
    """
    Build SQL CASE statement for metric ordering from METRIC_DISPLAY_ORDER.

    SAFETY NOTE: This uses f-string SQL building which is safe ONLY because
    metric_ids are hardcoded constants from METRIC_DISPLAY_ORDER, never user input.
    DO NOT copy this pattern for user-supplied values.
    """
    clauses = [
        f"WHEN '{metric_id}' THEN {order}"
        for metric_id, order in METRIC_DISPLAY_ORDER.items()
    ]
    return "CASE metric_id\n" + "\n".join(clauses) + "\nELSE 99\nEND"
```

### R6: Write Unit Tests for SQL Generation (Required)

Add tests in `tests/unit/web/test_review_routes.py`:

```python
class TestBuildMetricOrderClause:
    """Tests for _build_metric_order_clause SQL generation."""

    def test_generates_valid_case_statement(self):
        """Verify generated SQL has correct structure."""
        from src.web.routes.review import _build_metric_order_clause, METRIC_DISPLAY_ORDER

        clause = _build_metric_order_clause()

        assert clause.startswith("CASE metric_id")
        assert "ELSE 99" in clause
        assert clause.endswith("END")

    def test_includes_all_metrics_from_dict(self):
        """Verify every metric in METRIC_DISPLAY_ORDER appears in SQL."""
        from src.web.routes.review import _build_metric_order_clause, METRIC_DISPLAY_ORDER

        clause = _build_metric_order_clause()

        for metric_id, order in METRIC_DISPLAY_ORDER.items():
            assert f"WHEN '{metric_id}' THEN {order}" in clause

    def test_ordering_values_are_integers(self):
        """Verify all THEN values are valid integers."""
        from src.web.routes.review import _build_metric_order_clause
        import re

        clause = _build_metric_order_clause()
        then_values = re.findall(r"THEN (\d+)", clause)

        assert len(then_values) > 0
        for val in then_values:
            assert val.isdigit()
```

### R7: Add Safety Documentation

Add a comment block above `METRIC_DISPLAY_ORDER` explaining:
1. This is the single source of truth
2. Gap numbering (1-9, 11-19, etc.) allows future insertions without renumbering
3. The f-string SQL pattern is safe only for hardcoded values

```python
# Metric ordering for dropdowns - semantic grouping by business category.
# This is the SINGLE SOURCE OF TRUTH for dropdown ordering.
# The SQL CASE statement is generated dynamically from this dict.
#
# ORDERING CONVENTION:
#   - Category 1 (Customer Counts): 1-9
#   - Category 2 (Transactions): 11-19
#   - Category 3 (Revenue): 21-29
#   - Category 4 (Retention/Churn): 31-39
#   - Category 5 (Unit Economics): 41-49
#   Gaps allow inserting new metrics without renumbering existing ones.
#
# SAFETY: These IDs are used in f-string SQL generation. This is safe because
# they are hardcoded constants. Never add user-supplied values to this dict.
```

## Verification Commands

```bash
# 1. Run the new unit tests for SQL generation
TEST_DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis_test" \
  python3 -m pytest tests/unit/web/test_review_routes.py::TestBuildMetricOrderClause -v

# 2. Run all web unit tests
TEST_DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis_test" \
  python3 -m pytest tests/unit/web/ -v --tb=short

# 3. Run web integration tests
TEST_DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis_test" \
  python3 -m pytest tests/integration/web/ -v --tb=short

# 4. Verify no hardcoded CASE clauses remain in _get_active_metrics
# Use ast-grep for structural search (more reliable than grep)
ast-grep run --pattern 'def _get_active_metrics($$$):
    $$$
    WHEN $_ THEN $_
    $$$' --lang python src/web/routes/review.py
# Expected: No matches (CASE is now generated dynamically)

# 5. Verify helper function exists
ast-grep run --pattern 'def _build_metric_order_clause() -> str:' --lang python src/web/routes/review.py
# Expected: 1 match

# 6. Manual verification: Start Flask and check dropdown order
# DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis" python3 -m src.web.app
# Navigate to review page, verify metrics appear in category order
```

## Deliverables

1. **Single source of truth**: `METRIC_DISPLAY_ORDER` dict is the only place ordering is defined
2. **Dynamic SQL generation**: CASE statement built from dict via `_build_metric_order_clause()` helper
3. **Unit tests**: `TestBuildMetricOrderClause` class with 3 tests covering SQL generation
4. **Safety documentation**: Comments explain single-source pattern, gap numbering convention, and f-string safety constraints
5. **All tests pass**: No regressions in dropdown functionality

## Out of Scope

- Changing the actual ordering (that's already defined)
- Adding new metrics
- Modifying the filter dropdown logic (uses same dict)

## Completion Checklist

- [ ] Create `_build_metric_order_clause()` helper function (R5)
- [ ] Modify `_get_active_metrics()` to use helper function (R2)
- [ ] Remove hardcoded SQL CASE clauses (R4)
- [ ] Add safety documentation comments to dict (R7)
- [ ] Write unit tests in `TestBuildMetricOrderClause` class (R6)
- [ ] Run verification commands 1-5 (all pass)
- [ ] Manual verification: dropdown order correct in Flask UI
- [ ] Update PROJECT_TASK_INVENTORY.md to mark MET-8 complete
- [ ] Archive this worker prompt to `docs/archive/worker-prompts-completed/`

## Technical Notes

- **SQL injection safety**: Not a risk because metric IDs come from a hardcoded dict, never user input. However, this f-string pattern should NOT be copied for user-supplied values elsewhere.
- **Deterministic output**: The generated SQL is deterministic and can be logged for debugging if needed.
- **Performance**: String building happens once per request (cached in Flask's `g` object). Impact is negligible (<1ms).
- **Gap numbering**: Categories use non-consecutive numbers (1-9, 11-19, 21-29, etc.) so new metrics can be inserted without renumbering existing entries.
- **Dict iteration order**: Python 3.7+ guarantees dict insertion order, so `METRIC_DISPLAY_ORDER.items()` produces consistent SQL.
