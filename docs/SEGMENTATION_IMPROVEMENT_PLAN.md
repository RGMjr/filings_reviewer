# HTML Segmentation Improvement Plan

**Version:** 1.0
**Created:** 2025-12-16
**Status:** Draft for Review

---

## Executive Summary

The HTML segmentation system (`src/extraction/html_segmenter.py`) is a well-architected, production-ready component with comprehensive test coverage (~87%, 85+ tests). The recent 8-phase redesign (commit 3adf1c6) added significant capabilities for context preservation and false positive reduction.

After comprehensive evaluation, I've identified **12 potential improvements** categorized by priority and impact. Many are optimizations rather than critical fixes, reflecting the system's mature state.

**Overall Assessment:** The segmentation logic is solid and production-ready. The improvements below would enhance performance, robustness, and feature completeness but are not blocking issues.

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

### 5. Character Offset Tracking (Feature)

**Current State:** `char_start_offset` and `char_end_offset` fields exist in `SourceSegment` but are never populated.

**Problem:** Precise source location is useful for:
- Highlighting in UI
- Debugging extraction issues
- Cross-referencing with original document

**Proposed Solution:**
Track cumulative character position during extraction:
```python
def segment_filing(self, ...):
    ...
    cumulative_offset = 0
    for element in main_content.find_all(...):
        segment = self._extract_segment(element, filing_id, sequence_index)
        if segment:
            segment.char_start_offset = cumulative_offset
            segment.char_end_offset = cumulative_offset + len(segment.raw_text)
            cumulative_offset = segment.char_end_offset
            raw_segments.append(segment)
```

**Impact:** Enables precise source tracking
**Effort:** Medium (2-3 hours + tests)
**Risk:** Low

---

### 6. Hierarchical Section Path Building (Feature)

**Current State:** `section_path` is set to the same value as `section_heading` (nearest heading only).

**Expected:** "Item 1. Business > Customers > Growth Metrics"

**Proposed Solution:**
```python
def _build_hierarchical_section_path(self, element: Tag) -> str:
    """Build full path from h1 -> h2 -> h3 etc."""
    path_parts = []
    current = element

    for level in ['h1', 'h2', 'h3', 'h4', 'h5', 'h6']:
        heading = current.find_previous(level)
        if heading:
            text = self._normalize_text(heading.get_text())
            if text and text.lower() not in self.METADATA_HEADINGS:
                path_parts.insert(0, text)

    return " > ".join(path_parts) if path_parts else None
```

**Impact:** Richer navigation context for analysts
**Effort:** Medium (2-3 hours + tests)
**Risk:** Low

---

### 7. Robust Encoding Detection (Robustness)

**Current State:** Tries UTF-8, then Latin-1 fallback.

**Problem:** Some filings use Windows-1252 or other encodings that Latin-1 won't correctly decode.

**Proposed Solution:**
Add `charset-normalizer` or `chardet` library:
```python
from charset_normalizer import from_path

def _read_html_file_with_encoding(self, html_path: str) -> Tuple[Optional[str], str]:
    path = Path(html_path)

    # Try auto-detection first
    result = from_path(path)
    if result.best():
        encoding = result.best().encoding
        content = path.read_text(encoding=encoding)
        return content, encoding

    # Fallback to existing logic
    ...
```

**Impact:** Handles edge case encodings correctly
**Effort:** Medium (1-2 hours + dependency)
**Risk:** Low (new dependency)

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

### 10. HTML Selector Generation (Feature)

**Current State:** `html_selector` field exists but is never populated.

**Proposed Solution:**
```python
def _generate_css_selector(self, element: Tag) -> str:
    """Generate a CSS selector path to this element."""
    parts = []
    current = element
    while current and hasattr(current, 'name') and current.name:
        selector = current.name
        if current.get('id'):
            selector += f"#{current['id']}"
        elif current.get('class'):
            selector += f".{current['class'][0]}"
        parts.insert(0, selector)
        current = current.parent
    return " > ".join(parts[-5:])  # Last 5 levels
```

**Impact:** Enables DOM highlighting in UI
**Effort:** Medium (1-2 hours)
**Risk:** Low

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
| 4 | Expand continuation patterns | 30 min | Accuracy | |

**Total:** ~1 hour, immediate benefits

### Phase B: Performance (1-2 Days)
| # | Item | Time | Impact |
|---|------|------|--------|
| 1 | Heading cache binary search | 2 hr | O(n²) → O(n log n) |
| 11 | Parallel sentence detection | 1 hr | 2-4x faster |

**Total:** ~3 hours, significant for large filings

### Phase C: Features (1 Week)
| # | Item | Time | Impact |
|---|------|------|--------|
| 5 | Character offset tracking | 3 hr | Source tracking |
| 6 | Hierarchical section paths | 3 hr | Navigation |
| 8 | Additional element types | 1 hr | Coverage |
| 10 | HTML selector generation | 2 hr | UI highlighting |

**Total:** ~9 hours, improved feature set

### Phase D: Polish (As Needed)
| # | Item | Time | Impact |
|---|------|------|--------|
| 7 | Robust encoding detection | 2 hr | Edge cases |
| 9 | DOM caching | 2 hr | Minor perf |
| 12 | Table summary sampling | 1 hr | Large tables |

**Total:** ~5 hours, edge case handling

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
