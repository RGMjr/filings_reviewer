---
autonomy: safe
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

### Resolution

Deleted both stale workaround blocks from
`tests/integration/conftest.py::_apply_migrations_to_test_db`:

1. **`_CHECKSUM_REFRESH_ALLOWLIST` block** — removed the comment referencing
   the `_CHECKSUM_REFRESH_ALLOWLIST` constant (the constant itself had
   already been partially cleaned up on `origin/main`, but the explanatory
   comment referencing it remained alongside the try/except retry).
2. **`try/except RuntimeError("Checksum mismatch")` retry block** — removed
   the entire try/except around `apply_migration` that caught checksum-drift
   errors, deleted the stale ledger row, logged
   `Auto-recovered checksum drift for ...`, and retried. Replaced with a
   plain `apply_migration(db, sql_dir, migration_name)` call so genuine
   checksum drift raises as designed.

The `legacy-095` self-heal in `scripts/apply_migrations.py::apply_migration`
now handles the comment-only-edit failure mode structurally: it computes a
raw-byte hash equality fallback and, when the file is byte-identical to what
was previously applied, performs an in-place ledger `UPDATE` rather than
raising. There is no longer any need for the conftest to pre-empt or catch
these errors.

The cluster-DDL advisory-lock serialization (acquiring `pg_advisory_lock`
on the admin `postgres` DB before the apply loop, released by closing the
connection in the `finally` block) was preserved — it is unrelated to
checksum drift and guards against concurrent `tuple concurrently updated`
races on the cluster-level `metabase_ro` role created by sql/37.
