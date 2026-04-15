"""
Shared metric helpers for review route dropdowns.

Provides the full list of active metrics from the database, ordered by
semantic grouping (customer counts, transactions, revenue, etc.).
Used by both review.py (legacy) and review_unified.py.
"""

from typing import TypedDict

from flask import g

from src.web.app import get_db


class MetricData(TypedDict):
    """Active metric data for metric dropdown."""

    metric_id: str
    display_name: str
    metric_class: str  # 'core', 'extended', etc.
    primary_concept: str


# Metric ordering for dropdowns - semantic grouping by business category.
# This is the SINGLE SOURCE OF TRUTH for dropdown ordering.
# The SQL CASE statement is generated dynamically from this dict.
#
# ORDERING CONVENTION:
#   - Category 1 (Customer Counts): 1-9
#   - Category 2 (Transactions): 11-19
#   - Category 3 (Revenue): 21-29
#   - Category 4 (Retention/Churn): 31-39
#   - Category 5 (Unit Economics): 41-49
#   Gaps allow inserting new metrics without renumbering existing ones.
#
# SAFETY: These IDs are used in f-string SQL generation. This is safe because
# they are hardcoded constants. Never add user-supplied values to this dict.
METRIC_DISPLAY_ORDER: dict[str, int] = {
    # Category 1: Customer Count Metrics (1-9)
    "cm_customers_period_end": 1,
    "cm_active_customers_total": 2,
    "cm_daily_active_users": 3,
    "cm_monthly_active_users": 4,
    "cm_large_customers_period_end": 5,
    "cm_new_customers_acquired": 6,
    "cm_customers_period_end_by_tenure": 7,
    # Category 2: Transaction & Purchase Behavior (11-19)
    "cm_purchase_transactions_overall": 11,
    "cm_transactions_by_cohort": 12,
    "cm_repeat_purchase_rate": 13,
    "cm_average_order_value": 14,
    # Category 3: Revenue Metrics (21-29)
    "cm_revenue_per_customer": 23,
    "cm_revenue_by_cohort": 24,
    "cm_gross_margin_by_cohort": 25,
    "cm_revenue_concentration": 27,
    # Category 4: Retention, Churn & Attrition (31-39)
    "cm_net_revenue_retention": 31,
    "cm_gross_revenue_retention": 32,
    "cm_customer_churn_rate": 33,
    "cm_customer_retention_rate": 34,
    # Category 5: Unit Economics & CAC (41-49)
    "cm_lifetime_value_per_customer": 41,
    "cm_customer_acquisition_cost": 42,
    "cm_ltv_to_cac_ratio": 43,
    "cm_ltv_to_cac_ratio_by_cohort": 44,
    "cm_cac_payback_period": 45,
}


def _build_metric_order_clause() -> str:
    """
    Build SQL CASE statement for metric ordering from METRIC_DISPLAY_ORDER.

    Returns:
        SQL CASE expression string for ORDER BY clause.

    SAFETY NOTE: This uses f-string SQL building which is safe ONLY because
    metric_ids are hardcoded constants from METRIC_DISPLAY_ORDER, never user input.
    DO NOT copy this pattern for user-supplied values.
    """
    clauses = [
        f"WHEN '{metric_id}' THEN {order}" for metric_id, order in METRIC_DISPLAY_ORDER.items()
    ]
    return "CASE metric_id\n" + "\n".join(clauses) + "\nELSE 99\nEND"


def get_active_metrics() -> list[MetricData]:
    """
    Get list of all active metrics for dropdown.

    Cached in Flask g object to avoid repeated queries per request.
    Returns list sorted by logical grouping (customer count, transactions, revenue, etc.).

    Returns:
        List[MetricData]: Active metrics with metric_id, display_name, metric_class, primary_concept
    """
    if "all_metrics" not in g:
        db = get_db()
        order_clause = _build_metric_order_clause()
        metrics_sql = f"""
            SELECT metric_id, display_name, metric_class, primary_concept
            FROM metrics
            WHERE status = 'active'
            ORDER BY {order_clause}
        """
        g.all_metrics = db.query(metrics_sql)

    return g.all_metrics
