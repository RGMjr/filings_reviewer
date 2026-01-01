# WORKER PROMPT: Task GR-8 - Add NaN/Inf Validation

```
═══════════════════════════════════════════════════════════════════════════════
TASK ID:       GR-8
TASK NAME:     Validate richness_score for NaN and infinity values
WORKSTREAM:    Code Quality
SOURCE:        docs/GOLDMINE_REMEDIATION_PLAN.md - Phase 1 Critical Accuracy
STATUS:        🟡 PENDING
TIME ESTIMATE: 1 hour (implementation 15 min, testing 30 min, edge cases 15 min)
RISK LEVEL:    NONE (defensive coding, no breaking changes)
TASK SIZE:     XS (< 30 min implementation, < 1 hour total)
DEPENDS ON:    None
UNLOCKS:       None (standalone safety improvement)
BLOCKS:        None
PARALLEL WITH: GR-1, GR-2, GR-4, GR-6, GR-7, GR-9
═══════════════════════════════════════════════════════════════════════════════
```

## Objective

Add validation to ensure richness_score never returns NaN (Not a Number) or Infinity values, which could cause downstream issues in segment selection and database storage.

**Business Rationale**: Silent data corruption from NaN/Inf values can cause unpredictable behavior in the extraction pipeline - comparisons with NaN always return False, and Infinity can cause database errors or incorrect sorting. Defensive validation prevents these edge cases.

**Current Behavior**: If any calculation produces NaN or Inf (e.g., division by zero, overflow), it propagates through the system silently.

**Desired Behavior**: NaN and Inf values are detected and replaced with 0.0, with an error log for debugging.

## Prerequisites

- None (standalone task)

## Files to Modify

1. **`src/extraction/segment_enricher.py`** - Add validation before returning richness_score
2. **`tests/unit/extraction/test_segment_enricher.py`** - Add NaN/Inf validation tests

## Files to Read (Context Only)

- `src/extraction/segment_enricher.py` - Find `_calculate_richness_score()` method (around line 1000+)

## Implementation Requirements

### Core Functionality

1. **Import math Module**
   - Add `import math` at top of file if not already present

2. **Add Validation Before Return**
   - At the end of `_calculate_richness_score()` method, before returning the score:
   ```python
   if math.isnan(score) or math.isinf(score):
       logger.error(
           "Invalid richness score detected: %s for segment %s. Returning 0.0",
           score,
           segment_id  # or other identifying info
       )
       return 0.0
   ```

3. **Validation Placement**
   - Must be the final check before `return score`
   - Should catch any NaN/Inf from upstream calculations

### Error Handling

- NaN → log error, return 0.0
- +Infinity → log error, return 0.0
- -Infinity → log error, return 0.0
- Normal values → pass through unchanged

### Performance Requirements

- `math.isnan()` and `math.isinf()` are O(1) operations
- Negligible performance impact

## Test Requirements

### Coverage Target: ≥ 95% for new validation code

### Test Categories (6+ tests)

1. **NaN Detection** (2 tests)
   - Simulate NaN input → returns 0.0
   - Verify error is logged

2. **Infinity Detection** (2 tests)
   - Simulate +Infinity → returns 0.0
   - Simulate -Infinity → returns 0.0

3. **Normal Value Pass-through** (2 tests)
   - Normal score (e.g., 5.5) → passes through unchanged
   - Score 0.0 → passes through as 0.0
   - Score 10.0 → passes through as 10.0

### Known Edge Cases to Test

- Very small positive values (should pass through)
- Very large values that are still finite (should pass through)
- Negative scores (should pass through - they're valid, just low)

## Acceptance Criteria

- [ ] `import math` added (if not present)
- [ ] NaN/Inf validation added before return statement
- [ ] Error logged when invalid value detected
- [ ] Invalid values replaced with 0.0
- [ ] Normal values pass through unchanged
- [ ] 6+ unit tests covering validation
- [ ] All existing tests pass
- [ ] `pytest tests/unit/extraction/test_segment_enricher.py -v` passes

## Do NOT

- Change any scoring calculation logic
- Add validation at multiple points (only at final return)
- Raise exceptions (return 0.0 and log instead)
- Modify how bonuses are calculated

## Verification Commands

```bash
# Run unit tests
TEST_DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis_test" \
  python3 -m pytest tests/unit/extraction/test_segment_enricher.py -v -k "nan or inf or invalid" --tb=short

# Run all enricher tests
TEST_DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis_test" \
  python3 -m pytest tests/unit/extraction/test_segment_enricher.py -v --tb=short

# Verify math import
grep -n "import math" src/extraction/segment_enricher.py

# Verify validation exists
grep -n "isnan\|isinf" src/extraction/segment_enricher.py
```

## Example Implementation Reference

**Note**: This is for reference only - do NOT copy verbatim.

<details>
<summary>Expand to see example structure</summary>

```python
import math

# In _calculate_richness_score() method, at the end:

def _calculate_richness_score(self, segment: SourceSegment) -> float:
    """Calculate richness score for segment."""
    score = 0.0

    # ... existing calculation logic ...

    # Final validation before return
    if math.isnan(score) or math.isinf(score):
        logger.error(
            "Invalid richness score detected: %s for segment_id=%s. Returning 0.0",
            score,
            getattr(segment, 'id', 'unknown')
        )
        return 0.0

    return score
```
</details>

## Expected Impact

**Before GR-8**:
- NaN/Inf values silently propagate
- Potential database errors on Infinity values
- Unpredictable comparison behavior with NaN

**After GR-8**:
- NaN/Inf values caught and logged
- Clean 0.0 fallback prevents downstream issues
- Production safety improved
- Debugging easier with logged errors

---

**Last Updated**: 2025-12-25
**Format Version**: 2.4
