#!/usr/bin/env python3
"""
Re-classify existing filings to detect post-combination SPACs (de-SPACs).

This script:
1. Reads all existing filings from the database
2. Re-runs post-combination detection logic
3. Updates is_post_combination flag and is_in_scope_phase1 as needed

Usage:
    python scripts/reclassify_post_combination.py
    python scripts/reclassify_post_combination.py --dry-run
"""

import argparse
import logging
import os
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv

from src.infra.db import DatabaseAdapter
from src.universe.classifiers import detect_post_combination, is_in_scope_phase1

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
)
logger = logging.getLogger(__name__)


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Re-classify filings to detect post-combination SPACs"
    )
    parser.add_argument(
        "--database-url",
        help="Database connection string (defaults to DATABASE_URL from .env)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be updated but don't commit changes",
    )

    args = parser.parse_args()

    # Load environment
    load_dotenv()
    db_url = args.database_url or os.getenv(
        "DATABASE_URL", "postgresql://localhost/filings_analysis"
    )

    logger.info("=" * 80)
    logger.info("Re-classifying Filings for Post-Combination SPAC Detection")
    logger.info("=" * 80)
    logger.info(f"Database: {db_url}")
    logger.info(f"Dry run: {args.dry_run}")
    logger.info("=" * 80)

    # Set up database connection
    db = DatabaseAdapter(db_url)

    # Get all filings with company names
    logger.info("Loading all filings from database...")
    filings = db.query("""
        SELECT
            f.filing_id,
            f.company_id,
            f.cik,
            f.accession_number,
            f.form_type,
            f.filing_date,
            f.is_spac,
            f.is_first_time_issuer,
            f.is_post_combination,
            f.offering_type,
            f.is_in_scope_phase1,
            c.company_name
        FROM filings f
        JOIN companies c ON f.company_id = c.company_id
        ORDER BY f.filing_date, f.cik
    """)

    logger.info(f"Found {len(filings)} filings to re-classify")

    # Process each filing
    updated_count = 0
    newly_in_scope_count = 0
    newly_out_of_scope_count = 0

    for idx, filing in enumerate(filings):
        if (idx + 1) % 1000 == 0:
            logger.info(f"Processed {idx + 1} / {len(filings)} filings...")

        # Detect post-combination
        has_prior_spac = db.has_prior_spac_filing(filing['cik'], filing['filing_date'])
        is_post_comb, method = detect_post_combination(
            company_name=filing['company_name'],
            filing_text=None,  # v0.1: no filing text yet
            is_spac=filing['is_spac'] or False,
            has_prior_spac_filing=has_prior_spac,
        )

        # Determine new scope
        new_in_scope = is_in_scope_phase1(
            is_spac=filing['is_spac'] or False,
            is_first_time_issuer=filing['is_first_time_issuer'] or False,
            offering_type=filing['offering_type'],
            form_type=filing['form_type'],
            is_post_combination=is_post_comb,
        )

        # Check if anything changed
        old_is_post_comb = filing['is_post_combination'] or False
        old_in_scope = filing['is_in_scope_phase1'] or False

        if is_post_comb != old_is_post_comb or new_in_scope != old_in_scope:
            updated_count += 1

            if new_in_scope and not old_in_scope:
                newly_in_scope_count += 1
                logger.info(
                    f"  ✓ Filing {filing['accession_number']} now IN SCOPE "
                    f"(post_combination={is_post_comb}, method={method})"
                )
            elif not new_in_scope and old_in_scope:
                newly_out_of_scope_count += 1
                logger.info(
                    f"  ✗ Filing {filing['accession_number']} now OUT OF SCOPE"
                )

            # Update database (if not dry run)
            if not args.dry_run:
                db.execute(
                    """
                    UPDATE filings
                    SET
                        is_post_combination = %(is_post_combination)s,
                        is_in_scope_phase1 = %(is_in_scope_phase1)s,
                        updated_at = now()
                    WHERE filing_id = %(filing_id)s
                    """,
                    {
                        "filing_id": filing['filing_id'],
                        "is_post_combination": is_post_comb,
                        "is_in_scope_phase1": new_in_scope,
                    },
                )

    logger.info("=" * 80)
    logger.info("Re-classification Complete!")
    logger.info("=" * 80)
    logger.info(f"  Total filings processed: {len(filings)}")
    logger.info(f"  Filings updated: {updated_count}")
    logger.info(f"  Newly in scope: {newly_in_scope_count}")
    logger.info(f"  Newly out of scope: {newly_out_of_scope_count}")
    logger.info("=" * 80)

    if args.dry_run:
        logger.warning("DRY RUN: No changes were committed to database")
    else:
        logger.info("✓ All changes committed to database")

    # Show updated stats
    logger.info("")
    logger.info("Updated Coverage Statistics:")
    logger.info("-" * 80)

    stats = {
        'in_scope': db.query("SELECT COUNT(*) as count FROM filings WHERE is_in_scope_phase1 = true")[0]['count'],
        'post_combination': db.query("SELECT COUNT(*) as count FROM filings WHERE is_post_combination = true")[0]['count'],
        'spacs': db.query("SELECT COUNT(*) as count FROM filings WHERE is_spac = true")[0]['count'],
    }

    logger.info(f"  In-scope Phase 1 filings: {stats['in_scope']}")
    logger.info(f"  Post-combination SPACs: {stats['post_combination']}")
    logger.info(f"  Total SPACs (all types): {stats['spacs']}")
    logger.info("-" * 80)

    logger.info("")
    logger.info("Done!")


if __name__ == "__main__":
    main()
