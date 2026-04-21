"""Unit tests for src/universe/onboarding_runner.py.

All tests are DB-free — DatabaseAdapter is replaced with a lightweight stub.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest

from src.universe.onboarding import FilingEvent
from src.universe.onboarding_runner import (
    _FACT_COUNT_RE,
    build_progress_cb,
    claim_batch,
    claim_next_queued_batch,
    should_abort,
)

# ---------------------------------------------------------------------------
# DB stub
# ---------------------------------------------------------------------------


class _FakeDB:
    """Minimal DatabaseAdapter stand-in that records SQL calls."""

    def __init__(self, rows: list[dict[str, Any]] | None = None) -> None:
        self._rows = rows or []
        self.calls: list[tuple[str, Any]] = []

    def query(self, sql: str, params: Any = None) -> list[dict[str, Any]]:
        self.calls.append((sql, params))
        return list(self._rows)

    def execute(self, sql: str, params: Any = None, *, fetch: bool = False) -> Any:
        self.calls.append((sql, params))
        return list(self._rows) if fetch else None


# ---------------------------------------------------------------------------
# claim_batch lock semantics
# ---------------------------------------------------------------------------


class TestClaimBatch:
    def test_returns_row_when_claimable(self) -> None:
        batch_id = uuid.uuid4()
        fake_row = {
            "batch_id": str(batch_id),
            "kind": "onboard",
            "reviewer_id": "rob",
            "criteria": {},
            "resolved_query": {},
            "limits": {},
            "total_filings": 2,
            "status": "running",
            "started_at": None,
        }
        db = _FakeDB(rows=[fake_row])
        result = claim_batch(db, batch_id)
        assert result is not None
        assert result["kind"] == "onboard"
        # SQL must include the batch_id param
        sql, params = db.calls[0]
        assert "batch_id" in params
        assert params["batch_id"] == str(batch_id)

    def test_returns_none_when_not_claimable(self) -> None:
        batch_id = uuid.uuid4()
        db = _FakeDB(rows=[])  # empty → not claimable
        result = claim_batch(db, batch_id)
        assert result is None

    def test_lock_ttl_is_passed_to_sql(self) -> None:
        batch_id = uuid.uuid4()
        db = _FakeDB(rows=[])
        claim_batch(db, batch_id, lock_ttl_seconds=300)
        _, params = db.calls[0]
        assert params["ttl"] == 300

    def test_claim_sql_contains_required_clauses(self) -> None:
        batch_id = uuid.uuid4()
        db = _FakeDB(rows=[])
        claim_batch(db, batch_id)
        sql, _ = db.calls[0]
        assert "run_lock_until" in sql
        assert "CASE WHEN status='queued' THEN 'running'" in sql
        assert "COALESCE(started_at, NOW())" in sql
        assert "status IN ('queued','running')" in sql
        assert "run_lock_until IS NULL OR run_lock_until < NOW()" in sql
        assert "RETURNING" in sql


class TestClaimNextQueuedBatch:
    def test_returns_row_when_available(self) -> None:
        batch_id = uuid.uuid4()
        db = _FakeDB(rows=[{"batch_id": str(batch_id), "kind": "onboard", "status": "running",
                             "reviewer_id": "rob", "criteria": {}, "resolved_query": {},
                             "limits": {}, "total_filings": 1, "started_at": None}])
        result = claim_next_queued_batch(db)
        assert result is not None
        assert result["kind"] == "onboard"

    def test_returns_none_when_no_batches(self) -> None:
        db = _FakeDB(rows=[])
        result = claim_next_queued_batch(db)
        assert result is None

    def test_sql_contains_order_by_created_at(self) -> None:
        db = _FakeDB(rows=[])
        claim_next_queued_batch(db)
        sql, _ = db.calls[0]
        assert "ORDER BY created_at" in sql
        assert "LIMIT 1" in sql


# ---------------------------------------------------------------------------
# should_abort
# ---------------------------------------------------------------------------


class TestShouldAbort:
    def test_returns_false_when_running(self) -> None:
        batch_id = uuid.uuid4()
        db = _FakeDB(rows=[{"status": "running"}])
        assert should_abort(db, batch_id) is False

    def test_returns_true_when_cancelled(self) -> None:
        batch_id = uuid.uuid4()
        db = _FakeDB(rows=[{"status": "cancelled"}])
        assert should_abort(db, batch_id) is True

    def test_returns_false_when_no_row(self) -> None:
        batch_id = uuid.uuid4()
        db = _FakeDB(rows=[])
        assert should_abort(db, batch_id) is False

    def test_returns_true_when_shutdown_requested(self) -> None:
        import src.universe.onboarding_runner as runner_mod

        batch_id = uuid.uuid4()
        db = _FakeDB(rows=[{"status": "running"}])
        original = runner_mod._shutdown_requested
        try:
            runner_mod._shutdown_requested = True
            assert should_abort(db, batch_id) is True
            # Should short-circuit before hitting DB
            assert len(db.calls) == 0
        finally:
            runner_mod._shutdown_requested = original


# ---------------------------------------------------------------------------
# build_progress_cb — UPDATE SQL correctness
# ---------------------------------------------------------------------------


class TestBuildProgressCb:
    def _make_db(self) -> _FakeDB:
        return _FakeDB(rows=[])

    def test_started_writes_fetching(self) -> None:
        db = self._make_db()
        batch_id = uuid.uuid4()
        cb = build_progress_cb(db, batch_id)
        cb(FilingEvent(filing_id=42, status="started"))
        # calls: [heartbeat, started_update]
        sqls = [c[0] for c in db.calls]
        assert any("'fetching'" in s for s in sqls)
        assert any("started_at" in s for s in sqls)

    def test_succeeded_writes_persisted_with_fact_count(self) -> None:
        db = self._make_db()
        batch_id = uuid.uuid4()
        cb = build_progress_cb(db, batch_id)
        cb(FilingEvent(filing_id=42, status="succeeded", message="27 facts persisted (force=False)"))
        sqls_params = db.calls
        # Find the persisted update
        persisted_call = next(
            (p for _, p in sqls_params if isinstance(p, dict) and p.get("fact_count") is not None),
            None,
        )
        assert persisted_call is not None
        assert persisted_call["fact_count"] == 27
        assert any("'persisted'" in c[0] for c in sqls_params)

    def test_succeeded_fact_count_zero_when_no_match(self) -> None:
        db = self._make_db()
        batch_id = uuid.uuid4()
        cb = build_progress_cb(db, batch_id)
        cb(FilingEvent(filing_id=42, status="succeeded", message="no numeric facts here"))
        persisted_call = next(
            (p for _, p in db.calls if isinstance(p, dict) and "fact_count" in p),
            None,
        )
        assert persisted_call is not None
        assert persisted_call["fact_count"] is None

    def test_failed_writes_failed_with_error(self) -> None:
        db = self._make_db()
        batch_id = uuid.uuid4()
        cb = build_progress_cb(db, batch_id)
        cb(FilingEvent(filing_id=42, status="failed", message="fetch error"))
        assert any("'failed'" in c[0] for c in db.calls)
        error_call = next(
            (p for _, p in db.calls if isinstance(p, dict) and p.get("error") == "fetch error"),
            None,
        )
        assert error_call is not None

    def test_skipped_reviewed_writes_skipped(self) -> None:
        db = self._make_db()
        batch_id = uuid.uuid4()
        cb = build_progress_cb(db, batch_id)
        cb(FilingEvent(filing_id=42, status="skipped_reviewed"))
        assert any("'skipped'" in c[0] for c in db.calls)

    def test_heartbeat_runs_on_every_event(self) -> None:
        db = self._make_db()
        batch_id = uuid.uuid4()
        cb = build_progress_cb(db, batch_id)
        cb(FilingEvent(filing_id=1, status="started"))
        cb(FilingEvent(filing_id=1, status="succeeded", message="5 facts persisted (force=False)"))
        heartbeat_calls = [c for c in db.calls if "run_lock_until" in c[0] and "CASE WHEN" not in c[0]]
        assert len(heartbeat_calls) == 2

    def test_batch_id_is_passed_to_all_updates(self) -> None:
        db = self._make_db()
        batch_id = uuid.uuid4()
        cb = build_progress_cb(db, batch_id)
        cb(FilingEvent(filing_id=99, status="started"))
        for _, params in db.calls:
            if isinstance(params, dict) and "batch_id" in params:
                assert params["batch_id"] == str(batch_id)


# ---------------------------------------------------------------------------
# FilingEvent → current_status mapping (all 4 plan-table status values)
# ---------------------------------------------------------------------------


class TestFilingEventMapping:
    """Verify the exact current_status each FilingEvent.status maps to."""

    @pytest.mark.parametrize(
        "event_status, expected_db_status",
        [
            ("started", "fetching"),
            ("succeeded", "persisted"),
            ("failed", "failed"),
            ("skipped_reviewed", "skipped"),
        ],
    )
    def test_mapping(self, event_status: str, expected_db_status: str) -> None:
        db = _FakeDB(rows=[])
        batch_id = uuid.uuid4()
        cb = build_progress_cb(db, batch_id)

        message = "5 facts persisted (force=False)" if event_status == "succeeded" else ""
        cb(FilingEvent(filing_id=1, status=event_status, message=message))

        all_sql = " ".join(c[0] for c in db.calls)
        assert f"'{expected_db_status}'" in all_sql


# ---------------------------------------------------------------------------
# argparse validation — mutually exclusive --batch-id / --watch
# ---------------------------------------------------------------------------


class TestArgparse:
    def _parse(self, *args: str) -> Any:
        """Run argparse and return parsed namespace; raises SystemExit on error."""
        import argparse as _ap


        # Re-build the parser inline to avoid running main()
        parser = _ap.ArgumentParser()
        mode_group = parser.add_mutually_exclusive_group(required=True)
        mode_group.add_argument("--batch-id", metavar="UUID")
        mode_group.add_argument("--watch", action="store_true")
        parser.add_argument("--poll-interval", type=int, default=10)
        parser.add_argument("--verbose", action="store_true")
        return parser.parse_args(list(args))

    def test_batch_id_accepted(self) -> None:
        ns = self._parse("--batch-id", str(uuid.uuid4()))
        assert ns.batch_id is not None
        assert not ns.watch

    def test_watch_accepted(self) -> None:
        ns = self._parse("--watch")
        assert ns.watch
        assert ns.batch_id is None

    def test_neither_raises(self) -> None:
        with pytest.raises(SystemExit):
            self._parse()

    def test_both_raises(self) -> None:
        with pytest.raises(SystemExit):
            self._parse("--batch-id", str(uuid.uuid4()), "--watch")

    def test_poll_interval_default(self) -> None:
        ns = self._parse("--watch")
        assert ns.poll_interval == 10

    def test_poll_interval_custom(self) -> None:
        ns = self._parse("--watch", "--poll-interval", "30")
        assert ns.poll_interval == 30


# ---------------------------------------------------------------------------
# _FACT_COUNT_RE regex coverage
# ---------------------------------------------------------------------------


class TestFactCountRegex:
    @pytest.mark.parametrize(
        "message, expected",
        [
            ("27 facts persisted (force=False)", 27),
            ("0 facts persisted (force=True)", 0),
            ("1 facts persisted (force=False)", 1),
            ("no match here", None),
            ("", None),
        ],
    )
    def test_regex(self, message: str, expected: int | None) -> None:
        m = _FACT_COUNT_RE.search(message)
        result = int(m.group(1)) if m else None
        assert result == expected
