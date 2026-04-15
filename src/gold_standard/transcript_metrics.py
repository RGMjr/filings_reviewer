"""
Shared constants for transcript annotation and gold standard tooling.

ACTIVE_METRICS is the canonical set of 24 customer metric IDs used across:
  - scripts/preannotate_transcript.py
  - scripts/review_transcript_annotations.py
  - scripts/validate_transcript_annotations.py
  - scripts/merge_transcript_annotations.py

Must stay in sync with config/metric_keywords.yaml active set.
"""

ACTIVE_METRICS: frozenset[str] = frozenset(
    [
        "cm_active_customers_total",
        "cm_average_order_value",
        "cm_cac_payback_period",
        "cm_customer_acquisition_cost",
        "cm_customer_churn_rate",
        "cm_customer_retention_rate",
        "cm_customers_period_end",
        "cm_customers_period_end_by_tenure",
        "cm_daily_active_users",
        "cm_gross_margin_by_cohort",
        "cm_gross_revenue_retention",
        "cm_large_customers_period_end",
        "cm_lifetime_value_per_customer",
        "cm_ltv_to_cac_ratio",
        "cm_ltv_to_cac_ratio_by_cohort",
        "cm_monthly_active_users",
        "cm_net_revenue_retention",
        "cm_new_customers_acquired",
        "cm_purchase_transactions_overall",
        "cm_repeat_purchase_rate",
        "cm_revenue_by_cohort",
        "cm_revenue_concentration",
        "cm_revenue_per_customer",
        "cm_transactions_by_cohort",
    ]
)
