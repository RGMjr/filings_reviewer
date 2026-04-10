#!/usr/bin/env python3
"""
Backfill the PostgreSQL image_cache table from image_review_candidates.

Fetches all known images from SEC EDGAR and stores them in the image_cache table
so they persist across Render redeploys. Skips images already cached. Idempotent —
safe to run multiple times.

Usage:
    # Dry run — print candidate count without fetching
    python3 scripts/backfill_image_cache.py --dry-run

    # Fetch up to 10 images (for testing)
    python3 scripts/backfill_image_cache.py --limit 10

    # Full backfill (all images, respects SEC rate limit ~100ms/request)
    python3 scripts/backfill_image_cache.py
"""

import argparse
import logging
import os
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv

from src.infra.db import DatabaseAdapter
from src.infra.logging_config import configure_logging
from src.infra.sec_client import SECClient

configure_logging(level="INFO")
logger = logging.getLogger(__name__)


def get_image_candidates(db: DatabaseAdapter, limit: int | None = None) -> list[dict]:
    """
    Get all distinct images from image_review_candidates, joined to filings for cik/accession_number.

    Returns list of dicts with: image_src, cik, accession_number
    """
    sql = """
        SELECT DISTINCT irc.image_src, f.cik, f.accession_number
        FROM image_review_candidates irc
        JOIN filings f ON irc.filing_id = f.filing_id
        ORDER BY f.cik, f.accession_number, irc.image_src
    """
    if limit is not None:
        sql += f" LIMIT {limit}"
    return db.query(sql)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Backfill image_cache table from image_review_candidates",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would be fetched without actually fetching",
    )
    parser.add_argument(
        "--limit",
        type=int,
        help="Maximum number of images to fetch",
    )
    parser.add_argument(
        "--database-url",
        help="Database connection string (defaults to DATABASE_URL env var)",
    )
    parser.add_argument(
        "--user-agent",
        default="CMASB Filings Analyzer rgmarkey@gmail.com",
        help="User agent for SEC EDGAR requests",
    )
    args = parser.parse_args()

    load_dotenv()
    db_url = args.database_url or os.getenv("DATABASE_URL", "")
    if not db_url:
        print("ERROR: DATABASE_URL not set. Use --database-url or set the env var.")
        sys.exit(1)

    logger.info("=" * 60)
    logger.info("Image Cache Backfill")
    logger.info("=" * 60)
    logger.info(f"Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    logger.info(f"Dry run: {args.dry_run}")
    logger.info(f"Limit:   {args.limit or 'none'}")

    db = DatabaseAdapter(db_url)
    sec_client = SECClient(user_agent=args.user_agent, db_adapter=db)

    logger.info("\nFetching image candidates...")
    candidates = get_image_candidates(db, limit=args.limit)
    logger.info(f"Found {len(candidates)} distinct images to process")

    if args.dry_run:
        logger.info("\nDry run — no images will be fetched.")
        for row in candidates[:20]:
            logger.info(f"  Would fetch: {row['cik']}/{row['accession_number']}/{row['image_src']}")
        if len(candidates) > 20:
            logger.info(f"  ... and {len(candidates) - 20} more")
        return

    fetched = skipped = failed = 0

    for i, row in enumerate(candidates, 1):
        cik = row["cik"]
        accession_number = row["accession_number"]
        filename = row["image_src"]

        # Check DB cache first — skip if already stored
        cik_stripped = cik.lstrip("0") or "0"
        accession_no_dashes = accession_number.replace("-", "")
        if db.get_cached_image(cik_stripped, accession_no_dashes, filename):
            skipped += 1
            logger.debug(f"[{i}/{len(candidates)}] Skip (cached): {filename}")
            continue

        # Fetch from SEC EDGAR — SECClient auto-stores in image_cache on success
        logger.info(f"[{i}/{len(candidates)}] Fetching: {cik}/{accession_number}/{filename}")
        result = sec_client.fetch_image(cik=cik, accession_number=accession_number, filename=filename)

        if result is not None:
            fetched += 1
        else:
            failed += 1
            logger.warning(f"  Failed to fetch: {filename}")

    stats = db.get_image_cache_stats()
    logger.info("\n" + "=" * 60)
    logger.info("Backfill complete")
    logger.info(f"  Fetched:  {fetched}")
    logger.info(f"  Skipped:  {skipped} (already cached)")
    logger.info(f"  Failed:   {failed}")
    logger.info(f"  Cache total: {stats['count']} images ({stats['total_bytes'] / 1024 / 1024:.1f} MB)")
    logger.info("=" * 60)


if __name__ == "__main__":
    main()
