# WORKER PROMPT: Task HRV-21 - Diagnostic Investigation of Farfetch Segment Data

```
===============================================================================
TASK ID:       HRV-21
TASK NAME:     Diagnostic investigation of Farfetch segment HTML/text mismatch
WORKSTREAM:    Human Review Validation
SOURCE:        Critical evaluation of HRV-20 (verify assumptions before remediation)
STATUS:        PENDING
COMPLETION:    N/A
TIME ESTIMATE: 2-3 hours (read-only investigation, 6 investigations)
TIME ACTUAL:   N/A
RISK LEVEL:    NONE - Read-only diagnostic investigation, no data modification
TASK SIZE:     M
DEPENDS ON:    None (standalone investigation)
UNLOCKS:       HRV-20 (remediation can proceed after diagnosis confirms root cause)
BLOCKS:        HRV-20
PARALLEL WITH: None
===============================================================================
```

## Objective

Perform a rigorous diagnostic investigation to verify or refute the claims from HRV-17 about Farfetch segment data corruption, and identify the true root cause before any remediation is attempted.

**Business Rationale**: HRV-20 proposes invasive remediation (re-extraction, data repair) based on HRV-17's findings. Before modifying production data, we must:
1. Understand the INTENDED relationship between `raw_html` and `raw_text`
2. Verify if the observed behavior is actually a bug or expected behavior
3. Confirm the root cause with evidence
4. Ensure the proposed remediation will actually fix the problem

**Current Claims (to verify)**:
- 48/80 Farfetch segments (60%) have `raw_text` with more content than `raw_html`
- The extra content is 188 characters containing "Farfetch Marketplace: Active Consumers"
- `TableRowParser.are_in_same_row()` returns False for positions 529-716
- This causes valid candidates to be filtered out

**Critical Question**: Is the data actually corrupt, or is `raw_text` intentionally enriched with context beyond `raw_html`?

**Desired Outcome**:
- Clear understanding of intended behavior
- Root cause identified with evidence
- Recommendation for HRV-20: proceed as-is / modify approach / abandon
- Clear documentation of findings for future reference

## Prerequisites

- Database access to query `source_segments` table
- Access to SEC EDGAR for original filing comparison

## Files to Read (Context Only)

- `src/extraction/html_segmenter.py` - **CRITICAL**: Understand how `raw_html` and `raw_text` are generated
- `src/review/table_structure.py` - `TableRowParser` class (row detection logic)
- `sql/02_create_extraction_schema.sql` - `source_segments` table schema

## Files to Modify

**None** - This is a read-only diagnostic task.

## Implementation Requirements

### Investigation 0: Understand Intended Behavior (MUST DO FIRST)

**This investigation must be completed before any other investigation.** Without understanding intended behavior, we cannot diagnose "corruption."

1. **Read `html_segmenter.py`** and document:
   - How is `raw_html` populated? (What HTML element does it capture?)
   - How is `raw_text` populated? (What method extracts text?)
   - Are they derived from the same source element?
   - Is there any intentional content enrichment (e.g., including parent/sibling text)?

2. **Identify the text extraction method**:
   - Find the exact code that generates `raw_text` from HTML
   - Document the method signature and any transformations applied
   - Note: Do NOT assume it's `BeautifulSoup.get_text()` - verify this

3. **Document the intended relationship**:
   - Should `raw_text` be an exact extraction from `raw_html`?
   - Or is `raw_text` intentionally different (e.g., includes context)?
   - What does the code documentation say?

4. **Determine the "correct" comparison method**:
   - Based on how `raw_text` is generated, what is the appropriate way to compare it to `raw_html`?
   - This will inform Investigation 2's methodology

**Output**: Clear statement of intended behavior, with code references.

### Investigation 1: Verify Mismatch Count Claim

**Note**: Use the extraction method identified in Investigation 0, NOT generic BeautifulSoup.

1. **Query actual data** to count segments where extracted text from `raw_html` differs from `raw_text`
   - Use the SAME extraction method that HTMLSegmenter uses
   - Do NOT use `LENGTH(raw_text) > LENGTH(raw_html)` (this compares apples to oranges)

2. **Categorize mismatches**:
   - How many segments have `raw_text` longer than extracted HTML text?
   - How many have `raw_text` shorter?
   - How many match exactly (or within whitespace tolerance)?
   - What is the distribution of character deltas?

