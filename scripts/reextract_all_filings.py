#!/usr/bin/env python3
"""
Re-extraction Script for Phase 1 Quality Fixes (EI-7).

Applies all Phase 1 extraction quality fixes (EI-1 through EI-5) to all existing
filings in the database, replacing old extraction data with higher-quality results.

The script:
1. Queries all filings with extracted source_segments
2. For each filing:
   - Deletes existing metric_values (preserves segments)
   - Re-runs extraction pipeline with EI-1 to EI-5 fixes
   - Inserts new values with improved quality
3. Tracks progress with logging and checkpoint files
4. Supports resume capability for interrupted runs

Usage:
    # Dry run - see what would be done
    python scripts/reextract_all_filings.py --dry-run

    # Test single filing
    python scripts/reextract_all_filings.py --filing-id 123 --dry-run

    # Limited run for testing
    python scripts/reextract_all_filings.py --limit 5

    # Full re-extraction with custom batch size
    python scripts/reextract_all_filings.py --batch-size 10

    # Resume from specific filing after interrupt
    python scripts/reextract_all_filings.py --resume-from 456
"""

import argparse
import json
import logging
import os
import signal
import sys
import time
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv()

from src.infra.db import DatabaseAdapter
from src.infra.logging_config import configure_logging, get_timestamped_log_path
from src.extraction.extraction_pipeline import ExtractionPipeline
from src.llm.openai_client import OpenAIClient

# Configure logging with file output for long-running extractions
configure_logging(
    level="INFO",
    log_file=get_timestamped_log_path("reextract"),
)
logger = logging.getLogger(__name__)

# Progress file for resume capability
PROGRESS_FILE = Path("logs/reextract_progress.json")


@dataclass
class ReextractionStats:
    """Track re-extraction statistics."""
    total_filings: int = 0
    processed: int = 0
    skipped: int = 0
    errors: int = 0
    values_before: int = 0
    values_after: int = 0
    start_time: float = 0.0
    last_filing_id: Optional[int] = None

    def elapsed_minutes(self) -> float:
        """Return elapsed time in minutes."""
        if self.start_time == 0:
            return 0
        return (time.time() - self.start_time) / 60

    def filings_per_minute(self) -> float:
        """Calculate processing rate."""
        elapsed = self.elapsed_minutes()
        if elapsed == 0:
            return 0
        return self.processed / elapsed

    def eta_minutes(self) -> float:
        """Estimate time remaining in minutes."""
        rate = self.filings_per_minute()
        if rate == 0:
            return 0
        remaining = self.total_filings - self.processed
        return remaining / rate


