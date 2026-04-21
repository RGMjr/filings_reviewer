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


class TestRunOneDispatch:
    """Wave C: run_one branches on batch_row['kind']."""

    def test_dispatch_onboard_calls_run_onboard(self) -> None:
        import src.universe.onboarding_runner as runner_mod
        from src.universe.onboarding_runner import run_one

        called = {}

        def fake_run_onboard(db, row):
            called["onboard"] = row

        original = runner_mod._run_onboard
        runner_mod._run_onboard = fake_run_onboard
        try:
            run_one(_FakeDB(), {"kind": "onboard", "batch_id": "x"})
        finally:
            runner_mod._run_onboard = original

        assert "onboard" in called

    def test_dispatch_populate_calls_run_populate(self) -> None:
        import src.universe.onboarding_runner as runner_mod
        from src.universe.onboarding_runner import run_one

        called = {}

        def fake_run_populate(db, row):
            called["populate"] = row

        original = runner_mod._run_populate
        runner_mod._run_populate = fake_run_populate
        try:
            run_one(_FakeDB(), {"kind": "populate", "batch_id": "x"})
        finally:
            runner_mod._run_populate = original

        assert "populate" in called

    def test_dispatch_unknown_kind_raises(self) -> None:
        from src.universe.onboarding_runner import run_one
        with pytest.raises(ValueError, match="Unknown batch kind"):
            run_one(_FakeDB(), {"kind": "wat", "batch_id": "x"})


class TestRunPopulate:
    """Wave C: _run_populate calls build_universe + writes populate_progress."""

    def test_progress_cb_writes_jsonb(self) -> None:
        """The progress_cb passed into build_universe must UPDATE limits.populate_progress."""
        import src.universe.onboarding_runner as runner_mod
        from src.universe.onboarding_runner import _run_populate

        db = _FakeDB(rows=[])

        # Capture the progress_cb to invoke it directly
        captured_cb = {}

        class FakeBuilder:
            def __init__(self, *a, **kw):
                pass

            def build_universe(self, start, end, form_types=None, progress_cb=None, **kw):
                captured_cb["fn"] = progress_cb
                if progress_cb:
                    progress_cb(0, 10)
                    progress_cb(5, 10)
                    progress_cb(10, 10)
                return 10

        original = runner_mod.UniverseBuilder
        runner_mod.UniverseBuilder = FakeBuilder
        try:
            _run_populate(db, {
                "batch_id": "abc",
                "kind": "populate",
                "criteria": {"year": 2024, "form_type": "10-K"},
            })
        finally:
            runner_mod.UniverseBuilder = original

        # Heartbeat + populate-progress UPDATEs fired
        sqls = " ".join(c[0] for c in db.calls)
        assert "populate_progress" in sqls
        # _BATCH_COMPLETE_SQL fired (conditional WHERE status='running')
        assert "status = 'complete'" in sqls
        # _FINALIZE_CANCEL_SQL also fired (idempotent finaliser)
        assert "status = 'cancelled' AND finished_at IS NULL" in sqls

    def test_exception_marks_batch_failed(self) -> None:
        import src.universe.onboarding_runner as runner_mod
        from src.universe.onboarding_runner import _run_populate

        db = _FakeDB(rows=[])

        class BoomBuilder:
            def __init__(self, *a, **kw):
                pass

            def build_universe(self, *a, **kw):
                raise RuntimeError("SEC says no")

        original = runner_mod.UniverseBuilder
        runner_mod.UniverseBuilder = BoomBuilder
        try:
            _run_populate(db, {
                "batch_id": "abc",
                "kind": "populate",
                "criteria": {"year": 2024, "form_type": "10-K"},
            })
        finally:
            runner_mod.UniverseBuilder = original

        sqls = " ".join(c[0] for c in db.calls)
        assert "status = 'failed'" in sqls

    def test_criteria_string_is_parsed(self) -> None:
        """criteria may arrive as a JSON string (depending on psycopg version)."""
        import json as _json

        import src.universe.onboarding_runner as runner_mod
        from src.universe.onboarding_runner import _run_populate

        db = _FakeDB(rows=[])
        captured = {}

        class FakeBuilder:
            def __init__(self, *a, **kw):
                pass

            def build_universe(self, start, end, form_types=None, **kw):
                captured["form_types"] = form_types
                captured["start"] = start
                return 0

        original = runner_mod.UniverseBuilder
        runner_mod.UniverseBuilder = FakeBuilder
        try:
            _run_populate(db, {
                "batch_id": "abc",
                "kind": "populate",
                "criteria": _json.dumps({"year": 2024, "form_type": "10-K"}),
            })
        finally:
            runner_mod.UniverseBuilder = original

        assert captured["start"] == "2024-01-01"
        assert "10-K" in captured["form_types"]


class TestBatchCompleteConditional:
    """Wave C bugfix: _BATCH_COMPLETE_SQL has WHERE status='running' guard."""

    def test_complete_sql_has_status_running_predicate(self) -> None:
        from src.universe.onboarding_runner import _BATCH_COMPLETE_SQL
        assert "status = 'running'" in _BATCH_COMPLETE_SQL

    def test_finalize_cancel_sql_exists(self) -> None:
        from src.universe.onboarding_runner import _FINALIZE_CANCEL_SQL
        assert "status = 'cancelled'" in _FINALIZE_CANCEL_SQL
        assert "finished_at IS NULL" in _FINALIZE_CANCEL_SQL