3. **Document findings** with exact counts and percentages

### Investigation 2: Analyze Specific Segment (25861 or alternative)

1. **Fetch the segment** and examine:
   - `raw_html` content (full HTML)
   - `raw_text` content (stored text)
   - `segment_type` (table, paragraph, etc.)
   - `created_at` and `updated_at` timestamps
   - `has_row_marker` and `has_cell_marker` flags

2. **Extract text from raw_html** using:
   - The SAME method HTMLSegmenter uses (identified in Investigation 0)
   - NOT generic BeautifulSoup unless that's what the code uses

3. **Character-by-character comparison**:
   - Where does `raw_text` diverge from extracted HTML text?
   - What is the exact content that differs?
   - Is the difference consistent with Investigation 0 findings?

4. **Interpret the difference**:
   - Is this a bug (data corruption)?
   - Or expected behavior (intentional enrichment)?
   - Or a code change since extraction (stale data)?

### Investigation 3: Trace Original Source

1. **Fetch original Farfetch S-1 filing** from SEC EDGAR
   - Use `SECClient` or direct fetch
   - Find the table containing the metrics in question

2. **Locate the "different" content** in the original filing:
   - Is the content that's in `raw_text` but not in `raw_html` located in:
     - The same HTML element?
     - A parent element?
     - A sibling element?
     - A completely separate section?

3. **Determine if segmentation was correct**:
   - Did `HTMLSegmenter` correctly identify element boundaries?
   - Was content split across multiple segments?
   - Is this expected behavior or a bug?

### Investigation 4: Check Extraction History

1. **Query segment creation date** for the analyzed segment(s)
2. **Check git history** for `html_segmenter.py` changes around that date
3. **Determine if extraction logic has changed** since segment was created
4. **If changed**: Does current code produce different output than what's stored?

### Investigation 5: Pattern Analysis

1. **Sample 5-10 other "mismatched" segments** (not just one)
2. **Check if pattern is consistent**:
   - Same type of difference?
   - Same segment types affected?
   - Same content pattern?

3. **Check non-Farfetch filings** (e.g., Slack):
   - Do they have similar differences?
   - Is this Farfetch-specific or systemic?

4. **Correlate with Investigation 0**:
   - Do the patterns match the intended behavior?
   - Or do they indicate a bug?

### Error Handling

- If database connection fails: document and stop
- If SEC EDGAR fetch fails: document and continue with available data
- If segment 25861 doesn't exist: find alternative Farfetch segment to analyze
- If Investigation 0 is inconclusive: document uncertainty and proceed with caution

## Acceptance Criteria

- [ ] **Investigation 0 complete**: Intended behavior documented with code references
- [ ] **Extraction method identified**: Know exactly how `raw_text` is generated
- [ ] Mismatch count verified with correct methodology
- [ ] Specific segment analyzed with appropriate comparison method
- [ ] Original SEC filing examined to understand source structure
- [ ] Extraction history checked for relevant code changes
- [ ] Pattern analysis across multiple segments completed
- [ ] Root cause documented with supporting evidence
- [ ] Clear determination: bug vs expected behavior vs stale data
- [ ] Recommendation for HRV-20 provided (proceed/modify/abandon)
- [ ] Findings documented in a structured report

## Do NOT

- Modify any database records
- Modify any source code
- Run re-extraction or data repair
- Assume BeautifulSoup.get_text() is the extraction method without verifying
- Skip Investigation 0 (understanding intended behavior)
- Conclude "corruption" without ruling out expected behavior
- Make assumptions without verifying with evidence

## Verification Commands

