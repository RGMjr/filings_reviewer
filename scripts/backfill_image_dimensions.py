#!/usr/bin/env python3
"""
Backfill pixel dimensions for image_review_candidates that have NULL image_width/image_height.

Looks up cached image bytes in the image_cache table, parses width/height using Pillow,
and updates image_review_candidates. Clears predicted_relevance on updated rows so they
are automatically re-scored on the next score_image_candidates.py run.

Images not found in the DB cache are skipped by default. Use --live-fetch to also fetch
uncached images from SEC EDGAR (slow — respects the 100ms EDGAR rate limit).

Usage:
    # Dry run — show count of candidates missing dimensions
    python3 scripts/backfill_image_dimensions.py --dry-run

    # Fill from DB image cache only (fast, no SEC requests)
    python3 scripts/backfill_image_dimensions.py

    # Also fetch uncached images from SEC EDGAR
    python3 scripts/backfill_image_dimensions.py --live-fetch

    # Limit to N candidates
    python3 scripts/backfill_image_dimensions.py --limit 50
"""

import argparse
import io
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


def get_candidates_missing_dimensions(
    db: DatabaseAdapter, limit: int | None = None
) -> list[dict]:
    """
    Return image_review_candidates that are missing at least one dimension,
    joined to filings for cik and accession_number.
    """
    sql = """
        SELECT irc.image_candidate_id,
               irc.image_src,
               f.cik,
               f.accession_number
        FROM image_review_candidates irc
        JOIN filings f ON irc.filing_id = f.filing_id
        WHERE irc.image_width IS NULL OR irc.image_height IS NULL
        ORDER BY f.cik, f.accession_number, irc.image_src
    """
    if limit is not None:
        sql += f" LIMIT {limit}"
    return db.query(sql)


def parse_dimensions(image_data: bytes) -> tuple[int, int] | None:
    """
    Parse (width, height) from raw image bytes using Pillow.
    Returns None if the bytes cannot be parsed as a known image format.
    """
    try:
        from PIL import Image

        # Disable the decompression bomb limit — we only read header metadata,
        # never decompress pixels, so the size check is irrelevant here.
        Image.MAX_IMAGE_PIXELS = None

        with Image.open(io.BytesIO(image_data)) as img:
            return img.size  # (width, height)
    except Exception:
        return None


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Backfill image dimensions for candidates with NULL width/height",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print candidate count without making changes",
    )
    parser.add_argument(
        "--limit",
        type=int,
        help="Maximum number of candidates to process",
    )
    parser.add_argument(
        "--live-fetch",
        action="store_true",
        help="Fetch images from SEC EDGAR when not found in DB cache (slow)",
    )
    parser.add_argument(
        "--database-url",
        help="Database connection string (defaults to DATABASE_URL env var)",
    )
    parser.add_argument(
        "--user-agent",
        default="CMASB Filings Analyzer rgmarkey@gmail.com",
        help="User agent for SEC EDGAR requests (only used with --live-fetch)",
    )
    args = parser.parse_args()

    load_dotenv()
    db_url = args.database_url or os.getenv("DATABASE_URL", "")
    if not db_url:
        print("ERROR: DATABASE_URL not set. Use --database-url or set the env var.")
        sys.exit(1)

    logger.info("=" * 60)
    logger.info("Image Dimension Backfill")
    logger.info("=" * 60)
    logger.info(f"Started:     {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    logger.info(f"Dry run:     {args.dry_run}")
    logger.info(f"Limit:       {args.limit or 'none'}")
    logger.info(f"Live fetch:  {args.live_fetch}")

    db = DatabaseAdapter(db_url)
    sec_client = (
        SECClient(user_agent=args.user_agent, db_adapter=db) if args.live_fetch else None
    )

    logger.info("\nQuerying candidates with missing dimensions...")
    candidates = get_candidates_missing_dimensions(db, limit=args.limit)
    logger.info(
        f"Found {len(candidates)} candidates with NULL image_width or image_height"
    )

    if args.dry_run:
        logger.info("\nDry run — no changes will be made.")
        for row in candidates[:20]:
            logger.info(
                f"  Would process: cik={row['cik']} "
                f"acc={row['accession_number']} src={row['image_src']}"
            )
        if len(candidates) > 20:
            logger.info(f"  ... and {len(candidates) - 20} more")
        return

    updated = 0
    skipped_no_cache = 0
    skipped_already_set = 0
    parse_errors = 0
    live_fetched = 0

    for i, row in enumerate(candidates, 1):
        candidate_id = row["image_candidate_id"]
        image_src = row["image_src"]
        cik = row["cik"]
        accession_number = row["accession_number"]

        # Construct image_cache lookup key.
        # image_src is the filename (e.g. 'mdaa2.jpg'); basename defensively in case
        # any rows have a path prefix.
        filename = Path(image_src).name
        cik_stripped = cik.lstrip("0") or "0"
        accession_no = accession_number.replace("-", "")

        # Try DB cache first
        cached = db.get_cached_image(cik_stripped, accession_no, filename)
        image_data: bytes | None = cached["image_data"] if cached else None

        # Optionally fall back to live SEC EDGAR fetch
        if image_data is None and args.live_fetch and sec_client is not None:
            logger.info(
                f"[{i}/{len(candidates)}] Cache miss — fetching live: "
                f"{cik}/{accession_number}/{filename}"
            )
            result = sec_client.fetch_image(
                cik=cik, accession_number=accession_number, filename=filename
            )
            if result is not None:
                image_data = result
                live_fetched += 1
            else:
                logger.warning(f"  Live fetch failed: {filename}")

        if image_data is None:
            skipped_no_cache += 1
            logger.debug(
                f"[{i}/{len(candidates)}] Skip (not cached): "
                f"{cik}/{accession_number}/{filename}"
            )
            continue

        # Parse pixel dimensions from bytes
        dims = parse_dimensions(image_data)
        if dims is None:
            parse_errors += 1
            logger.warning(
                f"[{i}/{len(candidates)}] Parse error (corrupt/unknown format): "
                f"{filename}"
            )
            continue

        width, height = dims

        # Update the candidate row; clears predicted_relevance for re-scoring
        was_updated = db.update_image_dimensions(candidate_id, width, height)
        if was_updated:
            updated += 1
            logger.debug(
                f"[{i}/{len(candidates)}] Updated: {filename} → {width}×{height}"
            )
        else:
            # Row was already updated by a concurrent run or dimensions were set
            skipped_already_set += 1
            logger.debug(
                f"[{i}/{len(candidates)}] Skip (already set): {filename}"
            )

    logger.info("\n" + "=" * 60)
    logger.info("Backfill complete")
    logger.info(f"  Updated:               {updated}")
    logger.info(f"  Skipped (not cached):  {skipped_no_cache}")
    if args.live_fetch:
        logger.info(f"  Fetched live:          {live_fetched}")
    logger.info(f"  Skipped (already set): {skipped_already_set}")
    logger.info(f"  Parse errors:          {parse_errors}")
    logger.info("=" * 60)
    if updated > 0:
        logger.info(
            f"\nNext step: run score_image_candidates.py to re-score "
            f"the {updated} updated candidates."
            "\n  python3 scripts/score_image_candidates.py"
        )


if __name__ == "__main__":
    main()
