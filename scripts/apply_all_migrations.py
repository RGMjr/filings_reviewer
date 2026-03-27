#!/usr/bin/env python3
"""
Apply all SQL migrations to a PostgreSQL database.

Applies all sql/*.sql files in the canonical order defined below.
Works against any PostgreSQL connection (local Docker, Neon, etc.).

Usage:
    # Apply to database from environment
    python3 scripts/apply_all_migrations.py

    # Apply to a specific database URL
    DATABASE_URL="postgresql://..." python3 scripts/apply_all_migrations.py

    # Dry run (show order without applying)
    python3 scripts/apply_all_migrations.py --dry-run

Notes:
    - Several migration prefixes appear twice (04, 08, 09). The canonical order
      below was determined from file creation history and dependency analysis.
    - Most migrations are idempotent (use CREATE TABLE IF NOT EXISTS, etc.),
      so re-running is safe on an already-migrated database.
    - For Neon (cloud PostgreSQL), set DATABASE_URL with sslmode=require:
      postgresql://user:password@host.neon.tech/dbname?sslmode=require
"""

import argparse
import logging
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.infra.db import DatabaseAdapter
from src.infra.logging_config import configure_logging

configure_logging(level="INFO")
logger = logging.getLogger(__name__)

# Canonical migration order.
# Files with duplicate numeric prefixes (04, 08, 09) are listed explicitly
# in the order they should be applied.
MIGRATION_ORDER = [
    "00_init_databases.sql",
    "01_create_schema.sql",
    "02_add_filing_storage.sql",
    "03_create_analysis_schema.sql",
    "04_add_post_combination.sql",
    "04_seed_metrics_taxonomy.sql",
    "05_add_business_type_exclusions.sql",
    "06_cmasb_analysis_queries.sql",
    "07_create_review_schema.sql",
    "08_add_richness_metadata.sql",
    "08_add_suppressed_candidates.sql",
    "09_create_image_review_schema.sql",
    "09_v2_schema.sql",
    "10_add_html_content_column.sql",
    "10_v2_fact_identity_dedup.sql",
    "11_transcript_support.sql",
    "11_v2_definitions.sql",
    "12_drop_v1_fk_constraints.sql",
    "12_v2_documents_transcript_columns.sql",
    "13_transcript_section_types.sql",
    "14_presentation_section_types.sql",
]


def apply_migration(db: DatabaseAdapter, sql_file: Path, dry_run: bool = False) -> bool:
    """Apply a single SQL migration file."""
    if dry_run:
        logger.info(f"  [dry-run] Would apply: {sql_file.name}")
        return True

    logger.info(f"  Applying: {sql_file.name}")
    try:
        db.execute_script(str(sql_file))
        logger.info(f"  OK: {sql_file.name}")
        return True
    except Exception as e:
        logger.error(f"  FAILED: {sql_file.name}: {e}")
        return False


def main():
    parser = argparse.ArgumentParser(
        description="Apply all SQL migrations in canonical order",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the migration order without executing anything",
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

    logger.info("=" * 70)
    logger.info("Applying all SQL migrations")
    if args.dry_run:
        logger.info("(dry run — no changes will be made)")
    else:
        logger.info(f"Target: {db_url}")
    logger.info("=" * 70)
    logger.info("")

    db = DatabaseAdapter(db_url or "postgresql://localhost/filings_analysis")

    missing = []
    success_count = 0
    fail_count = 0

    for filename in MIGRATION_ORDER:
        sql_file = sql_dir / filename
        if not sql_file.exists():
            logger.warning(f"  MISSING: {filename} (skipped)")
            missing.append(filename)
            continue

        ok = apply_migration(db, sql_file, dry_run=args.dry_run)
        if ok:
            success_count += 1
        else:
            fail_count += 1
            logger.error("Migration failed — stopping to avoid cascading errors.")
            break

    logger.info("")
    logger.info("=" * 70)
    if args.dry_run:
        logger.info(f"Dry run complete: {success_count} migrations would be applied")
    else:
        logger.info(
            f"Migrations complete: {success_count} succeeded, {fail_count} failed"
        )
    if missing:
        logger.warning(f"Missing files ({len(missing)}): {', '.join(missing)}")
    logger.info("=" * 70)

    if fail_count > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
