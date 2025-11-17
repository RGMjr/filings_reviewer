#!/usr/bin/env python3
"""
Fetch known good companies with excellent customer metrics disclosure.
"""

import logging
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
from src.infra.db import DatabaseAdapter
from src.infra.sec_client import FilingMetadata
from src.filing_fetcher.filing_fetcher import FilingFetcher

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
)
logger = logging.getLogger(__name__)

# Known good companies
CURATED_COMPANIES = [
    'SHOPIFY INC.',
    'Square, Inc.',
    'DROPBOX, INC.',
    'Zoom Video Communications, Inc.',
    'Slack Technologies, Inc.',
    'Datadog, Inc.',
]

def main():
    load_dotenv()
    db_url = os.getenv("DATABASE_URL", "postgresql://localhost/filings_analysis")

    logger.info("=" * 80)
    logger.info("Fetching Known Good Companies with Customer Metrics Disclosure")
    logger.info("=" * 80)

    db = DatabaseAdapter(db_url)
    fetcher = FilingFetcher(storage_root="data/filings", db=db)

    # Query for these specific companies
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
        WHERE c.company_name = ANY(%(companies)s)
          AND f.form_type IN ('S-1', 'S-1/A', 'F-1', 'F-1/A')
          AND f.html_fetched_at IS NULL
        ORDER BY f.filing_date
    """

    results = db.query(query, {"companies": CURATED_COMPANIES})

    if not results:
        logger.warning("No curated filings found!")
        return

    logger.info(f"Found {len(results)} curated company filings to fetch:")
    for r in results:
        logger.info(f"  - {r['company_name']} ({r['form_type']}, {r['filing_date']})")

    logger.info("")
    logger.info("Fetching HTML documents...")

    filings = [
        FilingMetadata(
            cik=r["cik"],
            company_name=r["company_name"],
            form_type=r["form_type"],
            filing_date=str(r["filing_date"]),
            accession_number=r["accession_number"],
            primary_doc_url=r["primary_doc_url"],
            txt_url=r.get("txt_url"),
        )
        for r in results
    ]

    stats = fetcher.fetch_batch(filings, fetch_txt=False)

    logger.info("")
    logger.info("=" * 80)
    logger.info("✓ Fetch complete!")
    logger.info("=" * 80)
    logger.info(f"  Fetched: {stats['fetched']}")
    logger.info(f"  Skipped (cached): {stats['skipped']}")
    logger.info(f"  Failed: {stats['failed']}")
    logger.info("=" * 80)

if __name__ == "__main__":
    main()
