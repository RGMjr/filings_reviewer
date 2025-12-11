#!/usr/bin/env python3
"""
B3: Batch Review Candidate Generation Script

Generates review candidates from source segments for human review.
Uses high-recall detection (numbers near metric keywords) to populate
the review_candidates table.

Algorithm:
1. Query filings that have segments but no review candidates
2. For each filing, call generate_candidates_for_filing()
3. Track statistics (candidates generated, failures)
4. Report summary

Usage:
    # Process specific filings
    python scripts/generate_review_candidates.py --filing-ids 123,456,789

    # Process N filings needing candidates
    python scripts/generate_review_candidates.py --limit 10

    # Dry run (don't save to database)
    python scripts/generate_review_candidates.py --limit 5 --dry-run

    # Assign batch ID for grouping
    python scripts/generate_review_candidates.py --limit 10 --batch-id 1

    # Process specific filings with custom database
    python scripts/generate_review_candidates.py --filing-ids 123 --database-url postgresql://...
"""

import argparse
import logging
import os
import sys
from pathlib import Path
from typing import Dict, List, Optional

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
from tqdm import tqdm

from src.infra.db import DatabaseAdapter
from src.infra.logging_config import configure_logging, get_timestamped_log_path
from src.review.helpers import generate_candidates_for_filing

logger = logging.getLogger(__name__)


def parse_filing_ids(filing_ids_str: str) -> List[int]:
    """
    Parse comma-separated filing IDs into list of integers.

    Args:
        filing_ids_str: Comma-separated filing IDs (e.g., "123,456,789")

    Returns:
        List of filing IDs as integers

    Raises:
        ValueError: If any filing ID is not a valid integer
    """
    if not filing_ids_str or not filing_ids_str.strip():
        return []

    try:
        filing_ids = [int(fid.strip()) for fid in filing_ids_str.split(",")]
        return filing_ids
    except ValueError as e:
        raise ValueError(
            f"Invalid filing ID format. Expected comma-separated integers, got: {filing_ids_str}"
        ) from e


def get_filings_by_ids(db: DatabaseAdapter, filing_ids: List[int]) -> List[Dict]:
    """
    Query filings by specific IDs.

    Args:
        db: DatabaseAdapter instance
        filing_ids: List of filing IDs to fetch

    Returns:
        List of filing dicts with metadata
    """
    query = """
        SELECT DISTINCT
            f.filing_id,
            f.company_id,
            c.company_name,
            f.accession_number,
            f.filing_date,
            COUNT(DISTINCT s.source_segment_id) as segment_count
        FROM filings f
        JOIN companies c ON f.company_id = c.company_id
        JOIN source_segments s ON f.filing_id = s.filing_id
        WHERE f.filing_id = ANY(%(filing_ids)s)
        GROUP BY f.filing_id, f.company_id, c.company_name,
                 f.accession_number, f.filing_date
        ORDER BY f.filing_date DESC
    """
    return db.query(query, {"filing_ids": filing_ids})


def get_filings_needing_candidates(
    db: DatabaseAdapter, limit: int
) -> List[Dict]:
    """
    Query filings that have segments but no review candidates.

    Returns filings ordered by filing_date DESC (most recent first).

    Args:
        db: DatabaseAdapter instance
        limit: Maximum number of filings to return

    Returns:
        List of filing dicts with metadata
    """
    query = """
        SELECT DISTINCT
            f.filing_id,
            f.company_id,
            c.company_name,
            f.accession_number,
            f.filing_date,
            COUNT(DISTINCT s.source_segment_id) as segment_count
        FROM filings f
        JOIN companies c ON f.company_id = c.company_id
        JOIN source_segments s ON f.filing_id = s.filing_id
        LEFT JOIN review_candidates rc ON f.filing_id = rc.filing_id
        WHERE f.is_in_scope_phase1 = true
          AND rc.candidate_id IS NULL  -- No candidates generated yet
        GROUP BY f.filing_id, f.company_id, c.company_name,
                 f.accession_number, f.filing_date
        HAVING COUNT(DISTINCT s.source_segment_id) > 0  -- Has segments
        ORDER BY f.filing_date DESC
        LIMIT %(limit)s
    """
    return db.query(query, {"limit": limit})


def process_filings(
    db: DatabaseAdapter,
    filings: List[Dict],
    dry_run: bool = False,
    batch_id: Optional[int] = None,
    show_progress: bool = True,
) -> Dict[str, int]:
    """
    Process filings to generate review candidates.

    Args:
        db: DatabaseAdapter instance
        filings: List of filing dicts to process
        dry_run: If True, don't save to database
        batch_id: Optional batch ID to assign to candidates
        show_progress: If True, show progress bar (default: True)

    Returns:
        Dictionary of processing statistics
    """
    stats = {
        "filings_processed": 0,
        "filings_failed": 0,
        "total_candidates": 0,
        "total_segments": 0,
    }

    # Create progress bar if requested
    filings_iter = (
        tqdm(filings, desc="Processing filings", unit="filing")
        if show_progress
        else filings
    )

    for i, filing in enumerate(filings_iter, 1):
        filing_id = filing["filing_id"]
        company_name = filing["company_name"]

        # Don't show detailed logging if progress bar is visible
        if not show_progress:
            logger.info("=" * 80)
            logger.info(f"Filing {i}/{len(filings)}: {company_name}")
            logger.info(f"  Filing ID: {filing_id}")
            logger.info(f"  Accession: {filing['accession_number']}")
            logger.info(f"  Date: {filing['filing_date']}")
            logger.info(f"  Segments: {filing['segment_count']}")
            logger.info("-" * 80)

        try:
            candidates = generate_candidates_for_filing(
                db=db,
                filing_id=filing_id,
                save=not dry_run,
                batch_id=batch_id,
            )

            stats["filings_processed"] += 1
            stats["total_candidates"] += len(candidates)
            stats["total_segments"] += filing["segment_count"]

            if show_progress:
                # Update progress bar description with candidate count
                if isinstance(filings_iter, tqdm):
                    filings_iter.set_postfix(
                        candidates=len(candidates), total=stats["total_candidates"]
                    )
            else:
                logger.info(f"✓ Generated {len(candidates)} candidates")

        except Exception as e:
            stats["filings_failed"] += 1
            logger.error(f"✗ Failed to process filing {filing_id}: {e}", exc_info=True)
            continue  # Continue with next filing

    return stats


