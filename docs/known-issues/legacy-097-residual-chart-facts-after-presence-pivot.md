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
pr_refs:
- 301
severity: low
slug: residual-chart-facts-after-presence-pivot
source: legacy
status: archived
title: Residual Chart Facts Remain After Chart-Presence Pivot (Drain Deferred)
touches: []
updated: '2026-04-28'
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
3. **Keep deferred (current default).** No action; residual 30 rows are inert. **Drain intentionally deferred indefinitely; reviewer decisions preserved.** Revisit only if analytics downstream actually reports impact from the residual rows.

### Cross-References

- Parent rollout: legacy-096 (chart-presence pivot rollout, resolved).
- Dissolved root cause: legacy-086 (dedup stage collapse).
- Dissolved consequence: legacy-035 (pre-2026-04-17 chart-fact backfill).
- See also legacy-053 — chart OCR dollar budget on the same pipeline post-pivot; both are residual-concern fragments rooted in the chart-presence transition.
- Reviewed-filing guard: `src/extraction_v2/persistence.py::_persist_facts_in_tx`, `ReviewedFilingError`.
- Cascade path: `v2_review_decisions.fact_id ON DELETE CASCADE` (sql/05 originally; `chart_only=True` guard in `persist_pipeline_result` refuses when decisions exist).

### Resolution

Drained the 30 residual chart `v2_metric_facts` rows on **2026-04-28** via direct SQL DELETE in a single transaction (Option 1 from the original deferred-next-steps list). The pivot from the planned Option 2 (`chart_only --force-reextract` with lifted budget) is recorded below.

**Measured outcome (post-drain audit, `scripts/audit_residual_chart_facts.py`):**

| Quantity | Pre-drain | Post-drain |
|---|---|---|
| `v2_metric_facts WHERE source_type='chart'` | 30 | **0** |
| Chart-fact reviewer decisions (CASCADE-destroyed, intentional) | 28 | **0** |
| Text-fact reviewer decisions on the 10 affected filings | 146 | **146** (unchanged) |
| Image-metric confirmations on PYPL filing 1753 | 3 | **4** (unchanged by drain; +1 from concurrent reviewer action) |
| Vision API spend | — | $2–5 (from the abandoned Option-2 attempt) |

The 28 destroyed decisions accumulated to 28 (from 18 at fragment-write time on 2026-04-24) over the four-day deferral window. Pre-drain breakdown was 17 by `RGM` (15 reject / accept / correct) plus 1 bulk-system entry; the additional 10 since 2026-04-24 followed the same shape.

**Why a direct DELETE replaced the planned `chart_only --force-reextract`:** the Option-2 attempt ran the full pipeline on all 10 filings (`scripts/batch_v2_extraction.py --chart-only --force-reextract`) and produced **zero** purge-warning log lines. Investigation (`src/extraction_v2/persistence.py:1038-1042`) showed that `_persist_facts_in_tx` early-returns on `if not facts: return 0` *before* the reviewed-filing guard and the DELETE — and the post-pivot pipeline emits zero chart-source facts (`enable_chart_candidate_emission=False`), so the filter at line 1039 always produces an empty list. The drain branch is therefore unreachable post-pivot. Documented separately as a follow-up (see "Follow-ups discovered" below). The marginal benefit Option 2 was sized for — refreshing `v2_image_assets.detected_metrics` to seed the per-image review queue — was also measured at zero usable signal: only 1 of 128 surviving chart-classified images gained a `detected_metrics` entry across 7 successful filings, and 3 of 10 filings could not even ingest because their `html_storage_path` still pointed at unhydrated OneDrive files.

**Pre-drain archive:** `data/audit/chart_fact_drain_predrain_<UTC-ts>.csv` (gitignored). Captures all 30 facts joined to all 28 reviewer decisions, including `decision`, `assigned_metric_id`, `corrected_value`, `rejection_reason`, `rejection_category`, and `reviewer_notes`. Recoverable as JSON if specific decisions ever need to be cited.

**Follow-ups discovered:**
- `chart_only=True` is a no-op post-pivot — the early-return at `persistence.py:1041-1042` defeats the drain branch when the pipeline emits zero chart facts (now always). Should be filed as a separate fix.
- 5 of the 10 affected filings have stale `filings.html_storage_path` values pointing at unhydrated OneDrive paths with NULL `html_content` (filing_ids 1539, 1544, 1546, 1548, 1551). Re-extraction on those filings fails ingestion; canonical local copies live under `data/gold_standard/<Company>/filing.html`.
- Long-haul: filings could move to R2 (analogous to image bytes) to remove local-disk / OneDrive dependency entirely.
