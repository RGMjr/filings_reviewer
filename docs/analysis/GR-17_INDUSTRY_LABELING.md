# GR-17: Industry Filing Labeling Summary

**Date**: 2025-12-25
**Status**: ✅ COMPLETE
**Task**: Add gold standard labels for fintech, healthcare, and e-commerce filings

## Executive Summary

Successfully added 3 new industry-specific filing labels to `tests/fixtures/goldmine_labels.json`, expanding validation coverage from 4 to 7 filings with diverse industry representation. New filings span fintech (payment/crypto), healthcare tech (telehealth), and e-commerce (merchant platforms).

## Filings Added

| Industry | Company | CIK | Accession Number | Goldmines | Form | Filing Date |
|----------|---------|-----|------------------|-----------|------|-------------|
| Fintech | Coinbase Global, Inc. | 1679788 | 000162828021003168 | 6 | S-1 | Feb 25, 2021 |
| E-commerce | Shopify Inc. | 1594805 | 000119312515129273 | 5 | F-1 | Apr 14, 2015 |
| Healthcare | Teladoc Health, Inc. | 1477449 | 000104746915005109 | 4 | S-1 | May 29, 2015 |

**Total goldmine segments labeled**: 15 new goldmine labels
**Total filings in goldmine_labels.json**: 7 (4 original + 3 new)

## Industry-Specific Patterns Observed

### Fintech (Coinbase)

**Key Metrics**: Monthly Transacting Users (MTU), Trading Volume, Assets on Platform, Verified Users

**Common Patterns**:
- "2.8 million Monthly Transacting Users (MTUs)" - Active usage metric
- "$38 billion in Trading Volume in Q4 2020" - Platform transaction volume
- "$90+ billion in Assets on Platform" - Customer assets under management
- "43 million verified users" - Total registered user base
- Retail vs institutional breakdown for customer segmentation

**Richness Characteristics**:
- High metric density (6+ metrics per goldmine section)
- Strong temporal trends with QoQ and YoY comparisons
- Clear unit economics (Transaction Revenue per MTU)
- Customer segmentation (retail vs institutional)

**False Positive Risks**:
- Historical price charts/tables (contains numbers but not business metrics)
- Risk factor discussions mentioning trading without values
- Regulatory compliance sections with dollar thresholds

**Recommended Pattern Improvements**:
- Add "MTU" and "Monthly Transacting Users" to high-value keyword list
- Add "Trading Volume" with $ or billion context
- Add "Assets on Platform" / "AoP" abbreviation
- Consider crypto-specific terms: "cryptocurrency", "digital assets", "blockchain transactions"

### Healthcare Tech (Teladoc)

**Key Metrics**: Patient visits, Members with access, Subscription revenue, PMPM cost savings

**Common Patterns**:
- "298,833 patient visits in 2014" - Usage/volume metric
- "11 million Members had access to Teladoc" - Member base disclosure
- "$43.5 million in subscription fee revenue" - Revenue tied to member/visit context
- "$21.30 per-member-per-month savings" - Healthcare cost savings/ROI metric

**Richness Characteristics**:
- Strong YoY growth metrics (135% visit growth)
- Unit economics clearly disclosed (PMPM, per-visit costs)
- Member/visit conversion funnel (11M members → 298K visits)
- Healthcare ROI metrics ($9.10 ROI per $1 spent)

**False Positive Risks**:
- Clinical trial data (patient counts but not customer metrics)
- Regulatory approval timelines with dates
- Physician/provider counts vs patient/member counts
- "Visits" in context of site visits, not medical consultations

**Recommended Pattern Improvements**:
- Add "patient visits" and "telehealth visits" as high-value keywords
- Add "members" with healthcare context (not just "subscribers")
- Add PMPM ("per-member-per-month") as unit economics indicator
- Add "consultations", "prescriptions filled" for healthcare engagement
- Distinguish "patient" from clinical trial contexts using surrounding words

### E-commerce (Shopify)

**Key Metrics**: Gross Merchandise Volume (GMV), Merchant count, MRR, Order volume

**Common Patterns**:
- "$3.8 billion in Gross Merchandise Volume" - Platform GMV with growth
- "165,000+ merchants using Shopify" - Customer/seller count
- "Monthly Recurring Revenue" - Subscription business health
- "orders processed" - Platform transaction volume
- Merchant Solutions vs Subscription revenue breakdown

**Richness Characteristics**:
- Multi-year GMV trends (2013: $1.5B → 2014: $3.8B, 153% growth)
- Clear customer segmentation (Subscription vs Merchant Solutions)
- Platform engagement (GMV per merchant, orders per merchant)
- Recurring revenue metrics (MRR growth)

**False Positive Risks**:
- Generic "revenue" without merchant/GMV context
- "Orders" in context of purchase orders for inventory vs platform orders
- "Volume" in shipping/logistics context vs transaction volume
- Table of contents with dollar amounts

