# HRV-6: Human Review Validation Analysis

**Date**: 2025-12-30
**Status**: COMPLETE
**Reviewer**: Human + Claude Code

---

## Executive Summary

Completed comprehensive human review validation of Slack (HRV-3) and Farfetch (HRV-4) filings. Results reveal significant differences in system performance across filing types and identify three critical improvement areas.

### Overall Results

| Metric | Slack | Farfetch | Combined |
|--------|-------|----------|----------|
| **Candidates Generated** | 59 | 50 | 109 |
| **Accepted** | 33 | 20 | 53 |
| **Rejected** | 14 | 30 | 44 |
| **Reclassified** | 12 | 0 | 12 |
| **Human Precision** | 76.3% | 40.0% | 59.6% |
| **Gold Standard Recall** | 84.2% | 28.4% | - |

### Key Findings

1. **Slack (Enterprise SaaS)**: Good performance - 76% precision, 84% recall
2. **Farfetch (E-commerce)**: Poor performance - 40% precision, 28% recall
3. **Root cause**: Metric ID taxonomy mismatch, not detection failure
4. **Gap identified**: Chart-based metrics not detected

---

## Section 1: Detailed Results by Filing

### Slack Technologies (Filing 35)

**Review Session**: 2025-12-30
**Gold Standard Entries**: 38 metrics
**Candidates Reviewed**: 59

#### Decision Distribution by Metric

| Metric ID | Accept | Reject | Reclassify | Total | Precision |
|-----------|--------|--------|------------|-------|-----------|
| `cm_customers_period_end` | 11 | 6 | 5 | 22 | 50% |
| `cm_large_customers_period_end` | 10 | 1 | 7 | 18 | 56% |
| `cm_net_revenue_retention` | 9 | 0 | 0 | 9 | 100% |
| `cm_tcv` | 0 | 4 | 0 | 4 | 0% |
| `cm_daily_active_users` | 2 | 1 | 0 | 3 | 67% |
| `cm_revenue_concentration` | 1 | 0 | 0 | 1 | 100% |
| `cm_arr` | 0 | 1 | 0 | 1 | 0% |
| `cm_active_customers_total` | 0 | 1 | 0 | 1 | 0% |

#### Analysis

**High-performing metrics** (100% precision):
- `cm_net_revenue_retention` - Clear keyword "Net Dollar Retention Rate"
- `cm_revenue_concentration` - Specific context

**Problematic metrics**:
- `cm_tcv` (0% precision) - All 4 candidates rejected, TCV values misidentified
- `cm_customers_period_end` (50% precision) - Many values are percentages, not customer counts

**Reclassification patterns** (12 total):
- 5 from `cm_customers_period_end` → likely to more specific metric
- 7 from `cm_large_customers_period_end` → threshold variations

---

### Farfetch Ltd (Filing 31)

**Review Session**: 2025-12-30
**Gold Standard Entries**: 67 metrics
**Candidates Reviewed**: 50

#### Decision Distribution by Metric

| Metric ID | Accept | Reject | Total | Precision |
|-----------|--------|--------|-------|-----------|
| `cm_active_customers_total` | 10 | 5 | 15 | 67% |
| `cm_transactions_by_cohort` | 0 | 15 | 15 | 0% |
| `cm_average_order_value` | 5 | 5 | 10 | 50% |
| `cm_take_rate` | 5 | 5 | 10 | 50% |

#### Analysis

**Critical issue**: `cm_transactions_by_cohort` had 0% precision (all 15 rejected)
- Keyword "Number of Orders" triggers `cm_transactions_by_cohort`
- Gold standard uses `cm_purchase_transactions_overall`
- System IS detecting these values, but wrong metric ID assignment

**Moderate performance**:
- `cm_active_customers_total` (67%) - "Active Consumers" detected correctly
- `cm_average_order_value` / `cm_take_rate` (50%) - Half were financial statement values

---

## Section 2: False Positive Analysis

### Top FP Patterns (Prioritized by Frequency)

#### Pattern 1: Financial Statement Values (High Impact)

**Frequency**: ~35% of FPs
**Affected Filings**: Both Slack and Farfetch

**Examples**:
- GMV values from revenue tables
- Take Rate percentages from financial summaries
- TCV values from contract accounting sections

**Root Cause**: Keywords appear near numbers in financial disclosure sections, not customer metrics sections.

**Recommended Fix**:
- Enhance `filter_financial_statements` in config
- Add section-aware filtering (exclude "Revenue Recognition", "Financial Statements" sections)

---

#### Pattern 2: Percentage Values Misclassified as Counts (Medium Impact)

**Frequency**: ~20% of FPs
**Affected Filings**: Slack

**Examples**:
- "143%" retention rate flagged as `cm_customers_period_end`
- "152%" flagged as customer count

