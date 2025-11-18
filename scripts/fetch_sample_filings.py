#!/usr/bin/env python3
"""
Script to fetch a sample of filing HTML documents for testing and development.

This script:
1. Queries the database for in-scope filings
2. Downloads a sample set of HTML documents
3. Stores them locally for testing classification and extraction

Usage:
    # Fetch 10 sample filings
    python scripts/fetch_sample_filings.py --limit 10

    # Fetch filings from specific year
    python scripts/fetch_sample_filings.py --year 2024 --limit 20

    # Fetch all unfetched in-scope filings
    python scripts/fetch_sample_filings.py --limit 1000
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
from src.infra.sec_client import FilingMetadata
from src.filing_fetcher.filing_fetcher import FilingFetcher

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
)
logger = logging.getLogger(__name__)


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Fetch sample filing HTML documents"
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=10,
        help="Number of filings to fetch (default: 10)",
    )
    parser.add_argument(
        "--year",
        type=int,
        help="Filter to specific year (e.g., 2024)",
    )
    parser.add_argument(
        "--database-url",
        help="Database connection string (defaults to DATABASE_URL from .env)",
    )
    parser.add_argument(
        "--storage-root",
        default="data/filings",
        help="Root directory for storing filings (default: data/filings)",
    )
    parser.add_argument(
        "--user-agent",
        default="CMASB Filings Analyzer rgmarkey@gmail.com",
        help="User agent for SEC requests",
    )
    parser.add_argument(
        "--skip-txt",
        action="store_true",
        help="Skip fetching complete text files (HTML only)",
    )

    args = parser.parse_args()

    # Load environment
    load_dotenv()
    db_url = args.database_url or os.getenv(
        "DATABASE_URL", "postgresql://localhost/filings_analysis"
    )

    logger.info("=" * 80)
    logger.info("Fetching Sample Filing Documents")
    logger.info("=" * 80)
    logger.info(f"Database: {db_url}")
    logger.info(f"Storage root: {args.storage_root}")
    logger.info(f"Limit: {args.limit}")
    logger.info(f"Year filter: {args.year or 'None'}")
    logger.info(f"Fetch TXT: {not args.skip_txt}")
    logger.info("=" * 80)

    # Set up database connection
    logger.info("Connecting to database...")
    db = DatabaseAdapter(db_url)

    # Initialize FilingFetcher
    logger.info("Initializing FilingFetcher...")
    fetcher = FilingFetcher(
        storage_root=args.storage_root,
        user_agent=args.user_agent,
        db=db,
    )

    # Get unfetched filings
    logger.info("Querying database for unfetched filings...")

    query = """
        SELECT
            c.company_name,
            f.cik,
            f.accession_number,
            f.form_type,
            f.filing_date,
            f.sec_html_url as primary_doc_url,
            f.sec_txt_url as txt_url
        FROM filings f
        JOIN companies c ON f.company_id = c.company_id
        WHERE
            f.is_in_scope_phase1 = true
            AND f.html_fetched_at IS NULL
            AND (f.html_fetch_error IS NULL OR f.html_fetch_error = '')
    """

    params = {}

    if args.year:
        query += " AND EXTRACT(YEAR FROM f.filing_date) = %(year)s"
        params["year"] = args.year

    query += " ORDER BY f.filing_date DESC LIMIT %(limit)s"
    params["limit"] = args.limit

    filings_data = db.query(query, params)

    if not filings_data:
        logger.warning("No unfetched filings found matching criteria")
        return

    logger.info(f"Found {len(filings_data)} unfetched filings to fetch")

    # Convert to FilingMetadata objects
    filings = [
        FilingMetadata(
            cik=f["cik"],
            company_name=f["company_name"],
            form_type=f["form_type"],
            filing_date=str(f["filing_date"]),
            accession_number=f["accession_number"],
            primary_doc_url=f["primary_doc_url"],
            txt_url=f.get("txt_url"),
        )
        for f in filings_data
    ]

    # Show sample of what will be fetched
    logger.info("")
    logger.info("Sample of filings to fetch:")
    for i, f in enumerate(filings[:5], 1):
        logger.info(
            f"  {i}. {f.company_name} - {f.form_type} - {f.filing_date}"
        )
    if len(filings) > 5:
        logger.info(f"  ... and {len(filings) - 5} more")
    logger.info("")

    # Fetch filings
    logger.info("Fetching filings (this may take a while)...")
    logger.info("SEC imposes a rate limit of ~10 requests/second")
    logger.info("")

    try:
        stats = fetcher.fetch_batch(
            filings,
            fetch_txt=not args.skip_txt,
            max_failures=10,
        )

        logger.info("")
        logger.info("=" * 80)
        logger.info("✓ Fetch complete!")
        logger.info("=" * 80)
        logger.info(f"  Total: {stats['total']}")
        logger.info(f"  Fetched: {stats['fetched']}")
        logger.info(f"  Skipped (cached): {stats['skipped']}")
        logger.info(f"  Failed: {stats['failed']}")
        logger.info("=" * 80)
        logger.info(f"Files stored in: {args.storage_root}")

        # Show some example paths
        if stats['fetched'] > 0:
            logger.info("")
            logger.info("Example fetched files:")
            for i, f in enumerate(filings[:3], 1):
                content = fetcher.get_filing_content(f.cik, f.accession_number)
                if content:
                    logger.info(f"  {i}. {content.html_path}")

    except KeyboardInterrupt:
        logger.warning("\n\nProcess interrupted by user")
        sys.exit(1)
    except Exception as e:
        logger.error(f"\n\nError fetching filings: {e}", exc_info=True)
        sys.exit(1)

    logger.info("")
    logger.info("Done!")


if __name__ == "__main__":
    main()
