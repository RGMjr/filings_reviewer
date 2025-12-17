# HTML Segmentation Improvement Plan

**Version:** 1.1
**Created:** 2025-12-16
**Last Updated:** 2025-12-16
**Status:** In Progress

---

## Implementation Status Summary

### Completed (8 of 12 items - 67%)

**Phase A - Quick Wins:** ✅ **Complete** (3/3 items)
- SEG2: SGML case insensitivity
- SEG3: Singleton BoundaryDetector
- SEG4: Expand continuation patterns

**Phase B - Performance:** ✅ **Complete** (2/2 items)
- SEG1: Heading cache binary search
- SEG11: Parallel sentence detection

**Phase C - Features:** ✅ **Complete** (4/4 items)
- SEG5: Character offset tracking
- SEG6: Hierarchical section paths
- SEG8: Additional element types (blockquote, pre, figure)
- SEG10: CSS selector generation

**Phase D - Polish:** 🟡 **In Progress** (1/3 items)
- SEG7: Robust encoding detection ✅

### Recent Commits
- `be96a98` SEG7: Robust encoding detection with charset-normalizer (Dec 17)
- `b6da6b2` SEG10: CSS selector generation (Dec 17)
- `95a7feb` SEG8: Additional element types (Dec 17)
- `3ad44c1` SEG11: Parallel sentence detection (Dec 16)
- `d332a57` SEG1: Binary search for heading cache (Dec 16)
- `1d5c4db` SEG4: Expand definition patterns (Dec 16)
- `9f44773` SEG3: Singleton BoundaryDetector (Dec 16)
- `6a95004` SEG2: SGML case insensitivity (Dec 16)

---

## Executive Summary

The HTML segmentation system (`src/extraction/html_segmenter.py`) is a well-architected, production-ready component with comprehensive test coverage (~87%, 85+ tests). The recent 8-phase redesign (commit 3adf1c6) added significant capabilities for context preservation and false positive reduction.

After comprehensive evaluation, I've identified **12 potential improvements** categorized by priority and impact. **Phases A and B are now complete**, delivering immediate correctness fixes and significant performance improvements.

**Overall Assessment:** The segmentation logic is solid and production-ready. Phases C and D remain pending and would enhance feature completeness but are not blocking issues.

---

## Current Architecture Summary

### 8-Phase Pipeline

| Phase | Component | Status | Coverage |
|-------|-----------|--------|----------|
| 1 | HTML Parsing & Content Discovery | Complete | High |
| 2 | Sentence Detection with SEC Abbreviations | Complete | High |
| 3 | Definition Merging | Complete | Medium |
| 4 | Composite Segment Splitting (L5) | Complete | High |
| 5 | Large Table Handling | Complete | High |
| 6 | Context Enrichment (overlap + position) | Complete | High |
| 7 | List Item Extraction | Complete | High |
| 8 | Validation & Filtering | Complete | High |

### Key Strengths

1. **Auditability**: Every segment maintains provenance (filing_id, sequence_index, section heading)
2. **SEC-Specific**: Handles SGML format, SEC abbreviations, filing-specific patterns
3. **Robustness**: Graceful degradation with encoding fallback, malformed HTML handling
4. **Comprehensive Testing**: 85+ unit tests, golden file tests, edge case coverage

---

## Improvement Categories

### Priority Levels
- **P0**: Critical - Affects correctness or causes failures
- **P1**: High - Significant performance or accuracy improvement
- **P2**: Medium - Valuable enhancement for specific use cases
- **P3**: Low - Nice-to-have polish

---

## P1: High Priority Improvements

### 1. Heading Cache Binary Search (Performance)

**Current State:** `_build_heading_cache()` creates a cache of headings with positions, but `_get_section_from_cache()` still uses BeautifulSoup's `find_previous()` method.

**Problem:** O(n) lookup per segment leads to O(n²) complexity for entire document with many segments.

