# MET-1: Metric Consistency Audit Report

**Generated**: 2026-01-07
**Task ID**: MET-1
**Phase**: 1 (Audit)
**Status**: Awaiting User Review

---

## Executive Summary

| Category | Count | Severity |
|----------|-------|----------|
| **Total Canonical Metrics (YAML)** | 32 | - |
| **Total SQL Metrics** | 32 | - |
| **CRITICAL: YAML-SQL Mismatch** | 2 | HIGH |
| **CRITICAL: Alias Conflict** | 1 | HIGH |
| **Missing YAML Patterns** | 1 | MEDIUM |
| **METRIC_NAME_MAPPING Gaps** | 12 | LOW |
| **Test Fixture Issues** | 38+ | LOW |

### Critical Issues Requiring Decision

1. **`cm_customers_period_end` exists in YAML but NOT in SQL** - The YAML has this as the primary metric with alias `cm_active_customers_total`, but SQL only has `cm_active_customers_total` as a standalone metric.

2. **Alias Contradiction**: `cm_active_customers_total` is:
   - An **alias** of `cm_customers_period_end` in YAML (line 89-90)
   - A **standalone metric** with its own patterns in YAML (line 182-196)
   - A **standalone metric** in SQL with `status = 'active'`

3. **`cm_deferred_revenue`** exists in SQL but has NO patterns in YAML.

---

## Section 1: Canonical Metric List (YAML - Source of Truth)

### Active Metrics (27)

| Metric ID | Has Patterns | Aliases | Notes |
|-----------|--------------|---------|-------|
| `cm_new_customers_acquired` | Yes | - | |
| `cm_customers_period_end` | Yes | `cm_active_customers_total` | **NOT IN SQL** |
| `cm_large_customers_period_end` | Yes | - | |
| `cm_customers_period_end_by_tenure` | Yes | - | |
| `cm_revenue_by_cohort` | Yes | - | |
| `cm_transactions_by_cohort` | Yes | - | |
| `cm_purchase_transactions_overall` | Yes | - | |
| `cm_active_customers_total` | Yes | - | Alias conflict |
| `cm_revenue_per_customer` | Yes | - | |
| `cm_customer_acquisition_cost` | Yes | - | |
| `cm_cac_payback_period` | Yes | - | |
| `cm_customer_retention_rate` | Yes | - | |
| `cm_customer_churn_rate` | Yes | - | |
| `cm_net_revenue_retention` | Yes | - | |
| `cm_gross_revenue_retention` | Yes | - | |
| `cm_monthly_active_users` | Yes | - | |
| `cm_daily_active_users` | Yes | - | |
| `cm_gross_margin_by_cohort` | Yes | - | |
| `cm_arr` | Yes | - | |
| `cm_mrr` | Yes | - | |
| `cm_expansion_revenue` | Yes | - | |
| `cm_revenue_concentration` | Yes | - | |
| `cm_average_order_value` | Yes | - | |
| `cm_repeat_purchase_rate` | Yes | - | |
| `cm_lifetime_value_per_customer` | Yes | - | |
| `cm_ltv_to_cac_ratio` | Yes | - | |
| `cm_ltv_to_cac_ratio_by_cohort` | Yes | - | Added 2026-01-07 |

### Deprecated Metrics (5)

| Metric ID | YAML Status | SQL Status | Notes |
|-----------|-------------|------------|-------|
| `cm_bookings` | DEPRECATED 2026-01-07 | deprecated | Sync OK |
| `cm_billings` | DEPRECATED 2026-01-07 | deprecated | Sync OK |
| `cm_gmv` | DEPRECATED 2026-01-07 | deprecated | Sync OK |
| `cm_acv` | DEPRECATED 2026-01-07 | deprecated | Sync OK |
| `cm_tcv` | DEPRECATED 2026-01-07 | deprecated | Sync OK |

---

## Section 2: SQL vs YAML Comparison

### In SQL but NOT in YAML (2)

| SQL Metric ID | SQL Status | Issue |
|---------------|------------|-------|
| `cm_deferred_revenue` | active | **NO YAML PATTERNS** - Cannot be detected |
| `cm_gross_margin_overall` | deprecated | Intentionally removed (not customer-specific) |

### In YAML but NOT in SQL (1)

