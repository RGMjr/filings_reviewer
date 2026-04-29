---
autonomy: review
discovered: '2026-04-19'
estimated: M
id: 38
note: Column rename + callsite sweep; needs callsite audit
pr_refs:
- 326
severity: low
slug: v2-metric-facts-doc-id-is-misleadingly-named
source: legacy
status: resolved
title: '`v2_metric_facts.doc_id` Is Misleadingly Named'
touches:
- sql/*.sql
- src/*/*.py
- src/web/routes/*.py
- tests/**/*.py
updated: '2026-04-28'
---

### Problem

`v2_metric_facts.doc_id` is `BIGINT REFERENCES filings(filing_id)` per
`sql/09_v2_schema.sql:18` — i.e., it's a `filing_id`, not a reference to
`v2_documents.doc_id` (which is a separate UUID primary key). The column
name suggests the latter.

This tripped me during Issue #7 hotfix work: `count_review_decisions` in
`scripts/onboard_tickers.py` originally joined
`v2_documents.doc_id (UUID) = v2_metric_facts.doc_id (BIGINT)`, producing
a runtime `operator does not exist: uuid = bigint` error that only fired
in production (fixed in commit `c353e83`). Any future developer writing
a cross-table query is likely to hit the same trap.

### Suggested Fix

Rename `v2_metric_facts.doc_id` → `filing_id` via a migration:

- `sql/NN_rename_metric_facts_doc_id.sql` — `ALTER TABLE v2_metric_facts
  RENAME COLUMN doc_id TO filing_id`.
- Update every caller in `src/` (look for `.doc_id` on fact objects or in
  raw SQL touching `v2_metric_facts`).
- Update `MetricFact` dataclass if the attribute is exposed.
- Identity-tuple logic in `src/extraction_v2/models.py` and
  `src/extraction_v2/persistence.py` references `doc_id` — check.

Not urgent (inline comment in `scripts/onboard_tickers.py` flags the
naming; `count_review_decisions` SQL correct). Queue when `v2_*` has a
broader cleanup window.

### Cross-References

- `sql/09_v2_schema.sql:18` — column definition
- `scripts/onboard_tickers.py::REVIEW_DECISIONS_SQL` — inline caveat comment
- commit `c353e83` — the bug that surfaced this

### Resolution

Renamed `v2_metric_facts.doc_id` → `filing_id` via timestamped migration
`sql/202604282225_rename_v2_metric_facts_doc_id_to_filing_id.sql` (idempotent
`information_schema` existence guard; index `idx_v2_metric_facts_doc_id`
also renamed). Postgres views in the frozen `sql/09`/`sql/38` files store
column references as attnums, so `v_v2_review_decisions`,
`v_analytics_fact_wide`, and `v_analytics_coverage_matrix` continued to
work without recreation — `pg_get_viewdef` now displays the new name.

Callsite sweep covered raw SQL referencing `v2_metric_facts.doc_id` /
`mf.doc_id` / `f.doc_id` in `src/infra/db.py`, `src/extraction_v2/persistence.py`,
`src/universe/onboarding.py`, `src/web/routes/api_unified.py`,
`scripts/{audit_residual_chart_facts,backfill_text_presence,backfill_full_page_ocr,
audit_filing_url_mismatch,repair_filing_url_mismatch,check_image_referential_integrity,
diagnostic_chart_evidence_coverage,export_for_evaluation,convert_v2_to_gold_standard}.py`,
and the corresponding integration tests. The stale caveat comment in
`src/universe/onboarding.py::REVIEW_DECISIONS_SQL` was removed.

**Out of scope (deliberate):** the `MetricFact` dataclass field at
`src/extraction_v2/models.py:320` is named `doc_id` but its value is the
`Document.doc_id` UUID (populated from `context.document.doc_id` in
`stages/fact_construction.py`), and `_fact_to_params` ignores it in favor of
the `filing_id` parameter. Renaming that field to `filing_id` would be
semantically wrong; left untouched. Other `doc_id` columns on
`v2_segments`, `v2_tables`, `v2_image_assets`, and `v2_metric_definitions`
have the same naming smell but were not in scope for this change.
