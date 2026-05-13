# Tier-1 Disclosure Reports in Metabase

Operator guide for the four recurring Tier-1 customer-metric disclosure
reports against `v_analytics_company_tier1_summary` and
`v_analytics_company_metric_disclosure`.

## What "disclosed" means here

A company is recorded as disclosing a metric in a given filing when **any**
of the following is true:

- A row exists in `v2_text_metric_presence` for `(filing_id, canonical_metric_id)` — text pipeline detected presence.
- A reviewer-confirmed row exists in `v2_image_metric_confirmations` with
  `decision IN ('accept','correct','add')` for an image attached to the filing
  — image surface is **reviewer-confirmed only**, not raw pipeline output.
  Rows superseded by a later admin override are excluded.

Disclosure is **deduplicated** per `(company, metric)` across all of a
company's in-scope filings: a company that discloses NRR in any of its
S-1/F-1 filings counts once.

## Universe

The summary view restricts to `filings.is_in_scope_phase1 = TRUE`
(first-time-issuer S-1/F-1, non-SPAC, not secondary-only — the project's
canonical "relevant IPO" definition). Companies whose only filings are
out-of-scope do not appear.

## Tier-1 metric set

Defined inline in `v_analytics_metric_tiers` (`sql/202605131507_tier1_disclosure_analytics.sql`),
mirroring `config/metric_keywords.yaml`. If the YAML's tier-1 set changes,
edit the `CASE` in the migration and re-apply (the view is
`CREATE OR REPLACE`).

## Metabase queries

Paste these into a new Metabase question (Native SQL, against the
`filings_analysis` database, user `metabase_ro`).

### Q1 — Companies by # of Tier-1 metrics disclosed

```sql
SELECT
    disclosure_bucket,
    COUNT(*) AS company_count
FROM v_analytics_company_tier1_summary
GROUP BY disclosure_bucket
ORDER BY
    CASE disclosure_bucket
        WHEN '0' THEN 0 WHEN '1' THEN 1 WHEN '2' THEN 2
        WHEN '3' THEN 3 WHEN '4' THEN 4 WHEN '5+' THEN 5
    END;
```

Bar chart: x = `disclosure_bucket`, y = `company_count`.

### Q2 — Companies by industry

```sql
SELECT
    industry_bucket,
    COUNT(*) AS company_count
FROM v_analytics_company_tier1_summary
GROUP BY industry_bucket
ORDER BY company_count DESC;
```

For an industry breakdown restricted to companies that disclosed at least
one Tier-1 metric, add `WHERE tier1_metric_count > 0`.

### Q3 — Per-industry % of IPOs at each disclosure bucket

```sql
WITH per_industry AS (
    SELECT
        industry_bucket,
        disclosure_bucket,
        COUNT(*) AS company_count
    FROM v_analytics_company_tier1_summary
    GROUP BY industry_bucket, disclosure_bucket
),
industry_totals AS (
    SELECT industry_bucket, SUM(company_count) AS industry_total
    FROM per_industry
    GROUP BY industry_bucket
)
SELECT
    p.industry_bucket,
    p.disclosure_bucket,
    p.company_count,
    t.industry_total,
    ROUND(100.0 * p.company_count / NULLIF(t.industry_total, 0), 1) AS pct_of_industry
FROM per_industry p
JOIN industry_totals t USING (industry_bucket)
ORDER BY
    p.industry_bucket,
    CASE p.disclosure_bucket
        WHEN '0' THEN 0 WHEN '1' THEN 1 WHEN '2' THEN 2
        WHEN '3' THEN 3 WHEN '4' THEN 4 WHEN '5+' THEN 5
    END;
```

In Metabase, set the visualization to **Pivot Table** with
`industry_bucket` as the row dimension, `disclosure_bucket` as the column
dimension, and `pct_of_industry` as the measure.

### Q4 — Per Tier-1 metric: company count + company list

```sql
SELECT
    d.canonical_metric_id,
    d.metric_display_name,
    COUNT(DISTINCT d.company_id) AS company_count,
    jsonb_agg(DISTINCT d.company_name ORDER BY d.company_name) AS companies
FROM v_analytics_company_metric_disclosure d
WHERE d.tier = 1
GROUP BY d.canonical_metric_id, d.metric_display_name
ORDER BY company_count DESC;
```

For a flattened drill-down (one row per company × metric, sortable by
metric or company), use:

```sql
SELECT
    d.canonical_metric_id,
    d.metric_display_name,
    d.company_name,
    d.ticker,
    d.cik,
    d.industry_bucket,
    d.disclosed_via_text,
    d.disclosed_via_image,
    d.filing_ids
FROM v_analytics_company_metric_disclosure d
WHERE d.tier = 1
ORDER BY d.canonical_metric_id, d.company_name;
```

## Future drill-through to evidence

`v_analytics_metric_presence` already carries `evidence_segment_ids`
(JSONB array of segment UUIDs from `v2_text_metric_presence`) and
`image_ids` (JSONB array of `img_id` values from confirmed
`v2_image_metric_confirmations`). A follow-up migration can add a
`v_analytics_metric_evidence` view that resolves those to segment text or
image storage keys without re-plumbing the underlying joins.

## Related

- `sql/202605131507_tier1_disclosure_analytics.sql` — view definitions
- `sql/38_create_analytics_views.sql` — fact-grain views (advisory)
- `docs/operations/analytics-ui-runbook.md` — Metabase deployment & role setup
- `config/metric_keywords.yaml` — tier definitions
- `config/industry_sic_codes.yaml` — SIC bucket definitions (source for `industry_sic_buckets`)
