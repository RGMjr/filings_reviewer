#!/usr/bin/env python3
"""
Re-classify existing filings to detect investment vehicles and resource extraction companies.

This script:
1. Reads all existing filings from the database
2. Re-runs business type classification logic
3. Updates is_investment_vehicle and is_resource_extraction flags
4. Updates is_in_scope_phase1 as needed

Usage:
    python scripts/reclassify_business_types.py
    python scripts/reclassify_business_types.py --dry-run
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
from src.universe.classifiers import (
    classify_investment_vehicle,
    classify_resource_extraction,
    is_in_scope_phase1,
)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
)
logger = logging.getLogger(__name__)


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Re-classify filings for business type exclusions"
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
    logger.info("Re-classifying Filings for Business Type Exclusions")
    logger.info("=" * 80)
    logger.info(f"Database: {db_url}")
    logger.info(f"Dry run: {args.dry_run}")
    logger.info("=" * 80)

    # Set up database connection
    db = DatabaseAdapter(db_url)

    # Get all filings with company names and SIC codes
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
            f.is_investment_vehicle,
            f.is_resource_extraction,
            f.offering_type,
            f.is_in_scope_phase1,
            c.company_name,
            c.industry_code as sic_code
        FROM filings f
        JOIN companies c ON f.company_id = c.company_id
        ORDER BY f.filing_date, f.cik
    """)

    logger.info(f"Found {len(filings)} filings to re-classify")

    # Process each filing
    updated_count = 0
    newly_excluded_count = 0
    investment_vehicle_count = 0
    resource_extraction_count = 0

    for idx, filing in enumerate(filings):
        if (idx + 1) % 1000 == 0:
            logger.info(f"Processed {idx + 1} / {len(filings)} filings...")

        # Classify investment vehicle
        is_investment_vehicle, inv_method = classify_investment_vehicle(
            company_name=filing['company_name'],
            sic_code=filing['sic_code'],
        )

        # Classify resource extraction
        is_resource_extraction, res_method = classify_resource_extraction(
            company_name=filing['company_name'],
            sic_code=filing['sic_code'],
        )

        # Determine new scope
        new_in_scope = is_in_scope_phase1(
            is_spac=filing['is_spac'] or False,
            is_first_time_issuer=filing['is_first_time_issuer'] or False,
            offering_type=filing['offering_type'],
            form_type=filing['form_type'],
            is_post_combination=filing['is_post_combination'] or False,
            is_investment_vehicle=is_investment_vehicle,
            is_resource_extraction=is_resource_extraction,
        )

        # Check if anything changed
        old_is_investment = filing['is_investment_vehicle'] or False
        old_is_resource = filing['is_resource_extraction'] or False
        old_in_scope = filing['is_in_scope_phase1'] or False

        if (is_investment_vehicle != old_is_investment or
            is_resource_extraction != old_is_resource or
            new_in_scope != old_in_scope):

            updated_count += 1

            if is_investment_vehicle and not old_is_investment:
                investment_vehicle_count += 1
                logger.debug(
                    f"  Investment vehicle detected: {filing['company_name']} "
                    f"(SIC {filing['sic_code']}, method={inv_method})"
                )

            if is_resource_extraction and not old_is_resource:
                resource_extraction_count += 1
                logger.debug(
                    f"  Resource extraction detected: {filing['company_name']} "
                    f"(SIC {filing['sic_code']}, method={res_method})"
                )

            if old_in_scope and not new_in_scope:
                newly_excluded_count += 1
                reason = 'investment_vehicle' if is_investment_vehicle else 'resource_extraction'
                logger.info(
                    f"  ✗ Filing {filing['accession_number']} now EXCLUDED "
                    f"({reason}: {filing['company_name']})"
                )

            # Update database (if not dry run)
            if not args.dry_run:
                db.execute(
                    """
                    UPDATE filings
                    SET
                        is_investment_vehicle = %(is_investment_vehicle)s,
                        is_resource_extraction = %(is_resource_extraction)s,
                        is_in_scope_phase1 = %(is_in_scope_phase1)s,
                        updated_at = now()
                    WHERE filing_id = %(filing_id)s
                    """,
                    {
                        "filing_id": filing['filing_id'],
                        "is_investment_vehicle": is_investment_vehicle,
                        "is_resource_extraction": is_resource_extraction,
                        "is_in_scope_phase1": new_in_scope,
                    },
                )

    logger.info("=" * 80)
    logger.info("Re-classification Complete!")
    logger.info("=" * 80)
    logger.info(f"  Total filings processed: {len(filings)}")
    logger.info(f"  Filings updated: {updated_count}")
    logger.info(f"  Investment vehicles detected: {investment_vehicle_count}")
    logger.info(f"  Resource extraction detected: {resource_extraction_count}")
    logger.info(f"  Newly excluded from scope: {newly_excluded_count}")
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
        'investment_vehicles': db.query("SELECT COUNT(*) as count FROM filings WHERE is_investment_vehicle = true")[0]['count'],
        'resource_extraction': db.query("SELECT COUNT(*) as count FROM filings WHERE is_resource_extraction = true")[0]['count'],
    }

    logger.info(f"  In-scope Phase 1 filings: {stats['in_scope']}")
    logger.info(f"  Investment vehicles (excluded): {stats['investment_vehicles']}")
    logger.info(f"  Resource extraction (excluded): {stats['resource_extraction']}")
    logger.info("-" * 80)

    logger.info("")
    logger.info("Done!")


if __name__ == "__main__":
    main()
