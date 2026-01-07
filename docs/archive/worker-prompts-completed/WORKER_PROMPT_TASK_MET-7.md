# Worker Prompt: MET-7 - Resolve Alias Contradiction for cm_active_customers_total

## Task Overview

| Field | Value |
|-------|-------|
| Task ID | MET-7 |
| Task Name | Resolve Alias Contradiction |
| Size | S (30 min - 2 hours) |
| Priority | Critical |
| Dependencies | None |
| Blocking | MET-9, MET-11 |

## Objective

Resolve the semantic contradiction where `cm_active_customers_total` is defined both as an alias of `cm_customers_period_end` AND as a standalone metric with its own patterns.

## Background

The current implementation has a logical contradiction:

1. **As alias** (`config/metric_keywords.yaml` line 90):
   ```yaml
   cm_customers_period_end:
     aliases:
       - cm_active_customers_total
   ```

2. **As standalone metric** (`config/metric_keywords.yaml` line 182):
   ```yaml
   cm_active_customers_total:
     patterns:
       - '\bactive\s+customers?\b'
       - '\bactive\s+consumers?\b'
       ...
   ```

3. **In dropdown ordering** (`src/web/routes/review.py` line 1022):
   ```python
   "cm_active_customers_total": 2,  # Separate from cm_customers_period_end
   ```

This is semantically confused:
- If `cm_active_customers_total` is an alias, extraction should resolve to `cm_customers_period_end`
- If they are distinct metrics, there should be no alias relationship
- The dropdown shows both as separate options, implying they are distinct

## Requirements

### R1: Clarify Semantic Distinction

Determine the correct relationship. Based on the user's earlier input:

> "Active Customers" is different from "Total Customers." "Total Customers" and "Customers at Period End" are the same metric.

This means:
- `cm_customers_period_end` = "Total Customers" (stock count at period end)
- `cm_active_customers_total` = "Active Customers" (engagement-based, e.g., logged in, made purchase)

These are **distinct metrics**, NOT aliases.

### R2: Remove Alias Declaration

In `config/metric_keywords.yaml`, remove the alias declaration:

**Before:**
```yaml
cm_customers_period_end:
  aliases:
    - cm_active_customers_total
  patterns:
    ...
```

**After:**
```yaml
cm_customers_period_end:
  # No aliases - cm_active_customers_total is a distinct metric
  patterns:
    ...
```

### R3: Verify Pattern Separation

Confirm patterns are correctly separated:

| Metric | Patterns |
|--------|----------|
| `cm_customers_period_end` | "total customers", "customer base", "customers at period end", "paid customers" |
| `cm_active_customers_total` | "active customers", "active users", "active accounts" |

### R4: Update keyword_config.py if Needed

If `keyword_config.py` has alias resolution logic that needs updating, modify accordingly.

### R5: Document Decision

Add a comment in YAML explaining the distinction:

```yaml
# =============================================================================
# Customer Count Metrics - Semantic Distinctions
# =============================================================================
# cm_customers_period_end: Stock count of customers at period end ("total customers")
# cm_active_customers_total: Engagement-based count ("active customers" - implies activity criteria)
# These are DISTINCT metrics, not aliases. "Total" ≠ "Active"
# =============================================================================
```

## Verification Commands

```bash
# Verify YAML syntax
python3 -c "import yaml; yaml.safe_load(open('config/metric_keywords.yaml'))"

# Check no alias remains
grep -A2 "cm_customers_period_end:" config/metric_keywords.yaml | grep -c "cm_active_customers_total"
# Expected: 0

# Verify both metrics exist as separate entries
grep "^cm_customers_period_end:" config/metric_keywords.yaml
grep "^cm_active_customers_total:" config/metric_keywords.yaml

# Run unit tests
TEST_DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis_test" python3 -m pytest tests/unit/review/ -q --tb=short
```

## Deliverables

1. **Updated YAML**: Alias removed, clear documentation of distinction
2. **No test failures**: All existing tests pass
3. **Clear semantic model**: Two distinct metrics with no overlap

## Out of Scope

- Changing dropdown ordering (already correct)
- Running gold standard validation (that's MET-11)
- Adding new metrics

## Completion Checklist

- [ ] Remove alias declaration from cm_customers_period_end
- [ ] Verify patterns are correctly separated
- [ ] Add documentation comment explaining distinction
- [ ] Update keyword_config.py if needed
- [ ] Run verification commands (all tests pass)
- [ ] Update PROJECT_TASK_INVENTORY.md to mark MET-7 complete
- [ ] Archive this worker prompt to `docs/archive/worker-prompts-completed/`

## Notes

- The alias system was designed for gold standard compatibility (different names for same concept)
- In this case, "active" and "total" are genuinely different concepts
- This change may affect gold standard results - that validation is in MET-11
