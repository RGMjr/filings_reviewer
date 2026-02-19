"""
Unit tests for B3 candidate generation script.

Tests helper functions, argument parsing, and query building.
"""

import sys
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

# Add scripts to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent / "scripts"))

from generate_review_candidates import (
    get_filings_by_ids,
    get_filings_needing_candidates,
    parse_filing_ids,
    process_filings,
    report_summary,
)


class TestParseFilingIds:
    """Tests for parse_filing_ids()."""

    def test_parse_single_id(self):
        """Test parsing a single filing ID."""
        result = parse_filing_ids("123")
        assert result == [123]

    def test_parse_multiple_ids(self):
        """Test parsing multiple filing IDs."""
        result = parse_filing_ids("123,456,789")
        assert result == [123, 456, 789]

    def test_parse_with_spaces(self):
        """Test parsing IDs with whitespace."""
        result = parse_filing_ids(" 123 , 456 , 789 ")
        assert result == [123, 456, 789]

    def test_parse_empty_string(self):
        """Test parsing empty string returns empty list."""
        result = parse_filing_ids("")
        assert result == []

    def test_parse_whitespace_only(self):
        """Test parsing whitespace-only string returns empty list."""
        result = parse_filing_ids("   ")
        assert result == []

    def test_parse_invalid_format(self):
        """Test parsing invalid format raises ValueError."""
        with pytest.raises(ValueError, match="Invalid filing ID format"):
            parse_filing_ids("abc,123")

    def test_parse_negative_ids(self):
        """Test parsing negative IDs (valid integers)."""
        result = parse_filing_ids("-123,-456")
        assert result == [-123, -456]

    def test_parse_mixed_invalid(self):
        """Test parsing mixed valid/invalid raises ValueError."""
        with pytest.raises(ValueError, match="Invalid filing ID format"):
            parse_filing_ids("123,abc,456")


class TestGetFilingsByIds:
    """Tests for get_filings_by_ids()."""

    def test_query_single_filing(self):
        """Test querying a single filing by ID."""
        mock_db = Mock()
        mock_db.query.return_value = [
            {
                "filing_id": 123,
                "company_id": 1,
                "company_name": "Test Company",
                "accession_number": "0001234567-23-000001",
                "filing_date": "2023-06-15",
                "segment_count": 100,
            }
        ]

        result = get_filings_by_ids(mock_db, [123])

        assert len(result) == 1
        assert result[0]["filing_id"] == 123
        mock_db.query.assert_called_once()
        # Verify the query uses ANY() for array parameter
        call_args = mock_db.query.call_args
        assert "ANY(%(filing_ids)s)" in call_args[0][0]
        assert call_args[0][1]["filing_ids"] == [123]

    def test_query_multiple_filings(self):
        """Test querying multiple filings by ID."""
        mock_db = Mock()
        mock_db.query.return_value = [
            {"filing_id": 123, "company_name": "Company 1"},
            {"filing_id": 456, "company_name": "Company 2"},
        ]

        result = get_filings_by_ids(mock_db, [123, 456])

        assert len(result) == 2
        call_args = mock_db.query.call_args
        assert call_args[0][1]["filing_ids"] == [123, 456]

    def test_query_empty_list(self):
        """Test querying with empty filing ID list."""
        mock_db = Mock()
        mock_db.query.return_value = []

        result = get_filings_by_ids(mock_db, [])

        assert result == []
        mock_db.query.assert_called_once()


class TestGetFilingsNeedingCandidates:
    """Tests for get_filings_needing_candidates()."""

    def test_query_with_limit(self):
        """Test querying filings with limit."""
        mock_db = Mock()
        mock_db.query.return_value = [
            {"filing_id": 123, "company_name": "Company 1"},
            {"filing_id": 456, "company_name": "Company 2"},
        ]

        result = get_filings_needing_candidates(mock_db, 10)

        assert len(result) == 2
        mock_db.query.assert_called_once()
        call_args = mock_db.query.call_args
        assert call_args[0][1]["limit"] == 10

    def test_query_checks_no_existing_candidates(self):
        """Test query filters filings without candidates."""
        mock_db = Mock()
        mock_db.query.return_value = []

        get_filings_needing_candidates(mock_db, 5)

        call_args = mock_db.query.call_args
        query = call_args[0][0]
        # Verify query checks for NULL candidates
        assert "rc.candidate_id IS NULL" in query

    def test_query_checks_has_segments(self):
        """Test query filters filings with segments."""
        mock_db = Mock()
        mock_db.query.return_value = []

        get_filings_needing_candidates(mock_db, 5)

        call_args = mock_db.query.call_args
        query = call_args[0][0]
        # Verify query checks for segments
        assert "source_segments" in query
        assert "HAVING COUNT(DISTINCT s.source_segment_id) > 0" in query

    def test_query_orders_by_date_desc(self):
        """Test query orders by filing_date DESC."""
        mock_db = Mock()
        mock_db.query.return_value = []

        get_filings_needing_candidates(mock_db, 5)

        call_args = mock_db.query.call_args
        query = call_args[0][0]
        # Verify query orders by date descending
        assert "ORDER BY f.filing_date DESC" in query


