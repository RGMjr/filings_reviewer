#!/usr/bin/env python3
"""
Apply SQL migrations to the database.

Tracks applied migrations in a schema_migrations ledger table. Skips already-applied
migrations. Raises on checksum mismatch to prevent silent schema drift.

Usage:
    python3 scripts/apply_migrations.py          # Uses DATABASE_URL (required)
    python3 scripts/apply_migrations.py --test    # Uses TEST_DATABASE_URL (required)
    python3 scripts/apply_migrations.py --dry-run # Print what would be applied
"""

import argparse
import hashlib
import logging
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

# Add src to path before importing from it
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.infra.db import DatabaseAdapter
from src.infra.logging_config import configure_logging

configure_logging(level="INFO")
logger = logging.getLogger(__name__)

# Ordered list of schema migrations (dependency order matters).
# Excludes 00_init_databases.sql (Docker-only).
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
    "10_add_html_content_column.sql",
    "10_v2_fact_identity_dedup.sql",
    "11_transcript_support.sql",
    "11_v2_definitions.sql",
    "12_drop_v1_fk_constraints.sql",
    "12_v2_documents_transcript_columns.sql",
    "13_transcript_section_types.sql",
    "14_presentation_section_types.sql",
    "15_rename_cohort_heatmap_to_parfait.sql",
    "16_add_8k_form_type.sql",
    "17_add_cohort_type_to_v2.sql",
    "18_add_presentation_detection_tier.sql",
    "19_add_predicted_relevance.sql",
    "20_add_auto_rejected_status.sql",
    "21_create_image_cache.sql",
    "22_seed_missing_metrics.sql",
    "23_chart_source_dedup.sql",
    "24_add_part_of_date_rejection_category.sql",
    "25_cross_source_confirmation.sql",
    "28_extend_v2_image_assets_review.sql",
    "29_create_v2_image_review_decisions.sql",
    "30_drop_v1_image_review.sql",
    "31_drop_v1_review_tables.sql",
    # NOTE: 33_fix_identity_index.sql was applied to Neon prod out-of-band
    # (identity-index rollout; see docs/KNOWN_ISSUES.md Issue #13) and is not
    # required for CI integration tests to pass — it is a pure index fix with
    # no schema objects the V2 code path depends on.
    "32_add_detected_keywords_to_v2_image_assets.sql",
    "34_dedup_v2_image_assets.sql",
    "35_drop_v2_image_assets_segment_id.sql",
    "36_backfill_presentation_urls.sql",
    "37_create_analytics_role.sql",
    "38_create_analytics_views.sql",
    "39_v2_ingest_batches.sql",
    "40_full_page_scan_and_ocr_provenance.sql",
    "42_add_detected_metrics_to_v2_image_assets.sql",
    "43_create_v2_image_metric_confirmations.sql",
    "44_extend_image_rejection_reason_enum.sql",
    "45_create_v2_image_classifications.sql",
    "46_v2_text_metric_presence.sql",
    "46_extend_audit_http_method_constraint.sql",
    "47_add_skip_to_image_metric_confirmations.sql",
]

BOOTSTRAP_DDL = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    id            TEXT PRIMARY KEY,
    applied_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    checksum      TEXT NOT NULL
);
"""


def _checksum(sql: str) -> str:
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
    """
    Apply a single migration atomically with ledger tracking.

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

    # Check ledger (uses a separate auto-committed connection via db.query)
    rows = db.query(
        "SELECT checksum FROM schema_migrations WHERE id = %(id)s",
        {"id": migration_name},
    )

    if rows:
        stored_checksum = rows[0]["checksum"]
        if stored_checksum != chk:
            raise RuntimeError(
                f"Checksum mismatch for {migration_name}: "
                f"expected {stored_checksum[:8]}…, got {chk[:8]}…. "
                "Migration file was modified after it was applied."
            )
        return "skipped"

    if dry_run:
        logger.info(f"  [DRY RUN] Would apply: {migration_name} ({chk[:8]}…)")
        return "applied"

    # Apply migration SQL + ledger INSERT atomically
    with db.get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql)
            cur.execute(
                "INSERT INTO schema_migrations (id, checksum) VALUES (%(id)s, %(checksum)s)",
                {"id": migration_name, "checksum": chk},
            )

    return "applied"


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
        help="Print what would be applied without making changes",
    )
    args = parser.parse_args()

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