**Proposed Solution:**
```python
def _get_section_from_cache(self, element: Tag, element_position: int) -> Tuple[Optional[str], Optional[str]]:
    """Use binary search to find nearest preceding heading."""
    if not self._heading_cache:
        return None, None

    # Binary search for largest position <= element_position
    left, right = 0, len(self._heading_cache) - 1
    result = None

    while left <= right:
        mid = (left + right) // 2
        pos, level, text = self._heading_cache[mid]
        if pos <= element_position:
            result = self._heading_cache[mid]
            left = mid + 1
        else:
            right = mid - 1

    if result:
        pos, level, text = result
        if text.lower() not in self.METADATA_HEADINGS:
            return text, text

    return None, None
```

**Impact:** Reduces section lookup from O(n) to O(log n)
**Effort:** Low (1-2 hours)
**Risk:** Low

---

### 2. SGML Tag Case Insensitivity (Correctness)

**Current State:** Line 379 checks `soup.find("text")` (lowercase only)

**Problem:** Older SEC EDGAR filings may use `<TEXT>` (uppercase). BeautifulSoup is generally case-insensitive for HTML, but SGML tags may be preserved literally.

**Proposed Solution:**
```python
def _find_main_content(self, soup: BeautifulSoup) -> Optional[Tag]:
    # Try to find <TEXT> tag (SGML format) - case insensitive
    text_tag = soup.find("text") or soup.find("TEXT")
    if text_tag:
        return text_tag
    # ... rest unchanged
```

**Impact:** Prevents missed content in older filings
**Effort:** Trivial (15 minutes)
**Risk:** None

---

### 3. Singleton BoundaryDetector Instance (Performance)

**Current State:** Creates new `BoundaryDetector()` instance for each segment in `_apply_sentence_detection()` and `_truncate_at_sentence_boundary()`.

**Problem:** Unnecessary object creation overhead (~200-500 segments per filing).

**Proposed Solution:**
```python
class HTMLSegmenter:
    def __init__(self, ...):
        ...
        self._boundary_detector = BoundaryDetector()

    def _apply_sentence_detection(self, segment: SourceSegment) -> SourceSegment:
        ...
        boundaries = self._boundary_detector.find_sentence_boundaries(...)
```

**Impact:** ~5-10% reduction in memory allocations
**Effort:** Trivial (15 minutes)
**Risk:** None

---

### 4. Expand Definition Continuation Patterns (Accuracy)

**Current State:** `DEFINITION_CONTINUATION_PATTERNS` only matches:
- Lowercase start
- Conjunctions: and, or, but, which, that, who, where, when
- Parenthetical start
- Qualifiers: including, excluding, such as

**Problem:** Misses valid continuations like:
- "Such metrics include..."
- "These calculations are..."
- "The above definition also..."

**Proposed Solution:**
```python
DEFINITION_CONTINUATION_PATTERNS = [
    r"^[a-z]",  # Starts with lowercase (likely mid-sentence)
    r"^(?:and|or|but|which|that|who|where|when)\b",  # Conjunctions
    r"^\s*\(",  # Starts with parenthetical
    r"^(?:including|excluding|such\s+as)\b",  # Qualifiers
    # NEW: Demonstrative pronouns that refer back
    r"^(?:Such|These|Those|This|The\s+above|The\s+following)\b",
]
```

**Impact:** 10-20% more definitions correctly merged
**Effort:** Low (30 minutes + tests)
**Risk:** Low (may over-merge in edge cases - add length checks)

---

## P2: Medium Priority Improvements

### 5. Character Offset Tracking (Feature) ✅ COMPLETE

**Current State:** ~~`char_start_offset` and `char_end_offset` fields exist in `SourceSegment` but are never populated.~~ **IMPLEMENTED** - Offsets now tracked using string matching approach.

**Problem:** Precise source location is useful for:
- Highlighting in UI
- Debugging extraction issues
- Cross-referencing with original document

