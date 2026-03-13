"""
Unit-compatibility filtering for V2 metric extraction.

Validates whether a detected unit (currency, percent, count) is semantically
compatible with a given metric. For example, cm_customers_period_end should
only bind COUNT values, not $14.8M or 152%.

Ported from V1 constraints in src/review/false_positive_filter.py:316-349.
"""

from __future__ import annotations

from src.extraction_v2.models import Unit

# ============================================================================
# Metric → Allowed Units mapping
# ============================================================================

# Count-only metrics: customer/user counts, transaction counts, time-based periods
_COUNT_ONLY_METRICS: set[str] = {
    "cm_customers_period_end",
    "cm_active_customers_total",
    "cm_large_customers_period_end",
    "cm_new_customers_acquired",
    "cm_daily_active_users",
    "cm_monthly_active_users",
    "cm_customers_period_end_by_tenure",
    "cm_purchase_transactions_overall",
    "cm_transactions_by_cohort",
    "cm_cac_payback_period",  # payback period in months — not a currency value
}

# Currency-only metrics: ARR, MRR, revenue-per-customer, etc.
_CURRENCY_ONLY_METRICS: set[str] = {
    "cm_arr",
    "cm_mrr",
    "cm_tcv",
    "cm_acv",
    "cm_lifetime_value_per_customer",
    "cm_customer_acquisition_cost",
    "cm_revenue_per_customer",
    "cm_average_order_value",
    "cm_expansion_revenue",
    "cm_deferred_revenue",
    "cm_billings",
    "cm_bookings",
    "cm_gmv",
}

# Percent-only metrics: retention rates, churn, margins
_PERCENT_ONLY_METRICS: set[str] = {
    "cm_net_revenue_retention",
    "cm_gross_revenue_retention",
    "cm_customer_retention_rate",
    "cm_customer_churn_rate",
    "cm_revenue_concentration",
    "cm_gross_margin_by_cohort",
    "cm_gross_margin_overall",
}

# Ratio metrics: naturally appear as bare decimals (e.g., 1.42x LTV/CAC)
_RATIO_METRICS: set[str] = {
    "cm_ltv_to_cac_ratio",
    "cm_ltv_to_cac_ratio_by_cohort",
    "cm_repeat_purchase_rate",
}

# Build the lookup: metric_id → frozenset of allowed units
METRIC_ALLOWED_UNITS: dict[str, frozenset[Unit]] = {}

for _m in _COUNT_ONLY_METRICS:
    METRIC_ALLOWED_UNITS[_m] = frozenset({Unit.COUNT, Unit.OTHER})

for _m in _CURRENCY_ONLY_METRICS:
    METRIC_ALLOWED_UNITS[_m] = frozenset({Unit.CURRENCY, Unit.OTHER})

for _m in _PERCENT_ONLY_METRICS:
    METRIC_ALLOWED_UNITS[_m] = frozenset({Unit.PERCENT, Unit.RATIO})

for _m in _RATIO_METRICS:
    METRIC_ALLOWED_UNITS[_m] = frozenset({Unit.PERCENT, Unit.RATIO, Unit.OTHER})


def get_allowed_units(metric_id: str) -> frozenset[Unit] | None:
    """
    Return the set of allowed units for a metric, or None if unconstrained.

    Args:
        metric_id: Canonical metric ID (e.g., "cm_customers_period_end")

    Returns:
        frozenset of allowed Unit values, or None if the metric accepts all units.
    """
    return METRIC_ALLOWED_UNITS.get(metric_id)


def is_unit_compatible(metric_id: str, unit: Unit) -> bool:
    """
    Check whether a unit is compatible with a metric.

    Args:
        metric_id: Canonical metric ID
        unit: Detected unit from value parsing

    Returns:
        True if the unit is allowed (or the metric is unconstrained).
    """
    allowed = METRIC_ALLOWED_UNITS.get(metric_id)
    if allowed is None:
        return True
    return unit in allowed