| YAML Metric ID | Issue | Recommendation |
|----------------|-------|----------------|
| `cm_customers_period_end` | Has alias to `cm_active_customers_total`, but SQL only has the alias as standalone | **Requires Decision** (see Design Issue below) |

### Status Mismatches (0)

All deprecated metrics are correctly synchronized between YAML and SQL.

---

## Section 3: METRIC_NAME_MAPPING Audit

The `METRIC_NAME_MAPPING` dict previously in `src/extraction/value_extractor.py` (removed in v2.7) mapped LLM-returned names to canonical IDs. In V2, name normalization is handled via the `aliases` field in `config/metric_keywords.yaml` and loaded by `src/shared/keyword_config.py`.

### Coverage Summary

| Category | Count |
|----------|-------|
| Total unique target metric IDs | 20 |
| Canonical metrics with LLM mapping | 20 |
| Canonical metrics WITHOUT LLM mapping | 12 |

### Metrics Without LLM Mapping

These metrics have no entries in METRIC_NAME_MAPPING. This may be intentional if LLM extraction is not expected for these metrics:

| Metric ID | Notes |
|-----------|-------|
| `cm_customers_period_end` | **CRITICAL**: This is the canonical ID but mapping points to `cm_active_customers_total` |
| `cm_purchase_transactions_overall` | No mapping |
| `cm_gross_margin_by_cohort` | No mapping |
| `cm_arr` | No mapping |
| `cm_mrr` | No mapping |
| `cm_expansion_revenue` | No mapping |
| `cm_revenue_concentration` | No mapping |
| `cm_average_order_value` | No mapping |
| `cm_repeat_purchase_rate` | No mapping |
| `cm_bookings` | Deprecated - mapping not needed |
| `cm_billings` | Deprecated - mapping not needed |
| `cm_gmv` | Deprecated - mapping not needed |

### Mapping to Non-Canonical IDs

All METRIC_NAME_MAPPING target values are valid metric IDs. No issues found.

---

## Section 4: Test Fixture Audit

Found 38+ unique non-canonical metric IDs used in tests.

### Clearly Wrong (Should Fix) - 15 IDs

These are typos or incorrect suffixes:

| Test ID | Occurrences | Should Be | Priority |
|---------|-------------|-----------|----------|
| `cm_mau` | 38 | `cm_monthly_active_users` | LOW |
| `cm_dau` | 34 | `cm_daily_active_users` | LOW |
| `cm_active_users_total` | 20 | `cm_active_customers_total` | MEDIUM |
| `cm_churn_rate` | 14 | `cm_customer_churn_rate` | LOW |
| `cm_nrr` | 13 | `cm_net_revenue_retention` | LOW |
| `cm_cac` | 11 | `cm_customer_acquisition_cost` | LOW |
| `cm_active_users_daily` | 7 | `cm_daily_active_users` | LOW |
| `cm_ltv` | 5 | `cm_lifetime_value_per_customer` | LOW |
| `cm_arpu` | 5 | `cm_revenue_per_customer` | LOW |
| `cm_new_customers` | 4 | `cm_new_customers_acquired` | LOW |
| `cm_retention_rate` | 2 | `cm_customer_retention_rate` | LOW |
| `cm_net_retention` | 2 | `cm_net_revenue_retention` | LOW |
| `cm_ltv_cac_ratio` | 2 | `cm_ltv_to_cac_ratio` | LOW |
| `cm_grr` | 2 | `cm_gross_revenue_retention` | LOW |
| `cm_gross_retention` | 2 | `cm_gross_revenue_retention` | LOW |

### Intentional Test IDs (No Fix Needed) - 8 IDs

These appear to be intentionally invalid for testing error handling:

| Test ID | Occurrences | Purpose |
|---------|-------------|---------|
| `cm_unknown_metric` | 4 | Testing unknown metric handling |
| `cm_nonexistent` | 2 | Testing non-existent metric handling |
| `cm_old` | 2 | Testing deprecated/old metrics |
| `cm_custom_metric` | 2 | Testing custom metrics |
| `cm_missing` | 1 | Testing missing metrics |
| `cm_unknown` | 1 | Testing unknown metrics |
| `cm_unknown_metric_without_rules` | 1 | Testing rule absence |
| `cm_fp` | 1 | Testing false positives |

### Ambiguous/Context-Dependent - 15+ IDs

