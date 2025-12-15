# WORKER PROMPT: Task L5 - Composite Segment Splitting

```markdown
═══════════════════════════════════════════════════════════════════════════════
TASK ID:       L5
TASK NAME:     Implement composite segment splitting (text + table separation)
WORKSTREAM:    Metric Logic Repairs (L-series)
SOURCE:        METRIC_IDENTIFICATION_ISSUES.md Issue 6
STATUS:        🟡 PENDING
TIME ESTIMATE: 2-3 hours (investigation 30-45 min, implementation 60-90 min, testing 30-45 min)
PARALLEL WITH: None (modifies extraction layer, independent of L1-L4)
═══════════════════════════════════════════════════════════════════════════════
```

## Objective

Implement support in `src/extraction/html_segmenter.py` for splitting composite segments (where text and tables are combined into a single segment) into distinct objects.

**Business Rationale**: The HTML segmenter sometimes creates segments containing both prose text AND table content, causing the review candidate generator to associate numbers from tables with keywords from surrounding text (or vice versa), producing false positives.

**Goal**: Enable clean separation:
1. Table content → separate segment with `segment_type='table'`
2. Text before/after table → separate segments with `segment_type='paragraph'`
3. Preserve metadata (`section_name`, `order_in_document`, etc.)

## Prerequisites

- None (L5 is independent of L1-L4 tasks)
- Understand existing `SourceSegment` data structure
- Understand HTML segmentation logic

## Files to Examine (Investigation Phase)

1. **Primary**: `src/extraction/html_segmenter.py` - Main segmentation logic (~800 lines)
2. **Supporting**: `src/extraction/models.py` - `SourceSegment` dataclass definition
3. **Tests**: `tests/unit/extraction/test_html_segmenter.py` - Existing test patterns
4. **Consumer**: `src/review/candidate_generator.py` - Understand how segments are consumed (read-only)

## Files to Modify

1. **`src/extraction/html_segmenter.py`** - Add composite segment splitting logic
2. **`tests/unit/extraction/test_html_segmenter.py`** - Add comprehensive test cases

## Implementation Requirements

### Investigation Steps (30-45 minutes)

1. **Understand Current Behavior**
   - Read `src/extraction/html_segmenter.py` completely
   - Identify where segment boundaries are determined (likely in parsing functions)
   - Find logic that handles `<table>` elements
   - Document current `segment_type` values used (paragraph, table, list, etc.)
   - Note any TODO comments or known issues

2. **Identify Composite Segment Creation**
   - Search for cases where table HTML and non-table text end up in same segment
   - Look for parent element handling (e.g., `<div>` containing both `<p>` and `<table>`)
   - Check if tables are extracted separately or included in parent text
   - Document 2-3 examples from test fixtures or real filings

3. **Design the Split**
   - Determine: Should splitting happen during parsing or post-processing?
   - Decide: How to handle `order_in_document` sequencing (increment by 0.1, 0.01, or reindex?)
   - Plan: How to preserve parent `section_name` for all split segments
   - Consider: Nested tables (table within table) - how to handle?

### Core Functionality

1. **Composite Detection**
   - Detect when a segment contains both `<table>` elements and non-table text content
   - Use regex or HTML parsing to identify `<table>...</table>` boundaries
   - Handle multiple tables in same segment (split into N+1 segments)

2. **Splitting Logic**
   - Extract text BEFORE first table → create segment with `segment_type='paragraph'`
   - Extract each `<table>` → create segment with `segment_type='table'`
   - Extract text AFTER last table → create segment with `segment_type='paragraph'`
   - **Important**: Skip creating segments for empty/whitespace-only text

3. **Metadata Preservation**
   - All split segments inherit:
     - `filing_id`
     - `section_name` (same parent section)
     - `company_id`
   - Update `order_in_document`:
     - Original segment order: N
     - Before-text: N
     - First table: N + 0.1
     - After-text: N + 0.2
     - (Or use sequential integers: N, N+1, N+2)

4. **Segment ID Handling**
   - Generate unique IDs for split segments
   - Naming convention: `{original_id}_split_{index}` or new UUID
   - Ensure no ID collisions

