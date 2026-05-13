-- Migration 202605131507: tier1_disclosure_analytics
--
-- Adds the analytics surface for Tier-1 customer-metric disclosure reporting
-- in Metabase. Answers four recurring questions:
--   1. Histogram of in-scope companies by # of Tier-1 metrics disclosed
--   2. Industry breakdown of those companies
--   3. Per-industry % of IPOs disclosing 1/2/3/4/5+ Tier-1 metrics
--   4. Per-metric: count of disclosing companies + drillable company list
--
-- "Disclosed" is presence-based and deduplicated across two surfaces:
--   - Text: any row in v2_text_metric_presence for (filing, metric)
--   - Image: a v2_image_metric_confirmations row with decision in
--     ('accept','correct','add'), excluding rows superseded by a later
--     admin override.
--
-- Universe filter: filings.is_in_scope_phase1 = TRUE.
--
-- New objects:
--   industry_sic_buckets               (seed table, sic_code -> primary bucket)
--   v_analytics_metric_tiers           (catalog of metric_id -> tier)
--   v_analytics_metric_presence        (per filing x metric, text+image unioned)
--   v_analytics_company_metric_disclosure  (per company x metric, deduped)
--   v_analytics_company_tier1_summary  (per company, tier-1 count + bucket)
--
-- Default privileges (sql/37_create_analytics_role.sql) grant SELECT on new
-- tables/views to metabase_ro automatically; no explicit GRANT here.

BEGIN;

-- ============================================================================
-- industry_sic_buckets
-- ----------------------------------------------------------------------------
-- Snapshot of config/industry_sic_codes.yaml flattened to (sic_code, bucket).
-- The YAML is many-to-many (one SIC can appear in several buckets); for
-- aggregation we collapse each SIC to its *first-listed* bucket in the YAML
-- so every company falls into exactly one bucket.
--
-- To regenerate after editing the YAML:
--
--   python3 - <<'PY'
--   import yaml
--   cfg = yaml.safe_load(open('config/industry_sic_codes.yaml'))
--   seen = {}
--   for bucket, body in cfg['industries'].items():
--       for code in body.get('sic_codes', []):
--           seen.setdefault(code, bucket)
--   for code in sorted(seen):
--       print(f"    ('{code}', '{seen[code]}'),")
--   PY
--
-- ON CONFLICT DO UPDATE makes the migration safely re-runnable.
-- ============================================================================

