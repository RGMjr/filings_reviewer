# WORKER PROMPT: Task SEG5 - Character Offset Tracking

```markdown
═══════════════════════════════════════════════════════════════════════════════
TASK ID:       SEG5
TASK NAME:     Implement character offset tracking for source segments
WORKSTREAM:    Segmentation Improvements (Phase C - Features)
SOURCE:        docs/SEGMENTATION_IMPROVEMENT_PLAN.md Item #5
STATUS:        🟡 PENDING
COMPLETION:    N/A
TIME ESTIMATE: 2-3 hours (investigation 30 min, implementation 60 min, testing 60 min)
TIME ACTUAL:   N/A
RISK LEVEL:    Low (additive feature, no changes to existing logic)
PARALLEL WITH: SEG6, SEG8, SEG10 (all Phase C features are independent)
═══════════════════════════════════════════════════════════════════════════════
```

## Objective

Populate the existing `char_start_offset` and `char_end_offset` fields in `SourceSegment` with accurate character positions relative to the original HTML content.

**Business Rationale**: Precise source location enables:
- UI highlighting of extracted text in the original document
- Debugging extraction issues by pinpointing exact source location
- Cross-referencing extracted values back to original filings for audit

**Current Behavior**: The `char_start_offset` and `char_end_offset` fields in `SourceSegment` (models.py:31-33) are defined but always `None`.

**Desired Behavior**: After segmentation, each segment has accurate character offsets pointing to its location in the original HTML content.

## Prerequisites

- None (standalone task)
- Read `src/extraction/html_segmenter.py` to understand the segmentation flow
- Read `src/extraction/models.py` to understand `SourceSegment` structure

## Files to Modify

1. **`src/extraction/html_segmenter.py`** - Add offset tracking logic during extraction
2. **`tests/unit/extraction/test_html_segmenter.py`** - Add tests for offset tracking

## Files to Read (Context Only)

- `src/extraction/models.py` - Understand `SourceSegment` dataclass (lines 14-57)
- `docs/SEGMENTATION_IMPROVEMENT_PLAN.md` - Task specification (lines 201-228)

## Implementation Requirements

### Core Functionality

1. **Track Character Offsets During Element Extraction**
   - Compute offsets relative to the **original HTML content** (before BeautifulSoup parsing)
   - Each segment's `char_start_offset` should point to where its source element starts in the HTML
   - Each segment's `char_end_offset` should point to where its source element ends
   - Handle the fact that BeautifulSoup elements have `sourceline` and `sourcepos` attributes (Python 3.8+ with lxml parser) OR use element string representation matching

2. **Design Choice: HTML vs Text Offsets**
   - **Option A (Recommended)**: Offsets into raw HTML string - enables precise DOM highlighting
   - **Option B**: Offsets into extracted text stream - simpler but less useful for UI
   - Choose Option A if feasible; document decision in code comments

3. **Handle Edge Cases**
   - Segments created from composite splitting (`_split_composite_segment`) - inherit parent offsets or compute sub-offsets
   - Merged definition segments (`_merge_definition_segments`) - use earliest start, latest end
   - List item segments - track individual `<li>` positions within the `<ul>/<ol>`

4. **Preserve Existing Behavior**
   - Offset tracking is purely additive - no changes to segment text, types, or sequence indices
   - If offset computation fails for any reason, log a warning and leave fields as `None`

### Error Handling

- **Element not found in HTML**: Log debug message, set offsets to `None`
- **Invalid position data**: Log warning, set offsets to `None`
- **No exceptions should propagate** - offset tracking is non-critical

### Performance Requirements

- Minimal overhead: Use string matching only if BeautifulSoup position attributes unavailable
- Do not re-parse HTML - use the existing `soup` object
- Target: <5% increase in `segment_filing()` execution time

## Test Requirements

### Coverage Target: **Maintain ≥85%** for `src/extraction/html_segmenter.py`

### Test Categories (8+ tests recommended)

1. **Basic Offset Tracking** (3-4 tests)
   - Single paragraph: verify start/end offsets match element position
   - Multiple paragraphs: verify offsets are distinct and ordered
   - Table element: verify offsets capture full table HTML
   - Mixed content: paragraphs + tables have correct relative offsets

