#!/usr/bin/env python3
"""
Generate candidates for specific filings.

Usage:
    python scripts/generate_candidates_for_filing.py --filing-ids 33,35
"""

import argparse
import logging
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv

from src.infra.db import DatabaseAdapter
from src.infra.logging_config import configure_logging
from src.review.candidate_generator import CandidateGenerator
from src.review.config import get_high_precision_config

logger = logging.getLogger(__name__)


def generate_candidates_for_filing(db: DatabaseAdapter, filing_id: int, company_id: int) -> int:
    """Generate candidates for a single filing."""
    # Load segments
    segments_query = """
        SELECT
            source_segment_id,
            filing_id,
            segment_type,
            raw_text,
            raw_html,
            section_heading,
            section_path
        FROM source_segments
        WHERE filing_id = %(filing_id)s
        ORDER BY sequence_index
    """
    segments = db.query(segments_query, {"filing_id": filing_id})

    if not segments:
        logger.warning(f"No segments found for filing {filing_id}")
        return 0

    logger.info(f"  Found {len(segments)} segments")

    # Generate candidates
    generator = CandidateGenerator(config=get_high_precision_config())
    candidates = generator.generate_for_filing(
        filing_id=filing_id,
        company_id=company_id,
        segments=segments,
        db=db,
    )

    logger.info(f"  Generated {len(candidates)} candidates")

    # Insert candidates
    if candidates:
        candidate_dicts = [c.to_dict() for c in candidates]
        db.bulk_insert_review_candidates(candidate_dicts)
        logger.info(f"  Inserted {len(candidates)} candidates into database")

    return len(candidates)


def main():
    parser = argparse.ArgumentParser(description="Generate candidates for specific filings")
    parser.add_argument("--filing-ids", type=str, required=True, help="Comma-separated filing IDs")
    parser.add_argument("--database-url", type=str, help="Database URL")

    args = parser.parse_args()

    load_dotenv()
    configure_logging(level="INFO")

    db_url = args.database_url or os.getenv("DATABASE_URL")
    if not db_url:
        logger.error("DATABASE_URL not set")
        return 1

    db = DatabaseAdapter(db_url)
    logger.info("Connected to database")

    filing_ids = [int(fid.strip()) for fid in args.filing_ids.split(",")]

    # Get filing info
    filings_query = """
        SELECT f.filing_id, f.company_id, c.company_name
        FROM filings f
        JOIN companies c ON f.company_id = c.company_id
        WHERE f.filing_id = ANY(%(filing_ids)s)
    """
    filings = db.query(filings_query, {"filing_ids": filing_ids})

    if not filings:
        logger.error(f"No filings found for IDs: {filing_ids}")
        return 1

    logger.info(f"Generating candidates for {len(filings)} filings...")

    total_generated = 0
    for filing in filings:
        logger.info(f"\nProcessing {filing['company_name']} (filing {filing['filing_id']})...")
        num_generated = generate_candidates_for_filing(
            db, filing["filing_id"], filing["company_id"]
        )
        total_generated += num_generated

    print(f"\n{'='*70}")
    print("GENERATION COMPLETE")
    print(f"{'='*70}")
    print(f"Total candidates generated: {total_generated}")
    print("\nView in review UI: http://127.0.0.1:5002/review/filings")

    return 0


if __name__ == "__main__":
    sys.exit(main())