**Implemented Solution:**
- Store original HTML content before parsing
- Use string matching to find element positions in original HTML
- Compute offsets for paragraphs, tables, and list items
- Handle merged definitions (use earliest start, latest end offset)
- Handle composite splits (child segments inherit parent offsets)
- Graceful degradation (offsets are None if string matching fails)

**Implementation Details:**
- Added `_compute_element_offsets()` helper method (html_segmenter.py:410-462)
- Offsets populated in `_extract_segment()` (html_segmenter.py:511-514)
- Offsets tracked for list items (html_segmenter.py:1213-1216)
- Merged definitions span all merged segments (html_segmenter.py:955-998)
- 12 comprehensive tests added to test_html_segmenter.py

**Impact:** ✅ Enables precise source tracking for UI highlighting and debugging
**Effort:** 2.5 hours (implementation + 12 tests)
**Risk:** Low - graceful failure when string matching doesn't work
**Test Coverage:** 79% for html_segmenter.py (98 tests pass, 3 skipped)

---

### 6. Hierarchical Section Path Building (Feature) ✅ Complete

**Status:** ✅ Complete (SEG6) - Commit: de27f33 (2025-12-17)

**Implementation:**
- Added `_build_hierarchical_path()` method that walks backwards through heading cache
- Modified `_get_section_from_cache()` to build hierarchical paths
- `section_path` now contains full hierarchy (e.g., "Item 1 > Business > Customers")
- `section_heading` remains just the nearest heading (unchanged behavior)
- Level resets handled correctly (new h1 clears previous h2, h3, etc.)
- Path truncation for very long paths (>500 chars)

**Test Coverage:** 17 new tests added for hierarchical paths covering:
- Basic hierarchy (2-level, 3-level, single heading)
- Level resets (h1 clears hierarchy, same-level replaces)
- Edge cases (no heading, all same level, deep nesting)
- Formatting (separators, unicode, truncation)
- Integration tests (full segment_filing, shared path prefix)

**Impact:** Richer navigation context for analysts
**Effort:** Medium (2-3 hours + tests)
**Risk:** Low

---

### 7. Robust Encoding Detection (Robustness) ✅ COMPLETE

**Status:** ✅ Complete (SEG7) - Commit: be96a98 (2025-12-17)

**Implementation:**
- Added `charset-normalizer>=3.3.0` dependency to requirements.txt
- Added conditional import with graceful fallback if library unavailable
- Added `_detect_encoding_auto()` method that:
  - Reads up to 64KB for encoding detection (handles large files efficiently)
  - Uses confidence threshold (80%) to avoid low-confidence detections
  - Returns detected encoding or None if confidence is below threshold
- Updated `_read_html_file_with_encoding()` with 4-step cascade:
  1. charset-normalizer auto-detection (if confidence >= 80%)
  2. UTF-8 explicit attempt
  3. Latin-1 fallback
  4. EncodingError (only if all above fail)
- Added test fixtures in `tests/fixtures/encoding/`:
  - `utf8_sample.html` - UTF-8 with non-ASCII (€, é, ñ)
  - `windows1252_sample.html` - Windows-1252 with curly quotes and em-dashes
  - `latin1_sample.html` - Latin-1 with accented characters
  - `utf8_bom_sample.html` - UTF-8 with BOM
  - `ascii_only_sample.html` - Pure ASCII (control case)
  - `very_short_sample.html` - Short file edge case

**Test Coverage:** 15 new tests added covering:
- Auto-detection: UTF-8, Windows-1252, Latin-1, UTF-8 BOM
- Fallback cascade: ASCII files, fallback when detection fails
- Graceful degradation: mocked unavailable library, empty file, short file
- Edge cases: encoding in metrics, EncodingError structure, mixed content

**Impact:** ✅ Correctly handles Windows-1252, ISO-8859-* variants, and other legacy encodings
**Effort:** 2 hours (implementation + 15 tests + fixtures)
**Risk:** Low (graceful fallback when library unavailable)

---

### 8. Additional Element Types (Feature)

**Current State:** Only extracts `<p>`, `<table>`, `<div>`, `<ul>`, `<ol>`.

