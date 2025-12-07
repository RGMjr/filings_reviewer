#!/usr/bin/env python3
"""
Script to build the Phase 1 universe using real SEC EDGAR data.

This script:
1. Connects to the production database
2. Queries SEC EDGAR for S-1/F-1 filings in the specified date range
3. Classifies filings (SPAC, first-time issuer, etc.)
4. Populates companies and filings tables
5. Reports coverage statistics

Usage:
    # Test with a small date range (recommended first)
    python scripts/build_universe_real.py --start-date 2024-01-01 --end-date 2024-01-31

    # Run full Phase 1 date range (2015-2025)
    python scripts/build_universe_real.py --start-date 2015-01-01 --end-date 2025-12-31

    # Dry run (don't commit to database)
    python scripts/build_universe_real.py --start-date 2024-01-01 --end-date 2024-01-31 --dry-run
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
from src.universe.universe_builder import UniverseBuilder
from src.infra.logging_config import configure_logging

configure_logging(level="INFO")
logger = logging.getLogger(__name__)


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Build Phase 1 universe from real SEC EDGAR data"
    )
    parser.add_argument(
        "--start-date",
        required=True,
        help="Start date in ISO format (YYYY-MM-DD)",
    )
    parser.add_argument(
        "--end-date",
        required=True,
        help="End date in ISO format (YYYY-MM-DD)",
    )
    parser.add_argument(
        "--database-url",
        help="Database connection string (defaults to DATABASE_URL from .env)",
    )
    parser.add_argument(
        "--user-agent",
        default="CMASB Filings Analyzer rgmarkey@gmail.com",
        help="User agent for SEC requests (must include contact email)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Fetch and classify filings but don't commit to database",
    )

    args = parser.parse_args()

    # Load environment
    load_dotenv()
    db_url = args.database_url or os.getenv(
        "DATABASE_URL", "postgresql://localhost/filings_analysis"
    )

    logger.info("=" * 80)
    logger.info("Building Phase 1 Universe from Real SEC Data")
    logger.info("=" * 80)
    logger.info(f"Date range: {args.start_date} to {args.end_date}")
    logger.info(f"Database: {db_url}")
    logger.info(f"User agent: {args.user_agent}")
    logger.info(f"Dry run: {args.dry_run}")
    logger.info("=" * 80)

    # Validate user agent includes contact email
    if "@" not in args.user_agent:
        logger.error(
            "User agent must include a contact email address per SEC policy.\n"
            "Example: 'CompanyName contact@example.com'"
        )
        sys.exit(1)

    # Set up database connection
    logger.info("Connecting to database...")
    db = DatabaseAdapter(db_url)

    # Initialize SEC client
    logger.info("Initializing SEC client...")
    sec_client = SECClient(user_agent=args.user_agent)

    # Initialize UniverseBuilder
    builder = UniverseBuilder(sec_client=sec_client, db=db)

    # Build universe
    logger.info("Building universe (this may take a while for large date ranges)...")
    logger.info("SEC imposes a rate limit of ~10 requests/second")

    try:
        in_scope_count = builder.build_universe(
            start_date=args.start_date,
            end_date=args.end_date,
        )

        logger.info("=" * 80)
        logger.info(f"✓ Universe build complete!")
        logger.info(f"  In-scope Phase 1 filings: {in_scope_count}")
        logger.info("=" * 80)

        # Get coverage statistics
        logger.info("Generating coverage statistics...")
        stats = builder.get_coverage_stats()

        logger.info("")
        logger.info("Coverage Statistics:")
        logger.info("-" * 80)
        logger.info(f"  Total companies: {stats['total_companies']}")
        logger.info(f"  Total filings: {stats['total_filings']}")
        logger.info(f"  In-scope filings (Phase 1): {stats['in_scope_filings']}")
        logger.info(f"  SPACs (excluded): {stats['spac_count']}")
        logger.info(f"  First-time issuers: {stats['first_time_issuer_count']}")
        logger.info("")
        logger.info("Filings by year:")
        for year in sorted(stats['by_year'].keys()):
            count = stats['by_year'][year]
            logger.info(f"    {year}: {count}")
        logger.info("-" * 80)

        if args.dry_run:
            logger.warning("DRY RUN: Changes were NOT committed to database")
        else:
            logger.info("✓ All changes committed to database")

    except KeyboardInterrupt:
        logger.warning("\n\nProcess interrupted by user")
        sys.exit(1)
    except Exception as e:
        logger.error(f"\n\nError building universe: {e}", exc_info=True)
        sys.exit(1)

    logger.info("")
    logger.info("Done!")


if __name__ == "__main__":
    main()