def report_summary(
    stats: Dict[str, int], total_filings: int, dry_run: bool
) -> None:
    """
    Report processing summary statistics.

    Args:
        stats: Dictionary of processing statistics
        total_filings: Total number of filings to process
        dry_run: Whether this was a dry run
    """
    logger.info("=" * 80)
    logger.info("SUMMARY")
    logger.info("=" * 80)
    logger.info(f"Filings processed: {stats['filings_processed']}/{total_filings}")
    logger.info(f"Filings failed: {stats['filings_failed']}")
    logger.info(f"Total candidates generated: {stats['total_candidates']}")

    if stats["filings_processed"] > 0:
        avg_candidates = stats["total_candidates"] / stats["filings_processed"]
        avg_segments = stats["total_segments"] / stats["filings_processed"]
        logger.info(f"Average candidates per filing: {avg_candidates:.1f}")
        logger.info(f"Average segments per filing: {avg_segments:.1f}")

    if dry_run:
        logger.warning("DRY RUN: Candidates were NOT saved to database")
    else:
        logger.info("✓ All candidates saved to database")

    logger.info("=" * 80)


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Generate review candidates from filing segments",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Process 10 filings needing candidates
  python scripts/generate_review_candidates.py --limit 10

  # Process specific filings
  python scripts/generate_review_candidates.py --filing-ids 123,456,789

  # Test with dry-run (no database changes)
  python scripts/generate_review_candidates.py --limit 2 --dry-run

  # Assign batch ID for grouping
  python scripts/generate_review_candidates.py --limit 10 --batch-id 1
        """,
    )

    parser.add_argument(
        "--filing-ids",
        type=str,
        help="Comma-separated filing IDs to process (e.g., '123,456,789')",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=10,
        help="Maximum number of filings to process from database query (default: 10, max: 1000)",
    )
    parser.add_argument(
        "--batch-id",
        type=int,
        help="Optional batch ID to assign to generated candidates",
    )
    parser.add_argument(
        "--database-url",
        help="Database connection string (defaults to DATABASE_URL from .env)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Don't save candidates to database (for testing)",
    )
    parser.add_argument(
        "--no-progress",
        action="store_true",
        help="Disable progress bar (useful for logging to files)",
    )

    args = parser.parse_args()

    # Validate limit parameter
    MAX_LIMIT = 1000
    if args.limit > MAX_LIMIT:
        print(f"Error: --limit cannot exceed {MAX_LIMIT}", file=sys.stderr)
        print(f"Requested: {args.limit}, Maximum allowed: {MAX_LIMIT}", file=sys.stderr)
        print("For large batches, run the script multiple times with smaller limits", file=sys.stderr)
        sys.exit(1)

    if args.limit < 1:
        print("Error: --limit must be at least 1", file=sys.stderr)
        sys.exit(1)

    # Load environment
    load_dotenv()
    db_url = args.database_url or os.getenv(
        "DATABASE_URL", "postgresql://localhost/filings_analysis"
    )

    # Configure logging with timestamped file
    configure_logging(
        level="INFO", log_file=get_timestamped_log_path("candidate_generation")
    )

    # Log configuration
    logger.info("=" * 80)
    logger.info("B3: Batch Review Candidate Generation")
    logger.info("=" * 80)
    logger.info(f"Database: {db_url}")
    if args.filing_ids:
        logger.info(f"Mode: Specific filing IDs: {args.filing_ids}")
    else:
        logger.info(f"Mode: Query filings needing candidates (limit: {args.limit})")
    if args.batch_id:
        logger.info(f"Batch ID: {args.batch_id}")
    logger.info(f"Dry run: {args.dry_run}")
    logger.info("=" * 80)

    # Connect to database
    logger.info("Connecting to database...")
    db = DatabaseAdapter(db_url)

    # Get filings to process
    if args.filing_ids:
        try:
            filing_ids = parse_filing_ids(args.filing_ids)
            logger.info(f"Fetching {len(filing_ids)} specific filings...")
            filings = get_filings_by_ids(db, filing_ids)
        except ValueError as e:
            logger.error(f"Error parsing filing IDs: {e}")
            sys.exit(1)
    else:
        logger.info(f"Querying filings needing candidates (limit: {args.limit})...")
        filings = get_filings_needing_candidates(db, args.limit)

    if not filings:
        logger.warning("No filings found to process")
        logger.info("=" * 80)
        sys.exit(0)

    logger.info(f"Found {len(filings)} filings to process")
    logger.info("")

    # Process filings
    stats = process_filings(
        db=db,
        filings=filings,
        dry_run=args.dry_run,
        batch_id=args.batch_id,
        show_progress=not args.no_progress,
    )

    # Report summary
    report_summary(stats, len(filings), args.dry_run)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        logger.warning("\n\nProcess interrupted by user")
        sys.exit(1)
    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
        sys.exit(1)
