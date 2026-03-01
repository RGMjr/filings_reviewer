# EI-4 Completion Summary: TableRowParser Validation in ValueExtractor

**Task ID**: EI-4
**Completed**: 2025-12-18
**Commit**: [To be added after commit]

## Summary

Integrated `TableRowParser` into `ValueExtractor` to validate that keyword-value pairs are in the same table row, preventing cross-row false associations where metric labels from row N incorrectly match values from row N-1 or N+1.

## Changes Made

### `src/extraction/value_extractor.py`

1. **Import Added** (line 20):
   ```python
   from ..review.table_structure import TableRowParser
   ```

2. **TableRowParser Creation in `extract_from_table()`** (lines 468-478):
   - Creates `TableRowParser` from `segment.raw_html` and `segment.raw_text`
   - Includes try/except for graceful fallback if initialization fails
   - Logs debug message on successful creation

3. **Modified `_parse_table_row()` Signature** (line 991):
   - Added optional `row_parser: Optional[TableRowParser] = None` parameter
   - Updated docstring to document new parameter

4. **Row Boundary Validation** (lines 1055-1072):
   - Tracks `cohort_position` for row validation
   - Before creating `MetricValue`, validates positions with `row_parser.are_in_same_row()`
   - Cross-row matches logged at DEBUG level and skipped
   - Includes try/except for graceful fallback if validation fails

5. **Logging Enhancements** (lines 1099-1102):
   - Added counter for cross-row rejections
   - Debug log shows count of filtered cross-row matches per row

### `tests/unit/extraction/test_value_extractor.py`

Added `TestRowBoundaryValidation` class with 12 tests:

1. **Row Boundary Validation Tests** (5 tests):
   - `test_cross_row_match_rejected_row_above` - Keywords don't match values from prior row
   - `test_cross_row_match_rejected_row_below` - Keywords don't match values from subsequent row
   - `test_same_row_match_accepted` - Same-row matches work correctly
   - `test_row_heading_matches_same_row_values` - Row headings match their row's values
   - `test_multi_row_table_correct_associations` - Multi-row tables extract correct associations

2. **Edge Case/Graceful Degradation Tests** (5 tests):
   - `test_segment_without_raw_html_extracts_normally` - Handles missing HTML
   - `test_segment_without_raw_text_extracts_normally` - Handles missing raw_text
   - `test_position_not_found_extracts_normally` - Handles position lookup failures
   - `test_table_with_irregular_structure_handled` - Handles rowspan/colspan
   - `test_empty_rows_ignored` - Handles tables with empty rows

3. **Integration with EI-3 Tests** (2 tests):
   - `test_row_validation_with_false_positive_filter` - Both filters work together
   - `test_filter_order_correct_fp_then_row` - FP filter runs before row validation

## Test Results

```
97 tests passed
0 tests failed
```

All existing tests continue to pass. The new 12 EI-4 tests verify row boundary validation.

## Coverage

`value_extractor.py` coverage: 60% (unchanged from before EI-4)

Note: The uncovered lines are primarily LLM-related methods that require an actual LLM client to test. The EI-4 specific code (row boundary validation) is fully covered by tests.

## Deviations from Plan

1. **Test values adjusted**: Used values like `10,500`, `25,000`, `37,500` instead of `1,000`, `2,000`, `3,000` to avoid triggering the FalsePositiveFilter's year detection (since `2,000` parses to `2000` which is detected as a likely year).

2. **raw_text format**: Tests use raw_text format that matches what `TableRowParser` extracts from HTML, including header row text for proper position alignment.

## Key Implementation Details

### Filter Order
The implementation ensures proper filter order:
1. **FalsePositiveFilter (EI-3)** runs first - removes page numbers, years, dates
2. **Row boundary validation (EI-4)** runs second - validates same-row constraint

### Fallback Behavior
Following the "never block extraction" principle:
- If `raw_html` or `raw_text` is missing: Skip row validation, extract normally
- If `TableRowParser` initialization fails: Log warning, extract normally
- If cohort position not found: Skip row validation for that value
- If value position not found: Skip row validation for that value
- If `are_in_same_row()` raises exception: Log debug, extract normally

### Position Mapping
Row validation depends on text positions aligning correctly between:
- `segment.raw_text` (the extracted text)
- HTML structure parsed by `TableRowParser`

For accurate row validation, `raw_text` should match what `TableRowParser` would extract from the HTML.

## Example Cross-Row Rejection

```
DEBUG: Cross-row match rejected: cohort='Gross profit' at pos 31, value='450,069' at pos 18
```

This shows the EI-4 fix preventing "Gross profit" from matching "450,069" from the prior "Cost of revenues" row.

## Dependencies Verified

- `src/review/table_structure.py` - Unchanged, reused as-is
- `src/review/false_positive_filter.py` - Works correctly with EI-4

## Next Steps

EI-4 completion enables:
- **EI-6** (Integration Testing) - Can now test full extraction pipeline with both EI-3 and EI-4 fixes
