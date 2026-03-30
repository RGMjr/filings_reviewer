#!/usr/bin/env python3
"""
IMG-1-3: Generate Image Review Candidates from Inventory

Reads the image inventory CSV and populates the image_review_candidates table
with four-tier filtering and pattern learning metadata.

Tier Classification:
    - seed_list: Known valuable charts (hardcoded URLs, highest priority)
    - tier_1_cohort: Cohort keyword detected (confidence >= 0.60)
    - tier_2_large: Large non-decorative image (>= 300x300 pixels)
    - tier_3_all: All remaining non-decorative images

Insertion Order:
    Candidates are inserted in tier priority order so that image_candidate_id
    reflects review priority. Seed list images get the lowest IDs (reviewed first).

Usage:
    # Dry run to see what would be inserted
    python scripts/generate_image_candidates.py --dry-run

    # Actually insert candidates
    python scripts/generate_image_candidates.py

    # Process specific filing
    python scripts/generate_image_candidates.py --filing-id 31

    # Clear existing and re-insert
    python scripts/generate_image_candidates.py --clear

    # Use specific CSV
    python scripts/generate_image_candidates.py --csv /path/to/inventory.csv

Known Limitations / Future Improvements:
    1. Dry-run doesn't detect CSV duplicates (actual insertion does via upsert)
    2. No --tier filter to generate only specific tiers
    3. No progress bar for large CSV files
"""

import argparse
import csv
import logging
import os
import sys
import time
import urllib.request
from collections import Counter
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv

from src.infra.db import DatabaseAdapter

logger = logging.getLogger(__name__)

# =============================================================================
# Constants
# =============================================================================

DEFAULT_CSV_PATH = "data/discovery/chart_image_inventory.csv"

# Seed list: Known valuable chart images that should always be included
# These get 'seed_list' tier to ensure they're reviewed first
SEED_LIST_URLS = {
    # Slack ARR by cohort chart
    "https://www.sec.gov/Archives/edgar/data/1764925/000162828019007428/mdaa2.jpg",
    # Farfetch GMV chart
    "https://www.sec.gov/Archives/edgar/data/1740915/000119312518252315/g532260g12o45.jpg",
}


# =============================================================================
# Classification Logic
# =============================================================================


def parse_int(value: str) -> int | None:
    """Parse string to int, returning None for empty/invalid values."""
    if not value or value.strip() == "":
        return None
    try:
        return int(value)
    except ValueError:
        return None


def parse_float(value: str) -> float:
    """Parse string to float, defaulting to 0.0 for empty/invalid values."""
    if not value or value.strip() == "":
        return 0.0
    try:
        return float(value)
    except ValueError:
        return 0.0


def parse_bool(value: str) -> bool:
    """Parse string to bool."""
    return value.strip().lower() == "true"


def parse_keywords(value: str) -> list[str]:
    """Parse semicolon-separated keywords to list."""
    if not value or value.strip() == "":
        return []
    return [k.strip() for k in value.split(";") if k.strip()]


def validate_image_url(url: str, user_agent: str) -> bool:
    """
    Send a HEAD request to verify the image URL exists on SEC EDGAR.

    Returns True if the URL returns HTTP 200, False otherwise.
    Respects SEC rate limiting (100ms delay applied by caller).
    """
    try:
        req = urllib.request.Request(url, method="HEAD")
        req.add_header("User-Agent", user_agent)
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status == 200
    except Exception:
        return False


def classify_tier(row: dict) -> str | None:
    """
    Assign detection tier based on image attributes.

    Tier hierarchy:
    - tier_1_cohort: Cohort keyword detected (confidence >= 0.60)
    - tier_2_large: Large non-decorative image (>= 300x300)
    - tier_3_all: All remaining non-decorative images
    - None: Decorative images (excluded)

    Returns:
        Tier string or None if image should be excluded.
    """
    # Check if decorative first
    is_decorative = parse_bool(row.get("is_decorative", "False"))
    if is_decorative:
        return None

    # Tier 1: Cohort keyword detected
    cohort_confidence = parse_float(row.get("cohort_confidence", "0"))
    if cohort_confidence >= 0.60:
        return "tier_1_cohort"

    # Tier 2: Large non-decorative image
    width = parse_int(row.get("width", ""))
    height = parse_int(row.get("height", ""))
    if width and height and width >= 300 and height >= 300:
        return "tier_2_large"

    # Tier 3: All remaining non-decorative
    return "tier_3_all"


def is_seed_list_url(image_url: str) -> bool:
    """Check if URL is in the seed list of known valuable charts."""
    return image_url in SEED_LIST_URLS


# =============================================================================
# Database Operations
# =============================================================================


def get_company_id_for_filing(db: DatabaseAdapter, filing_id: int) -> int | None:
    """Look up company_id for a filing_id."""
    result = db.query(
        "SELECT company_id FROM filings WHERE filing_id = %s",
        (filing_id,),
    )
    return int(result[0]["company_id"]) if result else None


