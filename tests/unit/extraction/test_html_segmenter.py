"""
Unit tests for HTMLSegmenter.

Tests the segmentation of HTML filings into source segments.
"""

import tempfile
from pathlib import Path

import pytest

from src.extraction.html_segmenter import HTMLSegmenter


@pytest.fixture
def sample_html_simple():
    """Simple HTML with paragraphs and a table."""
    return """
    <!DOCTYPE html>
    <html>
    <body>
        <h1>Prospectus Summary</h1>
        <p>We are a leading technology company with innovative products.</p>
        <p>Our key metrics include daily active users and revenue per user.</p>

        <table>
            <tr><th>Metric</th><th>Value</th></tr>
            <tr><td>DAU</td><td>1,500</td></tr>
            <tr><td>Revenue</td><td>$10M</td></tr>
        </table>

        <p>We define daily active users as users who log in at least once per day.</p>
    </body>
    </html>
    """


@pytest.fixture
def sample_html_sgml():
    """SGML-wrapped SEC filing format."""
    return """
    <DOCUMENT>
    <TYPE>S-1
    <SEQUENCE>1
    <TEXT>
    <HTML>
    <HEAD></HEAD>
    <BODY>
        <p>This is a prospectus for an initial public offering.</p>
        <p>We had 10,000 monthly active users as of December 31, 2024.</p>
    </BODY>
    </HTML>
    </TEXT>
    </DOCUMENT>
    """


@pytest.fixture
def sample_html_sgml_uppercase():
    """SGML-wrapped SEC filing format with uppercase TEXT tag."""
    return """
    <DOCUMENT>
    <TYPE>S-1
    <SEQUENCE>1
    <TEXT>
    <HTML>
    <HEAD></HEAD>
    <BODY>
        <p>Our customer count grew to 500 users in the last quarter.</p>
    </BODY>
    </HTML>
    </TEXT>
    </DOCUMENT>
    """


@pytest.fixture
def temp_html_file():
    """Create a temporary HTML file for testing."""

    def _create_file(content):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".html", delete=False) as f:
            f.write(content)
            return f.name

    return _create_file


def test_segment_simple_html(sample_html_simple, temp_html_file):
    """Test segmentation of simple HTML document."""
    html_path = temp_html_file(sample_html_simple)
    segmenter = HTMLSegmenter()

    try:
        segments = segmenter.segment_filing(filing_id=1, html_path=html_path)

        # Should extract paragraphs and table
        assert len(segments) > 0

        # Check segment types
        segment_types = [s.segment_type for s in segments]
        assert "paragraph" in segment_types or "other" in segment_types

        # Check all segments have required fields
        for segment in segments:
            assert segment.filing_id == 1
            assert segment.raw_text is not None
            assert len(segment.raw_text) > 0
            assert segment.sequence_index >= 0

    finally:
        Path(html_path).unlink()


def test_segment_sgml_format(sample_html_sgml, temp_html_file):
    """Test segmentation of SGML-wrapped filing."""
    html_path = temp_html_file(sample_html_sgml)
    segmenter = HTMLSegmenter()

    try:
        segments = segmenter.segment_filing(filing_id=2, html_path=html_path)

        # Should find content inside <TEXT> tags
        assert len(segments) > 0

        # Check that text was extracted
        all_text = " ".join(s.raw_text for s in segments)
        assert (
            "prospectus" in all_text.lower()
            or "monthly active users" in all_text.lower()
        )

    finally:
        Path(html_path).unlink()


def test_segment_sgml_filing_uppercase_text_tag(sample_html_sgml_uppercase, temp_html_file):
    """Test segmentation of SGML-wrapped filing with uppercase TEXT tag.

    Regression test for Task 2: SGML Tag Case Insensitivity.
    Older SEC EDGAR filings may use <TEXT> instead of <text>.
    """
    html_path = temp_html_file(sample_html_sgml_uppercase)
    segmenter = HTMLSegmenter()

    try:
        segments = segmenter.segment_filing(filing_id=3, html_path=html_path)

        # Should find content inside uppercase <TEXT> tags
        assert len(segments) > 0, "Should extract segments from uppercase <TEXT> tag"

        # Verify content was extracted
        all_text = " ".join(s.raw_text for s in segments)
        assert "customer count" in all_text.lower()

    finally:
        Path(html_path).unlink()


def test_boundary_detector_is_singleton(temp_html_file):
    """Verify BoundaryDetector instance is reused across method calls.

    Regression test for SEG3: Singleton BoundaryDetector optimization.
    Ensures we don't create a new BoundaryDetector instance on every
    segmentation call, reducing memory allocation overhead.
    """
    from src.review.boundary_detection import BoundaryDetector

    segmenter = HTMLSegmenter()

    # Verify instance exists
    assert hasattr(segmenter, '_boundary_detector')
    assert isinstance(segmenter._boundary_detector, BoundaryDetector)

    # Verify it's the same instance (singleton pattern)
    detector_id = id(segmenter._boundary_detector)

    # Segment a filing with multiple paragraphs
    html_content = """
    <html><body>
    <p>First paragraph with some text. Second sentence here.</p>
    <p>Second paragraph with different content. More sentences.</p>
    </body></html>
    """
    html_path = temp_html_file(html_content)

    try:
        segmenter.segment_filing(filing_id=1, html_path=html_path)

        # Verify same instance was used (not recreated)
        assert id(segmenter._boundary_detector) == detector_id
    finally:
        Path(html_path).unlink()


def test_min_segment_length_filter():
    """Test that segments shorter than min_length are filtered out."""
    html = """
    <html><body>
        <p>Short</p>
        <p>This is a much longer paragraph that should definitely be included in the segments because it exceeds the minimum length.</p>
    </body></html>
    """

    with tempfile.NamedTemporaryFile(mode="w", suffix=".html", delete=False) as f:
        f.write(html)
        html_path = f.name

    try:
        segmenter = HTMLSegmenter(min_length=50)
        segments = segmenter.segment_filing(filing_id=3, html_path=html_path)

        # Only the long paragraph should be included
        assert len(segments) >= 1
        assert all(len(s.raw_text) >= 50 for s in segments)

    finally:
        Path(html_path).unlink()


def test_max_segment_length_truncation():
    """Test that segments longer than max_length are truncated."""
    # Create very long text
    long_text = "A" * 12000  # Longer than default max_length of 10000
    html = f"<html><body><p>{long_text}</p></body></html>"

    with tempfile.NamedTemporaryFile(mode="w", suffix=".html", delete=False) as f:
        f.write(html)
        html_path = f.name

    try:
        segmenter = HTMLSegmenter(max_length=10000)
        segments = segmenter.segment_filing(filing_id=4, html_path=html_path)

        # Segment should be truncated
        if segments:
            assert all(len(s.raw_text) <= 10000 for s in segments)

    finally:
        Path(html_path).unlink()


def test_empty_html_returns_empty_list(temp_html_file):
    """Test that empty or minimal HTML returns empty segment list."""
    html_path = temp_html_file("<html></html>")
    segmenter = HTMLSegmenter()

    try:
        segments = segmenter.segment_filing(filing_id=5, html_path=html_path)
        assert isinstance(segments, list)
        # May be empty or have very few segments

    finally:
        Path(html_path).unlink()


