# Metric Lifecycle Guide

This command provides guidance for adding, deprecating, or removing customer metrics.

## Quick Reference

See `docs/development/metric-lifecycle-process.md` for the authoritative guide.

## Adding a New Metric

### 1. Define the Pattern
Add to `config/metric_keywords.yaml`:
```yaml
cm_new_metric:
  primary:
    - "new metric name"
    - "alternative name"
  context:
    - "required context word"
  negative:
    - "words that disqualify"
```

### 2. Add Database Definition
Insert into `metric_definitions` table:
```sql
INSERT INTO metric_definitions (metric_id, display_name, category, description)
VALUES ('cm_new_metric', 'New Metric Name', 'Category', 'Description of what this measures');
```

### 3. Update UI Mapping
Add to dropdown in `src/web/templates/` and route handlers.

### 4. Validate
```bash
pytest -m gold_standard --gold-standard-mode=fresh -v
```

## Deprecating a Metric

When a metric should no longer be extracted but historical data must be preserved:

1. Remove from `config/metric_keywords.yaml`
2. Keep database definition with `deprecated=true`
3. Remove from UI dropdowns
4. Document in commit message

## Removing a Metric

Only when NO production data exists for the metric:

1. Remove from `config/metric_keywords.yaml`
2. Remove database definition
3. Remove from UI components
4. Verify no orphaned references

## Naming Conventions

- Prefix: `cm_` (customer metric)
- Style: lowercase with underscores
- Examples: `cm_customers_period_end`, `cm_active_customers_total`, `cm_net_revenue_retention`

## Dropdown Category Ordering

1. Customer counts
2. Engagement metrics
3. Retention metrics
4. Revenue metrics
5. Other/custom
