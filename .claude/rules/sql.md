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

Use `python3 -c 'from datetime import datetime, timezone; print(datetime.now(timezone.utc).strftime("%Y%m%d%H%M"))'` if you need to inspect the current timestamp manually.

## Legacy Files (frozen)

`sql/00_*.sql` through `sql/46_*.sql` use a legacy zero-padded integer scheme
(`NN_description.sql`). Several prefixes have *two* files (04, 08, 09, 10, 11,
12, 46) — relics of parallel-branch collisions that the timestamp scheme now
prevents. **Do not rename these files.** Their filenames are PK values in
`schema_migrations` on every prod, dev, and test database; renaming would
break the ledger.

You may freely edit a legacy file's body (comment fixes, etc.) — the
`migration-name-guard` only inspects newly *added* files.

## Ordering Authority

The **canonical apply order** is the `MIGRATION_ORDER` list in
`scripts/apply_all_migrations.py`. Filename prefixes are informational; the
runtime never sorts by filename. After creating a new migration:

1. Append its filename to `MIGRATION_ORDER`.
2. Pre-commit hook `migration-order-check`
   (`scripts/check_migration_order.py`) fails the commit if you forget.

Among legacy duplicate prefixes the list dictates order — see the existing
entries for the canonical sequence.

## FK Dependency Rules

- A migration may only reference tables defined in **earlier-listed**
  migrations (`MIGRATION_ORDER` order, not filename order).
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
3. Append the filename to `MIGRATION_ORDER` in
   `scripts/apply_all_migrations.py`.
4. If the migration adds tables/columns used by Python code, update
   `src/infra/db.py` in the same commit.
5. Test locally before committing:
   `psql $TEST_DATABASE_URL -f sql/<timestamp>_<description>.sql`
6. Commit. The three pre-commit hooks
   (`migration-name-guard`, `migration-order-check`, `cluster-ddl-guard`)
   run automatically.