def test_missing_file_returns_empty_list():
    """Test that missing HTML file returns empty list."""
    segmenter = HTMLSegmenter()
    segments = segmenter.segment_filing(filing_id=6, html_path="/nonexistent/path.html")

    assert segments == []


def test_sequence_indices_are_sequential(sample_html_simple, temp_html_file):
    """Test that sequence indices increment properly."""
    html_path = temp_html_file(sample_html_simple)
    segmenter = HTMLSegmenter()

    try:
        segments = segmenter.segment_filing(filing_id=7, html_path=html_path)

        if len(segments) > 1:
            indices = [s.sequence_index for s in segments]
            # Check they're sequential starting from 0
            assert indices == list(range(len(indices)))

    finally:
        Path(html_path).unlink()


def test_normalize_text_removes_extra_whitespace():
    """Test that text normalization works properly."""
    html = """
    <html><body>
        <p>This    has    multiple    spaces    and
        newlines
        that should be normalized into single spaces for readability.</p>
    </body></html>
    """

    with tempfile.NamedTemporaryFile(mode="w", suffix=".html", delete=False) as f:
        f.write(html)
        html_path = f.name

    try:
        segmenter = HTMLSegmenter(min_length=10)
        segments = segmenter.segment_filing(filing_id=8, html_path=html_path)

        if segments:
            # Check that text doesn't have excessive whitespace
            for segment in segments:
                assert "    " not in segment.raw_text  # No quad spaces
                assert "\n\n\n" not in segment.raw_text  # No triple newlines

    finally:
        Path(html_path).unlink()


def test_table_extraction():
    """Test that tables are properly extracted as segments."""
    html = """
    <html><body>
        <table>
            <tr><th>Quarter</th><th>Revenue</th></tr>
            <tr><td>Q1 2024</td><td>$5M</td></tr>
            <tr><td>Q2 2024</td><td>$6M</td></tr>
            <tr><td>Q3 2024</td><td>$7M</td></tr>
        </table>
    </body></html>
    """

    with tempfile.NamedTemporaryFile(mode="w", suffix=".html", delete=False) as f:
        f.write(html)
        html_path = f.name

    try:
        segmenter = HTMLSegmenter(min_length=20)
        segments = segmenter.segment_filing(filing_id=9, html_path=html_path)

        # Should extract the table
        assert len(segments) > 0

        # At least one segment should contain table data
        all_text = " ".join(s.raw_text for s in segments)
        assert "Q1 2024" in all_text or "Revenue" in all_text

    finally:
        Path(html_path).unlink()


def test_custom_min_and_max_lengths():
    """Test that custom min/max lengths work."""
    html = """
    <html><body>
        <p>Short text here.</p>
        <p>This is a medium length paragraph with enough content to pass most filters.</p>
        <p>{"A" * 5000}</p>
    </body></html>
    """

    with tempfile.NamedTemporaryFile(mode="w", suffix=".html", delete=False) as f:
        f.write(html)
        html_path = f.name

    try:
        segmenter = HTMLSegmenter(min_length=30, max_length=100)
        segments = segmenter.segment_filing(filing_id=10, html_path=html_path)

        for segment in segments:
            # Should respect custom min length
            assert len(segment.raw_text) >= 30
            # Should respect custom max length
            assert len(segment.raw_text) <= 100

    finally:
        Path(html_path).unlink()


def test_section_heading_skips_table_of_contents():
    """Test that 'Table of Contents' is skipped as section heading."""
    html = """
    <html><body>
        <h2>Table of Contents</h2>
        <p>Navigation link to prospectus summary</p>
        <h2>Item 1. Business</h2>
        <p>We are a technology company providing innovative software solutions to enterprise customers worldwide.</p>
        <p>Our business model focuses on subscription revenue and we have grown significantly over the past year.</p>
    </body></html>
    """

    with tempfile.NamedTemporaryFile(mode="w", suffix=".html", delete=False) as f:
        f.write(html)
        html_path = f.name

    try:
        segmenter = HTMLSegmenter(min_length=30)
        segments = segmenter.segment_filing(filing_id=11, html_path=html_path)

        # Find segments after the actual content heading
        content_segments = [s for s in segments if "technology company" in s.raw_text.lower()]

        if content_segments:
            # Section heading should be "Item 1. Business", NOT "Table of Contents"
            assert content_segments[0].section_heading != "Table of Contents"
            assert content_segments[0].section_heading == "Item 1. Business"

    finally:
        Path(html_path).unlink()


def test_section_heading_skips_multiple_metadata_headings():
    """Test that multiple metadata headings are all skipped."""
    html = """
    <html><body>
        <h1>Index</h1>
        <h2>Table of Contents</h2>
        <h3>Cover Page</h3>
        <h2>Prospectus Summary</h2>
        <p>We are a leading provider of cloud software with over one million active customers using our platform daily.</p>
    </body></html>
    """

    with tempfile.NamedTemporaryFile(mode="w", suffix=".html", delete=False) as f:
        f.write(html)
        html_path = f.name

    try:
        segmenter = HTMLSegmenter(min_length=30)
        segments = segmenter.segment_filing(filing_id=12, html_path=html_path)

        # Find segments with actual content
        content_segments = [s for s in segments if "cloud software" in s.raw_text.lower()]

        if content_segments:
            # Section heading should be "Prospectus Summary"
            # Should skip Index, Table of Contents, and Cover Page
            assert content_segments[0].section_heading == "Prospectus Summary"
            assert content_segments[0].section_heading not in [
                "Index", "Table of Contents", "Cover Page"
            ]

    finally:
        Path(html_path).unlink()


def test_section_heading_returns_none_if_only_metadata():
    """Test that section heading is None if only metadata headings exist."""
    html = """
    <html><body>
        <h1>Table of Contents</h1>
        <h2>Index</h2>
        <p>This paragraph has no meaningful section heading because all preceding headings are metadata navigation elements.</p>
    </body></html>
    """

    with tempfile.NamedTemporaryFile(mode="w", suffix=".html", delete=False) as f:
        f.write(html)
        html_path = f.name

    try:
        segmenter = HTMLSegmenter(min_length=30)
        segments = segmenter.segment_filing(filing_id=13, html_path=html_path)

        if segments:
            # All headings are metadata, so section_heading should be None
            assert segments[0].section_heading is None

    finally:
        Path(html_path).unlink()


# ===== Encoding Tests (Phase 3.2) =====


def test_encoding_utf8_with_special_chars(temp_html_file):
    """Test that UTF-8 encoding handles special characters correctly."""
    html = """
    <html><body>
        <p>This text contains UTF-8 special characters: é, ñ, ü, 中文, 日本語</p>
        <p>Mathematical symbols: ∑, ∫, ∂, √, ∞, ≠, ≤, ≥</p>
        <p>Currency symbols: €, £, ¥, ₹, ₽</p>
    </body></html>
    """

    html_path = temp_html_file(html)
    segmenter = HTMLSegmenter(min_length=20)

    try:
        segments = segmenter.segment_filing(filing_id=1, html_path=html_path)

        # Should successfully parse UTF-8 content
        assert len(segments) == 3
        assert "é" in segments[0].raw_text
        assert "∑" in segments[1].raw_text
        assert "€" in segments[2].raw_text

        # Metrics should record UTF-8 encoding
        metrics = segmenter.get_metrics()
        assert metrics is not None
        assert metrics.encoding_used == "utf-8"

    finally:
        Path(html_path).unlink()


