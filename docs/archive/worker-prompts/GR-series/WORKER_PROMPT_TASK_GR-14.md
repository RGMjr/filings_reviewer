# WORKER PROMPT: Task GR-14 - Skip Image Detection for Text Segments

```
═══════════════════════════════════════════════════════════════════════════════
TASK ID:       GR-14
TASK NAME:     Skip HTML parsing for paragraph segments in image detection
WORKSTREAM:    Performance
SOURCE:        docs/GOLDMINE_REMEDIATION_PLAN.md - Phase 2 Performance
STATUS:        🟡 PENDING
TIME ESTIMATE: 1 hour (implementation 15 min, testing 30 min, benchmarking 15 min)
RISK LEVEL:    NONE (performance optimization only)
TASK SIZE:     S (30 min - 2 hours)
DEPENDS ON:    None
UNLOCKS:       GR-15 (performance regression tests)
BLOCKS:        None
PARALLEL WITH: GR-11, GR-12, GR-13, GR-16, GR-17
═══════════════════════════════════════════════════════════════════════════════
```

## Objective

Add an early return in `_detect_images()` for paragraph segments to skip unnecessary HTML parsing, improving performance by 10-15%.

**Business Rationale**: The `_detect_images()` method parses HTML to count `<img>` tags. For paragraph segments (which are pure text, not tables), this HTML parsing is unnecessary overhead. Approximately 70% of segments are paragraphs, so skipping image detection for them provides significant performance improvement.

**Current Behavior**: `_detect_images()` parses HTML for all segment types, including paragraphs that never contain images.

**Desired Behavior**: `_detect_images()` immediately returns 0 for paragraph segments, skipping HTML parsing.

## Prerequisites

- None (standalone optimization)

## Files to Modify

1. **`src/extraction/segment_enricher.py`** - Add early return in `_detect_images()` (around line 809)
2. **`tests/unit/extraction/test_segment_enricher.py`** - Test early return behavior

## Files to Read (Context Only)

- `src/extraction/segment_enricher.py` lines 805-840 - Current `_detect_images()` method
- `src/extraction/models.py` - SourceSegment.segment_type values

## Implementation Requirements

### Core Functionality

1. **Add Early Return for Paragraphs**

   At the start of `_detect_images()`:
   ```python
   def _detect_images(self, segment: SourceSegment) -> int:
       """Count images in segment. Returns 0 for text-only segments."""
       # Early return for text-only segments (no HTML to parse)
       if segment.segment_type == "paragraph":
           return 0

       # Existing HTML parsing logic for tables and other types
       ...
   ```

2. **Identify All Text-Only Segment Types**
   - Check SourceSegment.segment_type possible values
   - May also include: "list_item", "header" if those don't contain images
   - Conservative approach: only skip "paragraph" initially

3. **Preserve Existing Behavior**
   - Table segments still get image detection
   - Mixed content segments still parsed
   - Return value semantics unchanged

### Error Handling

- Missing segment_type: Default to existing behavior (parse HTML)
- None segment: Handle gracefully (return 0)

### Performance Requirements

- Target: 10-15% reduction in enrichment time for paragraph-heavy filings
- No impact on image detection accuracy for tables

### Test Requirements

#### Coverage Target: **Maintain existing coverage** for `segment_enricher.py`

#### Test Categories (5+ tests)

1. **Early Return Tests** (3 tests)
   - Paragraph segment returns 0 immediately
   - Early return doesn't parse HTML for paragraphs
   - Verify no HTML parsing overhead for text segments

2. **Preserved Behavior Tests** (2-3 tests)
   - Table segments still detect images
   - Segments with images return correct count
   - Mixed content segments handled correctly

### Known Edge Cases to Test

- Paragraph with segment_type=None (should parse HTML)
- Table segment with no images (should still return 0 but via parsing)
- Segment type case sensitivity

## Acceptance Criteria

- [ ] `_detect_images()` returns 0 immediately for paragraph segments
- [ ] No HTML parsing for paragraph segments
- [ ] Table segments still detect images correctly
- [ ] All existing tests pass
- [ ] 5+ tests covering early return and preserved behavior
- [ ] Benchmark shows 10%+ improvement for paragraph-heavy filings
- [ ] `pytest tests/unit/extraction/test_segment_enricher.py -v` passes

## Do NOT

- Remove image detection for tables (they may have images)
- Change the return value semantics
- Skip for all segment types without verification
- Modify other detection methods (only `_detect_images`)

## Verification Commands

```bash
# Run enricher tests
TEST_DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis_test" \
  python3 -m pytest tests/unit/extraction/test_segment_enricher.py -v --tb=short

# Run specific image detection tests
TEST_DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis_test" \
  python3 -m pytest tests/unit/extraction/test_segment_enricher.py -k "image" -v --tb=short

# Quick verification
python3 -c "
from src.extraction.segment_enricher import SegmentEnricher
from src.extraction.models import SourceSegment

enricher = SegmentEnricher()
para_seg = SourceSegment(id=1, segment_type='paragraph', raw_text='text only')
table_seg = SourceSegment(id=2, segment_type='table', raw_html='<img src=\"x.png\">')

print(f'Paragraph images: {enricher._detect_images(para_seg)}')  # Should be 0
print(f'Table images: {enricher._detect_images(table_seg)}')  # Should be 1
"
```

## Example Implementation Reference

**Note**: This is for reference only - do NOT copy verbatim.

<details>
<summary>Expand to see example structure</summary>

```python
# In segment_enricher.py

def _detect_images(self, segment: SourceSegment) -> int:
    """
    Count images in segment.

    Returns 0 immediately for text-only segments (paragraphs)
    to avoid unnecessary HTML parsing.
    """
    # Early return for text-only segments - no images possible
    if segment.segment_type == "paragraph":
        return 0

    # Also skip other text-only types if identified
    # if segment.segment_type in ("list_item", "header"):
    #     return 0

    # Existing HTML parsing logic for tables and mixed content
    if not segment.raw_html:
        return 0

    try:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(segment.raw_html, "html.parser")
        return len(soup.find_all("img"))
    except Exception:
        return 0
```
</details>

## Expected Impact

**Before GR-14**:
- HTML parsing for all 25,000 segments
- BeautifulSoup initialized even for text-only paragraphs
- Unnecessary overhead for 70% of segments

**After GR-14**:
- HTML parsing only for table/mixed segments (~30%)
- Immediate return for paragraphs (~70%)
- 10-15% overall enrichment speedup
- Reduced BeautifulSoup import overhead

---

**Last Updated**: 2025-12-25
**Format Version**: 2.4
