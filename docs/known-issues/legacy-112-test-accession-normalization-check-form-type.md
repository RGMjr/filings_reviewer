---
autonomy: safe
discovered: '2026-04-27'
estimated: S
id: 112
severity: medium
slug: test-accession-normalization-check-form-type
source: legacy
status: open
title: tests/integration/infra/test_accession_normalization.py — all upsert tests fail on check_form_type
touches:
  - tests/integration/infra/test_accession_normalization.py
  - sql/
updated: '2026-04-27'
---

### Problem

On clean `origin/main`, every test in `TestUpsertFilingNormalizes` (e.g. `test_path_prefixed_accession_stored_as_bare_token`, `test_bare_token_unchanged`) fails with:

```
psycopg.errors.CheckViolation: new row for relation "filings" violates check constraint "check_form_type"
DETAIL: Failing row contains (..., 8-K, 2023-11-01, ...)
```

The tests insert filings with `form_type = '8-K'`, but the live schema's `check_form_type` constraint apparently no longer permits `8-K`. Either the constraint tightened (S-1/F-1 only) or the test fixture was never updated when the constraint changed. Reproducible under `git stash` of all local changes.

### Next Steps

- Inspect the live `check_form_type` constraint definition: `psql -c "\d+ filings"` against the test database, or grep `sql/` for `check_form_type`.
- If the constraint is correct (S-1/F-1 only by design), update the test fixtures to use a permitted form type.
- If the constraint is wrong (over-tightened), restore `8-K` to the allowed set via a new migration.
- Verify the fix by running `pytest tests/integration/infra/test_accession_normalization.py -x -q`.
