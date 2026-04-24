#!/usr/bin/env python3
"""
Apply all SQL migrations to a PostgreSQL database.

Applies all sql/*.sql files in the canonical order defined below.
Works against any PostgreSQL connection (local Docker, Neon, etc.).

Migration tracking: a schema_migrations table records which migrations have
been applied. Already-applied migrations are skipped, making re-runs safe.

Usage:
    # Apply new migrations (skips already-applied ones)
    python3 scripts/apply_all_migrations.py

    # Apply to a specific database URL
    DATABASE_URL="postgresql://..." python3 scripts/apply_all_migrations.py

    # Dry run (show which would be applied vs skipped without executing)
    python3 scripts/apply_all_migrations.py --dry-run

    # Mark all migrations as applied WITHOUT running them.
    # Use this ONCE on an existing database that was set up before tracking was added.
    python3 scripts/apply_all_migrations.py --mark-all-applied

Notes:
    - Several migration prefixes appear twice (04, 08, 09). The canonical order
      below was determined from file creation history and dependency analysis.
    - For Neon (cloud PostgreSQL), set DATABASE_URL with sslmode=require:
      postgresql://user:password@host.neon.tech/dbname?sslmode=require
"""

import argparse
import hashlib
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
    "26_drop_filing_metric_incidence.sql",
    "27_drop_v1_metric_tables.sql",
    "28_extend_v2_image_assets_review.sql",
    "29_create_v2_image_review_decisions.sql",
    "30_drop_v1_image_review.sql",
    "31_drop_v1_review_tables.sql",
    "32_add_detected_keywords_to_v2_image_assets.sql",
    "33_fix_identity_index.sql",
    "34_dedup_v2_image_assets.sql",
    "35_drop_v2_image_assets_segment_id.sql",
    "36_backfill_presentation_urls.sql",
    "37_create_analytics_role.sql",
    "38_create_analytics_views.sql",
    "39_v2_ingest_batches.sql",
    "40_full_page_scan_and_ocr_provenance.sql",
    "41_normalize_accession_numbers.sql",
    "42_add_detected_metrics_to_v2_image_assets.sql",
    "43_create_v2_image_metric_confirmations.sql",
    "44_extend_image_rejection_reason_enum.sql",
    "45_create_v2_image_classifications.sql",
    "46_v2_text_metric_presence.sql",
    "46_extend_audit_http_method_constraint.sql",
    "47_add_skip_to_image_metric_confirmations.sql",
]

# Non-migration SQL files that live in sql/ but are not schema migrations.
EXCLUDED_FILES = {
    "register_gold_standard_filings.sql",
    "seed_snap_s1a.sql",
}


def _checksum(sql: str) -> str:
    return hashlib.sha256(sql.encode()).hexdigest()


def check_unregistered_migrations(sql_dir: Path) -> list[str]:
    """Return sql/*.sql filenames that are on disk but not in MIGRATION_ORDER."""
    registered = set(MIGRATION_ORDER) | EXCLUDED_FILES
    on_disk = {f.name for f in sql_dir.glob("*.sql")}
    return sorted(on_disk - registered)


def bootstrap_tracking(db: DatabaseAdapter) -> None:
    """Create schema_migrations table if it does not exist."""
    db.execute("""
        CREATE TABLE IF NOT EXISTS schema_migrations (
            id          TEXT PRIMARY KEY,
            applied_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            checksum    TEXT NOT NULL
        )
    """)


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
            "Add these to MIGRATION_ORDER in scripts/apply_all_migrations.py "
            "(or to EXCLUDED_FILES if they are not migrations)."
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