**Missing:** `<blockquote>`, `<pre>`, `<figure>`, `<aside>` can contain disclosures.

**Proposed Solution:**
```python
# In segment_filing():
for element in main_content.find_all(
    ["p", "table", "div", "ul", "ol", "blockquote", "pre", "figure"],
    recursive=True
):
    ...

def _get_segment_type(self, element: Tag) -> str:
    if element.name == "blockquote":
        return "blockquote"
    if element.name == "pre":
        return "preformatted"
    if element.name == "figure":
        return "figure"
    # ... existing logic
```

**Impact:** Captures additional disclosure types
**Effort:** Low (1 hour + tests)
**Risk:** Low (may need min_length adjustments)

---

## P3: Low Priority Improvements

### 9. Cache Parsed DOM in Composite Splitting (Performance)

**Current State:** `_split_composite_segment()` creates new BeautifulSoup objects for each segment.

**Problem:** Redundant parsing when segment was already parsed during extraction.

**Proposed Solution:** Pass the parsed element to `_split_composite_segment()` or cache the parsed content in the segment object temporarily.

**Impact:** Minor performance improvement
**Effort:** Medium (2 hours)
**Risk:** Medium (memory trade-off)

---

### 10. HTML Selector Generation (Feature) ✅ COMPLETE

**Status:** ✅ Complete (SEG10) - Pending commit (2025-12-17)

**Implementation:**
- Added `_element_selector()` helper method that generates CSS selector for single element:
  - Elements with ID: returns `#id` (globally unique, terminates path)
  - Elements with class: returns `tag.classname` (first class only)
  - Otherwise: returns `tag:nth-of-type(n)` for uniqueness among siblings
- Added `_escape_css_identifier()` to escape special CSS characters (`:`, `.`, `[`, `]`, etc.)
- Added `_generate_css_selector()` method that builds path from element toward root:
  - Terminates at element with ID (no need to go higher)
  - Limited to 6 levels to avoid overly long selectors
  - Uses direct descendant combinator (` > `)
- Integrated into `_extract_segment()` and `_extract_list_segments()`

**Test Coverage:** 17 new tests added covering:
- ID selectors, class selectors, nth-of-type fallback
- Path building and termination at ID elements
- Depth limiting, special character escaping
- Integration with full segment_filing()
- Selector uniqueness verification

**Impact:** ✅ Enables DOM highlighting in UI
**Effort:** 1.5 hours (implementation + 17 tests)
**Risk:** Low - graceful fallback to None on error

---

### 11. Parallel Sentence Detection (Performance)

**Current State:** Sentence detection runs sequentially for each segment.

**Proposed Solution:**
```python
from concurrent.futures import ThreadPoolExecutor

def segment_filing(self, ...):
    ...
    # Apply sentence detection in parallel
    with ThreadPoolExecutor(max_workers=4) as executor:
        segments = list(executor.map(self._apply_sentence_detection, segments))
```

**Impact:** 2-4x faster for large filings
**Effort:** Low (30 minutes)
**Risk:** Medium (thread safety verification needed)

---

### 12. Table Summary Intelligence (Enhancement)

**Current State:** Large table summary includes headers + row count + first 3000 chars.

**Problem:** May miss important data patterns in the middle/end of large tables.

**Proposed Solution:**
Sample rows from beginning, middle, and end:
```python
def _create_table_summary(self, raw_html, raw_text) -> str:
    ...
    # Sample first 1000, middle 1000, last 1000 chars
    if len(raw_text) > 3000:
        first = raw_text[:1000]
        mid_start = len(raw_text) // 2 - 500
        middle = raw_text[mid_start:mid_start + 1000]
        last = raw_text[-1000:]
        truncated_text = f"{first}...[middle sample]...{middle}...[end sample]...{last}"
```

**Impact:** Better coverage of large table content
**Effort:** Low (1 hour)
**Risk:** Low

---

## Implementation Roadmap

