# WORKER PROMPT: Task EI-5 - Add Cell Boundary Markers to HTMLSegmenter

```
===============================================================================
TASK ID:       EI-5
TASK NAME:     Add cell boundary markers to preserve table structure in text extraction
WORKSTREAM:    Extraction Quality Improvements
SOURCE:        EXTRACTION_IMPROVEMENT_PLAN.md Phase 1 - Issue #4 (Adjacent Values in Text)
STATUS:        🟡 PENDING
COMPLETION:    [Will be: docs/completion/EI-5_COMPLETION_SUMMARY.md]
TIME ESTIMATE: 6-8 hours (implementation 3-4 hours, testing 3-4 hours)
TIME ACTUAL:   N/A
RISK LEVEL:    Medium - Changes text extraction format for table segments
               - Risk: TableRowParser position mapping may fail with new marker format
               - Impact: If position mapping breaks, EI-4 row validation stops working
               - Likelihood: Medium (text format change affects downstream consumers)
               - Mitigation: Extensive position mapping tests; markers are human-readable
                 and designed to not break regex patterns looking for numbers
TASK SIZE:     L (4-8 hours)
DEPENDS ON:    None (can run independently)
UNLOCKS:       EI-6 (Integration Testing - requires all EI-1 to EI-5)
BLOCKS:        None
PARALLEL WITH: EI-4 (but coordinate testing - both affect table extraction)
===============================================================================
```

## Objective

Preserve table cell boundaries in extracted text by adding `[CELL]` and `[ROW]` markers during HTML-to-text conversion, preventing adjacent numeric values from merging together.

**Business Rationale**: When table HTML is converted to plain text, cell boundaries are lost. This causes values like "171% 152% 143%" to run together, making it impossible to determine which value belongs to which column. Analysts waste time disambiguating values that should have clear separation.

**Current Behavior**: Table HTML like:
```html
<table>
  <tr><td>Metric</td><td>2023</td><td>2022</td></tr>
  <tr><td>Retention Rate</td><td>171%</td><td>152%</td></tr>
</table>
```
Becomes: `"Metric 2023 2022 Retention Rate 171% 152%"` (cell boundaries lost)

**Desired Behavior**: Same table becomes:
```
"Metric [CELL] 2023 [CELL] 2022 [ROW] Retention Rate [CELL] 171% [CELL] 152%"
```
Cell and row boundaries are clearly marked, preserving structure for downstream processing.

## Prerequisites

- None (standalone enhancement to HTMLSegmenter)
- Understanding of BeautifulSoup table parsing (`find_all('tr')`, `find_all(['td', 'th'])`)
- Understanding of `_normalize_text()` method in HTMLSegmenter
- Understanding of how `raw_text` is used downstream (TableRowParser, ValueExtractor)

## Files to Modify

1. **`src/extraction/html_segmenter.py`** - Add `_extract_table_text_with_markers()` method and modify `_extract_segment()` to use it for table elements

## Files to Read (Context Only)

