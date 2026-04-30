"""
Unit tests for scripts/batch_v2_extraction.py.

Covers BatchConfig, BatchStats computed properties, and BatchV2Runner
circuit-breaker logic, timeout handling, and transient retry using mocks
(no database required).
"""

from __future__ import annotations

import importlib.util
import os
import sys
import time
from concurrent.futures import TimeoutError as FuturesTimeoutError
from pathlib import Path
from unittest.mock import MagicMock, patch

# ---------------------------------------------------------------------------
# Import the batch script via importlib so we don't rely on it being
# installed as a package.  The script adds PROJECT_ROOT to sys.path itself,
# so the normal src.* imports inside it will resolve correctly once loaded.
# ---------------------------------------------------------------------------
_SCRIPTS_DIR = Path(__file__).parent.parent.parent.parent / "scripts"
_BATCH_SCRIPT = _SCRIPTS_DIR / "batch_v2_extraction.py"

spec = importlib.util.spec_from_file_location("batch_v2_extraction", _BATCH_SCRIPT)
assert spec is not None and spec.loader is not None, f"Could not locate {_BATCH_SCRIPT}"
batch_v2_extraction = importlib.util.module_from_spec(spec)
# Register module so patch() can find it by dotted name
sys.modules["batch_v2_extraction"] = batch_v2_extraction
# exec_module runs load_dotenv() inside the script which may set env vars (e.g.
# VISION_ROUTING_MODE) from a local .env file.  Save and restore so we don't
# contaminate later tests that assume a clean environment.
_prior_routing_mode = os.environ.get("VISION_ROUTING_MODE")
spec.loader.exec_module(batch_v2_extraction)  # type: ignore[union-attr]
if _prior_routing_mode is None:
    os.environ.pop("VISION_ROUTING_MODE", None)
else:
    os.environ["VISION_ROUTING_MODE"] = _prior_routing_mode

BatchConfig = batch_v2_extraction.BatchConfig
BatchStats = batch_v2_extraction.BatchStats
BatchV2Runner = batch_v2_extraction.BatchV2Runner

# Import exceptions for transient/fatal retry tests
from src.extraction_v2.exceptions import V2FatalError, V2TransientError  # noqa: E402

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_filings(n: int) -> list[dict]:
    """Build a list of minimal filing dicts."""
    return [
        {
            "filing_id": i,
            "company_name": f"Company{i}",
            "company_id": i,
            "cik": str(i),
            "html_storage_path": None,
            "accession_number": f"0001-{i:06d}",
        }
        for i in range(1, n + 1)
    ]


def _success_result(filing_id: int, fact_count: int = 5) -> dict:
    return {
        "filing_id": filing_id,
        "success": True,
        "fact_count": fact_count,
        "definition_count": 0,
        "error": None,
        "duration_ms": 100,
    }


def _failure_result(filing_id: int) -> dict:
    return {
        "filing_id": filing_id,
        "success": False,
        "fact_count": 0,
        "definition_count": 0,
        "error": "test error",
        "duration_ms": 50,
    }


# ---------------------------------------------------------------------------
# TestBatchConfig
# ---------------------------------------------------------------------------


class TestBatchConfig:
    """BatchConfig dataclass defaults and custom construction."""

    def test_defaults(self) -> None:
        config = BatchConfig()

        assert config.workers == 4
        assert config.batch_size == 10
        assert config.dry_run is False
        assert config.resume_from is None
        assert config.limit is None
        assert config.no_images is False
        assert config.min_confidence == 0.90
        assert config.worker_timeout == 300

    def test_custom_values(self) -> None:
        config = BatchConfig(
            workers=8,
            batch_size=25,
            dry_run=True,
            resume_from=42,
            limit=200,
            no_images=True,
            min_confidence=0.75,
        )

        assert config.workers == 8
        assert config.batch_size == 25
        assert config.dry_run is True
        assert config.resume_from == 42
        assert config.limit == 200
        assert config.no_images is True
        assert config.min_confidence == 0.75


# ---------------------------------------------------------------------------
# TestBatchStats
# ---------------------------------------------------------------------------


