# HRV-4: Farfetch Filing Validation Results

**Filing**: Farfetch F-1 (filing_id=31)
**Industry**: Fashion/Luxury E-commerce
**Reviewed**: 2025-12-26
**Gold Standard Metrics**: 67
**Method**: Automated matching via validate_against_gold_standard.py

## Summary Metrics

| Metric | Value |
|--------|-------|
| Review Candidates | 316 |
| True Positives | 33 |
| False Positives | 283 |
| False Negatives | 34 |
| Precision | 10.4% |
| Recall | 49.3% |
| F1 Score | 17.2% |

**Note**: These metrics reflect automated matching between candidates and gold standard entries. The low precision is primarily due to:
1. The system detecting more granular values than the gold standard (e.g., individual table values vs. summary metrics)
2. Metric ID mismatches between system taxonomy and gold standard taxonomy
3. The gold standard focusing on key disclosed metrics while the system finds all potential customer metric candidates

## Comparison with Slack (HRV-3)

| Metric | Slack | Farfetch | Difference |
|--------|-------|----------|------------|
| Gold Standard | 38 | 67 | +29 |
| Candidates | 128 | 316 | +188 |
| True Positives | 28 | 33 | +5 |
| Precision | 21.9% | 10.4% | -11.5pp |
| Recall | 73.7% | 49.3% | -24.4pp |
| F1 Score | 33.7% | 17.2% | -16.5pp |

**Analysis**: Farfetch has lower precision and recall compared to Slack, likely due to:
- Larger filing with more financial tables (316 candidates vs 128)
- More complex metric presentation in e-commerce context
- Different metric taxonomy in fashion/luxury industry

## False Positive Patterns

### Pattern 1: Financial Statement Line Items (cm_gross_margin_overall)
**Frequency**: 113 occurrences (40% of FPs)
**Examples**: "52,420", "67.0%", "55,536", "79.7%"
**Context**: Income statement line items near "Gross profit" keyword
**Why FP**: System finds financial statement values (revenue, cost of revenue, gross profit) that match near gross margin keywords. The gold standard focuses on specific disclosed customer metrics, not general financial figures.
**Fix Recommendation**: Add filter to exclude values from standard financial statement tables (income statement, balance sheet)
**Also seen in Slack?**: Yes - 40 cm_gross_margin_overall FPs

### Pattern 2: GMV-Related Financial Figures (cm_gmv)
**Frequency**: 62 occurrences (22% of FPs)
**Examples**: "$909.8 million", "$585.8 million", "$387,175"
**Context**: Values near "GMV" keyword in financial tables
**Why FP**: Gold standard only includes GMV as a chart reference. System finds all numeric GMV mentions including detailed breakdowns.
**Fix Recommendation**: Consider that GMV in e-commerce filings appears frequently in financial breakdowns - may need industry-specific handling
**Also seen in Slack?**: No - GMV not relevant to Slack

### Pattern 3: Cohort Transaction Metrics (cm_transactions_by_cohort)
**Frequency**: 25 occurrences (9% of FPs)
**Examples**: "800,500", "49.3%", "57.4%", "1.9 million"
**Context**: Values near order/transaction keywords in cohort analysis sections
**Why FP**: System detects transaction-related numbers that aren't in gold standard as standalone metrics
**Fix Recommendation**: Improve cohort metric detection to require specific cohort context patterns
**Also seen in Slack?**: No - different metric taxonomy

### Pattern 4: Customer Count Percentages (cm_active_customers_total)
**Frequency**: 22 occurrences (8% of FPs)
**Examples**: "33.0%", "35.0%", "43.0%"
**Context**: Percentage values near "Active Consumers" keyword
**Why FP**: System picks up growth percentages and margin percentages near customer keywords instead of actual customer counts
**Fix Recommendation**: Filter percentage values for customer count metrics
**Also seen in Slack?**: Partially - similar pattern with different magnitude

### Pattern 5: Deferred Revenue Values (cm_deferred_revenue)
**Frequency**: 16 occurrences (6% of FPs)
**Examples**: "969", "713", "6,646"
**Context**: Values in financial tables near deferred revenue line items
**Why FP**: Not a customer metric in gold standard - system incorrectly classifies as customer-related
**Fix Recommendation**: Remove cm_deferred_revenue from customer metrics or restrict context
**Also seen in Slack?**: No

## False Negative Patterns

### Pattern 1: Number of Orders / Purchase Transactions (cm_purchase_transactions_overall)
**Frequency**: 7 occurrences
**Examples**: "Number of Orders" = 2, 800, 1,260, 1,861, 853.2, 1,305.3, 1,259.7
**Why Missed**: System uses cm_transactions_by_cohort instead of cm_purchase_transactions_overall
**Fix Recommendation**: Add metric ID mapping or alias for "Number of Orders" to match gold standard taxonomy

