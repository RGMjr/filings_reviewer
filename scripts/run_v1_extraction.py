#!/usr/bin/env python3
"""
V1 Extraction Pipeline Runner

Runs the rule-based V1 ExtractionPipeline against filings with
processing_status = 'fetched'. No LLM required.

Usage:
    # Process up to 3 fetched filings
    python3 scripts/run_v1_extraction.py --limit 3

    # Process specific filing IDs
    python3 scripts/run_v1_extraction.py --filing-ids 123,456
"""

import argparse
import logging
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv

from src.extraction.extraction_pipeline import ExtractionPipeline
from src.infra.db import DatabaseAdapter
from src.infra.logging_config import configure_logging

load_dotenv()

configure_logging(level="INFO")
logger = logging.getLogger(__name__)


def get_fetched_filings(db: DatabaseAdapter, limit: int) -> list[dict]:
    return db.query(
        """
        SELECT f.filing_id, c.company_name, f.cik, f.accession_number
        FROM filings f
        JOIN companies c ON f.company_id = c.company_id
        WHERE f.processing_status = 'fetched'
          AND f.html_storage_path IS NOT NULL
        ORDER BY f.filing_date DESC
        LIMIT %(limit)s
        """,
        {"limit": limit},
    )


def get_filings_by_ids(db: DatabaseAdapter, filing_ids: list[int]) -> list[dict]:
    return db.query(
        """
        SELECT f.filing_id, c.company_name, f.cik, f.accession_number
        FROM filings f
        JOIN companies c ON f.company_id = c.company_id
        WHERE f.filing_id = ANY(%(ids)s)
        ORDER BY f.filing_date DESC
        """,
        {"ids": filing_ids},
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Run V1 ExtractionPipeline on fetched filings")
    parser.add_argument("--limit", type=int, default=10, help="Max filings to process (default: 10)")
    parser.add_argument("--filing-ids", help="Comma-separated filing IDs to process")
    parser.add_argument("--database-url", help="Override DATABASE_URL from .env")
    args = parser.parse_args()

    db_url = args.database_url or os.getenv("DATABASE_URL", "postgresql://localhost/filings_analysis")
    db = DatabaseAdapter(db_url)
    pipeline = ExtractionPipeline(db=db)

    if args.filing_ids:
        ids = [int(x.strip()) for x in args.filing_ids.split(",")]
        filings = get_filings_by_ids(db, ids)
    else:
        filings = get_fetched_filings(db, args.limit)

    if not filings:
        print("No fetched filings found.")
        sys.exit(0)

    print(f"Processing {len(filings)} filing(s)...")
    results = pipeline.process_batch([f["filing_id"] for f in filings])

    print(f"\nDone. Success: {results['success']}, Failed: {results['failed']}")
    print(f"Segments: {results['total_segments']}, Values: {results['total_values']}, "
          f"Definitions: {results['total_definitions']}")


if __name__ == "__main__":
    main()
