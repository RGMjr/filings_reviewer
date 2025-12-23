#!/usr/bin/env python3
"""
Batch Download Runner for FilingFetcher Integration

This script integrates FilingFetcher with UniverseBuilder by:
1. Querying for filings with processing_status='pending'
2. Downloading HTML and TXT files in batches
3. Updating processing_status to 'fetched' on success
4. Tracking progress and generating statistics

Usage:
    # Download next 50 pending filings
    python scripts/batch_download_filings.py --limit 50

    # Download all pending filings (use with caution - could be thousands!)
    python scripts/batch_download_filings.py --limit 10000

    # Download from specific year
    python scripts/batch_download_filings.py --year 2024 --limit 100

    # Resume after interruption (skips already fetched)
    python scripts/batch_download_filings.py --limit 100

    # Dry run - show what would be downloaded without fetching
    python scripts/batch_download_filings.py --limit 20 --dry-run
"""

import argparse
import logging
import os
import sys
from datetime import datetime
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv

from src.filing_fetcher.filing_fetcher import FilingFetcher
from src.infra.db import DatabaseAdapter
from src.infra.logging_config import configure_logging, get_timestamped_log_path
from src.infra.sec_client import FilingMetadata, SECClient

# Configure logging with file output for batch operations
configure_logging(
    level="INFO",
    log_file=get_timestamped_log_path("batch_download"),
)
logger = logging.getLogger(__name__)


def get_pending_filings(db, limit=100, year=None):
    """
    Query database for filings with processing_status='pending'.

    Args:
        db: DatabaseAdapter instance
        limit: Maximum number of filings to return
        year: Optional year filter

    Returns:
        List of filing dictionaries
    """
    query = """
        SELECT
            f.filing_id,
            c.company_name,
            f.cik,
            f.accession_number,
            f.form_type,
            f.filing_date,
            f.sec_html_url as primary_doc_url,
            f.sec_txt_url as txt_url,
            f.processing_status,
            f.created_at
        FROM filings f
        JOIN companies c ON f.company_id = c.company_id
        WHERE
            f.is_in_scope_phase1 = true
            AND f.processing_status = 'pending'
    """

    params = {}

    if year:
        query += " AND EXTRACT(YEAR FROM f.filing_date) = %(year)s"
        params["year"] = year

    query += " ORDER BY f.filing_date DESC LIMIT %(limit)s"
    params["limit"] = limit

    return db.query(query, params)


def get_processing_stats(db):
    """
    Get overall processing statistics from database.

    Args:
        db: DatabaseAdapter instance

    Returns:
        Dictionary with counts by processing_status
    """
    query = """
        SELECT
            processing_status,
            COUNT(*) as count
        FROM filings
        WHERE is_in_scope_phase1 = true
        GROUP BY processing_status
        ORDER BY processing_status
    """

    results = db.query(query)
    return {row["processing_status"]: row["count"] for row in results}


def print_banner(title):
    """Print a formatted banner."""
    logger.info("=" * 80)
    logger.info(title)
    logger.info("=" * 80)


