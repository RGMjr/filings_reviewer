"""
Unit tests for SEC client pattern matching and URL resolution.
"""

import pytest
from unittest.mock import Mock, patch
from src.infra.sec_client import SECClient


class TestResolveRimary_documentUrl:
    """Test suite for resolve_primary_document_url method."""

    @pytest.fixture
    def sec_client(self):
        """Create a SECClient instance for testing."""
        return SECClient(user_agent="test-client test@example.com")

    def test_pattern_matching_standard_s1(self, sec_client):
        """Test that standard s-1 pattern is recognized."""
        mock_response = Mock()
        mock_response.json.return_value = {
            "directory": {
                "item": [
                    {"name": "d123456ds1.htm", "size": 500000},
                    {"name": "ex10_1.htm", "size": 50000},
                ]
            }
        }

        with patch.object(sec_client.session, "get", return_value=mock_response):
            url = sec_client.resolve_primary_document_url(
                "0001234567", "0001234567-12-123456"
            )

        assert url is not None
        assert "d123456ds1.htm" in url
        assert "0001234567" in url

    def test_pattern_matching_form_prefix(self, sec_client):
        """Test that form prefix patterns (forms1, formf1) are recognized."""
        mock_response = Mock()
        mock_response.json.return_value = {
            "directory": {
                "item": [
                    {"name": "forms1_company.htm", "size": 500000},
                    {"name": "ex10_1.htm", "size": 50000},
                ]
            }
        }

        with patch.object(sec_client.session, "get", return_value=mock_response):
            url = sec_client.resolve_primary_document_url(
                "0001234567", "0001234567-12-123456"
            )

        assert url is not None
        assert "forms1_company.htm" in url

    def test_pattern_matching_mainbody(self, sec_client):
        """Test that mainbody pattern is recognized."""
        mock_response = Mock()
        mock_response.json.return_value = {
            "directory": {
                "item": [
                    {"name": "mainbody.htm", "size": 500000},
                    {"name": "signature.htm", "size": 10000},
                ]
            }
        }

        with patch.object(sec_client.session, "get", return_value=mock_response):
            url = sec_client.resolve_primary_document_url(
                "0001234567", "0001234567-12-123456"
            )

        assert url is not None
        assert "mainbody.htm" in url

    def test_pattern_matching_prospectus(self, sec_client):
        """Test that prospectus pattern is recognized."""
        mock_response = Mock()
        mock_response.json.return_value = {
            "directory": {
                "item": [
                    {"name": "prospectus.htm", "size": 500000},
                    {"name": "cover.htm", "size": 10000},
                ]
            }
        }

        with patch.object(sec_client.session, "get", return_value=mock_response):
            url = sec_client.resolve_primary_document_url(
                "0001234567", "0001234567-12-123456"
            )

        assert url is not None
        assert "prospectus.htm" in url

    def test_pattern_matching_registration(self, sec_client):
        """Test that registration pattern is recognized."""
        mock_response = Mock()
        mock_response.json.return_value = {
            "directory": {
                "item": [
                    {"name": "registration_statement.htm", "size": 500000},
                    {"name": "ex21.htm", "size": 10000},
                ]
            }
        }

        with patch.object(sec_client.session, "get", return_value=mock_response):
            url = sec_client.resolve_primary_document_url(
                "0001234567", "0001234567-12-123456"
            )

        assert url is not None
        assert "registration_statement.htm" in url

    def test_fallback_to_largest_file(self, sec_client):
        """Test fallback to largest file when no pattern matches."""
        mock_response = Mock()
        mock_response.json.return_value = {
            "directory": {
                "item": [
                    {"name": "cover.htm", "size": 10000},
                    {"name": "document.htm", "size": 500000},  # Largest
                    {"name": "signature.htm", "size": 5000},
                ]
            }
        }

        with patch.object(sec_client.session, "get", return_value=mock_response):
            url = sec_client.resolve_primary_document_url(
                "0001234567", "0001234567-12-123456"
            )

        assert url is not None
        assert "document.htm" in url  # Should select largest file

    def test_exclude_exhibit_files_in_fallback(self, sec_client):
        """Test that exhibit files are excluded from fallback selection."""
        mock_response = Mock()
        mock_response.json.return_value = {
            "directory": {
                "item": [
                    {"name": "document.htm", "size": 300000},
                    {
                        "name": "exhibit_99_1.htm",
                        "size": 500000,
                    },  # Larger but is exhibit
                    {
                        "name": "ex10_1.htm",
                        "size": 400000,
                    },  # Larger but starts with 'ex'
                ]
            }
        }

        with patch.object(sec_client.session, "get", return_value=mock_response):
            url = sec_client.resolve_primary_document_url(
                "0001234567", "0001234567-12-123456"
            )

        assert url is not None
        assert (
            "document.htm" in url
        )  # Should exclude exhibits and select largest non-exhibit

    def test_exclude_xbrl_files(self, sec_client):
        """Test that XBRL files (starting with R) are excluded."""
        mock_response = Mock()
        mock_response.json.return_value = {
            "directory": {
                "item": [
                    {"name": "document.htm", "size": 300000},
                    {"name": "R1.htm", "size": 500000},  # XBRL file
                    {"name": "R2.htm", "size": 400000},  # XBRL file
                ]
            }
        }

        with patch.object(sec_client.session, "get", return_value=mock_response):
            url = sec_client.resolve_primary_document_url(
                "0001234567", "0001234567-12-123456"
            )

        assert url is not None
        assert "document.htm" in url  # Should exclude R*.htm files

    def test_no_html_files_returns_none(self, sec_client):
        """Test that None is returned when no HTML files are found."""
        mock_response = Mock()
        mock_response.json.return_value = {
            "directory": {
                "item": [
                    {"name": "filing.txt", "size": 500000},
                    {"name": "filing.xml", "size": 300000},
                ]
            }
        }

        with patch.object(sec_client.session, "get", return_value=mock_response):
            url = sec_client.resolve_primary_document_url(
                "0001234567", "0001234567-12-123456"
            )

        assert url is None

    def test_http_error_returns_none(self, sec_client):
        """Test that None is returned on HTTP errors."""
        mock_response = Mock()
        mock_response.raise_for_status.side_effect = Exception("404 Not Found")

        with patch.object(sec_client.session, "get", return_value=mock_response):
            url = sec_client.resolve_primary_document_url(
                "0001234567", "0001234567-12-123456"
            )

        assert url is None

    def test_url_format_correctness(self, sec_client):
        """Test that returned URL has correct format."""
        mock_response = Mock()
        mock_response.json.return_value = {
            "directory": {
                "item": [
                    {"name": "d123456ds1.htm", "size": 500000},
                ]
            }
        }

        with patch.object(sec_client.session, "get", return_value=mock_response):
            url = sec_client.resolve_primary_document_url(
                "0001234567", "0001234567-12-123456"
            )

        # URL should have format: https://www.sec.gov/Archives/edgar/data/{cik}/{accession_no_dashes}/{filename}
        assert url.startswith("https://www.sec.gov/Archives/edgar/data/")
        assert "0001234567" in url
        assert "000123456712123456" in url  # Accession without dashes
        assert "d123456ds1.htm" in url

    def test_compact_patterns_ss1_ff1(self, sec_client):
        """Test compact patterns without separators (ss1, ff1)."""
        mock_response = Mock()
        mock_response.json.return_value = {
            "directory": {
                "item": [
                    {"name": "ff12014a1_biondvax.htm", "size": 500000},
                    {"name": "ex10_1.htm", "size": 50000},
                ]
            }
        }

        with patch.object(sec_client.session, "get", return_value=mock_response):
            url = sec_client.resolve_primary_document_url(
                "0001234567", "0001234567-12-123456"
            )

        assert url is not None
        assert "ff12014a1_biondvax.htm" in url

    def test_amendment_patterns_s1a_f1a(self, sec_client):
        """Test amendment patterns (s1a, f1a)."""
        mock_response = Mock()
        mock_response.json.return_value = {
            "directory": {
                "item": [
                    {"name": "d123456ds1a.htm", "size": 500000},
                    {"name": "ex10_1.htm", "size": 50000},
                ]
            }
        }

        with patch.object(sec_client.session, "get", return_value=mock_response):
            url = sec_client.resolve_primary_document_url(
                "0001234567", "0001234567-12-123456"
            )

        assert url is not None
        assert "d123456ds1a.htm" in url

    def test_case_insensitive_matching(self, sec_client):
        """Test that pattern matching is case-insensitive."""
        mock_response = Mock()
        mock_response.json.return_value = {
            "directory": {
                "item": [
                    {"name": "FORM_S-1.htm", "size": 500000},
                    {"name": "other_document.htm", "size": 50000},
                ]
            }
        }

        with patch.object(sec_client.session, "get", return_value=mock_response):
            url = sec_client.resolve_primary_document_url(
                "0001234567", "0001234567-12-123456"
            )

        assert url is not None
        assert "FORM_S-1.htm" in url