```bash
# Investigation 0: Find text extraction method in HTMLSegmenter
# Read the file first, then search for text extraction patterns
grep -n "raw_text" src/extraction/html_segmenter.py
grep -n "get_text" src/extraction/html_segmenter.py
grep -n "text_content" src/extraction/html_segmenter.py

# Investigation 1: Query mismatch data (UPDATE extraction method based on Investigation 0)
DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis" python3 << 'EOF'
import psycopg
import os
from bs4 import BeautifulSoup

# NOTE: Update this extraction method based on Investigation 0 findings
def extract_text_like_segmenter(html):
    """
    TODO: Replace this with the actual method HTMLSegmenter uses.
    This is a placeholder - Investigation 0 must identify the real method.
    """
    soup = BeautifulSoup(html, 'html.parser')
    return soup.get_text(separator=' ', strip=True)

conn = psycopg.connect(os.environ['DATABASE_URL'])
cur = conn.cursor()

# Get all Farfetch segments
cur.execute("""
    SELECT ss.source_segment_id, ss.raw_html, ss.raw_text, ss.segment_type,
           ss.created_at, ss.has_row_marker, ss.has_cell_marker
    FROM source_segments ss
    JOIN filings f ON ss.filing_id = f.filing_id
    JOIN companies c ON f.company_id = c.company_id
    WHERE c.company_name ILIKE '%farfetch%'
    ORDER BY ss.source_segment_id
""")

results = cur.fetchall()
print(f"Total Farfetch segments: {len(results)}")

# Analyze each segment
longer = shorter = equal = 0
deltas = []
for seg_id, raw_html, raw_text, seg_type, created, has_row, has_cell in results:
    extracted = extract_text_like_segmenter(raw_html)
    delta = len(raw_text) - len(extracted)
    deltas.append((seg_id, delta, seg_type))

    if delta > 10:
        longer += 1
    elif delta < -10:
        shorter += 1
    else:
        equal += 1

print(f"\nraw_text longer than extracted HTML: {longer}")
print(f"raw_text shorter than extracted HTML: {shorter}")
print(f"Approximately equal (±10 chars): {equal}")

# Show distribution
print(f"\nDelta distribution:")
for seg_id, delta, seg_type in sorted(deltas, key=lambda x: -x[1])[:10]:
    print(f"  Segment {seg_id} ({seg_type}): {delta:+d} chars")
conn.close()
EOF

# Investigation 2: Analyze specific segment (UPDATE ID if 25861 doesn't exist)
DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis" python3 << 'EOF'
import psycopg
import os
from bs4 import BeautifulSoup

# NOTE: Update this extraction method based on Investigation 0 findings
def extract_text_like_segmenter(html):
    """TODO: Replace with actual method from Investigation 0"""
    soup = BeautifulSoup(html, 'html.parser')
    return soup.get_text(separator=' ', strip=True)

conn = psycopg.connect(os.environ['DATABASE_URL'])
cur = conn.cursor()

# First, find a Farfetch segment if 25861 doesn't exist
cur.execute("""
    SELECT ss.source_segment_id
    FROM source_segments ss
    JOIN filings f ON ss.filing_id = f.filing_id
    JOIN companies c ON f.company_id = c.company_id
    WHERE c.company_name ILIKE '%farfetch%'
    ORDER BY ss.source_segment_id
    LIMIT 1
""")
fallback = cur.fetchone()

segment_id = 25861  # Try this first
cur.execute("""
    SELECT raw_html, raw_text, segment_type, created_at, updated_at,
           has_row_marker, has_cell_marker
    FROM source_segments
    WHERE source_segment_id = %s
""", (segment_id,))

row = cur.fetchone()
if not row and fallback:
    segment_id = fallback[0]
    cur.execute("""
        SELECT raw_html, raw_text, segment_type, created_at, updated_at,
               has_row_marker, has_cell_marker
        FROM source_segments
        WHERE source_segment_id = %s
    """, (segment_id,))
    row = cur.fetchone()

if row:
    raw_html, raw_text, seg_type, created, updated, has_row, has_cell = row
    extracted = extract_text_like_segmenter(raw_html)

    print(f"Analyzing segment {segment_id}")
    print(f"Segment type: {seg_type}")
    print(f"Created: {created}")
    print(f"Updated: {updated}")
    print(f"has_row_marker: {has_row}, has_cell_marker: {has_cell}")
    print(f"\nraw_text length: {len(raw_text)}")
    print(f"extracted HTML text length: {len(extracted)}")
    print(f"Delta: {len(raw_text) - len(extracted)}")

    # Find divergence point
    min_len = min(len(raw_text), len(extracted))
    diverge_at = None
    for i in range(min_len):
        if raw_text[i] != extracted[i]:
            diverge_at = i
            break

    if diverge_at:
        print(f"\nFirst divergence at position {diverge_at}")
        print(f"raw_text[{diverge_at}]: {repr(raw_text[diverge_at:diverge_at+1])}")
        print(f"extracted[{diverge_at}]: {repr(extracted[diverge_at:diverge_at+1])}")
        print(f"\nraw_text around divergence:")
        print(f"  ...{raw_text[max(0,diverge_at-30):diverge_at]}<<<HERE>>>{raw_text[diverge_at:diverge_at+50]}...")
        print(f"\nextracted around divergence:")
        print(f"  ...{extracted[max(0,diverge_at-30):diverge_at]}<<<HERE>>>{extracted[diverge_at:diverge_at+50]}...")
    elif len(raw_text) == len(extracted):
        print("\nTexts match exactly!")

    if len(raw_text) > len(extracted):
        extra = raw_text[len(extracted):]
        print(f"\nExtra content in raw_text ({len(extra)} chars):")
        print(repr(extra[:500]))
    elif len(extracted) > len(raw_text):
        extra = extracted[len(raw_text):]
        print(f"\nExtra content in extracted ({len(extra)} chars):")
        print(repr(extra[:500]))
else:
    print(f"Segment {segment_id} not found, and no Farfetch segments exist")
conn.close()
EOF
```

