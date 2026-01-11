# DROPPED: P2-UF-1 - Unit-Based Metric Filtering

## Drop Decision

**Status:** DROPPED (2026-01-07)
**Reason:** Duplicates existing functionality

### Critical Evaluation Summary

This task proposed adding `unit_constraints` to `config/metric_keywords.yaml` to filter metric-unit mismatches. However, **this system already exists** in `src/review/false_positive_filter.py`:

1. **Existing Constants:**
   - `PERCENTAGE_ONLY_METRICS`: Metrics that must be percentages
   - `DOLLAR_ONLY_METRICS`: Metrics that must be currency
   - `COUNT_ONLY_METRICS`: Metrics that must be counts

2. **Existing Filtering Logic** (`candidate_generator.py:802-838`):
   ```python
   if metric_id in COUNT_ONLY_METRICS:
       if not is_count_format(raw_text, unit):
           type_mismatch = True
   ```

3. **The Actual Bug:**
   The metrics mentioned (`cm_large_customers_period_end`, `cm_customers_period_end`, etc.) were simply not added to `COUNT_ONLY_METRICS`.

### Resolution

Instead of the 3-4 hour P2-UF-1 task, a **15-minute fix** was applied:

```python
# Added to COUNT_ONLY_METRICS in false_positive_filter.py:
'cm_customers_period_end',
'cm_active_customers_total',
'cm_large_customers_period_end',
'cm_new_customers_acquired',
```

### Why YAML Migration Was Not Needed

1. Type constraints change rarely (semantic, not data-driven)
2. Python sets are simpler, type-checked, and already working
3. YAML migration would add parsing complexity with no benefit
4. The existing system is already tested and integrated

---

# Original Worker Prompt (for reference)

# WORKER PROMPT: Task P2-UF-1 - Unit-Based Metric Filtering

```markdown
═══════════════════════════════════════════════════════════════════════════════
TASK ID:       P2-UF-1
TASK NAME:     Add unit compatibility rules to prevent metric-unit mismatches in candidate generation
WORKSTREAM:    Human Review System Improvements - Phase 2
SOURCE:        Slack filing duplicate candidates analysis (snuggly-watching-micali.md)
STATUS:        🔴 DROPPED (duplicates existing functionality)
COMPLETION:    N/A
TIME ESTIMATE: 3-4 hours (analysis 1h, implementation 1.5h, testing 1.5h)
TIME ACTUAL:   15 minutes (added missing metrics to existing COUNT_ONLY_METRICS)
RISK LEVEL:    Medium (could exclude valid edge cases if rules too strict)
TASK SIZE:     M → XS (actual fix)
DEPENDS ON:    DUP-3 (Deduplicator and Helpers Integration)
UNLOCKS:       None (end of this workstream)
BLOCKS:        None
PARALLEL WITH: None
═══════════════════════════════════════════════════════════════════════════════
```

## Original Objective

Add unit compatibility rules to `config/metric_keywords.yaml` to prevent obviously incorrect metric-unit matches (e.g., percentages matching customer count metrics).

**Business Rationale**: In the Slack filing review, retention rate percentages (146%, 149%, 151%) incorrectly matched the "Customers >$100" keyword and generated candidates for `cm_large_customers_period_end`. These are clearly Net Revenue Retention values, not customer counts. This wastes reviewer time and reduces confidence in the system.

**Current Behavior**: Any numeric value near a metric keyword generates a candidate, regardless of whether the value's unit makes sense for that metric.

**Desired Behavior**:
1. Metrics define allowed and/or forbidden unit types
2. Candidate generation filters out unit-incompatible matches
3. Filtering logged for debugging

[Rest of original prompt omitted for brevity - see git history]