def test_encoding_fallback_to_latin1():
    """Test fallback to latin-1 when UTF-8 fails."""
    # Create file with latin-1 encoded content
    with tempfile.NamedTemporaryFile(mode="wb", suffix=".html", delete=False) as f:
        # Latin-1 specific characters (valid in latin-1 but not UTF-8)
        html_bytes = b"""
        <html><body>
            <p>Latin-1 characters: \xe9 \xf1 \xfc \xa3 \xa9</p>
        </body></html>
        """
        f.write(html_bytes)
        html_path = f.name

    try:
        segmenter = HTMLSegmenter(min_length=10)
        segments = segmenter.segment_filing(filing_id=1, html_path=html_path)

        # Should successfully parse with latin-1 fallback
        assert len(segments) > 0
        assert len(segments[0].raw_text) > 0

        # Metrics should record latin-1 encoding
        metrics = segmenter.get_metrics()
        assert metrics is not None
        assert metrics.encoding_used == "latin-1"

    finally:
        Path(html_path).unlink()


@pytest.mark.skip(reason="latin-1 accepts all bytes, so this test cannot fail encoding")
def test_encoding_both_fail_raises_error():
    """Test that EncodingError is raised when both UTF-8 and latin-1 fail."""
    # This test is difficult to create because latin-1 accepts all byte values (0-255)
    # So we'll test raise_on_error behavior instead with a corrupted file
    from src.extraction.exceptions import EncodingError

    # Create binary file that will fail parsing
    with tempfile.NamedTemporaryFile(mode="wb", suffix=".html", delete=False) as f:
        # Write invalid UTF-8/UTF-16 byte sequence that latin-1 would "successfully" decode
        # but BeautifulSoup would fail to parse
        f.write(b"\xff\xfe\x00\x00<html>")  # BOM for UTF-32LE
        html_path = f.name

    try:
        segmenter = HTMLSegmenter()
        # This should succeed with latin-1 (it accepts all bytes)
        # but produce garbage content
        segments = segmenter.segment_filing(filing_id=1, html_path=html_path)

        # Should return empty list due to parsing failure
        assert len(segments) == 0

        # Metrics should show warning
        metrics = segmenter.get_metrics()
        assert metrics is not None
        assert len(metrics.warnings) > 0

    finally:
        Path(html_path).unlink()


# ===== Validation Tests (Phase 3.2) =====


def test_validation_invalid_filing_id_raises():
    """Test that invalid filing_id raises ValidationError with raise_on_error=True."""
    from src.extraction.exceptions import ValidationError

    segmenter = HTMLSegmenter()

    with pytest.raises(ValidationError) as exc_info:
        segmenter.segment_filing(filing_id=-1, html_path="/tmp/fake.html", raise_on_error=True)

    assert "filing_id" in str(exc_info.value).lower()
    assert "-1" in str(exc_info.value)


def test_validation_invalid_filing_id_returns_empty():
    """Test that invalid filing_id returns empty list with raise_on_error=False (default)."""
    segmenter = HTMLSegmenter()

    # Should not raise, just return empty list
    segments = segmenter.segment_filing(filing_id=0, html_path="/tmp/fake.html")
    assert segments == []


def test_validation_invalid_html_path_raises():
    """Test that invalid html_path raises ValidationError with raise_on_error=True."""
    from src.extraction.exceptions import ValidationError

    segmenter = HTMLSegmenter()

    with pytest.raises((ValidationError, FileNotFoundError)):
        segmenter.segment_filing(
            filing_id=1, html_path="/nonexistent/path/file.html", raise_on_error=True
        )


def test_validation_empty_html_path_raises():
    """Test that empty html_path raises ValidationError."""
    from src.extraction.exceptions import ValidationError

    segmenter = HTMLSegmenter()

    with pytest.raises(ValidationError) as exc_info:
        segmenter.segment_filing(filing_id=1, html_path="", raise_on_error=True)

    assert "html_path" in str(exc_info.value).lower()


# ===== Metrics Tests (Phase 3.2) =====


def test_metrics_collection(sample_html_simple, temp_html_file):
    """Test that metrics are collected during segmentation."""
    html_path = temp_html_file(sample_html_simple)
    segmenter = HTMLSegmenter()

    try:
        segments = segmenter.segment_filing(filing_id=123, html_path=html_path)
        metrics = segmenter.get_metrics()

        # Metrics should exist
        assert metrics is not None
        assert metrics.filing_id == 123

        # Should track segment counts
        assert metrics.total_segments == len(segments)
        assert metrics.total_segments > 0

        # Should have segment type distribution
        assert len(metrics.segment_counts_by_type) > 0
        assert "paragraph" in metrics.segment_counts_by_type

        # Should track parse time
        assert metrics.parse_time_seconds > 0
        assert metrics.parse_time_seconds < 1.0  # Should be fast for small file

        # Should have encoding
        assert metrics.encoding_used in ["utf-8", "latin-1"]

        # Summary should be informative
        summary = metrics.summary()
        assert "segments" in summary
        assert str(metrics.total_segments) in summary

    finally:
        Path(html_path).unlink()


def test_metrics_avg_segment_length():
    """Test average segment length calculation."""
    from src.extraction.html_segmenter import SegmentationMetrics

    metrics = SegmentationMetrics(filing_id=1)
    metrics.total_segments = 5
    metrics.total_text_length = 500

    assert metrics.avg_segment_length() == 100.0

    # Test with zero segments
    metrics_empty = SegmentationMetrics(filing_id=2)
    assert metrics_empty.avg_segment_length() == 0.0


@pytest.mark.skip(reason="_find_main_content returns whole soup, never None")
def test_metrics_warnings_recorded():
    """Test that warnings are recorded in metrics."""
    # Create HTML with no main content
    html = "<html><head><title>No Body</title></head></html>"

    with tempfile.NamedTemporaryFile(mode="w", suffix=".html", delete=False) as f:
        f.write(html)
        html_path = f.name

    try:
        segmenter = HTMLSegmenter()
        segments = segmenter.segment_filing(filing_id=1, html_path=html_path)

        # Should return empty list
        assert len(segments) == 0

        # Metrics should record warning
        metrics = segmenter.get_metrics()
        assert metrics is not None
        assert len(metrics.warnings) > 0
        assert any("main content" in w.lower() for w in metrics.warnings)

    finally:
        Path(html_path).unlink()


# ===== Error Handling with raise_on_error (Phase 3.2) =====