class TestProcessFilings:
    """Tests for process_filings()."""

    @patch("generate_review_candidates.generate_candidates_for_filing")
    @patch("generate_review_candidates.logger")
    def test_process_single_filing_success(self, mock_logger, mock_generate):
        """Test processing a single filing successfully."""
        mock_db = Mock()
        mock_generate.return_value = [Mock(), Mock(), Mock()]  # 3 candidates

        filings = [
            {
                "filing_id": 123,
                "company_name": "Test Company",
                "accession_number": "0001234567-23-000001",
                "filing_date": "2023-06-15",
                "segment_count": 100,
            }
        ]

        stats = process_filings(mock_db, filings, dry_run=False, batch_id=None, show_progress=False)

        assert stats["filings_processed"] == 1
        assert stats["filings_failed"] == 0
        assert stats["total_candidates"] == 3
        assert stats["total_segments"] == 100

        mock_generate.assert_called_once_with(
            db=mock_db,
            filing_id=123,
            save=True,
            batch_id=None,
        )

    @patch("generate_review_candidates.generate_candidates_for_filing")
    @patch("generate_review_candidates.logger")
    def test_process_with_dry_run(self, mock_logger, mock_generate):
        """Test processing with dry_run=True doesn't save."""
        mock_db = Mock()
        mock_generate.return_value = [Mock()]

        filings = [
            {
                "filing_id": 123,
                "company_name": "Test",
                "accession_number": "0001234567-23-000001",
                "filing_date": "2023-06-15",
                "segment_count": 50,
            }
        ]

        process_filings(mock_db, filings, dry_run=True, show_progress=False)

        # Verify save=False was passed
        mock_generate.assert_called_once()
        call_kwargs = mock_generate.call_args[1]
        assert call_kwargs["save"] is False

    @patch("generate_review_candidates.generate_candidates_for_filing")
    @patch("generate_review_candidates.logger")
    def test_process_with_batch_id(self, mock_logger, mock_generate):
        """Test processing with batch_id assigns it correctly."""
        mock_db = Mock()
        mock_generate.return_value = [Mock()]

        filings = [
            {
                "filing_id": 123,
                "company_name": "Test",
                "accession_number": "0001234567-23-000001",
                "filing_date": "2023-06-15",
                "segment_count": 50,
            }
        ]

        process_filings(mock_db, filings, batch_id=42, show_progress=False)

        # Verify batch_id was passed
        call_kwargs = mock_generate.call_args[1]
        assert call_kwargs["batch_id"] == 42

    @patch("generate_review_candidates.generate_candidates_for_filing")
    @patch("generate_review_candidates.logger")
    def test_process_multiple_filings(self, mock_logger, mock_generate):
        """Test processing multiple filings."""
        mock_db = Mock()
        mock_generate.side_effect = [
            [Mock(), Mock()],  # Filing 1: 2 candidates
            [Mock(), Mock(), Mock()],  # Filing 2: 3 candidates
        ]

        filings = [
            {
                "filing_id": 123,
                "company_name": "Company 1",
                "accession_number": "0001234567-23-000001",
                "filing_date": "2023-06-15",
                "segment_count": 50,
            },
            {
                "filing_id": 456,
                "company_name": "Company 2",
                "accession_number": "0001234567-23-000002",
                "filing_date": "2023-07-20",
                "segment_count": 75,
            },
        ]

        stats = process_filings(mock_db, filings, show_progress=False)

        assert stats["filings_processed"] == 2
        assert stats["filings_failed"] == 0
        assert stats["total_candidates"] == 5
        assert stats["total_segments"] == 125

    @patch("generate_review_candidates.generate_candidates_for_filing")
    @patch("generate_review_candidates.logger")
    def test_process_continues_on_error(self, mock_logger, mock_generate):
        """Test processing continues when one filing fails."""
        mock_db = Mock()
        mock_generate.side_effect = [
            Exception("Database error"),  # Filing 1 fails
            [Mock(), Mock()],  # Filing 2 succeeds
        ]

        filings = [
            {
                "filing_id": 123,
                "company_name": "Bad Filing",
                "accession_number": "0001234567-23-000001",
                "filing_date": "2023-06-15",
                "segment_count": 50,
            },
            {
                "filing_id": 456,
                "company_name": "Good Filing",
                "accession_number": "0001234567-23-000002",
                "filing_date": "2023-07-20",
                "segment_count": 75,
            },
        ]

        stats = process_filings(mock_db, filings, show_progress=False)

        # Verify second filing was processed despite first failing
        assert stats["filings_processed"] == 1
        assert stats["filings_failed"] == 1
        assert stats["total_candidates"] == 2

        # Verify error was logged
        assert mock_logger.error.called

    @patch("generate_review_candidates.generate_candidates_for_filing")
    @patch("generate_review_candidates.logger")
    def test_process_empty_filings(self, mock_logger, mock_generate):
        """Test processing empty filings list."""
        mock_db = Mock()

        stats = process_filings(mock_db, [], show_progress=False)

        assert stats["filings_processed"] == 0
        assert stats["filings_failed"] == 0
        assert stats["total_candidates"] == 0
        mock_generate.assert_not_called()


