-- =============================================================================
-- CMASB Analysis Queries
-- Created: 2025-12-03
-- Purpose: Reusable queries for analyzing extracted customer metrics
-- =============================================================================

-- -----------------------------------------------------------------------------
-- 1. EXTRACTION SUMMARY
-- Overview of data in extraction tables
-- -----------------------------------------------------------------------------

-- 1a. Row counts by table
SELECT
    'source_segments' as table_name, COUNT(*) as row_count FROM source_segments
UNION ALL SELECT 'metric_values', COUNT(*) FROM metric_values
UNION ALL SELECT 'metric_definitions', COUNT(*) FROM metric_definitions
UNION ALL SELECT 'filing_metric_incidence', COUNT(*) FROM filing_metric_incidence
ORDER BY table_name;

-- 1b. Distinct filings and companies with extraction data
SELECT
    (SELECT COUNT(DISTINCT filing_id) FROM metric_values) as filings_with_values,
    (SELECT COUNT(DISTINCT company_id) FROM metric_values) as companies_with_values,
    (SELECT COUNT(DISTINCT filing_id) FROM filing_metric_incidence) as filings_with_incidences,
    (SELECT ROUND(AVG(cnt), 1) FROM (SELECT COUNT(*) as cnt FROM metric_values GROUP BY filing_id) s) as avg_values_per_filing;

-- -----------------------------------------------------------------------------
-- 2. CMASB METRIC COVERAGE
-- Which CMASB metrics are found across filings
-- -----------------------------------------------------------------------------

-- 2a. CMASB coverage summary (found vs not found)
SELECT
    m.metric_id,
    m.display_name,
    m.metric_class,
    m.primary_concept,
    CASE WHEN fmi.metric_id IS NOT NULL THEN 'Found' ELSE 'Not Found' END as status,
    COALESCE(fmi.filing_count, 0) as filings,
    COALESCE(fmi.company_count, 0) as companies
FROM metrics m
LEFT JOIN (
    SELECT
        metric_id,
        COUNT(DISTINCT filing_id) as filing_count,
        COUNT(DISTINCT company_id) as company_count
    FROM filing_metric_incidence
    GROUP BY metric_id
) fmi ON m.metric_id = fmi.metric_id
WHERE m.metric_class IN ('core', 'extended')
ORDER BY m.metric_class, status DESC, filings DESC;

-- 2b. CMASB coverage percentage
WITH coverage AS (
    SELECT
        m.metric_class,
        COUNT(*) as total_metrics,
        COUNT(fmi.metric_id) as found_metrics
    FROM metrics m
    LEFT JOIN (SELECT DISTINCT metric_id FROM filing_metric_incidence) fmi
        ON m.metric_id = fmi.metric_id
    WHERE m.metric_class IN ('core', 'extended')
    GROUP BY m.metric_class
)
SELECT
    metric_class,
    found_metrics || '/' || total_metrics as coverage,
    ROUND(100.0 * found_metrics / total_metrics, 1) as pct
FROM coverage
UNION ALL
SELECT
    'TOTAL',
    SUM(found_metrics) || '/' || SUM(total_metrics),
    ROUND(100.0 * SUM(found_metrics) / SUM(total_metrics), 1)
FROM coverage;

-- 2c. Metric frequency across companies
SELECT
    fmi.metric_id,
    m.display_name,
    m.metric_class,
    COUNT(DISTINCT fmi.company_id) as companies,
    COUNT(DISTINCT fmi.filing_id) as filings,
    ROUND(100.0 * COUNT(DISTINCT fmi.company_id) /
          (SELECT COUNT(DISTINCT company_id) FROM filing_metric_incidence), 1) as pct_of_companies
FROM filing_metric_incidence fmi
JOIN metrics m ON fmi.metric_id = m.metric_id
GROUP BY fmi.metric_id, m.display_name, m.metric_class
ORDER BY companies DESC;

-- -----------------------------------------------------------------------------
-- 3. QUALITY SCORE ANALYSIS
-- Distribution and analysis of quality scores
-- -----------------------------------------------------------------------------

-- 3a. Quality score distribution
SELECT
    quality_overall_score as score,
    COUNT(*) as count,
    ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER(), 1) as pct
FROM filing_metric_incidence
GROUP BY quality_overall_score
ORDER BY quality_overall_score;

-- 3b. Quality by metric
SELECT
    fmi.metric_id,
    m.display_name,
    COUNT(*) as incidences,
    ROUND(AVG(fmi.quality_overall_score), 2) as avg_quality,
    ROUND(AVG(fmi.quality_definition_score), 2) as avg_definition,
    ROUND(AVG(fmi.quality_methodology_score), 2) as avg_methodology