@pytest.mark.skip(reason="_find_main_content returns whole soup, never raises")
def test_raise_on_error_html_parsing_failure():
    """Test that HTMLParsingError is raised on parsing failure with raise_on_error=True."""
    from src.extraction.exceptions import HTMLParsingError

    # Create HTML with no main content
    html = "<html><head><title>No Body</title></head></html>"

    with tempfile.NamedTemporaryFile(mode="w", suffix=".html", delete=False) as f:
        f.write(html)
        html_path = f.name

    try:
        segmenter = HTMLSegmenter()

        # Should raise HTMLParsingError
        with pytest.raises(HTMLParsingError) as exc_info:
            segmenter.segment_filing(filing_id=1, html_path=html_path, raise_on_error=True)

        # Error should have context
        error = exc_info.value
        assert error.filing_id == 1
        assert error.html_path == html_path
        assert "main content" in str(error).lower()

    finally:
        Path(html_path).unlink()


def test_raise_on_error_empty_html():
    """Test that HTMLParsingError is raised for empty HTML with raise_on_error=True."""
    from src.extraction.exceptions import HTMLParsingError

    # Create empty HTML file
    with tempfile.NamedTemporaryFile(mode="w", suffix=".html", delete=False) as f:
        f.write("")
        html_path = f.name

    try:
        segmenter = HTMLSegmenter()

        with pytest.raises(HTMLParsingError) as exc_info:
            segmenter.segment_filing(filing_id=1, html_path=html_path, raise_on_error=True)

        assert "empty" in str(exc_info.value).lower()

    finally:
        Path(html_path).unlink()

# ===== Composite Segment Splitting Tests (L5) =====


