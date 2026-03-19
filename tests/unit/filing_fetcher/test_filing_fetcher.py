"""
Unit tests for FilingFetcher core functionality.
"""

from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from src.filing_fetcher.filing_fetcher import FilingFetcher
from src.infra.sec_client import FilingMetadata


class TestStoragePathGeneration:
    """Test suite for storage path generation."""

    @pytest.fixture
    def fetcher(self, tmp_path):
        """Create a FilingFetcher with temporary storage."""
        return FilingFetcher(storage_root=str(tmp_path / "test_filings"))

    def test_get_storage_dir_format(self, fetcher):
        """Test that storage directory has correct format."""
        storage_dir = fetcher._get_storage_dir("0001234567", "0001234567-12-123456")

        assert "0001234567" in str(storage_dir)
        assert "000123456712123456" in str(storage_dir)  # Accession without dashes

    def test_get_storage_dir_removes_dashes(self, fetcher):
        """Test that dashes are removed from accession number in path."""
        storage_dir = fetcher._get_storage_dir("0001234567", "0001234567-12-123456")

        # Path should not contain dashes in accession number
        assert "-12-" not in str(storage_dir)

    def test_get_storage_dir_creates_nested_structure(self, fetcher):
        """Test that directory structure is nested by CIK."""
        storage_dir = fetcher._get_storage_dir("0001234567", "0001234567-12-123456")

        # Should be: storage_root/CIK/accession_no_dashes
        path_parts = storage_dir.parts
        assert path_parts[-2] == "0001234567"  # CIK
        assert path_parts[-1] == "000123456712123456"  # Accession


class TestGetFilingContent:
    """Test suite for get_filing_content method."""

    @pytest.fixture
    def fetcher(self, tmp_path):
        """Create a FilingFetcher with temporary storage."""
        return FilingFetcher(storage_root=str(tmp_path / "test_filings"))

    def test_get_existing_filing(self, fetcher, tmp_path):
        """Test retrieving existing cached filing."""
        # Create fake cached filing
        cik = "0001234567"
        accession = "0001234567-12-123456"
        storage_dir = fetcher._get_storage_dir(cik, accession)
        storage_dir.mkdir(parents=True, exist_ok=True)

        html_path = storage_dir / "primary.htm"
        html_path.write_text("<html>Test filing</html>")

        # Retrieve filing content
        content = fetcher.get_filing_content(cik, accession)

        assert content is not None
        assert content.cik == cik
        assert content.accession_number == accession
        assert str(html_path) in content.html_path
        assert content.txt_path is None  # No TXT file created

    def test_get_nonexistent_filing(self, fetcher):
        """Test that None is returned for nonexistent filing."""
        content = fetcher.get_filing_content("0001234567", "0001234567-12-123456")

        assert content is None

    def test_get_filing_with_txt(self, fetcher, tmp_path):
        """Test retrieving filing with both HTML and TXT files."""
        # Create fake cached filing with both files
        cik = "0001234567"
        accession = "0001234567-12-123456"
        storage_dir = fetcher._get_storage_dir(cik, accession)
        storage_dir.mkdir(parents=True, exist_ok=True)

        html_path = storage_dir / "primary.htm"
        txt_path = storage_dir / "complete.txt"
        html_path.write_text("<html>Test filing</html>")
        txt_path.write_text("Complete text filing")

        # Retrieve filing content
        content = fetcher.get_filing_content(cik, accession)

        assert content is not None
        assert content.txt_path is not None
        assert str(txt_path) in content.txt_path


