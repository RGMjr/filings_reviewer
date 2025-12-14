# Metric Identification Issues

**Status**: Partially Implemented (Issue 1: 2/4 root causes fixed)
**Date Created**: 2025-12-13
**Last Updated**: 2025-12-14
**Priority**: Medium (affects review quality but reviewers can correct)

## Overview

This document tracks known issues with the metric identification and keyword matching system. These issues cause the candidate generator to create false positive candidates by associating values with incorrect metrics.

---

## Issue 1: Proximity Matching Crosses Semantic Boundaries

**Severity**: High
**Filing Example**: Farfetch Ltd
**Reported**: 2025-12-13

### Problem Description

The keyword matching algorithm uses proximity-based matching (default: 100 characters) to associate numbers with metric keywords. This causes incorrect associations when:
- Multiple metrics appear in adjacent bullet points
- Multiple values appear in the same paragraph
- Metric keywords appear in headings/context near unrelated values

### Specific Example

**Text**:
```
• Six month LTV/CAC ratio for the years ended December 31, 2015, 2016 and 2017 cohorts
  was 1.42, 1.53 and 1.72, respectively; and
• Platform Order Contribution Margin for the years ended December 31, 2015, 2016 and 2017
  was 33.0%, 35.0% and 43.0%, respectively.

Lifetime Value of a Consumer to Consumer Acquisition Cost Ratios
```

**Incorrect Association**:
- Value: 33%
- Matched Keyword: "lifetime value" (from heading or "LTV" in first bullet)
- Correct Metric: "Platform Order Contribution Margin" (gross margin)
- Incorrect Metric: "Lifetime Value" or "LTV/CAC ratio"

### Root Causes

1. **No bullet point boundary detection**: The algorithm doesn't recognize that bullet points separate distinct metric-value pairs
2. **No preference for closest keyword**: All keywords within `max_keyword_distance` are treated equally
3. **Heading text included in context**: Headings contribute metric keywords that may not apply to values below
4. **No semantic parsing**: System doesn't understand "respectively" patterns or subject-value relationships

### Impact

- Creates false positive candidates that reviewers must reject
- Increases review burden
- May reduce reviewer confidence in the system
- Multiple candidates generated for same value with different metrics

### Implementation Status

**✅ PARTIALLY COMPLETE** (2025-12-13/14)

**Root Cause 1 & 2 - IMPLEMENTED:**
- ✅ **Bullet point boundary detection**: Implemented in `src/review/boundary_detection.py` (Dec 13)
  - 95% test coverage, 23 comprehensive tests
  - Detects Unicode bullets, numbered lists, lettered lists
  - Tests against real Farfetch LTV/CAC example
  - Integrated via `config.enable_boundary_detection` flag (default: True)

- ✅ **Closest keyword preference**: Implemented in `src/review/keyword_matching.py:289-294` (Dec 13)
  - Sorts matches by distance first (closest keyword wins)
  - Documented as "P1 enhancement" in code
  - Configurable via `config.prefer_closest_keyword` flag (default: True)

**Implementation Details:**
- Files: `boundary_detection.py` (11KB), `test_boundary_detection.py` (11KB)
- Config integration: Both features enabled by default in high-precision and default presets
- Type safety: Passes `mypy --strict` (Dec 14)

**Remaining Root Causes:**
- ❌ Root Cause 3 (heading text): Not yet addressed
- ❌ Root Cause 4 (semantic parsing): Deferred to P2/P3

**Next Steps:**
- Test boundary detection on more filings beyond Farfetch
- Monitor impact on false positive rates during human review

---

## Issue 2: Overly Broad Keyword Patterns for "By Cohort" Metrics

**Severity**: Medium
**Filing Example**: Farfetch Ltd
**Reported**: 2025-12-13

### Problem Description

The metric `cm_gross_margin_by_cohort` uses keyword patterns that match ANY occurrence of "gross margin" or "gross profit" without requiring "cohort" context. This causes:
- Overall gross margin values to be misclassified as "by cohort"
- No "Gross Margin (Overall)" metric available as alternative

### Keyword Patterns (from `metric_classifier.py:196-203`)

