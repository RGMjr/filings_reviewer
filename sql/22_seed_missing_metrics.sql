-- Seed metrics that are active in metric_keywords.yaml but absent from the metrics table.
-- ON CONFLICT DO NOTHING makes this safe to run against databases that already have either row.

INSERT INTO metrics (metric_id, display_name, metric_class, description, primary_concept, status, version)
VALUES
    (
        'cm_large_customers_period_end',
        'Large Customers at Period End',
        'extended',
        'Count of enterprise or large customers (e.g., above an ARR threshold) at end of reporting period.',
        'customer_count',
        'active',
        1
    ),
    (
        'cm_balance_by_cohort',
        'Customer Balance by Cohort',
        'core',
        'Outstanding balance or loan portfolio balance tracked by customer acquisition cohort.',
        'cohort_balance',
        'active',
        1
    )
ON CONFLICT (metric_id) DO NOTHING;
