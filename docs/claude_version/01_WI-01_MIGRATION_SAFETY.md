# WI-01: Migration Safety — Forward-Only Ledger

**Branch**: `prod/wi-01-migration-safety`
**Depends on**: Nothing
**Blocks**: WI-03 (landing WIP that includes migration 11)
**Risk level**: High (database schema management)
**Execution**: `/ralph develop --isolated`

---

## Context

`scripts/apply_migrations.py` (122 lines) replays every SQL file in `MIGRATIONS` on every run. The only protection against duplicate execution is SQL-level `IF NOT EXISTS` / `CREATE OR REPLACE`. This means:

- No history of what was applied and when
- A checksum change in a previously-run migration is silently ignored
- No `--dry-run` mode to preview what would be applied
- Re-running after a partial failure re-runs all previously-applied migrations

The file lists 13 migrations but has no mechanism to detect when a new migration has been added vs. already applied.

---

## Implementation

### How the API works (read this first)

`DatabaseAdapter` (in `src/infra/db.py`) has two relevant methods:

- `db.query(sql, params)` → `list[dict]`: run a SELECT, returns rows as dicts
- `db.get_connection()` → context manager that yields a psycopg connection; auto-commits on clean exit, rolls back on exception

`db.get_connection()` is the correct way to share a single connection across multiple statements. The key insight: psycopg3's `cur.execute()` supports multi-statement SQL strings (via the simple query protocol), which is why `execute_script()` already works on migration files with multiple DDL statements.

### Step 1: Bootstrap the `schema_migrations` table inline at startup

Do NOT create a new SQL file. Run the DDL inline at the top of `main()` before any migration logic:

```python
BOOTSTRAP_DDL = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    migration_id  TEXT        PRIMARY KEY,
    checksum      TEXT        NOT NULL,
    applied_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
"""

def main():
    # ... arg parsing, db setup ...

    # Bootstrap ledger table — idempotent, always runs first
    with db.get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(BOOTSTRAP_DDL)

    # Then process MIGRATIONS list normally
    for migration_name in MIGRATIONS:
        ...
```

This resolves the chicken-and-egg problem: the ledger table always exists before any migration is checked against it. The `IF NOT EXISTS` guard makes this idempotent on every subsequent run.

The `MIGRATIONS` list stays as-is (13 entries). No new SQL files.

### Step 2: Rewrite `scripts/apply_migrations.py`

Replace the current 122-line script with a ledger-aware version. The new script must:

1. **Deterministic ordering**: Same `MIGRATIONS` list, same order. Do not glob or auto-discover (too risky — the list has duplicate numeric prefixes; see note below).
2. **Checksum each file**: `hashlib.sha256(content.encode()).hexdigest()`
3. **Skip if already applied with matching checksum**: query the ledger before running
4. **Fail on checksum mismatch**: halt with `RuntimeError` if checksum differs from what's recorded
5. **Per-migration transactions**: migration SQL + ledger INSERT in one `get_connection()` context
6. **`--dry-run` flag**: print status without executing
7. **`--test` flag**: uses `TEST_DATABASE_URL` (preserve existing behavior)

**Key logic (uses `db.get_connection()` directly)**:

```python
import hashlib

def apply_migration(db: DatabaseAdapter, sql_dir: Path, migration_name: str, dry_run: bool = False) -> bool:
    """Apply a single migration. Returns True if applied, False if skipped."""
    migration_path = sql_dir / migration_name
    content = migration_path.read_text()
    checksum = hashlib.sha256(content.encode()).hexdigest()

    # Check ledger — uses db.query() (its own connection, auto-commits)
    rows = db.query(
        "SELECT checksum FROM schema_migrations WHERE migration_id = %(id)s",
        {"id": migration_name},
    )

    if rows:
        if rows[0]["checksum"] != checksum:
            raise RuntimeError(
                f"Checksum mismatch for {migration_name}: "
                f"recorded={rows[0]['checksum'][:8]}..., "
                f"on-disk={checksum[:8]}...\n"
                "Migration file was modified after being applied. "
                "Do not edit committed migrations."
            )
        logger.info(f"  SKIP {migration_name} (already applied)")
        return False

    if dry_run:
        logger.info(f"  DRY-RUN would apply: {migration_name} (checksum={checksum[:8]}...)")
        return False

    # Run migration SQL + ledger INSERT atomically in one connection
    with db.get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(content)  # psycopg3 simple query protocol supports multi-statement SQL
            cur.execute(
                "INSERT INTO schema_migrations (migration_id, checksum) VALUES (%s, %s)",
                [migration_name, checksum],
            )
    # get_connection() auto-commits on clean exit; rolls back on exception

    logger.info(f"  APPLIED {migration_name}")
    return True
```

> **Note on `MIGRATIONS` list naming**: The list has duplicate numeric prefixes (`04_`, `08_`, `09_` each appear twice). This is fine — `migration_name` is the full filename (e.g., `"08_add_richness_metadata.sql"`), which is unique. Never use the numeric prefix alone as an identifier.

### Step 3: Add `--dry-run` argument

```python
parser.add_argument(
    "--dry-run",
    action="store_true",
    help="Print what would be applied without executing",
)
```

When `--dry-run` is set, the script prints each migration's status (would apply / would skip) and exits with code 0.

---

## Files to Modify

| File | Change |
|------|--------|
| `scripts/apply_migrations.py` | Full rewrite (~120 lines → ~180 lines) |

**No new files required.** The ledger table DDL is created inline at startup. No new SQL files. No new scripts.

---

## Acceptance Criteria

- [ ] **Idempotency**: Running the script twice on a clean database applies each migration exactly once. Second run prints "SKIP" for all migrations.
- [ ] **Checksum mismatch**: Mutate the content of `sql/09_v2_schema.sql` after it has been applied (e.g., add a comment). Re-running raises `RuntimeError: Checksum mismatch` and exits non-zero.
- [ ] **Dry-run**: `--dry-run` on a clean database prints "would apply" for all migrations and makes no schema changes (verify `schema_migrations` table is empty after).
- [ ] **Test mode**: `--test` flag uses `TEST_DATABASE_URL`. Integration test initializes a fresh DB and verifies `schema_migrations` has 13 rows.
- [ ] **Partial failure recovery**: If migration 7 fails mid-run (e.g., due to syntax error), migrations 1–6 are in `schema_migrations` and migration 7 is not. Re-running retries only from migration 7 onward.

---

## Verification Commands

```bash
# Idempotency: run twice, second run should show all SKIPs
python3 scripts/apply_migrations.py --test
python3 scripts/apply_migrations.py --test

# Dry-run on fresh test DB
python3 scripts/apply_migrations.py --test --dry-run

# Unit tests
pytest tests/unit/test_apply_migrations.py -v

# Integration test (requires TEST_DATABASE_URL)
pytest tests/integration/test_migration_safety.py -v
```

---

## Unit Test Cases to Write

Create `tests/unit/test_apply_migrations.py` with mocked database:

1. `test_first_run_applies_all`: Fresh DB → all 13 migrations applied → `schema_migrations` has 13 rows
2. `test_second_run_is_noop`: Pre-populated ledger → all migrations skipped
3. `test_checksum_mismatch_raises`: Ledger has migration with different checksum → `RuntimeError` raised
4. `test_dry_run_makes_no_changes`: `--dry-run` → no DB writes, returns applied count = 0
5. `test_partial_ledger_resumes`: Ledger has migrations 1–6 → only 7–13 applied

---

## Rollback

If the script fails after deployment:
- The script does not drop or truncate anything.
- Rollback = revert `scripts/apply_migrations.py` to the previous version. The `schema_migrations` table is harmless if it exists.
- Database state is always recoverable: no destructive operations are introduced.