class TestReportSummary:
    """Tests for report_summary()."""

    @patch("generate_review_candidates.logger")
    def test_report_with_successful_processing(self, mock_logger):
        """Test summary report with successful processing."""
        stats = {
            "filings_processed": 5,
            "filings_failed": 0,
            "total_candidates": 150,
            "total_segments": 500,
        }

        report_summary(stats, total_filings=5, dry_run=False)

        # Verify key metrics were logged
        log_calls = [call[0][0] for call in mock_logger.info.call_args_list]
        assert any("5/5" in msg for msg in log_calls)  # Processed count
        assert any("150" in msg for msg in log_calls)  # Total candidates
        assert any("30.0" in msg for msg in log_calls)  # Avg per filing (150/5)
        assert any("saved to database" in msg for msg in log_calls)

    @patch("generate_review_candidates.logger")
    def test_report_with_failures(self, mock_logger):
        """Test summary report with some failures."""
        stats = {
            "filings_processed": 3,
            "filings_failed": 2,
            "total_candidates": 90,
            "total_segments": 300,
        }

        report_summary(stats, total_filings=5, dry_run=False)

        log_calls = [call[0][0] for call in mock_logger.info.call_args_list]
        assert any("3/5" in msg for msg in log_calls)  # 3 processed out of 5
        assert any("2" in msg and "failed" in msg.lower() for msg in log_calls)

    @patch("generate_review_candidates.logger")
    def test_report_with_dry_run(self, mock_logger):
        """Test summary report with dry_run=True shows warning."""
        stats = {
            "filings_processed": 5,
            "filings_failed": 0,
            "total_candidates": 150,
            "total_segments": 500,
        }

        report_summary(stats, total_filings=5, dry_run=True)

        # Verify warning was logged for dry run
        warning_calls = [call[0][0] for call in mock_logger.warning.call_args_list]
        assert any("DRY RUN" in msg for msg in warning_calls)
        assert any("NOT saved" in msg for msg in warning_calls)

    @patch("generate_review_candidates.logger")
    def test_report_with_no_filings_processed(self, mock_logger):
        """Test summary report with zero filings processed."""
        stats = {
            "filings_processed": 0,
            "filings_failed": 5,
            "total_candidates": 0,
            "total_segments": 0,
        }

        report_summary(stats, total_filings=5, dry_run=False)

        # Should not crash with division by zero
        log_calls = [call[0][0] for call in mock_logger.info.call_args_list]
        assert any("0/5" in msg for msg in log_calls)

    @patch("generate_review_candidates.logger")
    def test_report_calculates_averages_correctly(self, mock_logger):
        """Test average calculations in summary."""
        stats = {
            "filings_processed": 4,
            "filings_failed": 0,
            "total_candidates": 100,
            "total_segments": 400,
        }

        report_summary(stats, total_filings=4, dry_run=False)

        log_calls = [call[0][0] for call in mock_logger.info.call_args_list]
        # Average candidates: 100/4 = 25.0
        assert any("25.0" in msg for msg in log_calls)
        # Average segments: 400/4 = 100.0
        assert any("100.0" in msg for msg in log_calls)


class TestArgumentValidation:
    """Tests for argument validation in main()."""

    @patch("generate_review_candidates.load_dotenv")
    @patch("sys.argv", ["script.py", "--limit", "2000"])
    def test_limit_exceeds_maximum(self, mock_dotenv):
        """Test limit validation rejects values > 1000."""
        from generate_review_candidates import main

        with pytest.raises(SystemExit) as exc_info:
            main()

        assert exc_info.value.code == 1

    @patch("generate_review_candidates.load_dotenv")
    @patch("sys.argv", ["script.py", "--limit", "0"])
    def test_limit_must_be_positive(self, mock_dotenv):
        """Test limit validation rejects values < 1."""
        from generate_review_candidates import main

        with pytest.raises(SystemExit) as exc_info:
            main()

        assert exc_info.value.code == 1

    @patch("generate_review_candidates.DatabaseAdapter")
    @patch("generate_review_candidates.load_dotenv")
    @patch("sys.argv", ["script.py", "--limit", "500"])
    def test_limit_within_range_accepted(self, mock_dotenv, mock_db_class):
        """Test limit validation accepts valid values."""
        mock_db = Mock()
        mock_db_class.return_value = mock_db
        mock_db.query.return_value = []  # No filings

        from generate_review_candidates import main

        # Should exit with code 0 (no filings found, but validation passed)
        with pytest.raises(SystemExit) as exc_info:
            main()

        assert exc_info.value.code == 0
