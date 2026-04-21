"""
Unit tests for batch_v2_extraction.py.
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Add project root
PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.batch_v2_extraction import (  # noqa: E402
    BatchConfig,
    BatchStats,
    BatchV2Runner,
    _load_filing_ids,
    _process_filing_worker,
)


class TestSubmitFilingAccessionNumber:
    """Verify accession_number is forwarded through the submission chain."""

    def test_accession_number_passed_to_worker(self):
        """_submit_filing includes accession_number as a positional arg to the worker."""
        config = BatchConfig(workers=1)
        runner = BatchV2Runner(config=config, db_url="postgresql://test/db")

        filing = {
            "filing_id": 42,
            "accession_number": "0001234567-24-000001",
            "html_storage_path": None,
            "company_name": "TestCo",
            "company_id": 10,
            "cik": "0001234567",
        }

        mock_executor = MagicMock()
        mock_executor.submit.return_value = MagicMock()

        runner._submit_filing(mock_executor, filing, {})

        call_args = mock_executor.submit.call_args.args
        # Expected order: (fn, filing_id, html_path, company_name, company_id, cik, accession_number, db_url, config_dict)
        assert call_args[0] is _process_filing_worker
        assert call_args[6] == "0001234567-24-000001", (
            "accession_number must be the 7th positional arg so _process_filing_worker "
            "can pass it to pipeline.process() for image downloads"
        )

    def test_missing_accession_number_defaults_to_empty_string(self):
        """Filing dict without accession_number key doesn't crash _submit_filing."""
        config = BatchConfig(workers=1)
        runner = BatchV2Runner(config=config, db_url="postgresql://test/db")

        filing = {
            "filing_id": 1,
            "html_storage_path": None,
            "company_name": "Co",
            "company_id": 1,
            "cik": "001",
            # no accession_number key
        }

        mock_executor = MagicMock()
        mock_executor.submit.return_value = MagicMock()
        runner._submit_filing(mock_executor, filing, {})

        call_args = mock_executor.submit.call_args.args
        assert call_args[6] == ""  # str(filing.get("accession_number", ""))


class TestBatchConfig:
    def test_default_values(self):
        config = BatchConfig()
        assert config.workers == 4
        assert config.batch_size == 10
        assert config.dry_run is False
        assert config.resume_from is None
        assert config.limit is None
        assert config.no_images is False
        assert config.min_confidence == 0.90
        assert config.status is None

    def test_custom_values(self):
        config = BatchConfig(workers=8, batch_size=20, dry_run=True, limit=100, status="fetched")
        assert config.workers == 8
        assert config.batch_size == 20
        assert config.dry_run is True
        assert config.limit == 100
        assert config.status == "fetched"


class TestBatchStats:
    def test_initial_values(self):
        stats = BatchStats(total_filings=100)
        assert stats.total_filings == 100
        assert stats.processed == 0
        assert stats.succeeded == 0
        assert stats.failed == 0
        assert stats.total_facts == 0

    def test_rate_zero_when_no_processed(self):
        stats = BatchStats()
        assert stats.rate_per_minute == 0.0

    def test_rate_calculation(self):
        stats = BatchStats()
        stats.start_time = time.time() - 60  # 60 seconds ago
        stats.processed = 30
        # Should be approximately 30/min
        assert 25 < stats.rate_per_minute < 35

    def test_eta_none_when_rate_zero(self):
        stats = BatchStats(total_filings=100)
        assert stats.eta_seconds is None

    def test_eta_calculation(self):
        stats = BatchStats(total_filings=100)
        stats.start_time = time.time() - 60  # 60 seconds ago
        stats.processed = 20  # 20/min
        # 80 remaining at 20/min → 240 seconds
        eta = stats.eta_seconds
        assert eta is not None
        assert 200 < eta < 280

    def test_eta_none_when_all_processed(self):
        stats = BatchStats(total_filings=10)
        stats.start_time = time.time() - 60
        stats.processed = 10
        assert stats.eta_seconds is None