```python
"cm_gross_margin_by_cohort": [
    r"\bgross\s+margin\b",        # TOO BROAD - matches ANY gross margin
    r"\bgross\s+profit\b",        # TOO BROAD - matches ANY gross profit
    r"\bmargin\s+by\s+cohort\b",
    r"\bcohort\s+margin\b",
    r"\bgross\s+margin\s+%\b",
    r"\bgross\s+profit\s+margin\b",
],
```

### Root Causes

1. **Missing overall variant**: No `cm_gross_margin_overall` metric exists
2. **Patterns don't check context**: First two patterns don't require "cohort" or "by cohort" nearby
3. **Database vs code mismatch**: `cm_gross_margin_by_cohort` defined in code but not seeded in database

### Impact

- Overall gross margin values incorrectly tagged as "by cohort"
- Reviewers cannot select correct metric (no overall option)
- Metric taxonomy incomplete

---

## Issue 3: No "Respectively" Pattern Recognition

**Severity**: Medium
**Related To**: Issue 1

### Problem Description

The text analysis doesn't recognize "respectively" patterns where multiple values map to multiple time periods in parallel lists:

```
Platform Order Contribution Margin for the years ended December 31, 2015, 2016 and 2017
was 33.0%, 35.0% and 43.0%, respectively.
```

Should create three metric-value-year associations:
- 33.0% → 2015
- 35.0% → 2016
- 43.0% → 2017

Currently creates three candidates but may not correctly associate years with values.

---

## Issue 4: Page Numbers Not Filtered by False Positive Filter

**Severity**: Medium
**Filing Example**: Farfetch Ltd
**Reported**: 2025-12-13

### Problem Description

Page numbers appearing before "Table of Contents" links are being flagged as metric candidates. The false positive filter (`src/review/false_positive_filter.py`) is supposed to filter out page references but is not catching this pattern.

### Specific Example

**Text**:
```
... was 33.0%, 35.0% and 43.0%, respectively.
73 Table of Contents
Lifetime Value of a Consumer to Consumer Acquisition Cost Ratios
```

**False Positive**:
- Value: 73
- Context: Appears immediately before "Table of Contents" link
- Pattern: Sequential numbering (73, 74, 75, etc. throughout document)

### Detection Heuristics

Page numbers can be identified by:
1. **Position**: Immediately before "Table of Contents" text/link
2. **Sequential pattern**: Numbers appear in sequence (73, 74, 75...) before each ToC link
3. **Small integers**: Typically 1-3 digit numbers (page counts rarely exceed 999)
4. **No metric keywords nearby**: Usually standalone numbers without metric context

### Root Causes

1. **Current filter patterns insufficient**: The false positive filter may check for "page" keyword but not "Table of Contents" pattern
2. **No sequential number detection**: Filter doesn't detect patterns of sequential numbers across a document
3. **Context window may exclude "Table of Contents"**: If "Table of Contents" is just outside the context extraction window, the pattern isn't visible

### Impact

- Low-value false positives that reviewers must reject
- Increases review burden
- May appear multiple times per filing (once per page with ToC link)
- Easy to identify visually but requires manual rejection

### Current False Positive Filter (from `false_positive_filter.py`)

The filter currently checks for:
- Years (1990-2100)
- Dates (month/day/year patterns)
- Small values (below `min_metric_value`, default 10)
- Page references (may check for "page" keyword)

Needs enhancement to detect:
- "Table of Contents" proximity pattern
- Sequential standalone numbers
- Common filing footer/header patterns

---

## Issue 5: No Preference for Post-Value Keywords Over Pre-Value Keywords

**Severity**: Medium
**Filing Example**: Farfetch Ltd (and others)
**Reported**: 2025-12-13

### Problem Description

When multiple metric keywords are found near a value, the system doesn't distinguish between keywords appearing BEFORE vs AFTER the value. In many cases, a keyword appearing after the value is a more reliable indicator of the correct metric association.

### Common Patterns

**Pre-value keyword (standard pattern)**:
```
Platform Order Contribution Margin was 33.0%, 35.0% and 43.0%
```
- Metric keyword: "margin" (before values)
- Values: 33.0%, 35.0%, 43.0%
- Association: Correct

**Post-value keyword (often more specific)**:
```
Achieved 33% gross margin in 2017
```
- Value: 33%
- Metric keyword: "margin" (after value)
- Association: More specific/reliable

