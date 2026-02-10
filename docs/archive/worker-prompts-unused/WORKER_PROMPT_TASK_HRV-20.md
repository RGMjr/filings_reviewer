# WORKER PROMPT: Task HRV-20 - Diagnose and Remediate Farfetch Segment Data Mismatch

> **TASK SUPERSEDED (2026-01-03)**
>
> This task was superseded by **HRV-22** which combines:
> 1. Root cause fix in HTMLSegmenter (bug where raw_text is extracted from full element but raw_html is truncated afterward)
> 2. Data re-extraction for affected filings
>
> See `docs/worker-prompts/WORKER_PROMPT_TASK_HRV-22.md` for the combined implementation.
>
> **Original scope (diagnosis only) was completed by HRV-21** - see `docs/archive/HRV-21_DIAGNOSTIC_FINDINGS.md`

```
===============================================================================
TASK ID:       HRV-20
TASK NAME:     Diagnose and remediate Farfetch HTML/text segment data mismatch
WORKSTREAM:    Human Review Validation
SOURCE:        HRV-17 investigation findings (TableRowParser working correctly, data is corrupt)
STATUS:        SUPERSEDED by HRV-22
COMPLETION:    N/A
TIME ESTIMATE: 2-4 hours (diagnosis 1-2h, remediation 1-2h)
TIME ACTUAL:   N/A
RISK LEVEL:    MEDIUM - Re-extraction may affect existing review decisions
               - Risk: Losing review decisions if candidates change IDs
               - Risk: Fix may not be straightforward if multiple issues exist
               - Mitigation: Backup data before any remediation; preserve decision linkage
TASK SIZE:     M
DEPENDS ON:    None (standalone investigation)
UNLOCKS:       HRV-16 (Validation re-run can proceed after data is fixed)
BLOCKS:        HRV-16
PARALLEL WITH: HRV-12 (no file conflicts)
===============================================================================
```

## Objective

Investigate why 60% of Farfetch segments (48/80) have `raw_text` containing more content than exists in `raw_html`, then remediate the issue so TableRowParser can correctly map all text positions.

**Business Rationale**: Farfetch recall is stuck at 23.9% because valid candidates in "unmapped" text regions are filtered out. The HRV-17 investigation proved that TableRowParser is working correctly - the issue is that `raw_text` contains 188 characters (the "Farfetch Marketplace" section with Active Consumers, Number of Orders, AOV) that simply don't exist in `raw_html`.