- `src/extraction/html_segmenter.py` - Current `_normalize_text()` (lines 1027-1041) and `_extract_segment()` (lines 710-779)
- `src/review/table_structure.py` - TableRowParser to understand how it uses extracted text (lines 65-96)
- `src/extraction/value_extractor.py` - See how `segment.raw_text` is used in extraction
- `src/review/number_parsing.py` - See how numbers are found in text (ensure markers don't interfere)

## Implementation Requirements

### Core Functionality

1. **Create `_extract_table_text_with_markers()` Method**
   - New method in HTMLSegmenter class (add near `_normalize_text()` around line 1042)
   - Accept a BeautifulSoup Tag element (table or element containing table)
   - Find all `<tr>` elements within the table
   - For each row, find all `<td>` and `<th>` cells
   - Extract and normalize text from each cell using `_normalize_text()`
   - Join cell texts with ` [CELL] ` separator
   - Join row texts with ` [ROW] ` separator
   - Skip empty cells (cells with only whitespace after normalization)
   - Return the combined text string

2. **Modify `_extract_segment()` for Table Elements**
   - In `_extract_segment()` method (around line 728-731)
   - Current code: `raw_text = self._normalize_text(element.get_text())`
   - For table segments (`segment_type == "table"` or `element.name == "table"`):
     - Use `_extract_table_text_with_markers(element)` instead
   - For non-table segments: keep existing `_normalize_text(element.get_text())`

3. **Marker Format Specification**
   - Cell separator: ` [CELL] ` (space-bracket-CELL-bracket-space, 8 characters)
   - Row separator: ` [ROW] ` (space-bracket-ROW-bracket-space, 7 characters)
   - Markers are part of `raw_text` and included in position calculations
   - Markers should not appear at start or end of text (only between cells/rows)

4. **Position Mapping Compatibility**
   - Markers add characters to the text, shifting all positions
   - TableRowParser works with this new format (text positions still map to rows)
   - The markers themselves are NOT table content, so number parsing should ignore them
   - Regex patterns like `\d+` will still find numbers correctly (markers use letters)

### Error Handling

- **Empty table**: Return empty string (no markers needed)
- **Table with no cells**: Return empty string
- **Malformed table structure**: Fall back to `_normalize_text(element.get_text())`
- **BeautifulSoup parsing errors**: Log warning, fall back to standard normalization
- **Nested tables**: Apply markers to outermost table only (nested content treated as cell text)

### Performance Requirements

- Marker insertion adds ~5-20ms per table segment
- Negligible overhead for non-table segments (code path unchanged)
- No significant memory overhead (string operations on existing content)

### Backward Compatibility

- **API Changes**: None - `_extract_segment()` signature unchanged
- **Data Format Changes**: `raw_text` for table segments will include markers
  - Existing segments in database won't have markers (no migration needed)
  - New segments will have markers
  - Code should handle both formats gracefully
- **Downstream Consumers**:
  - TableRowParser: Will work with marker text (designed for position mapping)
  - ValueExtractor: Numbers are still findable (markers don't contain digits)
  - NumberParsing: Regex `\d+` patterns unaffected by letter-based markers
- **Feature Flags**: Not needed - markers improve quality universally
- **Re-extraction**: EI-7 will regenerate all segments with markers

## Test Requirements

### Coverage Target: **Maintain >= 90%** for `src/extraction/html_segmenter.py`

### Test Categories (15-20 tests recommended)

1. **Cell Marker Insertion** (8-10 tests)
   - `test_single_row_table_has_cell_markers` - `<tr><td>A</td><td>B</td></tr>` -> `"A [CELL] B"`
   - `test_multi_row_table_has_row_markers` - Two rows separated by `[ROW]`
   - `test_mixed_th_td_cells_all_marked` - Both `<th>` and `<td>` get cell markers
   - `test_empty_cells_skipped` - Empty cells don't create empty markers
   - `test_whitespace_only_cells_skipped` - Cells with only spaces/newlines skipped
   - `test_cell_text_normalized_before_marking` - Internal whitespace normalized
   - `test_numeric_values_separated_by_markers` - "171% [CELL] 152% [CELL] 143%"
   - `test_no_markers_at_string_boundaries` - No leading/trailing markers
   - `test_nested_table_outer_only` - Nested tables treated as cell content

2. **Position Mapping Compatibility** (4-5 tests)
   - `test_table_row_parser_works_with_markers` - TableRowParser can parse marker text
   - `test_number_parsing_finds_values_with_markers` - Numbers found despite markers
   - `test_keyword_positions_correct_with_markers` - Keyword positions account for markers
   - `test_value_positions_correct_with_markers` - Value positions account for markers
   - `test_are_in_same_row_works_with_markers` - Row validation still functional

3. **Edge Cases and Fallbacks** (3-5 tests)
   - `test_empty_table_returns_empty_string` - Table with no rows
   - `test_malformed_table_fallback_to_normalize` - Bad HTML falls back gracefully
   - `test_non_table_element_unchanged` - Paragraphs, divs not affected
   - `test_table_with_only_headers` - Table with only `<th>` row
   - `test_very_large_table_handles_markers` - 100+ cell table doesn't break

### Known Edge Cases to Test

- Tables with `colspan` and `rowspan` attributes
- Tables with missing closing tags
- Tables embedded in other elements (div > table)
- Tables with special characters in cells (parentheses, brackets)
- Tables with numeric-only content

### Test File Location

Add tests to: `tests/unit/extraction/test_html_segmenter.py`

### Test Class Name

```python
class TestTableCellMarkers:
    """EI-5: Cell boundary markers to preserve table structure."""

    def test_single_row_table_has_cell_markers(self):
        """Single row table should have [CELL] markers between cells."""
        ...

    def test_multi_row_table_has_row_markers(self):
        """Multi-row table should have [ROW] markers between rows."""
        ...

    def test_table_row_parser_works_with_markers(self):
        """TableRowParser should correctly parse text with markers."""
        ...
```

## Acceptance Criteria

- [ ] `_extract_table_text_with_markers()` method created in HTMLSegmenter
- [ ] Method correctly extracts text from `<tr>`, `<td>`, `<th>` elements
- [ ] Cell values separated by ` [CELL] ` markers
- [ ] Row values separated by ` [ROW] ` markers
- [ ] Empty and whitespace-only cells skipped (no empty markers)
- [ ] `_extract_segment()` uses marker method for table elements
- [ ] Non-table elements use existing `_normalize_text()` (unchanged)
- [ ] Fallback to `_normalize_text()` when table parsing fails
- [ ] TableRowParser still functional with marker text
- [ ] Number parsing still finds values (markers don't interfere)
- [ ] 15+ unit tests covering markers and edge cases
- [ ] Coverage maintained >= 90% for `html_segmenter.py`
- [ ] All existing tests still pass (no regressions)
- [ ] `mypy src/extraction/html_segmenter.py` has no new errors

## Do NOT

- Modify `src/review/table_structure.py` (markers designed to work with existing parser)
- Modify `src/review/number_parsing.py` (markers don't contain digits)
- Add markers to non-table elements (scope: tables only)
- Change the marker format after testing starts (downstream dependencies)
- Remove or modify `_normalize_text()` (still needed for cell content and non-tables)
- Add configuration options for marker characters (fixed format simplifies testing)
- Break existing `char_start_offset`/`char_end_offset` calculations
- Apply markers to figure elements (those have separate handling)

## Verification Commands

```bash
# Run new tests specifically
TEST_DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis_test" \
  python3 -m pytest tests/unit/extraction/test_html_segmenter.py::TestTableCellMarkers -v

# Verify no regressions in html_segmenter tests
TEST_DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis_test" \
  python3 -m pytest tests/unit/extraction/test_html_segmenter.py --no-cov -q

# Check coverage is maintained
TEST_DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis_test" \
  python3 -m pytest tests/unit/extraction/test_html_segmenter.py \
  --cov=src/extraction/html_segmenter --cov-report=term-missing -q

# Type safety check
mypy src/extraction/html_segmenter.py

# Verify TableRowParser compatibility (if available)
TEST_DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis_test" \
  python3 -m pytest tests/unit/review/test_table_structure.py --no-cov -q

# Verify number parsing still works
TEST_DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis_test" \
  python3 -m pytest tests/unit/review/test_number_parsing.py --no-cov -q

# Full extraction module regression test
TEST_DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis_test" \
  python3 -m pytest tests/unit/extraction/ --no-cov -q
```

## Expected Impact

**Before EI-5**:
- Table text: `"Retention Rate 171% 152% 143%"` (ambiguous - which value for which year?)
- Cell boundaries lost during extraction
- Adjacent numeric values merge together
- Manual disambiguation required

**After EI-5**:
- Table text: `"Retention Rate [CELL] 171% [CELL] 152% [CELL] 143%"`
- Cell boundaries preserved with clear markers
- Values remain distinct and parseable
- Downstream processing can identify column associations
- Combined with EI-4: Complete table structure awareness in extraction

## Example Implementation Reference

**Note**: This is for reference only - do NOT copy verbatim. Design your own solution.

<details>
<summary>Expand to see example structure</summary>

```python
# Example pseudocode showing the general approach
# NOT meant to be copied directly

def _extract_table_text_with_markers(self, element: Tag) -> str:
    """Extract table text with cell/row boundary markers."""
    # 1. Find the table element (may be element itself or nested)
    # 2. Find all <tr> rows
    # 3. For each row:
    #    - Find all <td>/<th> cells
    #    - Normalize each cell's text
    #    - Skip empty cells
    #    - Join with " [CELL] "
    # 4. Join rows with " [ROW] "
    # 5. Return combined text (no leading/trailing markers)
    pass
```
</details>

## Post-Implementation Tasks

After completing EI-5:

1. **Create Completion Summary**:
   - Create `docs/completion/EI-5_COMPLETION_SUMMARY.md` with:
     - Summary of changes made
     - Test results and coverage
     - Any deviations from plan
     - Example of marker output from real table
     - Commit hash

2. **Update Documentation**:
   - Mark EI-5 as COMPLETE (checkmark) in `docs/EXTRACTION_IMPROVEMENT_PLAN.md` task table
   - Update status from PENDING to COMPLETE with date

3. **Archive This Prompt**:
   - Move this file to `docs/archive/workstreams/EI-extraction-improvements/WORKER_PROMPT_TASK_EI-5.md`
   - Create the `EI-extraction-improvements` directory if it doesn't exist

4. **Commit and Push**:
   ```bash
   # Stage changes
   git add src/extraction/html_segmenter.py \
           tests/unit/extraction/test_html_segmenter.py \
           docs/EXTRACTION_IMPROVEMENT_PLAN.md \
           docs/completion/EI-5_COMPLETION_SUMMARY.md

   # Commit with descriptive message
   git commit -m "$(cat <<'EOF'
   EI-5: Add cell boundary markers to HTMLSegmenter

   Preserve table cell boundaries in extracted text by adding [CELL] and
   [ROW] markers during HTML-to-text conversion. This prevents adjacent
   numeric values from merging together when table structure is lost.

   Changes:
   - Add _extract_table_text_with_markers() method to HTMLSegmenter
   - Modify _extract_segment() to use marker method for table elements
   - Cell separator: " [CELL] " between cells in same row
   - Row separator: " [ROW] " between table rows
   - Empty/whitespace cells skipped (no empty markers)
   - Fallback to standard normalization if table parsing fails

   This addresses the "adjacent values in text" bug where table values
   like "171% 152% 143%" became ambiguous when cell boundaries were lost.

   Marker format designed to be compatible with:
   - TableRowParser (position mapping still works)
   - Number parsing (markers don't contain digits)
   - Existing extraction patterns

   Part of Phase 1 extraction quality improvements (EI-1 through EI-5).

   Co-Authored-By: Claude <noreply@anthropic.com>
   EOF
   )"

   git push origin main
   ```

## Integration Notes

**Relationship with EI-4**:
- EI-4 adds TableRowParser validation to ValueExtractor
- EI-5 adds cell markers to HTMLSegmenter
- Both can run in parallel but need coordination for integration testing
- Markers help EI-4's row validation by preserving structure
- Test that TableRowParser works correctly with marker text

**Relationship with EI-3**:
- EI-3 adds FalsePositiveFilter to ValueExtractor
- EI-5 changes the input text format for tables
- Filters should still work (markers don't affect number patterns)
- Test that false positive detection still works with marker text

**Dependencies**:
- EI-5 can run independently (no prerequisites)
- EI-5 enables EI-6 (Integration Testing - needs all fixes)
- Re-extraction (EI-7) will populate all segments with markers

## Reference

- **Issue source**: EXTRACTION_IMPROVEMENT_PLAN.md Problem 3 (Text Normalization) and Problem 4 (Adjacent Values)
- **Dependencies**: None (standalone)
- **Enables**: EI-6 (Integration Testing) - depends on this task
- **Related tasks**:
  - EI-1 (Definition Filtering) - complete, independent
  - EI-2 (Measurement Unit Patterns) - complete, independent
  - EI-3 (FalsePositiveFilter) - complete, independent
  - EI-4 (TableRowParser) - parallel, coordinate testing
  - EI-6 (Integration Testing) - depends on this task
- **Key files**:
  - `src/extraction/html_segmenter.py` - Target file
  - `src/review/table_structure.py` - TableRowParser (must remain compatible)

---

**Last Updated**: 2025-12-18
**Format Version**: 2.3 (concise requirements-focused format with dependency tracking)
