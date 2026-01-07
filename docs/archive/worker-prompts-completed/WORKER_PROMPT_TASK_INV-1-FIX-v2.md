# WORKER PROMPT: Task INV-1-FIX-v2 - Remove Unused Offset Computation

```
===============================================================================
TASK ID:       INV-1-FIX-v2
TASK NAME:     Remove Unused Character Offset Computation
WORKSTREAM:    Extraction Pipeline Simplification
SOURCE:        INV-1 Investigation + Critical Analysis (supersedes INV-1-FIX)
STATUS:        PENDING
COMPLETION:    N/A
TIME ESTIMATE: 1-2 hours
TIME ACTUAL:   N/A
RISK LEVEL:    Low - Removes unused code path
TASK SIZE:     S
DEPENDS ON:    INV-1 (complete)
UNLOCKS:       All filings process faster, Farfetch available for review
BLOCKS:        None
PARALLEL WITH: None
===============================================================================
```

## Background & Rationale

### Original Problem (INV-1)
Farfetch filing (filing_id=31) takes ~105 seconds to extract due to O(n*m) complexity in `_compute_element_offsets()`. BeautifulSoup HTML normalization causes 100% offset lookup failures, resulting in full HTML scans for each of 7,760 elements.

### Original Proposed Fix (INV-1-FIX)
Skip offset computation for filings > 1MB or > 5,000 elements.

### Critical Analysis Finding
The `char_start_offset` and `char_end_offset` fields are:
- **Stored in DB** but **never read by any feature**
- **Not used** by the human review UI (which uses keyword/value text matching)
- **Not used** by gold standard validation
- **Not used** by any scripts or downstream processing

The 1MB threshold would affect **284 out of 462 filings (61.5%)** - making it a de-facto removal anyway.

### Revised Approach
**Remove `_compute_element_offsets()` entirely.** Don't optimize unused code - delete it.

**Benefits:**
1. Performance improvement for ALL filings (not just large ones)
2. Reduced code complexity (~100 lines removed)
3. Eliminates a class of bugs (offset lookup failures)
4. Farfetch and all other filings process faster

**Risk Mitigation:**
- `html_selector` (CSS selector) provides an alternative path to source location if needed
- DB columns remain (no schema migration), just NULL values
- Can recompute offsets on-demand in future if a feature requires them

## Objective

Remove the `_compute_element_offsets()` method and all related code from HTMLSegmenter. This eliminates ~100 lines of code that computes data nobody uses, while improving performance for all filings.

## Prerequisites

- INV-1 investigation complete (documented root cause)
- Understanding that offset fields are unused by all current features

## Files to Modify

### 1. `src/extraction/html_segmenter.py`

**Remove:**
- `_compute_element_offsets()` method (lines 659-711, ~53 lines)
- `self._original_html` assignment (line 225)
- `self._last_search_position` assignment (line 226)
- Calls to `_compute_element_offsets()` in `_extract_segment()` (lines 771-773)
- Calls to `_compute_element_offsets()` in `_extract_list_segments()` (lines 1799-1801)

**Simplify:**
- `_merge_definition_segments()` offset tracking (lines 1465-1494) - remove dead code that tracks/merges offsets

**Keep unchanged:**
- `char_start_offset` and `char_end_offset` parameters in SourceSegment creation (just pass `None`)
- All other functionality

### 2. `tests/unit/extraction/test_html_segmenter.py`

**Remove:**
- Entire `TestCharacterOffsetTracking` class (lines 2960-3310, ~350 lines)

**Update:**
- Any other tests that assert `char_start_offset is not None` should be changed to `is None`

### 3. Documentation Updates

**Update `CLAUDE.md`:**
- Remove or update any references to SEG5 (character offset tracking)
- Add note that offsets are deprecated/removed

**No changes needed:**
- `src/extraction/models.py` - fields remain Optional, just always None
- `src/infra/db.py` - already handles NULL values
- `src/review/models.py` - already NotRequired
- SQL schema - columns stay for backward compatibility

