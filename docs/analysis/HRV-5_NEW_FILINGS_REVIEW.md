# HRV-5: New Filings Review Results

**Reviewed**: 2025-12-27
**Filings Reviewed**: 3 of 4 (see Data Quality Issues)
**Reviewer**: Automated (hrv5_review_decisions.py)

## Summary

| Filing | Company | Industry | Candidates | Accepted | Rejected | New Metrics Added |
|--------|---------|----------|------------|----------|----------|-------------------|
| 39 | Snowflake Inc. | Cloud/SaaS | 165 | 24 | 141 | 24 |
| 40 | DOCUSIGN, INC. | Enterprise SaaS | 103 | 0 | 103 | 0 |
| 38 | Samsara Vision Inc | IoT | 4* | 0* | 4* | 0* |
| 33 | Snap | Social Media | 0 | N/A | N/A | N/A (data issue) |
| **Total** | - | - | 272 | 24 | 248 | 24 |

*Samsara already had 6 reviewed candidates (3 accepted, 3 rejected) from prior review

## Data Quality Issues

### Snap Filing (filing_id=33) - Mislabeled Data

The filing labeled as "Snap" (filing_id=33) contains data for a different company (appears to be RMR Inc., a REIT-related company). The source segments reference:
- "RMR Inc."
- "Managed REITs"
- EBITDA calculations for a REIT company

**Root Cause**: CIK `0001644378` belongs to **RMR Group Inc.** (confirmed 2026-03-19 via SEC API),
not Snap. The wrong CIK was used when this filing was ingested.

**Snap's correct data**: CIK `0001564408`, form S-1/A, filed 2017-02-27,
accession `0001193125-17-056992`, URL:
`https://www.sec.gov/Archives/edgar/data/0001564408/000119312517056992/d270216ds1a.htm`

**Impact**: No candidates were generated for Snap, reducing the expected metric yield.

**Status (2026-03-19)**: Investigation complete. Fix blocked on local dev validation DB rebuild
(DB is empty). See `docs/KNOWN_ISSUES.md` issue #9 for resolution steps.

## Snowflake Review

### Metrics Added to Gold Standard

| Metric ID | Text Variant | Value | Detection Difficulty |
|-----------|--------------|-------|---------------------|
| cm_net_revenue_retention | retention rate was 158% | 158% | easy |
| cm_net_revenue_retention | Net revenue retention | 180% | easy |
| cm_net_revenue_retention | Net revenue retention | 169% | easy |
| cm_net_revenue_retention | Net revenue retention | 223% | easy |
| cm_net_revenue_retention | Net revenue retention | 150% | easy |
| cm_net_revenue_retention | Net revenue retention | 165% | medium |
| cm_net_revenue_retention | Net revenue retention | 187% | medium |
| cm_net_revenue_retention | Net revenue retention | 189% | medium |
| cm_net_revenue_retention | Net revenue retention | 171% | medium |
| cm_active_customers_total | total customers | 948 | easy |
| cm_active_customers_total | total customers | 2,392 | easy |
| cm_active_customers_total | Total customers | 1,547 | medium |
| cm_active_customers_total | total customers | 3,117 | easy |
| cm_active_customers_total | Total customers | 702 | medium |
| cm_active_customers_total | Total customers | 1,194 | medium |
| cm_active_customers_total | Total customers | 1,934 | medium |
| cm_active_customers_total | Total customers | 2,720 | medium |

Note: Some NRR values appear both with and without "%" in the raw text due to table cell parsing.

### Industry-Specific Patterns

1. **Net Revenue Retention > 100%**: Snowflake's NRR ranges from 150% to 223%, indicating strong expansion revenue
2. **Customer Count Progression**: Clear growth from 702 to 3,117 customers across quarters
3. **Table-based Disclosure**: Key metrics presented in structured tables with multiple time periods

### New FP Patterns (not seen in HRV-3/4)

None - all FP patterns were covered by HRV-3/4 learnings:
- Financial statement line items (65 rejected)
- Deferred revenue/RPO values (42 rejected)
- Dollar values wrongly matched to retention rate (16 rejected)

## DocuSign Review

### Metrics Added to Gold Standard

None. All 103 candidates were rejected.

### Industry-Specific Patterns

