"""
Integration tests for end-to-end filing fetcher pipeline.

These tests simulate real-world scenarios including edge cases and error handling.
"""

import pytest
from pathlib import Path
from unittest.mock import Mock, patch

from src.filing_fetcher.filing_fetcher import FilingFetcher
from src.infra.sec_client import SECClient, FilingMetadata


class TestRealWorldEdgeCases:
    """Integration tests for real-world edge cases we've encountered."""

    @pytest.fixture
    def fetcher(self, tmp_path):
        """Create a full filing fetcher setup."""
        sec_client = SECClient(user_agent="test-client test@example.com")
        return FilingFetcher(
            storage_root=str(tmp_path / "test_filings"), sec_client=sec_client
        )

    @pytest.fixture
    def valid_filing_html(self):
        """Create valid filing HTML."""
        return (
            """
<DOCUMENT>
<TYPE>S-1
<TEXT>
<HTML>
<HEAD><TITLE>S-1</TITLE></HEAD>
<BODY>
<P>UNITED STATES SECURITIES AND EXCHANGE COMMISSION</P>
<P>FORM S-1</P>
<P>REGISTRATION STATEMENT</P>
"""
            + "X" * 20000
        )

    def test_unusual_filename_mainbody(self, fetcher, valid_filing_html):
        """Test handling filing with 'mainbody.htm' as primary document."""
        metadata = FilingMetadata(
            cik="0001234567",
            company_name="Test Corp",
            form_type="S-1",
            filing_date="2024-01-15",
            accession_number="0001234567-12-123456",
            primary_doc_url="https://www.sec.gov/Archives/edgar/data/1234567/000123456712123456/",  # Directory URL
        )

        # Mock SEC client to resolve URL with unusual filename
        with patch.object(fetcher.sec_client, "session") as mock_session:
            # First call: get index.json
            mock_index_response = Mock()
            mock_index_response.json.return_value = {
                "directory": {
                    "item": [
                        {"name": "mainbody.htm", "size": 500000},
                        {"name": "exhibit99_1.htm", "size": 100000},
                    ]
                }
            }
            mock_index_response.raise_for_status = Mock()

            # Second call: get mainbody.htm
            mock_filing_response = Mock()
            mock_filing_response.text = valid_filing_html
            mock_filing_response.raise_for_status = Mock()

            mock_session.get.side_effect = [mock_index_response, mock_filing_response]

            # Also patch fetcher's session for the actual filing download
            with patch.object(
                fetcher.session, "get", return_value=mock_filing_response
            ):
                content = fetcher.fetch_filing(metadata, fetch_txt=False)

        assert content is not None
        assert Path(content.html_path).exists()

    def test_compact_pattern_ff1(self, fetcher, valid_filing_html):
        """Test handling filing with compact pattern 'ff1' in filename."""
        metadata = FilingMetadata(
            cik="0001234567",
            company_name="Biondvax",
            form_type="F-1",
            filing_date="2024-01-15",
            accession_number="0001234567-12-123456",
            primary_doc_url="https://www.sec.gov/Archives/edgar/data/1234567/000123456712123456/",
        )

        with patch.object(fetcher.sec_client, "session") as mock_session:
            mock_index_response = Mock()
            mock_index_response.json.return_value = {
                "directory": {
                    "item": [
                        {"name": "ff12014a1_biondvax.htm", "size": 500000},
                        {"name": "ex10_1.htm", "size": 100000},
                    ]
                }
            }
            mock_index_response.raise_for_status = Mock()

            mock_filing_response = Mock()
            mock_filing_response.text = valid_filing_html
            mock_filing_response.raise_for_status = Mock()

            mock_session.get.side_effect = [mock_index_response, mock_filing_response]

            with patch.object(
                fetcher.session, "get", return_value=mock_filing_response
            ):
                content = fetcher.fetch_filing(metadata, fetch_txt=False)

        assert content is not None

    def test_modern_html_format(self, fetcher):
        """Test handling modern HTML format (2022+) without SGML wrapper."""
        modern_html = (
            """
<!DOCTYPE html>
<HTML>
<HEAD><TITLE>SEC Filing</TITLE></HEAD>
<BODY>
<P>UNITED STATES SECURITIES AND EXCHANGE COMMISSION</P>
<P>FORM S-1</P>
<P>REGISTRATION STATEMENT</P>
<TABLE><TR><TD>Company info</TD></TR></TABLE>
<DIV>Additional filing content</DIV>
"""
            + "X" * 20000
        )

        metadata = FilingMetadata(
            cik="0001234567",
            company_name="Modern Corp",
            form_type="S-1",
            filing_date="2024-01-15",
            accession_number="0001234567-12-123456",
            primary_doc_url="https://www.sec.gov/Archives/edgar/data/1234567/000123456712123456/document.htm",
        )

        mock_response = Mock()
        mock_response.text = modern_html
        mock_response.raise_for_status = Mock()

        with patch.object(fetcher.session, "get", return_value=mock_response):
            content = fetcher.fetch_filing(metadata, fetch_txt=False)

        assert content is not None
        assert Path(content.html_path).exists()

        # Verify file content
        saved_content = Path(content.html_path).read_text()
        assert "DOCTYPE html" in saved_content
        assert "<DOCUMENT>" not in saved_content  # No SGML wrapper

    def test_largest_file_fallback(self, fetcher, valid_filing_html):
        """Test fallback to largest file when no pattern matches."""
        metadata = FilingMetadata(
            cik="0001234567",
            company_name="Test Corp",
            form_type="S-1",
            filing_date="2024-01-15",
            accession_number="0001234567-12-123456",
            primary_doc_url="https://www.sec.gov/Archives/edgar/data/1234567/000123456712123456/",
        )

        with patch.object(fetcher.sec_client, "session") as mock_session:
            mock_index_response = Mock()
            mock_index_response.json.return_value = {
                "directory": {
                    "item": [
                        {"name": "cover.htm", "size": 10000},
                        {"name": "document.htm", "size": 500000},  # Largest
                        {"name": "signature.htm", "size": 5000},
                    ]
                }
            }
            mock_index_response.raise_for_status = Mock()

            mock_filing_response = Mock()
            mock_filing_response.text = valid_filing_html
            mock_filing_response.raise_for_status = Mock()

            mock_session.get.side_effect = [mock_index_response, mock_filing_response]

            with patch.object(
                fetcher.session, "get", return_value=mock_filing_response
            ):
                content = fetcher.fetch_filing(metadata, fetch_txt=False)

        assert content is not None


