#!/usr/bin/env python3
"""
Backfill filing HTML/TXT content into the database.

Reads local files referenced by html_storage_path and txt_storage_path and
stores their content in the html_content and txt_content columns. This enables
cloud deployments where the local filesystem may not be available.

Usage:
    # Backfill all filings that have local files but no database content
    python3 scripts/backfill_html_to_db.py

    # Limit to first N filings
    python3 scripts/backfill_html_to_db.py --limit 100

    # Dry run (report what would be updated without writing)
    python3 scripts/backfill_html_to_db.py --dry-run

    # Verbose logging
    python3 scripts/backfill_html_to_db.py -v
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv  # noqa: E402

from src.infra.db import DatabaseAdapter  # noqa: E402

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


def backfill(db: DatabaseAdapter, limit: int | None = None, dry_run: bool = False) -> dict:
    """
    Backfill html_content and txt_content from local files into the database.

    Args:
        db: Database adapter instance
        limit: Maximum number of filings to process (None = all)
        dry_run: If True, report what would be updated without writing

    Returns:
        Dict with counts: processed, updated, skipped, failed
    """
    stats = {"processed": 0, "updated": 0, "skipped": 0, "failed": 0}

    # Query filings that have local paths but no database content
    query = """
        SELECT filing_id, html_storage_path, txt_storage_path
        FROM filings
        WHERE html_content IS NULL
          AND html_storage_path IS NOT NULL
    """
    if limit is not None:
        query += f" LIMIT {int(limit)}"

    filings = db.query(query)
    total = len(filings)
    logger.info(f"Found {total} filings to backfill")

    for i, filing in enumerate(filings, 1):
        filing_id = filing["filing_id"]
        html_path = filing.get("html_storage_path")
        txt_path = filing.get("txt_storage_path")
        stats["processed"] += 1

        # Read HTML content from local file
        html_content = None
        if html_path:
            p = Path(html_path)
            if p.exists():
                try:
                    html_content = p.read_text(encoding="utf-8")
                except Exception as e:
                    logger.warning(f"Filing {filing_id}: failed to read HTML {html_path}: {e}")
                    stats["failed"] += 1
                    continue
            else:
                logger.debug(f"Filing {filing_id}: HTML file not found at {html_path}")
                stats["skipped"] += 1
                continue

        if html_content is None:
            stats["skipped"] += 1
            continue

        # Read TXT content from local file (optional)
        txt_content = None
        if txt_path:
            p = Path(txt_path)
            if p.exists():
                try:
                    txt_content = p.read_text(encoding="utf-8")
                except Exception as e:
                    logger.warning(f"Filing {filing_id}: failed to read TXT {txt_path}: {e}")
                    # Non-fatal: still update html_content

        if dry_run:
            html_size = len(html_content)
            txt_size = len(txt_content) if txt_content else 0
            logger.info(
                f"[DRY RUN] Filing {filing_id}: would store "
                f"html_content ({html_size:,} bytes)"
                + (f", txt_content ({txt_size:,} bytes)" if txt_content else "")
            )
            stats["updated"] += 1
            continue

        # Update database
        try:
            update_query = """
                UPDATE filings
                SET html_content = %(html_content)s,
                    txt_content = %(txt_content)s,
                    updated_at = now()
                WHERE filing_id = %(filing_id)s
            """
            db.execute(
                update_query,
                {
                    "html_content": html_content,
                    "txt_content": txt_content,
                    "filing_id": filing_id,
                },
            )
            stats["updated"] += 1
        except Exception as e:
            logger.error(f"Filing {filing_id}: database update failed: {e}")
            stats["failed"] += 1
            continue

        # Progress logging
        if i % 50 == 0 or i == total:
            logger.info(
                f"Progress: {i}/{total} processed, "
                f"{stats['updated']} updated, "
                f"{stats['skipped']} skipped, "
                f"{stats['failed']} failed"
            )

    return stats


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Backfill filing HTML/TXT content from local files into the database",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--limit", type=int, help="Maximum number of filings to process")
    parser.add_argument(
        "--dry-run", action="store_true", help="Report what would be updated without writing"
    )
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose logging")
    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        print("ERROR: DATABASE_URL environment variable not set", file=sys.stderr)
        sys.exit(1)

    db = DatabaseAdapter(db_url)

    if args.dry_run:
        logger.info("Running in DRY RUN mode (no database writes)")

    stats = backfill(db, limit=args.limit, dry_run=args.dry_run)

    # Print summary
    print()
    print("=" * 50)
    print("Backfill Summary")
    print("=" * 50)
    print(f"  Processed: {stats['processed']}")
    print(f"  Updated:   {stats['updated']}")
    print(f"  Skipped:   {stats['skipped']} (file not found)")
    print(f"  Failed:    {stats['failed']}")
    print("=" * 50)

    if stats["failed"] > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