## Implementation Requirements

### Core Changes

1. **Remove `_compute_element_offsets()` method**
   - Delete the entire method (lines 659-711)
   - This is the source of the O(n*m) performance issue

2. **Remove instance variables**
   - Delete `self._original_html = html_content` (line 225)
   - Delete `self._last_search_position = 0` (line 226)

3. **Update `_extract_segment()`**
   - Remove lines 771-773 (call to `_compute_element_offsets`)
   - Pass `char_start_offset=None, char_end_offset=None` to SourceSegment

4. **Update `_extract_list_segments()`**
   - Remove lines 1799-1801 (call to `_compute_element_offsets`)
   - Pass `char_start_offset=None, char_end_offset=None` to SourceSegment

5. **Simplify `_merge_definition_segments()`**
   - Remove offset tracking logic (lines 1465-1467, 1489-1494, 1513-1514)
   - These lines track and merge offsets that are now always None

### Error Handling

No new error conditions. This is a code removal, not addition.

### Performance Requirements

- All filings should process faster (no more offset computation overhead)
- Farfetch extraction time: < 30 seconds (vs current ~105s)
- No performance regression possible (only removing code)

## Test Requirements

### Tests to Remove

Delete the entire `TestCharacterOffsetTracking` class:
- `test_single_paragraph_offset_populated`
- `test_multiple_paragraphs_distinct_offsets`
- `test_table_offset_captures_full_table`
- `test_mixed_content_relative_offsets`
- `test_composite_segment_splitting_preserves_offsets`
- `test_definition_merging_spans_offsets`
- `test_list_items_distinct_offsets`
- `test_empty_or_minimal_html_graceful_handling`
- `test_offset_content_extraction_matches_raw_html`
- `test_offset_ordering_non_overlapping`
- `test_unicode_content_offset_handling`
- `test_sgml_format_offset_tracking`

### Tests to Update

Search for any remaining assertions like:
- `assert segment.char_start_offset is not None` -> change to `is None`
- `assert segment.char_end_offset is not None` -> change to `is None`

### New Tests (Optional)

Consider adding one simple test to verify offsets are None:
```python
def test_offsets_are_none_by_design(self, temp_html_file):
    """Character offsets are intentionally not computed (removed for performance)."""
    html = "<html><body><p>Test paragraph content.</p></body></html>"
    segments = segmenter.segment_filing(filing_id=1, html_path=temp_html_file(html))
    for segment in segments:
        assert segment.char_start_offset is None
        assert segment.char_end_offset is None
```

## Acceptance Criteria

- [ ] `_compute_element_offsets()` method removed from html_segmenter.py
- [ ] `_original_html` and `_last_search_position` instance variables removed
- [ ] All segments have `char_start_offset=None` and `char_end_offset=None`
- [ ] `TestCharacterOffsetTracking` test class removed
- [ ] All remaining tests pass
- [ ] Farfetch filing (id=31) extracts in < 30 seconds
- [ ] Slack filing (id=35) still extracts successfully (regression check)
- [ ] No linting or type errors
- [ ] CLAUDE.md updated to remove SEG5 references

## Do NOT

