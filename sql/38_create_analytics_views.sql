-- Migration 38: Curated analytics views for BI tooling (Metabase, etc.)
--
-- Why: Metabase users (and ad-hoc SQL users) should query curated denormalized
-- views rather than raw tables. Centralizing joins here means the shape of
-- questions like "who discloses what?" and "all facts for metric X" stays
-- consistent regardless of who is asking.
--
-- Views live under the v_analytics_* namespace to distinguish them from the
-- internal v2_* / v_* review views defined in sql/09_v2_schema.sql.
--
-- These views are CREATE OR REPLACE so the migration is idempotent — safe to
-- re-run as the analytical surface evolves.

-- ============================================================================
-- v_analytics_fact_wide
-- ----------------------------------------------------------------------------
-- Grain: one row per v2_metric_facts row.
-- Purpose: the default starting point for any question about extracted values.
-- Metabase's visual query builder can derive trends, per-company rollups, QA
-- breakdowns, etc. from this single view without further SQL.
-- ============================================================================

CREATE OR REPLACE VIEW v_analytics_fact_wide AS
SELECT
    -- Fact identity
    f.fact_id,
    f.pipeline_version,
    f.created_at AS fact_created_at,
    f.updated_at AS fact_updated_at,

    -- Company dimension
    c.company_id,
    c.cik,
    c.ticker,
    c.company_name,

    -- Filing dimension
    fi.filing_id,
    fi.accession_number,
    fi.form_type,
    fi.filing_date,

    -- Metric dimension
    m.metric_id,
    m.display_name AS metric_display_name,
    m.metric_class,           -- 'core' | 'extended' | 'future'
    m.primary_concept,
    m.status AS metric_status,

    -- Value
    f.value,
    f.value_raw,
    f.unit,
    f.currency,

    -- Period
    f.period_type,
    f.period_start,
    f.period_end,

    -- Scope
    f.scope,
    f.scope_detail,
    f.cohort_def,
    f.customer_type,

    -- Provenance & quality
    f.source_type,            -- 'html_table' | 'ocr_table' | 'text' | 'chart'
    f.extraction_method,
    f.confidence,
    f.review_status,          -- 'auto_accepted' | 'pending_review' | 'accepted' | 'rejected' | 'corrected'
    f.requires_review,
    f.review_reason
FROM v2_metric_facts f
JOIN filings   fi ON fi.filing_id  = f.doc_id
JOIN companies c  ON c.company_id  = fi.company_id
JOIN metrics   m  ON m.metric_id   = f.canonical_metric_id
WHERE f.primary_fact_id IS NULL;  -- Exclude dedup shadows; keep only primary facts

COMMENT ON VIEW v_analytics_fact_wide IS
    'Denormalized fact view: one row per primary v2_metric_fact with company, filing, metric context. Exclude dedup shadows. Default surface for BI tools.';

-- ============================================================================
-- v_analytics_coverage_matrix
-- ----------------------------------------------------------------------------
-- Grain: one row per (company, canonical_metric_id) combination where the
-- company has issued at least one in-scope filing. Includes a has_fact flag so
-- Metabase heatmaps can render "who discloses what" without extra logic.
--
-- "At least one in-scope filing" uses filings.is_in_scope_phase1 when set;
-- falls back to any filing via COALESCE. Filtering by form_type happens at
-- dashboard time (Metabase parameter), not here, so this view stays flexible.
-- ============================================================================

CREATE OR REPLACE VIEW v_analytics_coverage_matrix AS
WITH company_filing_universe AS (
    -- Distinct companies with at least one filing we care about.
    SELECT DISTINCT fi.company_id
    FROM filings fi
    WHERE COALESCE(fi.is_in_scope_phase1, TRUE) = TRUE
),
fact_aggregates AS (
    -- Per-company, per-metric rollup of accepted / not-rejected facts.
    SELECT
        fi.company_id,
        f.canonical_metric_id,
        COUNT(*) AS fact_count,
        MAX(f.period_end) AS latest_period_end,
        MAX(fi.filing_date) AS latest_filing_date,
        COUNT(*) FILTER (
            WHERE f.review_status IN ('accepted', 'auto_accepted', 'corrected')
        ) AS accepted_fact_count
    FROM v2_metric_facts f
    JOIN filings fi ON fi.filing_id = f.doc_id
    WHERE f.primary_fact_id IS NULL
      AND f.review_status <> 'rejected'
    GROUP BY fi.company_id, f.canonical_metric_id
)
SELECT
    c.company_id,
    c.cik,
    c.ticker,
    c.company_name,
    m.metric_id,
    m.display_name AS metric_display_name,
    m.metric_class,
    m.primary_concept,
    COALESCE(fa.fact_count, 0)          AS fact_count,
    COALESCE(fa.accepted_fact_count, 0) AS accepted_fact_count,
    (fa.fact_count IS NOT NULL)         AS has_fact,
    (fa.accepted_fact_count > 0)        AS has_accepted_fact,
    fa.latest_period_end,
    fa.latest_filing_date
FROM company_filing_universe cfu
JOIN companies c ON c.company_id = cfu.company_id
CROSS JOIN metrics m
LEFT JOIN fact_aggregates fa
    ON fa.company_id = cfu.company_id
   AND fa.canonical_metric_id = m.metric_id
WHERE m.status = 'active';

COMMENT ON VIEW v_analytics_coverage_matrix IS
    'Company x active metric coverage matrix. One row per (company, metric) with has_fact / fact_count for heatmap dashboards.';
