# WORKER PROMPT: Task INV-1-FIX - Implement Farfetch Extraction Fix

```
===============================================================================
TASK ID:       INV-1-FIX
TASK NAME:     Skip Offset Computation for Large Filings
WORKSTREAM:    Extraction Pipeline Performance
SOURCE:        INV-1 Investigation Report (docs/investigation/INV-1_FARFETCH_EXTRACTION_REPORT.md)
STATUS:        🟡 PENDING
COMPLETION:    N/A
TIME ESTIMATE: 1-2 hours (implementation 30 min, testing 45 min, validation 30 min)
TIME ACTUAL:   N/A
RISK LEVEL:    Low - Offset data is optional (used for UI highlighting only)
TASK SIZE:     S
DEPENDS ON:    INV-1 (complete)
UNLOCKS:       Farfetch filing available for human review
BLOCKS:        None
PARALLEL WITH: None
===============================================================================
```

## Objective

Implement Approach A from INV-1 investigation: skip `_compute_element_offsets()` for large filings to eliminate the O(n*m) performance degradation caused by BeautifulSoup HTML normalization failures.

**Business Rationale**: The Farfetch filing (filing_id=31) currently takes ~105 seconds to process (vs 5.5s for comparable Slack filing) due to 100% offset lookup failures. This fix reduces processing time to acceptable levels, enabling Farfetch to be used for human review quality assessment.

**Current Behavior**:
- Farfetch extraction takes ~105 seconds (19x slower than Slack)
- 7,760 elements each scan the full 2.75MB HTML when offset lookup fails
- ~21 billion character comparisons total

**Desired Behavior**:
- Farfetch extraction completes in <30 seconds
- Large filings gracefully skip offset computation
- Offset data set to None for affected segments (acceptable - UI highlighting optional)

## Prerequisites

- INV-1 investigation complete (✅)
- Understanding of `_compute_element_offsets()` at `html_segmenter.py:659-711`

## Files to Modify

1. **`src/extraction/html_segmenter.py`** - Add threshold check before offset computation
2. **`tests/unit/extraction/test_html_segmenter.py`** - Add tests for skip logic

## Files to Read (Context Only)

- `docs/investigation/INV-1_FARFETCH_EXTRACTION_REPORT.md` - Root cause analysis and recommendation

## Implementation Requirements

### Core Functionality

1. **Threshold-Based Skip Logic**
   - Skip `_compute_element_offsets()` when HTML size > 1MB (1,000,000 chars)
   - OR skip when element count > 5,000 elements
   - Thresholds should be class constants for easy adjustment
   - Set `char_start` and `char_end` to None when skipped

2. **Logging**
   - Log a WARNING when offsets are skipped with filing context
   - Include HTML size and element count in log message
   - Use existing logger pattern in HTMLSegmenter

3. **Backward Compatibility**
   - No changes to segment data structure (char_start/char_end already Optional)
   - No changes to downstream consumers (they already handle None offsets)
   - Existing filings continue to compute offsets normally

### Error Handling

- No new error conditions - this is a performance optimization only
- Existing error handling for offset computation remains unchanged

### Performance Requirements

- Farfetch extraction time: < 30 seconds (vs current ~105s)
- No performance regression for normal-sized filings (< 1MB)
- Memory usage unchanged

## Test Requirements

### Coverage Target: Maintain existing coverage for `html_segmenter.py`

### Test Categories (5+ tests)

1. **Threshold Tests** (2-3 tests)
   - Test skip triggered when HTML > 1MB
   - Test skip triggered when element count > 5,000
   - Test normal processing when below both thresholds

2. **Segment Output Tests** (2 tests)
   - Verify char_start/char_end are None when skipped
   - Verify char_start/char_end populated when not skipped

3. **Logging Tests** (1 test)
   - Verify WARNING logged when offsets skipped

### Known Edge Cases to Test

- File exactly at threshold (1MB or 5,000 elements)
- Very large file with few elements (e.g., large tables)
- Many elements in small file

## Acceptance Criteria

