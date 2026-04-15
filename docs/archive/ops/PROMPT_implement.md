# Ralph Implementation Loop - Regression Fixes

You are Claude, operating in a Ralph autonomous loop to implement fixes for the Slack Technologies validation regression.

## Context

**Problem**: Validation shows P=28.6% R=63.6% F1=39.4% (baseline was P=76% R=84% F1=80%)
**Root causes identified** (from ANALYSIS_RESULTS.md):
1. cm_billings generating 49 FP (not a customer metric)
2. cm_mrr misclassifying percentages as MRR
3. cm_customers_period_end matching unrelated numbers
4. Table parsing only extracting rightmost columns
5. Validation matching using greedy first-come-first-served

## Your Task

1. Read `ops/IMPLEMENTATION_PLAN.md` to find the next `[ ]` pending task
2. Implement the fix for that ONE task only
3. Run relevant tests to verify the fix
4. Mark the task `[x]` complete in the plan with test results
5. Commit changes with message: `fix: FIX-N - brief summary`
6. Exit this session

## Implementation Details

### FIX-1: Deprecate cm_billings
```yaml
# In config/metric_keywords.yaml, add under cm_billings:
cm_billings:
  status: deprecated
  deprecation_reason: "GAAP financial metric, not customer-specific"
```

### FIX-2: Add cm_mrr to DOLLAR_ONLY_METRICS
```python
# In src/review/false_positive_filter.py
DOLLAR_ONLY_METRICS = {
    "cm_arr",
    "cm_mrr",  # ADD THIS
    ...
}
```

### FIX-3: Add cm_customers_period_end exclusions
```yaml
# In config/metric_keywords.yaml, under cm_customers_period_end:
exclusions:
  - '\b(?:eight|twelve|ten)\s+(?:languages?|months?|countries?|weeks?|days?)\b'
  - '\btrailing\s+twelve\s+months?\b'
  - '\bavailable\s+in\s+\w+\s+(?:languages?|countries?)\b'
```

### FIX-4/5: Table parsing investigation
```python
# Debug in src/extraction/html_segmenter.py
# Check _extract_table_structure() method
# Look for cell iteration logic that may skip cells
# Check if [ROW] markers include all cells or only some
```

### FIX-6: Two-pass optimal matching
```python
# In scripts/validate_against_gold_standard.py:347-432
# Replace first-come-first-served with:
# 1. Build all candidate-gold pairs with scores
# 2. Sort by score descending
# 3. Assign matches greedily from highest score
```

## File Locations

- Plan: `ops/IMPLEMENTATION_PLAN.md`
- Keyword config: `config/metric_keywords.yaml`
- False positive filter: `src/review/false_positive_filter.py`
- HTML segmenter: `src/extraction/html_segmenter.py`
- Validation script: `scripts/validate_against_gold_standard.py`
- Analysis results: `ops/ANALYSIS_RESULTS.md`

## Testing Commands

```bash
# Run unit tests
pytest tests/unit/ -x -q

# Run gold standard validation
pytest -m gold_standard --gold-standard-mode=fresh -v

# Quick validation check
python scripts/validate_against_gold_standard.py --company "Slack Technologies" --mode fresh
```

## Completion

After implementation and commit:
```
<promise>IMPLEMENTATION_ITERATION_COMPLETE</promise>
```

If all tasks done:
```
<promise>IMPLEMENTATION_COMPLETE</promise>
```

If blocked or need human review:
```
<promise>IMPLEMENTATION_PAUSED</promise>
```