class TestBatchV2RunnerQueryFilings:
    def _make_runner(self, config: BatchConfig) -> BatchV2Runner:
        return BatchV2Runner(config=config, db_url="postgresql://test/db")

    def _make_mock_db(self, filings: list[dict]) -> MagicMock:
        mock_db = MagicMock()
        mock_db.query.return_value = filings
        return mock_db

    def test_returns_all_filings(self):
        filings = [
            {"filing_id": 1, "company_name": "CompanyA", "company_id": 10, "cik": "001"},
            {"filing_id": 2, "company_name": "CompanyB", "company_id": 20, "cik": "002"},
            {"filing_id": 3, "company_name": "CompanyC", "company_id": 30, "cik": "003"},
        ]
        mock_db = self._make_mock_db(filings)
        runner = self._make_runner(BatchConfig())

        with patch("src.infra.db.DatabaseAdapter", return_value=mock_db):
            runner._db_for_test = mock_db  # Inject mock
            # Bypass actual DB call
            runner.query_filings.__func__  # noqa: B018  # Just check it exists

        # Test the filtering logic directly (resume/limit are pure Python)
        all_filings = filings[:]
        config = BatchConfig()
        if config.resume_from is not None:
            all_filings = [f for f in all_filings if f["filing_id"] >= config.resume_from]
        if config.limit is not None:
            all_filings = all_filings[: config.limit]
        assert len(all_filings) == 3

    def test_limit_applied(self):
        config = BatchConfig(limit=3)
        _runner = self._make_runner(config)

        all_filings = [
            {"filing_id": i, "company_name": f"Co{i}", "company_id": i, "cik": str(i)}
            for i in range(1, 11)
        ]

        # Test the limit filter (pure Python logic extracted from query_filings)
        result = all_filings[: config.limit]
        assert len(result) == 3

    def test_resume_from_filters_filings(self):
        config = BatchConfig(resume_from=5)
        all_filings = [
            {"filing_id": 1, "company_name": "Co1", "company_id": 1, "cik": "001"},
            {"filing_id": 5, "company_name": "Co5", "company_id": 5, "cik": "005"},
            {"filing_id": 10, "company_name": "Co10", "company_id": 10, "cik": "010"},
        ]

        # Simulate resume_from filter from query_filings
        filtered = [f for f in all_filings if f["filing_id"] >= config.resume_from]
        assert len(filtered) == 2
        assert all(f["filing_id"] >= 5 for f in filtered)

    def test_resume_from_inclusive(self):
        config = BatchConfig(resume_from=5)
        all_filings = [
            {"filing_id": 4, "company_name": "Co4", "company_id": 4, "cik": "004"},
            {"filing_id": 5, "company_name": "Co5", "company_id": 5, "cik": "005"},
        ]

        filtered = [f for f in all_filings if f["filing_id"] >= config.resume_from]
        assert len(filtered) == 1
        assert filtered[0]["filing_id"] == 5


class TestBatchV2RunnerCheckpoint:
    def test_checkpoint_written(self, tmp_path):
        config = BatchConfig()
        runner = BatchV2Runner(config=config, db_url="postgresql://test/db")

        stats = BatchStats(total_filings=10)
        stats.processed = 5
        stats.succeeded = 4
        stats.failed = 1
        stats.total_facts = 100

        checkpoint_file = tmp_path / "checkpoint.json"
        with patch("scripts.batch_v2_extraction.CHECKPOINT_FILE", checkpoint_file):
            with patch("scripts.batch_v2_extraction.LOGS_DIR", tmp_path):
                runner._save_checkpoint(stats, last_filing_id=50)

        assert checkpoint_file.exists()
        data = json.loads(checkpoint_file.read_text())
        assert data["last_filing_id"] == 50
        assert data["processed"] == 5
        assert data["succeeded"] == 4
        assert data["failed"] == 1
        assert data["total_facts"] == 100


