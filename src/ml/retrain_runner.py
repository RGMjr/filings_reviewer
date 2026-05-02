"""
Background retrain claim+run helpers for image-classifier retrains (gh-400).

Mirrors the queue+worker pattern in src/universe/onboarding_runner.py:
  1. Web POST inserts a model_training_runs row with status='queued'.
  2. A long-lived worker (filings-onboarding-runner) polls for queued rows,
     atomically claims one via UPDATE … RETURNING, sets run_lock_until, then
     shells out to scripts/retrain_image_triage.py.
  3. The script's own try/except writes the terminal status. If the worker
     dies mid-run, run_lock_until expires and another worker re-claims.

Why this exists: the previous shape spawned the retrain script as a detached
subprocess from a gunicorn web worker. Render container recycles silently
SIGKILL'd the subprocess, leaving the row 'running' forever and blocking
every future retrain. Web POSTs no longer own the lifetime of the work.
"""

from __future__ import annotations

import logging
import os
import subprocess
import sys
import time
import uuid
from pathlib import Path
from typing import Any

from src.infra.db import DatabaseAdapter

logger = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_RETRAIN_SCRIPT = _PROJECT_ROOT / "scripts" / "retrain_image_triage.py"

# Default TTL on a claim. Retrains take ~3 min on the current corpus, so 15
# minutes is comfortably long enough for one to finish without heartbeat
# extension; the heartbeat below covers slower runs and absorbs occasional
# pauses without rendering the lock window load-bearing.
DEFAULT_LOCK_TTL_SECONDS = 900

_CLAIM_NEXT_SQL = """\
UPDATE model_training_runs
SET status         = 'running',
    run_lock_until = NOW() + (INTERVAL '1 second' * %(ttl)s),
    started_at     = COALESCE(started_at, NOW())
WHERE id = (
    SELECT id FROM model_training_runs
    WHERE model_type = 'image_relevance'
      AND status     = 'queued'
      AND (run_lock_until IS NULL OR run_lock_until < NOW())
    ORDER BY started_at
    LIMIT 1
)
RETURNING id, model_type, status, started_at, triggered_by;
"""

_HEARTBEAT_SQL = """\
UPDATE model_training_runs
SET run_lock_until = NOW() + (INTERVAL '1 second' * %(ttl)s)
WHERE id = %(run_id)s
  AND status = 'running';
"""

_FAIL_NO_STATUS_SQL = """\
UPDATE model_training_runs
SET status         = 'failed',
    error          = 'retrain_subprocess_died_no_status',
    completed_at   = NOW(),
    run_lock_until = NULL
WHERE id = %(run_id)s
  AND status = 'running';
"""


def claim_next_queued_retrain(
    db: DatabaseAdapter,
    lock_ttl_seconds: int = DEFAULT_LOCK_TTL_SECONDS,
) -> dict[str, Any] | None:
    """Atomically claim the oldest queued image_relevance retrain.

    Returns the row dict on success, or None when no queued row is available
    (or another worker won the race). Mirrors the
    onboarding_runner.claim_next_queued_batch shape.
    """
    rows = db.query(_CLAIM_NEXT_SQL, {"ttl": lock_ttl_seconds})
    return dict(rows[0]) if rows else None


def extend_lock(
    db: DatabaseAdapter,
    run_id: uuid.UUID | str,
    lock_ttl_seconds: int = DEFAULT_LOCK_TTL_SECONDS,
) -> None:
    """Heartbeat: extend run_lock_until on a 'running' row."""
    db.execute(_HEARTBEAT_SQL, {"run_id": str(run_id), "ttl": lock_ttl_seconds})


def run_retrain(
    db: DatabaseAdapter,
    run_row: dict[str, Any],
    *,
    lock_ttl_seconds: int = DEFAULT_LOCK_TTL_SECONDS,
    model_type_arg: str = "logistic",
) -> int:
    """Shell out to scripts/retrain_image_triage.py for a claimed row.

    Returns the subprocess exit code. The script writes its own terminal
    status to model_training_runs via --run-id; if the subprocess exits
    non-zero AND the row is still 'running' (script crashed before the
    try/except in main() could write a status), this function flips it
    to 'failed' as a safety net.

    Subprocess inherits the worker's process group (no start_new_session)
    so SIGTERM to the worker cascades and the script dies cleanly rather
    than orphaning into PID 1.
    """
    run_id = str(run_row["id"])
    database_url = os.environ.get("DATABASE_URL", "")

    log_dir = _PROJECT_ROOT / "logs"
    log_dir.mkdir(exist_ok=True)
    log_path = log_dir / f"retrain_{run_id}.log"

    logger.info("run_retrain: starting run_id=%s (model_type=%s)", run_id, model_type_arg)
    poll_interval = max(1, min(30, lock_ttl_seconds // 3))

    with open(log_path, "ab") as log_fh:
        proc = subprocess.Popen(
            [
                sys.executable,
                str(_RETRAIN_SCRIPT),
                "--run-id",
                run_id,
                "--model-type",
                model_type_arg,
                "--database-url",
                database_url,
            ],
            stdout=log_fh,
            stderr=subprocess.STDOUT,
            cwd=str(_PROJECT_ROOT),
        )
        try:
            while proc.poll() is None:
                time.sleep(poll_interval)
                try:
                    extend_lock(db, run_id, lock_ttl_seconds)
                except Exception:  # noqa: BLE001
                    logger.exception("run_retrain: heartbeat failed for run_id=%s", run_id)
            rc = proc.returncode
        finally:
            if proc.poll() is None:
                proc.terminate()

    if rc != 0:
        # The script's own try/except should have written status='failed' on
        # any Python-level exception. A non-zero exit with status still
        # 'running' means the subprocess was killed (SIGKILL/OOM/SIGTERM) or
        # crashed before main()'s wrapper could record terminal status.
        db.execute(_FAIL_NO_STATUS_SQL, {"run_id": run_id})
        logger.warning(
            "run_retrain: run_id=%s exited rc=%d (any 'running' state forced to 'failed')",
            run_id,
            rc,
        )
    else:
        logger.info("run_retrain: run_id=%s completed (rc=0)", run_id)

    return rc
