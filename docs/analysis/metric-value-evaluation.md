# Metric Value Evaluation

**Date**: 2026-04-15
**Scope**: All 28 active metrics in `config/metric_keywords.yaml`
**Purpose**: Determine which metrics reveal genuine customer value disclosure vs. noise

---

## Executive Summary

| Category | Count | Metrics |
|----------|-------|---------|
| **Deprecate** | 3 | cm_arr, cm_mrr, cm_expansion_revenue |
| **Promote to Tier 1** | 3 | cm_large_customers_period_end, cm_new_customers_acquired, cm_customers_period_end_by_tenure |
| **Keep Tier 1** | 12 | (no changes) |
| **Keep Tier 2** | 10 | (no changes) |

After this evaluation, the system has **25 active metrics** (15 Tier 1, 10 Tier 2) and **8 deprecated metrics**.

---

## Evaluation Framework

Each metric was scored on five dimensions:

1. **Customer-level signal**: Does this metric reveal per-customer or per-cohort economic behavior, or is it an aggregate financial number that happens to contain a customer-related keyword?
2. **CMASB mission alignment**: Does it help assess the *quality* of customer metric disclosures in S-1/F-1 filings?
3. **Gold standard evidence**: Coverage across 3 datasets -- filing GS (401 entries), transcript GS (91 entries), presentation GS (282 entries).
4. **Signal-to-noise ratio**: FP rule count in `src/extraction_v2/stages/false_positive_filter.py` (V2) + `src/review/candidate_generator.py` (V1) as a maintenance burden proxy.
5. **Overlap/duplication**: Semantic overlap with other metrics that causes classification confusion.

Value ratings: **HIGH** (clear customer-level economics), **MODERATE** (useful context but not independently insightful), **LOW/NOISE** (aggregate financial measure or unmeasurable).

---

## Recommendation: Deprecate

### cm_arr -- NOISE, Deprecate

| Dimension | Assessment |
|-----------|-----------|
| Customer-level signal | **No.** ARR is the annualized run-rate of total recurring revenue. It tells you nothing about individual customers, cohorts, retention, or unit economics. |
| CMASB alignment | No. ARR is a financial reporting metric, not a customer disclosure quality indicator. |
| GS coverage | Filing=11, Transcript=14, Presentation=28. High frequency -- but frequency does not equal customer-level value. |
| FP burden | V2=9 rules, V1=8 rules. **17 total -- highest of any metric.** Includes arr_tier_threshold, arr_magnitude_cap, arr_tam_context, arr_average_not_total, arr_capital_not_arr, arr_zero_not_valid, and more. |
| Overlap | Customer-relevant ARR cases are already captured: "customers with >$100K ARR" -> cm_large_customers_period_end. "ARR by cohort" -> cm_revenue_by_cohort. |

**Rationale**: ARR falls into the same category as cm_bookings, cm_billings, cm_acv, cm_tcv -- all deprecated on 2026-01-07 as "financial metrics, not customer-specific." The deprecation logic applies identically to ARR. The 17 FP rules represent extreme maintenance cost for a metric that produces aggregate financial noise, not customer-level insight.

The user's intuition is correct: standalone ARR is noise. When ARR is qualified ("$100K+ ARR customers", "ARR by cohort"), those customer-relevant uses are captured by cm_large_customers_period_end and cm_revenue_by_cohort respectively.

### cm_mrr -- NOISE, Deprecate

| Dimension | Assessment |
|-----------|-----------|
| Customer-level signal | **No.** Monthly version of ARR. Same aggregate financial measure. |
| CMASB alignment | No. |
| GS coverage | **Zero across all 3 datasets.** |
| FP burden | 0 rules. The metric is so rarely encountered that no rules were needed. |
| Overlap | Fully subsumed by cm_arr, which is itself recommended for deprecation. |

**Rationale**: Zero gold standard coverage means we have literally no evidence this metric is disclosed in S-1/F-1 filings. Combined with the same "not a customer metric" rationale, this is a clear deprecation.

---

## Recommendation: Promote to Tier 1

### cm_large_customers_period_end -- HIGH VALUE, Promote to Tier 1

| Dimension | Assessment |
|-----------|-----------|
| Customer-level signal | **Yes.** Enterprise customer counts with ARR thresholds ($100K+, $1M+) reveal that a company segments its customer base by value -- a direct indicator of customer-level economic transparency. |
| CMASB alignment | Strong. Threshold-based customer segmentation is a key disclosure quality signal. |
| GS coverage | Filing=**75** (highest of any metric, 6 companies), Presentation=24, Transcript=5. Dominant. |
| FP burden | V2=9, V1=1. Total=10. Moderate and manageable. |
| Overlap | None. Distinct from cm_customers_period_end (total headcount) and cm_active_customers_total (engagement-based). |

