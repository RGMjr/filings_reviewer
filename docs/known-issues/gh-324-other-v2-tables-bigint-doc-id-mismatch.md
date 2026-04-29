---
id: 324
source: gh
slug: other-v2-tables-bigint-doc-id-mismatch
title: Other v2 tables share v2_metric_facts' BIGINT-named-doc_id mismatch
status: open
severity: low
autonomy: skip
estimated: M
touches:
- sql/*.sql
- src/extraction_v2/persistence.py
- src/infra/db.py
discovered: '2026-04-28'
updated: '2026-04-28'
gh_issue: 324
note: v2_segments / v2_tables / v2_image_assets / v2_metric_definitions doc_id columns are all filing_ids — same legacy-038 trap class.
---

### Problem

`v2_metric_facts.doc_id` was renamed to `filing_id` in legacy-038 because
it is `BIGINT REFERENCES filings(filing_id)` despite the name suggesting
`v2_documents.doc_id` (UUID). The same naming smell applies to four other
v2 tables: `v2_segments.doc_id`, `v2_tables.doc_id`,
`v2_image_assets.doc_id`, and `v2_metric_definitions.doc_id`. All are
`BIGINT NOT NULL REFERENCES filings(filing_id)` and trip the same
`operator does not exist: uuid = bigint` bug class as commit `c353e83`
for any cross-join with `v2_documents.doc_id`.

### Next Steps

- Generate a single timestamped migration that renames `doc_id` →
  `filing_id` on all four tables (idempotent `information_schema` guard
  per table) plus their indices.
- Sweep callsites in `src/extraction_v2/persistence.py` (segments /
  tables / images / definitions INSERT blocks), `src/infra/db.py` JOIN
  sites, integration tests, and scripts.
- Postgres views in frozen `sql/09`/`sql/38` resolve via attnums — no
  view recreation needed (proven in legacy-038).
