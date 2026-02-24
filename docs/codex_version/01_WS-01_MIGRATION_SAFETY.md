# 01 - WS-01 Migration Safety and Forward-Only Change Process

## Why This Workstream Exists
Current migration behavior allows destructive SQL replay and lacks migration history checks. This is incompatible with production data safety.

## Primary Touchpoints
1. `scripts/apply_migrations.py`
2. `scripts/setup_test_db.sh`
3. `tests/conftest.py`
4. `sql/` (existing baseline files)
5. `sql/migrations/` (new forward-only migration path)
6. `sql/bootstrap/` (destructive reset/bootstrap-only files)
7. `docs/operations/setup-guide.md`
8. `docs/operations/deployment-guide.md`

## Scope
1. Introduce forward-only migrations tracked by `schema_migrations`.
2. Split destructive bootstrap/reset SQL from production migration SQL.
3. Add an idempotent migration runner (`scripts/apply_forward_migrations.py`).
4. Ensure test database initialization uses the same forward-only contract.

## Out of Scope
1. Full migration framework replacement.
2. Unrelated schema redesign.

## Conflict Resolution from Prior Plans
1. Supersedes the old instruction to execute every `sql/*.sql` alphabetically.
2. Test setup must call forward migration logic, not raw file-order execution.

## Technical Design
1. Add migration ledger table:
2. `schema_migrations(migration_id text primary key, checksum text not null, applied_at timestamptz not null default now())`.
3. Number forward migrations under `sql/migrations/` with immutable filenames.
4. Create `scripts/apply_forward_migrations.py`:
5. Deterministic file ordering.
6. Per-migration checksum verification.
7. Skip already-applied migrations.
8. Fail fast on checksum mismatch.
9. Transaction per migration.
10. Create `scripts/bootstrap_database.py` with `--allow-destructive` guard and environment safety checks.
11. Update test DB setup (`tests/conftest.py` or equivalent) to call forward migration runner APIs.

## Implementation Plan
1. Build migration ledger bootstrap migration.
2. Port safe schema deltas into forward migration files.
3. Relocate destructive SQL to `sql/bootstrap/`.
4. Add migration runner + unit tests.
5. Update test DB fixtures to use forward migrations and fast reset strategy.
6. Update setup/deployment docs to prohibit destructive production usage.

## Test and Validation
1. Unit: initial apply, rerun idempotency, checksum mismatch failure.
2. Integration: existing DB with data survives rerun.
3. Integration: test DB initialization succeeds without `relation does not exist` errors for V2 tables.
4. Manual: run migration runner twice on staging clone; confirm no destructive operations.

## Acceptance Criteria
1. Re-running forward migrations does not drop/truncate existing data.
2. Applied migrations are tracked and checksum-protected.
3. Test fixtures initialize schema via forward migration path only.
4. Production docs contain no destructive migration instruction.

## Rollout and Rollback
1. Rollout: backup DB, run forward migrations, validate schema version and smoke tests.
2. Rollback: restore from backup for unrecoverable operator errors; no destructive rollback scripts in normal flow.

## Deliverables
1. New migration runner and migration ledger.
2. `sql/migrations/` baseline.
3. `sql/bootstrap/` + guarded bootstrap script.
4. Updated docs and migration evidence artifact.