class TestErrorRecovery:
    """Integration tests for error handling and recovery."""

    @pytest.fixture
    def fetcher(self, tmp_path):
        """Create a full filing fetcher setup."""
        sec_client = SECClient(user_agent="test-client test@example.com")
        return FilingFetcher(
            storage_root=str(tmp_path / "test_filings"), sec_client=sec_client
        )

    def test_retry_after_validation_failure(self, fetcher):
        """Test that invalid content is properly rejected and not saved."""
        metadata = FilingMetadata(
            cik="0001234567",
            company_name="Test Corp",
            form_type="S-1",
            filing_date="2024-01-15",
            accession_number="0001234567-12-123456",
            primary_doc_url="https://www.sec.gov/Archives/edgar/data/1234567/000123456712123456/document.htm",
        )

        # First attempt: return error page
        invalid_content = """
<HTML>
<HEAD><TITLE>Error</TITLE></HEAD>
<BODY>
<P>No rendered XBRL documents were found</P>
</BODY>
</HTML>
"""

        mock_response = Mock()
        mock_response.text = invalid_content
        mock_response.raise_for_status = Mock()

        with patch.object(fetcher.session, "get", return_value=mock_response):
            content = fetcher.fetch_filing(metadata, fetch_txt=False)

        # Should return None because content is invalid
        assert content is None

        # Verify no file was saved
        storage_dir = fetcher._get_storage_dir("0001234567", "0001234567-12-123456")
        html_path = storage_dir / "primary.htm"
        assert not html_path.exists()

    def test_http_404_handling(self, fetcher):
        """Test handling of HTTP 404 errors."""
        metadata = FilingMetadata(
            cik="0001234567",
            company_name="Test Corp",
            form_type="S-1",
            filing_date="2024-01-15",
            accession_number="0001234567-12-123456",
            primary_doc_url="https://www.sec.gov/Archives/edgar/data/1234567/000123456712123456/document.htm",
        )

        mock_response = Mock()
        mock_response.raise_for_status.side_effect = Exception("404 Not Found")

        with patch.object(fetcher.session, "get", return_value=mock_response):
            content = fetcher.fetch_filing(metadata, fetch_txt=False)

        assert content is None

    def test_partial_download_recovery(self, fetcher):
        """Test recovery from partial/interrupted downloads."""
        (
            """
<DOCUMENT>
<TYPE>S-1
<TEXT>
<HTML>
<HEAD><TITLE>S-1</TITLE></HEAD>
<BODY>
<P>UNITED STATES SECURITIES AND EXCHANGE COMMISSION</P>
<P>FORM S-1</P>
"""
            + "X" * 20000
        )

        metadata = FilingMetadata(
            cik="0001234567",
            company_name="Test Corp",
            form_type="S-1",
            filing_date="2024-01-15",
            accession_number="0001234567-12-123456",
            primary_doc_url="https://www.sec.gov/Archives/edgar/data/1234567/000123456712123456/document.htm",
        )

        # Simulate partial download by creating incomplete file
        storage_dir = fetcher._get_storage_dir("0001234567", "0001234567-12-123456")
        storage_dir.mkdir(parents=True, exist_ok=True)
        html_path = storage_dir / "primary.htm"
        html_path.write_text("<html>partial content")  # Incomplete/invalid

        # Now try to fetch again - should skip because file exists
        mock_get = Mock()
        with patch.object(fetcher.session, "get", mock_get):
            content = fetcher.fetch_filing(metadata, fetch_txt=False)

        # Should not make HTTP request because file exists
        mock_get.assert_not_called()
        assert content is not None


