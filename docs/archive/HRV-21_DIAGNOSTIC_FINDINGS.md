# HRV-21 Diagnostic Investigation Findings

## Executive Summary

**The data corruption is REAL.** Investigation confirms that 13 Farfetch table segments contain text in `raw_text` that does not exist in `raw_html`. The root cause is a bug in the HTMLSegmenter extraction pipeline where text is extracted from the full HTML element, but HTML is truncated afterward without ensuring consistency.

**Recommendation for HRV-20**: **PROCEED WITH MODIFICATIONS** - Re-extraction will fix the corrupted data, but the underlying bug in HTMLSegmenter must also be fixed to prevent recurrence.

## Investigation Results

### 0. Intended Behavior Analysis (CRITICAL)

**How raw_html is populated** (`html_segmenter.py` lines 759-762):
```python
html_max = self.TABLE_MAX_LENGTH if segment_type == "table" else self.max_length
raw_html = str(element)[:html_max]
```
- For tables: truncate HTML to 25,000 chars (TABLE_MAX_LENGTH)
- For text: truncate to 10,000 chars (max_length)

**How raw_text is populated** (`html_segmenter.py` lines 731-739):
```python
if segment_type == "table" or element.name == "table":
    raw_text = self._extract_table_text_with_markers(element)
else:
    raw_text = self._normalize_text(element.get_text())
```
- Extracts from the FULL element (no truncation applied)

**Intended relationship**: `raw_text` should contain ONLY text that exists within `raw_html`. If `raw_html` is truncated, `raw_text` should be limited to content from the truncated portion.

**The Bug**: Text extraction happens BEFORE HTML truncation, with no consistency check afterward. This allows `raw_text` to contain content from beyond the truncation point.

### 1. Mismatch Count Verification

**Claimed** (HRV-17): 48/80 segments (60%) have mismatch
**Actual**: 13/80 segments (16%) have the specific raw_text > truncated html_text issue

**Methodology**: Compared stored `raw_text` against text extracted from stored `raw_html` using BeautifulSoup. Counted segments where `raw_text` extends beyond what's extractable from `raw_html`.

**Note**: HRV-17's count may have used different comparison methodology. The critical finding (data corruption exists) is confirmed regardless of exact count.

### 2. Segment Analysis

**Segment Analyzed**: 25861 (table)

| Metric | Value |
|--------|-------|
| raw_html length | 10,000 chars (truncated) |
| Text extractable from raw_html | 528 chars |
| Stored raw_text length | 716 chars |
| Extra content | 188 chars |

**Extra Content**:
```
 Farfetch Marketplace: Active Consumers 796.3 1,118.0 415.7 651.7 935.8
 Number of Orders 853.2 1,305.3 800.5 1,259.7 1,881.0
 Average Order Value (actual) $591.7 $622.1 $586.8 $583.6 $620.0
```

**Key Findings**:
- "Active Consumers" IS in `raw_text` (position 551)
- "Active Consumers" is NOT in `raw_html` (not found)
- The stored `raw_text` perfectly starts with text extractable from `raw_html`, then continues with extra content
- This confirms the text was extracted from a FULL element, while HTML was truncated

### 3. Original Source Examination

**Filing**: Farfetch S-1 (Accession: 000119312518252315)
**Local Path**: `data/filings/0001740915/000119312518252315/primary.htm`

**Original Table Analysis** (Table 238 in filing):
| Metric | Value |
|--------|-------|
| Full table HTML | 13,666 chars |
| Full table text | 716 chars |
| After truncating HTML to 10,000 | Text becomes 528 chars |
| Delta | 188 chars (exact match!) |

**Conclusion**: The original table is 13,666 chars, which exceeds the 10,000 char limit. When truncated to 10,000 chars, the "Farfetch Marketplace: Active Consumers" rows are cut off. But the stored `raw_text` contains the full 716 chars from the untruncated table.

### 4. Extraction History

**TABLE_MAX_LENGTH (25,000) introduced**: December 16, 2025 (commit 3adf1c6)
**Segment created**: December 27, 2025 17:02 UTC

**Anomaly**: The segment was created AFTER TABLE_MAX_LENGTH was introduced, so it should have used the 25,000 char limit. But `raw_html` is exactly 10,000 chars.