## Output Format

Create a findings document with this structure:

```markdown
# HRV-21 Diagnostic Investigation Findings

## Executive Summary
[1-2 paragraphs: key findings and recommendation]

## Investigation Results

### 0. Intended Behavior Analysis (CRITICAL)
- **How raw_html is populated**: [description with code reference]
- **How raw_text is populated**: [description with code reference]
- **Intended relationship**: [should they match? is enrichment expected?]
- **Correct comparison method**: [what method should be used]

### 1. Mismatch Count Verification
- Claimed: 48/80 segments (60%)
- Actual: [X/Y segments (Z%)]
- Methodology: [extraction method used, why it's appropriate]
- Interpretation: [bug vs expected behavior]

### 2. Segment Analysis
- Segment ID analyzed: [ID]
- Character comparison results
- Divergence point and content
- Interpretation: [consistent with intended behavior?]

### 3. Original Source Examination
- SEC filing structure findings
- Location of "different" content in source HTML
- Segmentation correctness assessment

### 4. Extraction History
- Segment creation date
- Code changes around that time
- Relevant findings

### 5. Pattern Analysis
- Consistency across segments
- Farfetch-specific vs systemic
- Segment type correlation

## Root Cause Determination

**Finding**: [One of the following]

A. **Data Corruption**: raw_text contains content that should not be there
   - Evidence: [...]
   - Cause: [...]

B. **Expected Behavior**: raw_text intentionally differs from raw_html extraction
   - Evidence: [...]
   - Design rationale: [...]

C. **Stale Data**: Extraction logic changed, stored data reflects old behavior
   - Evidence: [...]
   - When changed: [...]

D. **Inconclusive**: Unable to determine with available evidence
   - What's known: [...]
   - What's uncertain: [...]

## Recommendation for HRV-20

**Recommendation**: [PROCEED AS-IS | MODIFY APPROACH | ABANDON]

**Rationale**: [why this recommendation, based on findings]

**If PROCEED**: [any adjustments needed]
**If MODIFY**: [specific changes needed to HRV-20]
**If ABANDON**: [alternative approach suggested]
```

## Critical Evaluation Phase

**Required: Depth M (Thorough)**

After investigation but BEFORE finalizing findings:

1. **Evidence Review**
   - [ ] Each claim supported by data
   - [ ] Alternative explanations considered
   - [ ] No logical leaps or assumptions
   - [ ] Investigation 0 findings inform all subsequent interpretations

2. **Methodology Check**
   - [ ] Text extraction method matches what HTMLSegmenter actually uses
   - [ ] Comparison is apples-to-apples
   - [ ] Sample size sufficient for conclusions
   - [ ] Did not assume BeautifulSoup.get_text() without verification

3. **Recommendation Validation**
   - [ ] Recommendation follows logically from findings
   - [ ] Risks of recommended path documented
   - [ ] If ABANDON, alternative path suggested
   - [ ] Considered impact on downstream tasks (HRV-20, HRV-16)

## Reference

- **Issue source**: Critical evaluation of HRV-20 assumptions
- **Related tasks**: HRV-17 (code fix complete), HRV-20 (blocked pending this investigation)
- **Key question**: Is the data actually corrupt, or is this expected behavior?

---

**Last Updated**: 2026-01-03
**Format Version**: 2.6
