#!/usr/bin/env python3
"""Apply SQL migrations to the database.

Tracks applied migrations in a schema_migrations ledger table. Skips
already-applied migrations. Raises on checksum mismatch to prevent silent
schema drift.

The migration registry is `src.infra.migrations.migration_files()` — a single
source of truth shared with `scripts/apply_all_migrations.py`. There is no
hand-curated list. To add a new migration: place the file under sql/.

Checksum normalization (legacy-095 #3): the checksum strips whole-line SQL
comments (lines whose first non-whitespace token is `--`) before hashing.
Comment-only edits to applied migration files (cluster-DDL markers, operator
notes, doc fixes) therefore do NOT trip the checksum guard. Inline trailing
comments are preserved.

When this normalization first ships, every existing ledger row has the legacy
raw-bytes hash. Reconcile the ledger ONCE per environment with:

    python3 scripts/apply_migrations.py --reconcile-checksums

Run from a shell with DATABASE_URL pointed at the target DB. Idempotent.
The normal apply path stays strict: a stored-vs-computed mismatch raises
RuntimeError exactly as before. Reconciliation is a deliberate operator event,
not silent self-healing.

`_checksum` strips line-leading SQL comments before hashing so cosmetic edits
(e.g. adding a `-- cluster-ddl-ok:` marker, fixing a typo in a header comment)
do not trip the guard. Ledger rows written before this rule existed self-heal
on next encounter — see `apply_migration`.

Usage:
    python3 scripts/apply_migrations.py                     # apply pending
    python3 scripts/apply_migrations.py --test              # use TEST_DATABASE_URL
    python3 scripts/apply_migrations.py --dry-run           # preview only
    python3 scripts/apply_migrations.py --check-checksums   # read-only audit
    python3 scripts/apply_migrations.py --reconcile-checksums  # update ledger
"""

import argparse
import hashlib
import logging
import os
import re
import sys
from pathlib import Path

from dotenv import load_dotenv

# Add repo root to path before importing from src/
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.infra.db import DatabaseAdapter
from src.infra.logging_config import configure_logging
from src.infra.migrations import migration_files

configure_logging(level="INFO")
logger = logging.getLogger(__name__)

# Canonical migration list — derived from sql/*.sql at import time.
# Re-exported as a module-level constant for backward compat with the test
# suite (tests/unit/test_apply_migrations.py, tests/integration/conftest.py,
# tests/integration/test_migration_safety.py).
MIGRATIONS: list[str] = migration_files()

BOOTSTRAP_DDL = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    id            TEXT PRIMARY KEY,
    applied_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    checksum      TEXT NOT NULL
);
"""

_COMMENT_LINE = re.compile(r"^\s*--")


def _checksum(sql: str) -> str:
    """SHA-256 of the migration with whole-line `--` comments stripped.

    Only lines whose first non-whitespace token is `--` are dropped; inline
    trailing comments (`SELECT 1; -- note`) are preserved. See module
    docstring for rationale.
    """
    lines = [ln for ln in sql.splitlines() if not _COMMENT_LINE.match(ln)]
    return hashlib.sha256("\n".join(lines).encode()).hexdigest()


def _checksum_legacy(sql: str) -> str:
    """Pre-normalization SHA-256 of raw file bytes.

    Used only by --reconcile-checksums / --check-checksums to recognize
    ledger rows that were applied before the normalization shipped.
    """
    return hashlib.sha256(sql.encode()).hexdigest()


def bootstrap_ledger(db: DatabaseAdapter) -> None:
    """Create schema_migrations table if it doesn't exist."""
    with db.get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(BOOTSTRAP_DDL)


