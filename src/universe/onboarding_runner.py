"""
Batch ingestion runner for v2_ingest_batches.

Drains queued batches from the database, running the onboard pipeline for each
filing in sequence and writing progress to v2_ingest_batch_filings.

Entry point:
    python3 -m src.universe.onboarding_runner --batch-id <UUID>
    python3 -m src.universe.onboarding_runner --watch [--poll-interval 10]

CLI flags
---------
--batch-id UUID         Process a single batch then exit.
--watch                 Long-running mode; claim queued batches one at a time.
--poll-interval N       Watch-mode sleep between claims (default: 10 seconds).
--verbose               DEBUG-level logging.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import signal
import time
import uuid
from collections.abc import Callable
from typing import Any

from dotenv import load_dotenv

from src.infra.db import DatabaseAdapter
from src.infra.logging_config import configure_logging
from src.infra.sec_client import SECClient
from src.universe.onboarding import (
    FORM_TYPE_BUNDLES,
    FilingEvent,
    load_candidates_by_filing_ids,
    onboard,
)
from src.universe.universe_builder import UniverseBuilder

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Global shutdown flag — set by SIGINT / SIGTERM handler
# ---------------------------------------------------------------------------

_shutdown_requested: bool = False


def _signal_handler(signum: int, frame: Any) -> None:  # noqa: ANN401
    global _shutdown_requested
    _shutdown_requested = True
    logger.info("Shutdown signal received (%s); will stop after current filing.", signum)


# ---------------------------------------------------------------------------
# Claim SQL (exact copy per API contract)
# ---------------------------------------------------------------------------

_CLAIM_SQL = """\
UPDATE v2_ingest_batches
SET run_lock_until = NOW() + (INTERVAL '1 second' * %(ttl)s),
    status = CASE WHEN status='queued' THEN 'running' ELSE status END,
    started_at = COALESCE(started_at, NOW())
WHERE batch_id = %(batch_id)s
  AND status IN ('queued','running')
  AND (run_lock_until IS NULL OR run_lock_until < NOW())
RETURNING batch_id, kind, reviewer_id, criteria, resolved_query, limits,
          total_filings, status, started_at;
"""

_CLAIM_NEXT_SQL = """\
UPDATE v2_ingest_batches
SET run_lock_until = NOW() + (INTERVAL '1 second' * %(ttl)s),
    status = CASE WHEN status='queued' THEN 'running' ELSE status END,
    started_at = COALESCE(started_at, NOW())
WHERE batch_id = (
    SELECT batch_id FROM v2_ingest_batches
    WHERE status IN ('queued','running')
      AND (run_lock_until IS NULL OR run_lock_until < NOW())
    ORDER BY created_at
    LIMIT 1
)
RETURNING batch_id, kind, reviewer_id, criteria, resolved_query, limits,
          total_filings, status, started_at;
"""

_HEARTBEAT_SQL = """\
UPDATE v2_ingest_batches
SET run_lock_until = NOW() + (INTERVAL '1 second' * %(ttl)s)
WHERE batch_id = %(batch_id)s;
"""

_PROGRESS_STARTED_SQL = """\
UPDATE v2_ingest_batch_filings
SET current_status = 'fetching',
    started_at = NOW()
WHERE batch_id = %(batch_id)s AND filing_id = %(filing_id)s;
"""

_PROGRESS_SUCCEEDED_SQL = """\
UPDATE v2_ingest_batch_filings
SET current_status = 'persisted',
    fact_count = %(fact_count)s,
    finished_at = NOW()
WHERE batch_id = %(batch_id)s AND filing_id = %(filing_id)s;
"""

_PROGRESS_FAILED_SQL = """\
UPDATE v2_ingest_batch_filings
SET current_status = 'failed',
    error = %(error)s,
    finished_at = NOW()
WHERE batch_id = %(batch_id)s AND filing_id = %(filing_id)s;
"""

_PROGRESS_SKIPPED_SQL = """\
UPDATE v2_ingest_batch_filings
SET current_status = 'skipped',
    finished_at = NOW()
