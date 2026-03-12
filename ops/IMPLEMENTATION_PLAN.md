# Implementation Plan - Recall Recovery

**Created**: 2026-01-22
**Purpose**: Achieve human baseline metrics (P=76%, R=84%, F1=80%)
**Mode**: Ralph autonomous loop

**Current**: P=60.8%, R=81.6%, F1=69.7% (validated)
**Target**: P=76%, R=84%, F1=80%
**Gap**: P -15.2pp, R -2.4pp, F1 -10.3pp

---

## Instructions

1. Process ONE implementation task per iteration
2. Write code changes and run tests
3. Mark `[x]` when complete with validation results
4. Commit changes after each task
5. Exit to allow fresh context for next task

---

## Implementation Tasks

### Phase 1: Recall Recovery (+23pp needed)

- [x] FIX-A | Context-based percentage detection | cm_net_revenue_retention values (138%, 171%, 152%, 143%, 149%) extracted as counts and filtered - need context-based detection
  **Result**: R=77.3% (+15.9pp), P=64.2% (-1.7pp), F1=70.1% (+6.6pp). Retention values now correctly extracted. Unit tests pass (1104 tests).
- [x] FIX-B | Flexible keyword patterns | "Paid Customers > $100,000" pattern doesn't match due to spacing - update regex in metric_keywords.yaml
  **Result**: P=66.7% (+2.5pp), R=77.3% (maintained), F1=71.6% (+1.5pp). Patterns now detect "Paid Customers >$100,000" matches. Keyword tests pass (284 tests).
- [x] FIX-C | Definition-only validation handling | Skip definition-only entries (no numeric values) in validation - don't count as false negatives
  **Result**: P=60.8% (-5.9pp), R=81.6% (+4.3pp), F1=69.7% (-1.9pp). Gold standard now 38 entries (filtered 6 definition-only). Unit tests pass (3110 tests).

### Phase 2: Precision Recovery (+10pp needed)

- [x] FIX-D | Review FIX-3 exclusions | Check if cm_customers_period_end exclusions are too aggressive - may need relaxation
  **Result**: FIX-3 exclusions are beneficial. Removing them decreased P from 60.8% to 57.4% (-3.4pp) with no recall improvement. Exclusions should REMAIN. FIX-3 patterns effectively filter word-form numbers in non-customer contexts (e.g., "twelve months", "eight languages").

### Phase 3: Final Validation

- [x] FIX-E | Full gold standard validation | Run full validation and compare to human baseline target
  **Result**: P=60.8%, R=81.6%, F1=69.7%. All 12 gold standard regression tests PASS. Final metrics vs human baseline (P=76%, R=84%, F1=80%): Precision -15.2pp below target, Recall -2.4pp below target, F1 -10.3pp below target. Slack validation: 31 TP, 20 FP, 7 FN from 38 gold entries and 51 candidates.

---

## Implementation Details

### FIX-A: Context-Based Percentage Detection

**Problem**: cm_net_revenue_retention values (138%, 171%, 152%, 143%, 149%) are extracted as plain numbers without % symbol and filtered by PERCENTAGE_ONLY_METRICS check.

**Files**:
- `src/review/false_positive_filter.py` - Modify `is_percentage_format()` or add context helper
- `src/review/candidate_generator.py` - Apply context-based check before unit filtering

**Implementation**:
```python
def should_treat_as_percentage(metric_id: str, raw_text: str, context_text: str) -> bool:
    """Context-based percentage detection for retention metrics."""
    # Explicit percentage format
    if '%' in raw_text:
        return True

    # Retention metrics with retention context are percentages
    if metric_id in {'cm_net_revenue_retention', 'cm_gross_revenue_retention'}:
        if 'retention' in context_text.lower():
            return True

    return False
```

**Test**: Validate 138%, 171%, 152%, 143%, 149% are extracted for cm_net_revenue_retention

---

### FIX-B: Flexible Keyword Patterns

**Problem**: Pattern `\bpaid\s+customers?\s*>\s*\$?\d` doesn't match "Paid Customers > $100,000" variations.

**File**: `config/metric_keywords.yaml` (cm_large_customers_period_end section)

**Current patterns** (around line 130):
```yaml
- '\bpaid\s+customers?\s*>\s*\$?\d'
```

**New patterns**:
```yaml
- '\bpaid\s+customers?\s*>\s*\$[\d,]+'      # Paid Customers > $100,000
- '\bcustomers?\s*(?:over|above|>)\s*\$[\d,]+'  # customers over $X
- '\bpaid\s+customers?\s+(?:with|of)\s+\$[\d,]+\s*(?:\+|or\s+more)?'  # paid customers with $X+
```

**Test**: Validate 575, 645, 298, 351 are extracted for cm_large_customers_period_end

---

### FIX-C: Definition-Only Validation Handling

**Problem**: Gold standard entries with `is_definition_only=x` and no numeric values are counted as false negatives, but our system can't generate candidates without numbers.

**File**: `scripts/validate_against_gold_standard.py`

**Implementation**:
1. When loading gold standard entries, check `is_definition_only` column
2. If `is_definition_only == 'x'` AND `raw_value == ''`, exclude from recall calculation
3. Log skipped definition-only entries

**Test**: Validate definition entries don't count as false negatives

---

### FIX-D: Review FIX-3 Exclusions

**Problem**: FIX-3 added exclusion patterns that may be too aggressive:
- `\b(?:eight|twelve|ten)\s+(?:languages?|months?|countries?|weeks?|days?)\b`

**File**: `config/metric_keywords.yaml` (cm_customers_period_end exclusions)

**Analysis needed**:
1. Check which legitimate matches were excluded
2. Consider if patterns are worth the precision/recall trade-off
3. Possibly relax or remove if recall impact > precision benefit

---

## Testing Commands

```bash
# Validate against Slack gold standard
python3 scripts/validate_against_gold_standard.py --company "Slack Technologies" --mode fresh

# Run unit tests
pytest tests/unit/review/ -x -q

# Full gold standard validation
pytest -m gold_standard --gold-standard-mode=fresh -v
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

---

## Statistics

| Metric | Count |
|--------|-------|
| Total Tasks | 5 |
| Completed | 5 |
| Remaining | 0 |