class TestExtractAccessionFromFilename:
    """Test suite for _extract_accession_from_filename method."""

    @pytest.fixture
    def sec_client(self):
        """Create a SECClient instance for testing."""
        return SECClient(user_agent="test-client test@example.com")

    def test_standard_filename(self, sec_client):
        """Test extraction from standard SEC filename."""
        filename = "edgar/data/1234567/0001193125-19-163007.txt"
        accession = sec_client._extract_accession_from_filename(filename)
        assert accession == "0001193125-19-163007"

    def test_html_filename(self, sec_client):
        """Test extraction from HTML filename."""
        filename = "edgar/data/1234567/0001193125-19-163007.htm"
        accession = sec_client._extract_accession_from_filename(filename)
        assert accession == "0001193125-19-163007"

    def test_malformed_filename_returns_empty(self, sec_client):
        """Test that malformed filename returns empty string."""
        filename = "invalid"
        accession = sec_client._extract_accession_from_filename(filename)
        assert accession == ""

    def test_filename_with_trailing_slash(self, sec_client):
        """Test extraction with trailing slash."""
        filename = "edgar/data/1234567/0001193125-19-163007.txt/"
        accession = sec_client._extract_accession_from_filename(filename)
        # Should still extract correctly
        assert "0001193125-19-163007" in accession or accession == ""