**Possible explanations**:
1. The extraction used cached/older data
2. The segment went through a code path that uses `self.max_length` (10,000) instead of `TABLE_MAX_LENGTH`
3. The segmenter was instantiated with a custom max_length

**Code paths that use self.max_length instead of TABLE_MAX_LENGTH**:
- `_split_composite_segment()` (lines 908-920)
- `_merge_definition_segments()` (line 1387)
- `_extract_list_segments()` (line 1690)

### 5. Pattern Analysis

**Affected Farfetch Segments** (13 total):
- 25861, 25864, 25867, 25870, 25873, 25876, 25879, 25882, 25885, 25888, 25891, 25894, 25897

**All share identical characteristics**:
- raw_html = 10,000 chars (truncated)
- raw_text = 716 chars
- Extra content = 188 chars
- Extra content pattern = "Farfetch Marketplace: Active Consumers..."

**Slack Segments**: 0 mismatches found (tables likely smaller than 10,000 chars)

**Conclusion**: Issue is specific to tables exceeding the truncation limit. Farfetch has a large table (13,666 chars) that triggers the bug; Slack does not.

## Root Cause Determination

**Finding**: **A. Data Corruption (Bug in Extraction Pipeline)**

The corruption is caused by a race between text extraction and HTML truncation:

```
1. element = BeautifulSoup parsed table (13,666 chars of HTML)
2. raw_text = extract_text(element)  # Gets all 716 chars
3. raw_html = str(element)[:10000]   # Truncates to 10,000 chars
4. Database.insert(raw_text, raw_html)  # Mismatch stored!
```

**Evidence**:
- Original table HTML is 13,666 chars
- `raw_text` contains 716 chars (full extraction)
- `raw_html` is truncated to 10,000 chars
- Text from chars 529-716 in `raw_text` doesn't exist in `raw_html`

**Why this causes TableRowParser failures**:
1. `TableRowParser.__init__(raw_html, raw_text)` receives mismatched data
2. Parser builds row mappings from `raw_html` (only covers positions 0-528)
3. Keywords/numbers in positions 529-716 can't be mapped to any row
4. `are_in_same_row()` returns `False` for unmapped positions
5. Valid candidates are incorrectly filtered out

## Recommendation for HRV-20

**Recommendation**: **PROCEED WITH MODIFICATIONS**

### Rationale

1. **The data is genuinely corrupt** - not expected behavior or stale data
2. **Re-extraction will fix the immediate issue** - segments will get consistent raw_text/raw_html
3. **But the underlying bug must also be fixed** - otherwise re-extraction will recreate the problem

### Required Modifications to HRV-20

1. **Add root cause fix** before re-extraction:
   - Modify `_extract_segment()` to ensure `raw_text` only contains content from `raw_html`
   - Either: Extract text AFTER truncation (from truncated HTML)
   - Or: Truncate text to match the truncation point

2. **Verify TABLE_MAX_LENGTH is being applied**:
   - Check why segments created after Dec 16 have raw_html=10,000 instead of 25,000
   - Review code paths that might bypass TABLE_MAX_LENGTH

3. **Add data validation**:
   - After extraction, verify text is subset of HTML content
   - Log warning if mismatch detected

4. **Scope of re-extraction**:
   - Can be limited to segments where `len(raw_html) == 10000` and segment_type='table'
   - Approximately 13 Farfetch segments need re-extraction

### Suggested Fix for HTMLSegmenter

```python
def _extract_segment(self, element, filing_id, sequence_index):
    # ... existing code ...

    # Determine limits
    effective_max = self.TABLE_MAX_LENGTH if segment_type == "table" else self.max_length
    html_max = self.TABLE_MAX_LENGTH if segment_type == "table" else self.max_length

    # Truncate HTML first
    raw_html = str(element)[:html_max]

    # Extract text from TRUNCATED HTML (not original element)
    if len(str(element)) > html_max:
        truncated_soup = BeautifulSoup(raw_html, 'html.parser')
        if segment_type == "table":
            raw_text = self._extract_table_text_with_markers(truncated_soup)
        else:
            raw_text = self._normalize_text(truncated_soup.get_text())
    else:
        # Original element not truncated, safe to extract directly
        raw_text = self._extract_table_text_with_markers(element) if segment_type == "table" else ...

    # ... rest of method ...
```

---

**Investigation Completed**: 2026-01-03
**Task**: HRV-21
**Status**: COMPLETE