- Remove the `char_start_offset` and `char_end_offset` fields from models (keep for schema compatibility)
- Modify the database schema (columns remain, just NULL values)
- Change any downstream code (review UI, gold standard, etc.)
- Add threshold-based skip logic (we're removing, not conditionally skipping)

## Verification Commands

```bash
# Run segmenter tests (should pass after removing offset tests)
TEST_DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis_test" \
  python3 -m pytest tests/unit/extraction/test_html_segmenter.py -v --tb=short

# Check Farfetch extraction time (should be < 30s)
time DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis" \
  python scripts/rerun_single_filing.py --filing-id 31

# Verify Slack still works (regression check)
time DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis" \
  python scripts/rerun_single_filing.py --filing-id 35

# Verify no type errors
mypy src/extraction/html_segmenter.py --ignore-missing-imports

# Verify no linting issues
ruff check src/extraction/html_segmenter.py

# Full test suite
TEST_DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis_test" \
  python3 -m pytest -v --tb=short
```

## Auto-Generated Verification Script

```bash
#!/bin/bash
# Verification for Task INV-1-FIX-v2: Remove Unused Character Offset Computation
set -e

echo "==============================================================================="
echo "Verifying Task INV-1-FIX-v2: Remove Unused Character Offset Computation"
echo "==============================================================================="

# Criterion 1: Method is removed
echo "Checking: _compute_element_offsets method removed..."
if grep -q "_compute_element_offsets" src/extraction/html_segmenter.py; then
  echo "FAIL: _compute_element_offsets still exists in code"
  exit 1
fi
echo "  Method removed"

# Criterion 2: Instance variables removed
echo "Checking: _original_html and _last_search_position removed..."
if grep -q "_original_html\|_last_search_position" src/extraction/html_segmenter.py; then
  echo "FAIL: Instance variables still exist"
  exit 1
fi
echo "  Instance variables removed"

# Criterion 3: Test class removed
echo "Checking: TestCharacterOffsetTracking class removed..."
if grep -q "TestCharacterOffsetTracking" tests/unit/extraction/test_html_segmenter.py; then
  echo "FAIL: TestCharacterOffsetTracking still exists"
  exit 1
fi
echo "  Test class removed"

# Criterion 4: Unit tests pass
echo "Running: Unit tests..."
TEST_DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis_test" \
  python3 -m pytest tests/unit/extraction/test_html_segmenter.py -v --tb=short -q

# Criterion 5: Farfetch extraction time < 30s
echo "Checking: Farfetch extraction time..."
START=$(date +%s)
DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis" \
  python scripts/rerun_single_filing.py --filing-id 31 > /dev/null 2>&1
END=$(date +%s)
ELAPSED=$((END - START))
if [ $ELAPSED -gt 30 ]; then
  echo "FAIL: Farfetch took ${ELAPSED}s (expected < 30s)"
  exit 1
fi
echo "  Farfetch extraction: ${ELAPSED}s"

# Criterion 6: Slack regression check
echo "Checking: Slack extraction (regression)..."
START=$(date +%s)
DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis" \
  python scripts/rerun_single_filing.py --filing-id 35 > /dev/null 2>&1
END=$(date +%s)
ELAPSED=$((END - START))
echo "  Slack extraction: ${ELAPSED}s"

echo "==============================================================================="
echo "All acceptance criteria verified for Task INV-1-FIX-v2!"
echo "==============================================================================="
```

## Critical Evaluation Phase

**Task Size: S** - Standard evaluation depth applies.

After verification passes but BEFORE committing:

### 1. Code Quality Review
- [ ] No references to removed methods remain
- [ ] No dead code paths
- [ ] Clean removal without breaking other functionality

### 2. Test Coverage Assessment
- [ ] All offset-related tests removed
- [ ] No remaining tests assert on offset values
- [ ] Core segmentation tests still pass

### 3. Architecture Alignment
- [ ] Follows "don't optimize unused code" principle
- [ ] Maintains backward compatibility (fields exist, just NULL)
- [ ] Documents the change appropriately

### 4. User Approval Required
STOP after evaluation and ask user before committing.

## Expected Impact

**Before INV-1-FIX-v2:**
- Farfetch extraction: ~105 seconds
- Other large filings: Variable slowdown
- ~100 lines of code for unused feature

**After INV-1-FIX-v2:**
- Farfetch extraction: < 30 seconds
- All filings process faster
- ~100 lines of code removed
- Simpler, more maintainable codebase

## Reference

- **Issue source**: INV-1 Investigation Report + Critical Analysis
- **Supersedes**: INV-1-FIX (threshold-based skip approach)
- **Dependencies**: INV-1 (complete)
- **Philosophy**: "Don't optimize unused code - delete it"

---

**Last Updated**: 2026-01-06
**Format Version**: 2.6
