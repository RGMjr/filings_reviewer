"""
Integration tests for B3 candidate generation script.

Tests the main() function with mocked components.
"""

import pytest
from unittest.mock import Mock, patch
import sys
from pathlib import Path

# Add scripts to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))


class TestMainFunction:
    """Integration tests for main() orchestration."""

    @patch("generate_review_candidates.DatabaseAdapter")
    @patch("generate_review_candidates.generate_candidates_for_filing")
    @patch("generate_review_candidates.load_dotenv")
    @patch("sys.argv", ["script.py", "--filing-ids", "123,456", "--dry-run"])
    def test_main_with_filing_ids(self, mock_dotenv, mock_generate, mock_db_class):
        """Test main() with specific filing IDs."""
        # Setup mocks
        mock_db = Mock()
        mock_db_class.return_value = mock_db
        mock_db.query.return_value = [
            {
                "filing_id": 123,
                "company_id": 1,
                "company_name": "Test Co 1",
                "accession_number": "0001234567-23-000001",
                "filing_date": "2023-06-15",
                "segment_count": 50,
            },
            {
                "filing_id": 456,
                "company_id": 2,
                "company_name": "Test Co 2",
                "accession_number": "0001234567-23-000002",
                "filing_date": "2023-07-20",
                "segment_count": 75,
            },
        ]
        mock_generate.return_value = [Mock(), Mock(), Mock()]  # 3 candidates

        # Import and run main
        from generate_review_candidates import main

        main()

        # Verify database was queried for specific IDs
        assert mock_db.query.called
        query_call = mock_db.query.call_args
        assert "filing_id = ANY(%(filing_ids)s)" in query_call[0][0]
        assert query_call[0][1]["filing_ids"] == [123, 456]

        # Verify generate was called twice (once per filing)
        assert mock_generate.call_count == 2

    @patch("generate_review_candidates.DatabaseAdapter")
    @patch("generate_review_candidates.generate_candidates_for_filing")
    @patch("generate_review_candidates.load_dotenv")
    @patch("sys.argv", ["script.py", "--limit", "5"])
    def test_main_with_limit(self, mock_dotenv, mock_generate, mock_db_class):
        """Test main() with limit parameter."""
        # Setup mocks
        mock_db = Mock()
        mock_db_class.return_value = mock_db
        mock_db.query.return_value = [
            {
                "filing_id": 789,
                "company_id": 3,
                "company_name": "Test Co 3",
                "accession_number": "0001234567-23-000003",
                "filing_date": "2023-08-15",
                "segment_count": 100,
            }
        ]
        mock_generate.return_value = [Mock()]

        from generate_review_candidates import main

        main()

        # Verify database was queried with limit
        query_call = mock_db.query.call_args
        assert "rc.candidate_id IS NULL" in query_call[0][0]
        assert query_call[0][1]["limit"] == 5

    @patch("generate_review_candidates.DatabaseAdapter")
    @patch("generate_review_candidates.load_dotenv")
    @patch("sys.argv", ["script.py", "--filing-ids", "abc"])
    def test_main_with_invalid_filing_ids(self, mock_dotenv, mock_db_class):
        """Test main() exits with error code 1 for invalid filing IDs."""
        mock_db = Mock()
        mock_db_class.return_value = mock_db

        from generate_review_candidates import main

        with pytest.raises(SystemExit) as exc_info:
            main()

        # Verify exit code is 1 (error)
        assert exc_info.value.code == 1

    @patch("generate_review_candidates.DatabaseAdapter")
    @patch("generate_review_candidates.load_dotenv")
    @patch("sys.argv", ["script.py", "--limit", "10"])
    def test_main_exits_cleanly_when_no_filings_found(
        self, mock_dotenv, mock_db_class
    ):
        """Test main() exits with code 0 when no filings found."""
        mock_db = Mock()
        mock_db_class.return_value = mock_db
        mock_db.query.return_value = []  # No filings found

        from generate_review_candidates import main

        with pytest.raises(SystemExit) as exc_info:
            main()

        # Verify exit code is 0 (success - no error, just no work to do)
        assert exc_info.value.code == 0

    @patch("generate_review_candidates.DatabaseAdapter")
    @patch("generate_review_candidates.generate_candidates_for_filing")
    @patch("generate_review_candidates.load_dotenv")
    @patch("sys.argv", ["script.py", "--limit", "2", "--batch-id", "42"])
    def test_main_with_batch_id(self, mock_dotenv, mock_generate, mock_db_class):
        """Test main() passes batch_id to generate function."""
        mock_db = Mock()
        mock_db_class.return_value = mock_db
        mock_db.query.return_value = [
            {
                "filing_id": 999,
                "company_id": 4,
                "company_name": "Test Co 4",
                "accession_number": "0001234567-23-000004",
                "filing_date": "2023-09-15",
                "segment_count": 80,
            }
        ]
        mock_generate.return_value = [Mock()]

        from generate_review_candidates import main

        main()

        # Verify batch_id was passed
        call_kwargs = mock_generate.call_args[1]
        assert call_kwargs["batch_id"] == 42
