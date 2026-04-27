#!/usr/bin/env python3
"""Apply all SQL migrations to a PostgreSQL database (dev / fresh-DB runner).

Companion to `scripts/apply_migrations.py` (the prod predeploy runner). Both
scripts consume the same source of truth — `src.infra.migrations.migration_files()`
— so there is no parallel hand-curated list to drift. To add a migration:
place the file under sql/.

Migration tracking: a `schema_migrations` table records which migrations have
been applied. Already-applied migrations are skipped, making re-runs safe.

Checksum normalization (legacy-095 #3): mirrors `apply_migrations.py`. Whole-line
SQL comments (`^\\s*--`) are stripped before hashing so comment-only edits to
applied migration files do not trip the checksum guard. To reconcile an existing
ledger to the new normalization, use `scripts/apply_migrations.py --reconcile-checksums`.

Usage:
    python3 scripts/apply_all_migrations.py
    DATABASE_URL="postgresql://..." python3 scripts/apply_all_migrations.py
    python3 scripts/apply_all_migrations.py --dry-run
    python3 scripts/apply_all_migrations.py --mark-all-applied

Notes:
    - Several legacy migration prefixes appear twice (04, 08, 09, 10, 11, 12,
      46). Order under alpha sort is dependency-safe; new migrations use
      timestamp filenames (YYYYMMDDHHMM_description.sql) — see
      scripts/new_migration.py.
    - For Neon (cloud PostgreSQL), set DATABASE_URL with sslmode=require:
      postgresql://user:password@host.neon.tech/dbname?sslmode=require
"""

from __future__ import annotations

import argparse
import hashlib
import logging
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.infra.db import DatabaseAdapter
from src.infra.logging_config import configure_logging
from src.infra.migrations import KNOWN_SKIPS, migration_files

configure_logging(level="INFO")
logger = logging.getLogger(__name__)

# Canonical migration order — derived from sql/*.sql at import time. Re-exported
# for backward compat with any caller that still imports MIGRATION_ORDER.
MIGRATION_ORDER: list[str] = migration_files()

# Backward-compat alias. The semantic meaning matches: files in sql/ that are
# NOT migrations (seed/utility SQL, Docker-init-only). Single source of truth
# now lives in src.infra.migrations.KNOWN_SKIPS.
EXCLUDED_FILES: frozenset[str] = KNOWN_SKIPS

_COMMENT_LINE = re.compile(r"^\s*--")


def _checksum(sql: str) -> str:
    """SHA-256 of the migration with whole-line `--` comments stripped.

    Mirrors `scripts.apply_migrations._checksum`. See its docstring for
    rationale.
    """
    lines = [ln for ln in sql.splitlines() if not _COMMENT_LINE.match(ln)]
    return hashlib.sha256("\n".join(lines).encode()).hexdigest()


def check_unregistered_migrations(sql_dir: Path) -> list[str]:
    """Return sql/*.sql filenames that are on disk but neither registered nor explicitly skipped.

    With the source-of-truth consolidation this is a tautology — every
    sql/*.sql is either in `migration_files()` or in `KNOWN_SKIPS` by
    construction — but we keep the function so the existing pre-commit hook
    (`scripts/check_migration_order.py`) keeps working unchanged.
    """
    registered = set(migration_files(sql_dir)) | KNOWN_SKIPS
    on_disk = {f.name for f in sql_dir.glob("*.sql")}
    return sorted(on_disk - registered)


