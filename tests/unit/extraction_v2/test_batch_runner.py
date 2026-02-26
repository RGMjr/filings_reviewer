"""
Unit tests for scripts/batch_v2_extraction.py.

Covers BatchConfig, BatchStats computed properties, and BatchV2Runner
circuit-breaker logic using mocks (no database required).
"""

from __future__ import annotations

import importlib.util
import sys
import time
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
spec.loader.exec_module(batch_v2_extraction)  # type: ignore[union-attr]

BatchConfig = batch_v2_extraction.BatchConfig
BatchStats = batch_v2_extraction.BatchStats
BatchV2Runner = batch_v2_extraction.BatchV2Runner


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
        assert config.skip_quality_scoring is False
        assert config.no_images is False
        assert config.min_confidence == 0.90

    def test_custom_values(self) -> None:
        config = BatchConfig(
            workers=8,
            batch_size=25,
            dry_run=True,
            resume_from=42,
            limit=200,
            skip_quality_scoring=True,
            no_images=True,
            min_confidence=0.75,
        )

        assert config.workers == 8
        assert config.batch_size == 25
        assert config.dry_run is True
        assert config.resume_from == 42
        assert config.limit == 200
        assert config.skip_quality_scoring is True
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
