#!/usr/bin/env python3
"""
Apply SQL migrations to the database.
"""

import logging
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from infra.db import DatabaseAdapter

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
)
logger = logging.getLogger(__name__)


def apply_migration(db: DatabaseAdapter, sql_file: Path):
    """Apply a SQL migration file."""
    logger.info(f"Applying migration: {sql_file.name}")

    try:
        # Execute SQL script
        db.execute_script(str(sql_file))

        logger.info(f" {sql_file.name} applied successfully")
        return True

    except Exception as e:
        logger.error(f" Failed to apply {sql_file.name}: {e}")
        return False


def main():
    db = DatabaseAdapter("postgresql://localhost/filings_analysis")

    sql_dir = Path(__file__).parent.parent / "sql"

    migrations = [
        sql_dir / "03_create_analysis_schema.sql",
        sql_dir / "04_seed_metrics_taxonomy.sql",
    ]

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
    logger.info(f"Migrations complete: {success_count}/{len(migrations)} succeeded")
    logger.info("=" * 80)

    # Verify
    logger.info("")
    logger.info("Verifying metrics...")
    metrics = db.query("SELECT metric_class, COUNT(*) as count FROM metrics GROUP BY metric_class ORDER BY metric_class")

    for row in metrics:
        logger.info(f"  {row['metric_class']}: {row['count']} metrics")


if __name__ == "__main__":
    main()