class ReextractionRunner:
    """Handles re-extraction of all filings with progress tracking."""

    def __init__(
        self,
        db: DatabaseAdapter,
        llm_client: Optional[OpenAIClient] = None,
        dry_run: bool = False,
        batch_size: int = 10,
    ):
        self.db = db
        self.llm_client = llm_client
        self.dry_run = dry_run
        self.batch_size = batch_size
        self.stats = ReextractionStats()
        self._interrupted = False

        # Set up interrupt handler
        signal.signal(signal.SIGINT, self._handle_interrupt)
        signal.signal(signal.SIGTERM, self._handle_interrupt)

    def _handle_interrupt(self, signum, frame):
        """Handle Ctrl+C gracefully."""
        logger.warning("\nInterrupt received, saving progress and exiting...")
        self._interrupted = True

    def get_filings_to_process(
        self,
        limit: Optional[int] = None,
        resume_from: Optional[int] = None,
        filing_id: Optional[int] = None,
    ) -> List[Dict]:
        """
        Get list of filings to re-extract.

        Args:
            limit: Maximum number of filings to process
            resume_from: Start from this filing_id (skip earlier ones)
            filing_id: Process only this specific filing

        Returns:
            List of filing records with company info
        """
        if filing_id:
            # Single filing mode
            query = """
                SELECT
                    f.filing_id,
                    f.company_id,
                    c.company_name,
                    f.html_storage_path,
                    f.processing_status,
                    (SELECT COUNT(*) FROM metric_values mv WHERE mv.filing_id = f.filing_id) as value_count
                FROM filings f
                JOIN companies c ON f.company_id = c.company_id
                WHERE f.filing_id = %(filing_id)s
            """
            return self.db.query(query, {"filing_id": filing_id})

        # All filings with extracted segments
        query = """
            SELECT DISTINCT
                f.filing_id,
                f.company_id,
                c.company_name,
                f.html_storage_path,
                f.processing_status,
                (SELECT COUNT(*) FROM metric_values mv WHERE mv.filing_id = f.filing_id) as value_count
            FROM filings f
            JOIN companies c ON f.company_id = c.company_id
            WHERE EXISTS (
                SELECT 1 FROM source_segments ss WHERE ss.filing_id = f.filing_id
            )
        """
        params: Dict = {}

        if resume_from:
            query += " AND f.filing_id >= %(resume_from)s"
            params["resume_from"] = resume_from

        query += " ORDER BY f.filing_id"

        if limit:
            query += " LIMIT %(limit)s"
            params["limit"] = limit

        return self.db.query(query, params)

    def get_total_values_count(self, filing_ids: List[int]) -> int:
        """Count total metric_values across filings."""
        if not filing_ids:
            return 0
        query = """
            SELECT COUNT(*) as count
            FROM metric_values
            WHERE filing_id = ANY(%(filing_ids)s)
        """
        result = self.db.query(query, {"filing_ids": filing_ids})
        return result[0]["count"] if result else 0

    def delete_metric_values_for_filing(self, filing_id: int) -> int:
        """
        Delete metric_values for a filing (preserves source_segments).

        Returns count of deleted values.
        """
        # First get count
        count_result = self.db.query(
            "SELECT COUNT(*) as count FROM metric_values WHERE filing_id = %(filing_id)s",
            {"filing_id": filing_id}
        )
        count = count_result[0]["count"] if count_result else 0

        if count > 0 and not self.dry_run:
            # Also delete metric_definitions to avoid foreign key issues
            self.db.execute(
                "DELETE FROM metric_definitions WHERE filing_id = %(filing_id)s",
                {"filing_id": filing_id}
            )
            # Delete filing_metric_incidence
            self.db.execute(
                "DELETE FROM filing_metric_incidence WHERE filing_id = %(filing_id)s",
                {"filing_id": filing_id}
            )
            # Delete metric_values
            self.db.execute(
                "DELETE FROM metric_values WHERE filing_id = %(filing_id)s",
                {"filing_id": filing_id}
            )

        return count

    def reextract_filing(self, filing: Dict) -> Optional[int]:
        """
        Re-extract a single filing.

        Returns new value count, or None on error.
        """
        filing_id = filing["filing_id"]
        company_name = filing["company_name"]

        logger.info(f"Processing filing {filing_id}: {company_name}")

        # Check HTML file exists
        html_path = filing.get("html_storage_path")
        if not html_path or not Path(html_path).exists():
            logger.warning(f"  HTML file not found: {html_path}")
            return None

        # Delete existing values
        old_count = self.delete_metric_values_for_filing(filing_id)
        self.stats.values_before += old_count

        if self.dry_run:
            logger.info(f"  [DRY RUN] Would delete {old_count} values and re-extract")
            return old_count  # Return old count as estimate

        # Delete source_segments to force full re-segmentation
        # (EI-5 cell boundary markers need fresh segmentation)
        self.db.execute(
            "DELETE FROM source_segments WHERE filing_id = %(filing_id)s",
            {"filing_id": filing_id}
        )

        # Run extraction pipeline
        pipeline = ExtractionPipeline(db=self.db, llm_client=self.llm_client)

        try:
            result = pipeline.process_filing(filing_id)

            if not result.success:
                logger.error(f"  Extraction failed: {result.error}")
                return None

            new_count = result.num_values
            self.stats.values_after += new_count

            change = new_count - old_count
            change_str = f"+{change}" if change >= 0 else str(change)
            logger.info(f"  Extracted {new_count} values (was {old_count}, {change_str})")

            return new_count

        except Exception as e:
            logger.exception(f"  Exception during extraction: {e}")
            return None

    def save_progress(self):
        """Save progress to checkpoint file."""
        PROGRESS_FILE.parent.mkdir(parents=True, exist_ok=True)

        progress = {
            "last_filing_id": self.stats.last_filing_id,
            "processed": self.stats.processed,
            "errors": self.stats.errors,
            "values_before": self.stats.values_before,
            "values_after": self.stats.values_after,
            "timestamp": datetime.now().isoformat(),
        }

        with open(PROGRESS_FILE, "w") as f:
            json.dump(progress, f, indent=2)

        logger.info(f"Progress saved to {PROGRESS_FILE}")

    def load_progress(self) -> Optional[Dict]:
        """Load progress from checkpoint file."""
        if not PROGRESS_FILE.exists():
            return None

        with open(PROGRESS_FILE) as f:
            return json.load(f)

    def run(
        self,
        limit: Optional[int] = None,
        resume_from: Optional[int] = None,
        filing_id: Optional[int] = None,
    ):
        """
        Run re-extraction on all filings.

        Args:
            limit: Maximum number of filings to process
            resume_from: Start from this filing_id
            filing_id: Process only this specific filing
        """
        logger.info("=" * 60)
        logger.info("EI-7: Re-extraction with Phase 1 Quality Fixes")
        logger.info("=" * 60)

        if self.dry_run:
            logger.info("DRY RUN MODE - No database modifications will be made")

        # Get filings to process
        filings = self.get_filings_to_process(
            limit=limit,
            resume_from=resume_from,
            filing_id=filing_id,
        )

        if not filings:
            logger.info("No filings to process")
            return

        self.stats.total_filings = len(filings)
        filing_ids = [f["filing_id"] for f in filings]
        initial_value_count = self.get_total_values_count(filing_ids)

        logger.info(f"Found {len(filings)} filings to re-extract")
        logger.info(f"Current total metric_values: {initial_value_count}")

        if resume_from:
            logger.info(f"Resuming from filing_id >= {resume_from}")

        if limit:
            logger.info(f"Limited to {limit} filings")

        logger.info("")

        # Process filings
        self.stats.start_time = time.time()
        batch_count = 0

        for i, filing in enumerate(filings):
            if self._interrupted:
                break

            filing_id = filing["filing_id"]
            self.stats.last_filing_id = filing_id

            # Progress logging every 10 filings
            if i > 0 and i % 10 == 0:
                rate = self.stats.filings_per_minute()
                eta = self.stats.eta_minutes()
                logger.info(
                    f"Progress: {i}/{self.stats.total_filings} "
                    f"({rate:.1f}/min, ETA: {eta:.1f} min)"
                )

            # Re-extract
            result = self.reextract_filing(filing)

            if result is None:
                self.stats.errors += 1
            else:
                self.stats.processed += 1

            batch_count += 1

            # Checkpoint every batch_size filings
            if batch_count >= self.batch_size:
                self.save_progress()
                batch_count = 0

        # Final save
        self.save_progress()

        # Print summary
        self._print_summary()

    def _print_summary(self):
        """Print final summary."""
        logger.info("")
        logger.info("=" * 60)
        logger.info("RE-EXTRACTION SUMMARY")
        logger.info("=" * 60)
        logger.info(f"Total filings:     {self.stats.total_filings}")
        logger.info(f"Processed:         {self.stats.processed}")
        logger.info(f"Errors:            {self.stats.errors}")
        logger.info(f"Values before:     {self.stats.values_before}")
        logger.info(f"Values after:      {self.stats.values_after}")

        if self.stats.values_before > 0:
            reduction = (1 - self.stats.values_after / self.stats.values_before) * 100
            logger.info(f"Change:            {reduction:+.1f}%")

        elapsed = self.stats.elapsed_minutes()
        logger.info(f"Elapsed time:      {elapsed:.1f} minutes")

        if self._interrupted:
            logger.info("")
            logger.info(f"INTERRUPTED - Resume with: --resume-from {self.stats.last_filing_id}")

        if self.dry_run:
            logger.info("")
            logger.info("[DRY RUN - No changes were made to the database]")