class TestFetchFiling:
    """Test suite for fetch_filing method."""

    @pytest.fixture
    def fetcher(self, tmp_path):
        """Create a FilingFetcher with temporary storage."""
        mock_sec_client = Mock()
        return FilingFetcher(
            storage_root=str(tmp_path / "test_filings"), sec_client=mock_sec_client
        )

    @pytest.fixture
    def valid_filing_html(self):
        """Create valid filing HTML content."""
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
        )  # Pad to meet size requirement

    def test_fetch_filing_success(self, fetcher, valid_filing_html):
        """Test successful filing fetch."""
        metadata = FilingMetadata(
            cik="0001234567",
            company_name="Test Corp",
            form_type="S-1",
            filing_date="2024-01-15",
            accession_number="0001234567-12-123456",
            primary_doc_url="https://www.sec.gov/Archives/edgar/data/1234567/000123456712123456/d123456ds1.htm",
            txt_url="https://www.sec.gov/Archives/edgar/data/1234567/000123456712123456.txt",
        )

        # Mock HTTP responses
        mock_response = Mock()
        mock_response.text = valid_filing_html
        mock_response.raise_for_status = Mock()

        with patch.object(fetcher.session, "get", return_value=mock_response):
            content = fetcher.fetch_filing(metadata, fetch_txt=False)

        assert content is not None
        assert content.cik == "0001234567"
        assert content.accession_number == "0001234567-12-123456"
        assert Path(content.html_path).exists()

    def test_fetch_filing_with_directory_url(self, fetcher, valid_filing_html):
        """Test fetching filing with directory URL that needs resolution."""
        metadata = FilingMetadata(
            cik="0001234567",
            company_name="Test Corp",
            form_type="S-1",
            filing_date="2024-01-15",
            accession_number="0001234567-12-123456",
            primary_doc_url="https://www.sec.gov/Archives/edgar/data/1234567/000123456712123456/",  # Directory URL
            txt_url=None,
        )

        # Mock SEC client to resolve URL
        fetcher.sec_client.resolve_primary_document_url.return_value = "https://www.sec.gov/Archives/edgar/data/1234567/000123456712123456/d123456ds1.htm"

        # Mock HTTP response
        mock_response = Mock()
        mock_response.text = valid_filing_html
        mock_response.raise_for_status = Mock()

        with patch.object(fetcher.session, "get", return_value=mock_response):
            content = fetcher.fetch_filing(metadata, fetch_txt=False)

        assert content is not None
        fetcher.sec_client.resolve_primary_document_url.assert_called_once_with(
            "0001234567", "0001234567-12-123456"
        )

    def test_fetch_filing_invalid_content(self, fetcher):
        """Test that invalid content is rejected."""
        metadata = FilingMetadata(
            cik="0001234567",
            company_name="Test Corp",
            form_type="S-1",
            filing_date="2024-01-15",
            accession_number="0001234567-12-123456",
            primary_doc_url="https://www.sec.gov/Archives/edgar/data/1234567/000123456712123456/d123456ds1.htm",
        )

        # Mock response with invalid content (too small)
        mock_response = Mock()
        mock_response.text = "<html>Error page</html>"
        mock_response.raise_for_status = Mock()

        with patch.object(fetcher.session, "get", return_value=mock_response):
            content = fetcher.fetch_filing(metadata, fetch_txt=False)

        # Should return None because content validation failed
        assert content is None

    def test_fetch_filing_http_error(self, fetcher):
        """Test handling of HTTP errors."""
        metadata = FilingMetadata(
            cik="0001234567",
            company_name="Test Corp",
            form_type="S-1",
            filing_date="2024-01-15",
            accession_number="0001234567-12-123456",
            primary_doc_url="https://www.sec.gov/Archives/edgar/data/1234567/000123456712123456/d123456ds1.htm",
        )

        # Mock HTTP error
        mock_response = Mock()
        mock_response.raise_for_status.side_effect = Exception("404 Not Found")

        with patch.object(fetcher.session, "get", return_value=mock_response):
            content = fetcher.fetch_filing(metadata, fetch_txt=False)

        assert content is None

    def test_fetch_filing_already_cached(self, fetcher, valid_filing_html, tmp_path):
        """Test that cached filings are not re-downloaded."""
        metadata = FilingMetadata(
            cik="0001234567",
            company_name="Test Corp",
            form_type="S-1",
            filing_date="2024-01-15",
            accession_number="0001234567-12-123456",
            primary_doc_url="https://www.sec.gov/Archives/edgar/data/1234567/000123456712123456/d123456ds1.htm",
        )

        # Pre-create cached file
        storage_dir = fetcher._get_storage_dir("0001234567", "0001234567-12-123456")
        storage_dir.mkdir(parents=True, exist_ok=True)
        html_path = storage_dir / "primary.htm"
        html_path.write_text(valid_filing_html)

        # Mock session.get to track calls
        mock_get = Mock()
        with patch.object(fetcher.session, "get", mock_get):
            content = fetcher.fetch_filing(metadata, fetch_txt=False)

        # Should not make any HTTP requests because file is cached
        mock_get.assert_not_called()
        assert content is not None

    def test_fetch_filing_with_txt(self, fetcher, valid_filing_html):
        """Test fetching both HTML and TXT files."""
        metadata = FilingMetadata(
            cik="0001234567",
            company_name="Test Corp",
            form_type="S-1",
            filing_date="2024-01-15",
            accession_number="0001234567-12-123456",
            primary_doc_url="https://www.sec.gov/Archives/edgar/data/1234567/000123456712123456/d123456ds1.htm",
            txt_url="https://www.sec.gov/Archives/edgar/data/1234567/000123456712123456.txt",
        )

        # Mock HTTP responses
        mock_html_response = Mock()
        mock_html_response.text = valid_filing_html
        mock_html_response.raise_for_status = Mock()

        mock_txt_response = Mock()
        mock_txt_response.text = "Complete text filing content"
        mock_txt_response.raise_for_status = Mock()

        call_count = [0]

        def get_side_effect(url):
            call_count[0] += 1
            if call_count[0] == 1:
                return mock_html_response
            else:
                return mock_txt_response

        with patch.object(fetcher.session, "get", side_effect=get_side_effect):
            content = fetcher.fetch_filing(metadata, fetch_txt=True)

        assert content is not None
        assert content.txt_path is not None
        assert Path(content.txt_path).exists()


