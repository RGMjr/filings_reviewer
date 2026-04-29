---
id: 333
source: gh
slug: definition-persistence-delete-wrong-column
title: test_definition_persistence fails — DELETE references non-existent doc_id on v2_metric_facts
status: open
severity: medium
autonomy: skip
estimated: —
touches:
  - tests/integration/extraction_v2/test_definition_persistence.py
discovered: 2026-04-29
updated: 2026-04-29
gh_issue: 333
note: Test setup DELETE uses doc_id which does not exist on v2_metric_facts; blocks full-suite pytest locally
---

### Problem

`tests/integration/extraction_v2/test_definition_persistence.py::TestDefinitionPersistence::test_persist_single_definition` fails on the local test DB:

```
psycopg.errors.UndefinedColumn: column "doc_id" does not exist
LINE 1: DELETE FROM v2_metric_facts WHERE doc_id = $1
```

The correct column name on `v2_metric_facts` is not `doc_id`. This predates the gh-289 Scope B work and blocks `pytest -x -q` from completing end-to-end locally (integration tests run after unit tests with `-x`).

### Next Steps

- Find the DELETE in the test setup fixture or persistence adapter that references `doc_id` on `v2_metric_facts`
- Correct the column name to match the actual schema (`document_id` or the appropriate FK column)
- Verify the fix does not break other integration tests
