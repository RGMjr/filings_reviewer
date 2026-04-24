---
autonomy: review
discovered: '2026-04-24'
estimated: M
id: 97
note: 'Residual pre-pivot chart facts (30 rows across 10 filings) remain in
  v2_metric_facts post-#86 because 18 reviewer decisions on those facts would
  CASCADE-destroy on DELETE. Low blast radius — new UI does not read them,
  validator bypasses them — but analytics views filtering on source_type=chart
  still see them.'
severity: low
slug: residual-chart-facts-after-presence-pivot
source: legacy
status: open
title: Residual Chart Facts Remain After Chart-Presence Pivot (Drain Deferred)
touches: []
updated: '2026-04-24'
---

### Problem

The chart-presence pivot (Issue #86, merged across PRs #147/#150/#151/#154/#158) stops new chart-fact emission but PR 4b deliberately **did not drain** the existing rows. Pre-flight audit on 2026-04-24:

| Metric | Count |
|---|---|
| Rows: `v2_metric_facts WHERE source_type='chart'` | 30 |
| Distinct filings | 10 |
| Reviewer decisions (`v2_review_decisions`) on chart facts | 18 |

The 18 decisions break down as:

| Decision | Count | Metrics |
|---|---|---|
| reject | 9 | cm_new_customers_acquired, cm_customers_period_end (bulk), cm_customers_period_end_by_tenure, cm_active_customers_total, cm_ltv_to_cac_ratio, cm_purchase_transactions_overall, cm_lifetime_value_per_customer, cm_customer_acquisition_cost |
| accept | 5 | cm_revenue_by_cohort (×3), cm_large_customers_period_end, cm_customers_period_end |
| correct | 4 | cm_average_order_value (×2), cm_monthly_active_users, cm_new_customers_acquired |

17 are by reviewer `RGM`, 1 is a bulk-system entry (`bulk:superseded_slack_s1a_2019-05-20`).

`v2_review_decisions.fact_id ON DELETE CASCADE` means a plain `DELETE FROM v2_metric_facts WHERE source_type='chart'` would silently destroy reviewer work. User chose to defer the drain (option B1 in the PR 4b exchange) to preserve those 18 pieces of work.

### Impact (low)

- **Review UI:** Chart Evidence block deleted in PR #151; detected-metrics card reads from `v2_image_assets.detected_metrics`, not `v2_metric_facts`. **No user-visible impact.**
- **Validator:** PR #150 routes `segment_type='chart'` gold rows through presence P/R, not value-level P/R. Chart facts in `v2_metric_facts` are not considered when evaluating chart gold expectations. **No measurement impact.**
- **Analytics views:** `v_analytics_*` views (sql/38, …) may include `source_type='chart'` rows in fact aggregates. If downstream reporting filters on source_type, the 30 residual rows will appear. Typical fix: add `AND source_type != 'chart'` at view level if unwanted. **Low impact, shimmable.**
- **DB footprint:** 30 rows. Negligible.

### Next Steps (if drain becomes needed later)

Three paths, pick at triage time:

1. **Archive decisions + DELETE.** Export the 18 `v2_review_decisions` rows (plus the 30 facts) to `data/audit/chart_fact_decisions_predrain_<ts>.json` for historical reference, then `DELETE FROM v2_metric_facts WHERE source_type='chart'` in a transaction. Reviewer work preserved as JSON, not queryable live.
2. **Migrate accepts + corrects to `v2_image_metric_confirmations`.** For each chart fact with `source_locator.img_id` not null: derive a `(img_id, detected_metric_id=canonical_metric_id, decision)` row. Rejects have no natural img-level equivalent (the "this value is wrong" signal doesn't map cleanly to "this metric is not present"), so rejects would still be lost. Complex but preserves the most work as live signal.
3. **Keep deferred.** No action; residual 30 rows are inert. Revisit only if analytics downstream actually needs them gone.

### Cross-References

- Parent rollout: legacy-096 (chart-presence pivot rollout, resolved).
- Dissolved root cause: legacy-086 (dedup stage collapse).
- Dissolved consequence: legacy-035 (pre-2026-04-17 chart-fact backfill).
- Reviewed-filing guard: `src/extraction_v2/persistence.py::_persist_facts_in_tx`, `ReviewedFilingError`.
- Cascade path: `v2_review_decisions.fact_id ON DELETE CASCADE` (sql/05 originally; `chart_only=True` guard in `persist_pipeline_result` refuses when decisions exist).
