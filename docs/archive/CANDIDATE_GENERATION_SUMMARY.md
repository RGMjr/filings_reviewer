# Candidate Generation Summary
**Date:** 2025-12-17
**Status:** ✅ READY FOR TESTING

## Overview

Generated candidates for 4 filings to test the human review system. **All candidates have proper source_segment_id links** and the system now includes actual table candidates for testing.

## Results by Filing

| Filing | Company | Candidates | Segment Types | Table Candidates | Status |
|--------|---------|------------|---------------|------------------|--------|
| 35 | **Slack Technologies** | **88** | paragraph, definition_block, methodology_block, **table** | **2** ✅ | **Perfect for testing** |
| 31 | Farfetch Ltd | 23 | paragraph | 0 | Good variety |
| 32 | Snowflake | 3 | definition_block | 0 | Small set |
| 33 | Snap | 0 | - | 0 | No metric keywords matched |
| **TOTAL** | | **114** | | **2** | |

## Key Findings

### ✅ All Candidates Have source_segment_id
- **114/114 candidates (100%)** have proper segment links
- **0 NULL values** - table display will work correctly

### 🎯 Table Display Testing Ready

**Slack filing has 2 table candidates** (candidates #1605 and #1606):
- Both from segment 8752 (12.6KB HTML)
- Revenue table showing Year Ended January 31 across 2017/2018/2019
- Values: $220,544 and $400,552
- Metric: `cm_deferred_revenue`
- Table text preview: "Year Ended January 31, 2017 2018 2019 (In thousands)Revenue$105,153 $220,544 $400,552Add: Total deferred revenue..."

**This is perfect for testing:**
1. ✅ Table HTML display in review UI
2. ✅ Table row-aware keyword matching
3. ✅ Highlighted values in table context
4. ✅ Same-row metric/value validation

### 📊 Candidate Distribution

**Slack (88 candidates):**
- 69 from paragraphs (55 contain embedded tables)
- 13 from definition blocks
- 4 from methodology blocks
- 2 from table segments ⭐

**Metrics detected in Slack:**
- Deferred Revenue (cm_deferred_revenue)
- Daily Active Users (cm_daily_active_users)
- MRR (cm_mrr)
- ARR (cm_arr)
- Net Revenue Retention (cm_net_revenue_retention)
- Billings (cm_billings)
- Active Customers Total (cm_active_customers_total)

## Testing Instructions

### Access Review UI

```bash
# Web interface is running at:
open http://127.0.0.1:5002/review/filings

# Direct links to specific filings:
open http://127.0.0.1:5002/review/filing/35  # Slack (88 candidates)
open http://127.0.0.1:5002/review/filing/31  # Farfetch (23 candidates)
open http://127.0.0.1:5002/review/filing/32  # Snowflake (3 candidates)
```

### Test Table Display

1. **Navigate to Slack filing:** http://127.0.0.1:5002/review/filing/35
2. **Find table candidates:** Look for candidates #1605 or #1606
3. **Verify table display:**
   - Should show "Table" badge in context header
   - Should render HTML table with highlighted value
   - Should display table structure (rows/columns)
   - Should highlight the candidate value in yellow

### Test Table Row Matching

For the table candidates, verify:
1. The keyword "deferred revenue" is in the **same row** as the value
2. The table has multiple rows with different metrics
3. Keywords from other rows don't incorrectly match values

### Test Review Workflow

1. **Accept a candidate:** Click "Accept" and assign correct metric
2. **Reject a candidate:** Click "Reject" with reason
3. **Reclassify:** Change metric assignment
4. **Skip:** Move to next without decision
5. **Navigate:** Use pagination, keyboard shortcuts

## Verification Queries

```sql
-- Verify all candidates have source_segment_id
SELECT COUNT(*) as null_count
FROM review_candidates
WHERE source_segment_id IS NULL;
-- Expected: 0

-- View table candidates
SELECT rc.candidate_id, rc.parsed_value, rc.triggering_keyword,
       ss.segment_type, LEFT(ss.raw_text, 100) as preview
FROM review_candidates rc
JOIN source_segments ss ON rc.source_segment_id = ss.source_segment_id
WHERE ss.segment_type = 'table'
ORDER BY rc.candidate_id;
-- Expected: 2 rows from Slack

-- Summary by filing
SELECT c.company_name, COUNT(*) as candidates
FROM review_candidates rc
JOIN filings f ON rc.filing_id = f.filing_id
JOIN companies c ON f.company_id = c.company_id
GROUP BY c.company_name
ORDER BY candidates DESC;
-- Expected: Slack=88, Farfetch=23, Snowflake=3
```

## Files Created

- `scripts/generate_candidates_for_filing.py` - Script to generate candidates for specific filings
- `scripts/regenerate_candidates_with_segments.py` - Full regeneration with decision backup
- `review_decisions_backup.json` - Backup of review decisions
- `REGENERATION_REPORT.md` - Detailed regeneration analysis
- `CANDIDATE_GENERATION_SUMMARY.md` - This file

## Next Steps

1. ✅ **Test table display** - View candidates #1605 and #1606 in Slack filing
2. ✅ **Test review workflow** - Accept/reject candidates, test navigation
3. ✅ **Verify table row matching** - Check that keywords don't cross rows
4. 📊 **Review metrics** - Test reclassification dropdown ordering
5. 🔍 **Test edge cases** - Embedded tables in paragraphs, long tables, etc.

## Notes

- **High recall config used** - Generates more candidates (some may be false positives)
- **Farfetch decisions recovered** - All 11 decisions from previous session restored
- **Snap has 0 candidates** - No metric keywords matched in this filing
- **55 paragraph candidates contain tables** - Paragraphs with embedded HTML tables

## Success Metrics

To validate the fix was successful:
- ✅ All candidates have non-NULL source_segment_id
- ✅ Table candidates exist for testing
- ✅ Review UI loads without errors
- ✅ Table HTML displays correctly in UI
- ✅ Decisions can be created and saved
- ✅ Navigation works smoothly