class TestBatchStats:
    """BatchStats computed properties: elapsed_seconds, rate_per_minute, eta_seconds."""

    def test_rate_per_minute_zero_elapsed(self) -> None:
        """When less than 1 second has elapsed, rate_per_minute must be 0.0 (no div-by-zero)."""
        stats = BatchStats()
        # start_time set to just now — elapsed will be < 1s
        stats.start_time = time.time()
        stats.processed = 100  # even with many processed, rate is 0 until 1s passes

        assert stats.rate_per_minute == 0.0

    def test_rate_per_minute_normal(self) -> None:
        """10 processed in ~60 s should yield ~10.0 filings/min."""
        stats = BatchStats()
        stats.start_time = time.time() - 60.0
        stats.processed = 10

        rate = stats.rate_per_minute
        # Allow ±2 filings/min tolerance for timing jitter
        assert 8.0 <= rate <= 12.0, f"Expected ~10.0, got {rate:.2f}"

    def test_eta_seconds_not_none_when_progress(self) -> None:
        """ETA should be a positive number when there are remaining filings and rate > 0."""
        stats = BatchStats(total_filings=100)
        stats.start_time = time.time() - 60.0
        stats.processed = 20  # 20/min rate, 80 remaining → ETA ~240 s

        eta = stats.eta_seconds
        assert eta is not None
        assert eta > 0

    def test_eta_seconds_none_when_zero_rate(self) -> None:
        """ETA is None when rate_per_minute == 0 (avoid division by zero)."""
        stats = BatchStats(total_filings=50)
        # elapsed < 1s → rate == 0.0
        stats.start_time = time.time()
        stats.processed = 0

        assert stats.eta_seconds is None

    def test_eta_seconds_none_when_complete(self) -> None:
        """ETA is None when processed >= total_filings (no remaining work)."""
        stats = BatchStats(total_filings=10)
        stats.start_time = time.time() - 60.0
        stats.processed = 10  # all done

        assert stats.eta_seconds is None


# ---------------------------------------------------------------------------
# TestBatchV2RunnerCircuitBreaker
# ---------------------------------------------------------------------------


class TestBatchV2RunnerCircuitBreaker:
    """Circuit-breaker logic inside BatchV2Runner.run()."""

    def _make_runner(self, workers: int = 1, batch_size: int = 20) -> BatchV2Runner:
        config = BatchConfig(workers=workers, batch_size=batch_size)
        return BatchV2Runner(config=config, db_url="postgresql://test/db")

    def _patch_executor(self, results_by_id: dict[int, dict]):
        """Return a context-manager stack that mocks ProcessPoolExecutor + as_completed."""

        def submit_side_effect(fn, filing_id, *args, **kwargs):
            future = MagicMock()
            future.result.return_value = results_by_id[filing_id]
            return future

        def as_completed_side_effect(futures):
            yield from futures.keys()

        mock_ppe_cls = MagicMock()
        mock_executor = MagicMock()
        mock_ppe_cls.return_value.__enter__ = MagicMock(return_value=mock_executor)
        mock_ppe_cls.return_value.__exit__ = MagicMock(return_value=False)
        mock_executor.submit.side_effect = submit_side_effect

        return mock_ppe_cls, as_completed_side_effect

    def test_circuit_breaker_triggers(self) -> None:
        """After max_consecutive_failures all-failure results, aborted_by_circuit_breaker is True."""
        runner = self._make_runner()
        filings = _make_filings(15)

        results_by_id = {f["filing_id"]: _failure_result(f["filing_id"]) for f in filings}
        mock_ppe_cls, as_completed_se = self._patch_executor(results_by_id)

        with patch.object(batch_v2_extraction, "ProcessPoolExecutor", mock_ppe_cls):
            with patch.object(batch_v2_extraction, "as_completed", side_effect=as_completed_se):
                with patch.object(runner, "_save_checkpoint"):
                    stats = runner.run(filings, max_consecutive_failures=3)

        assert stats.aborted_by_circuit_breaker is True
        assert stats.failed > 0
        # Should have stopped before processing all 15
        assert stats.processed <= 10

    def test_circuit_breaker_resets_on_success(self) -> None:
        """A single success resets the failure counter; run completes without aborting."""
        runner = self._make_runner()
        # Pattern: fail, fail, SUCCESS, fail, fail — threshold=3, never consecutive
        filings = _make_filings(5)

        results_by_id = {
            1: _failure_result(1),
            2: _failure_result(2),
            3: _success_result(3),
            4: _failure_result(4),
            5: _failure_result(5),
        }
        mock_ppe_cls, _ = self._patch_executor(results_by_id)

        # Force deterministic filing order so the interleave is predictable
        def as_completed_ordered(futures):
            sorted_futures = sorted(futures.keys(), key=lambda f: futures[f]["filing_id"])
            yield from sorted_futures

        with patch.object(batch_v2_extraction, "ProcessPoolExecutor", mock_ppe_cls):
            with patch.object(
                batch_v2_extraction, "as_completed", side_effect=as_completed_ordered
            ):
                with patch.object(runner, "_save_checkpoint"):
                    stats = runner.run(filings, max_consecutive_failures=3)

        assert stats.aborted_by_circuit_breaker is False
        assert stats.processed == 5