**Current Behavior**:
- Segment 25861: `raw_text` = 716 chars, `raw_html` extracts to 528 chars
- 48/80 Farfetch segments have similar mismatches (60% of filing)
- Table segments consistently have +188 char delta (same "Farfetch Marketplace" section)
- `TableRowParser.are_in_same_row()` returns False for positions 529-716 (can't find rows in HTML)
- Valid candidates for Active Consumers, Number of Orders, AOV are filtered out

**Desired Behavior**:
- `raw_html` contains all content that exists in `raw_text`
- OR `raw_text` matches what can be extracted from `raw_html`
- TableRowParser can map 100% of text positions to rows
- Farfetch recall improves to 50%+ (from 23.9%)

## Prerequisites

- Understanding of `src/extraction/html_segmenter.py` and how segments are created
- Database access to query and potentially update `source_segments` table
- Understanding of how review decisions link to candidates (avoid breaking linkage)

## Files to Read (Context Only)

- `src/extraction/html_segmenter.py` - How segments are created (lines 730-790, 1051-1132)
- `src/extraction/extraction_pipeline.py` - How extraction is orchestrated
- `src/infra/db.py` - Database methods for segments and candidates
- `sql/02_create_extraction_schema.sql` - Schema for source_segments table

## Files to Modify

1. **None initially** - This is primarily a diagnostic task
2. **Database**: May need to re-extract or repair segment data
3. **`src/extraction/html_segmenter.py`** - Only if a code bug is found (unlikely)

## Implementation Requirements

### Phase 1: Diagnosis (Required)

1. **Trace Segment Creation History**
   - Query when segment 25861 was created (`created_at` column)
   - Check if segment was ever updated (`updated_at` vs `created_at`)
   - Determine if segment was created with current code or older version

2. **Analyze HTML Structure**
   - Examine the actual `raw_html` content for segment 25861
   - Identify if there are sibling tables or adjacent elements that might contain the missing text
   - Check if the "Farfetch Marketplace" section is in a separate table in the original filing

3. **Compare Extraction Methods**
   - Run current `_extract_table_text_with_markers()` on `raw_html` - what does it produce?
   - Compare with `raw_text` - where does the extra 188 chars come from?
   - Check if markers are present (`has_row_marker`, `has_cell_marker` both False for 25861)

4. **Check Filing Source**
   - Fetch the original Farfetch S-1 filing from SEC EDGAR
   - Find the table containing "Farfetch Marketplace: Active Consumers" section
   - Determine if the 188 missing chars are in the same HTML table or a different element

5. **Pattern Analysis**
   - Are all 48 mismatched segments from the same section of the filing?
   - Do paragraph segments (30/48) have different root cause than table segments (18/48)?
   - Is this a systematic issue with how Farfetch filing was originally extracted?

### Phase 2: Remediation (Based on Diagnosis)

**Scenario A: Missing HTML (most likely)**
If `raw_html` was truncated or doesn't contain all the content:
- Re-extract the Farfetch filing with current `HTMLSegmenter`
- Verify new segments have matching `raw_html` and `raw_text`
- Preserve existing review decisions by matching on content, not ID

**Scenario B: Text Concatenation Bug**
If `raw_text` was incorrectly concatenated from multiple elements:
- Fix the `raw_text` to match what `raw_html` produces
- Document the bug location if in code (create follow-up task to fix)

**Scenario C: Complex Issue**
If the issue is more complex (e.g., original extraction used different logic):
- Document findings in detail
- Create follow-up task with specific remediation steps
- Do NOT attempt risky remediation without approval

### Error Handling

- **Before any data modification**: Create backup of affected segments
- **If re-extraction fails**: Restore from backup, document error
- **If review decisions would be lost**: STOP and ask user before proceeding

### Performance Requirements

- Diagnosis queries should complete in <30 seconds
- Re-extraction of single filing should complete in <5 minutes

## Test Requirements

### No New Tests Required

This is a diagnostic/remediation task. Verification is done through:
1. Comparing pre/post segment data
2. Validating HTML/text consistency
3. Running gold standard validation

### Verification Queries

```sql
-- Check segment HTML/text consistency after remediation
SELECT
    source_segment_id,
    LENGTH(raw_text) as text_len,
    LENGTH(raw_html) as html_len,
    segment_type
FROM source_segments ss
JOIN filings f ON ss.filing_id = f.filing_id
JOIN companies c ON f.company_id = c.company_id
WHERE c.company_name ILIKE '%farfetch%'
AND LENGTH(raw_text) > LENGTH(raw_html) + 100;  -- Should return 0 rows after fix
```

## Acceptance Criteria

- [ ] Root cause documented (WHY does raw_text have content not in raw_html?)
- [ ] All 48 mismatched Farfetch segments identified and categorized
- [ ] Remediation applied OR follow-up task created with specific fix
- [ ] After remediation: 0 segments with raw_text > raw_html + 100 chars
- [ ] Existing review decisions preserved (or documented why not possible)
- [ ] Gold standard validation run shows improved Farfetch recall
- [ ] No regressions in Slack filing metrics

## Do NOT

- Modify `src/review/table_structure.py` (HRV-17 code is correct)
- Delete review decisions without explicit user approval
- Re-extract filings other than Farfetch without investigation
- Make assumptions about root cause without evidence
- Proceed with risky remediation if diagnosis is unclear

## Verification Commands

```bash
# Check current segment state
DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis" python3 << 'EOF'
import psycopg
import os
from bs4 import BeautifulSoup

conn = psycopg.connect(os.environ['DATABASE_URL'])
cur = conn.cursor()

cur.execute("""
    SELECT COUNT(*) as total,
           COUNT(*) FILTER (WHERE LENGTH(raw_text) > LENGTH(raw_html) + 100) as mismatched
    FROM source_segments ss
    JOIN filings f ON ss.filing_id = f.filing_id
    JOIN companies c ON f.company_id = c.company_id
    WHERE c.company_name ILIKE '%farfetch%'
""")
total, mismatched = cur.fetchone()
print(f"Farfetch segments: {total} total, {mismatched} mismatched")
print(f"Target: 0 mismatched after remediation")
conn.close()
EOF

# Validate after remediation
DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis" \
  python3 scripts/validate_against_gold_standard.py --company "Farfetch" --mode fresh
```

## Critical Evaluation Phase

**Required for all tasks. Depth: M (Thorough evaluation)**

After diagnosis is complete but BEFORE applying remediation:

1. **Document Root Cause**
   - [ ] Clear explanation of why mismatch exists
   - [ ] Evidence supporting the diagnosis
   - [ ] Any uncertainty or assumptions noted

2. **Remediation Risk Assessment**
   - [ ] Impact on existing review decisions quantified
   - [ ] Backup strategy documented
   - [ ] Rollback plan if remediation fails

3. **User Approval (REQUIRED)**
   - STOP and present diagnosis findings
   - Get explicit approval before any data modification
   - Document user decision

## Expected Impact

**Before HRV-20**:
- Farfetch: 48/80 segments with data mismatch (60%)
- Farfetch recall: 23.9%
- TableRowParser unable to map 26% of text positions

**After HRV-20**:
- Farfetch: 0 segments with data mismatch
- Farfetch recall: 50%+ (target)
- TableRowParser can map 100% of text positions

## Reference

- **Issue source**: HRV-17 investigation (table row parsing is working; data is corrupt)
- **Related tasks**: HRV-17 (code fix complete), HRV-16 (validation after data fix)
- **Key finding**: 60% of Farfetch segments have `raw_text` containing content not in `raw_html`

---

**Last Updated**: 2026-01-03
**Format Version**: 2.6