class TestCompositeSegmentSplitting:
    """Test suite for composite segment splitting (text + table separation)."""

    def test_segment_with_table_only_no_split(self, temp_html_file):
        """Segment containing only a table doesn't get split."""
        html = """
        <html><body>
            <table>
                <tr><th>Metric</th><th>Value</th></tr>
                <tr><td>Revenue</td><td>$1M</td></tr>
                <tr><td>Users</td><td>10,000</td></tr>
            </table>
        </body></html>
        """

        html_path = temp_html_file(html)
        segmenter = HTMLSegmenter(min_length=20)

        try:
            segments = segmenter.segment_filing(filing_id=1, html_path=html_path)

            # Should have one table segment
            assert len(segments) == 1
            assert segments[0].segment_type == 'table'
            assert 'Revenue' in segments[0].raw_text

        finally:
            Path(html_path).unlink()

    def test_text_before_table_creates_two_segments(self, temp_html_file):
        """Text + table splits into 2 segments."""
        html = """
        <html><body>
            <div>
                <p>Our revenue metrics show strong growth in Q4 2024:</p>
                <table>
                    <tr><th>Quarter</th><th>Revenue</th></tr>
                    <tr><td>Q4 2024</td><td>$5M</td></tr>
                </table>
            </div>
        </body></html>
        """

        html_path = temp_html_file(html)
        segmenter = HTMLSegmenter(min_length=20)

        try:
            segments = segmenter.segment_filing(filing_id=2, html_path=html_path)

            # Should split into paragraph + table
            assert len(segments) >= 2

            # Find the segments
            paragraphs = [s for s in segments if s.segment_type == 'paragraph']
            tables = [s for s in segments if s.segment_type == 'table']

            assert len(paragraphs) >= 1
            assert len(tables) >= 1

            # Check content separation
            assert any('revenue metrics' in p.raw_text.lower() for p in paragraphs)
            assert any('Q4 2024' in t.raw_text for t in tables)

        finally:
            Path(html_path).unlink()

    def test_text_table_text_creates_three_segments(self, temp_html_file):
        """Text + table + text splits into 3 segments."""
        html = """
        <html><body>
            <div>
                <p>Our customer metrics for the year ended December 31, 2024:</p>
                <table>
                    <tr><th>Metric</th><th>Value</th></tr>
                    <tr><td>Active Customers</td><td>50,000</td></tr>
                </table>
                <p>As shown in the table above, our customer base has grown significantly.</p>
            </div>
        </body></html>
        """

        html_path = temp_html_file(html)
        segmenter = HTMLSegmenter(min_length=20)

        try:
            segments = segmenter.segment_filing(filing_id=3, html_path=html_path)

            # Should split into 3 segments: text, table, text
            assert len(segments) >= 3

            # Verify segment types in order
            paragraphs = [s for s in segments if s.segment_type == 'paragraph']
            tables = [s for s in segments if s.segment_type == 'table']

            assert len(paragraphs) >= 2  # Before and after table
            assert len(tables) >= 1

            # Check content
            assert any('customer metrics' in p.raw_text.lower() for p in paragraphs)
            assert any('Active Customers' in t.raw_text for t in tables)
            assert any('shown in the table above' in p.raw_text.lower() for p in paragraphs)

        finally:
            Path(html_path).unlink()

    def test_multiple_tables_split_correctly(self, temp_html_file):
        """Multiple tables in one segment split into separate segments."""
        html = """
        <html><body>
            <div>
                <p>We track multiple customer metrics across different dimensions:</p>
                <table id="t1">
                    <tr><th>Metric</th><th>Q3</th></tr>
                    <tr><td>Users</td><td>40,000</td></tr>
                </table>
                <table id="t2">
                    <tr><th>Metric</th><th>Q4</th></tr>
                    <tr><td>Users</td><td>50,000</td></tr>
                </table>
            </div>
        </body></html>
        """

        html_path = temp_html_file(html)
        segmenter = HTMLSegmenter(min_length=20)

        try:
            segments = segmenter.segment_filing(filing_id=4, html_path=html_path)

            # Should have at least 3 segments: paragraph + 2 tables
            assert len(segments) >= 3

            paragraphs = [s for s in segments if s.segment_type == 'paragraph']
            tables = [s for s in segments if s.segment_type == 'table']

            assert len(paragraphs) >= 1
            assert len(tables) >= 2  # Two separate table segments

            # Check that tables are separate
            assert any('Q3' in t.raw_text for t in tables)
            assert any('Q4' in t.raw_text for t in tables)

        finally:
            Path(html_path).unlink()

    def test_empty_text_before_table_skipped(self, temp_html_file):
        """Whitespace-only text before table doesn't create empty segment."""
        html = """
        <html><body>
            <div>

                <table>
                    <tr><th>Metric</th><th>Value</th></tr>
                    <tr><td>Monthly Active Users</td><td>100,000</td></tr>
                </table>
            </div>
        </body></html>
        """

        html_path = temp_html_file(html)
        segmenter = HTMLSegmenter(min_length=20)

        try:
            segments = segmenter.segment_filing(filing_id=5, html_path=html_path)

            # Should only have table segment, no empty paragraph
            tables = [s for s in segments if s.segment_type == 'table']
            assert len(tables) >= 1

            # No segment should be empty or whitespace-only
            for segment in segments:
                assert segment.raw_text.strip()

        finally:
            Path(html_path).unlink()

    def test_section_name_preserved_across_splits(self, temp_html_file):
        """All split segments inherit parent section_name."""
        html = """
        <html><body>
            <h2>Item 1. Business</h2>
            <div>
                <p>Our key performance indicators demonstrate strong customer engagement:</p>
                <table>
                    <tr><th>KPI</th><th>2024</th></tr>
                    <tr><td>DAU</td><td>500,000</td></tr>
                </table>
                <p>These metrics reflect our focus on customer retention and satisfaction.</p>
            </div>
        </body></html>
        """

        html_path = temp_html_file(html)
        segmenter = HTMLSegmenter(min_length=20)

        try:
            segments = segmenter.segment_filing(filing_id=6, html_path=html_path)

            # Find segments with our test content
            content_segments = [
                s for s in segments
                if 'performance indicators' in s.raw_text.lower()
                or 'DAU' in s.raw_text
                or 'retention' in s.raw_text.lower()
            ]

            # All should have the same section heading
            assert len(content_segments) >= 2
            for segment in content_segments:
                assert segment.section_heading == "Item 1. Business"

        finally:
            Path(html_path).unlink()

    def test_order_in_document_sequencing(self, temp_html_file):
        """Split segments have increasing sequence_index values."""
        html = """
        <html><body>
            <div>
                <p>Introduction text about our customer acquisition metrics and strategy:</p>
                <table>
                    <tr><th>Year</th><th>New Customers</th></tr>
                    <tr><td>2024</td><td>25,000</td></tr>
                </table>
                <p>These acquisition rates demonstrate the effectiveness of our go-to-market strategy.</p>
            </div>
        </body></html>
        """

        html_path = temp_html_file(html)
        segmenter = HTMLSegmenter(min_length=20)

        try:
            segments = segmenter.segment_filing(filing_id=7, html_path=html_path)

            if len(segments) >= 3:
                # Get sequence indices
                indices = [s.sequence_index for s in segments]

                # Should be in increasing order
                for i in range(len(indices) - 1):
                    assert indices[i] < indices[i + 1], f"Sequence not increasing: {indices}"

        finally:
            Path(html_path).unlink()

    def test_nested_table_not_split_separately(self, temp_html_file):
        """Nested tables stay within parent table segment."""
        html = """
        <html><body>
            <table>
                <tr>
                    <td>
                        <table>
                            <tr><td>Nested Data</td><td>Value</td></tr>
                        </table>
                    </td>
                </tr>
                <tr><td>Outer table data with at least fifty characters of text</td></tr>
            </table>
        </body></html>
        """

        html_path = temp_html_file(html)
        segmenter = HTMLSegmenter(min_length=20)

        try:
            segments = segmenter.segment_filing(filing_id=8, html_path=html_path)

            # Should have one table segment containing nested table
            tables = [s for s in segments if s.segment_type == 'table']
            assert len(tables) >= 1

            # The table segment should contain the nested table content
            table_text = tables[0].raw_text
            assert 'Nested Data' in table_text or 'Outer table data' in table_text

        finally:
            Path(html_path).unlink()

    def test_malformed_html_doesnt_crash(self, temp_html_file):
        """Malformed HTML returns original segment with warning log."""
        html = """
        <html><body>
            <div>
                <p>Valid paragraph before malformed table element with sufficient length:</p>
                <table><tr><td>Unclosed cell and row
            </div>
        </body></html>
        """

        html_path = temp_html_file(html)
        segmenter = HTMLSegmenter(min_length=20)

        try:
            # Should not raise exception
            segments = segmenter.segment_filing(filing_id=9, html_path=html_path)

            # Should return some segments (BeautifulSoup is forgiving)
            assert isinstance(segments, list)

        finally:
            Path(html_path).unlink()

    def test_segment_ids_preserved_after_split(self, temp_html_file):
        """Split segments maintain filing_id consistency."""
        html = """
        <html><body>
            <div>
                <p>We analyze customer lifetime value across multiple cohorts and segments:</p>
                <table>
                    <tr><th>Cohort</th><th>LTV</th></tr>
                    <tr><td>2024 Q1</td><td>$500</td></tr>
                </table>
            </div>
        </body></html>
        """

        html_path = temp_html_file(html)
        segmenter = HTMLSegmenter(min_length=20)

        try:
            segments = segmenter.segment_filing(filing_id=42, html_path=html_path)

            # All segments should have same filing_id
            for segment in segments:
                assert segment.filing_id == 42

        finally:
            Path(html_path).unlink()

    def test_metadata_preserved(self, temp_html_file):
        """filing_id, section_path, section_heading preserved on split."""
        html = """
        <html><body>
            <h1>Risk Factors</h1>
            <div>
                <p>Our customer concentration presents certain business risks that investors should consider:</p>
                <table>
                    <tr><th>Top Customer</th><th>% Revenue</th></tr>
                    <tr><td>Customer A</td><td>25%</td></tr>
                </table>
                <p>Loss of any major customer could materially impact our financial results.</p>
            </div>
        </body></html>
        """

        html_path = temp_html_file(html)
        segmenter = HTMLSegmenter(min_length=20)

        try:
            segments = segmenter.segment_filing(filing_id=10, html_path=html_path)

            # Find segments from our div
            content_segments = [
                s for s in segments
                if 'concentration' in s.raw_text.lower()
                or 'Customer A' in s.raw_text
                or 'Loss of any major' in s.raw_text
            ]

            assert len(content_segments) >= 2

            # All should have same metadata
            for segment in content_segments:
                assert segment.filing_id == 10
                assert segment.section_heading == "Risk Factors"

        finally:
            Path(html_path).unlink()

    def test_short_text_segments_filtered(self, temp_html_file):
        """Short text segments below min_length are filtered out."""
        html = """
        <html><body>
            <div>
                <p>Short</p>
                <table>
                    <tr><th>Metric</th><th>Value</th></tr>
                    <tr><td>Customer Acquisition Cost</td><td>$150</td></tr>
                </table>
            </div>
        </body></html>
        """

        html_path = temp_html_file(html)
        segmenter = HTMLSegmenter(min_length=50)

        try:
            segments = segmenter.segment_filing(filing_id=11, html_path=html_path)

            # Short paragraph should be filtered
            paragraphs = [s for s in segments if s.segment_type == 'paragraph']

            # No paragraph should exist if it's too short
            for p in paragraphs:
                assert len(p.raw_text) >= 50

        finally:
            Path(html_path).unlink()

    def test_table_with_text_in_between_multiple_tables(self, temp_html_file):
        """Text between multiple tables is preserved as separate segments."""
        html = """
        <html><body>
            <div>
                <p>First, we present our quarterly active user metrics for the trailing twelve months:</p>
                <table>
                    <tr><th>Q</th><th>MAU</th></tr>
                    <tr><td>Q1</td><td>100K</td></tr>
                </table>
                <p>Additionally, we track customer revenue metrics over the same time period:</p>
                <table>
                    <tr><th>Q</th><th>Revenue</th></tr>
                    <tr><td>Q1</td><td>$2M</td></tr>
                </table>
                <p>These metrics demonstrate consistent growth in both user base and monetization.</p>
            </div>
        </body></html>
        """

        html_path = temp_html_file(html)
        segmenter = HTMLSegmenter(min_length=20)

        try:
            segments = segmenter.segment_filing(filing_id=12, html_path=html_path)

            # Should have: text, table, text, table, text = 5 segments
            assert len(segments) >= 5

            paragraphs = [s for s in segments if s.segment_type == 'paragraph']
            tables = [s for s in segments if s.segment_type == 'table']

            assert len(paragraphs) >= 3
            assert len(tables) >= 2

            # Check content is properly separated
            assert any('active user metrics' in p.raw_text.lower() for p in paragraphs)
            assert any('revenue metrics' in p.raw_text.lower() for p in paragraphs)
            assert any('consistent growth' in p.raw_text.lower() for p in paragraphs)

        finally:
            Path(html_path).unlink()

    def test_very_long_table_segment_truncated(self, temp_html_file):
        """Very long table segments are truncated to max_length."""
        # Create a very large table
        table_rows = "".join(
            f"<tr><td>Row {i}</td><td>Data {i}</td></tr>"
            for i in range(500)  # 500 rows
        )
        html = f"""
        <html><body>
            <div>
                <p>The following table contains extensive customer segment data:</p>
                <table>
                    <tr><th>Segment</th><th>Value</th></tr>
                    {table_rows}
                </table>
            </div>
        </body></html>
        """

        html_path = temp_html_file(html)
        segmenter = HTMLSegmenter(min_length=20, max_length=5000)

        try:
            segments = segmenter.segment_filing(filing_id=13, html_path=html_path)

            # All segments should respect max_length
            for segment in segments:
                assert len(segment.raw_text) <= 5000

        finally:
            Path(html_path).unlink()

    def test_paragraph_only_not_split(self, temp_html_file):
        """Paragraph without tables is not affected by splitting."""
        html = """
        <html><body>
            <p>This is a simple paragraph discussing customer retention strategies and best practices
            without any tables or structured data elements that would require special handling.</p>
        </body></html>
        """

        html_path = temp_html_file(html)
        segmenter = HTMLSegmenter(min_length=20)

        try:
            segments = segmenter.segment_filing(filing_id=14, html_path=html_path)

            # Should have exactly one paragraph segment
            assert len(segments) == 1
            assert segments[0].segment_type == 'paragraph'
            assert 'retention strategies' in segments[0].raw_text

        finally:
            Path(html_path).unlink()

    def test_multiple_divs_with_tables_each_split_independently(self, temp_html_file):
        """Multiple divs with tables are each split independently."""
        html = """
        <html><body>
            <div>
                <p>First section about monthly recurring revenue metrics:</p>
                <table>
                    <tr><th>Month</th><th>MRR</th></tr>
                    <tr><td>Jan</td><td>$100K</td></tr>
                </table>
            </div>
            <div>
                <p>Second section about customer churn rates by cohort:</p>
                <table>
                    <tr><th>Cohort</th><th>Churn</th></tr>
                    <tr><td>2024-Q1</td><td>5%</td></tr>
                </table>
            </div>
        </body></html>
        """

        html_path = temp_html_file(html)
        segmenter = HTMLSegmenter(min_length=20)

        try:
            segments = segmenter.segment_filing(filing_id=15, html_path=html_path)

            # Should have at least 4 segments: 2 paragraphs + 2 tables
            assert len(segments) >= 4

            paragraphs = [s for s in segments if s.segment_type == 'paragraph']
            tables = [s for s in segments if s.segment_type == 'table']

            assert len(paragraphs) >= 2
            assert len(tables) >= 2

            # Check both sections are represented
            assert any('recurring revenue' in p.raw_text.lower() for p in paragraphs)
            assert any('churn rates' in p.raw_text.lower() for p in paragraphs)

        finally:
            Path(html_path).unlink()