def apply_migration(
    db: DatabaseAdapter,
    sql_dir: Path,
    migration_name: str,
    dry_run: bool = False,
) -> str:
    """Apply a single migration atomically with ledger tracking.

    Returns:
        "applied"  - migration was applied now
        "skipped"  - migration already in ledger (checksum matches)

    Raises:
        RuntimeError: if migration is in ledger with a different checksum
        FileNotFoundError: if SQL file doesn't exist
    """
    sql_file = sql_dir / migration_name
    sql = sql_file.read_text()
    chk = _checksum(sql)

    rows = db.query(
        "SELECT checksum FROM schema_migrations WHERE id = %(id)s",
        {"id": migration_name},
    )

    if rows:
        stored_checksum = rows[0]["checksum"]
        if stored_checksum != chk:
            # Self-heal the rule-change transition: a ledger row written before
            # `_checksum` started stripping comments may match the legacy raw-byte
            # hash even though it no longer matches the new-rule hash. Proves the
            # file is byte-identical to what was applied — update the ledger row only.
            if stored_checksum == _checksum_legacy(sql):
                with db.get_connection() as conn:
                    with conn.cursor() as cur:
                        cur.execute(
                            "UPDATE schema_migrations SET checksum = %(checksum)s "
                            "WHERE id = %(id)s",
                            {"checksum": chk, "id": migration_name},
                        )
                logger.info(
                    f"  RECONCILED: {migration_name} (rule-change checksum update)"
                )
                return "skipped"
            raise RuntimeError(
                f"Checksum mismatch for {migration_name}: "
                f"expected {stored_checksum[:8]}…, got {chk[:8]}…. "
                "Migration file was modified after it was applied. "
                "If the edit is comment-only, run "
                "`python3 scripts/apply_migrations.py --reconcile-checksums`."
            )
        return "skipped"

    if dry_run:
        logger.info(f"  [DRY RUN] Would apply: {migration_name} ({chk[:8]}…)")
        return "applied"

    with db.get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql)
            cur.execute(
                "INSERT INTO schema_migrations (id, checksum) VALUES (%(id)s, %(checksum)s)",
                {"id": migration_name, "checksum": chk},
            )

    return "applied"


def reconcile_checksums(
    db: DatabaseAdapter,
    sql_dir: Path,
    dry_run: bool = False,
) -> int:
    """Reconcile schema_migrations checksums to the new comment-stripped rule.

    For each ledger row:
      * If stored == new_checksum(file)  → log OK, leave alone.
      * If stored == legacy_checksum(file) → UPDATE to new_checksum (RECONCILED).
      * If file missing on disk → log ORPHAN.
      * Otherwise → log WARN (genuine post-application drift).

    Returns the count of WARN rows. Caller exits non-zero if > 0.
    """
    rows = db.query("SELECT id, checksum FROM schema_migrations ORDER BY id")
    reconciled = ok = warn = orphan = 0

    for row in rows:
        name = row["id"]
        stored = row["checksum"]
        sql_file = sql_dir / name
        if not sql_file.exists():
            logger.warning(f"  ORPHAN: {name} (no file in {sql_dir})")
            orphan += 1
            continue

        sql = sql_file.read_text()
        new_chk = _checksum(sql)
        if stored == new_chk:
            logger.info(f"  OK:         {name}")
            ok += 1
            continue

        legacy_chk = _checksum_legacy(sql)
        if stored == legacy_chk:
            if dry_run:
                logger.info(f"  [DRY RUN] Would reconcile: {name}")
            else:
                with db.get_connection() as conn:
                    with conn.cursor() as cur:
                        cur.execute(
                            "UPDATE schema_migrations SET checksum = %(c)s WHERE id = %(i)s",
                            {"c": new_chk, "i": name},
                        )
                logger.info(f"  RECONCILED: {name} ({stored[:8]}… → {new_chk[:8]}…)")
            reconciled += 1
            continue

        logger.error(
            f"  WARN: {name} — stored {stored[:8]}… matches neither legacy "
            f"({legacy_chk[:8]}…) nor new ({new_chk[:8]}…). "
            "File was modified after application; manual investigation required."
        )
        warn += 1

    logger.info("")
    logger.info("=" * 80)
    logger.info(
        f"Reconcile complete: {reconciled} reconciled, {ok} ok, "
        f"{warn} warn, {orphan} orphan"
        + (" [DRY RUN — no changes made]" if dry_run else "")
    )
    logger.info("=" * 80)
    return warn