### Pattern 2: LTV/CAC Ratio Variations (cm_ltv_cac_ratio, cm_ltv_cac_ratio_by_cohort)
**Frequency**: 10 occurrences (4 + 6)
**Examples**: "LTV/CAC ratio" = 1.42, 1.53, 1.77; "LTV/CAC after 6/12/24 months"
**Why Missed**: System uses cm_ltv_to_cac_ratio but gold standard uses cm_ltv_cac_ratio (different format)
**Fix Recommendation**: Normalize metric IDs between system and gold standard (underscore vs hyphen vs "to")

### Pattern 3: Active Customer Growth Metrics (cm_active_customers_growth)
**Frequency**: 4 occurrences
**Examples**: "Active Consumers growth" = 57%, 44%; "up" = 44%, 57%
**Why Missed**: Growth metrics not in system's candidate generation
**Fix Recommendation**: Add growth rate detection for customer metrics

### Pattern 4: Gross Margin by Cohort (cm_gross_margin_by_cohort)
**Frequency**: 4 occurrences
**Examples**: "Order Contribution Margin" = 23%, 26%, 31%, 54%
**Why Missed**: System uses cm_gross_margin_overall but gold standard distinguishes cohort variants
**Fix Recommendation**: Add cohort-specific variant detection

### Pattern 5: Definition-Only Metrics (No Numeric Value)
**Frequency**: 3 occurrences
**Examples**: "new consumers" (definition), "Lifetime Value of a Customer" (definition), "LTV/CAC ratio" (definition)
**Why Missed**: System requires numeric values; gold standard includes definition-only disclosures
**Fix Recommendation**: Add mode for detecting metric definitions without values

## Industry-Specific Patterns

### Fashion/E-commerce Terminology

1. **GMV (Gross Merchandise Value)**: Central metric for marketplace business
   - System correctly identifies GMV keyword
   - Over-generates candidates due to frequent GMV mentions in financial breakdowns

2. **Active Consumers vs Active Customers**: Industry-specific terminology
   - System handles "consumers" keyword
   - Some confusion with customer count vs growth metrics

3. **Order Contribution Margin**: Fashion-specific margin metric
   - Different from standard gross margin
   - Requires cohort-aware detection

4. **Take Rate / Platform Fee**: Marketplace-specific metric
   - 19 FPs suggest over-detection
   - Needs better context filtering

### Table Structure Observations

1. **Dense Financial Tables**: Farfetch includes detailed financial tables with multi-period data
   - High FP rate from table cell values
   - System needs better table structure awareness

2. **Cohort Analysis Charts**: Key metrics in chart format
   - Gold standard includes chart references
   - System doesn't capture chart-based metrics

## Observations

1. **Metric Taxonomy Mismatch**: Significant FN rate due to different metric ID conventions
   - System: cm_ltv_to_cac_ratio, cm_transactions_by_cohort
   - Gold Standard: cm_ltv_cac_ratio, cm_purchase_transactions_overall

2. **Granularity Difference**: System finds fine-grained values; gold standard captures summary metrics

3. **Financial Statement Contamination**: Many FPs from income statement/balance sheet values

4. **Definition Coverage Gap**: System misses definition-only metric disclosures

## Recommendations

### High Priority

1. **Metric ID Normalization**: Create mapping between system and gold standard metric IDs
   - cm_ltv_to_cac_ratio -> cm_ltv_cac_ratio
   - cm_transactions_by_cohort -> cm_purchase_transactions_overall
   - Expected impact: +10-15pp recall

2. **Financial Statement Filter**: Exclude values from standard financial statement tables
   - Detect income statement, balance sheet, cash flow patterns
   - Expected impact: -50-100 FPs, +10-20pp precision

3. **Percentage Filter for Count Metrics**: Don't suggest percentage values for customer count metrics
   - Expected impact: -20-30 FPs

### Medium Priority

4. **Growth Rate Detection**: Add detection for "X growth" patterns
   - Would capture "Active Consumers growth" type metrics
   - Expected impact: +5-10 gold standard matches

5. **Industry-Specific Keyword Weighting**: Adjust for fashion/e-commerce terminology
   - GMV context filtering
   - Take rate context restrictions

### Low Priority

6. **Definition-Only Mode**: Support metric definitions without values
   - Lower priority as these are harder to validate automatically

7. **Chart Detection**: Flag metrics presented as charts
   - Would improve recall for visual metrics

## Validation Script Output

```
============================================================
Validation Report for Farfetch Ltd
(filing_id=31)
============================================================

Gold Standard Entries: 67
Review Candidates: 316

Metrics:
  True Positives:  33
  False Positives: 283
  False Negatives: 34
  Precision:       10.4%
  Recall:          49.3%
  F1 Score:        17.2%
```

## Notes on Validation Methodology

The validation script (`scripts/validate_against_gold_standard.py`) was enhanced during this task to:
1. Normalize company names (Farfetch Ltd vs Farfetch Limited)
2. Handle Inc/Ltd/Corp variations

Matching criteria:
- Metric ID exact match: +2 score
- Exact value match: +3 score
- Close value match (<1%): +2.5 score
- Text variant match: +1 score
- Minimum score of 2 required for TP

---

**Last Updated**: 2025-12-26
**Validation Script Version**: HRV-2 enhanced
**Data Source**: data/gold_standard/golden_set_251218.csv
