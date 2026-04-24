---
autonomy: safe
discovered: '2026-04-24'
estimated: S
id: 105
severity: low
slug: v2-audit-log-relation-missing-in-test-db
source: legacy
status: open
title: v2_audit_log Relation Missing in Test DB Causes Log Noise
touches:
  - sql/
  - tests/integration/conftest.py
updated: '2026-04-24'
---

### Problem

Integration test runs emit repeated ERROR-level log lines:

```
Database error, rolling back: relation "v2_audit_log" does not exist
LINE 2:             INSERT INTO v2_audit_log (
```

The table exists in prod but is absent from the test DB. Tests still pass
(the insert is best-effort and the error is swallowed), but the noise can
mask real errors and is confusing to read. Likely caused by a migration that
creates `v2_audit_log` not being registered in `scripts/apply_migrations.py`
MIGRATIONS list.

### Next Steps

- Identify which SQL file creates `v2_audit_log` (`grep -rl v2_audit_log sql/`).
- If the migration exists but isn't registered in `MIGRATIONS`, add it.
- If the table was never migrated (created out-of-band), add a migration.
- Verify the insert is already guarded (`IF NOT EXISTS` / exception catch) so
  the production code path is not affected.