FROM filing_metric_incidence fmi
JOIN metrics m ON fmi.metric_id = m.metric_id
GROUP BY fmi.metric_id, m.display_name
ORDER BY avg_quality DESC, incidences DESC;

-- 3c. High-quality disclosures (score >= 2)
SELECT
    c.company_name,
    fmi.metric_id,
    m.display_name,
    fmi.quality_overall_score,
    fmi.quality_definition_score,
    fmi.quality_methodology_score
FROM filing_metric_incidence fmi
JOIN companies c ON fmi.company_id = c.company_id
JOIN metrics m ON fmi.metric_id = m.metric_id
WHERE fmi.quality_overall_score >= 2
ORDER BY fmi.quality_overall_score DESC, c.company_name;

-- -----------------------------------------------------------------------------
-- 4. BUSINESS TYPE ANALYSIS
-- Metrics by company business type
-- -----------------------------------------------------------------------------

-- 4a. Summary by business type
SELECT
    CASE
        WHEN bc.is_ecommerce_marketplace THEN 'E-commerce'
        WHEN bc.is_platform_network THEN 'Platform'
        WHEN bc.is_healthcare_tech THEN 'HealthTech'
        WHEN bc.is_media_subscription THEN 'Media'
        WHEN bc.is_fintech_crypto THEN 'Fintech'
        WHEN bc.is_saas_software THEN 'SaaS'
        WHEN bc.is_telecom THEN 'Telecom'
        ELSE 'Unclassified'
    END as business_type,
    COUNT(DISTINCT fmi.company_id) as companies,
    COUNT(DISTINCT fmi.filing_id) as filings,
    COUNT(fmi.filing_metric_incidence_id) as total_incidences,
    COUNT(DISTINCT fmi.metric_id) as distinct_metrics,
    ROUND(AVG(fmi.quality_overall_score), 2) as avg_quality
FROM filing_metric_incidence fmi
JOIN companies c ON fmi.company_id = c.company_id
LEFT JOIN business_classifications bc ON c.company_id = bc.company_id
GROUP BY CASE
    WHEN bc.is_ecommerce_marketplace THEN 'E-commerce'
    WHEN bc.is_platform_network THEN 'Platform'
    WHEN bc.is_healthcare_tech THEN 'HealthTech'
    WHEN bc.is_media_subscription THEN 'Media'
    WHEN bc.is_fintech_crypto THEN 'Fintech'
    WHEN bc.is_saas_software THEN 'SaaS'
    WHEN bc.is_telecom THEN 'Telecom'
    ELSE 'Unclassified'
END
ORDER BY total_incidences DESC;

-- 4b. Best metrics by business type
SELECT
    business_type,
    metric_id,
    display_name,
    companies,
    avg_quality
FROM (
    SELECT
        CASE
            WHEN bc.is_ecommerce_marketplace THEN 'E-commerce'
            WHEN bc.is_platform_network THEN 'Platform'
            WHEN bc.is_healthcare_tech THEN 'HealthTech'
            WHEN bc.is_media_subscription THEN 'Media'
            WHEN bc.is_fintech_crypto THEN 'Fintech'
            WHEN bc.is_saas_software THEN 'SaaS'
            WHEN bc.is_telecom THEN 'Telecom'
            ELSE 'Unclassified'
        END as business_type,
        fmi.metric_id,
        m.display_name,
        COUNT(DISTINCT fmi.company_id) as companies,
        ROUND(AVG(fmi.quality_overall_score), 2) as avg_quality,
        ROW_NUMBER() OVER (
            PARTITION BY CASE
                WHEN bc.is_ecommerce_marketplace THEN 'E-commerce'
                WHEN bc.is_platform_network THEN 'Platform'
                WHEN bc.is_healthcare_tech THEN 'HealthTech'
                WHEN bc.is_media_subscription THEN 'Media'
                WHEN bc.is_fintech_crypto THEN 'Fintech'
                WHEN bc.is_saas_software THEN 'SaaS'
                WHEN bc.is_telecom THEN 'Telecom'
                ELSE 'Unclassified'
            END
            ORDER BY COUNT(DISTINCT fmi.company_id) DESC
        ) as rn
    FROM filing_metric_incidence fmi
    JOIN companies c ON fmi.company_id = c.company_id
    JOIN metrics m ON fmi.metric_id = m.metric_id
    LEFT JOIN business_classifications bc ON c.company_id = bc.company_id
    GROUP BY CASE
        WHEN bc.is_ecommerce_marketplace THEN 'E-commerce'
        WHEN bc.is_platform_network THEN 'Platform'
        WHEN bc.is_healthcare_tech THEN 'HealthTech'
        WHEN bc.is_media_subscription THEN 'Media'
        WHEN bc.is_fintech_crypto THEN 'Fintech'
        WHEN bc.is_saas_software THEN 'SaaS'
        WHEN bc.is_telecom THEN 'Telecom'
        ELSE 'Unclassified'
    END, fmi.metric_id, m.display_name
) ranked
WHERE rn <= 3
ORDER BY business_type, companies DESC;

