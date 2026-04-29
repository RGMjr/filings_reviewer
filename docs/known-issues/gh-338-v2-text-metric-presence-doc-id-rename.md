---
id: 338
source: gh
slug: v2-text-metric-presence-doc-id-rename
title: v2_text_metric_presence.doc_id should be renamed to filing_id
status: open
severity: low
autonomy: skip
estimated: S
touches:
- sql/*.sql
- src/extraction_v2/persistence.py
- tests/integration/extraction_v2/test_presence_persistence.py
discovered: '2026-04-29'
updated: '2026-04-29'
gh_issue: 338
note: doc_id is BIGINT FK to filings(filing_id) — same naming smell fixed in gh-324 for four other v2 tables.
---

### Problem

`v2_text_metric_presence.doc_id` is a `BIGINT NOT NULL REFERENCES filings(filing_id)`
column named `doc_id`, the same naming smell that was resolved for
`v2_segments`, `v2_tables`, `v2_image_assets`, and `v2_metric_definitions`
in gh-324. It was explicitly out of scope for that PR but should be
cleaned up for consistency to prevent the same "operator does not exist:
uuid = bigint" bug class for any future cross-join with `v2_documents.doc_id`.

### Next Steps

- Generate a timestamped migration to rename `doc_id → filing_id` on
  `v2_text_metric_presence` (idempotency-guarded via `information_schema`).
- Sweep callsites in `src/extraction_v2/persistence.py`
  (`_persist_text_metric_presence_in_tx`), tests
  (`test_presence_persistence.py`), and any scripts querying the table directly.