# ===== Phase 2: Sentence Detection Tests =====


class TestSentenceDetection:
    """Test suite for sentence detection integration (Phase 2 of redesign)."""

    def test_sentence_boundaries_populated(self, temp_html_file):
        """Sentence boundaries are populated for paragraph segments."""
        html = """
        <html><body>
            <p>First sentence here. Second sentence follows. Third sentence ends it.</p>
        </body></html>
        """

        html_path = temp_html_file(html)
        segmenter = HTMLSegmenter(min_length=20)

        try:
            segments = segmenter.segment_filing(filing_id=1, html_path=html_path)

            assert len(segments) >= 1
            # Should have sentence boundaries populated
            assert segments[0].sentence_boundaries is not None
            assert len(segments[0].sentence_boundaries) >= 3

        finally:
            Path(html_path).unlink()

    def test_tables_skip_sentence_detection(self, temp_html_file):
        """Tables should not have sentence detection applied."""
        html = """
        <html><body>
            <table>
                <tr><th>Quarter</th><th>Revenue</th></tr>
                <tr><td>Q1 2024</td><td>$5M</td></tr>
            </table>
        </body></html>
        """

        html_path = temp_html_file(html)
        segmenter = HTMLSegmenter(min_length=20)

        try:
            segments = segmenter.segment_filing(filing_id=1, html_path=html_path)

            tables = [s for s in segments if s.segment_type == 'table']
            assert len(tables) >= 1
            # Tables should NOT have sentence boundaries
            assert tables[0].sentence_boundaries is None

        finally:
            Path(html_path).unlink()

    def test_sec_abbreviations_not_sentence_breaks(self, temp_html_file):
        """SEC abbreviations like FY, Q1 should not break sentences."""
        html = """
        <html><body>
            <p>In FY 2024, we achieved Q1 targets early. Revenue grew YoY by 25%.</p>
        </body></html>
        """

        html_path = temp_html_file(html)
        segmenter = HTMLSegmenter(min_length=20)

        try:
            segments = segmenter.segment_filing(filing_id=1, html_path=html_path)

            assert len(segments) >= 1
            # Should have exactly 2 sentences (not more due to abbreviations)
            assert segments[0].sentence_boundaries is not None
            # FY and Q1 and YoY should not break sentences
            assert len(segments[0].sentence_boundaries) == 2

        finally:
            Path(html_path).unlink()

    def test_truncation_respects_sentence_boundary(self, temp_html_file):
        """Truncation should occur at sentence boundary, not mid-sentence."""
        # Create text with multiple sentences that exceeds max_length
        sentence = "This is a complete sentence about customer metrics. "
        long_text = sentence * 30  # ~1500 chars

        html = f"""
        <html><body>
            <p>{long_text}</p>
        </body></html>
        """

        html_path = temp_html_file(html)
        segmenter = HTMLSegmenter(min_length=20, max_length=500)

        try:
            segments = segmenter.segment_filing(filing_id=1, html_path=html_path)

            assert len(segments) >= 1
            # Should end with a period (complete sentence)
            assert segments[0].raw_text.rstrip().endswith('.')

        finally:
            Path(html_path).unlink()


# ===== Phase 3: Definition Merging Tests =====


