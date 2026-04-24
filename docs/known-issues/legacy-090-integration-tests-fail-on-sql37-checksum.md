---
autonomy: n/a
discovered: '2026-04-23'
estimated: S
id: 90
severity: medium
slug: integration-tests-fail-on-sql37-checksum
source: legacy
status: resolved
title: Integration Tests Fail at Startup on sql/37 Migration-Checksum Drift
touches:
  - tests/integration/conftest.py
  - scripts/apply_migrations.py
  - sql/37_create_analytics_role.sql
updated: '2026-04-24'
pr_refs: []
---

### Problem

Running `pytest` without `--ignore=tests/integration` fails before any
test body executes with:

```
RuntimeError: Checksum mismatch for 37_create_analytics_role.sql:
expected e7b06ff3…, got a589d96a…. Migration file was modified
after it was applied.
```

Surfaced today while running the full suite for the B5.x chart-read
commit gate. `sql/37_create_analytics_role.sql` has been edited after
the shared test DB had already applied the earlier content (PRs #111
touched it for hook guards), so the `schema_migrations` checksum no
longer matches the file. Hitting this on any dev machine that rebuilds
its test DB from a snapshot, or that runs integration tests after
pulling a branch that touches migration 37.

Unit-only runs (`pytest --ignore=tests/integration`) are unaffected —
the full 3833-test unit suite passes cleanly. Blast radius is CI
integration jobs + local integration runs.

### Next Steps

- Add a "rebuild test DB" runbook entry under
  `docs/operations/setup-guide.md` documenting the drop/recreate
  workflow when checksums drift after a migration edit.
- Alternatively: loosen `scripts/apply_migrations.py:137` to `WARN` when
  the file is in a known "intentional edit" allowlist (the hook-guard
  migrations) rather than hard-failing. Risky — checksum mismatches
  usually indicate a real problem. Prefer the runbook entry.
- Could also add a `conftest.py` pre-check that drops the
  `schema_migrations` row for a modified migration before re-applying,
  scoped to test DBs only. More invasive.

### Resolution

Implemented Option A: added a `_CHECKSUM_REFRESH_ALLOWLIST` pre-check in
`tests/integration/conftest.py::_apply_migrations_to_test_db`. Before the main
migration loop runs, the fixture computes the current checksum for each allowlisted
migration, compares it against the ledger, and deletes the stale row if they differ.
The normal loop then re-applies the file and records the new checksum. Migration 37
is the only entry in the allowlist. All other checksum mismatches continue to raise
`RuntimeError` as before.
