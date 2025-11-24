#!/usr/bin/env python3
"""
Populate SIC codes for all companies in the database.

This script:
1. Fetches all companies from the database
2. Queries SEC submissions API for SIC code and description
3. Updates the companies table with industry classification data

Usage:
    python scripts/populate_sic_codes.py
    python scripts/populate_sic_codes.py --dry-run
    python scripts/populate_sic_codes.py --limit 100
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
from src.infra.sec_client import SECClient

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
)
logger = logging.getLogger(__name__)


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Populate SIC codes for all companies"
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
    parser.add_argument(
        "--limit",
        type=int,
        help="Limit number of companies to process (for testing)",
    )
    parser.add_argument(
        "--user-agent",
        default="FilingsReviewer/1.0 (contact: info@example.com)",
        help="User agent for SEC requests",
    )

    args = parser.parse_args()

    # Load environment
    load_dotenv()
    db_url = args.database_url or os.getenv(
        "DATABASE_URL", "postgresql://localhost/filings_analysis"
    )

    logger.info("=" * 80)
    logger.info("Populating SIC Codes for Companies")
    logger.info("=" * 80)
    logger.info(f"Database: {db_url}")
    logger.info(f"Dry run: {args.dry_run}")
    if args.limit:
        logger.info(f"Limit: {args.limit} companies")
    logger.info("=" * 80)

    # Set up database connection and SEC client
    db = DatabaseAdapter(db_url)
    sec_client = SECClient(user_agent=args.user_agent)

    # Get all companies that need SIC codes
    logger.info("Loading companies from database...")
    query = """
        SELECT company_id, cik, company_name, industry_code
        FROM companies
        WHERE industry_code IS NULL OR industry_code = ''
        ORDER BY company_id
    """

    if args.limit:
        query += f" LIMIT {args.limit}"

    companies = db.query(query)

    logger.info(f"Found {len(companies)} companies needing SIC codes")

    # Process each company
    updated_count = 0
    error_count = 0
    skipped_count = 0

    for idx, company in enumerate(companies):
        if (idx + 1) % 100 == 0:
            logger.info(f"Processed {idx + 1} / {len(companies)} companies...")

        try:
            # Fetch company info from SEC
            company_info = sec_client.get_company_info(company['cik'])

            if not company_info:
                logger.warning(f"Could not fetch info for CIK {company['cik']}")
                error_count += 1
                continue

            sic_code = company_info.get('sic', '')
            sic_description = company_info.get('sic_description', '')

            # Skip if no SIC code available
            if not sic_code:
                logger.debug(f"No SIC code available for {company['company_name']}")
                skipped_count += 1
                continue

            # Update database (if not dry run)
            if not args.dry_run:
                db.execute(
                    """
                    UPDATE companies
                    SET
                        industry_code = %(sic_code)s,
                        industry_classification_source = 'SEC',
                        updated_at = now()
                    WHERE company_id = %(company_id)s
                    """,
                    {
                        "company_id": company['company_id'],
                        "sic_code": sic_code,
                    },
                )

            updated_count += 1
            logger.debug(
                f"Updated {company['company_name']}: SIC {sic_code} - {sic_description}"
            )

        except Exception as e:
            logger.error(
                f"Error processing company {company['company_name']} (CIK {company['cik']}): {e}",
                exc_info=True,
            )
            error_count += 1

    logger.info("=" * 80)
    logger.info("SIC Code Population Complete!")
    logger.info("=" * 80)
    logger.info(f"  Total companies processed: {len(companies)}")
    logger.info(f"  Successfully updated: {updated_count}")
    logger.info(f"  Skipped (no SIC code): {skipped_count}")
    logger.info(f"  Errors: {error_count}")
    logger.info("=" * 80)

    if args.dry_run:
        logger.warning("DRY RUN: No changes were committed to database")
    else:
        logger.info("✓ All changes committed to database")

    # Show sample of updated companies by SIC category
    if not args.dry_run and updated_count > 0:
        logger.info("")
        logger.info("Sample of SIC Codes Added:")
        logger.info("-" * 80)

        samples = db.query("""
            SELECT
                industry_code,
                COUNT(*) as count,
                STRING_AGG(DISTINCT company_name, ', ') as sample_companies
            FROM companies
            WHERE industry_classification_source = 'SEC'
            AND industry_code IS NOT NULL
            GROUP BY industry_code
            ORDER BY count DESC
            LIMIT 20
        """)

        for row in samples:
            # Truncate sample companies if too long
            sample_names = row['sample_companies']
            if len(sample_names) > 100:
                sample_names = sample_names[:97] + "..."

            logger.info(
                f"  SIC {row['industry_code']}: {row['count']} companies "
                f"(e.g., {sample_names})"
            )
        logger.info("-" * 80)

    logger.info("")
    logger.info("Done!")


if __name__ == "__main__":
    main()