# ---------------------------------------------------------------------------
# TestBatchV2RunnerTimeout
# ---------------------------------------------------------------------------


class TestBatchV2RunnerTimeout:
    """Per-worker timeout: hung worker gets killed and filing is recorded as failure."""

    def _make_runner(self, worker_timeout: int = 5) -> BatchV2Runner:
        config = BatchConfig(workers=1, batch_size=20, worker_timeout=worker_timeout)
        return BatchV2Runner(config=config, db_url="postgresql://test/db")

    def test_timeout_records_failure(self) -> None:
        """When future.result() raises FuturesTimeoutError, the filing is recorded as failed."""
        runner = self._make_runner(worker_timeout=1)
        filings = _make_filings(1)

        # Build a future whose .result(timeout=...) raises FuturesTimeoutError
        mock_future = MagicMock()
        mock_future.result.side_effect = FuturesTimeoutError()

        mock_executor = MagicMock()
        mock_executor.submit.return_value = mock_future

        mock_ppe_cls = MagicMock()
        mock_ppe_cls.return_value.__enter__ = MagicMock(return_value=mock_executor)
        mock_ppe_cls.return_value.__exit__ = MagicMock(return_value=False)

        def as_completed_se(futures):
            yield from futures.keys()

        with patch.object(batch_v2_extraction, "ProcessPoolExecutor", mock_ppe_cls):
            with patch.object(batch_v2_extraction, "as_completed", side_effect=as_completed_se):
                with patch.object(runner, "_save_checkpoint"):
                    stats = runner.run(filings)

        assert stats.failed == 1
        assert stats.succeeded == 0
        # Confirm the hung future was cancelled
        mock_future.cancel.assert_called_once()
        # Per-filing result should note the timeout
        assert "timeout" in stats.filing_results[0]["error"]
        assert stats.filing_results[0]["success"] is False

    def test_timeout_result_not_retried(self) -> None:
        """Timeout failures are not retried (no transient retry for timeout)."""
        runner = self._make_runner(worker_timeout=1)
        filings = _make_filings(1)

        mock_future = MagicMock()
        mock_future.result.side_effect = FuturesTimeoutError()

        mock_executor = MagicMock()
        mock_executor.submit.return_value = mock_future

        mock_ppe_cls = MagicMock()
        mock_ppe_cls.return_value.__enter__ = MagicMock(return_value=mock_executor)
        mock_ppe_cls.return_value.__exit__ = MagicMock(return_value=False)

        def as_completed_se(futures):
            yield from futures.keys()

        with patch.object(batch_v2_extraction, "ProcessPoolExecutor", mock_ppe_cls):
            with patch.object(batch_v2_extraction, "as_completed", side_effect=as_completed_se):
                with patch.object(runner, "_save_checkpoint"):
                    runner.run(filings)

        # submit called exactly once (no retry)
        assert mock_executor.submit.call_count == 1


# ---------------------------------------------------------------------------
# TestBatchV2RunnerTransientRetry
# ---------------------------------------------------------------------------


