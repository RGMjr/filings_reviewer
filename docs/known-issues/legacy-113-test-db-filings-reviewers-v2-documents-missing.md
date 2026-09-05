---
autonomy: safe
discovered: '2026-04-27'
estimated: S
id: 113
pr_refs:
  - 265
severity: medium
slug: test-db-filings-reviewers-v2-documents-missing
source: legacy
status: archived
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

### Resolution

Incidentally fixed by the legacy-110 resolution (PR #254 / #255). The root cause was migration registry drift: `scripts/apply_migrations.py::MIGRATIONS` was a hand-curated list that was missing `09_v2_schema.sql` (and several other migrations) relative to what `apply_all_migrations.py::MIGRATION_ORDER` ran. The integration test conftest (`tests/integration/conftest.py::_apply_migrations_to_test_db`) consumed `MIGRATIONS`, so the V2 schema was never created in the test DB — causing the `relation "v2_documents" does not exist` error.

The fix: `src/infra/migrations.py::migration_files()` replaced both hand-curated lists with a single alpha-sorted glob over `sql/*.sql` (minus an explicit KNOWN_SKIPS set). Both apply scripts now import this function, making drift structurally impossible. With the full migration set applied, `09_v2_schema.sql` runs and creates `v2_documents`, and all three tests in `test_db_filings_reviewers.py` pass.

Verified on 2026-04-27: `pytest tests/integration/test_db_filings_reviewers.py -x -q` → 3 passed.