**Ambiguous case (multiple pre-value keywords)**:
```
Lifetime value metrics showed 33% gross margin improvement
```
- Value: 33%
- Pre-value keyword 1: "lifetime value" (farther away)
- Pre-value keyword 2: "gross margin" (closer)
- Post-value keyword: "margin" (could be from "gross margin")

### Why Post-Value Keywords Are Often More Reliable

1. **Subject-verb-object structure**: "Achieved 33% margin" - the metric is the object being described
2. **Less contamination from context**: Headlines and previous sentences are typically before the value
3. **Metric clarification**: Often used to clarify what a number represents: "33% (gross margin)"
4. **Appositives and labels**: "33%, or the gross margin, ..." - metric appears after as explanation

### Current Behavior

The keyword matching algorithm:
1. Finds ALL keywords within `max_keyword_distance` (default: 100 chars) in BOTH directions
2. Treats all matches equally (no preference for direction)
3. May prefer closest keyword, but doesn't weight post-value keywords higher

### Impact

- When both pre-value and post-value keywords exist, may choose the wrong one
- Increases false positives when pre-value keyword is from unrelated context
- Reduces confidence in correct associations

### Proposed Enhancement

Add directionality weighting to keyword matching:
1. **Distance score**: Closer keywords preferred (already considered)
2. **Direction bonus**: Post-value keywords get small boost (e.g., 0.9x effective distance)
3. **Tiebreaker**: If two keywords at similar distances, prefer post-value

**Example scoring**:
- Pre-value keyword at 30 chars: score = 30
- Post-value keyword at 30 chars: score = 30 * 0.9 = 27 (preferred)
- Pre-value keyword at 20 chars: score = 20
- Post-value keyword at 30 chars: score = 27 (pre-value still wins if much closer)

This makes post-value keywords slightly preferred without completely ignoring pre-value keywords.

### Caveats

The user notes: "This is not a 100% reliable indicator, but it's not a bad start."

Cases where pre-value keywords are correct:
- Standard declarative sentences: "Gross margin was 33%"
- Metric definitions: "Platform Order Contribution Margin ... was 33%"
- Table headers: Column header "Gross Margin" above value "33%"

So the preference should be modest, not absolute.

---

## Issue 6: HTML Segmenter Misclassifies Table Content as Paragraphs

**Severity**: Medium-High
**Filing Example**: Farfetch Ltd
**Reported**: 2025-12-13
**Component**: Upstream extraction pipeline (`html_segmenter.py`)

### Problem Description

Some table content is being classified as `segment_type='paragraph'` instead of `segment_type='table'` during the HTML segmentation phase. This causes table data to be displayed as plain text context, making it difficult to review.

### Specific Example

**Text context shown to reviewer**:
```
Revenue experienced a modest decrease of 1.9%, from $7.3 million to $7.2 million,
reflecting the closure of one store in West London. Platform Fulfilment Revenue
accounted for 18.9% of revenue for the six months ended June 30, 2018, compared to
19.6% for the six months ended June 30, 2017. Cost of revenue, gross profit and
gross profit margin Six months ended June 30, 2017 2018 $ Change % Change Cost of
revenue $(78,223 ) $(130,643 ) $(52,420 ) (67.0 %) Gross
```

**Table structure visible in text**:
- Table header: "Cost of revenue, gross profit and gross profit margin"
- Column headers: "Six months ended June 30, 2017 2018 $ Change % Change"
- Data row: "Cost of revenue $(78,223) $(130,643) $(52,420) (67.0%)"

This is clearly table content but being presented as continuous text.

### Indicators That Segment Is Actually a Table

1. **Column header pattern**: "2017 2018 $ Change % Change" - typical table columns
2. **Aligned values**: Numbers appear in sequence matching column structure
3. **Row label**: "Cost of revenue" followed by multiple values
4. **Formatting artifacts**: Parentheses for negative numbers, aligned spacing

### Root Causes

Possible causes in `html_segmenter.py`:

1. **Non-standard table markup**:
   - HTML might use `<div>` layout instead of `<table>` tags
   - CSS-styled divs that look like tables but aren't semantic tables
   - Malformed HTML that parser interprets as paragraphs