def print_stats(stats_before, stats_after):
    """Print before/after processing statistics."""
    logger.info("")
    logger.info("Processing Status Summary:")
    logger.info("-" * 80)
    logger.info(f"{'Status':<20} {'Before':<15} {'After':<15} {'Change':<15}")
    logger.info("-" * 80)

    all_statuses = set(stats_before.keys()) | set(stats_after.keys())
    for status in sorted(all_statuses):
        before = stats_before.get(status, 0)
        after = stats_after.get(status, 0)
        change = after - before
        change_str = f"+{change}" if change > 0 else str(change) if change != 0 else "0"

        logger.info(f"{status:<20} {before:<15} {after:<15} {change_str:<15}")

    logger.info("-" * 80)
    logger.info(
        f"{'TOTAL':<20} {sum(stats_before.values()):<15} {sum(stats_after.values()):<15}"
    )
    logger.info("")


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Batch download filings from SEC EDGAR",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=50,
        help="Number of filings to fetch (default: 50)",
    )
    parser.add_argument(
        "--year", type=int, help="Filter to specific year (e.g., 2024)"
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
    parser.add_argument(
        "--max-failures",
        type=int,
        default=10,
        help="Stop after this many consecutive failures (default: 10)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be downloaded without actually fetching",
    )

    args = parser.parse_args()

    # Load environment
    load_dotenv()
    db_url = args.database_url or os.getenv(
        "DATABASE_URL", "postgresql://localhost/filings_analysis"
    )

    print_banner("SEC Filings Batch Download Runner")
    logger.info(f"Started at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    logger.info(f"Database: {db_url}")
    logger.info(f"Storage root: {args.storage_root}")
    logger.info(f"Batch size: {args.limit}")
    logger.info(f"Year filter: {args.year or 'None'}")
    logger.info(f"Fetch TXT: {not args.skip_txt}")
    logger.info(f"Max consecutive failures: {args.max_failures}")
    logger.info(f"Dry run: {args.dry_run}")
    logger.info("=" * 80)
    logger.info("")

    # Set up database connection
    logger.info("Connecting to database...")
    db = DatabaseAdapter(db_url)

    # Get initial statistics
    logger.info("Fetching current processing statistics...")
    stats_before = get_processing_stats(db)

    # Initialize FilingFetcher with SECClient first (needed to query for filings)
    logger.info("Initializing FilingFetcher and SECClient...")
    sec_client = SECClient(user_agent=args.user_agent)
    fetcher = FilingFetcher(
        storage_root=args.storage_root,
        user_agent=args.user_agent,
        db=db,
        sec_client=sec_client,
    )

    # Get pending filings using FilingFetcher (with randomization and proper error exclusion)
    logger.info("Querying for pending filings...")
    filings_data = fetcher.get_unfetched_filings(limit=args.limit)

    # Apply year filter if specified
    if args.year:
        filings_data = [f for f in filings_data if f['filing_date'].year == args.year]

    if not filings_data:
        logger.warning("No pending filings found matching criteria")
        logger.info("")
        logger.info("Current processing status:")
        for status, count in sorted(stats_before.items()):
            logger.info(f"  {status}: {count}")
        return

    logger.info(f"Found {len(filings_data)} pending filings")
    logger.info("")

    # Show sample of what will be fetched
    logger.info("Sample of filings to fetch:")
    logger.info("-" * 80)
    logger.info(f"{'Company':<30} {'Form':<10} {'Date':<12} {'Status':<10}")
    logger.info("-" * 80)
    for i, f in enumerate(filings_data[:10], 1):
        logger.info(
            f"{f['company_name'][:28]:<30} {f['form_type']:<10} {str(f['filing_date']):<12} {f['processing_status']:<10}"
        )
    if len(filings_data) > 10:
        logger.info(f"  ... and {len(filings_data) - 10} more")
    logger.info("-" * 80)
    logger.info("")

    if args.dry_run:
        logger.info("DRY RUN - No files will be downloaded")
        logger.info("")
        logger.info("Processing breakdown:")
        logger.info(f"  Would fetch: {len(filings_data)} filings")
        logger.info(
            f"  Estimated time: ~{len(filings_data) * 0.15:.1f} seconds (at 10 req/sec rate limit)"
        )
        logger.info(
            f"  Estimated storage: ~{len(filings_data) * 2:.0f} MB (assuming avg 2MB per filing)"
        )
        return

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

    # Fetch filings
    print_banner("Starting Batch Download")
    logger.info("SEC rate limit: ~10 requests/second")
    logger.info(f"Estimated time: ~{len(filings) * 0.15:.1f} seconds")
    logger.info("Press Ctrl+C to interrupt (progress will be saved)")
    logger.info("")

    try:
        fetch_stats = fetcher.fetch_batch(
            filings, fetch_txt=not args.skip_txt, max_failures=args.max_failures
        )

        # Get final statistics
        stats_after = get_processing_stats(db)

        # Print results
        print_banner("✓ Batch Download Complete!")
        logger.info(f"Completed at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        logger.info("")
        logger.info("Batch Results:")
        logger.info(f"  Total requested: {fetch_stats['total']}")
        logger.info(f"  Successfully fetched: {fetch_stats['fetched']}")
        logger.info(f"  Skipped (already cached): {fetch_stats['skipped']}")
        logger.info(f"  Failed: {fetch_stats['failed']}")

        if fetch_stats["failed"] > 0:
            logger.warning("")
            logger.warning(
                f"⚠️  {fetch_stats['failed']} filing(s) failed to download"
            )
            logger.warning("Check logs above for error details")

        # Print before/after stats
        print_stats(stats_before, stats_after)

        logger.info(f"Files stored in: {args.storage_root}/")
        logger.info("")

        # Show some example paths
        if fetch_stats["fetched"] > 0:
            logger.info("Example downloaded files:")
            for i, f in enumerate(filings[:3], 1):
                content = fetcher.get_filing_content(f.cik, f.accession_number)
                if content:
                    logger.info(f"  {i}. {content.html_path}")
            logger.info("")

        # Next steps guidance
        if stats_after.get("pending", 0) > 0:
            logger.info("Next steps:")
            logger.info(
                f"  • {stats_after['pending']} filings still pending - run again to continue"
            )
            logger.info(
                f"  • {stats_after.get('fetched', 0)} filings ready for extraction pipeline"
            )
        else:
            logger.info("All in-scope filings have been fetched! 🎉")
            logger.info(
                f"Next: Run extraction pipeline on {stats_after.get('fetched', 0)} fetched filings"
            )

    except KeyboardInterrupt:
        logger.warning("\n\nProcess interrupted by user")
        logger.info(
            "Progress has been saved - you can resume by running this script again"
        )
        stats_after = get_processing_stats(db)
        print_stats(stats_before, stats_after)
        sys.exit(1)
    except Exception as e:
        logger.error(f"\n\nError during batch download: {e}", exc_info=True)
        sys.exit(1)

    logger.info("=" * 80)
    logger.info("Done!")
    logger.info("=" * 80)


if __name__ == "__main__":
    main()
