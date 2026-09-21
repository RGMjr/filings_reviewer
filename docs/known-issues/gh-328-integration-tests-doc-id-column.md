---
id: 328
source: gh
slug: integration-tests-doc-id-column
title: Integration tests broken by doc_id column removal from v2_metric_facts
status: archived
severity: high
autonomy: n/a
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
pr_refs:
  - 326
note: 'Many integration test modules error with "column doc_id does not exist" in v2_metric_facts — schema migration removed/renamed the column but src/infra/db.py and test SQL were not updated'
---

### Problem

Many integration test modules error on every local run with `column "doc_id" does not exist` in `v2_metric_facts`. Affected suites: `tests/integration/extraction_v2/` (8 files), `tests/integration/web/test_v2_review_workflow.py`, `tests/integration/web/test_image_metric_confirmations.py`, `test_migration_safety.py`, `test_onboard_tickers_cli.py`, `test_db_filings_reviewers.py`. The column was apparently renamed or removed in a schema migration but `src/infra/db.py` helper methods and test SQL were not updated.

### Next Steps

- Identify which migration removed/renamed `doc_id` from `v2_metric_facts` (check `sql/` for recent timestamp migrations)
- Update all `db.py` helper methods and test fixtures that still reference `doc_id`
- Verify test DB is migrated to latest schema (run migration suite against `TEST_DATABASE_URL`)

### Resolution

Fixed in PR #326 (`worktree fix+legacy 038 doc id rename`). The migration
`sql/202604282225_rename_v2_metric_facts_doc_id_to_filing_id.sql` formalizes
the rename. All callsites in `src/infra/db.py`, `src/extraction_v2/persistence.py`,
`src/web/routes/api_unified.py`, `src/universe/onboarding.py`, scripts, and
integration tests were updated to reference `filing_id`. All 22 integration
tests in `tests/integration/extraction_v2/test_persistence.py` pass.