def main():
    parser = argparse.ArgumentParser(
        description="Re-extract all filings with Phase 1 quality fixes (EI-7)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Dry run - see what would be done
  python scripts/reextract_all_filings.py --dry-run

  # Test single filing
  python scripts/reextract_all_filings.py --filing-id 123 --dry-run

  # Limited run for testing
  python scripts/reextract_all_filings.py --limit 5

  # Full re-extraction
  python scripts/reextract_all_filings.py

  # Resume after interrupt
  python scripts/reextract_all_filings.py --resume-from 456
""",
    )

    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Log what would be done without making changes",
    )
    parser.add_argument(
        "--limit",
        type=int,
        metavar="N",
        help="Process only first N filings (for testing)",
    )
    parser.add_argument(
        "--resume-from",
        type=int,
        metavar="ID",
        help="Resume from filing_id (skip earlier filings)",
    )
    parser.add_argument(
        "--filing-id",
        type=int,
        metavar="ID",
        help="Process single filing only (for debugging)",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=10,
        metavar="N",
        help="Commit and checkpoint every N filings (default: 10)",
    )
    parser.add_argument(
        "--database-url",
        type=str,
        metavar="URL",
        help="Override DATABASE_URL environment variable",
    )
    parser.add_argument(
        "--no-llm",
        action="store_true",
        help="Use rule-based extraction only (no LLM calls)",
    )

    args = parser.parse_args()

    # Database connection
    db_url = args.database_url or os.getenv(
        "DATABASE_URL",
        "postgresql://localhost/filings_analysis"
    )
    db = DatabaseAdapter(db_url)

    # LLM client (optional)
    llm_client = None
    if not args.no_llm and not args.dry_run:
        try:
            llm_client = OpenAIClient()
            logger.info("LLM client initialized for hybrid extraction")
        except Exception as e:
            logger.warning(f"Could not initialize LLM client: {e}")
            logger.info("Proceeding with rule-based extraction only")

    # Create runner and execute
    runner = ReextractionRunner(
        db=db,
        llm_client=llm_client,
        dry_run=args.dry_run,
        batch_size=args.batch_size,
    )

    runner.run(
        limit=args.limit,
        resume_from=args.resume_from,
        filing_id=args.filing_id,
    )


if __name__ == "__main__":
    main()
