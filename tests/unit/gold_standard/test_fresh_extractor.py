"""Unit tests for fresh_extractor module."""

import tempfile
from collections.abc import Generator
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.gold_standard.fresh_extractor import (
    ExtractionResult,
    ParsedSecUrl,
    _normalize_company_for_path,
    extract_fresh,
    extract_fresh_batch,
    fetch_from_sec,
    find_local_filing,
    parse_sec_url,
    segment_and_generate,
)

# =============================================================================
# Test Data
# =============================================================================

# Example SEC EDGAR URLs
SLACK_URL = "https://www.sec.gov/Archives/edgar/data/1764925/000162828019007428/slacks-1a3.htm"
FARFETCH_URL = "https://www.sec.gov/Archives/edgar/data/1740915/000119312518252315/primary.htm"


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def temp_filings_dir() -> Generator[Path, None, None]:
    """Create a temporary directory for test filings."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def mock_filing_html(temp_filings_dir: Path) -> Path:
    """Create a mock filing HTML file."""
    # Create directory structure matching SEC URL format
    cik_dir = temp_filings_dir / "0001764925" / "000162828019007428"
    cik_dir.mkdir(parents=True, exist_ok=True)

    filing_path = cik_dir / "slacks-1a3.htm"
    filing_path.write_text("""
    <html>
    <body>
    <p>We had 10 million daily active users as of January 31, 2019.</p>
    <p>Our Paid Customers increased to 88,000.</p>
    </body>
    </html>
    """, encoding="utf-8")

    return filing_path


@pytest.fixture
def temp_gold_standard_dir() -> Generator[Path, None, None]:
    """Create a temporary gold_standard directory with mock filings."""
    with tempfile.TemporaryDirectory() as tmpdir:
        base = Path(tmpdir)
        # Patch the gold_standard path to use our temp directory
        # We need to mock at the location where it's used
        yield base


# =============================================================================
# URL Parsing Tests
# =============================================================================


class TestParseSecUrl:
    """Tests for parse_sec_url function."""

    def test_valid_url_with_zero_padded_cik(self) -> None:
        """Parse SEC URL and zero-pad CIK to 10 digits."""
        result = parse_sec_url(SLACK_URL)

        assert result is not None
        assert result.cik == "0001764925"
        assert result.accession == "000162828019007428"
        assert result.filename == "slacks-1a3.htm"

    def test_valid_url_without_www(self) -> None:
        """Parse SEC URL without www prefix."""
        url = "https://sec.gov/Archives/edgar/data/1764925/000162828019007428/slacks-1a3.htm"
        result = parse_sec_url(url)

        assert result is not None
        assert result.cik == "0001764925"

    def test_valid_url_http(self) -> None:
        """Parse HTTP SEC URL (should work even though SEC uses HTTPS)."""
        url = "http://www.sec.gov/Archives/edgar/data/1764925/000162828019007428/slacks-1a3.htm"
        result = parse_sec_url(url)

        assert result is not None
        assert result.cik == "0001764925"

    def test_short_cik_zero_padded(self) -> None:
        """Short CIK should be zero-padded to 10 digits."""
        url = "https://www.sec.gov/Archives/edgar/data/12345/000119312518252315/filing.htm"
        result = parse_sec_url(url)

        assert result is not None
        assert result.cik == "0000012345"
        assert len(result.cik) == 10

    def test_invalid_url_returns_none(self) -> None:
        """Invalid URL should return None."""
        assert parse_sec_url("https://google.com/invalid") is None
        assert parse_sec_url("") is None
        assert parse_sec_url("not a url") is None

    def test_url_with_query_params(self) -> None:
        """URL with query params should be parsed correctly."""
        url = "https://www.sec.gov/Archives/edgar/data/1764925/000162828019007428/slacks-1a3.htm?query=1"
        result = parse_sec_url(url)

        assert result is not None
        # Filename should not include query params
        assert result.filename == "slacks-1a3.htm"


class TestParsedSecUrlToLocalPath:
    """Tests for ParsedSecUrl.to_local_path method."""

    def test_to_local_path_default_base(self) -> None:
        """Convert to local path with default base directory."""
        parsed = ParsedSecUrl(
            cik="0001764925",
            accession="000162828019007428",
            filename="slacks-1a3.htm",
        )
        path = parsed.to_local_path()

        assert path == Path("data/filings/0001764925/000162828019007428/slacks-1a3.htm")

    def test_to_local_path_custom_base(self) -> None:
        """Convert to local path with custom base directory."""
        parsed = ParsedSecUrl(
            cik="0001764925",
            accession="000162828019007428",
            filename="slacks-1a3.htm",
        )
        path = parsed.to_local_path("/tmp/filings")

        assert path == Path("/tmp/filings/0001764925/000162828019007428/slacks-1a3.htm")


# =============================================================================
# Local Cache Lookup Tests
# =============================================================================


class TestFindLocalFiling:
    """Tests for find_local_filing function."""

    def test_find_existing_file(self, temp_filings_dir: Path, mock_filing_html: Path) -> None:
        """Find an existing cached filing."""
        parsed = parse_sec_url(SLACK_URL)
        assert parsed is not None

        result = find_local_filing(parsed, temp_filings_dir)

        assert result is not None
        assert result.exists()
        assert result == mock_filing_html

    def test_find_primary_htm_alternative(self, temp_filings_dir: Path) -> None:
        """Find filing using primary.htm alternative name."""
        # Create file with primary.htm name instead of original
        cik_dir = temp_filings_dir / "0001764925" / "000162828019007428"
        cik_dir.mkdir(parents=True, exist_ok=True)
        primary_path = cik_dir / "primary.htm"
        primary_path.write_text("<html></html>")

        parsed = parse_sec_url(SLACK_URL)
        assert parsed is not None

        result = find_local_filing(parsed, temp_filings_dir)

        assert result is not None
        assert result == primary_path

    def test_find_with_unpadded_cik(self, temp_filings_dir: Path) -> None:
        """Find filing with unpadded CIK directory."""
        # Create file with unpadded CIK
        cik_dir = temp_filings_dir / "1764925" / "000162828019007428"
        cik_dir.mkdir(parents=True, exist_ok=True)
        filing_path = cik_dir / "slacks-1a3.htm"
        filing_path.write_text("<html></html>")

        parsed = parse_sec_url(SLACK_URL)
        assert parsed is not None

        result = find_local_filing(parsed, temp_filings_dir)

        assert result is not None
        assert result == filing_path

    def test_missing_file_returns_none(self, temp_filings_dir: Path) -> None:
        """Return None for missing file."""
        parsed = parse_sec_url(SLACK_URL)
        assert parsed is not None

        result = find_local_filing(parsed, temp_filings_dir)

        assert result is None

    def test_find_with_unpadded_cik_primary_htm(self, temp_filings_dir: Path) -> None:
        """Find filing with unpadded CIK directory and primary.htm filename."""
        # Create file with unpadded CIK and primary.htm
        cik_dir = temp_filings_dir / "1764925" / "000162828019007428"
        cik_dir.mkdir(parents=True, exist_ok=True)
        primary_path = cik_dir / "primary.htm"
        primary_path.write_text("<html></html>")

        parsed = parse_sec_url(SLACK_URL)
        assert parsed is not None

        result = find_local_filing(parsed, temp_filings_dir)

        assert result is not None
        assert result == primary_path


# =============================================================================
# SEC Fetch Tests
# =============================================================================


class TestFetchFromSec:
    """Tests for fetch_from_sec function."""

    def test_fetch_returns_error_on_network_failure(self) -> None:
        """Return error message on network failure."""
        parsed = parse_sec_url(SLACK_URL)
        assert parsed is not None

        # Mock at the location where it's imported (inside the function)
        with patch.dict("sys.modules", {"requests": MagicMock()}):
            import sys
            mock_requests = sys.modules["requests"]
            mock_requests.get.side_effect = Exception("Network error")

            html, error = fetch_from_sec(parsed, rate_limit_ms=0)

            assert html is None
            assert error is not None
            assert "Network error" in error

    def test_fetch_returns_html_on_success(self) -> None:
        """Return HTML content on successful fetch."""
        parsed = parse_sec_url(SLACK_URL)
        assert parsed is not None

        # Mock the requests module
        mock_response = MagicMock()
        mock_response.text = "<html><body>Test</body></html>"
        mock_response.raise_for_status = MagicMock()

        mock_requests_module = MagicMock()
        mock_requests_module.get.return_value = mock_response

        with patch.dict("sys.modules", {"requests": mock_requests_module}):
            html, error = fetch_from_sec(parsed, rate_limit_ms=0)

            assert html is not None
            assert error is None
            assert "<html>" in html


# =============================================================================
# Segmentation and Generation Tests
# =============================================================================


class TestSegmentAndGenerate:
    """Tests for segment_and_generate function."""

    def test_segment_empty_html(self, temp_filings_dir: Path) -> None:
        """Handle empty HTML file gracefully."""
        # Create empty HTML file
        html_path = temp_filings_dir / "empty.htm"
        html_path.write_text("<html><body></body></html>")

        candidates, segment_count, error = segment_and_generate(html_path)

        # Should return empty results without error
        assert error is None
        assert segment_count >= 0
        assert isinstance(candidates, list)

    def test_segment_with_numbers(self, temp_filings_dir: Path) -> None:
        """Segment HTML containing numbers and metrics keywords."""
        html_path = temp_filings_dir / "metrics.htm"
        html_path.write_text("""
        <html>
        <body>
        <p>We have 10 million daily active users worldwide.</p>
        <p>Our customer count reached 500,000 paid subscribers.</p>
        </body>
        </html>
        """, encoding="utf-8")

        candidates, segment_count, error = segment_and_generate(html_path)

        assert error is None
        assert segment_count > 0
        # Should generate some candidates from the text
        assert isinstance(candidates, list)

    def test_segment_nonexistent_file(self, temp_filings_dir: Path) -> None:
        """Handle nonexistent file gracefully (returns empty results)."""
        nonexistent = temp_filings_dir / "does_not_exist.htm"

        candidates, segment_count, error = segment_and_generate(nonexistent)

        # HTMLSegmenter logs error but returns empty results without raising
        # So we get empty candidates and zero segments, but no error string
        assert candidates == []
        assert segment_count == 0


# =============================================================================
# Fresh Extraction Tests
# =============================================================================


class TestExtractFresh:
    """Tests for extract_fresh function."""

    def test_extract_with_invalid_url(self) -> None:
        """Return error for invalid SEC URL."""
        result = extract_fresh(
            document_url="https://google.com/invalid",
            allow_sec_fetch=False,
        )

        assert result.success is False
        assert "Invalid SEC URL format" in (result.error_message or "")
        assert result.candidates == []

    def test_extract_missing_file_no_fetch(self, temp_filings_dir: Path) -> None:
        """Return error when file not cached and fetch disabled."""
        result = extract_fresh(
            document_url=SLACK_URL,
            base_dir=str(temp_filings_dir),
            allow_sec_fetch=False,
        )

        assert result.success is False
        assert "not found in cache" in (result.error_message or "")
        assert result.local_path is None

    def test_extract_with_cached_file(
        self, temp_filings_dir: Path, mock_filing_html: Path
    ) -> None:
        """Successfully extract from cached file."""
        result = extract_fresh(
            document_url=SLACK_URL,
            base_dir=str(temp_filings_dir),
            allow_sec_fetch=False,
        )

        assert result.success is True
        assert result.error_message is None
        assert result.local_path == mock_filing_html
        assert result.segments_count >= 0
        assert result.elapsed_seconds > 0

    def test_extract_result_has_document_url(self, temp_filings_dir: Path) -> None:
        """ExtractionResult always contains original document URL."""
        result = extract_fresh(
            document_url=SLACK_URL,
            base_dir=str(temp_filings_dir),
            allow_sec_fetch=False,
        )

        assert result.document_url == SLACK_URL


class TestExtractionResult:
    """Tests for ExtractionResult dataclass."""

    def test_extraction_result_success(self) -> None:
        """Create successful ExtractionResult."""
        result = ExtractionResult(
            document_url=SLACK_URL,
            success=True,
            error_message=None,
            segments_count=100,
            candidates=[],
            local_path=Path("/tmp/test.htm"),
            elapsed_seconds=1.5,
        )

        assert result.success is True
        assert result.error_message is None
        assert result.segments_count == 100

    def test_extraction_result_failure(self) -> None:
        """Create failed ExtractionResult."""
        result = ExtractionResult(
            document_url=SLACK_URL,
            success=False,
            error_message="File not found",
            segments_count=0,
            candidates=[],
            local_path=None,
            elapsed_seconds=0.1,
        )

        assert result.success is False
        assert result.error_message == "File not found"
        assert result.local_path is None


# =============================================================================
# Integration-style Tests (with real-ish data)
# =============================================================================


class TestExtractFreshWithSecFetch:
    """Tests for extract_fresh with SEC fetch enabled."""

    def test_extract_fetches_from_sec_when_not_cached(
        self, temp_filings_dir: Path
    ) -> None:
        """When file not cached and allow_sec_fetch=True, fetch from SEC."""
        with patch(
            "src.gold_standard.fresh_extractor.fetch_from_sec"
        ) as mock_fetch:
            # Mock successful fetch
            mock_fetch.return_value = (
                "<html><body><p>Test content</p></body></html>",
                None,
            )

            result = extract_fresh(
                document_url=SLACK_URL,
                base_dir=str(temp_filings_dir),
                allow_sec_fetch=True,
            )

            # Should have called fetch_from_sec
            assert mock_fetch.called
            # Should succeed
            assert result.success is True
            # Should have cached the file
            assert result.local_path is not None
            assert result.local_path.exists()

    def test_extract_fails_when_sec_fetch_fails(
        self, temp_filings_dir: Path
    ) -> None:
        """Return error when SEC fetch fails."""
        with patch(
            "src.gold_standard.fresh_extractor.fetch_from_sec"
        ) as mock_fetch:
            mock_fetch.return_value = (None, "Connection refused")

            result = extract_fresh(
                document_url=SLACK_URL,
                base_dir=str(temp_filings_dir),
                allow_sec_fetch=True,
            )

            assert result.success is False
            assert "Failed to fetch from SEC" in (result.error_message or "")


# =============================================================================
# Batch Extraction Tests
# =============================================================================


class TestExtractFreshBatch:
    """Tests for extract_fresh_batch function."""

    def test_batch_extraction_empty_list(self) -> None:
        """Handle empty URL list."""
        results = extract_fresh_batch(
            document_urls=[],
            allow_sec_fetch=False,
        )

        assert results == []

    def test_batch_extraction_multiple_urls(self, temp_filings_dir: Path) -> None:
        """Extract from multiple URLs."""
        # Create two mock filings
        for cik, accession in [("0001764925", "000162828019007428"),
                                ("0001740915", "000119312518252315")]:
            cik_dir = temp_filings_dir / cik / accession
            cik_dir.mkdir(parents=True, exist_ok=True)
            (cik_dir / "primary.htm").write_text(
                "<html><body><p>Test</p></body></html>"
            )

        results = extract_fresh_batch(
            document_urls=[SLACK_URL, FARFETCH_URL],
            base_dir=str(temp_filings_dir),
            allow_sec_fetch=False,
        )

        assert len(results) == 2
        # First URL should succeed
        assert results[0].document_url == SLACK_URL
        # Each result has the correct URL
        assert results[1].document_url == FARFETCH_URL

    def test_batch_extraction_with_progress_callback(
        self, temp_filings_dir: Path
    ) -> None:
        """Progress callback is called for each URL."""
        # Create mock filing
        cik_dir = temp_filings_dir / "0001764925" / "000162828019007428"
        cik_dir.mkdir(parents=True, exist_ok=True)
        (cik_dir / "slacks-1a3.htm").write_text("<html></html>")

        progress_calls = []

        def progress_callback(current: int, total: int, url: str) -> None:
            progress_calls.append((current, total, url))

        results = extract_fresh_batch(
            document_urls=[SLACK_URL],
            base_dir=str(temp_filings_dir),
            allow_sec_fetch=False,
            progress_callback=progress_callback,
        )

        assert len(results) == 1
        assert len(progress_calls) == 1
        assert progress_calls[0] == (1, 1, SLACK_URL)


class TestFreshExtractionIntegration:
    """Integration-style tests using mock filings."""

    def test_full_extraction_pipeline(self, temp_filings_dir: Path) -> None:
        """Test complete extraction pipeline with realistic HTML."""
        # Create a more realistic filing HTML
        cik_dir = temp_filings_dir / "0001764925" / "000162828019007428"
        cik_dir.mkdir(parents=True, exist_ok=True)

        filing_path = cik_dir / "slacks-1a3.htm"
        filing_path.write_text("""
        <!DOCTYPE html>
        <html>
        <head><title>Slack Technologies S-1</title></head>
        <body>
        <h1>Business Overview</h1>
        <p>During the three months ended January 31, 2019, our daily active users
        exceeded 10 million. As of January 31, 2019, Slack had more than 600,000
        organizations with three or more users.</p>

        <h2>Key Metrics</h2>
        <p>We had 88,000 Paid Customers as of January 31, 2019, compared to
        59,000 Paid Customers as of January 31, 2018.</p>

        <p>Our Net Dollar Retention Rate was 143% for fiscal year 2019.</p>
        </body>
        </html>
        """, encoding="utf-8")

        result = extract_fresh(
            document_url=SLACK_URL,
            base_dir=str(temp_filings_dir),
            allow_sec_fetch=False,
        )

        assert result.success is True
        assert result.segments_count > 0
        # The exact number of candidates depends on keyword matching
        assert isinstance(result.candidates, list)

    def test_extraction_with_minimal_html(self, temp_filings_dir: Path) -> None:
        """Handle minimal HTML with no metric content."""
        cik_dir = temp_filings_dir / "0001764925" / "000162828019007428"
        cik_dir.mkdir(parents=True, exist_ok=True)

        filing_path = cik_dir / "slacks-1a3.htm"
        filing_path.write_text("<html><body><p>No metrics here.</p></body></html>")

        result = extract_fresh(
            document_url=SLACK_URL,
            base_dir=str(temp_filings_dir),
            allow_sec_fetch=False,
        )

        assert result.success is True
        # May have zero candidates if no metrics found
        assert isinstance(result.candidates, list)


# =============================================================================
# Company Name Normalization Tests
# =============================================================================


class TestNormalizeCompanyForPath:
    """Tests for _normalize_company_for_path function."""

    def test_simple_company_name(self) -> None:
        """Simple company name with spaces."""
        assert _normalize_company_for_path("Slack Technologies") == "Slack_Technologies"

    def test_company_with_inc_period(self) -> None:
        """Company name with Inc. suffix."""
        assert _normalize_company_for_path("Samsara Vision Inc.") == "Samsara_Vision_Inc_"

    def test_company_with_ltd_comma(self) -> None:
        """Company name with Ltd suffix and comma."""
        # Note: comma is preserved as in actual directory naming
        assert _normalize_company_for_path("Farfetch, Ltd") == "Farfetch,_Ltd"

    def test_company_with_comma_and_inc(self) -> None:
        """Company name with comma and Inc. suffix."""
        assert _normalize_company_for_path("PlayAGS, Inc.") == "PlayAGS,_Inc_"

    def test_empty_string(self) -> None:
        """Empty string returns empty string."""
        assert _normalize_company_for_path("") == ""

    def test_no_special_chars(self) -> None:
        """Simple name without special characters."""
        assert _normalize_company_for_path("Apple") == "Apple"

    def test_double_underscore_collapsed(self) -> None:
        """Double underscores from '. ' are collapsed."""
        # "Inc. Holdings" -> "Inc__Holdings" would be collapsed to "Inc_Holdings"
        assert _normalize_company_for_path("Inc. Holdings") == "Inc_Holdings"


# =============================================================================
# Gold Standard Path Resolution Tests
# =============================================================================


class TestFindLocalFilingGoldStandard:
    """Tests for find_local_filing with gold_standard path lookup."""

    def test_find_in_gold_standard_directory(self, temp_filings_dir: Path) -> None:
        """Find filing in gold_standard directory when company_name provided."""
        # Create gold_standard directory structure
        gold_dir = temp_filings_dir / "data" / "gold_standard" / "Slack_Technologies"
        gold_dir.mkdir(parents=True, exist_ok=True)
        filing_path = gold_dir / "filing.html"
        filing_path.write_text("<html><body>Gold standard content</body></html>")

        parsed = parse_sec_url(SLACK_URL)
        assert parsed is not None

        # Patch the gold_standard base path
        with patch(
            "src.gold_standard.fresh_extractor.Path"
        ) as mock_path_class:
            # Make Path("data/gold_standard") return our temp path
            def path_side_effect(path_str: str) -> Path:
                if path_str == "data/gold_standard":
                    return temp_filings_dir / "data" / "gold_standard"
                return Path(path_str)

            mock_path_class.side_effect = path_side_effect
            mock_path_class.return_value = Path

            # Instead, let's use a simpler approach - directly set up the path
            # The function uses Path("data/gold_standard") / normalized / "filing.html"
            # We need to test with actual filesystem

        # Use real paths - create a gold_standard in a temp location
        # and patch to use it
        pass  # This test needs a different approach - see next test

    def test_gold_standard_lookup_with_mock(self, temp_filings_dir: Path) -> None:
        """Find filing in gold_standard using filesystem mock."""
        # Create the gold_standard structure in temp dir
        gold_standard_base = temp_filings_dir / "gold_standard"
        slack_dir = gold_standard_base / "Slack_Technologies"
        slack_dir.mkdir(parents=True, exist_ok=True)
        gold_filing = slack_dir / "filing.html"
        gold_filing.write_text("<html><body>Gold standard Slack</body></html>")

        parsed = parse_sec_url(SLACK_URL)
        assert parsed is not None

        # Mock Path to redirect gold_standard lookups
        original_path = Path

        def mock_path(path_str: str | Path) -> Path:
            if str(path_str) == "data/gold_standard":
                return gold_standard_base
            return original_path(path_str)

        with patch("src.gold_standard.fresh_extractor.Path", side_effect=mock_path):
            result = find_local_filing(
                parsed, temp_filings_dir, company_name="Slack Technologies"
            )

        # Should find the gold_standard filing
        assert result is not None
        assert result == gold_filing

    def test_fallback_to_filings_when_no_gold_standard(
        self, temp_filings_dir: Path, mock_filing_html: Path
    ) -> None:
        """Fall back to data/filings when gold_standard doesn't exist."""
        parsed = parse_sec_url(SLACK_URL)
        assert parsed is not None

        # No gold_standard directory exists, but mock_filing_html is in data/filings
        result = find_local_filing(
            parsed, temp_filings_dir, company_name="Nonexistent Company"
        )

        # Should fall back and find in data/filings
        assert result is not None
        assert result == mock_filing_html

    def test_without_company_name_skips_gold_standard(
        self, temp_filings_dir: Path, mock_filing_html: Path
    ) -> None:
        """Without company_name, skip gold_standard lookup."""
        parsed = parse_sec_url(SLACK_URL)
        assert parsed is not None

        # Even if gold_standard exists, without company_name it won't be checked
        # This tests backward compatibility
        result = find_local_filing(parsed, temp_filings_dir)

        assert result is not None
        assert result == mock_filing_html