**Key Finding**: The DocuSign S-1 filing (as processed) did not contain disclosed customer metrics in the expected format. All 103 candidates were:
- Financial statement line items (102 rejections)
- Generic ACV-related numbers (1 rejection)

**Possible Explanations**:
1. Customer metrics may be disclosed in a different format not captured by current segmentation
2. The S-1/A filing version may not have the summary metrics section
3. DocuSign may use different terminology not in current keyword list

### Recommendations

1. Manual review of DocuSign filing to identify actual customer metric disclosures
2. Consider adding DocuSign-specific keywords (e.g., "customers with ACV", "eSignature transactions")

## Samsara Vision Review

### Existing Metrics (from prior review)

| Metric ID | Text Variant | Value |
|-----------|--------------|-------|
| cm_revenue_concentration | Customer A | 39.90% |
| cm_revenue_concentration | Customer C | 20.20% |
| cm_gross_margin_overall | Gross profit | $32 |

### New Metrics Added

None (4 remaining candidates were all financial statement line items)

### Industry-Specific Patterns

1. **Revenue Concentration Disclosure**: Samsara uses Customer A/B/C naming convention for concentration
2. **Early-Stage Financials**: Very small revenue numbers ($39k) typical of early-stage IoT company

## Gold Standard Expansion Summary

**Before HRV-5**: 108 metrics from 3 companies (Farfetch 67, Slack 38, Samsara 3)
**After HRV-5**: 132 metrics from 4 companies (added Snowflake 24)

**Note**: The 24 new metrics achieved is within the realistic expected range (15-40) for reviewing 4 filings. Yields varied as expected:
- Snowflake: 24 metrics (rich SaaS disclosure)
- DocuSign: 0 metrics (financial focus, no customer metrics)
- Snap: Data quality issue (mislabeled filing)
- Samsara: 0 new (early-stage, prior review captured available metrics)

### New Metric Types Discovered

None - Snowflake uses standard SaaS metrics (NRR, Total Customers)

### Companies by Metric Count

| Company | Metrics | Industry |
|---------|---------|----------|
| Farfetch Limited | 67 | Fashion E-commerce |
| Slack Technologies | 38 | Enterprise Collaboration |
| Snowflake Inc. | 24 | Cloud Data Platform |
| Samsara Vision Inc | 3 | IoT/Medical Devices |
| **Total** | **132** | |

## FP Pattern Summary

| Pattern | Snowflake | DocuSign | Samsara | Total |
|---------|-----------|----------|---------|-------|
| Financial statement line item | 65 | 102 | 4 | 171 |
| Deferred revenue/RPO values | 42 | 0 | 0 | 42 |
| Dollar value (not retention rate) | 16 | 0 | 0 | 16 |
| Dollar amount (not customer count) | 5 | 0 | 0 | 5 |
| Not a percentage (concentration) | 4 | 0 | 0 | 4 |
| Date component | 3 | 0 | 0 | 3 |
| Revenue percentage (not acquisition) | 2 | 0 | 0 | 2 |
| Customer count value (not retention) | 2 | 0 | 0 | 2 |
| Generic number (not ACV) | 0 | 1 | 0 | 1 |
| Retention rate value (not count) | 1 | 0 | 0 | 1 |
| Percentage (not expansion metric) | 1 | 0 | 0 | 1 |

## Recommendations for Future Reviews

### High Priority

1. **Fix Snap Data**: Re-fetch correct Snap S-1 filing (CIK verification needed)
2. **DocuSign Manual Review**: Manually examine DocuSign filing for customer metrics not captured by current system

### Medium Priority

3. **Improve Table Parsing**: Many NRR values appear without % suffix due to table cell splitting
4. **Add More SaaS Keywords**: Consider DocuSign-specific terminology

### Low Priority

5. **Consolidate Duplicate Values**: Multiple rows for same metric at different time periods could be deduplicated

## Script Created

A new script `scripts/hrv5_review_decisions.py` was created to automate review decisions based on patterns learned from HRV-3/HRV-4. This script:

1. Applies 10 FP patterns learned from prior reviews
2. Identifies strong TP patterns for acceptance
3. Logs all decisions with rejection reasons
4. Supports dry-run mode for testing

---

**Last Updated**: 2025-12-27
**Reviewer**: Automated + Claude Code
**Hours Spent**: ~2 hours (automated review)
