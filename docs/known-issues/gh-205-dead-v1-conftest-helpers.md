---
id: 205
source: gh
slug: dead-v1-conftest-helpers
title: Dead V1 helper functions in tests/integration/conftest.py
status: open
severity: low
autonomy: safe
estimated: XS
touches:
  - tests/integration/conftest.py
discovered: '2026-04-25'
updated: '2026-04-25'
gh_issue: 205
note: Remove create_test_candidate and create_test_decision — call non-existent db methods
---

### Problem

`tests/integration/conftest.py` defines `create_test_candidate()` and
`create_test_decision()` which call `db.insert_review_candidate()` and
`db.insert_review_decision()`. These methods no longer exist in `DatabaseAdapter`
(V1 tables were retired via `sql/31`). No test in `tests/integration/` calls these
helpers, making them dead code. If someone adds a test using them it will fail with
`AttributeError` at runtime.

### Next Steps

- Confirm no integration test calls `create_test_candidate` or `create_test_decision`
  (`grep -r "create_test_candidate\|create_test_decision" tests/`).
- Remove both helper functions from `tests/integration/conftest.py`.