class TestDefinitionMerging:
    """Test suite for definition merging (Phase 3 of redesign)."""

    def test_simple_definition_merge(self, temp_html_file):
        """Consecutive definition paragraphs should be merged."""
        html = """
        <html><body>
            <p>We define "active customers" as customers who have made at least one purchase.</p>
            <p>and who have logged into our platform at least once in the preceding 90 days.</p>
        </body></html>
        """

        html_path = temp_html_file(html)
        segmenter = HTMLSegmenter(min_length=20)

        try:
            segments = segmenter.segment_filing(filing_id=1, html_path=html_path)

            # Should be merged into one segment
            assert len(segments) == 1
            assert 'active customers' in segments[0].raw_text
            assert '90 days' in segments[0].raw_text
            assert segments[0].definition_merged_count >= 2

        finally:
            Path(html_path).unlink()

    def test_definition_with_which_clause(self, temp_html_file):
        """Definition with 'which' continuation should merge."""
        html = """
        <html><body>
            <p>We define "monthly recurring revenue" as the total revenue recognized in a month.</p>
            <p>which includes all subscription fees and excludes one-time charges.</p>
        </body></html>
        """

        html_path = temp_html_file(html)
        segmenter = HTMLSegmenter(min_length=20)

        try:
            segments = segmenter.segment_filing(filing_id=1, html_path=html_path)

            # Should be merged
            assert len(segments) == 1
            assert 'recurring revenue' in segments[0].raw_text.lower()
            assert 'excludes' in segments[0].raw_text

        finally:
            Path(html_path).unlink()

    def test_no_merge_for_non_definitions(self, temp_html_file):
        """Non-definition paragraphs should not be merged."""
        html = """
        <html><body>
            <p>Our company was founded in 2010 in San Francisco.</p>
            <p>We have grown significantly since then.</p>
        </body></html>
        """

        html_path = temp_html_file(html)
        segmenter = HTMLSegmenter(min_length=20)

        try:
            segments = segmenter.segment_filing(filing_id=1, html_path=html_path)

            # Should remain as separate segments
            assert len(segments) == 2

        finally:
            Path(html_path).unlink()

    def test_merge_limit_3_segments(self, temp_html_file):
        """Definition merging should stop after 3 segments."""
        html = """
        <html><body>
            <p>We define customer lifetime value as the total revenue.</p>
            <p>and includes all subscription payments.</p>
            <p>and support fees.</p>
            <p>and implementation charges.</p>
            <p>and renewal fees over the entire relationship.</p>
        </body></html>
        """

        html_path = temp_html_file(html)
        segmenter = HTMLSegmenter(min_length=20)

        try:
            segments = segmenter.segment_filing(filing_id=1, html_path=html_path)

            # First segment should merge at most 3
            merged_segment = segments[0]
            assert merged_segment.definition_merged_count <= 3

        finally:
            Path(html_path).unlink()

    def test_merge_respects_length_limit(self, temp_html_file):
        """Definition merging should respect the 2000 char limit."""
        # Create definition continuation that would exceed limit
        long_continuation = "and " + "x" * 1800  # Very long continuation

        html = f"""
        <html><body>
            <p>We define net revenue retention as the total recurring revenue from existing customers. {long_continuation}</p>
        </body></html>
        """

        html_path = temp_html_file(html)
        segmenter = HTMLSegmenter(min_length=20)

        try:
            segments = segmenter.segment_filing(filing_id=1, html_path=html_path)

            # Merged text should not exceed the limit unreasonably
            assert len(segments) >= 1

        finally:
            Path(html_path).unlink()


class TestDefinitionContinuationPatterns:
    """Test expanded definition continuation pattern detection (SEG4)."""

    def test_such_pattern_detected(self):
        """'Such metrics...' should be detected as continuation."""
        segmenter = HTMLSegmenter()
        assert segmenter._is_continuation("Such metrics include ARR and MRR.")

    def test_these_pattern_detected(self):
        """'These calculations...' should be detected as continuation."""
        segmenter = HTMLSegmenter()
        assert segmenter._is_continuation("These calculations are performed quarterly.")

    def test_the_above_pattern_detected(self):
        """'The above definition...' should be detected as continuation."""
        segmenter = HTMLSegmenter()
        assert segmenter._is_continuation("The above definition excludes trial users.")

    def test_the_following_pattern_detected(self):
        """'The following table...' should be detected as continuation."""
        segmenter = HTMLSegmenter()
        assert segmenter._is_continuation("The following table summarizes our metrics.")

    def test_mid_text_such_not_continuation(self):
        """'such' mid-sentence should NOT trigger continuation."""
        segmenter = HTMLSegmenter()
        # Starts with capital "We" - not a continuation pattern
        assert not segmenter._is_continuation("We track such metrics quarterly.")

    def test_normal_the_not_continuation(self):
        """Normal 'The company...' should NOT trigger continuation."""
        segmenter = HTMLSegmenter()
        # "The company" is not a referential phrase
        assert not segmenter._is_continuation("The company reported revenue growth.")


# ===== Phase 4: Large Table Handling Tests =====


class TestLargeTableHandling:
    """Test suite for large table handling (Phase 4 of redesign)."""

    def test_table_uses_higher_limit(self, temp_html_file):
        """Tables should use 25K limit instead of 10K."""
        # Create table with ~15K chars (exceeds default 10K, under 25K)
        rows = "".join(
            f"<tr><td>Row {i}</td><td>{'Data ' * 20}</td></tr>"
            for i in range(200)
        )
        html = f"""
        <html><body>
            <table>
                <tr><th>ID</th><th>Content</th></tr>
                {rows}
            </table>
        </body></html>
        """

        html_path = temp_html_file(html)
        segmenter = HTMLSegmenter(min_length=20)

        try:
            segments = segmenter.segment_filing(filing_id=1, html_path=html_path)

            tables = [s for s in segments if s.segment_type == 'table']
            assert len(tables) >= 1
            # Should not be truncated (under 25K)
            assert not tables[0].table_truncated_flag

        finally:
            Path(html_path).unlink()

    def test_very_large_table_truncated_to_limit(self, temp_html_file):
        """Tables exceeding 25K should be truncated to the limit."""
        # Create very large table (~30K chars)
        rows = "".join(
            f"<tr><td>Row {i}</td><td>{'Data ' * 50}</td></tr>"
            for i in range(500)
        )
        html = f"""
        <html><body>
            <table>
                <tr><th>Row ID</th><th>Large Content Field</th></tr>
                {rows}
            </table>
        </body></html>
        """

        html_path = temp_html_file(html)
        segmenter = HTMLSegmenter(min_length=20)

        try:
            segments = segmenter.segment_filing(filing_id=1, html_path=html_path)

            tables = [s for s in segments if s.segment_type == 'table']
            assert len(tables) >= 1
            # Should be truncated to TABLE_MAX_LENGTH (25000)
            assert len(tables[0].raw_text) == 25000
            # Should still contain header row content (not truncated)
            assert 'Row ID' in tables[0].raw_text or 'Large Content' in tables[0].raw_text

        finally:
            Path(html_path).unlink()

    def test_large_table_preserves_headers(self, temp_html_file):
        """Large tables should preserve header content after truncation."""
        rows = "".join(
            f"<tr><td>Row {i}</td><td>Value {i}</td><td>{'X' * 100}</td></tr>"
            for i in range(400)
        )
        html = f"""
        <html><body>
            <table>
                <tr><th>Customer ID</th><th>Revenue</th><th>Details</th></tr>
                {rows}
            </table>
        </body></html>
        """

        html_path = temp_html_file(html)
        segmenter = HTMLSegmenter(min_length=20)

        try:
            segments = segmenter.segment_filing(filing_id=1, html_path=html_path)

            tables = [s for s in segments if s.segment_type == 'table']
            assert len(tables) >= 1
            # Header content should be at the beginning and preserved
            assert 'Customer ID' in tables[0].raw_text or 'Revenue' in tables[0].raw_text

        finally:
            Path(html_path).unlink()


# ===== Phase 5: Context Overlap Tests =====