### Phase A: Quick Wins (Same Day)
| # | Item | Time | Impact | Status |
|---|------|------|--------|--------|
| 2 | SGML case insensitivity | 15 min | Correctness | ✅ Complete |
| 3 | Singleton BoundaryDetector | 15 min | Performance | ✅ Complete |
| 4 | Expand continuation patterns | 30 min | Accuracy | ✅ Complete |

**Total:** ~1 hour, immediate benefits

### Phase B: Performance (1-2 Days)
| # | Item | Time | Impact | Status |
|---|------|------|--------|--------|
| 1 | Heading cache binary search | 2 hr | O(n²) → O(n log n) | ✅ Complete |
| 11 | Parallel sentence detection | 1 hr | 2-4x faster | ✅ Complete |

**Total:** ~3 hours, significant for large filings

### Phase C: Features (1 Week) ✅ **Complete**
| # | Item | Time | Impact | Status |
|---|------|------|--------|--------|
| 5 | Character offset tracking | 2.5 hr | Source tracking | ✅ Complete |
| 6 | Hierarchical section paths | 3 hr | Navigation | ✅ Complete |
| 8 | Additional element types | 1 hr | Coverage | ✅ Complete |
| 10 | HTML selector generation | 1.5 hr | UI highlighting | ✅ Complete |

**Total:** ~8 hours, improved feature set

### Phase D: Polish (As Needed)
| # | Item | Time | Impact | Status |
|---|------|------|--------|--------|
| 7 | Robust encoding detection | 2 hr | Edge cases | ✅ Complete |
| 9 | DOM caching | 2 hr | Minor perf | 🟡 Pending |
| 12 | Table summary sampling | 1 hr | Large tables | 🟡 Pending |

**Total:** ~5 hours, edge case handling (1 complete, 2 pending)

---

## Testing Requirements

### For Each Improvement

1. **Unit Tests:** Test the specific function in isolation
2. **Integration Tests:** Test full `segment_filing()` with representative HTML
3. **Golden File Tests:** Verify no regressions in existing test filings
4. **Performance Benchmarks:** For performance changes, measure before/after

### Regression Checklist

```bash
# Run full test suite
pytest tests/unit/extraction/test_html_segmenter.py -v

# Run golden file tests
pytest tests/unit/extraction/test_html_segmenter_golden.py -v

# Check coverage maintained
pytest tests/unit/extraction/test_html_segmenter.py --cov=src/extraction/html_segmenter --cov-fail-under=85
```

---

## Decision Points

### Before Implementation, Decide:

1. **Phase A Quick Wins:** Proceed immediately? (Recommended: Yes)

2. **Binary Search vs find_previous():** Worth the complexity for O(log n) improvement? (Recommended: Yes for large filings)

3. **Encoding Detection Library:** Add `charset-normalizer` dependency? (Recommended: Only if encoding issues observed)

4. **Parallel Processing:** Thread pool for sentence detection? (Recommended: Only if performance is a concern)

5. **Additional Element Types:** Include `<blockquote>`, `<pre>`, `<figure>`? (Recommended: Yes, low risk)

---

## Conclusion

The HTML segmentation system is production-ready with solid architecture and comprehensive testing. The improvements identified are optimizations and feature enhancements rather than critical fixes.

**Recommended Next Steps:**
1. Implement Phase A quick wins immediately (1 hour)
2. Evaluate need for Phase B performance improvements based on filing volumes
3. Prioritize Phase C features based on downstream needs
4. Address Phase D as edge cases arise

---

## Appendix: File References

| File | Lines | Purpose |
|------|-------|---------|
| `src/extraction/html_segmenter.py` | 1274 | Main implementation |
| `src/extraction/models.py` | 288 | SourceSegment model |
| `src/review/boundary_detection.py` | 572 | Sentence detection |
| `tests/unit/extraction/test_html_segmenter.py` | 1779 | Unit tests |
| `docs/architecture/extraction-pipeline.md` | 669 | Pipeline documentation |