def clear_candidates(db: DatabaseAdapter) -> int:
    """Delete all existing image review candidates. Returns count deleted."""
    # First count existing
    result = db.query("SELECT COUNT(*) as cnt FROM image_review_candidates")
    count = result[0]["cnt"] if result else 0

    # Delete all
    with db.get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM image_review_candidates")

    return count


# =============================================================================
# Main Processing
# =============================================================================


def process_csv(
    csv_path: str,
    db: DatabaseAdapter | None,
    dry_run: bool = False,
    limit: int | None = None,
    filing_id_filter: int | None = None,
    validate_urls: bool = False,
    sec_user_agent: str = "filings-reviewer info@example.com",
) -> dict:
    """
    Process the image inventory CSV and insert candidates.

    Returns:
        Summary dict with counts.
    """
    stats: Counter = Counter()

    # Cache for company_id lookups
    company_id_cache: dict[int, int | None] = {}

    # Track data quality issues
    missing_dimensions_count = 0
    seed_list_found: set[str] = set()

    # Read and parse CSV
    with open(csv_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    # Apply filing_id filter if specified
    if filing_id_filter is not None:
        rows = [r for r in rows if parse_int(r.get("filing_id", "")) == filing_id_filter]
        logger.info(f"Filtered to {len(rows)} rows for filing_id={filing_id_filter}")

    # Apply limit if specified
    if limit is not None:
        rows = rows[:limit]
        logger.info(f"Limited to {len(rows)} rows")

    # First pass: classify all rows and separate by tier for ordering
    classified_rows: list[tuple[dict, str]] = []
    for row in rows:
        tier = classify_tier(row)
        image_url = row.get("image_url", "")

        # Check seed list - override tier
        if is_seed_list_url(image_url):
            seed_list_found.add(image_url)
            if tier is None:
                # Even decorative images in seed list get included
                tier = "seed_list"
            else:
                tier = "seed_list"
            stats["seed_list_matches"] += 1

        if tier is None:
            stats["skipped_decorative"] += 1
            continue

        # Track data quality
        width = parse_int(row.get("width", ""))
        height = parse_int(row.get("height", ""))
        if not width or not height:
            missing_dimensions_count += 1

        classified_rows.append((row, tier))

    stats["missing_dimensions"] = missing_dimensions_count

    # Check for missing seed list images
    missing_seeds = SEED_LIST_URLS - seed_list_found
    if missing_seeds:
        for url in missing_seeds:
            logger.warning(f"Seed list image not found in CSV: {url}")
        stats["seed_list_missing"] = len(missing_seeds)

    # Sort by tier priority for insertion order
    # Seed list first, then tier_1, tier_2, tier_3
    tier_priority = {"seed_list": 0, "tier_1_cohort": 1, "tier_2_large": 2, "tier_3_all": 3}
    classified_rows.sort(key=lambda x: tier_priority.get(x[1], 99))

    # Second pass: insert in priority order
    for row, tier in classified_rows:
        stats["processed"] += 1
        stats[f"tier_{tier}"] += 1

        filing_id = parse_int(row.get("filing_id", ""))
        if filing_id is None:
            stats["errors"] += 1
            logger.warning(f"Missing filing_id in row: {row}")
            continue

        # Look up company_id (with caching)
        if filing_id not in company_id_cache:
            if db is not None:
                company_id_cache[filing_id] = get_company_id_for_filing(db, filing_id)
            else:
                company_id_cache[filing_id] = None

        company_id = company_id_cache[filing_id]
        if company_id is None and not dry_run:
            stats["errors"] += 1
            logger.warning(f"Could not find company_id for filing_id={filing_id}")
            continue

        if dry_run:
            stats["would_insert"] += 1
            continue

        # Insert candidate
        # Track seen keys to detect CSV duplicates
        image_src = row.get("image_src", "")
        key = (filing_id, image_src)
        if key in company_id_cache.get("_seen_keys", set()):
            stats["skipped_csv_duplicate"] += 1
            continue
        if "_seen_keys" not in company_id_cache:
            company_id_cache["_seen_keys"] = set()
        company_id_cache["_seen_keys"].add(key)

        # Validate URL before inserting (optional, respects SEC 100ms rate limit)
        image_url_value = row.get("image_url", "")
        if validate_urls and image_url_value:
            time.sleep(0.1)
            if not validate_image_url(image_url_value, sec_user_agent):
                stats["skipped_url_invalid"] += 1
                logger.warning(f"Skipping invalid URL: {image_url_value}")
                continue

        try:
            db.insert_image_review_candidate(
                filing_id=filing_id,
                company_id=company_id,
                image_src=image_src,
                image_url=row.get("image_url", ""),
                image_width=parse_int(row.get("width", "")),
                image_height=parse_int(row.get("height", "")),
                image_alt=row.get("alt_text") or None,
                preceding_text=row.get("preceding_text") or None,
                detected_keywords=parse_keywords(row.get("detected_keywords", "")),
                cohort_keyword_nearby=parse_bool(row.get("cohort_keyword_nearby", "False")),
                image_index=parse_int(row.get("image_index", "")),
                cohort_confidence=parse_float(row.get("cohort_confidence", "0")),
                is_decorative=False,  # We already filtered out decorative
                detection_tier=tier,
            )
            stats["inserted"] += 1

        except Exception as e:
            stats["errors"] += 1
            logger.error(f"Error inserting candidate: {e}")

    return dict(stats)


def print_summary(stats: dict, dry_run: bool = False) -> None:
    """Print a formatted summary of the processing results."""
    print("\n" + "=" * 50)
    if dry_run:
        print("=== Image Candidate Generation (DRY RUN) ===")
    else:
        print("=== Image Candidate Generation Complete ===")
    print("=" * 50)

    print(f"Total rows processed: {stats.get('processed', 0)}")

    if dry_run:
        print(f"Candidates would create: {stats.get('would_insert', 0)} (before de-duplication)")
    else:
        print(f"Candidates created: {stats.get('inserted', 0)}")

    # Tier breakdown
    print("  Tier breakdown:")
    print(f"    - seed_list: {stats.get('tier_seed_list', 0)}")
    print(f"    - tier_1_cohort: {stats.get('tier_tier_1_cohort', 0)}")
    print(f"    - tier_2_large: {stats.get('tier_tier_2_large', 0)}")
    print(f"    - tier_3_all: {stats.get('tier_tier_3_all', 0)}")

    print(f"Skipped (decorative): {stats.get('skipped_decorative', 0)}")
    if stats.get("skipped_url_invalid", 0) > 0:
        print(f"Skipped (URL 404): {stats.get('skipped_url_invalid', 0)}")
    if stats.get("skipped_csv_duplicate", 0) > 0:
        print(f"Skipped (CSV duplicates): {stats.get('skipped_csv_duplicate', 0)}")
    print(f"Errors: {stats.get('errors', 0)}")

    # Data quality warnings
    if stats.get("missing_dimensions", 0) > 0:
        print(f"\nData quality note: {stats.get('missing_dimensions', 0)} images missing dimensions")

    if stats.get("seed_list_missing", 0) > 0:
        print(f"WARNING: {stats.get('seed_list_missing', 0)} seed list images not found in CSV")

    print("=" * 50)


# =============================================================================
# CLI
# =============================================================================


def main() -> int:
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Generate image review candidates from discovery inventory CSV"
    )
    parser.add_argument(
        "--csv",
        default=DEFAULT_CSV_PATH,
        help=f"Input CSV path (default: {DEFAULT_CSV_PATH})",
    )
    parser.add_argument(
        "--database-url",
        default=None,
        help="Database URL (default: from DATABASE_URL env)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be inserted without inserting",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Process only first N rows",
    )
    parser.add_argument(
        "--filing-id",
        type=int,
        default=None,
        help="Process only specific filing",
    )
    parser.add_argument(
        "--clear",
        action="store_true",
        help="Clear existing candidates before inserting",
    )
    parser.add_argument(
        "--skip-url-validation",
        action="store_true",
        help="Skip HEAD-checking image URLs against SEC EDGAR (faster but may insert broken URLs)",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Enable verbose logging",
    )

    args = parser.parse_args()

    # Configure logging
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s - %(levelname)s - %(message)s",
    )

    # Load .env if present
    load_dotenv()

    # Get database URL
    database_url = args.database_url or os.environ.get("DATABASE_URL")
    if not database_url and not args.dry_run:
        print("ERROR: DATABASE_URL not set. Use --database-url or set DATABASE_URL env var.")
        print("       Or use --dry-run to preview without database access.")
        return 1

    # Verify CSV exists
    csv_path = Path(args.csv)
    if not csv_path.exists():
        print(f"ERROR: CSV file not found: {csv_path}")
        return 1

    # Connect to database (if not dry run or if we need company_id lookups)
    db = None
    if database_url:
        try:
            db = DatabaseAdapter(database_url)
            logger.info("Connected to database")
        except Exception as e:
            if not args.dry_run:
                print(f"ERROR: Could not connect to database: {e}")
                return 1
            logger.warning(f"Could not connect to database (continuing with dry run): {e}")

    # Clear existing if requested
    if args.clear and db and not args.dry_run:
        deleted = clear_candidates(db)
        logger.info(f"Cleared {deleted} existing candidates")
        print(f"Cleared {deleted} existing candidates")

    # Process CSV
    logger.info(f"Processing CSV: {csv_path}")
    sec_user_agent = os.environ.get("SEC_USER_AGENT", "filings-reviewer info@example.com")
    stats = process_csv(
        csv_path=str(csv_path),
        db=db,
        dry_run=args.dry_run,
        limit=args.limit,
        filing_id_filter=args.filing_id,
        validate_urls=not args.skip_url_validation,
        sec_user_agent=sec_user_agent,
    )

    # Print summary
    print_summary(stats, dry_run=args.dry_run)

    # Return error code if there were errors
    return 1 if stats.get("errors", 0) > 0 else 0


if __name__ == "__main__":
    sys.exit(main())
