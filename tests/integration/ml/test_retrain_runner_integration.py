"""Integration tests for src/ml/retrain_runner.py (gh-400).

Covers the queue-claim semantics that mirror src/universe/onboarding_runner.py:
  - Two claimers race; only one wins.
  - Active lock blocks claim.
  - Expired lock can be reclaimed (worker-died-mid-run recovery).
  - Oldest queued row is claimed first.
  - Heartbeat extends run_lock_until on a 'running' row.

Requires TEST_DATABASE_URL pointing at a live PostgreSQL instance with
sql/202605012350_add_queued_status_and_lock_to_model_training_runs.sql applied.
"""

from __future__ import annotations

from typing import Any

import pytest

from src.infra.db import DatabaseAdapter
from src.ml.retrain_runner import (
    claim_next_queued_retrain,
    extend_lock,
)

pytestmark = pytest.mark.integration


def _truncate_runs(db: DatabaseAdapter) -> None:
    db.execute("TRUNCATE TABLE model_training_runs CASCADE;")


@pytest.fixture
def clean_runs_db(clean_db: DatabaseAdapter) -> DatabaseAdapter:
    _truncate_runs(clean_db)
    yield clean_db
    _truncate_runs(clean_db)


def _insert_queued_run(
    db: DatabaseAdapter,
    *,
    triggered_by: str = "test_runner",
) -> str:
    """Insert a model_training_runs row in 'queued' state, return id (str)."""
    rows = db.query(
        """
        INSERT INTO model_training_runs (model_type, status, triggered_by)
        VALUES ('image_relevance', 'queued', %(triggered_by)s)
        RETURNING id::text;
        """,
        {"triggered_by": triggered_by},
    )
    return rows[0]["id"]


def _get_run(db: DatabaseAdapter, run_id: str) -> dict[str, Any] | None:
    rows = db.query(
        "SELECT id, status, run_lock_until, started_at FROM model_training_runs WHERE id = %s",
        [run_id],
    )
    return dict(rows[0]) if rows else None


class TestConcurrency:
    def test_only_one_claimer_wins(self, clean_runs_db: DatabaseAdapter) -> None:
        db = clean_runs_db
        _insert_queued_run(db)

        row1 = claim_next_queued_retrain(db)
        assert row1 is not None
        assert row1["status"] == "running"

        # Second claim returns None — first claim transitioned the row out of 'queued'.
        row2 = claim_next_queued_retrain(db)
        assert row2 is None

    def test_no_queued_rows_returns_none(self, clean_runs_db: DatabaseAdapter) -> None:
        assert claim_next_queued_retrain(clean_runs_db) is None


class TestLockSemantics:
    def test_expired_lock_can_be_reclaimed(self, clean_runs_db: DatabaseAdapter) -> None:
        """Worker-died-mid-run: lock expires, next claim wins."""
        db = clean_runs_db
        run_id = _insert_queued_run(db)

        # Claim once, then forcibly flip the row back to 'queued' with an
        # expired lock to simulate the recovery path (in real life: the row
        # would be 'running' with expired lock, picked up by claim_next_queued
        # via the OR expired-lock branch — but our claim only matches
        # status='queued'. The recovery path for retrain rows is covered by
        # the gh-392 stale-row sweep on the web side, which flips stuck
        # 'running' rows to 'failed' before a re-attempt). Here we verify
        # that an expired-lock 'queued' row IS claimable.
        db.execute(
            """
            UPDATE model_training_runs
               SET status = 'queued',
                   run_lock_until = NOW() - INTERVAL '1 minute'
             WHERE id = %s
            """,
            [run_id],
        )
        row = claim_next_queued_retrain(db)
        assert row is not None, "queued row with expired lock should be reclaimable"
        assert str(row["id"]) == run_id

    def test_active_lock_on_queued_blocks_claim(self, clean_runs_db: DatabaseAdapter) -> None:
        """A queued row with a future run_lock_until should not be claimed."""
        db = clean_runs_db
        run_id = _insert_queued_run(db)
        db.execute(
            """
            UPDATE model_training_runs
               SET run_lock_until = NOW() + INTERVAL '15 minutes'
             WHERE id = %s
            """,
            [run_id],
        )
        assert claim_next_queued_retrain(db) is None


class TestClaimOrdering:
    def test_oldest_queued_claimed_first(self, clean_runs_db: DatabaseAdapter) -> None:
        db = clean_runs_db
        # Insert two queued rows; backdate the first so it's clearly older.
        first = _insert_queued_run(db, triggered_by="first")
        db.execute(
            "UPDATE model_training_runs SET started_at = NOW() - INTERVAL '5 minutes' WHERE id = %s",
            [first],
        )
        _insert_queued_run(db, triggered_by="second")

        row = claim_next_queued_retrain(db)
        assert row is not None
        assert str(row["id"]) == first


class TestHeartbeat:
    def test_extend_lock_updates_run_lock_until(self, clean_runs_db: DatabaseAdapter) -> None:
        db = clean_runs_db
        _insert_queued_run(db)
        row = claim_next_queued_retrain(db)
        assert row is not None
        run_id = str(row["id"])

        before = _get_run(db, run_id)
        assert before is not None and before["run_lock_until"] is not None

        # Backdate the lock, then extend, and confirm the lock moved forward.
        db.execute(
            "UPDATE model_training_runs SET run_lock_until = NOW() + INTERVAL '5 seconds' WHERE id = %s",
            [run_id],
        )
        backdated = _get_run(db, run_id)
        assert backdated is not None

        extend_lock(db, run_id, lock_ttl_seconds=900)

        after = _get_run(db, run_id)
        assert after is not None
        assert after["run_lock_until"] > backdated["run_lock_until"]

    def test_extend_lock_only_affects_running_rows(self, clean_runs_db: DatabaseAdapter) -> None:
        """Heartbeat must not resurrect a row that has reached a terminal status."""
        db = clean_runs_db
        run_id = _insert_queued_run(db)
        # Move directly to 'failed' without going through 'running'.
        db.execute(
            "UPDATE model_training_runs SET status = 'failed', completed_at = NOW() WHERE id = %s",
            [run_id],
        )
        before = _get_run(db, run_id)
        assert before is not None
        before_lock = before["run_lock_until"]

        extend_lock(db, run_id, lock_ttl_seconds=900)

        after = _get_run(db, run_id)
        assert after is not None
        assert after["run_lock_until"] == before_lock, (
            "heartbeat must be a no-op on non-running rows"
        )
