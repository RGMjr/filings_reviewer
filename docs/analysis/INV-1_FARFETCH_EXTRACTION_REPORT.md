# INV-1: Farfetch Extraction Failure Investigation Report

**Date**: 2026-01-06
**Status**: Complete
**Author**: Claude Code

## Executive Summary

The Farfetch filing (filing_id=31) does not hang indefinitely as initially observed. Instead, it completes extraction in approximately 105 seconds (vs 5.5s for Slack), producing 2,537 segments. The apparent "hang" was caused by slow processing that exceeds typical user patience and script timeouts. The root cause is a combination of high element count (7,760 elements) and BeautifulSoup HTML normalization causing 100% element offset lookup failures.

## Problem Statement

- **Filing**: Farfetch Ltd (filing_id=31), F-1 filing from August 2018
- **File**: `data/filings/0001740915/000119312518252315/primary.htm` (2.6MB)
- **Symptoms**:
  - Script appears to hang when running `rerun_single_filing.py --filing-id 31`
  - 26+ HRV-22 warnings about text/HTML mismatches
  - No segments saved to database (0 segments, 0 metrics)
- **Impact**: Farfetch cannot be used for human review quality assessment

## Investigation Findings

### Reproduction Results

| Filing | File Size | Tables | Elements | Segmentation Time | Segments Created |
|--------|-----------|--------|----------|-------------------|------------------|
| Slack | 3.6MB | 500 | ~8,500 | 5.5s | 2,243 |
| Farfetch | 2.6MB | 665 | 7,760 | ~105s | 2,537 |

**Key observation**: Farfetch is smaller but takes 19x longer to process.

### Root Cause Analysis

The slowdown is caused by three interrelated issues:

#### Issue 1: BeautifulSoup HTML Normalization (Primary Cause)

BeautifulSoup normalizes HTML during parsing (e.g., lowercasing tag names, reordering attributes). The `_compute_element_offsets()` method at `html_segmenter.py:659-711` uses string matching to find elements in the original HTML:

```python
# Line 691: String search for element in original HTML
pos = self._original_html.find(element_html, search_start)
```

When elements cannot be found (because `str(element)` differs from original HTML):
- The search scans the entire 2.75MB HTML for EVERY element
- The `search_start` optimization never advances (stays at 0)
- For 7,760 elements, this creates ~21 billion character comparisons

**Evidence**: 100% of Farfetch elements fail to find their offset in the original HTML (all produce "Could not find element" debug messages).

#### Issue 2: High Element Count

Farfetch has 7,760 elements to process:
- 7,051 `<p>` elements (paragraphs)
- 665 `<table>` elements
- 44 `<div>` elements

The processing time is approximately O(n * m) where n = element count and m = HTML size.

#### Issue 3: Non-linear Performance Degradation

Processing time per element varies dramatically:
- First 1,000 elements: 18.9ms/element
- Elements 1,000-2,000: 34.5ms/element
- Elements 6,000-7,000: 2.4ms/element

The early elements are slowest, likely due to cache warming and the string search always starting from position 0.

### Code Path Trace

```
rerun_single_filing.py:main()
  └── ExtractionPipeline.process_filing(filing_id=31)
        └── HTMLSegmenter.segment_filing()
              ├── BeautifulSoup(html, "html.parser")  # 0.96s
              ├── find_all(['p','table','div',...])   # 0.06s
              ├── for element in elements:            # 7,760 iterations
              │     └── _extract_segment()
              │           ├── str(element)            # 0.1ms
              │           ├── _get_segment_type()     # 0.0ms
              │           ├── BeautifulSoup(raw_html) # 0.1ms (for non-tables)
              │           ├── _extract_section_info() # 0.0ms
              │           ├── _compute_element_offsets() # VARIES: 0.2-35ms
              │           │     └── html.find(elem_html) # Scans 2.75MB if not found
              │           └── _generate_css_selector()   # 0.0ms
              ├── _split_composite_segment()          # Per segment
              ├── _merge_definition_segments()        # O(n)
              ├── _apply_sentence_detection()         # Parallel if >100 segments
              └── _handle_large_table()               # Per table segment
```

## Alternative Approaches

### Approach A: Disable Offset Computation for Large Filings

**Description**: Skip `_compute_element_offsets()` when filing HTML exceeds a threshold (e.g., 1MB) or when element count exceeds 5,000.

**Files Modified**:
- `src/extraction/html_segmenter.py` (lines 771-773)

**Implementation Complexity**: Low

**Advantages**:
- Simple to implement (add conditional check)
- No architectural changes required
- Immediate performance improvement
- Offset data is optional (used for UI highlighting, can be None)

**Disadvantages**:
- Loss of offset data for large filings
- May affect downstream features that rely on char_start/char_end

**Unintended Consequences**:
- UI source highlighting will not work for large filings
- Other large filings (if any) will also skip offset computation
- No regression for normal-sized filings

### Approach B: Use lxml Parser with Source Position Tracking

**Description**: Switch to lxml parser which provides `sourceline` and `sourcepos` attributes, eliminating the need for string matching.

**Files Modified**:
- `src/extraction/html_segmenter.py` (lines 230, 659-711)
- Potentially `requirements.txt` if lxml not already installed