class TestBatchV2RunnerTransientRetry:
    """Transient retry: V2TransientError triggers one retry; V2FatalError does not."""

    def _make_runner(self) -> BatchV2Runner:
        config = BatchConfig(workers=1, batch_size=20, worker_timeout=300)
        return BatchV2Runner(config=config, db_url="postgresql://test/db")

    def _build_executor_mock(self, first_exc: Exception | None, retry_result: dict | None):
        """
        Build a mock executor where the first submit raises first_exc and the
        second submit (retry) returns retry_result (or raises if retry_result is None).
        """
        call_count = {"n": 0}

        def submit_side_effect(fn, filing_id, *args, **kwargs):
            call_count["n"] += 1
            future = MagicMock()
            if call_count["n"] == 1 and first_exc is not None:
                future.result.side_effect = first_exc
            elif retry_result is not None:
                future.result.return_value = retry_result
            return future

        mock_executor = MagicMock()
        mock_executor.submit.side_effect = submit_side_effect
        return mock_executor, call_count

    def test_transient_error_triggers_retry(self) -> None:
        """V2TransientError on first attempt causes one retry; success on retry is counted."""
        runner = self._make_runner()
        filings = _make_filings(1)
        filing_id = filings[0]["filing_id"]

        transient_exc = V2TransientError("api timeout", stage_name="llm_enrichment")
        retry_ok = _success_result(filing_id, fact_count=3)
        retry_ok["retried"] = True

        mock_executor, call_count = self._build_executor_mock(transient_exc, retry_ok)

        mock_ppe_cls = MagicMock()
        mock_ppe_cls.return_value.__enter__ = MagicMock(return_value=mock_executor)
        mock_ppe_cls.return_value.__exit__ = MagicMock(return_value=False)

        def as_completed_se(futures):
            yield from futures.keys()

        with patch.object(batch_v2_extraction, "ProcessPoolExecutor", mock_ppe_cls):
            with patch.object(batch_v2_extraction, "as_completed", side_effect=as_completed_se):
                with patch.object(runner, "_save_checkpoint"):
                    stats = runner.run(filings)

        assert stats.succeeded == 1
        assert stats.failed == 0
        # submit called twice: initial + retry
        assert call_count["n"] == 2
        assert stats.filing_results[0]["retried"] is True

    def test_transient_error_no_second_retry(self) -> None:
        """A filing that already retried is not retried again (max 1 retry)."""
        runner = self._make_runner()
        filings = _make_filings(1)
        filing_id = filings[0]["filing_id"]

        # Both first and retry attempts raise transient error
        transient_exc = V2TransientError("api timeout", stage_name="llm_enrichment")
        retry_fail = {
            "filing_id": filing_id,
            "success": False,
            "fact_count": 0,
            "definition_count": 0,
            "error": "still transient",
            "duration_ms": 0,
            "retried": True,
        }

        mock_executor, call_count = self._build_executor_mock(transient_exc, retry_fail)

        mock_ppe_cls = MagicMock()
        mock_ppe_cls.return_value.__enter__ = MagicMock(return_value=mock_executor)
        mock_ppe_cls.return_value.__exit__ = MagicMock(return_value=False)

        def as_completed_se(futures):
            yield from futures.keys()

        with patch.object(batch_v2_extraction, "ProcessPoolExecutor", mock_ppe_cls):
            with patch.object(batch_v2_extraction, "as_completed", side_effect=as_completed_se):
                with patch.object(runner, "_save_checkpoint"):
                    stats = runner.run(filings)

        assert stats.failed == 1
        # submit called twice (initial + one retry), not three times
        assert call_count["n"] == 2

    def test_fatal_error_not_retried(self) -> None:
        """V2FatalError is NOT retried — submit called only once."""
        runner = self._make_runner()
        filings = _make_filings(1)

        fatal_exc = V2FatalError("parse failure", stage_name="html_segmentation")
        mock_executor, call_count = self._build_executor_mock(fatal_exc, retry_result=None)

        mock_ppe_cls = MagicMock()
        mock_ppe_cls.return_value.__enter__ = MagicMock(return_value=mock_executor)
        mock_ppe_cls.return_value.__exit__ = MagicMock(return_value=False)

        def as_completed_se(futures):
            yield from futures.keys()

        with patch.object(batch_v2_extraction, "ProcessPoolExecutor", mock_ppe_cls):
            with patch.object(batch_v2_extraction, "as_completed", side_effect=as_completed_se):
                with patch.object(runner, "_save_checkpoint"):
                    stats = runner.run(filings)

        assert stats.failed == 1
        assert stats.succeeded == 0
        # Fatal error — no retry
        assert call_count["n"] == 1
        assert stats.filing_results[0]["retried"] is False