5. **Nested Table Handling**
   - Option A: Extract nested tables as separate segments (recursive)
   - Option B: Keep nested tables within parent table segment (simpler)
   - **Recommendation**: Option B (simpler, avoid over-splitting)

### Error Handling

- **Malformed HTML**: Log warning, return original segment unsplit
- **Empty segments after split**: Skip (don't create empty segments)
- **No exceptions should propagate** from splitting logic

### Performance Requirements

- Splitting should add <10% overhead to segmentation
- Use efficient HTML parsing (BeautifulSoup or regex, depending on existing approach)
- Avoid re-parsing entire document for each segment

## Test Requirements

### Coverage Target: **Maintain ≥ 80%** for `html_segmenter.py`

### Test Cases (15+ new tests recommended)

1. **TestCompositeSegmentSplitting** (new test class)

   ```python
   def test_segment_with_table_only_no_split(self):
       """Segment containing only table doesn't get split."""
       html = "<table><tr><td>Revenue</td><td>$1M</td></tr></table>"
       segments = segment_html(html)
       assert len(segments) == 1
       assert segments[0].segment_type == 'table'

   def test_text_before_table_creates_two_segments(self):
       """Text + table splits into 2 segments."""
       html = "<p>Our revenue metrics:</p><table>...</table>"
       segments = segment_html(html)
       assert len(segments) == 2
       assert segments[0].segment_type == 'paragraph'
       assert segments[1].segment_type == 'table'

   def test_text_table_text_creates_three_segments(self):
       """Text + table + text splits into 3 segments."""
       html = "<p>Revenue:</p><table>...</table><p>As shown above.</p>"
       segments = segment_html(html)
       assert len(segments) == 3
       assert segments[0].segment_type == 'paragraph'
       assert segments[1].segment_type == 'table'
       assert segments[2].segment_type == 'paragraph'

   def test_multiple_tables_split_correctly(self):
       """Multiple tables in one segment split into separate segments."""
       html = "<p>Data:</p><table id='t1'>...</table><table id='t2'>...</table>"
       segments = segment_html(html)
       assert len(segments) == 3
       assert [s.segment_type for s in segments] == ['paragraph', 'table', 'table']

   def test_empty_text_before_table_skipped(self):
       """Whitespace-only text before table doesn't create empty segment."""
       html = "   <table>...</table>"
       segments = segment_html(html)
       assert len(segments) == 1
       assert segments[0].segment_type == 'table'

   def test_section_name_preserved_across_splits(self):
       """All split segments inherit parent section_name."""
       # Test that section_name is same for all split segments

   def test_order_in_document_sequencing(self):
       """Split segments have increasing order_in_document values."""
       # Test that order values are: N, N+0.1, N+0.2, etc.

   def test_nested_table_not_split_separately(self):
       """Nested tables stay within parent table segment."""
       html = "<table><tr><td><table>...</table></td></tr></table>"
       segments = segment_html(html)
       assert len(segments) == 1
       assert '<table>' in segments[0].text  # Contains nested table

   def test_malformed_html_doesnt_crash(self):
       """Malformed HTML returns original segment with warning log."""
       html = "<table><tr><td>Unclosed"
       # Should not raise exception

   def test_segment_ids_unique_after_split(self):
       """All split segments have unique IDs."""
       # Test ID generation logic

   def test_metadata_preserved(self):
       """filing_id, company_id, section_name preserved on split."""
       # Test all metadata fields
   ```

2. **Integration Tests**
   - Test with real SEC filing HTML samples
   - Verify candidate generator produces fewer false positives after splitting

### Edge Cases to Test

- Segments with only whitespace between tables
- Tables with complex nested structure
- Very large tables (100+ rows)
- Tables with unusual attributes or classes

## Acceptance Criteria

- [ ] Composite segment detection implemented in `html_segmenter.py`
- [ ] Splitting logic creates separate paragraph and table segments
- [ ] Empty text segments are skipped (no whitespace-only segments)
- [ ] Metadata preserved across all split segments (`section_name`, `filing_id`, etc.)
- [ ] `order_in_document` properly sequenced for split segments
- [ ] Unique IDs generated for split segments
- [ ] Nested tables handled correctly (not over-split)
- [ ] **15+ unit tests** covering core splitting, edge cases, metadata preservation
- [ ] **Test coverage ≥ 80%** maintained for `html_segmenter.py`
- [ ] All existing tests still pass
- [ ] No performance regression (segmentation <10% slower)
- [ ] Malformed HTML doesn't crash (graceful degradation)

## Do NOT Modify

- `src/review/` modules (other workers may be modifying these)
- `src/infra/` modules
- Database schema (unless absolutely necessary)
- `src/extraction/models.py` (unless SourceSegment needs new field)

## Verification Commands

```bash
# Run new segmenter tests
TEST_DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis_test" \
  python3 -m pytest tests/unit/extraction/test_html_segmenter.py::TestCompositeSegmentSplitting -v

# Check coverage maintained
TEST_DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis_test" \
  python3 -m pytest tests/unit/extraction/test_html_segmenter.py \
  --cov=src/extraction/html_segmenter --cov-report=term-missing

# Run all extraction tests (regression check)
TEST_DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis_test" \
  python3 -m pytest tests/unit/extraction/ --no-cov -q

# Type check (if typed)
mypy src/extraction/html_segmenter.py --strict

# Integration test: Verify fewer false positives in candidate generation
TEST_DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis_test" \
  python3 -m pytest tests/integration/test_e2_candidate_filtering.py -v
```

## Expected Impact

**Before L5**:
- Composite segments create false positive candidates
- Example: "Revenue" keyword in paragraph matched to number in table
- Estimated 5-10% of candidates are cross-boundary false positives

**After L5**:
- Clean segment boundaries prevent cross-boundary matching
- False positive rate reduced by ~5-10%
- Cleaner separation improves confidence scoring

## Example Implementation Reference

**Note**: Design your own solution - this is for reference only.

<details>
<summary>Expand to see example structure</summary>

```python
# In src/extraction/html_segmenter.py

def split_composite_segment(segment: SourceSegment) -> List[SourceSegment]:
    """
    Split a segment containing both text and tables into separate segments.

    Args:
        segment: Original segment that may contain mixed content

    Returns:
        List of segments (may be 1 if no splitting needed, or 2+ if split)
    """
    # 1. Check if segment contains <table> tags
    if '<table' not in segment.text.lower():
        return [segment]  # No split needed

    # 2. Parse HTML and extract table boundaries
    # (Use BeautifulSoup or regex depending on existing approach)

    # 3. Extract text before first table
    # 4. Extract each table
    # 5. Extract text after last table

    # 6. Create new segments with proper metadata
    split_segments = []
    base_order = segment.order_in_document

    # Add before-text segment (if non-empty)
    if before_text.strip():
        split_segments.append(SourceSegment(
            filing_id=segment.filing_id,
            segment_type='paragraph',
            text=before_text,
            order_in_document=base_order,
            section_name=segment.section_name,
            # ... other metadata ...
        ))

    # Add table segments
    for i, table_html in enumerate(tables):
        split_segments.append(SourceSegment(
            filing_id=segment.filing_id,
            segment_type='table',
            text=table_html,
            order_in_document=base_order + (i + 1) * 0.1,
            section_name=segment.section_name,
            # ... other metadata ...
        ))

    # Add after-text segment (if non-empty)

    return split_segments

def segment_filing(html: str) -> List[SourceSegment]:
    """Main segmentation function - now applies composite splitting."""
    # ... existing segmentation logic ...

    # Apply composite splitting to all segments
    final_segments = []
    for segment in raw_segments:
        split = split_composite_segment(segment)
        final_segments.extend(split)

    return final_segments
```
</details>

## Reference

- **Issue source**: `METRIC_IDENTIFICATION_ISSUES.md` Issue 6
- **Related**: L1-L4 (improve candidate generation quality)
- **Downstream impact**: Should reduce false positives in review system

---

**Last Updated**: 2025-12-15
**Format Version**: 2.0 (concise requirements-focused format)
```
