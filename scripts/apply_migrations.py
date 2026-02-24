#!/usr/bin/env python3
"""
Apply SQL migrations to the database.

Usage:
    python3 scripts/apply_migrations.py          # Uses DATABASE_URL
    python3 scripts/apply_migrations.py --test    # Uses TEST_DATABASE_URL
"""

import argparse
import logging
import os
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.infra.db import DatabaseAdapter
from src.infra.logging_config import configure_logging

configure_logging(level="INFO")
logger = logging.getLogger(__name__)

# Ordered list of schema migrations (dependency order matters).
# Excludes 00_init_databases.sql (Docker-only) and 06_cmasb_analysis_queries.sql (views).
MIGRATIONS = [
    "01_create_schema.sql",
    "02_add_filing_storage.sql",
    "04_add_post_combination.sql",
    "05_add_business_type_exclusions.sql",
    "03_create_analysis_schema.sql",
    "04_seed_metrics_taxonomy.sql",
    "07_create_review_schema.sql",
    "08_add_richness_metadata.sql",
    "08_add_suppressed_candidates.sql",
    "09_create_image_review_schema.sql",
    "09_v2_schema.sql",
    "10_v2_fact_identity_dedup.sql",
]


def apply_migration(db: DatabaseAdapter, sql_file: Path):
    """Apply a SQL migration file."""
    logger.info(f"Applying migration: {sql_file.name}")

    try:
        # Execute SQL script
        db.execute_script(str(sql_file))

        logger.info(f" {sql_file.name} applied successfully")
        return True

    except Exception as e:
        logger.error(f" Failed to apply {sql_file.name}: {e}")
        return False


def main():
    parser = argparse.ArgumentParser(description="Apply SQL migrations")
    parser.add_argument(
        "--test",
        action="store_true",
        help="Use TEST_DATABASE_URL instead of DATABASE_URL",
    )
    args = parser.parse_args()

    if args.test:
        db_url = os.getenv("TEST_DATABASE_URL")
        if not db_url:
            logger.error("TEST_DATABASE_URL environment variable not set")
            sys.exit(1)
        logger.info("Using TEST_DATABASE_URL")
    else:
        db_url = os.getenv(
            "DATABASE_URL", "postgresql://localhost/filings_analysis"
        )

    db = DatabaseAdapter(db_url)

    sql_dir = Path(__file__).parent.parent / "sql"

    migrations = [sql_dir / name for name in MIGRATIONS]

    logger.info("=" * 80)
    logger.info("Applying SQL Migrations")
    logger.info("=" * 80)
    logger.info("")

    success_count = 0
    for migration in migrations:
        if not migration.exists():
            logger.warning(f"Migration file not found: {migration}")
            continue

        if apply_migration(db, migration):
            success_count += 1
        logger.info("")

    logger.info("=" * 80)
    logger.info(
        f"Migrations complete: {success_count}/{len(migrations)} succeeded"
    )
    logger.info("=" * 80)

    # Verify
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