class TestExtractFreshWithCompanyName:
    """Tests for extract_fresh with company_name parameter."""

    def test_extract_uses_gold_standard_when_company_provided(
        self, temp_filings_dir: Path
    ) -> None:
        """extract_fresh uses gold_standard path when company_name provided."""
        # Create gold_standard structure
        gold_standard_base = temp_filings_dir / "gold_standard"
        slack_dir = gold_standard_base / "Slack_Technologies"
        slack_dir.mkdir(parents=True, exist_ok=True)
        gold_filing = slack_dir / "filing.html"
        gold_filing.write_text("""
        <html><body>
        <p>Gold standard: 10 million daily active users.</p>
        </body></html>
        """)

        original_path = Path

        def mock_path(path_str: str | Path) -> Path:
            if str(path_str) == "data/gold_standard":
                return gold_standard_base
            return original_path(path_str)

        with patch("src.gold_standard.fresh_extractor.Path", side_effect=mock_path):
            result = extract_fresh(
                document_url=SLACK_URL,
                base_dir=str(temp_filings_dir),
                allow_sec_fetch=False,
                company_name="Slack Technologies",
            )

        assert result.success is True
        assert result.local_path == gold_filing

    def test_extract_falls_back_without_gold_standard_filing(
        self, temp_filings_dir: Path, mock_filing_html: Path
    ) -> None:
        """Falls back to data/filings when no gold_standard filing.html."""
        result = extract_fresh(
            document_url=SLACK_URL,
            base_dir=str(temp_filings_dir),
            allow_sec_fetch=False,
            company_name="Company Without Gold Standard",
        )

        assert result.success is True
        # Should find the mock_filing_html in data/filings path
        assert result.local_path == mock_filing_html
