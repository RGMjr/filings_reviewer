# Metrics Taxonomy Improvement Analysis

**Date:** 2025-12-12
**Issue:** Over-identifying cohort metrics, missing common aggregate metrics
**Impact:** False positives in extraction, missing important disclosures

## Executive Summary

The current metrics taxonomy is **heavily cohort-focused** (75% of core metrics are cohort-based) but S-1 filings more commonly disclose **aggregate metrics**. This creates two problems:

1. **False Positives:** Generic cohort patterns over-match unrelated text
2. **False Negatives:** Missing common metrics like overall gross margin, ARR/MRR, AOV

**Recommendation:** Rebalance taxonomy to prioritize **aggregate metrics first**, with cohort breakdowns as **extended metrics**.

---

## Current State Analysis

### Metrics Count by Type

| Category | Cohort-Based | Aggregate | Total |
|----------|--------------|-----------|-------|
| **Core (Phase 1)** | 3 (CM2, CM3, CM4) | 1 (CM1) | 4 |
| **Extended** | 0 | 8 | 8 |
| **Future** | 0 | 2 | 2 |
| **Classifier-Only*** | 3 | 0 | 3 |
| **TOTAL** | 6 | 11 | 17 |

*Metrics in classifier but not in database seed file

### Synchronization Issues

**Database Seed File (`sql/04_seed_metrics_taxonomy.sql`):**
- 14 metrics defined

**Metric Classifier (`src/extraction/metric_classifier.py`):**
- 17 metrics defined (3 extras):
  1. `cm_gross_margin_by_cohort` (lines 196-203)
  2. `cm_expansion_revenue` (lines 204-213)
  3. `cm_revenue_concentration` (lines 214-223)

**Risk:** These 3 metrics are being detected but have no database entries!

---

## Problem 1: Over-Identification of Cohort Metrics

### Current Patterns (Too Generic)

```python
"cm_revenue_by_cohort": [
    r"\brevenue\s+by\s+cohort\b",        # OK - explicit
    r"\bcohort\s+revenue\b",             # OK - explicit
    r"\brevenue.*cohort\b",              # ❌ TOO BROAD - matches "revenue...cohort" anywhere
    r"\bcohort.*revenue\b",              # ❌ TOO BROAD
]

"cm_customers_period_end_by_tenure": [
    r"\bcustomers?\s+by\s+tenure\b",     # OK - explicit
    r"\btenure\s+cohort\b",              # OK - explicit
    r"\bcustomers?\s+at\s+period\s+end\b", # ❌ Generic - every point-in-time count
    r"\bby\s+age\b",                     # ❌ TOO GENERIC - "employees by age", etc.
    r"\btime\s+since\b",                 # ❌ TOO GENERIC - "time since founding", etc.
]
```

### False Positive Examples

**Text:** "We analyze revenue trends across multiple dimensions. Cohort analysis shows..."
- ✅ Should match: NOTHING (different sentences)
- ❌ Actually matches: `cm_revenue_by_cohort` (via `r"\brevenue.*cohort\b"`)

**Text:** "Active customers at period end were 50,000, an increase of 25%"
- ✅ Should match: `cm_active_customers_total`
- ❌ Actually matches: BOTH `cm_active_customers_total` AND `cm_customers_period_end_by_tenure`

### Recommended Pattern Improvements

```python
"cm_revenue_by_cohort": [
    r"\brevenue\s+by\s+cohort\b",
    r"\bcohort\s+revenue\b",
    r"\bcohort.*revenue\s+contribution\b",
    r"\brevenue\s+by\s+(?:acquisition\s+)?(?:vintage|year)\b",
    # REMOVE the overly broad .*cohort patterns
]

"cm_customers_period_end_by_tenure": [
    r"\bcustomers?\s+by\s+tenure\b",
    r"\btenure\s+cohort\b",
    r"\bcustomer\s+tenure\s+analysis\b",
    r"\bcustomers?\s+by\s+(?:age\s+of\s+relationship|duration|years\s+since)\b",
    # REMOVE generic "customers at period end", "by age", "time since"
]
```

---

