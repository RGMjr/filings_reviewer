#!/usr/bin/env python3
"""
Script to fetch a curated sample of filings for development and testing.

This script fetches:
1. Known companies with good customer metrics disclosure (Slack, Shopify, etc.)
2. Diverse samples across categories (SPACs, F-1s, various industries)
3. Edge cases for testing classification logic

Usage:
    python scripts/fetch_curated_sample.py
"""

import argparse
import json
import logging
import os
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv

from src.filing_fetcher.filing_fetcher import FilingFetcher
from src.infra.db import DatabaseAdapter
from src.infra.logging_config import configure_logging
from src.infra.sec_client import FilingMetadata

configure_logging(level="INFO")
logger = logging.getLogger(__name__)


def fetch_curated_companies(db, fetcher):
    """Fetch filings from curated companies list (Slack, Shopify, etc.).

    Prefers the final S-1/A or F-1/A amendment over the original S-1/F-1,
    as amendments contain the most complete and accurate disclosure.
    """
    curated_file = Path("data/curated_companies.json")

    if not curated_file.exists():
        logger.warning("Curated companies file not found, skipping")
        return []

    with open(curated_file) as f:
        data = json.load(f)

    companies = data.get("companies", [])
    logger.info(f"Looking for {len(companies)} curated companies...")

    filings = []
    found_count = 0

    for company in companies:
        cik = company["cik"]
        name = company["company_name"]

        # Query for S-1/F-1 filings for this company
        # Prefer the final amendment (S-1/A, F-1/A) over original (S-1, F-1)
        # by ordering amendments first, then by filing_date DESC to get the latest
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
            WHERE f.cik = %(cik)s
              AND f.form_type IN ('S-1', 'S-1/A', 'F-1', 'F-1/A')
              AND f.html_fetched_at IS NULL
            ORDER BY
                -- Prefer amendments over originals
                CASE WHEN f.form_type LIKE '%%/A' THEN 0 ELSE 1 END,
                -- Get the latest filing date (final amendment)
                f.filing_date DESC
            LIMIT 1
        """

        results = db.query(query, {"cik": cik.zfill(10)})

        if results:
            found_count += 1
            form = results[0]["form_type"]
            logger.info(f"  ✓ Found {name} (CIK {cik}) - {form}")
            filings.extend(results)
        else:
            logger.debug(f"  ✗ Not found yet: {name} (CIK {cik})")

    logger.info(f"Found {found_count}/{len(companies)} curated companies in database")
    return filings


def fetch_diverse_sample(db, fetcher, limit=30):
    """Fetch diverse sample across different categories."""
    logger.info(f"Fetching diverse sample of {limit} filings...")

    samples = []

    # 1. Regular S-1s (in-scope, non-SPAC)
    logger.info("  Fetching regular S-1s...")
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
        WHERE f.is_in_scope_phase1 = true
          AND f.form_type = 'S-1'
          AND f.is_spac = false
          AND f.html_fetched_at IS NULL
        ORDER BY RANDOM()
        LIMIT %(limit)s
    """
    samples.extend(db.query(query, {"limit": int(limit * 0.4)}))  # 40% regular S-1s

    # 2. F-1s (foreign filers)
    logger.info("  Fetching F-1s (foreign filers)...")
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
        WHERE f.is_in_scope_phase1 = true
          AND f.form_type = 'F-1'
          AND f.html_fetched_at IS NULL
        ORDER BY RANDOM()
        LIMIT %(limit)s
    """
    samples.extend(db.query(query, {"limit": int(limit * 0.25)}))  # 25% F-1s

    # 3. SPACs (for testing detection)
    logger.info("  Fetching SPACs...")
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
        WHERE f.is_spac = true
          AND f.html_fetched_at IS NULL
        ORDER BY RANDOM()
        LIMIT %(limit)s
    """
    samples.extend(db.query(query, {"limit": int(limit * 0.2)}))  # 20% SPACs

    # 4. Amendments (for testing version handling)
    logger.info("  Fetching amendments...")
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
        WHERE f.form_type IN ('S-1/A', 'F-1/A')
          AND f.html_fetched_at IS NULL
        ORDER BY RANDOM()
        LIMIT %(limit)s
    """
    samples.extend(db.query(query, {"limit": int(limit * 0.15)}))  # 15% amendments

    logger.info(f"Selected {len(samples)} diverse filings")
    return samples


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Fetch curated sample of filings for development"
    )
    parser.add_argument(
        "--sample-size",
        type=int,
        default=40,
        help="Total number of filings to fetch (default: 40)",
    )
    parser.add_argument(
        "--database-url",
        help="Database connection string (defaults to DATABASE_URL from .env)",
    )
    parser.add_argument(
        "--storage-root",
        default="data/filings",
        help="Root directory for storing filings",
    )
    parser.add_argument(
        "--skip-txt",
        action="store_true",
        help="Skip fetching complete text files (HTML only)",
    )
    parser.add_argument(
        "--curated-only",
        action="store_true",
        help="Only fetch curated companies (Slack, Shopify, etc.)",
    )

    args = parser.parse_args()

    # Load environment
    load_dotenv()
    db_url = args.database_url or os.getenv(
        "DATABASE_URL", "postgresql://localhost/filings_analysis"
    )

    logger.info("=" * 80)
    logger.info("Fetching Curated Sample of Filings")
    logger.info("=" * 80)
    logger.info(f"Target sample size: {args.sample_size}")
    logger.info(f"Curated only: {args.curated_only}")
    logger.info("=" * 80)

    # Set up database and fetcher
    db = DatabaseAdapter(db_url)
    fetcher = FilingFetcher(storage_root=args.storage_root, db=db)

    # Fetch curated companies
    curated_filings = fetch_curated_companies(db, fetcher)

    # Fetch diverse sample (if not curated-only)
    diverse_filings = []
    if not args.curated_only:
        remaining = max(0, args.sample_size - len(curated_filings))
        if remaining > 0:
            diverse_filings = fetch_diverse_sample(db, fetcher, limit=remaining)

    # Combine
    all_filings = curated_filings + diverse_filings

    if not all_filings:
        logger.warning("No filings found to fetch!")
        return

    logger.info("")
    logger.info(f"Total filings to fetch: {len(all_filings)}")
    logger.info(f"  - Curated companies: {len(curated_filings)}")
    logger.info(f"  - Diverse sample: {len(diverse_filings)}")
    logger.info("")

    # Show sample
    logger.info("Sample of filings to fetch:")
    for i, f in enumerate(all_filings[:10], 1):
        logger.info(f"  {i}. {f['company_name']} - {f['form_type']} - {f['filing_date']}")
    if len(all_filings) > 10:
        logger.info(f"  ... and {len(all_filings) - 10} more")
    logger.info("")

    # Convert to FilingMetadata
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
        for f in all_filings
    ]

    # Fetch
    logger.info("Fetching filings...")
    try:
        stats = fetcher.fetch_batch(filings, fetch_txt=not args.skip_txt)

        logger.info("")
        logger.info("=" * 80)
        logger.info("✓ Fetch complete!")
        logger.info("=" * 80)
        logger.info(f"  Total: {stats['total']}")
        logger.info(f"  Fetched: {stats['fetched']}")
        logger.info(f"  Skipped (cached): {stats['skipped']}")
        logger.info(f"  Failed: {stats['failed']}")
        logger.info("=" * 80)

    except KeyboardInterrupt:
        logger.warning("\n\nProcess interrupted by user")
        sys.exit(1)
    except Exception as e:
        logger.error(f"\n\nError: {e}", exc_info=True)
        sys.exit(1)

    logger.info("Done!")


if __name__ == "__main__":
    main()