These may be intentionally abbreviated for readability or testing specific scenarios:

| Test ID | Occurrences | Notes |
|---------|-------------|-------|
| `cm_revenue` | 34 | Generic revenue - may be intentional |
| `cm_total_customers` | 11 | Ambiguous - could map to either period_end metric |
| `cm_retention` | 9 | Ambiguous - customer or revenue retention? |
| `cm_churn` | 9 | Ambiguous - abbreviated form |
| `cm_active_users` | 7 | Ambiguous - MAU/DAU/total? |
| `cm_subscribers_total` | 6 | Not canonical - subscriber vs customer |
| `cm_customers` | 3 | Too generic |
| `cm_active_customers` | 3 | Missing `_total` suffix |
| `cm_active` | 3 | Too short |
| `cm_large_customers` | 2 | Missing `_period_end` suffix |
| `cm_customer_count` | 2 | Not canonical form |
| `cm_user_growth_rate` | 4 | Removed metric (growth rates not tracked) |
| `cm_revenue_growth` | 2 | Removed metric |

---

## Section 5: Missing Patterns Check

### Active SQL Metrics Without YAML Patterns (1)

| Metric ID | SQL Status | Issue |
|-----------|------------|-------|
| `cm_deferred_revenue` | active | **Cannot be detected** - no YAML patterns exist |

### Recommendation

Either:
1. Add patterns to YAML for `cm_deferred_revenue`
2. Or change SQL status to `deprecated` if not needed

---

## Section 6: Design Issue - Alias Contradiction

### The Problem

`cm_active_customers_total` has a dual identity:

**As an Alias (YAML line 89-90):**
```yaml
cm_customers_period_end:
  aliases:
    - cm_active_customers_total
  patterns:
    - '\bpaid\s+customers?\b'
    - '\btotal\s+customers?\b'  # moved from cm_active_customers_total
    ...
```

**As a Standalone Metric (YAML line 182-196):**
```yaml
cm_active_customers_total:
  patterns:
    - '\bactive\s+customers?\b'
    - '\bactive\s+users?\b'
    ...
```

**In SQL:**
- `cm_active_customers_total` is a standalone metric with `status = 'active'`
- `cm_customers_period_end` **does not exist** in SQL

### Semantic Analysis

| Concept | Metric | Definition |
|---------|--------|------------|
| **Period-End Count** | `cm_customers_period_end` | Stock count of customers at period end (regardless of activity) |
| **Active Count** | `cm_active_customers_total` | Engagement-based count (logged in, made purchase, etc.) |

These are semantically **distinct**:
- "We have 10,000 total customers" (period-end count)
- "We have 8,000 active customers" (activity-based)

### The Current Behavior

1. The YAML alias declaration says: "cm_active_customers_total is equivalent to cm_customers_period_end for gold standard validation"
2. But the YAML also defines `cm_active_customers_total` as its own metric with different patterns
3. The SQL only has `cm_active_customers_total`, not `cm_customers_period_end`

### Recommendations (Choose One)

**Option A: Keep as Distinct Metrics**
- Remove the alias declaration from `cm_customers_period_end`
- Add `cm_customers_period_end` to SQL
- Update gold standard files to use correct canonical IDs
- Update METRIC_NAME_MAPPING to point to correct metric

**Option B: Merge into Single Metric**
- Keep `cm_active_customers_total` as the canonical ID
- Move all patterns from `cm_customers_period_end` into it
- Remove `cm_customers_period_end` from YAML entirely
- Add `cm_customers_period_end` as an alias to `cm_active_customers_total`

**Option C: Keep Current Hybrid (Not Recommended)**
- Accept the contradiction
- Risk: Extraction may produce inconsistent results

### Impact Assessment

| Option | Files Changed | Gold Standard Impact | Risk |
|--------|---------------|---------------------|------|
| A (Distinct) | YAML, SQL, metric_keywords.yaml aliases, tests | Gold standard updates needed | LOW |
| B (Merge) | YAML only | None (alias handles it) | LOW |
| C (Keep) | None | None | MEDIUM |

---

## Section 7: Recommended Fixes (Prioritized)

### Priority 1: Critical (Must Fix)