2. **Edge Cases** (3-4 tests)
   - Composite segment splitting: child segments have valid offsets
   - Definition merging: merged segment spans original elements
   - List items: each `<li>` has distinct offsets
   - Empty/minimal segments: gracefully handled (offsets may be None)

3. **Verification Tests** (1-2 tests)
   - Substring extraction: `html_content[start:end]` contains the segment's source
   - Offset ordering: `seg[i].char_end_offset <= seg[i+1].char_start_offset` (non-overlapping)

### Known Edge Cases to Test

- Nested elements (paragraph inside div)
- Unicode content (non-ASCII characters)
- SGML format with `<TEXT>` wrapper
- Segments with truncated text (offsets should reference original, not truncated)

## Acceptance Criteria

- [ ] `char_start_offset` populated for all successfully extracted segments
- [ ] `char_end_offset` populated for all successfully extracted segments
- [ ] Offsets are relative to original HTML content (not parsed/modified content)
- [ ] Composite-split segments have valid offsets
- [ ] Merged definition segments have valid spanning offsets
- [ ] **8+ unit tests** covering basic cases and edge cases
- [ ] **Test coverage ≥85%** maintained (run `pytest --cov=src/extraction/html_segmenter`)
- [ ] All new tests pass
- [ ] All existing tests still pass (regression check)
- [ ] No exceptions raised when offset computation fails (graceful degradation)

## Do NOT

- Modify `src/extraction/models.py` (SourceSegment already has the fields)
- Change the signature of `segment_filing()` or other public methods
- Add new dependencies (use BeautifulSoup's existing position tracking or string matching)
- Affect existing segment extraction logic (text content, types, sequence indices)
- Re-parse HTML multiple times (use existing `soup` object)

## Verification Commands

```bash
# Run new tests
TEST_DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis_test" \
  python3 -m pytest tests/unit/extraction/test_html_segmenter.py -v -k "offset"

# Check coverage maintained (must be ≥85%)
TEST_DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis_test" \
  python3 -m pytest tests/unit/extraction/test_html_segmenter.py \
  --cov=src/extraction/html_segmenter --cov-report=term-missing --cov-fail-under=85

# Full regression test
TEST_DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis_test" \
  python3 -m pytest tests/unit/extraction/test_html_segmenter.py --no-cov -q
```

## Expected Impact

**Before SEG5**:
- `char_start_offset` and `char_end_offset` are always `None`
- No way to map extracted segments back to source HTML position
- UI highlighting of source not possible

**After SEG5**:
- All segments have accurate character offsets
- Enables `html_content[segment.char_start_offset:segment.char_end_offset]` to retrieve source
- Foundation for UI source highlighting feature

## Implementation Hints

<details>
<summary>Expand to see implementation hints (reference only)</summary>

**Approach 1: BeautifulSoup Position Attributes**
```python
# BeautifulSoup with lxml parser provides sourceline/sourcepos
# However, html.parser (currently used) does NOT provide these
# If you switch to lxml, element.sourceline and element.sourcepos are available
```

**Approach 2: String Matching (Recommended)**
```python
# Store original HTML content before parsing
# After extracting element, find its position in original HTML
# Use str(element) to get element's HTML representation
# Find that string in original content

# In segment_filing(), store html_content before parsing:
# self._original_html = html_content

# In _extract_segment(), after creating segment:
# element_html = str(element)
# pos = self._original_html.find(element_html, search_start)
# if pos >= 0:
#     segment.char_start_offset = pos
#     segment.char_end_offset = pos + len(element_html)
```

**Key insight**: The `_calculate_document_positions()` method (lines 1071-1101) shows a similar pattern of tracking cumulative position - follow this pattern for offset tracking.
</details>

## Documentation Updates

After implementation, update:
1. **`docs/SEGMENTATION_IMPROVEMENT_PLAN.md`**: Mark SEG5 as ✅ Complete with commit hash
2. Add inline code comments explaining the offset tracking approach

## Commit and Push

After all tests pass:
```bash
# Stage changes
git add src/extraction/html_segmenter.py tests/unit/extraction/test_html_segmenter.py

# Commit with descriptive message
git commit -m "SEG5: Implement character offset tracking for source segments

Add char_start_offset and char_end_offset population during HTML segmentation.
Enables precise source location for UI highlighting and audit trails.

🤖 Generated with [Claude Code](https://claude.ai/code)

Co-Authored-By: Claude <noreply@anthropic.com>"

# Push to main
git push origin main
```