**Recommended Pattern Improvements**:
- Add "GMV" and "Gross Merchandise Volume" as Tier 1 keywords
- Add "merchants" in customer count context (not merchant vs customer)
- Add "sellers", "active sellers" for marketplace platforms
- Add "orders processed" / "order volume" with platform context
- Add "take rate" for marketplace monetization metric

## Cross-Industry Observations

### Universal Goldmine Characteristics

1. **Quantitative Disclosure**: All goldmines have specific numeric values, not just mentions
2. **Temporal Context**: YoY or QoQ comparisons showing growth trends
3. **Business Model Linkage**: Metrics tied to revenue or unit economics
4. **Customer Segmentation**: Breakdown by customer type, geography, or cohort

### Industry-Specific Vocabulary Patterns

| Industry | Volume Metrics | Customer Metrics | Engagement Metrics | Revenue Tie-in |
|----------|----------------|------------------|-------------------|----------------|
| Fintech | Trading Volume, TPV | MTU, Verified Users | Transactions, Active accounts | Revenue per MTU, Take rate |
| Healthcare | Patient visits, Consultations | Members, Patients | Visit frequency, Prescriptions | PMPM, Cost savings |
| E-commerce | GMV, Order volume | Merchants, Sellers, Buyers | Orders per merchant, Active listings | Merchant Solutions revenue, Take rate |

### Common False Positive Patterns Across Industries

1. **Risk Factors**: Discusses metrics but no values ("our MTU growth may slow")
2. **Definitions**: Explains what a metric means without current values
3. **Forward-Looking**: Projections without historical actuals
4. **Comparative Context**: Industry benchmarks without company-specific data
5. **Tables of Contents**: Page numbers that look like values

## Recommendations for Pattern Improvements

### High-Priority Additions (Based on GR-17 Labeling)

1. **Fintech Patterns** (for GR-6/GR-7 style tasks):
   - Add MTU ("Monthly Transacting Users", "MTUs") to Tier 1 keywords
   - Add "Trading Volume" with billion/million modifiers
   - Add "Assets on Platform", "AoP", "Assets under management"
   - Add crypto-specific: "cryptocurrency traded", "digital asset volume"

2. **Healthcare Patterns**:
   - Add "patient visits", "telehealth visits", "virtual consultations"
   - Add "members" with healthcare qualifiers (exclude generic membership)
   - Add PMPM, "per-member-per-month" as unit economics signal
   - Add "prescriptions filled", "medication orders" for pharma platforms

3. **E-commerce Enhancement** (Farfetch already partially covered):
   - Strengthen "GMV" weighting (currently covered, but increase richness bonus)
   - Add "active sellers", "active buyers" for two-sided marketplaces
   - Add "orders processed" / "order volume" with platform qualifiers
   - Add "listing" metrics: "active listings", "live listings"

### Pattern Validation Recommendations

Once GR-18 (final validation) is complete:
- Test these 3 new filings through the extraction pipeline
- Compare predicted richness scores against expected_goldmine_sections
- Measure precision/recall for each industry separately
- Identify systematic false positives unique to each industry
- Create industry-specific false positive filters if needed

## Validation Against Acceptance Criteria

✅ **3 new filings added** (1 fintech, 1 healthcare, 1 e-commerce)
✅ **Each filing has 3-10 labeled goldmine segments** (Coinbase: 6, Shopify: 5, Teladoc: 4)
✅ **Each filing has industry field populated** (fintech, ecommerce, healthcare)
✅ **Labels include expected richness scores, metric types, rationale**
✅ **JSON file remains valid** (validated with Python json.load)
✅ **Existing labels unchanged** (Farfetch, Vivint Solar, PropertyGuru, iSpecimen preserved)
✅ **Industry labeling summary document created** (this file)

## Next Steps

1. **GR-18 Validation**: Run full extraction pipeline on these 3 filings to validate labels
2. **Pattern Enhancement**: Implement recommended keyword additions from this analysis
3. **Industry-Specific Testing**: Create separate validation tests for fintech, healthcare, e-commerce
4. **False Positive Analysis**: Build industry-specific false positive filters based on observations

## Data Sources

Research for these labels was conducted using publicly available SEC filings and verified against:

- [Coinbase S-1 (SEC.gov)](https://www.sec.gov/Archives/edgar/data/1679788/000162828021003168/coinbaseglobalincs-1.htm)
- [Shopify F-1 (SEC.gov)](https://www.sec.gov/Archives/edgar/data/1594805/000119312515129273/d863202df1.htm)
- [Teladoc S-1 (SEC.gov)](https://www.sec.gov/Archives/edgar/data/1477449/000104746915005109/a2224910zs-1.htm)
- [Coinbase Investor Relations](https://investor.coinbase.com/financials/sec-filings/default.aspx)
- [Teladoc Investor Relations](https://ir.teladoc.com/financial-info/sec-filings/default.aspx)

---

**Task Completion**: 2025-12-25
**Next Task**: GR-18 (Final validation with industry-diverse filing set)
