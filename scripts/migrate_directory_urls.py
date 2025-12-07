#!/usr/bin/env python3
"""
Migrate directory URLs to resolved document URLs in the database.

This script:
1. Finds all filings where sec_html_url ends with '/' (directory URLs)
2. Resolves each to the actual document URL using SEC's index.json
3. Updates the database with the resolved URL
4. Respects SEC rate limiting (100ms between requests)

Usage:
    python scripts/migrate_directory_urls.py --dry-run    # Preview changes
    python scripts/migrate_directory_urls.py              # Apply changes
    python scripts/migrate_directory_urls.py --limit 100  # Process only 100 records
"""

import argparse
import json
import logging
import os
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.infra.db import DatabaseAdapter
from src.infra.sec_client import SECClient
from src.infra.logging_config import configure_logging

configure_logging(level="INFO")
logger = logging.getLogger(__name__)


def get_directory_url_filings(db: DatabaseAdapter, limit: int = None) -> list:
    """
    Get all filings with directory URLs (ending with '/').

    Args:
        db: Database adapter
        limit: Maximum records to return (None for all)

    Returns:
        List of filing records with directory URLs
    """
    query = """
        SELECT
            f.filing_id,
            f.cik,
            f.accession_number,
            f.sec_html_url,
            c.company_name
        FROM filings f
        JOIN companies c USING (company_id)
        WHERE f.sec_html_url LIKE '%%/'
        ORDER BY f.filing_id
    """

    if limit:
        query += f" LIMIT {limit}"

    return db.query(query)


def update_filing_url(db: DatabaseAdapter, filing_id: int, resolved_url: str) -> bool:
    """
    Update a filing's sec_html_url with the resolved URL.

    Args:
        db: Database adapter
        filing_id: Filing ID to update
        resolved_url: Resolved document URL

    Returns:
        True if update succeeded
    """
    query = """
        UPDATE filings
        SET
            sec_html_url = %(url)s,
            updated_at = now()
        WHERE filing_id = %(filing_id)s
    """

    try:
        db.execute(query, {"filing_id": filing_id, "url": resolved_url})
        return True
    except Exception as e:
        logger.error(f"Failed to update filing {filing_id}: {e}")
        return False


def migrate_directory_urls(
    db: DatabaseAdapter,
    sec_client: SECClient,
    limit: int = None,
    dry_run: bool = False,
) -> dict:
    """
    Migrate all directory URLs to resolved document URLs.

    Args:
        db: Database adapter
        sec_client: SEC client for URL resolution
        limit: Maximum records to process (None for all)
        dry_run: If True, don't make changes

    Returns:
        Dict with migration statistics
    """
    stats = {
        "total": 0,
        "resolved": 0,
        "failed": 0,
        "skipped": 0,
        "failed_records": [],
        "start_time": datetime.now().isoformat(),
    }

    # Get all filings with directory URLs
    filings = get_directory_url_filings(db, limit)
    stats["total"] = len(filings)

    if not filings:
        logger.info("No directory URLs found to migrate")
        return stats

    logger.info(f"Found {len(filings):,} directory URLs to migrate")

    if dry_run:
        logger.info("DRY RUN MODE - No changes will be made")

    # Process each filing
    for i, filing in enumerate(filings, 1):
        filing_id = filing["filing_id"]
        cik = filing["cik"]
        accession = filing["accession_number"]
        company = filing["company_name"]
        current_url = filing["sec_html_url"]

        # Progress logging
        if i % 100 == 0 or i == 1:
            logger.info(f"Progress: {i:,}/{len(filings):,} ({i/len(filings)*100:.1f}%)")

        try:
            # Resolve the URL
            resolved_url = sec_client.resolve_primary_document_url(cik, accession)

            if not resolved_url:
                logger.warning(f"[{i}] Could not resolve URL for {company} ({cik}/{accession})")
                stats["failed"] += 1
                stats["failed_records"].append({
                    "filing_id": filing_id,
                    "cik": cik,
                    "accession_number": accession,
                    "company_name": company,
                    "error": "Could not resolve primary document URL",
                })
                continue

            # Check if already resolved (shouldn't happen, but safety check)
            if resolved_url == current_url:
                logger.debug(f"[{i}] Already resolved: {cik}/{accession}")
                stats["skipped"] += 1
                continue

            # Update the database
            if dry_run:
                logger.info(f"[{i}] Would update {company}:")
                logger.info(f"      Old: {current_url}")
                logger.info(f"      New: {resolved_url}")
                stats["resolved"] += 1
            else:
                if update_filing_url(db, filing_id, resolved_url):
                    logger.debug(f"[{i}] Updated {company}: {resolved_url}")
                    stats["resolved"] += 1
                else:
                    stats["failed"] += 1
                    stats["failed_records"].append({
                        "filing_id": filing_id,
                        "cik": cik,
                        "accession_number": accession,
                        "company_name": company,
                        "error": "Database update failed",
                    })

        except Exception as e:
            logger.error(f"[{i}] Error processing {company} ({cik}/{accession}): {e}")
            stats["failed"] += 1
            stats["failed_records"].append({
                "filing_id": filing_id,
                "cik": cik,
                "accession_number": accession,
                "company_name": company,
                "error": str(e),
            })

    stats["end_time"] = datetime.now().isoformat()
    return stats


def save_failed_records(stats: dict, output_path: str):
    """Save failed records to a JSON file for retry."""
    if stats["failed_records"]:
        with open(output_path, "w") as f:
            json.dump(stats["failed_records"], f, indent=2)
        logger.info(f"Failed records saved to: {output_path}")


def main():
    parser = argparse.ArgumentParser(
        description="Migrate directory URLs to resolved document URLs"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview changes without making them",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Maximum number of records to process",
    )
    parser.add_argument(
        "--output",
        type=str,
        default="migration_failures.json",
        help="Output file for failed records (default: migration_failures.json)",
    )
    args = parser.parse_args()

    # Initialize connections
    db_url = os.getenv("DATABASE_URL", "postgresql://localhost/filings_analysis")
    user_agent = os.getenv("SEC_USER_AGENT", "CMASB Filings Analyzer contact@example.com")

    db = DatabaseAdapter(db_url)
    sec_client = SECClient(user_agent=user_agent)

    logger.info("=" * 80)
    logger.info("Directory URL Migration")
    logger.info("=" * 80)

    if args.dry_run:
        logger.info("MODE: DRY RUN (no changes will be made)")
    else:
        logger.info("MODE: LIVE (changes will be applied)")

    if args.limit:
        logger.info(f"LIMIT: {args.limit:,} records")

    logger.info("")

    # Run migration
    stats = migrate_directory_urls(
        db=db,
        sec_client=sec_client,
        limit=args.limit,
        dry_run=args.dry_run,
    )

    # Print summary
    logger.info("")
    logger.info("=" * 80)
    logger.info("MIGRATION SUMMARY")
    logger.info("=" * 80)
    logger.info(f"Total records: {stats['total']:,}")
    logger.info(f"  Resolved:    {stats['resolved']:,}")
    logger.info(f"  Failed:      {stats['failed']:,}")
    logger.info(f"  Skipped:     {stats['skipped']:,}")

    # Save failed records if any
    if stats["failed_records"]:
        save_failed_records(stats, args.output)

    # Exit with appropriate code
    if stats["failed"] > 0:
        logger.warning(f"⚠️  Migration completed with {stats['failed']} failures")
        sys.exit(1)
    else:
        logger.info("✓ Migration completed successfully")
        sys.exit(0)


if __name__ == "__main__":
    main()