**Rationale**: This is the most commonly disclosed metric in the filing gold standard. It directly reveals customer-level value segmentation. Its placement in Tier 2 appears to be a historical accident -- a company that discloses "we have 640 customers with >$100K ARR" is making a richer customer value disclosure than one that simply says "we have 8,800 customers."

---

## Tier 1 Metrics: Keep (13 metrics)

### HIGH VALUE -- No Changes Needed (9 metrics)

**cm_net_revenue_retention**
- Customer signal: Yes -- the gold standard of customer-level economic health
- GS: Filing=58, Presentation=17, Transcript=3
- FP burden: V2=5, V1=2. Manageable
- Action: None

**cm_revenue_concentration**
- Customer signal: Yes -- top-customer revenue share reveals value distribution and risk
- GS: Filing=42, Presentation=24
- FP burden: V2=8, V1=3. Manageable
- Action: None

**cm_customer_acquisition_cost**
- Customer signal: Yes -- fundamental unit economics
- GS: Filing=8, Presentation=6
- FP burden: V2=4, V1=1. Low
- Action: None

**cm_revenue_by_cohort**
- Customer signal: Yes -- CMASB Core Metric (CM3), shows retention/expansion at cohort level
- GS: Filing=32, Presentation=28
- FP burden: V2=1, V1=1. Very low
- Performance: **F1=31%, recall=23%**. Low performance is a recall problem, not a relevance problem
- Action: Prioritize recall improvement (extraction difficulty, not metric irrelevance)

**cm_ltv_to_cac_ratio**
- Customer signal: Yes -- canonical unit economics ratio
- GS: Filing=9, Presentation=6
- FP burden: V2=5, V1=1. Moderate
- Performance: F1=46%, recall=33%
- Action: None

**cm_ltv_to_cac_ratio_by_cohort**
- Customer signal: Yes -- LTV/CAC with temporal dimension
- GS: Filing=9 (all Farfetch)
- FP burden: V2=2, V1=0. Very low
- Action: None

**cm_customer_retention_rate**
- Customer signal: Yes -- logo retention is fundamental
- GS: Filing=2, Presentation=1, Transcript=3. Very low
- FP burden: V2=5, V1=0
- Performance: F1=50%. Low GS coverage reflects that companies often disclose NRR instead
- Action: Expand gold standard coverage

**cm_gross_revenue_retention**
- Customer signal: Yes -- isolates pure retention excluding expansion, complementing NRR
- GS: Filing=3, Presentation=2. Very low
- FP burden: V2=3, V1=0. Low
- Action: Expand gold standard coverage

**cm_lifetime_value_per_customer**
- Customer signal: Yes -- the single most important customer-level economic measure
- GS: Filing=2, Presentation=5
- FP burden: V2=5, V1=4
- SQL status is `experimental` -- should be promoted to `active`
- Action: Promote SQL status

### MODERATE VALUE -- Keep Tier 1 with Caveats (4 metrics)

**cm_expansion_revenue**
- Customer signal: Mixed -- "cross-sell" and "products per customer" are customer-centric, but patterns can catch generic mentions
- GS: **Zero across all 3 datasets**
- FP burden: V2=3, V1=0. Low
- Problem: Despite being Tier 1, we cannot measure extraction quality at all
- Action: **Urgent -- add gold standard entries**

**cm_balance_by_cohort**
- Customer signal: Yes -- cumulative net deposits by cohort (Robinhood-specific)
- GS: Filing=10 (all Robinhood, all chart-based). **F1=0%**
- FP burden: V2=0, V1=0. Zero
- Problem: Single-company, entirely chart-dependent. F1=0% is a chart extraction failure
- Action: Fix chart extraction; concept could generalize to banking/fintech

**cm_gross_margin_by_cohort**
- Customer signal: Yes -- margin improvement over customer lifecycle
- GS: Filing=9 (all Farfetch, all chart-based). **F1=0%**
- FP burden: V2=0, V1=0. Zero
- Problem: Same as cm_balance_by_cohort -- single-company, chart-dependent, F1=0%
- Action: Fix chart extraction