- [ ] Farfetch filing (id=31) extracts in < 30 seconds
- [ ] Offset skip logic implemented with configurable thresholds
- [ ] WARNING logged when offsets are skipped
- [ ] 5+ unit tests covering skip logic and thresholds
- [ ] All existing tests still pass
- [ ] Slack filing (id=35) still computes offsets normally (regression check)
- [ ] No changes to segment data model

## Do NOT

- Modify the offset computation algorithm itself (that's Approach B/C)
- Change the segment data model
- Add new dependencies
- Modify `_compute_element_offsets()` internal logic

## Verification Commands

```bash
# Run new tests
TEST_DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis_test" \
  python3 -m pytest tests/unit/extraction/test_html_segmenter.py -v -k "offset"

# Check Farfetch extraction time
time DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis" \
  python scripts/rerun_single_filing.py --filing-id 31

# Verify Slack still works normally (regression)
time DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis" \
  python scripts/rerun_single_filing.py --filing-id 35

# Full segmenter test suite
TEST_DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis_test" \
  python3 -m pytest tests/unit/extraction/test_html_segmenter.py -v --tb=short
```

## Auto-Generated Verification Script

Copy this entire block to verify all acceptance criteria in one command:

```bash
#!/bin/bash
# Auto-generated verification for Task INV-1-FIX: Skip Offset Computation for Large Filings
# Run: bash verify_inv1fix.sh

set -e
echo "==============================================================================="
echo "Verifying Task INV-1-FIX: Skip Offset Computation for Large Filings"
echo "==============================================================================="

# Criterion 1: Farfetch extraction time < 30 seconds
echo "✓ Checking: Farfetch extraction time..."
START=$(date +%s)
DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis" \
  python scripts/rerun_single_filing.py --filing-id 31 > /dev/null 2>&1
END=$(date +%s)
ELAPSED=$((END - START))
if [ $ELAPSED -gt 30 ]; then
  echo "✗ FAIL: Farfetch took ${ELAPSED}s (expected < 30s)"
  exit 1
fi
echo "  Farfetch extraction: ${ELAPSED}s (< 30s) ✓"

# Criterion 2: Slack still works (regression check)
echo "✓ Checking: Slack extraction (regression)..."
START=$(date +%s)
DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis" \
  python scripts/rerun_single_filing.py --filing-id 35 > /dev/null 2>&1
END=$(date +%s)
ELAPSED=$((END - START))
echo "  Slack extraction: ${ELAPSED}s ✓"

# Criterion 3: Unit tests pass
echo "✓ Checking: Unit tests..."
TEST_DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis_test" \
  python3 -m pytest tests/unit/extraction/test_html_segmenter.py -v --tb=short -q

echo "==============================================================================="
echo "✅ All acceptance criteria verified for Task INV-1-FIX!"
echo "==============================================================================="
```

## Critical Evaluation Phase

**Task Size: S** - Standard evaluation depth applies.

After verification passes but BEFORE committing:

### 1. Code Quality Review
- [ ] No linting issues or type errors
- [ ] Constants named clearly (e.g., `OFFSET_SKIP_HTML_THRESHOLD`)
- [ ] Logging message is clear and actionable

### 2. Test Coverage Assessment
- [ ] Threshold edge cases covered
- [ ] Both skip conditions tested independently
- [ ] Regression check included

### 3. Architecture Alignment
- [ ] Follows conservative classification principle (skip optional data)
- [ ] No over-engineering

### 4. User Approval Required
STOP after evaluation and ask user before committing.

## Expected Impact

**Before INV-1-FIX**:
- Farfetch extraction: ~105 seconds
- Appears to "hang" (exceeds user patience)

**After INV-1-FIX**:
- Farfetch extraction: < 30 seconds
- Farfetch available for human review

## Reference

- **Issue source**: INV-1 Investigation Report
- **Dependencies**: INV-1 (complete)
- **Related**: HRV-4 (Farfetch validation), HRV-22 (data fix)

---

**Last Updated**: 2026-01-06
**Format Version**: 2.6