def main():
    load_dotenv()
    parser = argparse.ArgumentParser(description="Apply SQL migrations")
    parser.add_argument(
        "--test",
        action="store_true",
        help="Use TEST_DATABASE_URL instead of DATABASE_URL",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would be applied / reconciled without making changes",
    )
    parser.add_argument(
        "--reconcile-checksums",
        action="store_true",
        help=(
            "Update schema_migrations rows whose stored checksum matches the "
            "legacy raw-bytes hash to use the new comment-stripped hash. "
            "Idempotent. Exit non-zero on any unrecognized drift."
        ),
    )
    parser.add_argument(
        "--check-checksums",
        action="store_true",
        help=(
            "Read-only audit: same enumeration as --reconcile-checksums but "
            "never writes. Useful for pre-merge verification."
        ),
    )
    args = parser.parse_args()

    if args.reconcile_checksums and args.check_checksums:
        logger.error("--reconcile-checksums and --check-checksums are mutually exclusive")
        sys.exit(2)

    if args.test:
        db_url = os.getenv("TEST_DATABASE_URL")
        if not db_url:
            logger.error("TEST_DATABASE_URL environment variable not set")
            sys.exit(1)
        logger.info("Using TEST_DATABASE_URL")
    else:
        db_url = os.getenv("DATABASE_URL")
        if not db_url:
            logger.error("DATABASE_URL environment variable not set")
            sys.exit(1)

    db = DatabaseAdapter(db_url)
    sql_dir = Path(__file__).parent.parent / "sql"

    if args.reconcile_checksums or args.check_checksums:
        mode = "Reconciling checksums" if args.reconcile_checksums else "Checking checksums"
        logger.info("=" * 80)
        logger.info(mode + (" [DRY RUN]" if args.dry_run else ""))
        logger.info("=" * 80)
        logger.info("")
        bootstrap_ledger(db)
        warn_count = reconcile_checksums(
            db, sql_dir, dry_run=args.check_checksums or args.dry_run
        )
        sys.exit(1 if warn_count > 0 else 0)

    logger.info("=" * 80)
    logger.info("Applying SQL Migrations" + (" [DRY RUN]" if args.dry_run else ""))
    logger.info("=" * 80)
    logger.info("")

    if not args.dry_run:
        bootstrap_ledger(db)

    applied_count = 0
    skipped_count = 0

    for migration_name in MIGRATIONS:
        sql_file = sql_dir / migration_name
        if not sql_file.exists():
            logger.warning(f"Migration file not found: {sql_file}")
            continue

        try:
            result = apply_migration(db, sql_dir, migration_name, dry_run=args.dry_run)
        except RuntimeError as e:
            logger.error(f"HALTED: {e}")
            sys.exit(1)

        if result == "applied":
            applied_count += 1
            if not args.dry_run:
                logger.info(f"  APPLIED:  {migration_name}")
        else:
            skipped_count += 1
            logger.info(f"  SKIPPED:  {migration_name} (already applied)")

    logger.info("")
    logger.info("=" * 80)
    logger.info(
        f"Done: {applied_count} applied, {skipped_count} skipped"
        + (" [DRY RUN — no changes made]" if args.dry_run else "")
    )
    logger.info("=" * 80)

    # Verify metrics table (skip on dry-run; schema may not exist)
    if not args.dry_run:
        logger.info("")
        logger.info("Verifying metrics...")
        try:
            metrics = db.query(
                "SELECT metric_class, COUNT(*) as count FROM metrics "
                "GROUP BY metric_class ORDER BY metric_class"
            )
            for row in metrics:
                logger.info(f"  {row['metric_class']}: {row['count']} metrics")
        except Exception as e:
            logger.warning(f"Could not verify metrics: {e}")


if __name__ == "__main__":
    main()