CREATE TABLE IF NOT EXISTS industry_sic_buckets (
    sic_code    TEXT PRIMARY KEY,
    bucket_name TEXT NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE industry_sic_buckets IS
    'Snapshot of config/industry_sic_codes.yaml: SIC code -> primary (first-listed) bucket. Source of truth is the YAML; regenerate via the script in the migration comment.';

INSERT INTO industry_sic_buckets (sic_code, bucket_name) VALUES
    ('1311', 'oil_gas_exploration'),
    ('1381', 'oil_gas_exploration'),
    ('1531', 'homebuilding'),
    ('2711', 'media_publishing'),
    ('2721', 'media_publishing'),
    ('2731', 'media_publishing'),
    ('2834', 'pharmaceuticals'),
    ('2835', 'pharmaceuticals'),
    ('2836', 'biotech'),
    ('2911', 'oil_gas_refining'),
    ('3576', 'computer_hardware'),
    ('3577', 'computer_hardware'),
    ('3661', 'telecom_equipment'),
    ('3663', 'telecom_equipment'),
    ('3672', 'computer_hardware'),
    ('3674', 'semiconductors'),
    ('3721', 'aerospace_defense'),
    ('3728', 'aerospace_defense'),
    ('3812', 'aerospace_defense'),
    ('3841', 'medical_devices'),
    ('3842', 'medical_devices'),
    ('3845', 'medical_devices'),
    ('4210', 'logistics_supply_chain'),
    ('4213', 'logistics_supply_chain'),
    ('4215', 'logistics_supply_chain'),
    ('4400', 'logistics_supply_chain'),
    ('4522', 'logistics_supply_chain'),
    ('4731', 'logistics_supply_chain'),
    ('4813', 'consumer_internet'),
    ('4911', 'electric_utilities'),
    ('4931', 'electric_utilities'),
    ('5047', 'healthtech_digital_health'),
    ('5211', 'home_improvement_retail'),
    ('5251', 'home_improvement_retail'),
    ('5411', 'grocery_retail'),
    ('5511', 'auto_dealers'),
    ('5521', 'auto_dealers'),
    ('5621', 'apparel_retail'),
    ('5651', 'apparel_retail'),
    ('5661', 'apparel_retail'),
    ('5699', 'apparel_retail'),
    ('5812', 'restaurants'),
    ('5900', 'marketplace_ecommerce'),
    ('5940', 'marketplace_ecommerce'),
    ('5961', 'marketplace_ecommerce'),
    ('5999', 'marketplace_ecommerce'),
    ('6020', 'commercial_banking'),
    ('6021', 'commercial_banking'),
    ('6022', 'commercial_banking'),
    ('6029', 'commercial_banking'),
    ('6099', 'fintech_payments'),
    ('6141', 'fintech_payments'),
    ('6153', 'fintech_payments'),
    ('6159', 'fintech_payments'),
    ('6199', 'fintech_payments'),
    ('6211', 'fintech_payments'),
    ('6282', 'investment_management'),
    ('6311', 'insurtech'),
    ('6321', 'insurtech'),
    ('6331', 'insurtech'),
    ('6351', 'insurtech'),
    ('6399', 'insurtech'),
    ('6411', 'insurtech'),
    ('6500', 'proptech'),
    ('6510', 'proptech'),
    ('6512', 'proptech'),
    ('6531', 'proptech'),
    ('6552', 'proptech'),
    ('6726', 'investment_management'),
    ('7361', 'hr_tech'),
    ('7370', 'software'),
    ('7371', 'software'),
    ('7372', 'software'),
    ('7373', 'software'),
    ('7374', 'software'),
    ('7375', 'consumer_internet'),
    ('7377', 'software'),
    ('7379', 'saas_cloud'),
    ('7382', 'cybersecurity'),
    ('7389', 'industrial_services'),
    ('7812', 'consumer_internet'),
    ('7941', 'consumer_internet'),
    ('7993', 'gaming_entertainment'),
    ('8000', 'healthtech_digital_health'),
    ('8011', 'healthtech_digital_health'),
    ('8049', 'healthtech_digital_health'),
    ('8099', 'healthtech_digital_health'),
    ('8200', 'edtech'),
    ('8211', 'edtech'),
    ('8220', 'edtech'),
    ('8249', 'edtech'),
    ('8731', 'biotech')
ON CONFLICT (sic_code) DO UPDATE SET bucket_name = EXCLUDED.bucket_name;

-- ============================================================================
-- v_analytics_metric_tiers
-- ----------------------------------------------------------------------------
-- Grain: one row per row in `metrics`.
-- Tier 1 = the must-not-miss set defined in config/metric_keywords.yaml.
-- Embedded inline to avoid adding a tier column to v2_metric_definitions /
-- metrics; if the YAML's tier-1 set changes, edit this list and re-apply.
-- ============================================================================

CREATE OR REPLACE VIEW v_analytics_metric_tiers AS
SELECT
    m.metric_id AS canonical_metric_id,
    m.display_name AS metric_display_name,
    CASE WHEN m.metric_id IN (
        'cm_new_customers_acquired',
        'cm_large_customers_period_end',
        'cm_customers_period_end_by_tenure',
        'cm_revenue_by_cohort',
        'cm_transactions_by_cohort',
        'cm_customer_acquisition_cost',
        'cm_customer_retention_rate',
        'cm_net_revenue_retention',
        'cm_gross_revenue_retention',
        'cm_balance_by_cohort',
        'cm_gross_margin_by_cohort',
        'cm_expansion_revenue',
        'cm_revenue_concentration',
        'cm_lifetime_value_per_customer',
        'cm_ltv_to_cac_ratio',
        'cm_ltv_to_cac_ratio_by_cohort'
    ) THEN 1 ELSE 2 END AS tier
FROM metrics m;

COMMENT ON VIEW v_analytics_metric_tiers IS
    'Metric tier annotation (1 = must-not-miss, 2 = nice-to-have). Source: config/metric_keywords.yaml. Edit the inline list if the tier-1 set changes.';

-- ============================================================================
-- v_analytics_metric_presence
-- ----------------------------------------------------------------------------
-- Grain: one row per (filing_id, canonical_metric_id) where any presence
-- signal exists. Built by FULL OUTER JOIN of text-presence rows and reviewer-
-- confirmed image rows, both keyed on (filing_id, metric_id). Carries
-- lightweight evidence pointers so future drill-down views can resolve
-- segment text / image URLs without re-plumbing.
--
-- Image side: only decisions in ('accept','correct','add') count as
-- "disclosed". Rows superseded by a later admin override (see migration
-- 202605111319) are excluded.
-- ============================================================================

CREATE OR REPLACE VIEW v_analytics_metric_presence AS
WITH text_per_pair AS (
    SELECT
        p.filing_id,
        p.canonical_metric_id,
        p.evidence_segment_ids
    FROM v2_text_metric_presence p
),
image_per_pair AS (
    SELECT
        a.filing_id,
        COALESCE(c.confirmed_metric_id, c.detected_metric_id) AS canonical_metric_id,
        jsonb_agg(DISTINCT to_jsonb(c.img_id::text)) AS image_ids
    FROM v2_image_metric_confirmations c
    JOIN v2_image_assets a ON a.img_id = c.img_id
    WHERE c.decision IN ('accept', 'correct', 'add')
      AND COALESCE(c.confirmed_metric_id, c.detected_metric_id) IS NOT NULL
      AND NOT EXISTS (
          SELECT 1
          FROM v2_image_metric_confirmations c2
          WHERE c2.supersedes_confirmation_id = c.id
      )
    GROUP BY a.filing_id, COALESCE(c.confirmed_metric_id, c.detected_metric_id)
)
SELECT
    COALESCE(t.filing_id, i.filing_id)                  AS filing_id,
    COALESCE(t.canonical_metric_id, i.canonical_metric_id) AS canonical_metric_id,
    (t.filing_id IS NOT NULL)                           AS text_disclosed,
    (i.filing_id IS NOT NULL)                           AS image_disclosed,
    TRUE                                                AS any_disclosed,
    COALESCE(t.evidence_segment_ids, '[]'::jsonb)       AS evidence_segment_ids,
    COALESCE(i.image_ids, '[]'::jsonb)                  AS image_ids
FROM text_per_pair t
FULL OUTER JOIN image_per_pair i
    ON t.filing_id = i.filing_id
   AND t.canonical_metric_id = i.canonical_metric_id;

COMMENT ON VIEW v_analytics_metric_presence IS
    'Per (filing, metric) unified presence signal: UNION of v2_text_metric_presence and reviewer-confirmed v2_image_metric_confirmations. Evidence pointers (segment_ids, image_ids) included for future drill-through.';

-- ============================================================================
-- v_analytics_company_metric_disclosure
-- ----------------------------------------------------------------------------
-- Grain: one row per (company_id, canonical_metric_id) where the company has
-- at least one *in-scope* filing (is_in_scope_phase1 = TRUE) disclosing the
-- metric. Joins industry_sic_buckets for industry bucket (default 'other')
-- and v_analytics_metric_tiers for tier annotation.
-- ============================================================================

CREATE OR REPLACE VIEW v_analytics_company_metric_disclosure AS
SELECT
    c.company_id,
    c.cik,
    c.ticker,
    c.company_name,
    c.industry_code,
    COALESCE(b.bucket_name, 'other')               AS industry_bucket,
    p.canonical_metric_id,
    mt.metric_display_name,
    mt.tier,
    BOOL_OR(p.text_disclosed)                      AS disclosed_via_text,
    BOOL_OR(p.image_disclosed)                     AS disclosed_via_image,
    jsonb_agg(DISTINCT to_jsonb(fi.filing_id))     AS filing_ids
FROM v_analytics_metric_presence p
JOIN filings fi                  ON fi.filing_id = p.filing_id
JOIN companies c                 ON c.company_id = fi.company_id
LEFT JOIN industry_sic_buckets b ON b.sic_code   = c.industry_code
LEFT JOIN v_analytics_metric_tiers mt
                                 ON mt.canonical_metric_id = p.canonical_metric_id
WHERE fi.is_in_scope_phase1 = TRUE
GROUP BY
    c.company_id, c.cik, c.ticker, c.company_name, c.industry_code,
    COALESCE(b.bucket_name, 'other'),
    p.canonical_metric_id, mt.metric_display_name, mt.tier;

COMMENT ON VIEW v_analytics_company_metric_disclosure IS
    'Per (company, metric) deduplicated disclosure across in-scope filings (is_in_scope_phase1). Each row means the company disclosed the metric in at least one IPO filing via text and/or image.';

-- ============================================================================
-- v_analytics_company_tier1_summary
-- ----------------------------------------------------------------------------
-- Grain: one row per company that has >=1 in-scope filing. Counts distinct
-- Tier-1 metrics disclosed; companies with zero Tier-1 disclosures still
-- appear (count = 0, bucket = '0').
-- ============================================================================

CREATE OR REPLACE VIEW v_analytics_company_tier1_summary AS
WITH in_scope_companies AS (
    SELECT DISTINCT fi.company_id
    FROM filings fi
    WHERE fi.is_in_scope_phase1 = TRUE
),
tier1_per_company AS (
    SELECT
        d.company_id,
        COUNT(DISTINCT d.canonical_metric_id) AS tier1_metric_count,
        jsonb_agg(DISTINCT d.canonical_metric_id ORDER BY d.canonical_metric_id) AS tier1_metric_ids
    FROM v_analytics_company_metric_disclosure d
    WHERE d.tier = 1
    GROUP BY d.company_id
)
SELECT
    c.company_id,
    c.cik,
    c.ticker,
    c.company_name,
    c.industry_code,
    COALESCE(b.bucket_name, 'other')               AS industry_bucket,
    COALESCE(t.tier1_metric_count, 0)              AS tier1_metric_count,
    COALESCE(t.tier1_metric_ids, '[]'::jsonb)      AS tier1_metric_ids,
    CASE
        WHEN COALESCE(t.tier1_metric_count, 0) >= 5 THEN '5+'
        ELSE COALESCE(t.tier1_metric_count, 0)::text
    END                                            AS disclosure_bucket
FROM in_scope_companies isc
JOIN companies c                 ON c.company_id = isc.company_id
LEFT JOIN industry_sic_buckets b ON b.sic_code   = c.industry_code
LEFT JOIN tier1_per_company t    ON t.company_id = c.company_id;

COMMENT ON VIEW v_analytics_company_tier1_summary IS
    'One row per in-scope company (is_in_scope_phase1) with count of distinct Tier-1 metrics disclosed and a 0/1/2/3/4/5+ disclosure bucket. Primary surface for the Metabase tier-1 disclosure reports.';

COMMIT;
