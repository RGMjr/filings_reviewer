---
autonomy: n/a
discovered: '2026-04-27'
estimated: XS
id: 114
severity: low
slug: stale-conftest-checksum-workarounds-after-self-heal
source: legacy
status: resolved
title: Stale checksum-drift workarounds in tests/integration/conftest.py after self-heal landed
touches:
  - tests/integration/conftest.py
updated: '2026-04-27'
---

### Resolution (2026-04-27)

Both workaround blocks have been removed from
`tests/integration/conftest.py::_apply_migrations_to_test_db`:

- The `_CHECKSUM_REFRESH_ALLOWLIST = {"37_create_analytics_role.sql"}`
  pre-emptive ledger refresh was deleted in a prior cleanup (origin/main
  pre this PR).
- The try/except retry around `apply_migration` that caught any
  `RuntimeError("Checksum mismatch")` on the test DB, deleted the stale
  ledger row, logged `Auto-recovered checksum drift for ...`, and
  re-applied the migration is removed in this PR.

The per-row self-heal in `scripts/apply_migrations.py::apply_migration`
(lines 162–173 — `if stored_checksum == _raw_checksum(sql): UPDATE
schema_migrations SET checksum = ...`) now handles the comment-only-edit
case the workarounds were guarding by proving byte-identity to what was
previously applied and reconciling the ledger row in place. Genuine drift
(neither new-rule nor raw-byte hash matches what's stored) raises as
designed.

The conftest workaround was actively destructive: when `apply_migration`
raised because raw-hash also missed, the workaround deleted the ledger row
and re-ran the SQL — re-applying DDL like
`17_add_cohort_type_to_v2.sql::ALTER TABLE … ADD COLUMN cohort_type` against
a DB where the column already existed produced
`psycopg.errors.DuplicateColumn`, breaking
`tests/integration/infra/test_accession_normalization.py` and the broader
integration suite on developer machines. With both blocks gone, that
failure path no longer exists; legitimate drift on a stale local test DB
is now recoverable by dropping and recreating it (`dropdb` + `createdb`),
not by ledger surgery.

The cluster-DDL advisory-lock serialization
(`SELECT pg_advisory_lock(MIGRATION_LOCK_KEY)` against the `postgres` admin
DB) is unchanged — that protects against concurrent migration application
under `pytest-xdist` and is unrelated to checksum drift.

### Problem

`tests/integration/conftest.py::_apply_migrations_to_test_db` carries two
defensive workarounds that pre-date the comment-stripping `_checksum` rule
+ per-row self-heal landed in `scripts/apply_migrations.py` (legacy-095
Phase-1 finish):

1. **Lines 383–403** — `_CHECKSUM_REFRESH_ALLOWLIST = {"37_create_analytics_role.sql"}`
   pre-emptively `DELETE`s the ledger row for sql/37 when its current
   raw-byte hash differs from the stored checksum, so the normal apply
   loop re-applies it cleanly.
2. **Lines 408–426** — try/except around `apply_migration` that catches
   any `RuntimeError("Checksum mismatch")` on the test DB, deletes the
   stale ledger row, logs `Auto-recovered checksum drift for ...`, and
   retries.

Both were workarounds for the exact failure mode the legacy-095 self-heal
now handles cleanly: when a migration file gains a comment-only edit, the
new-rule hash differs from the stored raw-byte hash, but `apply_migration`
recognizes the file is byte-identical to what was applied (raw hash
matches stored) and `UPDATE`s the ledger row in place.

### Why not fix in legacy-095

The legacy-095 PR was deliberately scoped to `scripts/apply_migrations.py`
+ unit tests + the legacy-095 fragment flip. Touching the integration
conftest expands the diff into a different module and is better as a
follow-up cleanup once the self-heal has soaked in CI for a few runs.

### Next steps

- Confirm the self-heal triggers correctly under the parallel
  `_apply_migrations_to_test_db` path (advisory-lock serialized, per-worker
  DBs) on at least one CI Integration Tests run.
- Delete `_CHECKSUM_REFRESH_ALLOWLIST` and the surrounding pre-emptive
  ledger refresh block.
- Delete the try/except retry branch around `apply_migration`; let the
  self-heal do the work, and let any genuine drift raise as designed.
- Keep the cluster-DDL advisory-lock serialization — that's unrelated to
  checksum drift.

### Cross-references

- legacy-095 — `migrations-drift-from-prod-no-post-deploy-apply` (parent;
  introduced the self-heal that supersedes these workarounds).
- legacy-110 — `migration-registry-drift-between-apply-scripts` (separate
  drift-class issue; not a precondition for this cleanup).
