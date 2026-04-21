#!/usr/bin/env python3
"""
Batch V2 Extraction Script.

Runs the V2 extraction pipeline on multiple filings in parallel using
ProcessPoolExecutor. Supports checkpointing, graceful shutdown, and
quality scoring.

Usage:
    # Process all filings (4 workers)
    python3 scripts/batch_v2_extraction.py

    # Process first 10 filings
    python3 scripts/batch_v2_extraction.py --limit 10

    # Resume from last checkpoint
    python3 scripts/batch_v2_extraction.py --resume-from 1234

    # Single filing
    python3 scripts/batch_v2_extraction.py --filing-id 42

    # Dry run (no database writes)
    python3 scripts/batch_v2_extraction.py --dry-run --limit 5

    # Custom workers and batch size
    python3 scripts/batch_v2_extraction.py --workers 8 --batch-size 20
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import signal
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from concurrent.futures import TimeoutError as FuturesTimeoutError
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv  # noqa: E402

from src.extraction_v2.logging_config import configure_logging  # noqa: E402
from src.infra.db import DatabaseAdapter  # noqa: E402

load_dotenv()

configure_logging()
logger = logging.getLogger(__name__)

# Logs directory for checkpoints
LOGS_DIR = PROJECT_ROOT / "logs"
CHECKPOINT_FILE = LOGS_DIR / "batch_v2_progress.json"

# Global shutdown flag (set by SIGINT handler)
_shutdown_requested = False


def _handle_sigint(signum: int, frame: object) -> None:
    """Handle Ctrl+C gracefully."""
    global _shutdown_requested
    logger.info("Shutdown requested (SIGINT). Finishing current batch then stopping...")
    _shutdown_requested = True


def _load_filing_ids(path: str) -> list[int]:
    """Parse a filing_ids file: one integer per line, blank lines and '#' comments ignored."""
    ids: list[int] = []
    with open(path) as fh:
        for lineno, raw in enumerate(fh, start=1):
            line = raw.split("#", 1)[0].strip()
            if not line:
                continue
            try:
                ids.append(int(line))
            except ValueError as exc:
                raise ValueError(
                    f"{path}:{lineno}: expected integer filing_id, got {raw.rstrip()!r}"
                ) from exc
    return ids


@dataclass
class BatchConfig:
    """Configuration for batch extraction."""

    workers: int = 4
    batch_size: int = 10  # Checkpoint interval
    dry_run: bool = False
    resume_from: int | None = None  # Skip filing_ids < this value
    limit: int | None = None
    no_images: bool = False
    min_confidence: float = 0.90
    worker_timeout: int = 300  # Seconds before killing a hung worker
    status: str | None = None  # Filter filings by processing_status (e.g. 'fetched')
    force_reextract: bool = False  # Purge existing human decisions on re-extract
    filing_ids: list[int] | None = None  # Explicit whitelist of filing_ids to process


@dataclass
class BatchStats:
    """Runtime statistics for batch processing."""

    total_filings: int = 0
    processed: int = 0
    succeeded: int = 0
    failed: int = 0
    skipped: int = 0
    total_facts: int = 0
    start_time: float = field(default_factory=time.time)
    aborted_by_circuit_breaker: bool = False
    filing_results: list = field(default_factory=list)

    @property
    def elapsed_seconds(self) -> float:
        return time.time() - self.start_time

    @property
    def rate_per_minute(self) -> float:
        elapsed = self.elapsed_seconds
        if elapsed < 1:
            return 0.0
        return self.processed / elapsed * 60

    @property
    def eta_seconds(self) -> float | None:
        remaining = self.total_filings - self.processed
        rate = self.rate_per_minute
        if rate <= 0 or remaining <= 0:
            return None
        return remaining / rate * 60


def _process_filing_worker(
    filing_id: int,
    html_path: str | None,
    company_name: str,
    company_id: int,
    cik: str,
    accession_number: str,
    filing_date: object,
    db_url: str,
    config_dict: dict,
) -> dict:
    """
    Worker function for ProcessPoolExecutor.

    Must be a module-level function (not a method) for pickling.
    Creates its own DB connection and pipeline instance.

    Returns dict with: filing_id, success, fact_count, definition_count, error, duration_ms, retried
    """
    import sys
    from pathlib import Path as _Path

    _PROJECT_ROOT = _Path(__file__).parent.parent
    sys.path.insert(0, str(_PROJECT_ROOT))

    import logging as _logging

    _logger = _logging.getLogger(__name__)

    start_ms = int(time.time() * 1000)
    _temp_html_path = None

    try:
        import tempfile

        from src.extraction_v2.exceptions import ReviewedFilingError
        from src.extraction_v2.persistence import V2PersistenceAdapter
        from src.extraction_v2.pipeline import PipelineConfig, V2Pipeline
        from src.infra.db import DatabaseAdapter

        # Resolve HTML path
        if html_path:
            resolved_path = _Path(html_path)
        else:
            # Try gold standard directory
            company_slug = company_name.replace(" ", "_")
            resolved_path = _PROJECT_ROOT / "data" / "gold_standard" / company_slug / "filing.html"
            if os.environ.get("APP_ENV") == "production":
                _logger.warning(
                    f"Filing {filing_id}: no html_storage_path set; refusing gold-standard fallback in production"
                )
                raise RuntimeError(
                    f"Filing {filing_id} has no html_storage_path and APP_ENV=production forbids gold-standard fallback"
                )
            else:
                _logger.warning(
                    f"Filing {filing_id}: no html_storage_path set; falling back to gold-standard path {resolved_path}"
                )

        # DB fallback: when disk file is absent (e.g. Render ephemeral filesystem),
        # read html_content from the database column populated by FilingFetcher.
        if not resolved_path.exists():
            try:
                _fallback_db = DatabaseAdapter(db_url)
                rows = _fallback_db.query(
                    "SELECT html_content FROM filings WHERE filing_id = %(filing_id)s AND html_content IS NOT NULL",
                    {"filing_id": filing_id},
                )
                if rows and rows[0].get("html_content"):
                    _tmp = tempfile.NamedTemporaryFile(
                        mode="w", suffix=".htm", delete=False, encoding="utf-8"
                    )
                    _tmp.write(rows[0]["html_content"])
                    _tmp.close()
                    _temp_html_path = _tmp.name
                    resolved_path = _Path(_temp_html_path)
                    _logger.info(
                        f"Filing {filing_id}: disk file missing, using html_content from DB "
                        f"({len(rows[0]['html_content'])} chars) -> {_temp_html_path}"
                    )
            except Exception as _db_err:
                _logger.warning(
                    f"Filing {filing_id}: disk file missing and DB fallback failed: {_db_err}"
                )

        if not resolved_path.exists():
            return {
                "filing_id": filing_id,
                "success": False,
                "fact_count": 0,
                "definition_count": 0,
                "error": f"HTML not found on disk and not in DB: {html_path}",
                "duration_ms": 0,
                "retried": False,
            }

        # Configure pipeline
        pipeline_config = PipelineConfig(
            enable_image_extraction=not config_dict.get("no_images", False),
            enable_chart_extraction=not config_dict.get("no_images", False),
            min_confidence_auto_accept=config_dict.get("min_confidence", 0.90),
        )

        # Run pipeline
        pipeline = V2Pipeline(config=pipeline_config)
        result = pipeline.process(
            html_path=resolved_path,
            filing_id=filing_id,
            cik=cik,
            accession_number=accession_number,
            document_date=filing_date,
        )

        duration_ms = int(time.time() * 1000) - start_ms

        if config_dict.get("dry_run"):
            return {
                "filing_id": filing_id,
                "success": result.success,
                "fact_count": result.fact_count,
                "definition_count": len(result.definitions),
                "error": result.error_message,
                "duration_ms": duration_ms,
                "retried": False,
            }

        # Persist results
        db = DatabaseAdapter(db_url)
        adapter = V2PersistenceAdapter(db)
        try:
            persist_result = adapter.persist_pipeline_result(
                result, filing_id, force=config_dict.get("force_reextract", False)
            )
        except ReviewedFilingError as guard_err:
            # Non-destructive skip: filing has human decisions and --force-reextract
            # was not passed. Leave processing_status untouched so re-runs behave
            # consistently until the operator decides.
            return {
                "filing_id": filing_id,
                "success": False,
                "skipped_reviewed": True,
                "fact_count": 0,
                "definition_count": 0,
                "error": str(guard_err),
                "duration_ms": int(time.time() * 1000) - start_ms,
                "retried": False,
            }

        if not persist_result.success:
            try:
                db.execute(
                    "UPDATE filings SET processing_status = 'extraction_failed', updated_at = now()"
                    " WHERE filing_id = %(filing_id)s",
                    {"filing_id": filing_id},
                )
            except Exception:
                pass  # Best-effort; filing will retry on next cron run
            return {
                "filing_id": filing_id,
                "success": False,
                "fact_count": 0,
                "definition_count": 0,
                "error": str(persist_result.errors),
                "duration_ms": duration_ms,
                "retried": False,
            }

        # Mark filing as extracted so cron skips it on subsequent runs
        db.execute(
            "UPDATE filings SET processing_status = 'extracted', updated_at = now()"
            " WHERE filing_id = %(filing_id)s",
            {"filing_id": filing_id},
        )

        return {
            "filing_id": filing_id,
            "success": True,
            "fact_count": result.fact_count,
            "definition_count": len(result.definitions),
            "error": None,
            "duration_ms": duration_ms,
            "retried": False,
        }

    except Exception as e:
        duration_ms = int(time.time() * 1000) - start_ms
        # Best-effort: mark as failed so cron can retry or skip
        try:
            _db = DatabaseAdapter(db_url)
            _db.execute(
                "UPDATE filings SET processing_status = 'extraction_failed', updated_at = now()"
                " WHERE filing_id = %(filing_id)s",
                {"filing_id": filing_id},
            )
        except Exception:
            pass
        return {
            "filing_id": filing_id,
            "success": False,
            "fact_count": 0,
            "definition_count": 0,
            "error": str(e),
            "duration_ms": duration_ms,
            "retried": False,
        }
    finally:
        # Clean up temp file written from DB html_content fallback
        if _temp_html_path:
            try:
                os.unlink(_temp_html_path)
            except OSError:
                pass


class BatchV2Runner:
    """
    Batch runner for V2 extraction pipeline.

    Queries filings from the database and processes them in parallel
    using ProcessPoolExecutor.
    """

    def __init__(
        self, config: BatchConfig, db_url: str, db_adapter: DatabaseAdapter | None = None
    ) -> None:
        self.config = config
        self.db_url = db_url
        self._db_adapter = db_adapter
        self._stats = BatchStats()

    def query_filings(self) -> list[dict]:
        """Query filings from database."""
        db = self._db_adapter if self._db_adapter is not None else DatabaseAdapter(self.db_url)

        params: dict = {}
        where_clause = ""
        if self.config.filing_ids is not None:
            where_clause = "WHERE f.filing_id = ANY(%(filing_ids)s)"
            params["filing_ids"] = list(self.config.filing_ids)
        elif self.config.status:
            where_clause = "WHERE f.processing_status = %(status)s"
            params["status"] = self.config.status

        sql = f"""
            SELECT f.filing_id, f.accession_number, f.html_storage_path,
                   f.filing_date, c.company_name, c.company_id, c.cik
            FROM filings f
            JOIN companies c ON f.company_id = c.company_id
            {where_clause}
            ORDER BY f.filing_id
        """
        filings = db.query(sql, params)

        # Apply resume filter
        if self.config.resume_from is not None:
            filings = [f for f in filings if f["filing_id"] >= self.config.resume_from]
            logger.info(f"Resuming from filing_id={self.config.resume_from}")

        # Apply limit
        if self.config.limit is not None:
            filings = filings[: self.config.limit]

        return list(filings)

    def _save_checkpoint(self, stats: BatchStats, last_filing_id: int) -> None:
        """Save progress checkpoint to disk."""
        LOGS_DIR.mkdir(parents=True, exist_ok=True)
        checkpoint = {
            "timestamp": datetime.now(UTC).isoformat(),
            "last_filing_id": last_filing_id,
            "processed": stats.processed,
            "succeeded": stats.succeeded,
            "failed": stats.failed,
            "total_facts": stats.total_facts,
        }
        with open(CHECKPOINT_FILE, "w") as f:
            json.dump(checkpoint, f, indent=2)
        logger.debug(f"Checkpoint saved: last_filing_id={last_filing_id}")

    def _log_progress(self, stats: BatchStats) -> None:
        """Log progress with rate and ETA."""
        rate = stats.rate_per_minute
        eta = stats.eta_seconds
        eta_str = f"{eta:.0f}s" if eta is not None else "unknown"

        logger.info(
            f"Progress: {stats.processed}/{stats.total_filings} "
            f"({stats.succeeded} ok, {stats.failed} failed) "
            f"| Rate: {rate:.1f}/min | ETA: {eta_str} "
            f"| Facts: {stats.total_facts}"
        )

    def _submit_filing(
        self,
        executor: ProcessPoolExecutor,
        filing: dict,
        config_dict: dict,
    ) -> object:
        """Submit a single filing to the executor and return the future."""
        return executor.submit(
            _process_filing_worker,
            filing["filing_id"],
            filing.get("html_storage_path"),
            filing["company_name"],
            filing["company_id"],
            str(filing.get("cik", "")),
            str(filing.get("accession_number", "")),
            filing.get("filing_date"),
            self.db_url,
            config_dict,
        )

    def run(self, filings: list[dict], max_consecutive_failures: int = 10) -> BatchStats:
        """
        Run batch extraction with parallel workers.

        Args:
            filings: List of filing dicts from query_filings()
            max_consecutive_failures: Circuit breaker threshold

        Returns:
            BatchStats with final counts
        """
        from src.extraction_v2.exceptions import V2TransientError

        global _shutdown_requested

        stats = BatchStats(total_filings=len(filings))
        stats.start_time = time.time()

        if not filings:
            logger.info("No filings to process")
            return stats

        logger.info(
            f"Starting batch V2 extraction: {len(filings)} filings, "
            f"{self.config.workers} workers, "
            f"batch_size={self.config.batch_size}, "
            f"worker_timeout={self.config.worker_timeout}s"
        )

        config_dict = {
            "dry_run": self.config.dry_run,
            "no_images": self.config.no_images,
            "min_confidence": self.config.min_confidence,
            "force_reextract": self.config.force_reextract,
        }

        last_filing_id = 0
        consecutive_failures = 0
        # Track which filing_ids have already been retried (max 1 retry)
        retried_ids: set[int] = set()

        # Process in batches for checkpointing (single executor for all batches)
        batch_num = 0
        with ProcessPoolExecutor(max_workers=self.config.workers) as executor:
            for batch_start in range(0, len(filings), self.config.batch_size):
                if _shutdown_requested:
                    logger.info("Shutdown requested, stopping after current batch")
                    break

                if stats.aborted_by_circuit_breaker:
                    break

                batch = filings[batch_start : batch_start + self.config.batch_size]
                batch_num += 1

                futures: dict[object, dict] = {
                    self._submit_filing(executor, filing, config_dict): filing for filing in batch
                }

                for future in as_completed(futures):
                    filing = futures[future]
                    filing_id = filing["filing_id"]
                    try:
                        result = future.result(timeout=self.config.worker_timeout)
                    except FuturesTimeoutError:
                        # Cancel the future and log; the worker process will be
                        # reaped when the executor shuts down.
                        future.cancel()
                        logger.warning(
                            f"Worker timeout for filing {filing_id} "
                            f"(>{self.config.worker_timeout}s); future cancelled"
                        )
                        result = {
                            "filing_id": filing_id,
                            "success": False,
                            "fact_count": 0,
                            "definition_count": 0,
                            "error": f"worker timeout after {self.config.worker_timeout}s",
                            "duration_ms": self.config.worker_timeout * 1000,
                            "retried": False,
                        }
                    except Exception as exc:
                        # Check if this is a transient error eligible for retry
                        if isinstance(exc, V2TransientError) and filing_id not in retried_ids:
                            retried_ids.add(filing_id)
                            logger.warning(
                                f"Filing {filing_id} raised V2TransientError, retrying once: {exc}"
                            )
                            retry_future = self._submit_filing(executor, filing, config_dict)
                            try:
                                result = retry_future.result(timeout=self.config.worker_timeout)
                                result["retried"] = True
                            except Exception as retry_exc:
                                result = {
                                    "filing_id": filing_id,
                                    "success": False,
                                    "fact_count": 0,
                                    "definition_count": 0,
                                    "error": str(retry_exc),
                                    "duration_ms": 0,
                                    "retried": True,
                                }
                        else:
                            result = {
                                "filing_id": filing_id,
                                "success": False,
                                "fact_count": 0,
                                "definition_count": 0,
                                "error": str(exc),
                                "duration_ms": 0,
                                "retried": False,
                            }

                    stats.processed += 1
                    if result["success"]:
                        stats.succeeded += 1
                        stats.total_facts += result.get("fact_count", 0)
                        consecutive_failures = 0
                    elif result.get("skipped_reviewed"):
                        stats.skipped += 1
                        # Reset consecutive-failure counter: a reviewed-skip is not
                        # an extraction failure, so it shouldn't trip the breaker.
                        consecutive_failures = 0
                        logger.info(
                            f"Filing {result['filing_id']} skipped (has human review "
                            "decisions; pass --force-reextract to override)"
                        )
                    else:
                        stats.failed += 1
                        consecutive_failures += 1
                        logger.warning(
                            f"Filing {result['filing_id']} failed: {result.get('error', 'unknown')}"
                        )

                    # Accumulate per-filing result for summary report
                    stats.filing_results.append(
                        {
                            "filing_id": result["filing_id"],
                            "company_name": filing.get("company_name", ""),
                            "success": result["success"],
                            "skipped_reviewed": result.get("skipped_reviewed", False),
                            "fact_count": result.get("fact_count", 0),
                            "error": result.get("error"),
                            "duration_ms": result.get("duration_ms", 0),
                            "retried": result.get("retried", False),
                        }
                    )

                    last_filing_id = max(last_filing_id, result["filing_id"])

                    # Circuit breaker
                    if consecutive_failures >= max_consecutive_failures:
                        logger.error(
                            f"Circuit breaker triggered: {consecutive_failures} consecutive failures. "
                            "Aborting batch run."
                        )
                        stats.aborted_by_circuit_breaker = True
                        break

                    # Log progress every 10 filings
                    if stats.processed % 10 == 0:
                        self._log_progress(stats)

                # Checkpoint after each batch
                self._save_checkpoint(stats, last_filing_id)
                logger.info(
                    f"Batch {batch_num} complete: "
                    f"{min(batch_start + self.config.batch_size, len(filings))}/{len(filings)} done"
                )

        # Final summary
        elapsed = stats.elapsed_seconds
        logger.info(
            f"Batch extraction complete: "
            f"{stats.succeeded}/{stats.total_filings} succeeded, "
            f"{stats.failed} failed, "
            f"{stats.skipped} skipped (reviewed), "
            f"{stats.total_facts} total facts, "
            f"{elapsed:.1f}s elapsed"
        )

        return stats


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Batch V2 extraction pipeline",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--filing-id", type=int, help="Process a single filing by ID")
    parser.add_argument("--limit", type=int, help="Maximum number of filings to process")
    parser.add_argument("--resume-from", type=int, help="Skip filing_ids less than this value")
    parser.add_argument(
        "--workers", type=int, default=4, help="Number of parallel workers (default: 4)"
    )
    parser.add_argument(
        "--batch-size", type=int, default=10, help="Checkpoint interval in filings (default: 10)"
    )
    parser.add_argument("--dry-run", action="store_true", help="Run without persisting to database")
    parser.add_argument("--no-images", action="store_true", help="Disable image extraction")
    parser.add_argument(
        "--min-confidence", type=float, default=0.90, help="Min confidence for auto-accept"
    )
    parser.add_argument(
        "--status",
        type=str,
        help="Filter filings by processing_status (e.g. 'fetched')",
    )
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose logging")
    parser.add_argument(
        "--max-consecutive-failures",
        type=int,
        default=10,
        help="Abort if this many consecutive failures occur (default: 10)",
    )
    parser.add_argument(
        "--worker-timeout",
        type=int,
        default=300,
        help="Seconds before killing a hung worker process (default: 300)",
    )
    parser.add_argument(
        "--force-reextract",
        action="store_true",
        help=(
            "Purge existing human review decisions on filings that have them "
            "and re-extract. Without this flag, such filings are skipped "
            "(counted under 'skipped'); the batch continues."
        ),
    )
    parser.add_argument(
        "--filing-ids-file",
        type=str,
        default=None,
        help=(
            "Path to a file containing filing_ids to process, one per line. "
            "Blank lines and '#' comments are ignored. Mutually exclusive with "
            "--filing-id, --status, and --resume-from."
        ),
    )
    args = parser.parse_args()

    filing_ids: list[int] | None = None
    if args.filing_ids_file:
        conflicts = [
            name
            for name, val in (
                ("--filing-id", args.filing_id),
                ("--status", args.status),
                ("--resume-from", args.resume_from),
            )
            if val is not None
        ]
        if conflicts:
            print(
                f"ERROR: --filing-ids-file is mutually exclusive with {', '.join(conflicts)}",
                file=sys.stderr,
            )
            sys.exit(2)
        filing_ids = _load_filing_ids(args.filing_ids_file)
        if not filing_ids:
            print(
                f"ERROR: --filing-ids-file {args.filing_ids_file!r} contains no filing_ids",
                file=sys.stderr,
            )
            sys.exit(2)

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        print("ERROR: DATABASE_URL environment variable not set", file=sys.stderr)
        sys.exit(1)

    # Register SIGINT handler for graceful shutdown
    signal.signal(signal.SIGINT, _handle_sigint)

    config = BatchConfig(
        workers=args.workers,
        batch_size=args.batch_size,
        dry_run=args.dry_run,
        resume_from=args.resume_from,
        limit=args.limit,
        no_images=args.no_images,
        min_confidence=args.min_confidence,
        worker_timeout=args.worker_timeout,
        status=args.status,
        force_reextract=args.force_reextract,
        filing_ids=filing_ids,
    )

    runner = BatchV2Runner(config=config, db_url=db_url)

    # Single filing mode
    if args.filing_id:
        from src.infra.db import DatabaseAdapter

        db = DatabaseAdapter(db_url)
        rows = db.query(
            """
            SELECT f.filing_id, f.accession_number, f.html_storage_path,
                   f.filing_date, c.company_name, c.company_id, c.cik
            FROM filings f
            JOIN companies c ON f.company_id = c.company_id
            WHERE f.filing_id = %(filing_id)s
            """,
            {"filing_id": args.filing_id},
        )
        if not rows:
            print(f"ERROR: Filing {args.filing_id} not found", file=sys.stderr)
            sys.exit(1)
        filings = list(rows)
    else:
        filings = runner.query_filings()

    if not filings:
        logger.info("No filings to process")
        sys.exit(0)

    logger.info(f"Found {len(filings)} filings to process")

    stats = runner.run(filings, max_consecutive_failures=args.max_consecutive_failures)

    # Write summary JSON report
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    summary_path = LOGS_DIR / f"batch_v2_summary_{timestamp}.json"
    summary = {
        "run_date": datetime.now(UTC).isoformat(),
        "total_filings": stats.total_filings,
        "succeeded": stats.succeeded,
        "failed": stats.failed,
        "skipped": stats.skipped,
        "total_facts": stats.total_facts,
        "duration_seconds": round(stats.elapsed_seconds, 1),
        "aborted_by_circuit_breaker": stats.aborted_by_circuit_breaker,
        "per_filing": stats.filing_results,
    }
    with open(summary_path, "w") as f:
        json.dump(summary, f, indent=2)
    logger.info(f"Summary written to {summary_path}")

    # Exit with error if all failed or majority failed (>50% failure rate)
    if stats.failed > 0 and stats.succeeded == 0:
        sys.exit(1)
    if stats.failed > stats.succeeded:
        sys.exit(1)


if __name__ == "__main__":
    main()
