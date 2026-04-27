---
paths:
  - "sql/**"
---

# SQL Migration Rules

## Naming Convention (new migrations)

New migrations use a **UTC timestamp prefix**:

```
sql/YYYYMMDDHHMM_<snake_case_description>.sql
```

Generate via the helper — never hand-pick a name:

```bash
python3 scripts/new_migration.py "short description"
```

The helper writes a stub with the standard `BEGIN;` / `COMMIT;` wrapper and a
TODO header. Pre-commit hook `migration-name-guard` rejects any newly added
`sql/*.sql` file that doesn't match `^sql/[0-9]{12}_[a-z0-9_]+\.sql$`.

## Legacy Files (frozen)

`sql/00_*.sql` through `sql/47_*.sql` use a legacy zero-padded integer scheme
(`NN_description.sql`). Several prefixes have *two* files (04, 08, 09, 10, 11,
12, 46) — relics of parallel-branch collisions that the timestamp scheme now
prevents. **Do not rename these files.** Their filenames are PK values in
`schema_migrations` on every prod, dev, and test database; renaming would
break the ledger.

You may freely edit a legacy file's body (comment fixes, etc.) — the
`migration-name-guard` only inspects newly *added* files.

## Ordering Authority

The **canonical migration list** is `src.infra.migrations.migration_files()`,
computed from `sql/*.sql` minus `KNOWN_SKIPS`. Both `scripts/apply_migrations.py`
(prod predeploy) and `scripts/apply_all_migrations.py` (dev runner) consume
this single source. There is no hand-curated list to keep in sync.

Order is filename-lexicographic (alpha sort). To add a migration: place the
file under `sql/` — registration is automatic. To exclude a non-migration SQL
file (seed/utility), add it to `KNOWN_SKIPS` in `src/infra/migrations.py`.

The pre-commit hook `migration-order-check`
(`scripts/check_migration_order.py`) is now a tautology guard against future
shape changes.

## FK Dependency Rules

- A migration may only reference tables defined in **earlier-sorted**
  migrations (alpha-sorted filename order, the same order
  `migration_files()` returns).
- Never forward-reference a table that will be created by a later migration.
- If two migrations are mutually dependent, combine them into one.

## Idempotency

Migrations must be safe to re-run. Every dev/test environment may have
applied a subset already. Use:

- `CREATE TABLE IF NOT EXISTS` / `CREATE INDEX IF NOT EXISTS`
- `ALTER TABLE ... ADD COLUMN IF NOT EXISTS`
- `DROP CONSTRAINT IF EXISTS` before `ADD CONSTRAINT`
- `DO $$ BEGIN ... EXCEPTION WHEN duplicate_object ... END $$;` for ENUM
  value adds and other PostgreSQL-version-dependent DDL

The `apply_all_migrations.py` runner skips entries already recorded in
`schema_migrations` (filename PK + SHA256 checksum), but a partial-apply
state must still re-converge cleanly when the missing entries run.

## Cluster-Scoped DDL

`CREATE/ALTER/DROP` on `ROLE/USER/TABLESPACE/SUBSCRIPTION` races under
parallel apply (pytest-xdist per-worker DBs). Pre-commit hook
`cluster-ddl-guard` blocks these unless the file contains a marker comment
`-- cluster-ddl-ok: <reason>`. Prefer moving cluster-level statements out
of per-DB migrations entirely; see `scripts/pre-commit-cluster-ddl-guard.sh`
for the full rationale.

## Registration Checklist

After creating a migration:

1. `python3 scripts/new_migration.py "<description>"`
2. Edit the body. Use the idempotency patterns above.
3. If the migration adds tables/columns used by Python code, update
   `src/infra/db.py` in the same commit.
4. Test locally before committing:
   `psql $TEST_DATABASE_URL -f sql/<timestamp>_<description>.sql`
5. Commit. The three pre-commit hooks
   (`migration-name-guard`, `migration-order-check`, `cluster-ddl-guard`)
   run automatically. Registration is automatic — `migration_files()` picks up
   any new `sql/*.sql` not in `KNOWN_SKIPS`.