-- -----------------------------------------------------------------------------
-- 5. COMPANY-LEVEL ANALYSIS
-- Detailed view by company
-- -----------------------------------------------------------------------------

-- 5a. Companies ranked by extraction success
SELECT
    c.company_name,
    c.cik,
    CASE
        WHEN bc.is_ecommerce_marketplace THEN 'E-commerce'
        WHEN bc.is_platform_network THEN 'Platform'
        WHEN bc.is_healthcare_tech THEN 'HealthTech'
        WHEN bc.is_media_subscription THEN 'Media'
        WHEN bc.is_fintech_crypto THEN 'Fintech'
        WHEN bc.is_saas_software THEN 'SaaS'
        WHEN bc.is_telecom THEN 'Telecom'
        ELSE 'Unclassified'
    END as business_type,
    COUNT(DISTINCT mv.metric_value_id) as metric_values,
    COUNT(DISTINCT fmi.metric_id) as distinct_metrics,
    ROUND(AVG(fmi.quality_overall_score), 2) as avg_quality
FROM companies c
JOIN metric_values mv ON c.company_id = mv.company_id
LEFT JOIN filing_metric_incidence fmi ON c.company_id = fmi.company_id
LEFT JOIN business_classifications bc ON c.company_id = bc.company_id
GROUP BY c.company_id, c.company_name, c.cik,
         bc.is_ecommerce_marketplace, bc.is_platform_network, bc.is_healthcare_tech,
         bc.is_media_subscription, bc.is_fintech_crypto, bc.is_saas_software, bc.is_telecom
ORDER BY metric_values DESC;

-- 5b. Companies with best quality disclosures
SELECT
    c.company_name,
    COUNT(DISTINCT fmi.metric_id) as metrics_disclosed,
    SUM(CASE WHEN fmi.quality_overall_score >= 2 THEN 1 ELSE 0 END) as high_quality_count,
    ROUND(AVG(fmi.quality_overall_score), 2) as avg_quality
FROM companies c
JOIN filing_metric_incidence fmi ON c.company_id = fmi.company_id
GROUP BY c.company_id, c.company_name
HAVING COUNT(DISTINCT fmi.metric_id) >= 3
ORDER BY avg_quality DESC, high_quality_count DESC;

-- -----------------------------------------------------------------------------
-- 6. METRIC VALUES ANALYSIS
-- Deep dive into extracted values
-- -----------------------------------------------------------------------------

-- 6a. Values by source type
SELECT
    source_type,
    COUNT(*) as count,
    ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER(), 1) as pct
FROM metric_values
GROUP BY source_type
ORDER BY count DESC;

-- 6b. Values by extraction method
SELECT
    extraction_method,
    COUNT(*) as count,
    ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER(), 1) as pct
FROM metric_values
GROUP BY extraction_method
ORDER BY count DESC;

-- 6c. Values with cohort breakdowns
SELECT
    cohort_type,
    COUNT(*) as count,
    COUNT(DISTINCT company_id) as companies
FROM metric_values
WHERE cohort_type IS NOT NULL
GROUP BY cohort_type
ORDER BY count DESC;

-- 6d. Period coverage
SELECT
    period_type,
    COUNT(*) as count,
    MIN(period_start) as earliest,
    MAX(period_end) as latest
FROM metric_values
WHERE period_type IS NOT NULL
GROUP BY period_type
ORDER BY count DESC;

-- -----------------------------------------------------------------------------
-- 7. DEFINITIONS ANALYSIS
-- Extracted metric definitions
-- -----------------------------------------------------------------------------

-- 7a. Definitions by metric
SELECT
    md.metric_id,
    m.display_name,
    COUNT(*) as definition_count,
    COUNT(DISTINCT md.company_id) as companies
FROM metric_definitions md
JOIN metrics m ON md.metric_id = m.metric_id
GROUP BY md.metric_id, m.display_name
ORDER BY definition_count DESC;

-- 7b. Sample definitions (first 5 per metric)
SELECT
    metric_id,
    company_name,
    LEFT(definition_text_normalized, 200) as definition_excerpt
FROM (
    SELECT
        md.metric_id,
        c.company_name,
        md.definition_text_normalized,
        ROW_NUMBER() OVER (PARTITION BY md.metric_id ORDER BY md.company_id) as rn
    FROM metric_definitions md
    JOIN companies c ON md.company_id = c.company_id
    WHERE md.definition_text_normalized IS NOT NULL
) ranked
WHERE rn <= 5
ORDER BY metric_id, rn;

-- =============================================================================
-- END OF ANALYSIS QUERIES
-- =============================================================================