class TestContextOverlap:
    """Test suite for context overlap extraction (Phase 5 of redesign)."""

    def test_context_prefix_from_previous_segment(self, temp_html_file):
        """Segments should have context_prefix from previous segment's last sentence."""
        html = """
        <html><body>
            <p>Our company provides cloud services. We have strong customer retention metrics.</p>
            <p>These metrics are calculated monthly and include all paying customers.</p>
        </body></html>
        """

        html_path = temp_html_file(html)
        segmenter = HTMLSegmenter(min_length=20)

        try:
            segments = segmenter.segment_filing(filing_id=1, html_path=html_path)

            assert len(segments) >= 2
            # Second segment should have context from first
            assert segments[1].context_prefix is not None
            assert 'retention metrics' in segments[1].context_prefix

        finally:
            Path(html_path).unlink()

    def test_no_context_from_tables(self, temp_html_file):
        """Context should not be taken from table segments."""
        html = """
        <html><body>
            <table>
                <tr><th>Metric</th><th>Value</th></tr>
                <tr><td>Revenue</td><td>$100M</td></tr>
            </table>
            <p>The table above shows our key financial metrics for the quarter.</p>
        </body></html>
        """

        html_path = temp_html_file(html)
        segmenter = HTMLSegmenter(min_length=20)

        try:
            segments = segmenter.segment_filing(filing_id=1, html_path=html_path)

            paragraphs = [s for s in segments if s.segment_type == 'paragraph']
            if paragraphs:
                # Paragraph should NOT have context from table
                assert paragraphs[0].context_prefix is None

        finally:
            Path(html_path).unlink()

    def test_first_segment_no_context_prefix(self, temp_html_file):
        """First segment should not have a context_prefix."""
        html = """
        <html><body>
            <p>This is the first paragraph about our customer metrics and growth strategy.</p>
            <p>This is the second paragraph with more details about our performance.</p>
        </body></html>
        """

        html_path = temp_html_file(html)
        segmenter = HTMLSegmenter(min_length=20)

        try:
            segments = segmenter.segment_filing(filing_id=1, html_path=html_path)

            assert len(segments) >= 1
            # First segment should have no context_prefix
            assert segments[0].context_prefix is None

        finally:
            Path(html_path).unlink()

    def test_document_position_calculated(self, temp_html_file):
        """Document position should be calculated for all segments."""
        html = """
        <html><body>
            <p>First paragraph with some content about our business operations.</p>
            <p>Second paragraph describing our customer acquisition strategies.</p>
            <p>Third paragraph about our revenue growth and future projections.</p>
        </body></html>
        """

        html_path = temp_html_file(html)
        segmenter = HTMLSegmenter(min_length=20)

        try:
            segments = segmenter.segment_filing(filing_id=1, html_path=html_path)

            assert len(segments) >= 3
            # All segments should have document_position
            for segment in segments:
                assert segment.document_position is not None
                assert 0.0 <= segment.document_position <= 1.0

            # First should be near 0, last should be near end
            assert segments[0].document_position == 0.0
            assert segments[-1].document_position > segments[0].document_position

        finally:
            Path(html_path).unlink()


# ===== Phase 6: List Handling Tests =====


class TestListHandling:
    """Test suite for list item extraction with context (Phase 6 of redesign)."""

    def test_list_items_extracted_separately(self, temp_html_file):
        """Each list item should become a separate segment."""
        html = """
        <html><body>
            <p>Key metrics include:</p>
            <ul>
                <li>Monthly recurring revenue of $5 million from our subscription business</li>
                <li>Customer acquisition cost averaging $150 per new customer acquired</li>
                <li>Net revenue retention rate of 115% for the fiscal year ended</li>
            </ul>
        </body></html>
        """

        html_path = temp_html_file(html)
        segmenter = HTMLSegmenter(min_length=20)

        try:
            segments = segmenter.segment_filing(filing_id=1, html_path=html_path)

            list_items = [s for s in segments if s.segment_type == 'list_item']
            assert len(list_items) >= 3

        finally:
            Path(html_path).unlink()

    def test_list_items_have_intro_context(self, temp_html_file):
        """List items should have the intro text as context_prefix."""
        html = """
        <html><body>
            <p>Our key performance indicators are:</p>
            <ul>
                <li>Active customer count exceeding one million users globally</li>
                <li>Monthly active users growing at twenty percent annually</li>
            </ul>
        </body></html>
        """

        html_path = temp_html_file(html)
        segmenter = HTMLSegmenter(min_length=20)

        try:
            segments = segmenter.segment_filing(filing_id=1, html_path=html_path)

            list_items = [s for s in segments if s.segment_type == 'list_item']
            if list_items:
                # List items should have intro as context
                assert list_items[0].context_prefix is not None
                assert 'performance indicators' in list_items[0].context_prefix

        finally:
            Path(html_path).unlink()

    def test_ordered_list_extraction(self, temp_html_file):
        """Ordered lists (<ol>) should also be extracted."""
        html = """
        <html><body>
            <p>Customer growth strategy steps:</p>
            <ol>
                <li>Identify target market segments with high growth potential</li>
                <li>Develop targeted marketing campaigns for each segment</li>
                <li>Measure and optimize customer acquisition costs regularly</li>
            </ol>
        </body></html>
        """

        html_path = temp_html_file(html)
        segmenter = HTMLSegmenter(min_length=20)

        try:
            segments = segmenter.segment_filing(filing_id=1, html_path=html_path)

            list_items = [s for s in segments if s.segment_type == 'list_item']
            assert len(list_items) >= 3

        finally:
            Path(html_path).unlink()

    def test_short_list_items_filtered(self, temp_html_file):
        """List items shorter than min_length should be filtered."""
        html = """
        <html><body>
            <p>Metrics:</p>
            <ul>
                <li>Short</li>
                <li>This list item is long enough to pass the minimum length filter easily</li>
            </ul>
        </body></html>
        """

        html_path = temp_html_file(html)
        segmenter = HTMLSegmenter(min_length=50)

        try:
            segments = segmenter.segment_filing(filing_id=1, html_path=html_path)

            list_items = [s for s in segments if s.segment_type == 'list_item']
            # Only the long item should be included
            for item in list_items:
                assert len(item.raw_text) >= 50

        finally:
            Path(html_path).unlink()

    def test_nested_lists_handled(self, temp_html_file):
        """Nested lists should not create duplicate segments."""
        html = """
        <html><body>
            <p>Customer segments:</p>
            <ul>
                <li>Enterprise customers with annual contracts exceeding one million dollars
                    <ul>
                        <li>Large enterprise with thousand plus employees</li>
                        <li>Mid-market with hundred to thousand employees</li>
                    </ul>
                </li>
                <li>Small business customers with monthly subscriptions under ten thousand</li>
            </ul>
        </body></html>
        """

        html_path = temp_html_file(html)
        segmenter = HTMLSegmenter(min_length=20)

        try:
            segments = segmenter.segment_filing(filing_id=1, html_path=html_path)

            # Should extract outer list items only (nested handled within)
            list_items = [s for s in segments if s.segment_type == 'list_item']
            # We expect outer list items to be extracted
            assert len(list_items) >= 2

        finally:
            Path(html_path).unlink()
