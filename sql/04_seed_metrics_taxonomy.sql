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

-- CM4b: Purchase Transactions Overall (added for HRV-6 taxonomy fix)
INSERT INTO metrics (metric_id, display_name, metric_class, description, primary_concept, status, version)
VALUES (
    'cm_purchase_transactions_overall',
    'Purchase Transactions Overall',
    'core',
    'Total number of purchase transactions or orders completed in the reporting period.',
    'transactions',
    'active',
    1
) ON CONFLICT (metric_id) DO NOTHING;

-- CM5: Customers at Period End (stock count)
-- Added 2026-01-07 (MET-1): Distinct from cm_active_customers_total (engagement-based)
INSERT INTO metrics (metric_id, display_name, metric_class, description, primary_concept, status, version)
VALUES (
    'cm_customers_period_end',
    'Customers at Period End',
    'core',
    'Total count of customers at the end of the reporting period, regardless of activity level. Includes paid customers, total customers, customer base counts.',
    'customer_count',
    'active',
    1
) ON CONFLICT (metric_id) DO NOTHING;

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

-- Gross Margin (Overall) - DEPRECATED: Not a customer-specific metric
INSERT INTO metrics (metric_id, display_name, metric_class, description, primary_concept, status, version)
VALUES (
    'cm_gross_margin_overall',
    'Gross Margin (Overall)',
    'extended',
    'Overall gross profit margin percentage across all customers and products.',
    'financial_performance',
    'deprecated',
    1
);

-- Gross Margin by Cohort
INSERT INTO metrics (metric_id, display_name, metric_class, description, primary_concept, status, version)
VALUES (
    'cm_gross_margin_by_cohort',
    'Gross Margin by Cohort',
    'extended',
    'Gross profit margin percentage broken down by customer cohort (acquisition or tenure).',
    'cohort_economics',
    'active',
    1
);

-- Annual Recurring Revenue (ARR)
INSERT INTO metrics (metric_id, display_name, metric_class, description, primary_concept, status, version)
VALUES (
    'cm_arr',
    'Annual Recurring Revenue',
    'extended',
    'Annualized value of recurring subscription revenue, typically calculated as MRR × 12 or based on contracted annual values.',
    'financial_performance',
    'active',
    1
);

-- Monthly Recurring Revenue (MRR)
INSERT INTO metrics (metric_id, display_name, metric_class, description, primary_concept, status, version)
VALUES (
    'cm_mrr',
    'Monthly Recurring Revenue',
    'extended',
    'Monthly value of recurring subscription revenue from active subscriptions.',
    'financial_performance',
    'active',
    1
);

-- Expansion Revenue
INSERT INTO metrics (metric_id, display_name, metric_class, description, primary_concept, status, version)
VALUES (
    'cm_expansion_revenue',
    'Expansion Revenue',
    'extended',
    'Additional revenue from existing customers through upsells, cross-sells, or increased usage.',
    'retention',
    'active',
    1
);

-- Revenue Concentration
INSERT INTO metrics (metric_id, display_name, metric_class, description, primary_concept, status, version)
VALUES (
    'cm_revenue_concentration',
    'Revenue Concentration',
    'extended',
    'Percentage of total revenue attributable to top customers (e.g., top 10 customers, top 5%).',
    'risk',
    'active',
    1
);

-- Bookings (DEPRECATED 2026-01-07: Financial metric, not customer metric unless cohort-specific)
INSERT INTO metrics (metric_id, display_name, metric_class, description, primary_concept, status, version)
VALUES (
    'cm_bookings',
    'Bookings',
    'extended',
    'Total value of customer contracts signed in a period, representing committed future revenue.',
    'revenue_predictability',
    'deprecated',
    1
);

-- Billings (DEPRECATED 2026-01-07: Financial metric, not customer metric unless cohort-specific)
INSERT INTO metrics (metric_id, display_name, metric_class, description, primary_concept, status, version)
VALUES (
    'cm_billings',
    'Billings',
    'extended',
    'Total amounts invoiced to customers in a period, typically revenue plus change in deferred revenue.',
    'revenue_predictability',
    'deprecated',
    1
);

