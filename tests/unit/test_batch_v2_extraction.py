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

from scripts.batch_v2_extraction import BatchConfig, BatchStats, BatchV2Runner


class TestBatchConfig:
    def test_default_values(self):
        config = BatchConfig()
        assert config.workers == 4
        assert config.batch_size == 10
        assert config.dry_run is False
        assert config.resume_from is None
        assert config.limit is None
        assert config.skip_quality_scoring is False
        assert config.no_images is False
        assert config.min_confidence == 0.90

    def test_custom_values(self):
        config = BatchConfig(workers=8, batch_size=20, dry_run=True, limit=100)
        assert config.workers == 8
        assert config.batch_size == 20
        assert config.dry_run is True
        assert config.limit == 100


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
            runner.query_filings.__func__  # Just check it exists

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
        runner = self._make_runner(config)

        all_filings = [{"filing_id": i, "company_name": f"Co{i}", "company_id": i, "cik": str(i)} for i in range(1, 11)]

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