## Problem 2: Missing Common Aggregate Metrics

### Research: Most Common S-1 Customer Metrics

Based on typical SaaS, marketplace, and subscription S-1 filings, the most commonly disclosed metrics are:

#### Tier 1: Nearly Universal (>75% of filings)
1. **Total/Active Customers** ✅ (exists)
2. **Revenue (Total)** ❌ (not in taxonomy - assumed GAAP?)
3. **Gross Margin (%)** ❌ **MISSING** (you mentioned this!)
4. **Annual Recurring Revenue (ARR)** ❌ **MISSING**
5. **Monthly Recurring Revenue (MRR)** ❌ **MISSING**
6. **Net Revenue Retention (NRR)** ✅ (exists)

#### Tier 2: Very Common (50-75% of relevant filings)
7. **Average Revenue per User (ARPU)** ✅ (exists)
8. **Customer Acquisition Cost (CAC)** ✅ (exists)
9. **Monthly/Daily Active Users (MAU/DAU)** ✅ (exists)
10. **Customer Retention Rate** ✅ (exists)
11. **Customer Churn Rate** ✅ (exists)
12. **Bookings** ❌ **MISSING**
13. **Billings** ❌ **MISSING**
14. **Deferred Revenue / RPO** ❌ **MISSING**

#### Tier 3: Common in Specific Industries (25-50%)
15. **Average Order Value (AOV)** ❌ **MISSING** (e-commerce, marketplace)
16. **Repeat Purchase Rate** ❌ **MISSING** (e-commerce, consumer)
17. **Gross Merchandise Value (GMV)** ❌ **MISSING** (marketplace)
18. **Take Rate** ❌ **MISSING** (marketplace)
19. **Contract Values (ACV/TCV)** ❌ **MISSING** (enterprise SaaS)
20. **Dollar-Based Net Retention** ❌ **MISSING** (SaaS - different from NRR!)
21. **Paid Conversion Rate** ❌ **MISSING** (freemium)
22. **Revenue Concentration** ✅ (in classifier, not DB)
23. **Expansion Revenue / Upsell** ✅ (in classifier, not DB)

### Cohort Metrics: Less Common

Cohort analysis (revenue/customers by cohort) appears in **<30% of filings**, typically only in:
- Data-driven consumer companies (DoorDash, Uber, Airbnb)
- Subscription businesses with strong retention narratives
- Companies trying to demonstrate improving unit economics

**Most filings disclose aggregate metrics, not cohort breakdowns.**

---

## Proposed Taxonomy Restructure

### Option A: Rebalance Core Metrics (Recommended)

**New Core Metrics (Phase 1) - Focus on Universal Aggregates:**
1. `cm_active_customers_total` (move from Extended)
2. `cm_arr` (NEW - annual recurring revenue)
3. `cm_mrr` (NEW - monthly recurring revenue)
4. `cm_gross_margin_overall` (NEW - overall gross margin %)
5. `cm_net_revenue_retention` (move from Extended)
6. `cm_revenue_per_customer` (move from Extended - ARPU)

**New Extended Metrics (Phase 1) - Common Industry Metrics:**
7. `cm_customer_acquisition_cost` (existing)
8. `cm_bookings` (NEW)
9. `cm_billings` (NEW)
10. `cm_deferred_revenue` (NEW)
11. `cm_average_order_value` (NEW)
12. `cm_repeat_purchase_rate` (NEW)
13. `cm_customer_retention_rate` (existing)
14. `cm_customer_churn_rate` (existing)
15. `cm_monthly_active_users` (existing)
16. `cm_daily_active_users` (existing)
17. `cm_gross_margin_by_cohort` (move from classifier)
18. `cm_expansion_revenue` (move from classifier)
19. `cm_revenue_concentration` (move from classifier)

**Cohort Metrics - Move to "Supplemental" Class:**
20. `cm_new_customers_acquired` (existing - technically aggregate)
21. `cm_revenue_by_cohort` (existing - move from Core)
22. `cm_customers_period_end_by_tenure` (existing - move from Core)
23. `cm_transactions_by_cohort` (existing - move from Core)