-- Deferred Revenue (DEPRECATED 2026-01-07: Financial metric, not customer metric)
INSERT INTO metrics (metric_id, display_name, metric_class, description, primary_concept, status, version)
VALUES (
    'cm_deferred_revenue',
    'Deferred Revenue',
    'extended',
    'Payments received from customers for services not yet delivered, representing future revenue obligation.',
    'revenue_predictability',
    'deprecated',
    1
);

-- Average Order Value
INSERT INTO metrics (metric_id, display_name, metric_class, description, primary_concept, status, version)
VALUES (
    'cm_average_order_value',
    'Average Order Value',
    'extended',
    'Average monetary value per order or transaction, commonly used by e-commerce and marketplace businesses.',
    'unit_economics',
    'active',
    1
);

-- Repeat Purchase Rate
INSERT INTO metrics (metric_id, display_name, metric_class, description, primary_concept, status, version)
VALUES (
    'cm_repeat_purchase_rate',
    'Repeat Purchase Rate',
    'extended',
    'Percentage of customers who make more than one purchase, or the frequency of repeat purchases.',
    'retention',
    'active',
    1
);

-- Gross Merchandise Value (DEPRECATED 2026-01-07: Financial metric, not customer metric unless cohort-specific)
INSERT INTO metrics (metric_id, display_name, metric_class, description, primary_concept, status, version)
VALUES (
    'cm_gmv',
    'Gross Merchandise Value',
    'extended',
    'Total value of merchandise sold through the platform over a defined period, before deductions for returns, discounts, or platform fees.',
    'transaction_volume',
    'deprecated',
    1
);

-- Take Rate - REMOVED (2026-01-02)
-- Rationale: Take rate is a platform/marketplace revenue metric, not a customer metric.
-- INSERT INTO metrics (metric_id, display_name, metric_class, description, primary_concept, status, version)
-- VALUES (
--     'cm_take_rate',
--     'Take Rate',
--     'extended',
--     'Percentage of gross merchandise value or transaction value retained by the platform as revenue, representing the platform commission or fee rate.',
--     'unit_economics',
--     'active',
--     1
-- );

-- Annual Contract Value (DEPRECATED 2026-01-07: Financial metric, not customer metric unless cohort-specific)
INSERT INTO metrics (metric_id, display_name, metric_class, description, primary_concept, status, version)
VALUES (
    'cm_acv',
    'Annual Contract Value',
    'extended',
    'Average or total annual value of customer contracts, commonly used by SaaS and subscription businesses.',
    'revenue_predictability',
    'deprecated',
    1
);

-- Total Contract Value (DEPRECATED 2026-01-07: Financial metric, not customer metric unless cohort-specific)
INSERT INTO metrics (metric_id, display_name, metric_class, description, primary_concept, status, version)
VALUES (
    'cm_tcv',
    'Total Contract Value',
    'extended',
    'Total value of customer contracts including all future committed revenue over the contract lifetime.',
    'revenue_predictability',
    'deprecated',
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

-- LTV to CAC Ratio by Cohort (added 2026-01-07)
INSERT INTO metrics (metric_id, display_name, metric_class, description, primary_concept, status, version)
VALUES (
    'cm_ltv_to_cac_ratio_by_cohort',
    'LTV/CAC Ratio by Cohort',
    'extended',
    'LTV to CAC ratio analyzed by customer acquisition cohort, showing unit economics evolution over time.',
    'unit_economics',
    'active',
    1
);

-- ============================================================================
-- GROWTH METRICS - REMOVED (2026-01-02)
-- ============================================================================
-- Decision: Growth metrics are not tracked separately because:
-- 1. They always appear alongside base metrics (e.g., "1.1M customers, up 57%")
-- 2. Growth can be calculated from period-over-period base metric values
-- 3. Detecting both creates duplicate/confusing review candidates
--
-- Previously defined metrics (now removed):
-- - cm_active_customers_growth
-- - cm_purchase_transactions_overall_growth
-- ============================================================================

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
