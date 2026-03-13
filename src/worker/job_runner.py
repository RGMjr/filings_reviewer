"""
Extraction job runner.

Polls extraction_jobs for pending work, runs V2Pipeline for each job,
and updates job status. Designed to run as a long-lived container process.

Usage:
    python3 -m src.worker.job_runner
"""

import logging
import os
import signal
import sys
import time

from src.infra.db import DatabaseAdapter
from src.infra.filing_storage import get_filing_html_path
from src.infra.logging_config import configure_logging

logger = logging.getLogger(__name__)

POLL_INTERVAL_SECONDS = 5


def _claim_next_job(db) -> dict | None:
    """
    Atomically claim the next pending job.

    Uses UPDATE ... WHERE status='pending' ... RETURNING to prevent
    two workers from claiming the same job.
    """
    result = db.query(
        """
        UPDATE extraction_jobs
        SET status = 'running', started_at = now()
        WHERE id = (
            SELECT id FROM extraction_jobs
            WHERE status = 'pending'
            ORDER BY created_at
            LIMIT 1
            FOR UPDATE SKIP LOCKED
        )
        RETURNING id, filing_id
        """,
        {},
    )
    return result[0] if result else None


def _mark_complete(db, job_id: int) -> None:
    db.execute(
        "UPDATE extraction_jobs SET status = 'complete', completed_at = now() WHERE id = %(id)s",
        {"id": job_id},
    )


def _mark_failed(db, job_id: int, error: str) -> None:
    db.execute(
        """
        UPDATE extraction_jobs
        SET status = 'failed', completed_at = now(), error = %(error)s
        WHERE id = %(id)s
        """,
        {"id": job_id, "error": error[:2000]},  # truncate to avoid oversized error strings
    )


def _run_job(db, job: dict) -> None:
    """Run V2 pipeline for a single job."""
    job_id = job["id"]
    filing_id = job["filing_id"]

    logger.info(f"Job {job_id}: starting extraction for filing_id={filing_id}")

    from src.extraction_v2.pipeline import PipelineConfig, V2Pipeline

    config = PipelineConfig(
        enable_image_extraction=os.environ.get("V2_ENABLE_IMAGES", "true").lower() == "true",
        min_confidence_auto_accept=float(os.environ.get("V2_MIN_CONFIDENCE", "0.5")),
    )
    pipeline = V2Pipeline(config=config)

    try:
        with get_filing_html_path(filing_id, None, db) as html_path:
            result = pipeline.process(html_path=html_path, filing_id=filing_id)

        logger.info(
            f"Job {job_id}: extracted {result.fact_count} facts "
            f"in {result.total_duration_ms}ms for filing_id={filing_id}"
        )
        _mark_complete(db, job_id)

    except RuntimeError as exc:
        # No HTML available — permanent failure
        logger.error(f"Job {job_id}: no HTML content for filing_id={filing_id}: {exc}")
        _mark_failed(db, job_id, str(exc))

    except Exception as exc:
        logger.error(
            f"Job {job_id}: extraction failed for filing_id={filing_id}: {exc}",
            exc_info=True,
        )
        _mark_failed(db, job_id, f"{type(exc).__name__}: {exc}")


def run(database_url: str) -> None:
    """Main poll loop. Runs until SIGINT/SIGTERM."""
    db = DatabaseAdapter(database_url)
    logger.info("Extraction worker started. Polling for pending jobs...")

    running = True

    def _stop(signum, frame):
        nonlocal running
        logger.info(f"Received signal {signum}, shutting down after current job...")
        running = False

    signal.signal(signal.SIGINT, _stop)
    signal.signal(signal.SIGTERM, _stop)

    while running:
        try:
            job = _claim_next_job(db)
            if job:
                _run_job(db, job)
            else:
                time.sleep(POLL_INTERVAL_SECONDS)
        except Exception as exc:
            logger.error(f"Worker loop error: {exc}", exc_info=True)
            time.sleep(POLL_INTERVAL_SECONDS)

    logger.info("Extraction worker stopped.")


if __name__ == "__main__":
    configure_logging(level=os.environ.get("LOG_LEVEL", "INFO"))

    database_url = os.environ.get("DATABASE_URL", "")
    if not database_url:
        logger.error("DATABASE_URL environment variable is required")
        sys.exit(1)

    run(database_url)