def bootstrap_tracking(db: DatabaseAdapter) -> None:
    """Create schema_migrations table if it does not exist."""
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            id          TEXT PRIMARY KEY,
            applied_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            checksum    TEXT NOT NULL
        )
        """
    )


def get_applied_migrations(db: DatabaseAdapter) -> set[str]:
    """Return the set of migration filenames already recorded as applied."""
    rows = db.query("SELECT id FROM schema_migrations ORDER BY applied_at")
    return {row["id"] for row in rows}


def record_migration(db: DatabaseAdapter, filename: str, checksum: str) -> None:
    """Record a migration as applied (idempotent)."""
    db.execute(
        "INSERT INTO schema_migrations (id, checksum) VALUES (%(id)s, %(checksum)s) "
        "ON CONFLICT (id) DO NOTHING",
        {"id": filename, "checksum": checksum},
    )


def apply_migration(
    db: DatabaseAdapter,
    sql_file: Path,
    dry_run: bool = False,
    mark_only: bool = False,
) -> bool:
    """Apply a single SQL migration file and record it in schema_migrations."""
    if dry_run:
        logger.info(f"  [dry-run] Would apply: {sql_file.name}")
        return True

    chk = _checksum(sql_file.read_text())

    if mark_only:
        record_migration(db, sql_file.name, chk)
        logger.info(f"  [marked] Recorded as applied (not executed): {sql_file.name}")
        return True

    logger.info(f"  Applying: {sql_file.name}")
    try:
        db.execute_script(str(sql_file))
        record_migration(db, sql_file.name, chk)
        logger.info(f"  OK: {sql_file.name}")
        return True
    except Exception as e:
        logger.error(f"  FAILED: {sql_file.name}: {e}")
        return False


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Apply all SQL migrations in canonical order",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print which migrations would be applied vs skipped, without executing",
    )
    parser.add_argument(
        "--mark-all-applied",
        action="store_true",
        help=(
            "Record all migrations as applied WITHOUT running them. "
            "Use once on an existing database set up before tracking was added."
        ),
    )
    parser.add_argument(
        "--database-url",
        type=str,
        help="Database connection string (overrides DATABASE_URL env var)",
    )
    args = parser.parse_args()

    db_url = args.database_url or os.getenv("DATABASE_URL")
    if not db_url and not args.dry_run:
        print(
            "Error: DATABASE_URL not set. Use --database-url or set DATABASE_URL in .env",
            file=sys.stderr,
        )
        sys.exit(1)

    sql_dir = Path(__file__).parent.parent / "sql"

    unregistered = check_unregistered_migrations(sql_dir)
    if unregistered:
        logger.error("Unregistered migration files found in sql/:")
        for f in unregistered:
            logger.error(f"  {f}")
        logger.error(
            "Add them to KNOWN_SKIPS in src/infra/migrations.py if they are "
            "not migrations; otherwise the glob picks them up automatically."
        )
        sys.exit(1)

    logger.info("=" * 70)
    if args.dry_run:
        logger.info("Migration dry run (no changes will be made)")
    elif args.mark_all_applied:
        logger.info("Marking all migrations as applied WITHOUT executing them")
    else:
        logger.info("Applying SQL migrations")
    logger.info(f"Target: {db_url or '(dry-run)'}")
    logger.info("=" * 70)
    logger.info("")

    db = DatabaseAdapter(db_url or "postgresql://localhost/filings_analysis")

    if not args.dry_run:
        bootstrap_tracking(db)

    applied = get_applied_migrations(db) if not args.dry_run else set()

    missing = []
    skipped_count = 0
    success_count = 0
    fail_count = 0

    for filename in MIGRATION_ORDER:
        sql_file = sql_dir / filename
        if not sql_file.exists():
            logger.warning(f"  MISSING: {filename} (skipped)")
            missing.append(filename)
            continue

        if filename in applied:
            logger.info(f"  SKIP (already applied): {filename}")
            skipped_count += 1
            continue

        ok = apply_migration(
            db,
            sql_file,
            dry_run=args.dry_run,
            mark_only=args.mark_all_applied,
        )
        if ok:
            success_count += 1
        else:
            fail_count += 1
            logger.error("Migration failed — stopping to avoid cascading errors.")
            break

    logger.info("")
    logger.info("=" * 70)
    if args.dry_run:
        logger.info(f"Dry run: {success_count} would be applied, {skipped_count} already applied")
    elif args.mark_all_applied:
        logger.info(f"Marked {success_count} migrations as applied")
    else:
        logger.info(
            f"Complete: {success_count} applied, {skipped_count} skipped, {fail_count} failed"
        )
    if missing:
        logger.warning(f"Missing files ({len(missing)}): {', '.join(missing)}")
    logger.info("=" * 70)

    if fail_count > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
