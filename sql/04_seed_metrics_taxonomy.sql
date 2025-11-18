-- ============================================================================
-- Seed: Metrics Taxonomy
-- Purpose: Populate metrics dimension table with canonical metric IDs
-- Date: 2025-11-17
-- Based on: 02_METRIC_TAXONOMY_AND_DEFINITIONS.md v0.1
-- ============================================================================

-- Clear existing metrics (for development)
TRUNCATE TABLE metrics CASCADE;

-- ============================================================================
-- CORE METRICS (Phase 1)
-- ============================================================================

-- CM1: New Customers Acquired per Period
INSERT INTO metrics (metric_id, display_name, metric_class, description, primary_concept, status, version)
VALUES (
    'cm_new_customers_acquired',
    'New Customers Acquired',
    'core',
    'Count of unique customers whose first qualifying economic activity with the company occurs in the reporting period.',
    'acquisition',
    'active',
    1
);

-- CM2: Customers at Period End by Tenure Cohort
INSERT INTO metrics (metric_id, display_name, metric_class, description, primary_concept, status, version)
VALUES (
    'cm_customers_period_end_by_tenure',
    'Customers at Period End by Tenure',
    'core',
    'Number of customers active at period end, broken down by tenure cohorts defined by time since first qualifying economic activity.',
    'cohort_count',
    'active',
    1
);

-- CM3: Revenue by Customer Cohort
INSERT INTO metrics (metric_id, display_name, metric_class, description, primary_concept, status, version)
VALUES (
    'cm_revenue_by_cohort',
    'Revenue by Customer Cohort',
    'core',
    'Recognized GAAP revenue in the period, attributed to customer cohorts defined by acquisition period or tenure.',
    'cohort_revenue',
    'active',
    1
);

-- CM4: Purchase Transactions by Cohort
INSERT INTO metrics (metric_id, display_name, metric_class, description, primary_concept, status, version)
VALUES (
    'cm_transactions_by_cohort',
    'Purchase Transactions by Cohort',
    'core',
    'Number of completed purchase transactions in the period, grouped by customer cohort (acquisition or tenure).',
    'cohort_transactions',
    'active',
    1
);

-- ============================================================================
-- EXTENDED METRICS (Phase 1)
-- ============================================================================

-- Active Customers (Total)
INSERT INTO metrics (metric_id, display_name, metric_class, description, primary_concept, status, version)
VALUES (
    'cm_active_customers_total',
    'Active Customers (Total)',
    'extended',
    'Total number of active customers as defined by the issuer at period end.',
    'customer_count',
    'active',
    1
);

-- ARPU / Revenue per Customer
INSERT INTO metrics (metric_id, display_name, metric_class, description, primary_concept, status, version)
VALUES (
    'cm_revenue_per_customer',
    'Average Revenue per User/Customer',
    'extended',
    'Revenue per user/customer/subscriber over a defined period (ARPU).',
    'unit_economics',
    'active',
    1
);

-- Customer Acquisition Cost
INSERT INTO metrics (metric_id, display_name, metric_class, description, primary_concept, status, version)
VALUES (
    'cm_customer_acquisition_cost',
    'Customer Acquisition Cost',
    'extended',
    'Cost to acquire a new customer, typically defined as sales and marketing expenses divided by new customers acquired.',
    'unit_economics',
    'active',
    1
);

-- CAC Payback Period
INSERT INTO metrics (metric_id, display_name, metric_class, description, primary_concept, status, version)
VALUES (
    'cm_cac_payback_period',
    'CAC Payback Period',
    'extended',
    'Time required for cumulative gross profit from a customer to recover the customer acquisition cost.',
    'unit_economics',
    'active',
    1
);

-- Customer Retention Rate
INSERT INTO metrics (metric_id, display_name, metric_class, description, primary_concept, status, version)
VALUES (
    'cm_customer_retention_rate',
    'Customer Retention Rate',
    'extended',
    'Percentage of customers retained over a defined period.',
    'retention',
    'active',
    1
);

-- Customer Churn Rate
INSERT INTO metrics (metric_id, display_name, metric_class, description, primary_concept, status, version)
VALUES (
    'cm_customer_churn_rate',
    'Customer Churn Rate',
    'extended',
    'Percentage of customers lost over a defined period.',
    'retention',
    'active',
    1
);

-- Net Revenue Retention (NRR)
INSERT INTO metrics (metric_id, display_name, metric_class, description, primary_concept, status, version)
VALUES (
    'cm_net_revenue_retention',
    'Net Revenue Retention',
    'extended',
    'Revenue from existing customer cohort including expansions and contractions, relative to prior period revenue from that cohort.',
    'retention',
    'active',
    1
);

-- Gross Revenue Retention (GRR)
INSERT INTO metrics (metric_id, display_name, metric_class, description, primary_concept, status, version)
VALUES (
    'cm_gross_revenue_retention',
    'Gross Revenue Retention',
    'extended',
    'Revenue from existing customer cohort excluding expansions, relative to prior period revenue from that cohort.',
    'retention',
    'active',
    1
);

-- Monthly Active Users (MAU)
INSERT INTO metrics (metric_id, display_name, metric_class, description, primary_concept, status, version)
VALUES (
    'cm_monthly_active_users',
    'Monthly Active Users',
    'extended',
    'Number of unique users active within a month.',
    'engagement',
    'active',
    1
);

-- Daily Active Users (DAU)
INSERT INTO metrics (metric_id, display_name, metric_class, description, primary_concept, status, version)
VALUES (
    'cm_daily_active_users',
    'Daily Active Users',
    'extended',
    'Number of unique users active within a day.',
    'engagement',
    'active',
    1
);

-- ============================================================================
-- FUTURE METRICS (Phase 2+)
-- ============================================================================

-- Customer Lifetime Value
INSERT INTO metrics (metric_id, display_name, metric_class, description, primary_concept, status, version)
VALUES (
    'cm_lifetime_value_per_customer',
    'Customer Lifetime Value',
    'future',
    'Expected total value (gross profit or revenue) from a customer over their entire relationship.',
    'unit_economics',
    'experimental',
    1
);

-- LTV to CAC Ratio
INSERT INTO metrics (metric_id, display_name, metric_class, description, primary_concept, status, version)
VALUES (
    'cm_ltv_to_cac_ratio',
    'LTV to CAC Ratio',
    'future',
    'Ratio of customer lifetime value to customer acquisition cost.',
    'unit_economics',
    'experimental',
    1
);

-- ============================================================================
-- Verification
-- ============================================================================

-- Show count by class
SELECT metric_class, COUNT(*) as count
FROM metrics
GROUP BY metric_class
ORDER BY
    CASE metric_class
        WHEN 'core' THEN 1
        WHEN 'extended' THEN 2
        WHEN 'future' THEN 3
    END;

-- List all metrics
SELECT metric_id, display_name, metric_class, primary_concept
FROM metrics
ORDER BY
    CASE metric_class
        WHEN 'core' THEN 1
        WHEN 'extended' THEN 2
        WHEN 'future' THEN 3
    END,
    metric_id;