**Implementation Complexity**: Medium

**Advantages**:
- Native source position tracking (no string matching needed)
- Potentially faster parsing for all filings
- More accurate offset computation

**Disadvantages**:
- lxml handles some edge cases differently than html.parser
- May require regression testing across all filings
- lxml is a native dependency (compilation issues possible)

**Unintended Consequences**:
- Some filings may parse differently with lxml
- Edge cases with malformed HTML may behave differently
- Need to verify lxml is available in production environment

### Approach C: Lazy Offset Computation with Caching

**Description**: Compute offsets only when requested (lazy evaluation), and cache results using a pre-built index of element signatures.

**Files Modified**:
- `src/extraction/html_segmenter.py` (new method for index building, modify _compute_element_offsets)
- `src/extraction/models.py` (make offset properties lazy)

**Implementation Complexity**: High

**Advantages**:
- Offsets computed only when needed
- Pre-built index enables O(1) lookups
- Works with any parser

**Disadvantages**:
- Significant refactoring required
- Increases memory usage for index
- Complex cache invalidation logic

**Unintended Consequences**:
- Memory pressure for very large filings
- Potential for stale cache issues
- Changes segment API contract

## Comparison Matrix

| Criterion | Approach A: Skip Offsets | Approach B: lxml Parser | Approach C: Lazy + Cache |
|-----------|-------------------------|------------------------|-------------------------|
| Implementation Complexity | Low | Medium | High |
| Risk Level | Low | Medium | Medium |
| Backward Compatibility | High | Medium | Medium |
| Performance Impact | Significant improvement | Good improvement | Best theoretical |
| Test Effort | Low | Medium | High |
| Maintenance Burden | None | Low | Medium |

## Recommendation

**Recommended Approach**: **Approach A: Disable Offset Computation for Large Filings**

**Rationale**:
1. **Immediate relief**: Addresses the critical blocker with minimal code changes
2. **Low risk**: Offset data is optional; skipping it doesn't break extraction
3. **Targeted fix**: Only affects large filings that trigger the performance issue
4. **Reversible**: Easy to adjust threshold or remove if Approach B is later implemented
5. **Production-safe**: No external dependencies or parser changes

**Implementation Details**:
- Add a threshold check in `_extract_segment()` before calling `_compute_element_offsets()`
- Threshold: Skip if HTML > 1MB or element count > 5,000
- Log a warning when offsets are skipped for visibility

**Validation Plan**:
1. Implement the fix and run segmentation on Farfetch
2. Verify completion time < 30 seconds
3. Verify segments are created and saved to database
4. Run gold standard validation to ensure no regression
5. Test on Slack and Samsara Vision to confirm no impact

**Estimated Implementation Effort**: 1-2 hours

## Appendix

### Filing Comparison Data

```
Farfetch Ltd (filing_id=31):
  - File: data/filings/0001740915/000119312518252315/primary.htm
  - Size: 2.6MB (2,755,094 chars)
  - Form: F-1
  - Tables: 665
  - Paragraphs: 7,051
  - Divs: 44
  - Total elements: 7,760
  - Segmentation time: ~105s
  - Segments created: 2,537
  - Offset lookup success rate: 0%

Slack Technologies, Inc. (filing_id=35):
  - File: data/filings/0001764925/000162828019004786/primary.htm
  - Size: 3.6MB
  - Form: S-1
  - Tables: 500
  - Divs: 13,930
  - Segmentation time: 5.5s
  - Segments created: 2,243
```

### Diagnostic Commands Used

```bash
# Check file sizes
ls -lh data/filings/0001740915/000119312518252315/primary.htm
ls -lh data/filings/0001764925/000162828019004786/primary.htm

# Count tables
grep -oi '<table' data/filings/0001740915/000119312518252315/primary.htm | wc -l

# Check segment counts in database
PGPASSWORD=dev psql -h localhost -p 5433 -U dev -d filings_analysis -c "
SELECT f.filing_id, c.company_name,
       (SELECT COUNT(*) FROM source_segments ss WHERE ss.filing_id = f.filing_id) as segments
FROM filings f JOIN companies c ON f.company_id = c.company_id
WHERE c.company_name IN ('Farfetch Ltd', 'Slack Technologies, Inc.');"

# Test segmenter in isolation
python3 -c "
from src.extraction.html_segmenter import HTMLSegmenter
import time
segmenter = HTMLSegmenter()
start = time.time()
segments = segmenter.segment_filing(31, 'data/filings/0001740915/000119312518252315/primary.htm')
print(f'{len(segments)} segments in {time.time()-start:.1f}s')
"
```

### Raw Output Samples

**Element offset lookup failure pattern** (thousands of these):
```
src.extraction.html_segmenter - Could not find element in original HTML (may have been modified): <p align="center" style="margin-top:0pt; margin-bottom:0pt; font-size:7pt; font-family:ARIAL">...
```

**HRV-22 warning** (26 occurrences for Farfetch):
```
src.extraction.html_segmenter - HRV-22: Text/HTML mismatch detected: raw_text=1361 chars, extractable from raw_html=1257 chars, segment_type=table
```

---

**Last Updated**: 2026-01-06
**Task ID**: INV-1