**cm_transactions_by_cohort**
- Customer signal: Yes -- CMASB Core Metric (CM4)
- GS: **Zero across all 3 datasets**
- FP burden: V2=1, V1=0. Minimal
- Problem: Like cm_expansion_revenue, zero GS coverage despite Tier 1 status
- Action: **Add gold standard entries**

---

## Tier 2 Metrics: Keep (12 metrics after deprecations)

### MODERATE VALUE (12 metrics)

**cm_customers_period_end**
- Customer signal: Moderate -- total headcount is context for other metrics (ARPU denominator), not independently insightful
- GS: Filing=53, Presentation=34, Transcript=15. Very high
- FP burden: V2=10, V1=6. **16 total -- second highest**. Reflects extreme keyword ambiguity
- Known issue: MET-1 alias contradiction with cm_active_customers_total
- Action: Resolve MET-1 alias contradiction

**cm_active_customers_total**
- Customer signal: Moderate -- "active" implies engagement criteria, more informative than raw headcount
- GS: Filing=25, Presentation=33, Transcript=3
- FP burden: V2=6, V1=2. Moderate
- Known issue: Same MET-1 alias contradiction
- Action: Resolve MET-1 alias contradiction

**cm_new_customers_acquired**
- Customer signal: Yes -- CMASB Core Metric (CM1), but a flow count, not customer economics
- GS: Filing=4, Presentation=2, Transcript=16
- FP burden: V2=6, V1=3. Moderate
- Note: Could be promoted to Tier 1 for strict CMASB taxonomy alignment (CM1), but keeping Tier 2 is defensible for S-1 focus
- Action: None (consider promotion if CMASB taxonomy alignment is prioritized)

**cm_revenue_per_customer**
- Customer signal: Yes -- ARPU is inherently per-customer
- GS: Filing=23, Presentation=23, Transcript=5
- FP burden: V2=13, V1=3. **16 total -- high**. Justified by importance
- Action: None

**cm_customer_churn_rate**
- Customer signal: Yes -- inverse of retention
- GS: Filing=0, Transcript=4. Rarely disclosed in filings (companies prefer positive framing via retention)
- FP burden: V2=1, V1=0. Minimal cost to keep
- Action: None

**cm_cac_payback_period**
- Customer signal: Yes -- unit economics metric
- GS: Filing=1. Very rare
- FP burden: V2=2, V1=0. Minimal
- Action: None

**cm_monthly_active_users**
- Customer signal: Moderate -- engagement metric, not economics. Primary customer disclosure for consumer/platform companies
- GS: Filing=9, Presentation=11, Transcript=20 (highest in transcripts)
- FP burden: V2=7, V1=0
- Action: None

**cm_daily_active_users**
- Customer signal: Moderate -- same rationale as MAU
- GS: Filing=4, Presentation=1, Transcript=3
- FP burden: V2=7, V1=0
- Action: None

**cm_repeat_purchase_rate**
- Customer signal: Yes -- genuine customer behavior metric for e-commerce
- GS: Filing=3, Presentation=5
- FP burden: V2=4, V1=1. Low
- Action: None

**cm_average_order_value**
- Customer signal: Mixed -- per-transaction, not per-customer (one step removed)
- GS: Filing=6, Presentation=9
- FP burden: V2=11, V1=1. **12 total -- high relative to moderate value**
- Action: Monitor FP burden; consider simplifying rules if maintenance grows

**cm_purchase_transactions_overall**
- Customer signal: Low -- aggregate order count, but non-cohorted sibling of cm_transactions_by_cohort
- GS: Filing=3, Presentation=14
- FP burden: V2=4, V1=0. Low
- Action: None

**cm_customers_period_end_by_tenure**
- Customer signal: Yes -- CMASB Core Metric (CM2), tenure segmentation
- GS: **Zero across all 3 datasets**
- FP burden: V2=1, V1=0. Minimal
- Note: Genuinely rare in S-1 filings. Could promote to Tier 1 for CMASB alignment
- Action: None (minimal cost to keep)

---

## FP Maintenance Burden Ranking

Total FP rule references across V2 filter + V1 candidate generator:

| Rank | Metric | V2 | V1 | Total | Value | Verdict |
|------|--------|----|----|-------|-------|---------|
| 1 | **cm_arr** | 9 | 8 | **17** | Noise | **Deprecate** -- removes highest-burden metric |
| 2 | cm_customers_period_end | 10 | 6 | 16 | Moderate | Keep -- essential context metric |
| 3 | cm_revenue_per_customer | 13 | 3 | 16 | Moderate | Keep -- justified |
| 4 | cm_average_order_value | 11 | 1 | 12 | Moderate | Keep -- monitor |
| 5 | cm_large_customers_period_end | 9 | 1 | 10 | High | Keep -- promote to T1 |
| 6 | cm_revenue_concentration | 8 | 3 | 11 | High | Keep |
| 7 | cm_monthly_active_users | 7 | 0 | 7 | Moderate | Keep |
| 8 | cm_daily_active_users | 7 | 0 | 7 | Moderate | Keep |
| 9 | cm_net_revenue_retention | 5 | 2 | 7 | High | Keep |
| 10 | cm_active_customers_total | 6 | 2 | 8 | Moderate | Keep |

Deprecating cm_arr would remove the system's single highest-maintenance metric.

---

## Gold Standard Coverage Gap Analysis

### Priority 1: Tier 1 metrics with zero coverage

| Metric | Filing | Transcript | Presentation | Urgency |
|--------|--------|-----------|-------------|---------|
| cm_expansion_revenue | 0 | 0 | 0 | **Critical** -- cannot validate T1 metric |
| cm_transactions_by_cohort | 0 | 0 | 0 | **Critical** -- CMASB Core Metric CM4 |

### Priority 2: Tier 1 metrics with very low coverage

| Metric | Filing | Transcript | Presentation | Issue |
|--------|--------|-----------|-------------|-------|
| cm_customer_retention_rate | 2 | 3 | 1 | F1=50%, easily confused with NRR |
| cm_gross_revenue_retention | 3 | 0 | 2 | Rarely disclosed |
| cm_lifetime_value_per_customer | 2 | 0 | 5 | SQL status still `experimental` |

### Priority 3: Tier 2 metrics with zero coverage

| Metric | Filing | Transcript | Presentation | Note |
|--------|--------|-----------|-------------|------|
| cm_customers_period_end_by_tenure | 0 | 0 | 0 | CMASB Core Metric CM2 |
| cm_customer_churn_rate | 0 | 4 | 0 | Has transcript coverage |
| cm_mrr | 0 | 0 | 0 | Recommended for deprecation |

---

## Open Design Issues

### MET-1: cm_customers_period_end vs cm_active_customers_total

Documented in `docs/analysis/MET-1-metric-consistency-audit.md`. These are semantically distinct ("total customers" vs "active customers") but have an alias contradiction in YAML. The recommended resolution is **Option A: Keep as distinct metrics** -- add cm_customers_period_end to SQL and remove the alias declaration. This evaluation assumes they remain distinct.

### cm_deferred_revenue

Exists in SQL with `active` status but has no YAML patterns. Cannot be detected. Should be deprecated in SQL (it is a financial metric, not a customer metric) or removed. Not included in this evaluation because it has no extraction patterns.

---

## Decision Log

Record decisions below. Each recommendation can be accepted, rejected, or modified.

| # | Recommendation | Decision | Notes |
|---|---------------|----------|-------|
| 1 | Deprecate cm_arr | agreed | |
| 2 | Deprecate cm_mrr | agreed | |
| 3 | Promote cm_large_customers_period_end to Tier 1 | agreed | |
| 4 | Add GS entries for cm_expansion_revenue (T1, zero coverage) | do not agree - deprecate| no evidence that anyone has disclosed this |
| 5 | Add GS entries for cm_transactions_by_cohort (T1, zero coverage) | agreed | |
| 6 | Expand GS for cm_customer_retention_rate (T1, 2 entries) | agreed | |
| 7 | Expand GS for cm_gross_revenue_retention (T1, 3 entries) | agrees | this may be a rare metric |
| 8 | Promote cm_lifetime_value_per_customer SQL status to active | agreed | |
| 9 | Resolve MET-1 alias contradiction | agreed | |
| 10 | Deprecate cm_deferred_revenue in SQL | agreed | this should not be a metric we track |
| 11 | Consider promoting cm_new_customers_acquired to Tier 1 (CMASB CM1) | agreed | |
| 12 | Consider promoting cm_customers_period_end_by_tenure to Tier 1 (CMASB CM2) | agreed | |

---

*Source files: `config/metric_keywords.yaml`, `data/gold_standard/golden_set_260408.csv`, `data/gold_standard/v2_baseline.json`, `src/extraction_v2/stages/false_positive_filter.py`, `src/review/candidate_generator.py`, `docs/analysis/MET-1-metric-consistency-audit.md`*