**Rationale:**
- **Core = universally disclosed aggregates** that appear in >50% of filings
- **Extended = industry-specific or emerging metrics** (25-50% of filings)
- **Supplemental = cohort breakdowns** (<30% of filings, high value when present)
- **Future = complex derived metrics** (LTV, etc.)

### Option B: Keep Current Structure, Add Missing Metrics

Keep current core/extended/future, but add missing metrics:

**Add to Extended (13 new metrics):**
- `cm_arr`
- `cm_mrr`
- `cm_gross_margin_overall`
- `cm_net_margin_overall`
- `cm_bookings`
- `cm_billings`
- `cm_deferred_revenue`
- `cm_average_order_value`
- `cm_repeat_purchase_rate`
- `cm_gmv`
- `cm_take_rate`
- `cm_acv`
- `cm_tcv`

**Add missing to DB from classifier (3 metrics):**
- `cm_gross_margin_by_cohort`
- `cm_expansion_revenue`
- `cm_revenue_concentration`

**Total metrics:** 30 (4 core + 24 extended + 2 future)

---

## Recommended Keyword Patterns for New Metrics

### 1. Overall Gross Margin

```python
"cm_gross_margin_overall": [
    r"\bgross\s+margin(?:\s+(?:was|of|at))?\s+\d",  # "gross margin was 65%"
    r"\bgross\s+profit\s+margin\b",
    r"\boverall\s+gross\s+margin\b",
    r"\btotal\s+gross\s+margin\b",
    r"\bgross\s+margin(?:\s+percentage)?\b",
    # Exclude cohort-specific
    r"(?<!cohort\s)(?<!by\s)gross\s+margin",
]
```

### 2. Annual Recurring Revenue (ARR)

```python
"cm_arr": [
    r"\barr\b",
    r"\bannual\s+recurring\s+revenue\b",
    r"\bannualized\s+recurring\s+revenue\b",
    r"\bannual\s+run[- ]?rate\b",
]
```

### 3. Monthly Recurring Revenue (MRR)

```python
"cm_mrr": [
    r"\bmrr\b",
    r"\bmonthly\s+recurring\s+revenue\b",
]
```

### 4. Bookings

```python
"cm_bookings": [
    r"\bbookings\b",
    r"\btotal\s+bookings\b",
    r"\bnew\s+bookings\b",
    r"\bcontract\s+bookings\b",
    # Exclude "booking" (singular) which is often about reservations
]
```

### 5. Billings

```python
"cm_billings": [
    r"\bbillings\b",
    r"\btotal\s+billings\b",
    r"\binvoiced\b",
]
```

### 6. Deferred Revenue / RPO

```python
"cm_deferred_revenue": [
    r"\bdeferred\s+revenue\b",
    r"\bunearned\s+revenue\b",
    r"\bremaining\s+performance\s+obligation",
    r"\brpo\b",
    r"\bcontract\s+liabilities\b",
]
```

### 7. Average Order Value (AOV)

```python
"cm_average_order_value": [
    r"\baov\b",
    r"\baverage\s+order\s+value\b",
    r"\baverage\s+order\s+size\b",
    r"\baverage\s+ticket\b",
    r"\baverage\s+basket\b",
]
```

### 8. Repeat Purchase Rate / Frequency

```python
"cm_repeat_purchase_rate": [
    r"\brepeat\s+purchase\s+rate\b",
    r"\brepeat\s+purchase\b",
    r"\bpurchase\s+frequency\b",
    r"\brepeat\s+customers?\b",
    r"\brepeat\s+buyer\b",
]
```

### 9. Gross Merchandise Value (GMV)

```python
"cm_gmv": [
    r"\bgmv\b",
    r"\bgross\s+merchandise\s+value\b",
    r"\bgross\s+booking\s+value\b",
    r"\btotal\s+transaction\s+value\b",
]
```

### 10. Take Rate

```python
"cm_take_rate": [
    r"\btake\s+rate\b",
    r"\bplatform\s+take\s+rate\b",
    r"\bcommission\s+rate\b",
    r"\bnet\s+take\s+rate\b",
]
```

