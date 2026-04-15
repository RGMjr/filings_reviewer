# Worker Prompt: Fix LLM Metric Name Mapping Conflicts

## Task ID: REV-05
## Priority: P1 (Accuracy Impact)
## Effort: S (1-2 hours)
## Finding IDs: G-D2-001

---

## Problem Statement

`METRIC_NAME_MAPPING` in `src/extraction/value_extractor.py` maps `"customer_count"` and `"total_customers"` to `cm_active_customers_total`. But `config/metric_keywords.yaml` explicitly treats `"total customers"` as `cm_customers_period_end` (stock count) and distinguishes it from `"active"` customers (engagement-based).

### Impact

- **Hurts precision**: Wrong metric_id assigned
- **Hurts recall**: Correct metric_id never produced for some LLM outputs
- **Undermines taxonomy**: Your own semantic distinction in YAML is violated

---

## Files to Modify

- `src/extraction/value_extractor.py` - Fix METRIC_NAME_MAPPING

---

## Acceptance Criteria

1. [ ] METRIC_NAME_MAPPING aligns with metric_keywords.yaml taxonomy
2. [ ] "total_customers" maps to `cm_customers_period_end` (not active)
3. [ ] "active_customers" maps to `cm_active_customers_total`
4. [ ] Unit test asserts correct mapping for key terms
5. [ ] Gold standard validation passes with no regression

---

## Analysis: Current vs Expected Mappings

### Current (WRONG)

```python
METRIC_NAME_MAPPING = {
    "customer_count": "cm_active_customers_total",  # WRONG - should be period_end
    "total_customers": "cm_active_customers_total", # WRONG - should be period_end
    ...
}
```

### Expected (CORRECT)

Based on `config/metric_keywords.yaml`:

| LLM Output | Should Map To | Reason |
|------------|---------------|--------|
| `total_customers` | `cm_customers_period_end` | Stock count at period end |
| `customer_count` | `cm_customers_period_end` | Stock count (no activity qualifier) |
| `active_customers` | `cm_active_customers_total` | Engagement-based |
| `active_users` | `cm_active_customers_total` | Engagement-based |
| `paid_customers` | `cm_customers_period_end` | Paying = stock count |
| `total_users` | `cm_customers_period_end` | Stock count |

---

## Implementation

### Step 1: Review metric_keywords.yaml

```yaml
# config/metric_keywords.yaml
cm_customers_period_end:
  patterns:
    - "total customers"
    - "paid customers"
    - "total paying customers"
    - "total users"
  # Stock count - number at end of period

cm_active_customers_total:
  patterns:
    - "active customers"
    - "active users"
    - "monthly active users"
    - "daily active users"
  # Engagement-based - activity threshold
```

### Step 2: Fix METRIC_NAME_MAPPING

```python
# src/extraction/value_extractor.py

METRIC_NAME_MAPPING = {
    # Period-end counts (stock metrics)
    "customer_count": "cm_customers_period_end",
    "customers": "cm_customers_period_end",
    "total_customers": "cm_customers_period_end",
    "paid_customers": "cm_customers_period_end",
    "paying_customers": "cm_customers_period_end",
    "total_users": "cm_customers_period_end",
    "total_subscribers": "cm_customers_period_end",
    "subscriber_count": "cm_customers_period_end",

    # Active counts (engagement metrics)
    "active_customers": "cm_active_customers_total",
    "active_users": "cm_active_customers_total",
    "monthly_active_users": "cm_active_customers_total",
    "daily_active_users": "cm_active_customers_total",
    "mau": "cm_active_customers_total",
    "dau": "cm_active_customers_total",

    # ... rest of mappings
}
```

### Step 3: Add Unit Test

```python
# tests/unit/extraction/test_value_extractor.py

def test_metric_name_mapping_aligns_with_taxonomy():
    """Ensure LLM metric mapping aligns with YAML taxonomy."""
    from src.extraction.value_extractor import METRIC_NAME_MAPPING

    # Period-end metrics (stock counts)
    period_end_terms = [
        "customer_count",
        "total_customers",
        "paid_customers",
        "customers",
        "total_users",
    ]
    for term in period_end_terms:
        assert METRIC_NAME_MAPPING.get(term) == "cm_customers_period_end", \
            f"'{term}' should map to cm_customers_period_end"

    # Active metrics (engagement-based)
    active_terms = [
        "active_customers",
        "active_users",
        "monthly_active_users",
        "daily_active_users",
        "mau",
        "dau",
    ]
    for term in active_terms:
        assert METRIC_NAME_MAPPING.get(term) == "cm_active_customers_total", \
            f"'{term}' should map to cm_active_customers_total"
```

---

## Verification Commands

```bash
# Run unit tests
pytest tests/unit/extraction/test_value_extractor.py -v -k "metric_name_mapping"

# Run gold standard validation (REQUIRED for extraction changes)
pytest -m gold_standard --gold-standard-mode=fresh -v

# Check for regressions
python scripts/validate_against_gold_standard.py --all --mode fresh --baseline
```

---

## Risk Assessment

- **Low risk**: Simple mapping change
- **Requires gold standard validation**: Yes - extraction logic changed
- **Potential for regression**: Low - fixing an existing bug, not changing logic