2. **Segmenter detection logic incomplete**:
   - Only looks for `<table>` tags, misses other table-like structures
   - Doesn't detect tabular text patterns (aligned columns, repeated structure)
   - Pre-formatted text (`<pre>`) with tabular data classified as paragraph

3. **Nested table handling**:
   - Table within another element might be flattened to text
   - HTML parser might serialize table content into plain text

4. **HTML parsing issues**:
   - SEC filings sometimes have complex/nested HTML
   - Parser might strip table tags if they're malformed
   - BeautifulSoup/lxml might normalize tables away

### Impact

- **Review quality**: Reviewers can't see table structure, making values harder to interpret
- **Context understanding**: Row/column headers not visible as headers
- **Wrong candidate type**: Values from tables should ideally show table context
- **Data quality**: Affects not just review UI but extraction quality scores

### Difference from Issue 1 (Table Display)

- **Issue 1** (FIXED): Candidates with `segment_type='table'` weren't rendering HTML properly
- **Issue 6** (NEW): Candidates with `segment_type='paragraph'` that should be `segment_type='table'`

This is an **upstream data quality issue** in the extraction pipeline, not a UI issue.

### Investigation Results (2025-12-13)

**Segment 3337 Analysis** (the reported example):
- `segment_type = 'definition_block'` (not 'table')
- **Contains proper `<table>` HTML** with correct tr/td structure
- **12 candidates** generated from this segment
- Segment includes BOTH paragraph text AND a table (composite segment)

**Scope Analysis - Farfetch Filing**:

| Segment Type | Total Count | Contains `<table>` | Correctly Classified |
|--------------|-------------|-------------------|---------------------|
| `table` | 557 | 557 (100%) | ✅ 557 |
| `definition_block` | 209 | 125 (60%) | ❌ 0 (misclassified) |
| `methodology_block` | 100 | 74 (74%) | ❌ 0 (misclassified) |
| `paragraph` | 1,207 | 38 (3%) | ❌ 0 (misclassified) |

**Key Finding**:
- **794 total segments** contain `<table>` tags
- **557 (70%)** correctly classified as `segment_type='table'`
- **237 (30%)** misclassified as other types

**Root Cause Identified**:
The HTML segmenter creates **composite segments** that bundle narrative text with tables, rather than splitting them into separate table/paragraph segments. This is a design decision, not a bug in table detection.

### Solutions Implemented

**✅ Quick UI Fix (2025-12-13)**:

Updated `src/web/templates/review.html` to render tables for ALL segment types:
- Changed condition from `segment_type == 'table'` to `'<table' in segment_html`
- Now renders tables for definition_block, methodology_block, and paragraph segments
- Added "Mixed" badge to indicate composite segments (table + narrative text)
- Benefits **237 additional segments** in Farfetch filing (30% improvement)

**Impact**:
- Farfetch: 794 segments now show tables (up from 557)
- Reviewers can now see table structure for 60% of definition_blocks
- 74% of methodology_blocks now display properly

**Code Changes**:
```jinja2
{% if current_candidate.segment_html and '<table' in current_candidate.segment_html %}
    {# Render table for ANY segment type containing tables #}
    <div class="table-context">...</div>
{% else %}
    {# Render text context #}
    <div class="context-text">...</div>
{% endif %}
```

### Remaining Work (Future)

**P2 - HTML Segmenter Enhancement** (upstream fix):

Current behavior:
- Segmenter creates composite segments (text + table)
- Classification based on dominant content type

Potential improvements:
- Split composite segments into separate table/paragraph segments
- More granular segmentation for better context extraction
- Preserve section hierarchy when splitting

**P3 - Re-segmentation** (if segmenter improved):
- Re-run HTML segmentation on all filings with improved logic
- Update `source_segments` table with finer-grained segments
- Regenerate candidates for affected filings
- Compare extraction quality before/after

---

## Proposed Solutions (For Future Implementation)

### Short-term Fixes (P1)

1. **Add bullet point boundary detection**
   - Detect `•`, `-`, `*`, numbered lists
   - Constrain keyword matching within same bullet point
   - Prefer keywords in same bullet over keywords in adjacent bullets