WHERE batch_id = %(batch_id)s AND filing_id = %(filing_id)s;
"""

_CANCEL_QUEUED_SQL = """\
UPDATE v2_ingest_batch_filings
SET current_status = 'cancelled', finished_at = NOW()
WHERE batch_id = %s AND current_status = 'queued';
"""

_BATCH_COMPLETE_SQL = """\
UPDATE v2_ingest_batches
SET status = 'complete', finished_at = NOW(), run_lock_until = NULL
WHERE batch_id = %s AND status = 'running';
"""

_FINALIZE_CANCEL_SQL = """\
UPDATE v2_ingest_batches
SET finished_at = NOW()
WHERE batch_id = %s AND status = 'cancelled' AND finished_at IS NULL;
"""

_BATCH_FAILED_SQL = """\
UPDATE v2_ingest_batches
SET status = 'failed', finished_at = NOW(), error = %s
WHERE batch_id = %s;
"""

_BATCH_STATUS_SQL = """\
SELECT status FROM v2_ingest_batches WHERE batch_id = %s;
"""

_BATCH_FILINGS_SQL = """\
SELECT filing_id, initial_bucket
FROM v2_ingest_batch_filings
WHERE batch_id = %s
ORDER BY filing_id;
"""

_POPULATE_PROGRESS_SQL = """\
UPDATE v2_ingest_batches
SET limits = jsonb_set(coalesce(limits, '{}'::jsonb), '{populate_progress}', %s::jsonb)
WHERE batch_id = %s;
"""

_FACT_COUNT_RE = re.compile(r"(\d+)\s+facts")


# ---------------------------------------------------------------------------
# Public functions
# ---------------------------------------------------------------------------


def claim_batch(
    db: DatabaseAdapter,
    batch_id: uuid.UUID,
    lock_ttl_seconds: int = 900,
) -> dict[str, Any] | None:
    """Attempt to claim *batch_id* for exclusive processing.

    Returns the batch row dict on success, or ``None`` if the batch is not
    claimable (already running, completed, failed, or locked by another worker).
    """
    rows = db.query(_CLAIM_SQL, {"batch_id": str(batch_id), "ttl": lock_ttl_seconds})
    return dict(rows[0]) if rows else None


def claim_next_queued_batch(
    db: DatabaseAdapter,
    lock_ttl_seconds: int = 900,
) -> dict[str, Any] | None:
    """Claim the oldest queued batch.

    Returns the batch row dict on success, or ``None`` if no batch is available.
    """
    rows = db.query(_CLAIM_NEXT_SQL, {"ttl": lock_ttl_seconds})
    return dict(rows[0]) if rows else None


def build_progress_cb(
    db: DatabaseAdapter,
    batch_id: uuid.UUID,
    lock_ttl_seconds: int = 900,
) -> Callable[[FilingEvent], None]:
    """Return a closure that writes FilingEvent progress to v2_ingest_batch_filings.

    Also extends run_lock_until on every call (heartbeat) to prevent watcher
    takeover on batches with many/slow filings.
    """
    batch_id_str = str(batch_id)

    def _cb(event: FilingEvent) -> None:
        # Extend the lock on every event (cheap heartbeat).
        db.execute(_HEARTBEAT_SQL, {"batch_id": batch_id_str, "ttl": lock_ttl_seconds})

        fid = event.filing_id
        status = event.status

        if status == "started":
            db.execute(_PROGRESS_STARTED_SQL, {"batch_id": batch_id_str, "filing_id": fid})

        elif status == "succeeded":
            m = _FACT_COUNT_RE.search(event.message)
            fact_count = int(m.group(1)) if m else None
            db.execute(
                _PROGRESS_SUCCEEDED_SQL,
                {"batch_id": batch_id_str, "filing_id": fid, "fact_count": fact_count},
            )

        elif status == "failed":
            db.execute(
                _PROGRESS_FAILED_SQL,
                {"batch_id": batch_id_str, "filing_id": fid, "error": event.message},
            )

        elif status == "skipped_reviewed":
            db.execute(_PROGRESS_SKIPPED_SQL, {"batch_id": batch_id_str, "filing_id": fid})

        else:
            logger.warning("build_progress_cb: unknown status %r for filing_id=%d", status, fid)

    return _cb


def should_abort(db: DatabaseAdapter, batch_id: uuid.UUID) -> bool:
    """Return True if the batch has been cancelled or a shutdown was requested.

    Used as the abort_check callable passed to onboard().
    """
    if _shutdown_requested:
        return True
    rows = db.query(_BATCH_STATUS_SQL, [str(batch_id)])
    if not rows:
        return False
    return str(rows[0]["status"]) == "cancelled"


def run_one(db: DatabaseAdapter, batch_row: dict[str, Any]) -> None:
    """Dispatch a single claimed batch to the appropriate handler based on kind.

    Raises ValueError for unknown batch kinds.
    """
    kind = batch_row.get("kind", "onboard")
    if kind == "onboard":
        _run_onboard(db, batch_row)
    elif kind == "populate":
        _run_populate(db, batch_row)
    else:
        raise ValueError(f"Unknown batch kind: {kind!r}")


def _run_onboard(db: DatabaseAdapter, batch_row: dict[str, Any]) -> None:
    """Process a single onboard batch to completion.

    Steps:
    1. Load candidates from v2_ingest_batch_filings.
    2. Reconstruct Candidate objects via load_candidates_by_filing_ids.
    3. Build reextract_decisions from initial_bucket column.
    4. Call onboard() with progress_cb and abort_check.
    5. On completion: mark batch complete.  On exception: mark batch failed.
    After abort_check fires: flip remaining queued filings to cancelled.
    """
    batch_id_str = str(batch_row["batch_id"])
    batch_id = uuid.UUID(batch_id_str)

    logger.info("_run_onboard: starting batch_id=%s", batch_id_str)

    # 1. Load per-filing rows.
    filing_rows = db.query(_BATCH_FILINGS_SQL, [batch_id_str])
    filing_ids = [int(r["filing_id"]) for r in filing_rows]
    reextract_decisions: dict[int, bool] = {
        int(r["filing_id"]): (r["initial_bucket"] in ("reextract", "reextract_reviewed"))
        for r in filing_rows
    }

    # 2. Reconstruct Candidate objects.
    candidates = load_candidates_by_filing_ids(db, filing_ids)
    logger.info("_run_onboard: batch_id=%s, %d candidates loaded", batch_id_str, len(candidates))

    # 3. Build callbacks.
    progress_cb = build_progress_cb(db, batch_id)

    def _abort_check() -> bool:
        return should_abort(db, batch_id)

    # 4. Run the pipeline.
    try:
        onboard(
            db,
            candidates,
            reextract_decisions,
            progress_cb=progress_cb,
            abort_check=_abort_check,
        )
    except Exception as exc:  # noqa: BLE001
        error_msg = repr(exc)[:500]
        logger.exception("_run_onboard: unhandled exception in batch_id=%s", batch_id_str)
        db.execute(_BATCH_FAILED_SQL, [error_msg, batch_id_str])
        return

    # 5. Post-run: check whether we aborted.
    if _abort_check():
        logger.info(
            "_run_onboard: batch_id=%s aborted — flipping remaining queued to cancelled",
            batch_id_str,
        )
        db.execute(_CANCEL_QUEUED_SQL, [batch_id_str])
        # Leave batch status as 'cancelled' (already set by caller via API).
        # Finalize finished_at if not yet set.
        db.execute(_FINALIZE_CANCEL_SQL, [batch_id_str])
        return

    db.execute(_BATCH_COMPLETE_SQL, [batch_id_str])
    db.execute(_FINALIZE_CANCEL_SQL, [batch_id_str])
    logger.info("_run_onboard: batch_id=%s complete", batch_id_str)


def _run_populate(db: DatabaseAdapter, batch_row: dict[str, Any]) -> None:
    """Process a single populate batch using UniverseBuilder.

    Steps:
    1. Parse criteria (year + form_type).
    2. Resolve form_types via FORM_TYPE_BUNDLES.
    3. Define a progress callback that writes populate_progress JSONB and heartbeats.
    4. Call UniverseBuilder.build_universe with progress_cb.
    5. On success: mark complete (conditional) + finalize cancel if needed.
       On exception: mark failed.
    Does NOT touch v2_ingest_batch_filings — populate has no per-filing rows.
    """
    batch_id_str = str(batch_row["batch_id"])
    lock_ttl_seconds = 900

    logger.info("_run_populate: starting batch_id=%s", batch_id_str)

    # 1. Parse criteria.
    criteria = batch_row.get("criteria") or {}
    if isinstance(criteria, str):
        criteria = json.loads(criteria)
    year = int(criteria["year"])
    form_type = str(criteria["form_type"])

    start = f"{year}-01-01"
    end = f"{year}-12-31"

    # 2. Resolve form types.
    resolved = FORM_TYPE_BUNDLES.get(form_type, [form_type])

    # 3. Define progress callback.
    def _cb(processed: int, total: int) -> None:
        progress_json = json.dumps({"processed": processed, "total": total})
        db.execute(_POPULATE_PROGRESS_SQL, [progress_json, batch_id_str])
        db.execute(_HEARTBEAT_SQL, {"batch_id": batch_id_str, "ttl": lock_ttl_seconds})

    # 4. Build and call UniverseBuilder.
    user_agent = os.environ.get("SEC_USER_AGENT", "filings-reviewer info@example.com")
    sec_client = SECClient(user_agent=user_agent)
    builder = UniverseBuilder(sec_client=sec_client, db=db)

    try:
        builder.build_universe(start, end, form_types=resolved, progress_cb=_cb)
    except Exception as exc:  # noqa: BLE001
        error_msg = repr(exc)[:500]
        logger.exception("_run_populate: unhandled exception in batch_id=%s", batch_id_str)
        db.execute(_BATCH_FAILED_SQL, [error_msg, batch_id_str])
        return

    # 5. Mark complete (conditional: only if still 'running'; no-op if cancelled).
    db.execute(_BATCH_COMPLETE_SQL, [batch_id_str])
    # Finalize finished_at for cancelled-mid-run case.
    db.execute(_FINALIZE_CANCEL_SQL, [batch_id_str])
    logger.info("_run_populate: batch_id=%s done", batch_id_str)


def main() -> int:
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        prog="onboarding_runner",
        description="Batch ingestion runner — drain queued v2_ingest_batches.",
    )
    mode_group = parser.add_mutually_exclusive_group(required=True)
    mode_group.add_argument(
        "--batch-id",
        metavar="UUID",
        help="Process a single batch then exit.",
    )
    mode_group.add_argument(
        "--watch",
        action="store_true",
        help="Long-running mode; claim queued batches one at a time.",
    )
    parser.add_argument(
        "--poll-interval",
        type=int,
        default=10,
        metavar="SECONDS",
        help="Watch-mode sleep between claim attempts (default: 10).",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable DEBUG logging.",
    )

    args = parser.parse_args()

    configure_logging(level="DEBUG" if args.verbose else "INFO")

    # Install signal handlers.
    signal.signal(signal.SIGINT, _signal_handler)
    signal.signal(signal.SIGTERM, _signal_handler)

    load_dotenv()
    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        logger.error("DATABASE_URL environment variable is not set.")
        return 1

    db = DatabaseAdapter(db_url)

    if args.batch_id:
        try:
            batch_uuid = uuid.UUID(args.batch_id)
        except ValueError:
            logger.error("Invalid UUID: %s", args.batch_id)
            return 1

        batch_row = claim_batch(db, batch_uuid)
        if batch_row is None:
            logger.error(
                "batch_id=%s is not claimable (not queued/running, locked, or does not exist).",
                args.batch_id,
            )
            return 1

        run_one(db, batch_row)
        return 0

    # --watch mode
    logger.info("Entering watch mode (poll_interval=%ds).", args.poll_interval)
    while not _shutdown_requested:
        batch_row = claim_next_queued_batch(db)
        if batch_row is not None:
            run_one(db, batch_row)
        else:
            logger.debug("No queued batches; sleeping %ds.", args.poll_interval)
            time.sleep(args.poll_interval)

    logger.info("Shutdown requested — exiting watch loop.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
