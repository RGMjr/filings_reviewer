#!/usr/bin/env python3
"""
Batch Pipeline Cron Script

Runs two stages for each scheduled execution:
  1. Extract — process filings with processing_status='fetched' and html_content stored
  2. Candidates — generate review candidates for newly extracted filings

Configured via environment variables (no argparse — designed for cron context):
  DATABASE_URL   PostgreSQL connection string (required)
  BATCH_LIMIT    Max filings to extract per run (default: 50)

Exit codes:
  0  Success (including "nothing to do")
  1  Unhandled error
"""

import logging
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv

from src.extraction.extraction_pipeline import ExtractionPipeline
from src.infra.db import DatabaseAdapter
from src.infra.logging_config import configure_logging
from src.review.helpers import generate_candidates_for_filing

load_dotenv()

configure_logging(level="INFO")
logger = logging.getLogger(__name__)


def get_fetched_filings(db: DatabaseAdapter, limit: int) -> list[dict]:
    """Return filings that have HTML stored in Postgres and haven't been extracted yet."""
    return db.query(
        """
        SELECT f.filing_id, c.company_name, f.cik, f.accession_number
        FROM filings f
        JOIN companies c ON f.company_id = c.company_id
        WHERE f.processing_status = 'fetched'
          AND f.html_content IS NOT NULL
        ORDER BY f.filing_date DESC
        LIMIT %(limit)s
        """,
        {"limit": limit},
    )


def get_filings_needing_candidates(db: DatabaseAdapter, filing_ids: list[int]) -> list[dict]:
    """Return filings (from the given set) that have segments but no review candidates."""
    return db.query(
        """
        SELECT DISTINCT f.filing_id, f.company_id, c.company_name
        FROM filings f
        JOIN companies c ON f.company_id = c.company_id
        JOIN source_segments s ON f.filing_id = s.filing_id
        LEFT JOIN review_candidates rc ON f.filing_id = rc.filing_id
        WHERE f.filing_id = ANY(%(filing_ids)s)
          AND rc.candidate_id IS NULL
        GROUP BY f.filing_id, f.company_id, c.company_name
        HAVING COUNT(DISTINCT s.source_segment_id) > 0
        """,
        {"filing_ids": filing_ids},
    )


def stage_extract(db: DatabaseAdapter, batch_limit: int) -> list[int]:
    """
    Extract filings with processing_status='fetched'.

    Returns list of filing_ids that were successfully extracted.
    """
    filings = get_fetched_filings(db, batch_limit)

    if not filings:
        logger.info("stage=extract filings_found=0 — nothing to do")
        return []

    logger.info(f"stage=extract filings_found={len(filings)}")
    pipeline = ExtractionPipeline(db=db)

    succeeded: list[int] = []
    failed = 0
    for filing in filings:
        filing_id = filing["filing_id"]
        result = pipeline.process_filing(filing_id)
        if result.success:
            succeeded.append(filing_id)
        else:
            failed += 1

    logger.info(f"stage=extract success={len(succeeded)} failed={failed}")
    return succeeded


def stage_candidates(db: DatabaseAdapter, extracted_filing_ids: list[int]) -> None:
    """Generate review candidates for newly extracted filings."""
    if not extracted_filing_ids:
        logger.info("stage=candidates filing_ids=[] — nothing to do")
        return

    filings = get_filings_needing_candidates(db, extracted_filing_ids)

    if not filings:
        logger.info("stage=candidates filings_needing_candidates=0 — nothing to do")
        return

    logger.info(f"stage=candidates filings_found={len(filings)}")
    total_candidates = 0
    failed = 0

    for filing in filings:
        filing_id = filing["filing_id"]
        try:
            candidates = generate_candidates_for_filing(db=db, filing_id=filing_id, save=True)
            total_candidates += len(candidates)
            logger.info(f"stage=candidates filing_id={filing_id} candidates={len(candidates)}")
        except Exception as e:
            failed += 1
            logger.error(f"stage=candidates filing_id={filing_id} error={e}", exc_info=True)

    logger.info(f"stage=candidates total_candidates={total_candidates} failed={failed}")


def main() -> None:
    db_url = os.getenv("DATABASE_URL", "postgresql://localhost/filings_analysis")
    batch_limit = int(os.getenv("BATCH_LIMIT", "50"))

    logger.info(f"batch_pipeline start batch_limit={batch_limit}")

    db = DatabaseAdapter(db_url)

    # Stage 1: Extract
    extracted_ids = stage_extract(db, batch_limit)

    # Stage 2: Candidates
    stage_candidates(db, extracted_ids)

    logger.info("batch_pipeline done")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        logger.critical(f"batch_pipeline fatal error: {e}", exc_info=True)
        sys.exit(1)