class TestBatchProcessing:
    """Integration tests for batch filing processing."""

    @pytest.fixture
    def fetcher(self, tmp_path):
        """Create a full filing fetcher setup."""
        sec_client = SECClient(user_agent="test-client test@example.com")
        return FilingFetcher(
            storage_root=str(tmp_path / "test_filings"), sec_client=sec_client
        )

    @pytest.fixture
    def valid_filing_html(self):
        """Create valid filing HTML."""
        return (
            """
<DOCUMENT>
<TYPE>S-1
<TEXT>
<HTML>
<HEAD><TITLE>S-1</TITLE></HEAD>
<BODY>
<P>UNITED STATES SECURITIES AND EXCHANGE COMMISSION</P>
<P>FORM S-1</P>
"""
            + "X" * 20000
        )

    def test_mixed_success_failure_batch(self, fetcher, valid_filing_html):
        """Test batch processing with mixed successes and failures."""
        filings = [
            FilingMetadata(
                cik="0001234567",
                company_name="Success Corp",
                form_type="S-1",
                filing_date="2024-01-15",
                accession_number="0001234567-12-123456",
                primary_doc_url="https://www.sec.gov/test1.htm",
            ),
            FilingMetadata(
                cik="0007654321",
                company_name="Fail Corp",
                form_type="S-1",
                filing_date="2024-01-16",
                accession_number="0007654321-12-654321",
                primary_doc_url="https://www.sec.gov/test2.htm",
            ),
            FilingMetadata(
                cik="0001111111",
                company_name="Success Corp 2",
                form_type="S-1",
                filing_date="2024-01-17",
                accession_number="0001111111-12-111111",
                primary_doc_url="https://www.sec.gov/test3.htm",
            ),
        ]

        call_count = [0]

        def get_side_effect(url):
            call_count[0] += 1
            response = Mock()

            if call_count[0] == 2:  # Second call fails
                response.raise_for_status.side_effect = Exception("404")
                return response
            else:
                response.text = valid_filing_html
                response.raise_for_status = Mock()
                return response

        with patch.object(fetcher.session, "get", side_effect=get_side_effect):
            stats = fetcher.fetch_batch(filings, fetch_txt=False, max_failures=10)

        assert stats["total"] == 3
        assert stats["fetched"] == 2
        assert stats["failed"] == 1
        assert stats["skipped"] == 0

    def test_batch_stops_on_consecutive_failures(self, fetcher):
        """Test that batch processing stops after max consecutive failures."""
        filings = [
            FilingMetadata(
                cik=f"{i:010d}",
                company_name=f"Corp {i}",
                form_type="S-1",
                filing_date="2024-01-15",
                accession_number=f"{i:010d}-12-123456",
                primary_doc_url=f"https://www.sec.gov/test{i}.htm",
            )
            for i in range(15)
        ]

        # All requests fail
        mock_response = Mock()
        mock_response.raise_for_status.side_effect = Exception("Error")

        with patch.object(fetcher.session, "get", return_value=mock_response):
            stats = fetcher.fetch_batch(filings, fetch_txt=False, max_failures=3)

        # Should stop after 3 consecutive failures
        assert stats["failed"] == 3
        assert stats["fetched"] == 0

    def test_batch_resumes_after_success(self, fetcher, valid_filing_html):
        """Test that consecutive failure counter resets after a success."""
        filings = [
            FilingMetadata(
                cik=f"{i:010d}",
                company_name=f"Corp {i}",
                form_type="S-1",
                filing_date="2024-01-15",
                accession_number=f"{i:010d}-12-123456",
                primary_doc_url=f"https://www.sec.gov/test{i}.htm",
            )
            for i in range(10)
        ]

        call_count = [0]

        def get_side_effect(url):
            call_count[0] += 1
            response = Mock()

            # Fail first 2, succeed on 3rd, fail next 2, succeed on 6th, etc.
            if call_count[0] % 3 == 0:
                response.text = valid_filing_html
                response.raise_for_status = Mock()
            else:
                response.raise_for_status.side_effect = Exception("Error")

            return response

        with patch.object(fetcher.session, "get", side_effect=get_side_effect):
            stats = fetcher.fetch_batch(filings, fetch_txt=False, max_failures=3)

        # Should process all 10 because successes reset the counter
        assert stats["total"] == 10
        assert stats["fetched"] > 0
        assert stats["failed"] < 10  # Some failures but not all