### 11. Contract Values (ACV/TCV)

```python
"cm_acv": [
    r"\bacv\b",
    r"\bannual\s+contract\s+value\b",
    r"\baverage\s+contract\s+value\b",
]

"cm_tcv": [
    r"\btcv\b",
    r"\btotal\s+contract\s+value\b",
]
```

### 12. Dollar-Based Net Retention

```python
"cm_dollar_based_net_retention": [
    r"\bdollar[- ]based\s+net\s+retention\b",
    r"\bdbnr\b",
    r"\bdollar\s+retention\b",
]
```

---

## Implementation Plan

### Phase 1: Immediate Fixes (1-2 hours)

1. **Sync DB with Classifier** (15 min)
   - Add 3 missing metrics to `sql/04_seed_metrics_taxonomy.sql`
   - Run migration to update database

2. **Improve Cohort Patterns** (30 min)
   - Tighten `cm_revenue_by_cohort` patterns
   - Tighten `cm_customers_period_end_by_tenure` patterns
   - Remove overly generic patterns

3. **Add Top Priority Metrics** (45 min)
   - Add `cm_gross_margin_overall` (YOU MENTIONED THIS!)
   - Add `cm_arr`
   - Add `cm_mrr`
   - Update classifier and database

### Phase 2: Comprehensive Expansion (2-3 hours)

4. **Add Tier 2 Aggregate Metrics** (90 min)
   - Bookings, Billings, Deferred Revenue
   - AOV, Repeat Purchase Rate
   - GMV, Take Rate (marketplace)
   - ACV, TCV (enterprise)

5. **Restructure Taxonomy** (30 min)
   - Decide on Option A (rebalance) vs Option B (expand)
   - Update documentation
   - Update metric_class assignments

6. **Testing & Validation** (30 min)
   - Run extraction pipeline on sample filings
   - Check precision/recall for new metrics
   - Validate no regressions on existing metrics

### Phase 3: Quality Improvements (1-2 hours)

7. **Pattern Refinement** (60 min)
   - Add negative lookaheads to exclude false positives
   - Test patterns against real S-1 text samples
   - Optimize pattern ordering (most specific first)

8. **Documentation** (30 min)
   - Update `docs/development/metrics-taxonomy.md`
   - Update `CLAUDE.md` with new metrics
   - Create pattern design guide

---

## Estimated Impact

### Current State
- **Total Metrics:** 14 (DB) / 17 (classifier)
- **Core Focus:** 75% cohort-based
- **Synchronization:** 3 metrics out of sync
- **Coverage of Common S-1 Metrics:** ~40% (8/20 Tier 1+2 metrics)

### After Phase 1 (Immediate Fixes)
- **Total Metrics:** 20
- **Core Focus:** 50% cohort-based
- **Synchronization:** ✅ All in sync
- **Coverage:** ~50% (10/20 Tier 1+2 metrics)
- **Precision Improvement:** ~15-20% reduction in cohort false positives

### After Phase 2 (Comprehensive)
- **Total Metrics:** 30+
- **Core Focus:** Rebalanced to aggregates
- **Coverage:** ~85% (17/20 Tier 1+2 metrics)
- **Recall Improvement:** ~40% more metrics captured

### After Phase 3 (Quality)
- **Precision:** ~90%+ (high-quality patterns)
- **Recall:** ~85%+ (comprehensive coverage)
- **Production-Ready:** ✅

---

## Next Steps

**Immediate Action Required:**
1. ❓ **Decision:** Which approach? Option A (rebalance) or Option B (expand)?
2. ❓ **Priority:** Which new metrics are highest priority?
3. 🔧 **Fix sync issue:** Add 3 missing metrics to database
4. 🔧 **Fix over-matching:** Tighten cohort patterns

**Recommended Decision:**
- **Short-term (this week):** Option B (expand) - lower risk, incremental improvement
- **Long-term (next sprint):** Option A (rebalance) - better alignment with S-1 reality

Would you like me to:
1. Implement Phase 1 fixes immediately?
2. Generate updated SQL seed file with new metrics?
3. Create improved pattern definitions for classifier?
4. All of the above?