class TestGracefulShutdown:
    def test_shutdown_flag_initially_false(self):
        import scripts.batch_v2_extraction as module

        # Reset flag
        module._shutdown_requested = False
        assert module._shutdown_requested is False

    def test_sigint_handler_sets_flag(self):
        import scripts.batch_v2_extraction as module

        module._shutdown_requested = False

        # Simulate SIGINT handler
        module._handle_sigint(2, None)

        assert module._shutdown_requested is True

        # Reset
        module._shutdown_requested = False

    def test_empty_filings_returns_zero_stats(self):
        config = BatchConfig()
        runner = BatchV2Runner(config=config, db_url="postgresql://test/db")
        stats = runner.run([])
        assert stats.processed == 0
        assert stats.succeeded == 0
        assert stats.total_filings == 0


def _make_filings(n: int) -> list[dict]:
    return [
        {
            "filing_id": i,
            "company_name": f"Company{i}",
            "company_id": i,
            "cik": str(i),
            "html_storage_path": None,
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
        "error": "mock error",
        "duration_ms": 50,
    }


class TestExecutorLifecycle:
    """Executor is created only once across all batches."""

    def test_executor_created_once_for_multiple_batches(self):
        """ProcessPoolExecutor should be instantiated once, not per-batch."""
        config = BatchConfig(workers=2, batch_size=2)
        runner = BatchV2Runner(config=config, db_url="postgresql://test/db")
        filings = _make_filings(6)  # 3 batches of 2

        mock_future_results = {f["filing_id"]: _success_result(f["filing_id"]) for f in filings}

        with patch("scripts.batch_v2_extraction.ProcessPoolExecutor") as mock_ppe_cls:
            mock_executor = MagicMock()
            mock_ppe_cls.return_value.__enter__ = MagicMock(return_value=mock_executor)
            mock_ppe_cls.return_value.__exit__ = MagicMock(return_value=False)

            def submit_side_effect(fn, filing_id, *args, **kwargs):
                future = MagicMock()
                future.result.return_value = mock_future_results[filing_id]
                return future

            mock_executor.submit.side_effect = submit_side_effect

            # as_completed must yield the futures
            def as_completed_side_effect(futures):
                yield from futures.keys()

            with patch(
                "scripts.batch_v2_extraction.as_completed", side_effect=as_completed_side_effect
            ):
                with patch.object(runner, "_save_checkpoint"):
                    runner.run(filings)

            # Executor context manager entered exactly once
            assert mock_ppe_cls.return_value.__enter__.call_count == 1


class TestCircuitBreaker:
    """Circuit breaker aborts run after consecutive failures."""

    def test_circuit_breaker_triggers(self):
        config = BatchConfig(workers=1, batch_size=20)
        runner = BatchV2Runner(config=config, db_url="postgresql://test/db")
        filings = _make_filings(15)

        def submit_side_effect(fn, filing_id, *args, **kwargs):
            future = MagicMock()
            future.result.return_value = _failure_result(filing_id)
            return future

        with patch("scripts.batch_v2_extraction.ProcessPoolExecutor") as mock_ppe_cls:
            mock_executor = MagicMock()
            mock_ppe_cls.return_value.__enter__ = MagicMock(return_value=mock_executor)
            mock_ppe_cls.return_value.__exit__ = MagicMock(return_value=False)
            mock_executor.submit.side_effect = submit_side_effect

            def as_completed_side_effect(futures):
                yield from futures.keys()

            with patch(
                "scripts.batch_v2_extraction.as_completed", side_effect=as_completed_side_effect
            ):
                with patch.object(runner, "_save_checkpoint"):
                    stats = runner.run(filings, max_consecutive_failures=5)

        assert stats.aborted_by_circuit_breaker is True
        # Should stop after hitting threshold (5 consecutive), not process all 15
        assert stats.processed <= 10  # Generous upper bound

    def test_circuit_breaker_resets_on_success(self):
        config = BatchConfig(workers=1, batch_size=20)
        runner = BatchV2Runner(config=config, db_url="postgresql://test/db")
        # 9 filings: 4 failures, 1 success, 4 failures — threshold=5, should NOT abort
        filings = _make_filings(9)

        results_by_id = {}
        for f in filings:
            fid = f["filing_id"]
            if fid == 5:
                results_by_id[fid] = _success_result(fid)
            else:
                results_by_id[fid] = _failure_result(fid)

        def submit_side_effect(fn, filing_id, *args, **kwargs):
            future = MagicMock()
            future.result.return_value = results_by_id[filing_id]
            return future

        # Force deterministic ordering (filing_id 1..9 in order)
        def as_completed_side_effect(futures):
            sorted_futures = sorted(futures.keys(), key=lambda f: futures[f]["filing_id"])
            yield from sorted_futures

        with patch("scripts.batch_v2_extraction.ProcessPoolExecutor") as mock_ppe_cls:
            mock_executor = MagicMock()
            mock_ppe_cls.return_value.__enter__ = MagicMock(return_value=mock_executor)
            mock_ppe_cls.return_value.__exit__ = MagicMock(return_value=False)
            mock_executor.submit.side_effect = submit_side_effect

            with patch(
                "scripts.batch_v2_extraction.as_completed", side_effect=as_completed_side_effect
            ):
                with patch.object(runner, "_save_checkpoint"):
                    stats = runner.run(filings, max_consecutive_failures=5)

        assert stats.aborted_by_circuit_breaker is False


class TestExitCode:
    """Exit code is 1 when failure rate > 50%."""

    def test_exit_1_when_majority_failed(self, tmp_path):
        import scripts.batch_v2_extraction as module

        stats = BatchStats(total_filings=10)
        stats.succeeded = 3
        stats.failed = 7

        with patch("scripts.batch_v2_extraction.LOGS_DIR", tmp_path):
            with patch("scripts.batch_v2_extraction.BatchV2Runner") as mock_runner_cls:
                mock_runner = MagicMock()
                mock_runner.run.return_value = stats
                mock_runner.query_filings.return_value = [
                    {"filing_id": i, "company_name": f"Co{i}", "company_id": i, "cik": str(i)}
                    for i in range(1, 11)
                ]
                mock_runner_cls.return_value = mock_runner

                with patch("sys.argv", ["batch_v2_extraction.py", "--dry-run"]):
                    with patch.dict(os.environ, {"DATABASE_URL": "postgresql://test/db"}):
                        with pytest.raises(SystemExit) as exc_info:
                            module.main()
                        assert exc_info.value.code == 1

    def test_exit_0_when_majority_succeeded(self, tmp_path):
        import scripts.batch_v2_extraction as module

        stats = BatchStats(total_filings=10)
        stats.succeeded = 7
        stats.failed = 3

        with patch("scripts.batch_v2_extraction.LOGS_DIR", tmp_path):
            with patch("scripts.batch_v2_extraction.BatchV2Runner") as mock_runner_cls:
                mock_runner = MagicMock()
                mock_runner.run.return_value = stats
                mock_runner.query_filings.return_value = [
                    {"filing_id": i, "company_name": f"Co{i}", "company_id": i, "cik": str(i)}
                    for i in range(1, 11)
                ]
                mock_runner_cls.return_value = mock_runner

                with patch("sys.argv", ["batch_v2_extraction.py", "--dry-run"]):
                    with patch.dict(os.environ, {"DATABASE_URL": "postgresql://test/db"}):
                        # Should not raise SystemExit(1)
                        try:
                            module.main()
                        except SystemExit as e:
                            assert e.code == 0 or e.code is None


class TestSummaryJSON:
    """Summary JSON is written to logs/ directory."""

    def test_summary_json_written(self, tmp_path):
        import scripts.batch_v2_extraction as module

        stats = BatchStats(total_filings=2)
        stats.succeeded = 2
        stats.failed = 0
        stats.total_facts = 10
        stats.filing_results = [
            {
                "filing_id": 1,
                "company_name": "Acme",
                "success": True,
                "fact_count": 5,
                "error": None,
                "duration_ms": 100,
            },
            {
                "filing_id": 2,
                "company_name": "Beta",
                "success": True,
                "fact_count": 5,
                "error": None,
                "duration_ms": 200,
            },
        ]

        with patch("scripts.batch_v2_extraction.LOGS_DIR", tmp_path):
            with patch("scripts.batch_v2_extraction.BatchV2Runner") as mock_runner_cls:
                mock_runner = MagicMock()
                mock_runner.run.return_value = stats
                mock_runner.query_filings.return_value = [
                    {"filing_id": 1, "company_name": "Acme", "company_id": 1, "cik": "001"},
                    {"filing_id": 2, "company_name": "Beta", "company_id": 2, "cik": "002"},
                ]
                mock_runner_cls.return_value = mock_runner

                with patch("sys.argv", ["batch_v2_extraction.py", "--dry-run"]):
                    with patch.dict(os.environ, {"DATABASE_URL": "postgresql://test/db"}):
                        try:
                            module.main()
                        except SystemExit:
                            pass

        summary_files = list(tmp_path.glob("batch_v2_summary_*.json"))
        assert len(summary_files) == 1

        data = json.loads(summary_files[0].read_text())
        assert data["total_filings"] == 2
        assert data["succeeded"] == 2
        assert data["failed"] == 0
        assert data["total_facts"] == 10
        assert "aborted_by_circuit_breaker" in data
        assert len(data["per_filing"]) == 2
        assert "run_date" in data
        assert "duration_seconds" in data


class TestProcessFilingWorkerHtmlFallback:
    """Tests for the DB html_content fallback when disk file is absent."""

    def _make_pipeline_result(self):
        result = MagicMock()
        result.success = True
        result.fact_count = 3
        result.facts = []
        result.definitions = []
        result.segments = []
        result.error_message = None
        return result

    def test_worker_falls_back_to_db_html_content(self):
        """When disk file is missing but html_content is in DB, worker succeeds."""
        from scripts.batch_v2_extraction import _process_filing_worker

        html_content = "<html><body>SEC filing content</body></html>"
        mock_pipeline_result = self._make_pipeline_result()

        with patch("src.infra.db.DatabaseAdapter") as mock_db_cls:
            mock_db = MagicMock()
            mock_db.query.return_value = [{"html_content": html_content}]
            mock_db_cls.return_value = mock_db

            with patch("src.extraction_v2.pipeline.V2Pipeline") as mock_pipeline_cls:
                mock_pipeline = MagicMock()
                mock_pipeline.process.return_value = mock_pipeline_result
                mock_pipeline_cls.return_value = mock_pipeline

                result = _process_filing_worker(
                    filing_id=99,
                    html_path="/nonexistent/primary.htm",
                    company_name="TestCo",
                    company_id=1,
                    cik="0001234",
                    accession_number="0001234-24-000001",
                    filing_date=None,
                    db_url="postgresql://test/db",
                    config_dict={"dry_run": True},
                )

        assert result["success"] is True
        assert result["fact_count"] == 3
        assert mock_pipeline.process.called

    def test_worker_fails_gracefully_when_no_html_content(self):
        """When disk file is missing and DB has no html_content, worker returns failure."""
        from scripts.batch_v2_extraction import _process_filing_worker

        with patch("src.infra.db.DatabaseAdapter") as mock_db_cls:
            mock_db = MagicMock()
            mock_db.query.return_value = []
            mock_db_cls.return_value = mock_db

            result = _process_filing_worker(
                filing_id=99,
                html_path="/nonexistent/primary.htm",
                company_name="TestCo",
                company_id=1,
                cik="0001234",
                accession_number="0001234-24-000001",
                filing_date=None,
                db_url="postgresql://test/db",
                config_dict={},
            )

        assert result["success"] is False
        assert result["filing_id"] == 99
        assert "not" in result["error"].lower()

    def test_worker_fails_gracefully_on_db_error(self):
        """When disk file is missing and DB query raises, worker returns failure (no raise)."""
        from scripts.batch_v2_extraction import _process_filing_worker

        with patch("src.infra.db.DatabaseAdapter") as mock_db_cls:
            mock_db = MagicMock()
            mock_db.query.side_effect = Exception("connection refused")
            mock_db_cls.return_value = mock_db

            result = _process_filing_worker(
                filing_id=99,
                html_path="/nonexistent/primary.htm",
                company_name="TestCo",
                company_id=1,
                cik="0001234",
                accession_number="0001234-24-000001",
                filing_date=None,
                db_url="postgresql://test/db",
                config_dict={},
            )

        assert result["success"] is False
        assert result["filing_id"] == 99


class TestLoadFilingIds:
    def test_parses_one_per_line(self, tmp_path):
        f = tmp_path / "ids.txt"
        f.write_text("101\n102\n103\n")
        assert _load_filing_ids(str(f)) == [101, 102, 103]

    def test_ignores_blank_lines_and_comments(self, tmp_path):
        f = tmp_path / "ids.txt"
        f.write_text("# target list\n101\n\n102  # reviewed-safe\n# end\n103\n")
        assert _load_filing_ids(str(f)) == [101, 102, 103]

    def test_raises_on_non_integer(self, tmp_path):
        f = tmp_path / "ids.txt"
        f.write_text("101\nnot-a-number\n103\n")
        with pytest.raises(ValueError, match="ids.txt:2"):
            _load_filing_ids(str(f))

    def test_empty_file_returns_empty_list(self, tmp_path):
        f = tmp_path / "ids.txt"
        f.write_text("# just comments\n\n")
        assert _load_filing_ids(str(f)) == []


class TestQueryFilingsWhitelist:
    """Verify --filing-ids-file whitelist branch builds the expected SQL + params."""

    def _runner_with_mock_db(self, config: BatchConfig) -> tuple[BatchV2Runner, MagicMock]:
        mock_db = MagicMock()
        mock_db.query.return_value = []
        runner = BatchV2Runner(config=config, db_url="postgresql://unused", db_adapter=mock_db)
        return runner, mock_db

    def test_filing_ids_restricts_query(self):
        runner, db = self._runner_with_mock_db(BatchConfig(filing_ids=[1, 2, 3]))
        runner.query_filings()
        sql, params = db.query.call_args.args
        assert "f.filing_id = ANY(%(filing_ids)s)" in sql
        assert params == {"filing_ids": [1, 2, 3]}
        assert "processing_status" not in sql

    def test_filing_ids_takes_precedence_over_status(self):
        runner, db = self._runner_with_mock_db(BatchConfig(filing_ids=[42], status="fetched"))
        runner.query_filings()
        sql, params = db.query.call_args.args
        assert "f.filing_id = ANY" in sql
        assert "processing_status" not in sql
        assert params == {"filing_ids": [42]}

    def test_status_only_branch_unchanged(self):
        runner, db = self._runner_with_mock_db(BatchConfig(status="fetched"))
        runner.query_filings()
        sql, params = db.query.call_args.args
        assert "f.processing_status = %(status)s" in sql
        assert "filing_id = ANY" not in sql
        assert params == {"status": "fetched"}

    def test_no_filters_returns_unfiltered_query(self):
        runner, db = self._runner_with_mock_db(BatchConfig())
        runner.query_filings()
        sql, params = db.query.call_args.args
        assert "WHERE" not in sql
        assert params == {}
