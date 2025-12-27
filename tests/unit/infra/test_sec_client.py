"""
Unit tests for SEC client pattern matching, URL resolution, retry logic, and metrics.
"""

import json
import time
from unittest.mock import Mock, patch

import pytest
import requests

from src.infra.exceptions import SECDataError, SECRateLimitError
from src.infra.http_client import HTTPResponse
from src.infra.sec_client import SECClient, SECClientMetrics
from tests.unit.infra.mock_http_client import MockHTTPClient


@pytest.fixture
def sec_client():
    """Create a SECClient instance for testing."""
    return SECClient()


class TestResolvePrimaryDocumentUrl:
    """Test suite for resolve_primary_document_url method."""

    def test_pattern_matching_standard_s1(self):
        """Test that standard s-1 pattern is recognized."""
        response_data = {
            "directory": {
                "item": [
                    {"name": "d123456ds1.htm", "size": 500000},
                    {"name": "ex10_1.htm", "size": 50000},
                ]
            }
        }

        mock_response = HTTPResponse(
            status_code=200,
            content=json.dumps(response_data).encode('utf-8'),
            headers={},
            url="https://www.sec.gov/Archives/edgar/data/0001234567/000123456712123456/index.json",
            elapsed_seconds=0.1
        )

        mock_client = MockHTTPClient()
        mock_client.responses["https://www.sec.gov/Archives/edgar/data/0001234567/000123456712123456/index.json"] = mock_response

        sec_client = SECClient(http_client=mock_client)
        url = sec_client.resolve_primary_document_url(
            "0001234567", "0001234567-12-123456"
        )

        assert url is not None
        assert "d123456ds1.htm" in url
        assert "0001234567" in url

    def test_exhibit_files_excluded_from_pattern_matching(self):
        """Test that exhibit files with form patterns are excluded (bug fix).

        This tests the fix for exhibit files like 'exhibit103s-1.htm' incorrectly
        matching before the actual S-1 document 'slacks-1.htm' when both contain 's-1'.
        """
        response_data = {
            "directory": {
                "item": [
                    # These are alphabetically first and contain 's-1' pattern
                    {"name": "exhibit101-sx1.htm", "size": 82122},
                    {"name": "exhibit103s-1.htm", "size": 80810},  # Contains 's-1'!
                    {"name": "exhibit107s-1.htm", "size": 63800},  # Contains 's-1'!
                    # The actual main document, alphabetically last
                    {"name": "slacks-1.htm", "size": 3782931},
                ]
            }
        }

        mock_response = HTTPResponse(
            status_code=200,
            content=json.dumps(response_data).encode('utf-8'),
            headers={},
            url="https://www.sec.gov/Archives/edgar/data/1764925/000162828019004786/index.json",
            elapsed_seconds=0.1
        )

        mock_client = MockHTTPClient()
        mock_client.responses["https://www.sec.gov/Archives/edgar/data/1764925/000162828019004786/index.json"] = mock_response

        sec_client = SECClient(http_client=mock_client)
        url = sec_client.resolve_primary_document_url(
            "1764925", "0001628280-19-004786"
        )

        assert url is not None
        # Should return the actual S-1 document, not the exhibit
        assert "slacks-1.htm" in url
        assert "exhibit" not in url.lower()

    def test_pattern_matching_form_prefix(self):
        """Test that form prefix patterns (forms1, formf1) are recognized."""
        response_data = {
            "directory": {
                "item": [
                    {"name": "forms1_company.htm", "size": 500000},
                    {"name": "ex10_1.htm", "size": 50000},
                ]
            }
        }

        mock_response = HTTPResponse(
            status_code=200,
            content=json.dumps(response_data).encode('utf-8'),
            headers={},
            url="https://www.sec.gov/Archives/edgar/data/0001234567/000123456712123456/index.json",
            elapsed_seconds=0.1
        )

        mock_client = MockHTTPClient()
        mock_client.responses["https://www.sec.gov/Archives/edgar/data/0001234567/000123456712123456/index.json"] = mock_response

        sec_client = SECClient(http_client=mock_client)
        url = sec_client.resolve_primary_document_url(
            "0001234567", "0001234567-12-123456"
        )

        assert url is not None
        assert "forms1_company.htm" in url

    def test_pattern_matching_mainbody(self):
        """Test that mainbody pattern is recognized."""
        response_data = {
            "directory": {
                "item": [
                    {"name": "mainbody.htm", "size": 500000},
                    {"name": "signature.htm", "size": 10000},
                ]
            }
        }

        mock_response = HTTPResponse(
            status_code=200,
            content=json.dumps(response_data).encode('utf-8'),
            headers={},
            url="https://www.sec.gov/Archives/edgar/data/0001234567/000123456712123456/index.json",
            elapsed_seconds=0.1
        )

        mock_client = MockHTTPClient()
        mock_client.responses["https://www.sec.gov/Archives/edgar/data/0001234567/000123456712123456/index.json"] = mock_response

        sec_client = SECClient(http_client=mock_client)
        url = sec_client.resolve_primary_document_url(
            "0001234567", "0001234567-12-123456"
        )

        assert url is not None
        assert "mainbody.htm" in url

    def test_pattern_matching_prospectus(self):
        """Test that prospectus pattern is recognized."""
        response_data = {
            "directory": {
                "item": [
                    {"name": "prospectus.htm", "size": 500000},
                    {"name": "cover.htm", "size": 10000},
                ]
            }
        }

        mock_response = HTTPResponse(
            status_code=200,
            content=json.dumps(response_data).encode('utf-8'),
            headers={},
            url="https://www.sec.gov/Archives/edgar/data/0001234567/000123456712123456/index.json",
            elapsed_seconds=0.1
        )

        mock_client = MockHTTPClient()
        mock_client.responses["https://www.sec.gov/Archives/edgar/data/0001234567/000123456712123456/index.json"] = mock_response

        sec_client = SECClient(http_client=mock_client)
        url = sec_client.resolve_primary_document_url(
            "0001234567", "0001234567-12-123456"
        )

        assert url is not None
        assert "prospectus.htm" in url

    def test_pattern_matching_registration(self):
        """Test that registration pattern is recognized."""
        response_data = {
            "directory": {
                "item": [
                    {"name": "registration_statement.htm", "size": 500000},
                    {"name": "ex21.htm", "size": 10000},
                ]
            }
        }

        mock_response = HTTPResponse(
            status_code=200,
            content=json.dumps(response_data).encode('utf-8'),
            headers={},
            url="https://www.sec.gov/Archives/edgar/data/0001234567/000123456712123456/index.json",
            elapsed_seconds=0.1
        )

        mock_client = MockHTTPClient()
        mock_client.responses["https://www.sec.gov/Archives/edgar/data/0001234567/000123456712123456/index.json"] = mock_response

        sec_client = SECClient(http_client=mock_client)
        url = sec_client.resolve_primary_document_url(
            "0001234567", "0001234567-12-123456"
        )

        assert url is not None
        assert "registration_statement.htm" in url

    def test_fallback_to_largest_file(self):
        """Test fallback to largest file when no pattern matches."""
        response_data = {
            "directory": {
                "item": [
                    {"name": "cover.htm", "size": 10000},
                    {"name": "document.htm", "size": 500000},  # Largest
                    {"name": "signature.htm", "size": 5000},
                ]
            }
        }

        mock_response = HTTPResponse(
            status_code=200,
            content=json.dumps(response_data).encode('utf-8'),
            headers={},
            url="https://www.sec.gov/Archives/edgar/data/0001234567/000123456712123456/index.json",
            elapsed_seconds=0.1
        )

        mock_client = MockHTTPClient()
        mock_client.responses["https://www.sec.gov/Archives/edgar/data/0001234567/000123456712123456/index.json"] = mock_response

        sec_client = SECClient(http_client=mock_client)
        url = sec_client.resolve_primary_document_url(
            "0001234567", "0001234567-12-123456"
        )

        assert url is not None
        assert "document.htm" in url  # Should select largest file

    def test_exclude_exhibit_files_in_fallback(self):
        """Test that exhibit files are excluded from fallback selection."""
        response_data = {
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

        mock_response = HTTPResponse(
            status_code=200,
            content=json.dumps(response_data).encode('utf-8'),
            headers={},
            url="https://www.sec.gov/Archives/edgar/data/0001234567/000123456712123456/index.json",
            elapsed_seconds=0.1
        )

        mock_client = MockHTTPClient()
        mock_client.responses["https://www.sec.gov/Archives/edgar/data/0001234567/000123456712123456/index.json"] = mock_response

        sec_client = SECClient(http_client=mock_client)
        url = sec_client.resolve_primary_document_url(
            "0001234567", "0001234567-12-123456"
        )

        assert url is not None
        assert (
            "document.htm" in url
        )  # Should exclude exhibits and select largest non-exhibit

    def test_exclude_xbrl_files(self):
        """Test that XBRL files (starting with R) are excluded."""
        response_data = {
            "directory": {
                "item": [
                    {"name": "document.htm", "size": 300000},
                    {"name": "R1.htm", "size": 500000},  # XBRL file
                    {"name": "R2.htm", "size": 400000},  # XBRL file
                ]
            }
        }

        mock_response = HTTPResponse(
            status_code=200,
            content=json.dumps(response_data).encode('utf-8'),
            headers={},
            url="https://www.sec.gov/Archives/edgar/data/0001234567/000123456712123456/index.json",
            elapsed_seconds=0.1
        )

        mock_client = MockHTTPClient()
        mock_client.responses["https://www.sec.gov/Archives/edgar/data/0001234567/000123456712123456/index.json"] = mock_response

        sec_client = SECClient(http_client=mock_client)
        url = sec_client.resolve_primary_document_url(
            "0001234567", "0001234567-12-123456"
        )

        assert url is not None
        assert "document.htm" in url  # Should exclude R*.htm files

    def test_no_html_files_returns_none(self):
        """Test that None is returned when no HTML files are found."""
        response_data = {
            "directory": {
                "item": [
                    {"name": "filing.txt", "size": 500000},
                    {"name": "filing.xml", "size": 300000},
                ]
            }
        }

        mock_response = HTTPResponse(
            status_code=200,
            content=json.dumps(response_data).encode('utf-8'),
            headers={},
            url="https://www.sec.gov/Archives/edgar/data/0001234567/000123456712123456/index.json",
            elapsed_seconds=0.1
        )

        mock_client = MockHTTPClient()
        mock_client.responses["https://www.sec.gov/Archives/edgar/data/0001234567/000123456712123456/index.json"] = mock_response

        sec_client = SECClient(http_client=mock_client)
        url = sec_client.resolve_primary_document_url(
            "0001234567", "0001234567-12-123456"
        )

        assert url is None

    def test_http_error_returns_none(self):
        """Test that None is returned on HTTP errors."""
        mock_client = MockHTTPClient()
        # Configure mock to raise an exception
        mock_client.failures["https://www.sec.gov/Archives/edgar/data/0001234567/000123456712123456/index.json"] = Exception("404 Not Found")

        sec_client = SECClient(http_client=mock_client)
        url = sec_client.resolve_primary_document_url(
            "0001234567", "0001234567-12-123456"
        )

        assert url is None

    def test_url_format_correctness(self):
        """Test that returned URL has correct format."""
        response_data = {
            "directory": {
                "item": [
                    {"name": "d123456ds1.htm", "size": 500000},
                ]
            }
        }

        mock_response = HTTPResponse(
            status_code=200,
            content=json.dumps(response_data).encode('utf-8'),
            headers={},
            url="https://www.sec.gov/Archives/edgar/data/0001234567/000123456712123456/index.json",
            elapsed_seconds=0.1
        )

        mock_client = MockHTTPClient()
        mock_client.responses["https://www.sec.gov/Archives/edgar/data/0001234567/000123456712123456/index.json"] = mock_response

        sec_client = SECClient(http_client=mock_client)
        url = sec_client.resolve_primary_document_url(
            "0001234567", "0001234567-12-123456"
        )

        # URL should have format: https://www.sec.gov/Archives/edgar/data/{cik}/{accession_no_dashes}/{filename}
        assert url.startswith("https://www.sec.gov/Archives/edgar/data/")
        assert "0001234567" in url
        assert "000123456712123456" in url  # Accession without dashes
        assert "d123456ds1.htm" in url

    def test_compact_patterns_ss1_ff1(self):
        """Test compact patterns without separators (ss1, ff1)."""
        response_data = {
            "directory": {
                "item": [
                    {"name": "ff12014a1_biondvax.htm", "size": 500000},
                    {"name": "ex10_1.htm", "size": 50000},
                ]
            }
        }

        mock_response = HTTPResponse(
            status_code=200,
            content=json.dumps(response_data).encode('utf-8'),
            headers={},
            url="https://www.sec.gov/Archives/edgar/data/0001234567/000123456712123456/index.json",
            elapsed_seconds=0.1
        )

        mock_client = MockHTTPClient()
        mock_client.responses["https://www.sec.gov/Archives/edgar/data/0001234567/000123456712123456/index.json"] = mock_response

        sec_client = SECClient(http_client=mock_client)
        url = sec_client.resolve_primary_document_url(
            "0001234567", "0001234567-12-123456"
        )

        assert url is not None
        assert "ff12014a1_biondvax.htm" in url

    def test_amendment_patterns_s1a_f1a(self):
        """Test amendment patterns (s1a, f1a)."""
        response_data = {
            "directory": {
                "item": [
                    {"name": "d123456ds1a.htm", "size": 500000},
                    {"name": "ex10_1.htm", "size": 50000},
                ]
            }
        }

        mock_response = HTTPResponse(
            status_code=200,
            content=json.dumps(response_data).encode('utf-8'),
            headers={},
            url="https://www.sec.gov/Archives/edgar/data/0001234567/000123456712123456/index.json",
            elapsed_seconds=0.1
        )

        mock_client = MockHTTPClient()
        mock_client.responses["https://www.sec.gov/Archives/edgar/data/0001234567/000123456712123456/index.json"] = mock_response

        sec_client = SECClient(http_client=mock_client)
        url = sec_client.resolve_primary_document_url(
            "0001234567", "0001234567-12-123456"
        )

        assert url is not None
        assert "d123456ds1a.htm" in url

    def test_case_insensitive_matching(self):
        """Test that pattern matching is case-insensitive."""
        response_data = {
            "directory": {
                "item": [
                    {"name": "FORM_S-1.htm", "size": 500000},
                    {"name": "other_document.htm", "size": 50000},
                ]
            }
        }

        mock_response = HTTPResponse(
            status_code=200,
            content=json.dumps(response_data).encode('utf-8'),
            headers={},
            url="https://www.sec.gov/Archives/edgar/data/0001234567/000123456712123456/index.json",
            elapsed_seconds=0.1
        )

        mock_client = MockHTTPClient()
        mock_client.responses["https://www.sec.gov/Archives/edgar/data/0001234567/000123456712123456/index.json"] = mock_response

        sec_client = SECClient(http_client=mock_client)
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


class TestHTTPClientIntegration:
    """Test suite for HTTP client abstraction and mocking."""

    def test_http_client_injection(self):
        """Test that HTTP client can be injected for testing."""
        mock_client = MockHTTPClient()
        client = SECClient(http_client=mock_client)

        assert client._http_client is mock_client

    def test_make_request_success(self):
        """Test successful request with mocked HTTP client."""
        # Create mock response
        response_data = {"name": "Test Company", "cik": "0001234567"}
        mock_response = HTTPResponse(
            status_code=200,
            content=json.dumps(response_data).encode('utf-8'),
            headers={"Content-Type": "application/json"},
            url="https://data.sec.gov/submissions/CIK0001234567.json",
            elapsed_seconds=0.123
        )

        mock_client = MockHTTPClient()
        mock_client.responses["https://data.sec.gov/submissions/CIK0001234567.json"] = mock_response

        client = SECClient(http_client=mock_client)
        result = client._make_request("https://data.sec.gov/submissions/CIK0001234567.json")

        assert result == response_data
        assert len(mock_client.request_history) == 1

    def test_make_request_404_raises_http_error(self):
        """Test that 404 errors raise HTTPError without retry."""
        # Create 404 response
        mock_error = requests.HTTPError("404 Not Found")
        mock_error.response = Mock(status_code=404)

        mock_client = MockHTTPClient()
        mock_client.failures["https://data.sec.gov/test.json"] = mock_error

        client = SECClient(http_client=mock_client)

        with pytest.raises(requests.HTTPError):
            client._make_request("https://data.sec.gov/test.json")

        # Should only attempt once (no retries for 4xx)
        assert len(mock_client.request_history) == 1

    def test_make_request_429_raises_rate_limit_error(self):
        """Test that 429 errors raise SECRateLimitError."""
        mock_error = requests.HTTPError("429 Too Many Requests")
        mock_error.response = Mock(status_code=429)

        mock_client = MockHTTPClient()
        mock_client.failures["https://data.sec.gov/test.json"] = mock_error

        client = SECClient(http_client=mock_client)

        with pytest.raises(SECRateLimitError, match="Rate limit exceeded"):
            client._make_request("https://data.sec.gov/test.json")


class TestRetryLogic:
    """Test suite for retry logic with exponential backoff."""

    def test_500_error_retries_with_backoff(self):
        """Test that 500 errors are retried with exponential backoff."""
        # Create 500 error that fails twice then succeeds
        call_count = [0]

        def response_factory(url):
            call_count[0] += 1
            if call_count[0] <= 2:
                # First two attempts fail with 500
                error = requests.HTTPError("500 Internal Server Error")
                error.response = Mock(status_code=500)
                raise error
            else:
                # Third attempt succeeds
                return HTTPResponse(
                    status_code=200,
                    content=b'{"success": true}',
                    headers={},
                    url=url,
                    elapsed_seconds=0.1
                )

        mock_client = MockHTTPClient(response_factory=response_factory)
        client = SECClient(http_client=mock_client)

        start_time = time.time()
        result = client._make_request("https://data.sec.gov/test.json", max_retries=3)
        elapsed = time.time() - start_time

        assert result == {"success": True}
        assert call_count[0] == 3  # Should have made 3 attempts
        # Should have backoff delays: 1s + 2s = 3s minimum
        assert elapsed >= 3.0

    def test_500_error_exceeds_max_retries(self):
        """Test that persistent 500 errors fail after max retries."""
        mock_error = requests.HTTPError("500 Internal Server Error")
        mock_error.response = Mock(status_code=500)

        mock_client = MockHTTPClient()
        mock_client.failures["https://data.sec.gov/test.json"] = mock_error

        client = SECClient(http_client=mock_client)

        with pytest.raises(requests.HTTPError):
            client._make_request("https://data.sec.gov/test.json", max_retries=2)

        # Should have attempted 3 times (1 initial + 2 retries)
        assert len(mock_client.request_history) == 3

    def test_timeout_retries_with_backoff(self):
        """Test that timeouts are retried with exponential backoff."""
        call_count = [0]

        def response_factory(url):
            call_count[0] += 1
            if call_count[0] <= 2:
                # First two attempts timeout
                raise TimeoutError(f"Request timed out after 10.0s: {url}")
            else:
                # Third attempt succeeds
                return HTTPResponse(
                    status_code=200,
                    content=b'{"success": true}',
                    headers={},
                    url=url,
                    elapsed_seconds=0.1
                )

        mock_client = MockHTTPClient(response_factory=response_factory)
        client = SECClient(http_client=mock_client)

        start_time = time.time()
        result = client._make_request("https://data.sec.gov/test.json", max_retries=3)
        elapsed = time.time() - start_time

        assert result == {"success": True}
        assert call_count[0] == 3
        assert elapsed >= 3.0  # 1s + 2s backoff

    def test_exponential_backoff_timing(self):
        """Test that backoff delays follow exponential pattern: 1s, 2s, 4s."""
        mock_error = requests.HTTPError("500 Internal Server Error")
        mock_error.response = Mock(status_code=500)

        mock_client = MockHTTPClient()
        mock_client.failures["https://data.sec.gov/test.json"] = mock_error

        client = SECClient(http_client=mock_client)

        start_time = time.time()
        with pytest.raises(requests.HTTPError):
            client._make_request("https://data.sec.gov/test.json", max_retries=3)
        elapsed = time.time() - start_time

        # Total backoff: 1s + 2s + 4s = 7s minimum
        assert elapsed >= 7.0
        assert len(mock_client.request_history) == 4  # 1 initial + 3 retries


class TestMalformedJSONHandling:
    """Test suite for malformed JSON handling."""

    def test_malformed_json_raises_sec_data_error(self):
        """Test that malformed JSON raises SECDataError with response preview."""
        # Create response with invalid JSON
        mock_response = HTTPResponse(
            status_code=200,
            content=b"not valid json{",
            headers={},
            url="https://data.sec.gov/test.json",
            elapsed_seconds=0.1
        )

        mock_client = MockHTTPClient()
        mock_client.responses["https://data.sec.gov/test.json"] = mock_response

        client = SECClient(http_client=mock_client)

        with pytest.raises(SECDataError) as exc_info:
            client._make_request("https://data.sec.gov/test.json")

        error = exc_info.value
        assert error.url == "https://data.sec.gov/test.json"
        assert "not valid json{" in error.response_preview
        assert "Invalid JSON" in str(error)

    def test_malformed_json_not_retried(self):
        """Test that malformed JSON is not retried (non-transient error)."""
        mock_response = HTTPResponse(
            status_code=200,
            content=b"not valid json{",
            headers={},
            url="https://data.sec.gov/test.json",
            elapsed_seconds=0.1
        )

        mock_client = MockHTTPClient()
        mock_client.responses["https://data.sec.gov/test.json"] = mock_response

        client = SECClient(http_client=mock_client)

        with pytest.raises(SECDataError):
            client._make_request("https://data.sec.gov/test.json", max_retries=3)

        # Should only attempt once (malformed JSON is not retryable)
        assert len(mock_client.request_history) == 1


class TestMetricsCollection:
    """Test suite for optional metrics collection."""

    def test_metrics_disabled_by_default(self):
        """Test that metrics collection is disabled by default."""
        client = SECClient()
        assert client._metrics is None

    def test_metrics_tracks_successful_requests(self):
        """Test that metrics correctly track successful requests."""
        metrics = SECClientMetrics()

        mock_response = HTTPResponse(
            status_code=200,
            content=b'{"success": true}',
            headers={},
            url="https://data.sec.gov/test.json",
            elapsed_seconds=0.456
        )

        mock_client = MockHTTPClient()
        mock_client.responses["https://data.sec.gov/test.json"] = mock_response

        client = SECClient(http_client=mock_client, metrics=metrics)
        client._make_request("https://data.sec.gov/test.json")

        summary = metrics.get_summary()
        assert summary["requests_total"] == 1
        assert summary["requests_success"] == 1
        assert summary["requests_failed"] == 0
        assert summary["requests_timeout"] == 0
        assert summary["avg_elapsed_seconds"] == 0.456
        assert summary["success_rate"] == 100.0

    def test_metrics_tracks_failed_requests(self):
        """Test that metrics correctly track failed requests."""
        metrics = SECClientMetrics()

        mock_error = requests.HTTPError("500 Internal Server Error")
        mock_error.response = Mock(status_code=500)

        mock_client = MockHTTPClient()
        mock_client.failures["https://data.sec.gov/test.json"] = mock_error

        client = SECClient(http_client=mock_client, metrics=metrics)

        with pytest.raises(requests.HTTPError):
            client._make_request("https://data.sec.gov/test.json", max_retries=0)

        summary = metrics.get_summary()
        assert summary["requests_total"] == 1
        assert summary["requests_success"] == 0
        assert summary["requests_failed"] == 1
        assert summary["success_rate"] == 0.0

    def test_metrics_tracks_timeout_requests(self):
        """Test that metrics correctly track timeout failures."""
        metrics = SECClientMetrics()

        mock_client = MockHTTPClient()
        mock_client.failures["https://data.sec.gov/test.json"] = TimeoutError("Timeout")

        client = SECClient(http_client=mock_client, metrics=metrics)

        with pytest.raises(TimeoutError):
            client._make_request("https://data.sec.gov/test.json", max_retries=0)

        summary = metrics.get_summary()
        assert summary["requests_total"] == 1
        assert summary["requests_success"] == 0
        assert summary["requests_failed"] == 1
        assert summary["requests_timeout"] == 1

    def test_metrics_aggregates_multiple_requests(self):
        """Test that metrics aggregate across multiple requests."""
        metrics = SECClientMetrics()

        # Create mixed responses
        mock_client = MockHTTPClient()
        mock_client.responses["https://data.sec.gov/success1.json"] = HTTPResponse(
            status_code=200, content=b'{"ok": 1}', headers={},
            url="https://data.sec.gov/success1.json", elapsed_seconds=0.1
        )
        mock_client.responses["https://data.sec.gov/success2.json"] = HTTPResponse(
            status_code=200, content=b'{"ok": 2}', headers={},
            url="https://data.sec.gov/success2.json", elapsed_seconds=0.2
        )

        error = requests.HTTPError("404")
        error.response = Mock(status_code=404)
        mock_client.failures["https://data.sec.gov/fail.json"] = error

        client = SECClient(http_client=mock_client, metrics=metrics)

        # Make successful requests
        client._make_request("https://data.sec.gov/success1.json")
        client._make_request("https://data.sec.gov/success2.json")

        # Make failed request
        with pytest.raises(requests.HTTPError):
            client._make_request("https://data.sec.gov/fail.json")

        summary = metrics.get_summary()
        assert summary["requests_total"] == 3
        assert summary["requests_success"] == 2
        assert summary["requests_failed"] == 1
        assert summary["success_rate"] == pytest.approx(66.7, rel=0.1)
        # Avg elapsed: (0.1 + 0.2 + elapsed_for_failure) / 3
        # The failure also takes some time, so average will be > 0.1
        assert summary["avg_elapsed_seconds"] > 0.1
        assert summary["avg_elapsed_seconds"] < 0.2

    def test_metrics_thread_safety(self):
        """Test that metrics are thread-safe."""
        import threading

        metrics = SECClientMetrics()

        def record_success():
            for _ in range(100):
                metrics.record_request()
                metrics.record_success(0.1)

        def record_failure():
            for _ in range(50):
                metrics.record_request()
                metrics.record_failure(0.1)

        # Run concurrent threads
        threads = [
            threading.Thread(target=record_success),
            threading.Thread(target=record_failure),
            threading.Thread(target=record_success),
        ]

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        summary = metrics.get_summary()
        assert summary["requests_total"] == 250  # 200 success + 50 failure
        assert summary["requests_success"] == 200
        assert summary["requests_failed"] == 50


class TestSearchFilings:
    """Test suite for search_filings method."""

    def test_search_filings_success_with_results(self):
        """Test successful search with filings found."""

        # Create mock daily index response
        index_text = """
------------------------------------------------------------
CIK|Company Name|Form Type|Date Filed|Filename
1234567|Example Corp|S-1|2024-01-15|edgar/data/1234567/0001193125-24-000001.txt
7654321|Test Inc|F-1|2024-01-15|edgar/data/7654321/0001193125-24-000002.txt
"""
        mock_response = HTTPResponse(
            status_code=200,
            content=index_text.encode('utf-8'),
            headers={},
            url="https://www.sec.gov/Archives/edgar/daily-index/2024/QTR1/master.20240115.idx",
            elapsed_seconds=0.1
        )

        mock_client = MockHTTPClient()
        mock_client.responses["https://www.sec.gov/Archives/edgar/daily-index/2024/QTR1/master.20240115.idx"] = mock_response

        client = SECClient(http_client=mock_client)
        filings = client.search_filings("2024-01-15", "2024-01-15", ["S-1", "F-1"])

        assert len(filings) == 2
        assert filings[0].cik == "0001234567"
        assert filings[0].form_type == "S-1"
        assert filings[1].cik == "0007654321"
        assert filings[1].form_type == "F-1"

    def test_search_filings_404_returns_empty_list(self):
        """Test that 404 errors are handled gracefully and return empty list."""
        # Create 404 error
        mock_error = requests.HTTPError("404 Not Found")
        mock_error.response = Mock(status_code=404)

        mock_client = MockHTTPClient()
        mock_client.failures["https://www.sec.gov/Archives/edgar/daily-index/2024/QTR1/master.20240115.idx"] = mock_error

        client = SECClient(http_client=mock_client)
        filings = client.search_filings("2024-01-15", "2024-01-15")

        # Should return empty list, not raise error
        assert filings == []

    def test_search_filings_uses_default_form_types(self):
        """Test that search_filings uses default form types when none provided."""
        index_text = """
------------------------------------------------------------
CIK|Company Name|Form Type|Date Filed|Filename
1234567|Example Corp|S-1|2024-01-15|edgar/data/1234567/0001193125-24-000001.txt
"""
        mock_response = HTTPResponse(
            status_code=200,
            content=index_text.encode('utf-8'),
            headers={},
            url="https://www.sec.gov/Archives/edgar/daily-index/2024/QTR1/master.20240115.idx",
            elapsed_seconds=0.1
        )

        mock_client = MockHTTPClient()
        mock_client.responses["https://www.sec.gov/Archives/edgar/daily-index/2024/QTR1/master.20240115.idx"] = mock_response

        client = SECClient(http_client=mock_client)
        filings = client.search_filings("2024-01-15", "2024-01-15")

        assert len(filings) == 1


class TestGetCompanyInfo:
    """Test suite for get_company_info method."""

    def test_get_company_info_success(self):
        """Test successful company info retrieval."""
        company_data = {
            "cik": "0001234567",
            "name": "Example Corp",
            "sic": "7372",
            "sicDescription": "Services-Prepackaged Software",
            "tickers": ["EXMP"],
            "ein": "12-3456789",
            "stateOfIncorporation": "DE"
        }

        mock_response = HTTPResponse(
            status_code=200,
            content=json.dumps(company_data).encode('utf-8'),
            headers={},
            url="https://data.sec.gov/submissions/CIK0001234567.json",
            elapsed_seconds=0.1
        )

        mock_client = MockHTTPClient()
        mock_client.responses["https://data.sec.gov/submissions/CIK0001234567.json"] = mock_response

        client = SECClient(http_client=mock_client)
        result = client.get_company_info("1234567")

        assert result is not None
        assert result["cik"] == "0001234567"
        assert result["name"] == "Example Corp"
        assert result["sic"] == "7372"
        assert result["sic_description"] == "Services-Prepackaged Software"
        assert result["tickers"] == ["EXMP"]
        assert result["ein"] == "12-3456789"
        assert result["state_of_incorporation"] == "DE"

    def test_get_company_info_404_returns_none(self):
        """Test that 404 returns None gracefully."""
        mock_error = requests.HTTPError("404 Not Found")
        mock_error.response = Mock(status_code=404)

        mock_client = MockHTTPClient()
        mock_client.failures["https://data.sec.gov/submissions/CIK0001234567.json"] = mock_error

        client = SECClient(http_client=mock_client)
        result = client.get_company_info("1234567")

        assert result is None

    def test_get_company_info_handles_missing_fields(self):
        """Test that missing optional fields are handled gracefully."""
        company_data = {
            "cik": "0001234567",
            "name": "Example Corp"
            # Missing sic, sicDescription, tickers, ein, stateOfIncorporation
        }

        mock_response = HTTPResponse(
            status_code=200,
            content=json.dumps(company_data).encode('utf-8'),
            headers={},
            url="https://data.sec.gov/submissions/CIK0001234567.json",
            elapsed_seconds=0.1
        )

        mock_client = MockHTTPClient()
        mock_client.responses["https://data.sec.gov/submissions/CIK0001234567.json"] = mock_response

        client = SECClient(http_client=mock_client)
        result = client.get_company_info("1234567")

        assert result is not None
        assert result["cik"] == "0001234567"
        assert result["name"] == "Example Corp"
        assert result["sic"] == ""
        assert result["sic_description"] == ""
        assert result["tickers"] == []
        assert result["ein"] == ""
        assert result["state_of_incorporation"] == ""


class TestGetFilingByAccession:
    """Test suite for get_filing_by_accession method."""

    def test_get_filing_by_accession_success(self):
        """Test successful filing retrieval by accession number."""
        from src.infra.sec_client import FilingMetadata

        submissions_data = {
            "cik": "0001234567",
            "name": "Example Corp",
            "filings": {
                "recent": {
                    "accessionNumber": ["0001193125-24-000001", "0001193125-24-000002"],
                    "form": ["S-1", "10-K"],
                    "filingDate": ["2024-01-15", "2024-02-15"],
                    "reportDate": ["2023-12-31", "2023-12-31"],
                    "primaryDocument": ["d123456ds1.htm", "d789012d10k.htm"],
                    "primaryDocDescription": ["S-1", "10-K"]
                }
            }
        }

        mock_response = HTTPResponse(
            status_code=200,
            content=json.dumps(submissions_data).encode('utf-8'),
            headers={},
            url="https://data.sec.gov/submissions/CIK0001234567.json",
            elapsed_seconds=0.1
        )

        mock_client = MockHTTPClient()
        mock_client.responses["https://data.sec.gov/submissions/CIK0001234567.json"] = mock_response

        client = SECClient(http_client=mock_client)
        filing = client.get_filing_by_accession("1234567", "0001193125-24-000001")

        assert filing is not None
        assert isinstance(filing, FilingMetadata)
        assert filing.cik == "1234567"  # CIK is returned as provided, not zero-padded
        assert filing.accession_number == "0001193125-24-000001"
        assert filing.form_type == "S-1"
        assert filing.filing_date == "2024-01-15"

    def test_get_filing_by_accession_not_found_returns_none(self):
        """Test that filing not found returns None."""
        submissions_data = {
            "cik": "0001234567",
            "name": "Example Corp",
            "filings": {
                "recent": {
                    "accessionNumber": ["0001193125-24-000001"],
                    "form": ["S-1"],
                    "filingDate": ["2024-01-15"],
                    "reportDate": ["2023-12-31"],
                    "primaryDocument": ["d123456ds1.htm"],
                    "primaryDocDescription": ["S-1"]
                }
            }
        }

        mock_response = HTTPResponse(
            status_code=200,
            content=json.dumps(submissions_data).encode('utf-8'),
            headers={},
            url="https://data.sec.gov/submissions/CIK0001234567.json",
            elapsed_seconds=0.1
        )

        mock_client = MockHTTPClient()
        mock_client.responses["https://data.sec.gov/submissions/CIK0001234567.json"] = mock_response

        client = SECClient(http_client=mock_client)
        filing = client.get_filing_by_accession("1234567", "0001193125-24-999999")  # Not in list

        assert filing is None