2. **Implement closest keyword preference**
   - Calculate distance to ALL matching keywords
   - Prefer the closest keyword if multiple matches
   - Log when multiple keywords match at similar distances (potential ambiguity)

3. **Fix gross margin patterns**
   - Add `cm_gross_margin_overall` metric to database and seed file
   - Update patterns for `cm_gross_margin_by_cohort` to require "cohort" context
   - Add negative patterns (reject if "overall" or "total" nearby)

4. **Reduce max_keyword_distance**
   - Current default: 100 characters
   - Test with 50-75 characters to reduce cross-contamination
   - Make configurable per metric type

5. **Enhance false positive filter for page numbers**
   - Add "Table of Contents" proximity check to `false_positive_filter.py`
   - Filter numbers immediately before "Table of Contents" (within 5-10 characters)
   - Consider adding sequential number detection (optional, more complex)
   - Check for common footer/header patterns (page numbers, dates)

### Medium-term Improvements (P2)

1. **Sentence/clause boundary detection**
   - Use sentence tokenization to constrain matching
   - Don't match across sentence boundaries unless necessary
   - Respect semicolons and conjunction patterns

2. **Heading context separation**
   - Detect headings (all caps, bold, size changes in HTML)
   - Reduce weight of keywords from headings vs body text
   - Don't match heading keywords to values in different sections

3. **"Respectively" pattern parser**
   - Detect "X, Y and Z ... A, B and C, respectively" patterns
   - Create parallel associations (X→A, Y→B, Z→C)
   - Extract year/period associations correctly

4. **Add directionality weighting to keyword matching**
   - Modify `keyword_matching.py` to track keyword direction (before/after value)
   - Apply small preference to post-value keywords (0.9x distance multiplier)
   - Use as tiebreaker when multiple keywords at similar distances
   - Make multiplier configurable (default: 0.9, range: 0.8-1.0)
   - Log cases where direction changes the selected keyword for analysis

### Long-term Solutions (P3)

1. **Semantic dependency parsing**
   - Use spaCy or similar NLP library
   - Parse subject-verb-object relationships
   - Match values to their grammatical subjects (the metrics)

2. **ML-based metric-value association**
   - Train model on human review decisions
   - Learn which features predict correct associations
   - Use pattern analyzer findings to inform features

3. **Confidence scoring based on association quality**
   - High confidence: value in same sentence/clause as keyword
   - Medium confidence: value in same bullet point
   - Low confidence: value in adjacent bullet point
   - Use confidence to prioritize review queue

---

## Testing Strategy (When Implementing Fixes)

### Test Cases Needed

1. **Bullet point separation**: Values in adjacent bullets with different metrics
2. **Respectively patterns**: Parallel lists with time periods
3. **Heading contamination**: Metric keyword in heading, unrelated value below
4. **Multiple metrics, single value**: Should prefer closest keyword
5. **Single metric, multiple values**: Should create multiple candidates correctly

### Test Filings

- **Farfetch Ltd**: Contains Issues 1, 2, and 3
- **Snowflake**: (Add examples as discovered)
- **Snap**: (Add examples as discovered)
- **DocuSign**: (Add examples as discovered)

### Regression Testing

Before implementing fixes:
1. Run candidate generation on test filings
2. Record count of candidates per filing and per metric
3. After fixes, compare counts and spot-check quality
4. Ensure fixes don't eliminate true positives

---

## Related Files

**Review System**:
- `src/review/candidate_generator.py` - Main orchestrator
- `src/review/keyword_matching.py` - Keyword proximity matching logic
- `src/review/false_positive_filter.py` - Filters dates, years, page refs, small values
- `src/review/context_extraction.py` - Context window extraction

**Extraction Pipeline** (upstream):
- `src/extraction/html_segmenter.py` - Segments filing HTML into paragraphs/tables/sections
- `src/extraction/metric_classifier.py` - Metric keyword patterns (source of truth)

**Database**:
- `sql/04_seed_metrics_taxonomy.sql` - Database metric definitions
- `source_segments` table - Stores segment_type and raw_html

---

## Notes

- These issues are observable during human review but don't block the review process
- Reviewers can reject false positives and select correct metrics from dropdown
- Pattern analyzer (E1) may learn to auto-reject some of these patterns
- Gathering more examples before implementing fixes will lead to better solutions