**Root Cause**: Percentage numbers near "customers" keyword get classified as customer counts.

**Recommended Fix**:
- Add format validation: customer count metrics should reject percentage formats
- Enhance `number_format` feature in confidence scoring

---

#### Pattern 3: Table Row Spillover (Medium Impact)

**Frequency**: ~15% of FPs
**Affected Filings**: Farfetch

**Examples**:
- Values from adjacent columns in financial tables
- Numbers from different metrics in same table row

**Root Cause**: Keyword distance doesn't account for table column boundaries.

**Recommended Fix**:
- Enhance table structure parsing in `table_structure.py`
- Add column-aware distance calculation

---

#### Pattern 4: Historical/Comparison Values (Low Impact)

**Frequency**: ~10% of FPs
**Affected Filings**: Both

**Examples**:
- "up from 796,297" - the comparison value, not primary metric
- Prior year values in parentheses

**Root Cause**: Both primary and comparison values trigger detection.

**Recommended Fix**:
- Detect comparison language ("up from", "compared to", "vs")
- Prefer first/primary value in sentence

---

## Section 3: False Negative Analysis

### Top FN Patterns (Prioritized by Impact)

#### Pattern 1: Metric ID Taxonomy Mismatch (Critical)

**Frequency**: ~40% of FNs (Farfetch)
**Impact**: High - Values ARE detected, just wrong classification

**Examples**:
| Gold Standard Metric | System Detected As |
|---------------------|-------------------|
| `cm_purchase_transactions_overall` | `cm_transactions_by_cohort` |
| `cm_active_customers_growth` | Not detected |
| `cm_purchase_transactions_overall_growth` | Not detected |

**Root Cause**:
- YAML config maps "Number of Orders" to `cm_transactions_by_cohort`
- Gold standard uses different metric IDs
- No patterns for growth metrics

**Recommended Fix**:
- Option A: Update YAML to use `cm_purchase_transactions_overall` for "Number of Orders"
- Option B: Update gold standard to use `cm_transactions_by_cohort`
- Add growth metric patterns: "X growth", "increase in X"

---

#### Pattern 2: Chart-Based Metrics (Critical)

**Frequency**: ~15% of FNs
**Impact**: High - Entire metric category missed

**Examples**:
- Slack: `cm_arr` cohort chart (mdaa2.jpg)
- Farfetch: `cm_revenue_by_cohort` GMV chart
- Farfetch: `cm_gross_margin_by_cohort` contribution margin charts

**Root Cause**:
- Candidate generator only processes text
- `cohort_chart_detector.py` exists but not integrated
- Gold standard includes `value = "chart"` entries

**Recommended Fix**:
- Integrate `cohort_chart_detector.py` into candidate generation
- Add chart-based candidate type
- Surface chart candidates in review UI

---

#### Pattern 3: Definition-Only Entries (Medium)

**Frequency**: ~10% of FNs
**Impact**: Medium - Definitions without numeric values

**Examples**:
- `cm_customer` "organization" definition
- `cm_customer` "paid customer" definition
- CAC/LTV definitions without values

**Root Cause**: System requires numeric value to generate candidate.

**Recommended Fix**:
- Add definition-only detection mode
- Generate candidates for definition text without requiring number
- Flag as "definition_only" in features

---

#### Pattern 4: Missing Keyword Patterns (Medium)

**Frequency**: ~15% of FNs
**Impact**: Medium - Keywords not in YAML config

**Examples**:
- "Active Consumers growth" - growth variant missing
- "new consumers" - acquisition variant missing
- "Number of Orders growth" - growth variant missing

**Root Cause**: YAML config doesn't include all keyword variations.

**Recommended Fix**:
- Add growth/change variants: `{metric} growth`, `increase in {metric}`
- Add "new" variants: `new customers`, `new consumers`, `new users`
- Add acquisition variants: `customers acquired`, `users acquired`

---

## Section 4: Industry-Specific Insights

### Enterprise SaaS (Slack)

**Characteristics**:
- Well-defined metrics (ARR, NRR, DAU)
- Clear metric definitions in filings
- Standard SaaS terminology

**Performance**: Good (76% precision, 84% recall)

**Unique Patterns**:
- Heavy use of "Paid Customers" with ARR thresholds
- NRR prominently featured
- Cohort ARR charts common

**Recommendations**:
- Add $100K ARR threshold detection
- Enhance net retention patterns

---

### Fashion E-commerce (Farfetch)

**Characteristics**:
- GMV-centric metrics
- Consumer (not customer) terminology
- Order-based rather than subscription-based

**Performance**: Poor (40% precision, 28% recall)

**Unique Patterns**:
- "Active Consumers" (not customers)
- "Number of Orders" (not transactions)
- Take Rate and AOV prominent
- Cohort GMV charts

