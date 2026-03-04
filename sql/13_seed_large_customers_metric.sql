-- Seed cm_large_customers_period_end into metrics table.
-- This metric is defined in config/metric_keywords.yaml but was missing from seed data.
INSERT INTO metrics (metric_id, display_name, metric_class, description, primary_concept, status, version)
VALUES (
    'cm_large_customers_period_end',
    'Large Customers at Period End',
    'extended',
    'Count of large/enterprise customers exceeding a revenue or ARR threshold at period end.',
    'customer_count',
    'active',
    1
)
ON CONFLICT (metric_id) DO NOTHING;
