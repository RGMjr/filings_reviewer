# WORKER PROMPT: Task HRV-5 - Review New Filings (Expansion)

```
═══════════════════════════════════════════════════════════════════════════════
TASK ID:       HRV-5
TASK NAME:     Review remaining filings and add to gold standard
WORKSTREAM:    Human Review Validation
SOURCE:        docs/HUMAN_REVIEW_VALIDATION_PLAN.md
STATUS:        🟡 PENDING
COMPLETION:    N/A
TIME ESTIMATE: 6-8 hours (review 4 filings, ~50-80 candidates each, add to CSV)
TIME ACTUAL:   N/A
RISK LEVEL:    None - Manual review task, additive to gold standard
TASK SIZE:     XL
DEPENDS ON:    HRV-3, HRV-4 (learn patterns from validated filings first)
UNLOCKS:       HRV-6 (comprehensive data for analysis)
BLOCKS:        None
PARALLEL WITH: None
═══════════════════════════════════════════════════════════════════════════════
```

## Objective

Review review candidates for 4 additional filings not yet in the gold standard (Snowflake, DocuSign, Snap, Samsara Vision). Add accepted metrics to the gold standard CSV to expand coverage.

**Business Rationale**: Current gold standard has 108 metrics from 2 companies. Expanding to additional companies improves diversity and covers additional industries (cloud SaaS, enterprise software, social media, IoT).

**Current Behavior**: Gold standard has 108 metrics from Farfetch (67) and Slack (38) plus 3 from Samsara Vision.

**Desired Behavior**: Gold standard expanded with 15-40 new metrics from filings with customer metric disclosures.

**Note on realistic expectations**: Metric yield varies significantly by filing. Richest filings (Farfetch, Slack) yielded 38-67 metrics each. Many S-1s have minimal or no customer metric disclosures. Prior experience shows 0-30 metrics per filing is typical.

## Prerequisites

- HRV-3 complete (learned FP/FN patterns from Slack)
- HRV-4 complete (learned FP/FN patterns from Farfetch)
- Database has all 4 target filings loaded
- Review candidates generated for each filing

## Files to Modify

1. **`data/gold_standard/golden_set_251218.csv`** - Add new metric rows (15-40 expected)

## Files to Create

1. **`docs/analysis/HRV-5_NEW_FILINGS_REVIEW.md`** - Review results per filing

## Files to Read (Context Only)

- `docs/analysis/HRV-3_SLACK_VALIDATION.md` - FP/FN patterns to watch for
- `docs/analysis/HRV-4_FARFETCH_VALIDATION.md` - FP/FN patterns to watch for
- `data/gold_standard/golden_set_251218.csv` - Current schema and examples

## Implementation Requirements

### Target Filings

| Filing ID | Company | Industry | Expected Metrics |
|-----------|---------|----------|------------------|
| 39 | Snowflake | Cloud/SaaS | 10-30 (depends on disclosure richness) |
| 40 | DocuSign | Enterprise SaaS | 0-20 (may have limited customer metrics) |
| 33 | Snap | Social Media | 5-25 (user metrics vary widely) |
| 38 | Samsara Vision | IoT | 0-5 (early-stage, expand from 3) |

**Note on expected yields**: Metric incidence varies dramatically by company. Richest filings (Farfetch, Slack) yielded 38-67 metrics. Many S-1s have minimal customer metric disclosures, yielding 0-10 metrics. Total expectation: 15-40 new metrics across all filings.

### Review Workflow Per Filing

1. **Generate Candidates**
   ```bash
   DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis" \
     python scripts/generate_review_candidates.py --filing-id [N]
   ```

2. **Review All Candidates**
   - Use web interface to review each candidate
   - Apply patterns learned from HRV-3/HRV-4
   - Accept valid metrics, reject false positives
   - Document any new patterns not seen before

3. **Export Accepted Decisions**
   ```bash
   DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis" \
     python scripts/export_review_decisions.py \
       --filing-id [N] --status accepted --output [company]_accepted.csv
   ```

4. **Add to Gold Standard**
   - Merge exported CSV with gold standard
   - Fill in new columns (segment_type, detection_difficulty, etc.)
   - Validate CSV format

### Industry-Specific Considerations

**Snowflake (Cloud/SaaS)**:
- Product revenue vs Professional services
- Consumption-based metrics
- Net revenue retention
- Remaining performance obligations (RPO)
- Customer counts by size tier

**DocuSign (Enterprise SaaS)**:
- Subscription revenue
- eSignature volume
- Customer retention
- Billings vs Revenue

**Snap (Social Media)**:
- DAU/MAU patterns
- ARPU (Average Revenue Per User)
- Time spent metrics
- Story views / content metrics
- Geographic segments

**Samsara Vision (IoT)**:
- Connected devices
- ARR (Annual Recurring Revenue)
- Customer counts
- Usage/telemetry metrics

### Gold Standard Entry Requirements

For each accepted metric, add to CSV with:

| Column | Requirement |
|--------|-------------|
| document_url | SEC filing URL |
| company | Company name (exact) |
| metric_id | Standard ID (e.g., cm_dau) or new ID |
| is_new_metric | TRUE if not in standard taxonomy |
| text_variant | Exact text from filing |
| raw_value | Raw numeric value |
| scaled_value | Normalized value (optional) |
| scale_unit | Unit (millions, percent, etc.) |
| period_start | YYYY-MM-DD (if known) |
| period_end | YYYY-MM-DD (if known) |
| definition | Definition text (if provided) |
| source_quote | Full context quote |
| segment_type | paragraph/table/list_item |
| is_definition_only | TRUE/FALSE |
| value_context | inline/table_cell/chart |
| detection_difficulty | easy/medium/hard |
| notes | Any reviewer notes |