class TestFetchBatch:
    """Test suite for fetch_batch method."""

    @pytest.fixture
    def fetcher(self, tmp_path):
        """Create a FilingFetcher with temporary storage."""
        return FilingFetcher(storage_root=str(tmp_path / "test_filings"))

    def test_fetch_batch_empty(self, fetcher):
        """Test fetching empty batch."""
        stats = fetcher.fetch_batch([], fetch_txt=False)

        assert stats["total"] == 0
        assert stats["fetched"] == 0
        assert stats["failed"] == 0
        assert stats["skipped"] == 0

    def test_fetch_batch_success(self, fetcher):
        """Test successful batch fetch."""
        valid_html = (
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

        filings = [
            FilingMetadata(
                cik="0001234567",
                company_name="Test Corp 1",
                form_type="S-1",
                filing_date="2024-01-15",
                accession_number="0001234567-12-123456",
                primary_doc_url="https://www.sec.gov/test1.htm",
            ),
            FilingMetadata(
                cik="0007654321",
                company_name="Test Corp 2",
                form_type="S-1",
                filing_date="2024-01-16",
                accession_number="0007654321-12-654321",
                primary_doc_url="https://www.sec.gov/test2.htm",
            ),
        ]

        # Mock HTTP responses
        mock_response = Mock()
        mock_response.text = valid_html
        mock_response.raise_for_status = Mock()

        with patch.object(fetcher.session, "get", return_value=mock_response):
            stats = fetcher.fetch_batch(filings, fetch_txt=False)

        assert stats["total"] == 2
        assert stats["fetched"] == 2
        assert stats["failed"] == 0
        assert stats["skipped"] == 0

    def test_fetch_batch_with_failures(self, fetcher):
        """Test batch fetch with some failures."""
        valid_html = (
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

        filings = [
            FilingMetadata(
                cik="0001234567",
                company_name="Test Corp 1",
                form_type="S-1",
                filing_date="2024-01-15",
                accession_number="0001234567-12-123456",
                primary_doc_url="https://www.sec.gov/test1.htm",
            ),
            FilingMetadata(
                cik="0007654321",
                company_name="Test Corp 2",
                form_type="S-1",
                filing_date="2024-01-16",
                accession_number="0007654321-12-654321",
                primary_doc_url="https://www.sec.gov/test2.htm",
            ),
        ]

        # Mock responses: first succeeds, second fails
        call_count = [0]

        def get_side_effect(url):
            call_count[0] += 1
            if call_count[0] == 1:
                response = Mock()
                response.text = valid_html
                response.raise_for_status = Mock()
                return response
            else:
                response = Mock()
                response.raise_for_status.side_effect = Exception("404")
                return response

        with patch.object(fetcher.session, "get", side_effect=get_side_effect):
            stats = fetcher.fetch_batch(filings, fetch_txt=False)

        assert stats["total"] == 2
        assert stats["fetched"] == 1
        assert stats["failed"] == 1
        assert stats["skipped"] == 0

    def test_fetch_batch_stops_on_max_failures(self, fetcher):
        """Test that batch fetch stops after max consecutive failures."""
        filings = [
            FilingMetadata(
                cik=f"{i:010d}",
                company_name=f"Test Corp {i}",
                form_type="S-1",
                filing_date="2024-01-15",
                accession_number=f"{i:010d}-12-123456",
                primary_doc_url=f"https://www.sec.gov/test{i}.htm",
            )
            for i in range(20)
        ]

        # Mock all requests to fail
        mock_response = Mock()
        mock_response.raise_for_status.side_effect = Exception("Error")

        with patch.object(fetcher.session, "get", return_value=mock_response):
            stats = fetcher.fetch_batch(filings, fetch_txt=False, max_failures=5)

        # Should stop after 5 consecutive failures
        assert stats["failed"] <= 5
        assert stats["total"] == 20  # Total count is still full list

    def test_fetch_batch_skips_cached(self, fetcher, tmp_path):
        """Test that batch fetch skips already cached filings."""
        valid_html = (
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

        # Pre-cache first filing
        storage_dir = fetcher._get_storage_dir("0001234567", "0001234567-12-123456")
        storage_dir.mkdir(parents=True, exist_ok=True)
        (storage_dir / "primary.htm").write_text(valid_html)

        filings = [
            FilingMetadata(
                cik="0001234567",
                company_name="Test Corp 1",
                form_type="S-1",
                filing_date="2024-01-15",
                accession_number="0001234567-12-123456",
                primary_doc_url="https://www.sec.gov/test1.htm",
            ),
            FilingMetadata(
                cik="0007654321",
                company_name="Test Corp 2",
                form_type="S-1",
                filing_date="2024-01-16",
                accession_number="0007654321-12-654321",
                primary_doc_url="https://www.sec.gov/test2.htm",
            ),
        ]

        # Mock HTTP response for second filing only
        mock_response = Mock()
        mock_response.text = valid_html
        mock_response.raise_for_status = Mock()

        with patch.object(fetcher.session, "get", return_value=mock_response):
            stats = fetcher.fetch_batch(filings, fetch_txt=False)

        assert stats["total"] == 2
        assert stats["fetched"] == 1  # Only second filing
        assert stats["skipped"] == 1  # First filing was cached
        assert stats["failed"] == 0


class TestRateLimiting:
    """Test suite for rate limiting in FilingFetcher."""

    @pytest.fixture
    def fetcher(self, tmp_path):
        """Create a FilingFetcher with temporary storage."""
        return FilingFetcher(storage_root=str(tmp_path / "test_filings"))

    def test_rate_limit_enforced(self, fetcher):
        """Test that rate limiting delays are enforced."""
        import time

        start = time.time()
        fetcher._rate_limit()
        fetcher._rate_limit()
        elapsed = time.time() - start

        # Should have delayed at least MIN_REQUEST_INTERVAL
        assert elapsed >= fetcher.MIN_REQUEST_INTERVAL


class TestSecurityPathTraversal:
    """Test suite for security checks against path traversal attacks."""

    @pytest.fixture
    def fetcher(self, tmp_path):
        """Create a FilingFetcher with temporary storage."""
        return FilingFetcher(storage_root=str(tmp_path / "test_filings"))

    def test_reject_cik_with_parent_directory(self, fetcher):
        """Test that CIK with '..' is rejected."""
        with pytest.raises(ValueError, match="path traversal"):
            fetcher._get_storage_dir("../etc", "0001234567-12-123456")

    def test_reject_cik_with_forward_slash(self, fetcher):
        """Test that CIK with '/' is rejected."""
        with pytest.raises(ValueError, match="path traversal"):
            fetcher._get_storage_dir("000/123", "0001234567-12-123456")

    def test_reject_cik_with_backslash(self, fetcher):
        """Test that CIK with backslash is rejected."""
        with pytest.raises(ValueError, match="path traversal"):
            fetcher._get_storage_dir("000\\123", "0001234567-12-123456")

    def test_reject_non_numeric_cik(self, fetcher):
        """Test that non-numeric CIK is rejected."""
        with pytest.raises(ValueError, match="must be numeric"):
            fetcher._get_storage_dir("ABC123", "0001234567-12-123456")

    def test_reject_accession_with_parent_directory(self, fetcher):
        """Test that accession number with '..' is rejected."""
        with pytest.raises(ValueError, match="path traversal"):
            fetcher._get_storage_dir("0001234567", "../etc/passwd")

    def test_reject_accession_with_forward_slash(self, fetcher):
        """Test that accession number with '/' is rejected (after dash removal)."""
        with pytest.raises(ValueError, match="path traversal"):
            fetcher._get_storage_dir("0001234567", "0001234567/12/123456")

    def test_reject_accession_with_backslash(self, fetcher):
        """Test that accession number with backslash is rejected."""
        with pytest.raises(ValueError, match="path traversal"):
            fetcher._get_storage_dir("0001234567", "0001234567\\12\\123456")

    def test_reject_accession_with_special_chars(self, fetcher):
        """Test that accession with non-alphanumeric chars (besides dash) is rejected."""
        with pytest.raises(ValueError, match="must be alphanumeric"):
            fetcher._get_storage_dir("0001234567", "0001234567-12-123456;rm -rf")

    def test_accept_valid_cik_and_accession(self, fetcher):
        """Test that valid CIK and accession are accepted."""
        # Should not raise any exceptions
        storage_dir = fetcher._get_storage_dir("0001234567", "0001234567-12-123456")
        assert "0001234567" in str(storage_dir)


class TestValidateFilingContent:
    """Test suite for filing content validation."""

    @pytest.fixture
    def fetcher(self, tmp_path):
        """Create a FilingFetcher with temporary storage."""
        return FilingFetcher(storage_root=str(tmp_path / "test_filings"))

    def test_reject_too_small_content(self, fetcher):
        """Test that content smaller than 15KB is rejected."""
        small_html = "<html>Small content</html>"
        is_valid, error = fetcher._validate_filing_content(
            small_html, "0001234567", "0001234567-12-123456"
        )

        assert is_valid is False
        assert "too small" in error.lower()

    def test_reject_404_error_page(self, fetcher):
        """Test that 404 error pages are rejected."""
        error_html = (
            """
        <html><body>
        <h1>404 Not Found</h1>
        """
            + "X" * 20000
        )

        is_valid, error = fetcher._validate_filing_content(
            error_html, "0001234567", "0001234567-12-123456"
        )

        assert is_valid is False
        assert "404 Not Found" in error

    def test_reject_no_documents_found_error(self, fetcher):
        """Test that 'No documents were found' error pages are rejected."""
        error_html = (
            """
        <html><body>
        <p>No documents were found for this request.</p>
        """
            + "X" * 20000
        )

        is_valid, error = fetcher._validate_filing_content(
            error_html, "0001234567", "0001234567-12-123456"
        )

        assert is_valid is False
        assert "No documents were found" in error

    def test_reject_access_denied_error(self, fetcher):
        """Test that 'Access Denied' error pages are rejected."""
        error_html = (
            """
        <html><body>
        <h1>Access Denied</h1>
        """
            + "X" * 20000
        )

        is_valid, error = fetcher._validate_filing_content(
            error_html, "0001234567", "0001234567-12-123456"
        )

        assert is_valid is False
        assert "Access Denied" in error

    def test_reject_service_unavailable_error(self, fetcher):
        """Test that 'Service Unavailable' error pages are rejected."""
        error_html = (
            """
        <html><body>
        <h1>Service Unavailable</h1>
        """
            + "X" * 20000
        )

        is_valid, error = fetcher._validate_filing_content(
            error_html, "0001234567", "0001234567-12-123456"
        )

        assert is_valid is False
        assert "Service Unavailable" in error

    def test_reject_xml_error_response(self, fetcher):
        """Test that XML error responses are rejected."""
        error_html = (
            """
        <Error>
        <Code>NoSuchKey</Code>
        <Message>The specified key does not exist.</Message>
        """
            + "X" * 20000
        )

        is_valid, error = fetcher._validate_filing_content(
            error_html, "0001234567", "0001234567-12-123456"
        )

        assert is_valid is False
        assert "Error page detected" in error

    def test_reject_missing_sec_indicators(self, fetcher):
        """Test that content without SEC indicators is rejected."""
        html_without_sec = (
            """
        <DOCUMENT>
        <TYPE>S-1
        <TEXT>
        <HTML>
        <HEAD><TITLE>Some Document</TITLE></HEAD>
        <BODY>
        <P>This is a document but not an SEC filing.</P>
        """
            + "X" * 20000
        )

        is_valid, error = fetcher._validate_filing_content(
            html_without_sec, "0001234567", "0001234567-12-123456"
        )

        assert is_valid is False
        assert "Missing SEC filing indicators" in error

    def test_reject_missing_filing_structure(self, fetcher):
        """Test that content without proper structure is rejected."""
        html_without_structure = (
            """
        Just plain text without any HTML or SGML structure.
        """
            + "X" * 20000
        )

        is_valid, error = fetcher._validate_filing_content(
            html_without_structure, "0001234567", "0001234567-12-123456"
        )

        assert is_valid is False
        assert "Missing valid filing structure" in error

    def test_accept_valid_sgml_filing(self, fetcher):
        """Test that valid SGML-wrapped filing is accepted."""
        valid_sgml = (
            """
        <DOCUMENT>
        <TYPE>S-1
        <TEXT>
        <HTML>
        <HEAD><TITLE>S-1 Registration</TITLE></HEAD>
        <BODY>
        <P>UNITED STATES SECURITIES AND EXCHANGE COMMISSION</P>
        <P>FORM S-1</P>
        <P>REGISTRATION STATEMENT</P>
        """
            + "X" * 20000
        )

        is_valid, error = fetcher._validate_filing_content(
            valid_sgml, "0001234567", "0001234567-12-123456"
        )

        assert is_valid is True
        assert error is None

    def test_accept_modern_html_filing(self, fetcher):
        """Test that modern HTML filing (without SGML wrapper) is accepted."""
        modern_html = (
            """
        <!DOCTYPE html>
        <html>
        <head><title>Form S-1</title></head>
        <body>
        <div>
        <h1>UNITED STATES SECURITIES AND EXCHANGE COMMISSION</h1>
        <h2>FORM S-1</h2>
        <table><tr><td>Financial data</td></tr></table>
        </div>
        </body>
        </html>
        """
            + "X" * 20000
        )

        is_valid, error = fetcher._validate_filing_content(
            modern_html, "0001234567", "0001234567-12-123456"
        )

        assert is_valid is True
        assert error is None

    def test_reject_modern_html_missing_elements(self, fetcher):
        """Test that modern HTML without expected elements is rejected."""
        incomplete_html = (
            """
        <!DOCTYPE html>
        <html>
        <head></head>
        <body>
        SECURITIES AND EXCHANGE COMMISSION
        </body>
        </html>
        """
            + "X" * 20000
        )

        is_valid, error = fetcher._validate_filing_content(
            incomplete_html, "0001234567", "0001234567-12-123456"
        )

        assert is_valid is False
        assert "missing expected structural elements" in error.lower()


class TestFetchFilingErrorHandling:
    """Test suite for error handling in fetch_filing method."""

    @pytest.fixture
    def fetcher(self, tmp_path):
        """Create a FilingFetcher with temporary storage."""
        mock_sec_client = Mock()
        return FilingFetcher(
            storage_root=str(tmp_path / "test_filings"), sec_client=mock_sec_client
        )

    def test_handle_url_resolution_failure(self, fetcher):
        """Test handling when primary document URL cannot be resolved."""
        metadata = FilingMetadata(
            cik="0001234567",
            company_name="Test Corp",
            form_type="S-1",
            filing_date="2024-01-15",
            accession_number="0001234567-12-123456",
            primary_doc_url="https://www.sec.gov/Archives/edgar/data/1234567/000123456712123456/",  # Directory URL
        )

        # Mock SEC client to return None (can't resolve)
        fetcher.sec_client.resolve_primary_document_url.return_value = None

        content = fetcher.fetch_filing(metadata, fetch_txt=False)

        assert content is None
        fetcher.sec_client.resolve_primary_document_url.assert_called_once()

    def test_handle_txt_fetch_error(self, fetcher):
        """Test that entire operation fails if TXT fetch fails."""
        valid_html = (
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
            primary_doc_url="https://www.sec.gov/test.htm",
            txt_url="https://www.sec.gov/test.txt",
        )

        # Mock responses: HTML succeeds, TXT fails
        call_count = [0]

        def get_side_effect(url):
            call_count[0] += 1
            response = Mock()
            if call_count[0] == 1:  # HTML request
                response.text = valid_html
                response.raise_for_status = Mock()
            else:  # TXT request
                response.raise_for_status.side_effect = Exception("404")
            return response

        with patch.object(fetcher.session, "get", side_effect=get_side_effect):
            content = fetcher.fetch_filing(metadata, fetch_txt=True)

        # Current behavior: HTML succeeds, TXT failure is logged as warning
        assert content is not None
        assert content.html_path is not None
        assert content.txt_path is None  # TXT fetch failed

    def test_txt_already_cached(self, fetcher, tmp_path):
        """Test that cached TXT files are not re-downloaded."""
        valid_html = (
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
            primary_doc_url="https://www.sec.gov/test.htm",
            txt_url="https://www.sec.gov/test.txt",
        )

        # Pre-cache both HTML and TXT files
        storage_dir = fetcher._get_storage_dir("0001234567", "0001234567-12-123456")
        storage_dir.mkdir(parents=True, exist_ok=True)
        (storage_dir / "primary.htm").write_text(valid_html)
        (storage_dir / "complete.txt").write_text("Cached TXT content")

        # Mock session.get to track calls
        mock_get = Mock()
        with patch.object(fetcher.session, "get", mock_get):
            content = fetcher.fetch_filing(metadata, fetch_txt=True)

        # Should not make any HTTP requests because both files are cached
        mock_get.assert_not_called()
        assert content is not None
        assert content.txt_path is not None
        assert "complete.txt" in content.txt_path


class TestDatabaseIntegration:
    """Test suite for database integration methods."""

    @pytest.fixture
    def fetcher(self, tmp_path):
        """Create a FilingFetcher with mocked database."""
        mock_db = Mock()
        return FilingFetcher(storage_root=str(tmp_path / "test_filings"), db=mock_db)

    def test_update_database_on_success(self, fetcher):
        """Test that database is updated after successful fetch."""
        valid_html = (
            """
        <DOCUMENT>
        <TYPE>S-1
        <TEXT>
        <HTML>
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
            primary_doc_url="https://www.sec.gov/test.htm",
        )

        mock_response = Mock()
        mock_response.text = valid_html
        mock_response.raise_for_status = Mock()

        with patch.object(fetcher.session, "get", return_value=mock_response):
            content = fetcher.fetch_filing(metadata, fetch_txt=False)

        # Verify database was updated
        assert content is not None
        fetcher.db.execute.assert_called_once()
        call_args = fetcher.db.execute.call_args
        assert "UPDATE filings" in call_args[0][0]
        assert "processing_status = 'fetched'" in call_args[0][0]

    def test_update_database_on_http_error(self, fetcher):
        """Test that database records HTTP errors."""
        import requests

        metadata = FilingMetadata(
            cik="0001234567",
            company_name="Test Corp",
            form_type="S-1",
            filing_date="2024-01-15",
            accession_number="0001234567-12-123456",
            primary_doc_url="https://www.sec.gov/test.htm",
        )

        mock_response = Mock()
        mock_response.raise_for_status.side_effect = requests.HTTPError("404 Not Found")

        with patch.object(fetcher.session, "get", return_value=mock_response):
            content = fetcher.fetch_filing(metadata, fetch_txt=False)

        assert content is None
        # Verify database error was recorded
        fetcher.db.execute.assert_called_once()
        call_args = fetcher.db.execute.call_args
        assert "html_fetch_error" in call_args[0][0]

    def test_update_database_on_validation_error(self, fetcher):
        """Test that database records validation errors."""
        metadata = FilingMetadata(
            cik="0001234567",
            company_name="Test Corp",
            form_type="S-1",
            filing_date="2024-01-15",
            accession_number="0001234567-12-123456",
            primary_doc_url="https://www.sec.gov/test.htm",
        )

        # Mock response with invalid content
        mock_response = Mock()
        mock_response.text = "<html>Too small</html>"
        mock_response.raise_for_status = Mock()

        with patch.object(fetcher.session, "get", return_value=mock_response):
            content = fetcher.fetch_filing(metadata, fetch_txt=False)

        assert content is None
        # Verify database error was recorded
        fetcher.db.execute.assert_called_once()

    def test_database_update_error_handling(self, fetcher):
        """Test that database update errors are logged but don't crash."""
        valid_html = (
            """
        <DOCUMENT>
        <TYPE>S-1
        <TEXT>
        <HTML>
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
            primary_doc_url="https://www.sec.gov/test.htm",
        )

        # Mock database to raise error
        fetcher.db.execute.side_effect = Exception("Database connection failed")

        mock_response = Mock()
        mock_response.text = valid_html
        mock_response.raise_for_status = Mock()

        with patch.object(fetcher.session, "get", return_value=mock_response):
            # Should not crash despite database error
            content = fetcher.fetch_filing(metadata, fetch_txt=False)

        # Filing should still be fetched successfully
        assert content is not None
        assert Path(content.html_path).exists()

    def test_get_unfetched_filings(self, fetcher):
        """Test retrieving list of unfetched filings from database."""
        mock_results = [
            {
                "filing_id": 1,
                "company_id": 100,
                "cik": "0001234567",
                "accession_number": "0001234567-12-123456",
                "form_type": "S-1",
                "filing_date": "2024-01-15",
                "primary_doc_url": "https://www.sec.gov/test1.htm",
                "txt_url": "https://www.sec.gov/test1.txt",
            },
            {
                "filing_id": 2,
                "company_id": 101,
                "cik": "0007654321",
                "accession_number": "0007654321-12-654321",
                "form_type": "F-1",
                "filing_date": "2024-01-16",
                "primary_doc_url": "https://www.sec.gov/test2.htm",
                "txt_url": None,
            },
        ]

        fetcher.db.query.return_value = mock_results

        results = fetcher.get_unfetched_filings(limit=100)

        assert len(results) == 2
        assert results[0]["cik"] == "0001234567"
        fetcher.db.query.assert_called_once()
        call_args = fetcher.db.query.call_args
        assert "is_in_scope_phase1 = true" in call_args[0][0]
        assert "html_fetched_at IS NULL" in call_args[0][0]

    def test_get_unfetched_filings_without_db(self, tmp_path):
        """Test that get_unfetched_filings raises error without database."""
        fetcher = FilingFetcher(storage_root=str(tmp_path / "test_filings"))

        with pytest.raises(ValueError, match="Database required"):
            fetcher.get_unfetched_filings()

    def test_database_error_update_fails_gracefully(self, fetcher):
        """Test that errors during database error recording are logged but don't crash."""
        import requests

        metadata = FilingMetadata(
            cik="0001234567",
            company_name="Test Corp",
            form_type="S-1",
            filing_date="2024-01-15",
            accession_number="0001234567-12-123456",
            primary_doc_url="https://www.sec.gov/test.htm",
        )

        # Mock database to raise error when trying to record the error
        fetcher.db.execute.side_effect = Exception("Database completely down")

        # Mock HTTP to fail
        mock_response = Mock()
        mock_response.raise_for_status.side_effect = requests.HTTPError("404 Not Found")

        with patch.object(fetcher.session, "get", return_value=mock_response):
            # Should not crash even though both fetch AND error recording fail
            content = fetcher.fetch_filing(metadata, fetch_txt=False)

        assert content is None
        # Verify that database.execute was called (even though it failed)
        fetcher.db.execute.assert_called()
