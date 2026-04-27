---
autonomy: safe
discovered: '2026-04-27'
estimated: S
id: 113
severity: medium
slug: test-db-filings-reviewers-v2-documents-missing
source: legacy
status: open
title: test_db_filings_reviewers.py — test_reviewers_aggregates_text_and_image_sources fails on missing v2_documents relation
touches:
  - tests/integration/test_db_filings_reviewers.py
  - sql/
updated: '2026-04-27'
---

### Problem

`tests/integration/test_db_filings_reviewers.py::TestReviewerAggregation::test_reviewers_aggregates_text_and_image_sources` fails on clean `origin/main`:

```
psycopg.errors.UndefinedTable: relation "v2_documents" does not exist
LINE 2: INSERT INTO v2_documents (filing_id, parse_version, ...
```

The test inserts directly into `v2_documents`, but the integration test database setup did not create the V2 schema. Either the test conftest is missing a migration step, the migration registry is out of order (cf. legacy-110), or the per-worker DB isolation fixture (`tests/integration/conftest.py::_isolate_xdist_worker_database`) is skipping V2 tables. Reproducible under `git stash` of all local changes.

This is **not** the same as legacy-076 (which was about *missing tests*; that test was added). This is the test breaking due to schema setup drift.

### Next Steps

- Run the integration conftest migration step manually against the test DB and confirm whether `v2_documents` is created (`\dt v2_*` in `psql`).
- Cross-reference with legacy-110 (migration registry drift between apply scripts) — likely the same root cause.
- Either fix the migration registry / conftest setup, or update the test to skip when V2 schema is absent (last resort).
- Confirm by running `pytest tests/integration/test_db_filings_reviewers.py -x -q`.