### Documentation Requirements

Create `docs/analysis/HRV-5_NEW_FILINGS_REVIEW.md` with:

```markdown
# HRV-5: New Filings Review Results

**Reviewed**: [DATE]
**Filings Reviewed**: 4

## Summary

| Filing | Company | Industry | Candidates | Accepted | Rejected | New Metrics Added |
|--------|---------|----------|------------|----------|----------|-------------------|
| 39 | Snowflake | Cloud/SaaS | [N] | [N] | [N] | [N] |
| 40 | DocuSign | Enterprise SaaS | [N] | [N] | [N] | [N] |
| 33 | Snap | Social Media | [N] | [N] | [N] | [N] |
| 38 | Samsara Vision | IoT | [N] | [N] | [N] | [N] |
| **Total** | - | - | [N] | [N] | [N] | [N] |

## Snowflake Review

### Metrics Added to Gold Standard
| Metric ID | Text Variant | Value | Detection Difficulty |
|-----------|--------------|-------|---------------------|
| cm_revenue | "Product revenue" | $X | easy |
| ... | ... | ... | ... |

### Industry-Specific Patterns
- [Pattern 1]
- [Pattern 2]

### New FP Patterns (not seen in HRV-3/4)
- [Pattern if any]

## DocuSign Review
[Same structure as above]

## Snap Review
[Same structure as above]

## Samsara Vision Review
[Same structure as above]

## Gold Standard Expansion Summary

**Before HRV-5**: 108 metrics from 3 companies
**After HRV-5**: [N] metrics from 6 companies

### New Metric Types Discovered
- [New metric type 1]
- [New metric type 2]

### Recommendations for Future Reviews
- [Recommendation 1]
- [Recommendation 2]
```

### Error Handling

- **Filing Not in Database**: Document and skip, proceed with others
- **No Candidates Generated**: Run generation script first
- **Ambiguous Metrics**: Mark as rejected, note in observations

## Test Requirements

### No Automated Tests Required

This is a manual review task. Validation is via:
1. All candidates reviewed for all 4 filings
2. Gold standard CSV expanded with 50+ new metrics
3. CSV still valid and parseable
4. Documentation complete

## Acceptance Criteria

- [ ] All 4 target filings reviewed (Snowflake, DocuSign, Snap, Samsara Vision)
- [ ] All review candidates have accept/reject decisions
- [ ] New metrics added to gold standard CSV (15-40 expected, depends on disclosure richness)
- [ ] Each filing reviewed (some may yield 0 metrics if no customer disclosures)
- [ ] Gold standard CSV remains valid (parseable with csv.DictReader)
- [ ] Industry-specific patterns documented for each filing
- [ ] Any new FP/FN patterns documented
- [ ] `docs/analysis/HRV-5_NEW_FILINGS_REVIEW.md` created
- [ ] New columns filled for added metrics (segment_type, detection_difficulty, etc.)

## Do NOT

- Delete existing gold standard entries
- Modify existing gold standard entries (only add new)
- Skip filings (review all 4)
- Add metrics without source quote verification

## Verification Commands

```bash
# Verify candidates reviewed for each filing
for id in 33 38 39 40; do
  echo "Filing $id:"
  DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis" \
    psql -c "
      SELECT
        COUNT(*) as total_candidates,
        COUNT(rd.id) as reviewed
      FROM review_candidates rc
      LEFT JOIN review_decisions rd ON rc.id = rd.candidate_id
      WHERE rc.filing_id = $id
    "
done

# Verify gold standard row count increased
python3 -c "
import csv
with open('data/gold_standard/golden_set_251218.csv', 'r', encoding='utf-8-sig') as f:
    rows = list(csv.DictReader(f))
    print(f'Total rows: {len(rows)}')
    assert len(rows) >= 158, f'Expected ≥158 rows (108 + 50), got {len(rows)}'
    print('✅ Gold standard expanded')
"

# Verify new companies in gold standard
python3 -c "
import csv
with open('data/gold_standard/golden_set_251218.csv', 'r', encoding='utf-8-sig') as f:
    companies = set(row['company'] for row in csv.DictReader(f))
    print(f'Companies: {companies}')
    expected = {'Farfetch', 'Slack', 'Samsara Vision', 'Snowflake', 'DocuSign', 'Snap'}
    missing = expected - companies
    assert not missing, f'Missing companies: {missing}'
    print('✅ All target companies in gold standard')
"

# Verify documentation exists
ls docs/analysis/HRV-5_NEW_FILINGS_REVIEW.md
```

## Expected Impact

**Before HRV-5**:
- 108 metrics from 3 companies
- Limited industry coverage (enterprise SaaS, fashion e-commerce)
- No cloud/IoT/social media coverage

**After HRV-5**:
- 120-150 metrics from 4-6 companies (depends on disclosure richness)
- Additional industries covered
- More diverse validation dataset
- Better pattern generalization

**Note**: Actual yield depends on which filings have rich customer metric disclosures. Some S-1s focus on financials with minimal customer metrics.

## Reference

- **Issue source**: docs/HUMAN_REVIEW_VALIDATION_PLAN.md
- **Dependencies**: HRV-3, HRV-4
- **Related**: HRV-6 (synthesis)

---

**Last Updated**: 2025-12-26
**Format Version**: 2.4
