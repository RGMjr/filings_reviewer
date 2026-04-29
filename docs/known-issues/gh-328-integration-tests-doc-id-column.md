---
id: 328
source: gh
slug: integration-tests-doc-id-column
title: Integration tests broken by doc_id column removal from v2_metric_facts
status: open
severity: high
autonomy: skip
estimated: M
touches:
  - src/infra/db.py
  - tests/integration/extraction_v2/**
  - tests/integration/web/test_v2_review_workflow.py
  - tests/integration/web/test_image_metric_confirmations.py
  - tests/integration/test_migration_safety.py
  - tests/integration/test_onboard_tickers_cli.py
  - tests/integration/test_db_filings_reviewers.py
discovered: '2026-04-29'
updated: '2026-04-29'
gh_issue: 328
note: 'Many integration test modules error with "column doc_id does not exist" in v2_metric_facts — schema migration removed/renamed the column but src/infra/db.py and test SQL were not updated'
---

### Problem

Many integration test modules error on every local run with `column "doc_id" does not exist` in `v2_metric_facts`. Affected suites: `tests/integration/extraction_v2/` (8 files), `tests/integration/web/test_v2_review_workflow.py`, `tests/integration/web/test_image_metric_confirmations.py`, `test_migration_safety.py`, `test_onboard_tickers_cli.py`, `test_db_filings_reviewers.py`. The column was apparently renamed or removed in a schema migration but `src/infra/db.py` helper methods and test SQL references were not updated.

### Next Steps

- Identify which migration removed/renamed `doc_id` from `v2_metric_facts` (check `sql/` for recent timestamp migrations)
- Update all `db.py` helper methods and test fixtures that still reference `doc_id`
- Verify test DB is migrated to latest schema (run migration suite against `TEST_DATABASE_URL`)