**Recommendations**:
- Add "consumer" variants to all customer metrics
- Map "Number of Orders" to correct metric ID
- Enhance GMV vs revenue distinction

---

## Section 5: Prioritized Improvement Recommendations

### Priority 1: Critical (Implement First)

| # | Improvement | Impact | Effort | Files to Modify |
|---|-------------|--------|--------|-----------------|
| 1 | Fix metric ID taxonomy mismatch | +20% Farfetch recall | Low | `config/metric_keywords.yaml` |
| 2 | Integrate chart detection | +15% recall | Medium | `src/review/candidate_generator.py`, `src/web/routes/review.py` |
| 3 | Add growth metric patterns | +10% recall | Low | `config/metric_keywords.yaml` |

### Priority 2: High (Significant Impact)

| # | Improvement | Impact | Effort | Files to Modify |
|---|-------------|--------|--------|-----------------|
| 4 | Enhance financial statement filtering | +15% precision | Medium | `src/review/false_positive_filter.py` |
| 5 | Add format validation (% vs count) | +10% precision | Low | `src/review/confidence_scoring.py` |
| 6 | Add consumer/customer synonyms | +5% recall | Low | `config/metric_keywords.yaml` |

### Priority 3: Medium (Quality Improvements)

| # | Improvement | Impact | Effort | Files to Modify |
|---|-------------|--------|--------|-----------------|
| 7 | Table column-aware matching | +5% precision | High | `src/review/table_structure.py` |
| 8 | Comparison value detection | +3% precision | Medium | `src/review/keyword_matching.py` |
| 9 | Definition-only candidate type | +5% recall | Medium | `src/review/candidate_generator.py` |

---

## Section 6: Updated Validation Metrics

### Before/After Comparison

| Filing | Metric | Before HRV-3/4 | After HRV-3/4 | Change |
|--------|--------|----------------|---------------|--------|
| Slack | Candidates | 111* | 59 | -47% |
| Slack | Human Precision | N/A | 76.3% | Baseline |
| Slack | Gold Standard Recall | 84.2% | 84.2% | No change |
| Farfetch | Candidates | 253* | 50 | -80% |
| Farfetch | Human Precision | N/A | 40.0% | Baseline |
| Farfetch | Gold Standard Recall | 28.4% | 28.4% | No change |

*Previous generation with older code

### Target vs Actual

| Metric | Target | Slack Actual | Farfetch Actual | Status |
|--------|--------|--------------|-----------------|--------|
| Human Precision | ≥80% | 76.3% | 40.0% | ⚠️ Slack close, Farfetch needs work |
| Gold Standard Recall | ≥80% | 84.2% | 28.4% | ✅ Slack meets, ❌ Farfetch critical |
| Candidates/Filing | <100 | 59 | 50 | ✅ Both meet |

---

## Appendix A: Review Decision Export

### Slack Decisions Summary
- **Total Reviewed**: 59
- **Accepts**: 33 (55.9%)
- **Rejects**: 14 (23.7%)
- **Reclassifies**: 12 (20.3%)

### Farfetch Decisions Summary
- **Total Reviewed**: 50
- **Accepts**: 20 (40.0%)
- **Rejects**: 30 (60.0%)
- **Reclassifies**: 0 (0.0%)

---

## Appendix B: Files Modified During Validation

None - this was a read-only validation exercise.

---

## Appendix C: Next Steps

1. **Immediate**: Fix metric ID taxonomy in `config/metric_keywords.yaml`
2. **Short-term**: Integrate chart detection into candidate workflow
3. **Medium-term**: Enhance false positive filtering for financial statements
4. **Long-term**: Add definition-only detection mode

---

## Appendix D: Implementation Status

### Completed (2025-12-30)

**PR1: Fix Metric ID Taxonomy Mismatch**
- Added `cm_purchase_transactions_overall` metric to `config/metric_keywords.yaml`
- Moved "Number of Orders" patterns from `cm_transactions_by_cohort`
- Added SQL INSERT for new metric
- **Result**: Farfetch recall improved from 28.4% to 40.3% (+11.9 pp)

**PR2: Add Growth Metric Patterns**
- Added `cm_active_customers_growth` metric
- Added `cm_purchase_transactions_overall_growth` metric
- Added SQL INSERT statements for both
- **Result**: Farfetch recall improved from 40.3% to 44.8% (+4.5 pp)

### Pending

**PR3: Chart Detection Integration**
- Requires schema migration (`extra_metadata` column)
- Requires re-enrichment pipeline
- Estimated: High effort

---

**Report Generated**: 2025-12-30
**Updated**: 2025-12-30 (implementation status added)
**Data Sources**:
- `review_decisions` table (109 decisions)
- `data/gold_standard/golden_set_251218.csv` (108 entries)
- Human review sessions via web interface