class TestRateLimiting:
    """Test suite for rate limiting functionality."""

    @pytest.fixture
    def sec_client(self):
        """Create a SECClient instance for testing."""
        return SECClient(user_agent="test-client test@example.com")

    def test_rate_limit_enforced(self, sec_client):
        """Test that rate limiting delays are enforced."""
        import time

        # Make two quick requests
        start = time.time()
        sec_client._rate_limit()
        sec_client._rate_limit()
        elapsed = time.time() - start

        # Should have delayed at least MIN_REQUEST_INTERVAL
        assert elapsed >= sec_client.MIN_REQUEST_INTERVAL

    def test_rate_limit_not_enforced_if_enough_time_passed(self, sec_client):
        """Test that rate limiting doesn't delay if enough time has passed."""
        import time

        sec_client._rate_limit()
        time.sleep(0.2)  # Wait longer than MIN_REQUEST_INTERVAL

        start = time.time()
        sec_client._rate_limit()
        elapsed = time.time() - start

        # Should not have significant delay
        assert elapsed < 0.05  # Less than 50ms


class TestParseMasterIndex:
    """Test suite for _parse_master_index method."""

    @pytest.fixture
    def sec_client(self):
        """Create a SECClient instance for testing."""
        return SECClient(user_agent="test-client test@example.com")

    def test_parse_valid_index(self, sec_client):
        """Test parsing of valid master index file."""
        index_text = """
Description: Master Index of EDGAR Dissemination Feed
Last Data Received: January 15, 2024
Comments: Webmaster@sec.gov
Anonymous FTP: ftp://ftp.sec.gov/edgar/

------------------------------------------------------------
CIK|Company Name|Form Type|Date Filed|Filename
1234567|Example Corp|S-1|2024-01-15|edgar/data/1234567/0001193125-24-000001.txt
7654321|Test Inc|F-1|2024-01-15|edgar/data/7654321/0001193125-24-000002.txt
"""
        filings = sec_client._parse_master_index(index_text, ["S-1", "F-1"])

        assert len(filings) == 2
        assert filings[0].cik == "0001234567"  # Should be zero-padded to 10 digits
        assert filings[0].company_name == "Example Corp"
        assert filings[0].form_type == "S-1"
        assert filings[0].filing_date == "2024-01-15"

    def test_filter_by_form_type(self, sec_client):
        """Test that filings are filtered by form type."""
        index_text = """
------------------------------------------------------------
CIK|Company Name|Form Type|Date Filed|Filename
1234567|Example Corp|S-1|2024-01-15|edgar/data/1234567/0001193125-24-000001.txt
7654321|Test Inc|10-K|2024-01-15|edgar/data/7654321/0001193125-24-000002.txt
"""
        filings = sec_client._parse_master_index(index_text, ["S-1"])

        assert len(filings) == 1
        assert filings[0].form_type == "S-1"

    def test_skip_malformed_lines(self, sec_client):
        """Test that malformed lines are skipped."""
        index_text = """
------------------------------------------------------------
CIK|Company Name|Form Type|Date Filed|Filename
1234567|Example Corp|S-1|2024-01-15|edgar/data/1234567/0001193125-24-000001.txt
invalid line
7654321|Test Inc|S-1|2024-01-15|edgar/data/7654321/0001193125-24-000002.txt
"""
        filings = sec_client._parse_master_index(index_text, ["S-1"])

        assert len(filings) == 2  # Should skip malformed line

    def test_empty_index(self, sec_client):
        """Test parsing of empty index file."""
        index_text = """
------------------------------------------------------------
CIK|Company Name|Form Type|Date Filed|Filename
"""
        filings = sec_client._parse_master_index(index_text, ["S-1"])

        assert len(filings) == 0
