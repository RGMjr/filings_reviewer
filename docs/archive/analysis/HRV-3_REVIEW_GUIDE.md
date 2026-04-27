# HRV-3 Review Guide - Slack Filing Validation

## Quick Start

### Step 1: Start the Web Interface

```bash
cd /Users/rgmarkey/Library/CloudStorage/OneDrive-CMASB/Analytics/Filings\ Analysis/Filings\ review\ tool/filings_reviewer
DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis" python3 -m src.web.app
```

Open browser to: http://localhost:8000

### Step 2: Navigate to Slack Filing

- Click on "Slack Technologies, Inc." (filing_id=35)
- You should see 111 review candidates

### Step 3: Review Workflow

For EACH of the 111 candidates:

1. **Read the candidate details**:
   - Context text (surrounding text)
   - Raw number text
   - Parsed value
   - Triggering keyword
   - Suggested metric ID

2. **Compare against gold standard**:
   - Open `data/gold_standard/golden_set_251218.csv` in a second window
   - Search for "Slack Technologies" entries
   - Look for matching metric type and value

3. **Make decision**:
   - **Accept** if:
     - Metric matches gold standard entry
     - Value and context align with known metric
     - Metric type is correctly identified
   - **Reject** if:
     - Not in gold standard
     - False positive (e.g., date, irrelevant number)
     - Wrong metric classification
     - Duplicate of already-accepted candidate

4. **Take notes**:
   - For rejections, note the pattern (e.g., "date in table header", "footnote reference")
   - For accepts, note if metric ID suggestion was correct

### Step 4: Run Validation

After reviewing all 111 candidates:

```bash
DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis" \
  python3 scripts/validate_against_gold_standard.py --filing-id 35 --verbose
```

Save the output to paste into `docs/analysis/HRV-3_SLACK_VALIDATION.md`

### Step 5: Document Patterns

Update `docs/analysis/HRV-3_SLACK_VALIDATION.md` with:
- Summary metrics (precision, recall, F1)
- Top 3-5 false positive patterns
- Top 3-5 false negative patterns
- Recommendations for improvements

---

## Gold Standard Quick Reference

**Slack metrics in gold standard**: 41 total

Key metric types to look for:
- `cm_daily_active_users` - Daily Active Users (DAU)
- `cm_arr` - Annual Recurring Revenue
- `cm_customer` - Paid Customers
- `cm_weekly_active_users` - Weekly Active Users
- `cm_ndr` - Net Dollar Retention Rate
- `cm_revenue` - Revenue figures
- `cm_messages_sent` - Messages sent
- Custom metrics specific to Slack

---

## Common False Positive Patterns to Watch For

Based on other filings, common FPs include:
1. **Dates**: Years (2018, 2019), date components
2. **Table headers**: Column headers with numbers
3. **Footnotes**: Reference numbers (1, 2, 3)
4. **Percentages in non-metric context**: Growth rates, tax rates
5. **Page numbers or section numbers**
6. **Chart/figure references**

---

## Tips for Efficient Review

1. **Use keyboard shortcuts** in web interface (if available)
2. **Sort candidates** by metric type to batch similar reviews
3. **Keep gold standard CSV open** in split screen
4. **Document as you go** - don't wait until the end
5. **Take breaks** every 30-40 candidates to maintain accuracy
6. **Time yourself** to estimate effort for larger filings

---

## Verification Queries

### Check review progress
```sql
SELECT
  COUNT(*) as total_candidates,
  COUNT(rd.decision_id) as reviewed,
  SUM(CASE WHEN rd.decision = 'accept' THEN 1 ELSE 0 END) as accepted,
  SUM(CASE WHEN rd.decision = 'reject' THEN 1 ELSE 0 END) as rejected,
  COUNT(*) - COUNT(rd.decision_id) as pending
FROM review_candidates rc
LEFT JOIN review_decisions rd ON rc.candidate_id = rd.candidate_id
WHERE rc.filing_id = 35;
```

### View accepted candidates
```sql
SELECT
  rc.suggested_metric_id,
  rc.raw_number_text,
  rc.parsed_value,
  rc.triggering_keyword,
  LEFT(rc.context_text, 100) as context_preview
FROM review_candidates rc
JOIN review_decisions rd ON rc.candidate_id = rd.candidate_id
WHERE rc.filing_id = 35 AND rd.decision = 'accept'
ORDER BY rc.suggested_metric_id;
```

---

## Expected Time

- **Candidate review**: 1.5-2.5 hours (111 candidates at 1-1.5 min each)
- **Validation & documentation**: 0.5-1 hour
- **Total**: 2-3.5 hours

---

**Created**: 2025-12-26
**For Task**: HRV-3 - Slack Filing Validation