| Issue | Fix | Impact |
|-------|-----|--------|
| **Alias Contradiction** | Requires design decision (see Section 6) | High |
| **Missing cm_customers_period_end in SQL** | Add INSERT or resolve via Option B | High |
| **cm_deferred_revenue has no patterns** | Add YAML patterns or deprecate in SQL | Medium |

### Priority 2: Medium (Should Fix)

| Issue | Fix | Impact |
|-------|-----|--------|
| `cm_active_users_total` in tests (20 uses) | Change to `cm_active_customers_total` | Low |
| Missing METRIC_NAME_MAPPING entries | Add entries for active metrics | Low |

### Priority 3: Low (Nice to Have)

| Issue | Fix | Impact |
|-------|-----|--------|
| Abbreviated test IDs (cm_mau, cm_dau, etc.) | Leave as-is or standardize | Very Low |
| Ambiguous test IDs | Leave as-is (may be intentional) | Very Low |

---

## Appendix A: Complete Metric ID Cross-Reference

| Metric ID | YAML | SQL | MAPPING | Tests |
|-----------|------|-----|---------|-------|
| cm_acv | Yes (deprecated) | Yes (deprecated) | No | 14 |
| cm_active_customers_total | Yes | Yes | Yes | 169 |
| cm_arr | Yes | Yes | No | 169 |
| cm_average_order_value | Yes | Yes | No | 9 |
| cm_billings | Yes (deprecated) | Yes (deprecated) | No | 9 |
| cm_bookings | Yes (deprecated) | Yes (deprecated) | No | 10 |
| cm_cac_payback_period | Yes | Yes | Yes | 0 |
| cm_customer_acquisition_cost | Yes | Yes | Yes | 40 |
| cm_customer_churn_rate | Yes | Yes | Yes | 32 |
| cm_customer_retention_rate | Yes | Yes | Yes | 26 |
| cm_customers_period_end | Yes | **NO** | No | 37 |
| cm_customers_period_end_by_tenure | Yes | Yes | Yes | 14 |
| cm_daily_active_users | Yes | Yes | Yes | 58 |
| cm_deferred_revenue | **NO** | Yes | No | 1 |
| cm_expansion_revenue | Yes | Yes | No | 1 |
| cm_gmv | Yes (deprecated) | Yes (deprecated) | No | 20 |
| cm_gross_margin_by_cohort | Yes | Yes | No | 2 |
| cm_gross_margin_overall | No | Yes (deprecated) | No | 0 |
| cm_gross_revenue_retention | Yes | Yes | Yes | 5 |
| cm_large_customers_period_end | Yes | Yes | Yes | 19 |
| cm_lifetime_value_per_customer | Yes | Yes (experimental) | Yes | 11 |
| cm_ltv_to_cac_ratio | Yes | Yes (experimental) | Yes | 10 |
| cm_ltv_to_cac_ratio_by_cohort | Yes | Yes | Yes | 0 |
| cm_monthly_active_users | Yes | Yes | Yes | 15 |
| cm_mrr | Yes | Yes | No | 19 |
| cm_net_revenue_retention | Yes | Yes | Yes | 55 |
| cm_new_customers_acquired | Yes | Yes | Yes | 76 |
| cm_purchase_transactions_overall | Yes | Yes | No | 0 |
| cm_repeat_purchase_rate | Yes | Yes | No | 8 |
| cm_revenue_by_cohort | Yes | Yes | Yes | 41 |
| cm_revenue_concentration | Yes | Yes | No | 6 |
| cm_revenue_per_customer | Yes | Yes | Yes | 19 |
| cm_tcv | Yes (deprecated) | Yes (deprecated) | No | 12 |
| cm_transactions_by_cohort | Yes | Yes | Yes | 17 |

---

## Phase 2: Next Steps (Requires User Approval)

After reviewing this audit, please provide guidance on:

1. **Alias Contradiction Resolution** (Section 6):
   - Option A: Keep as distinct metrics
   - Option B: Merge into single metric
   - Option C: Keep current hybrid

2. **cm_deferred_revenue** handling:
   - Add patterns to YAML?
   - Or deprecate in SQL?

3. **Test fixture fixes**:
   - Fix clearly wrong IDs (Priority 2)?
   - Leave abbreviated IDs as-is?

4. **METRIC_NAME_MAPPING gaps**:
   - Add missing entries for active metrics?

---

**END OF AUDIT REPORT**

*Generated by MET-1 Phase 1 Audit*
