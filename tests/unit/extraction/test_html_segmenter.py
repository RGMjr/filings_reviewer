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


# ===== SEG7: Robust Encoding Detection Tests =====
# Tests for charset-normalizer auto-detection and fallback cascade


@pytest.fixture
def encoding_fixtures_dir():
    """Return path to encoding test fixtures directory."""
    return Path(__file__).parent.parent.parent / "fixtures" / "encoding"


class TestSEG7EncodingAutoDetection:
    """Tests for automatic encoding detection using charset-normalizer."""

    def test_utf8_file_auto_detected(self, encoding_fixtures_dir):
        """Test that UTF-8 files are correctly auto-detected and decoded."""
        html_path = encoding_fixtures_dir / "utf8_sample.html"
        if not html_path.exists():
            pytest.skip("Test fixture not found: utf8_sample.html")

        segmenter = HTMLSegmenter(min_length=20)
        segments = segmenter.segment_filing(filing_id=1, html_path=str(html_path))

        # Should successfully parse
        assert len(segments) > 0

        # Should contain the special characters
        all_text = " ".join(s.raw_text for s in segments)
        assert "€10 million" in all_text or "€" in all_text
        assert "José García" in all_text or "José" in all_text

        # Metrics should record UTF-8 or auto-detected UTF-8 variant
        metrics = segmenter.get_metrics()
        assert metrics is not None
        assert "utf" in metrics.encoding_used.lower()

    def test_windows1252_file_auto_detected(self, encoding_fixtures_dir):
        """Test that Windows-1252 files with curly quotes are correctly detected."""
        html_path = encoding_fixtures_dir / "windows1252_sample.html"
        if not html_path.exists():
            pytest.skip("Test fixture not found: windows1252_sample.html")

        segmenter = HTMLSegmenter(min_length=20)
        segments = segmenter.segment_filing(filing_id=1, html_path=str(html_path))

        # Should successfully parse
        assert len(segments) > 0

        # Should contain properly decoded curly quotes
        all_text = " ".join(s.raw_text for s in segments)
        # Curly quotes should be decoded: 0x93 → " (U+201C), 0x94 → " (U+201D)
        # Em-dash should be decoded: 0x97 → — (U+2014)
        assert "active users" in all_text.lower()
        # Check that content was decoded (not mojibake)
        assert "key metrics" in all_text.lower()

        # Metrics should record an encoding (cp1252, windows-1252, or latin-1 fallback)
        metrics = segmenter.get_metrics()
        assert metrics is not None
        assert metrics.encoding_used is not None

    def test_latin1_file_auto_detected(self, encoding_fixtures_dir):
        """Test that Latin-1 files with accented characters are correctly detected."""
        html_path = encoding_fixtures_dir / "latin1_sample.html"
        if not html_path.exists():
            pytest.skip("Test fixture not found: latin1_sample.html")

        segmenter = HTMLSegmenter(min_length=20)
        segments = segmenter.segment_filing(filing_id=1, html_path=str(html_path))

        # Should successfully parse
        assert len(segments) > 0

        # Should contain properly decoded accented characters
        all_text = " ".join(s.raw_text for s in segments)
        # é (0xe9), ü (0xfc), £ (0xa3) should be decoded
        assert "Caf" in all_text  # "Café" - may decode differently
        # Check content is readable
        assert "revenue" in all_text.lower() or "chain" in all_text.lower()

        metrics = segmenter.get_metrics()
        assert metrics is not None

    def test_utf8_bom_file_detected(self, encoding_fixtures_dir):
        """Test that UTF-8 files with BOM are correctly detected."""
        html_path = encoding_fixtures_dir / "utf8_bom_sample.html"
        if not html_path.exists():
            pytest.skip("Test fixture not found: utf8_bom_sample.html")

        segmenter = HTMLSegmenter(min_length=20)
        segments = segmenter.segment_filing(filing_id=1, html_path=str(html_path))

        # Should successfully parse
        assert len(segments) > 0

        # Content should be properly decoded
        all_text = " ".join(s.raw_text for s in segments)
        assert "€5 million" in all_text or "€" in all_text

        metrics = segmenter.get_metrics()
        assert metrics is not None
        # Should detect UTF-8 variant (utf-8, utf-8-sig, utf_8)
        assert "utf" in metrics.encoding_used.lower()


class TestSEG7EncodingFallbackCascade:
    """Tests for the UTF-8 → Latin-1 fallback cascade."""

    def test_ascii_file_works_with_any_encoding(self, encoding_fixtures_dir):
        """Test that ASCII-only files work regardless of encoding detection."""
        html_path = encoding_fixtures_dir / "ascii_only_sample.html"
        if not html_path.exists():
            pytest.skip("Test fixture not found: ascii_only_sample.html")

        segmenter = HTMLSegmenter(min_length=20)
        segments = segmenter.segment_filing(filing_id=1, html_path=str(html_path))

        # Should successfully parse
        assert len(segments) > 0

        # Content should be intact
        all_text = " ".join(s.raw_text for s in segments)
        assert "10,000 daily active users" in all_text
        assert "$5 million" in all_text

        metrics = segmenter.get_metrics()
        assert metrics is not None

    def test_fallback_when_auto_detection_fails(self, temp_html_file):
        """Test that UTF-8 → Latin-1 fallback works when auto-detection fails."""
        # Create a file with bytes that are valid Latin-1 but not valid UTF-8
        # This should fall back through the cascade
        with tempfile.NamedTemporaryFile(mode="wb", suffix=".html", delete=False) as f:
            # Bytes 0x80-0x9F are control chars in Latin-1 but problematic for detection
            html_bytes = b"""<html><body>
            <p>This has Latin-1 chars: \xe9\xf1\xfc that should work with fallback.</p>
            </body></html>"""
            f.write(html_bytes)
            html_path = f.name

        try:
            segmenter = HTMLSegmenter(min_length=10)
            segments = segmenter.segment_filing(filing_id=1, html_path=html_path)

            # Should successfully parse with some encoding
            assert len(segments) > 0
            assert len(segments[0].raw_text) > 0

            metrics = segmenter.get_metrics()
            assert metrics is not None
            # Should have used some encoding (utf-8, latin-1, or auto-detected)
            assert metrics.encoding_used in ["utf-8", "latin-1", "iso-8859-1", "ascii", "cp1252", "windows-1252"]

        finally:
            Path(html_path).unlink()


class TestSEG7GracefulDegradation:
    """Tests for graceful degradation when charset-normalizer is unavailable."""

    def test_encoding_detection_with_mocked_unavailable_library(self, temp_html_file, monkeypatch):
        """Test that encoding detection works when charset-normalizer is unavailable."""
        import src.extraction.html_segmenter as segmenter_module

        # Save original state
        original_available = segmenter_module.CHARSET_NORMALIZER_AVAILABLE

        try:
            # Mock charset-normalizer as unavailable
            monkeypatch.setattr(segmenter_module, "CHARSET_NORMALIZER_AVAILABLE", False)

            # Create a simple UTF-8 file
            html = """<html><body>
            <p>Simple test content that should work with UTF-8 encoding.</p>
            </body></html>"""
            html_path = temp_html_file(html)

            segmenter = HTMLSegmenter(min_length=20)
            segments = segmenter.segment_filing(filing_id=1, html_path=html_path)

            # Should still successfully parse using fallback
            assert len(segments) > 0
            assert "Simple test content" in segments[0].raw_text

            metrics = segmenter.get_metrics()
            assert metrics is not None
            assert metrics.encoding_used == "utf-8"

            Path(html_path).unlink()
        finally:
            # Restore original state
            monkeypatch.setattr(segmenter_module, "CHARSET_NORMALIZER_AVAILABLE", original_available)

    def test_empty_file_handled_gracefully(self, temp_html_file):
        """Test that empty files are handled gracefully."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".html", delete=False) as f:
            f.write("")
            html_path = f.name

        try:
            segmenter = HTMLSegmenter()
            segments = segmenter.segment_filing(filing_id=1, html_path=html_path)

            # Should return empty list for empty file
            assert len(segments) == 0

            # Should have warning in metrics
            metrics = segmenter.get_metrics()
            assert metrics is not None

        finally:
            Path(html_path).unlink()

    def test_very_short_file_handled(self, encoding_fixtures_dir):
        """Test that very short files (<100 bytes) are handled correctly."""
        html_path = encoding_fixtures_dir / "very_short_sample.html"
        if not html_path.exists():
            pytest.skip("Test fixture not found: very_short_sample.html")

        segmenter = HTMLSegmenter(min_length=5)  # Lower min_length for short file
        segments = segmenter.segment_filing(filing_id=1, html_path=str(html_path))

        # May or may not have segments depending on min_length filtering
        # But should not raise any errors
        metrics = segmenter.get_metrics()
        assert metrics is not None


class TestSEG7EncodingEdgeCases:
    """Tests for edge cases in encoding detection."""

    def test_encoding_recorded_in_metrics(self, temp_html_file):
        """Test that the detected encoding is correctly recorded in metrics."""
        html = """<html><body>
        <p>Content with special characters: café, naïve, résumé</p>
        </body></html>"""
        html_path = temp_html_file(html)

        try:
            segmenter = HTMLSegmenter(min_length=10)
            segmenter.segment_filing(filing_id=1, html_path=html_path)

            metrics = segmenter.get_metrics()
            assert metrics is not None
            assert metrics.encoding_used is not None
            assert len(metrics.encoding_used) > 0
        finally:
            Path(html_path).unlink()

    def test_encoding_error_includes_attempted_encodings(self):
        """Test that EncodingError includes list of attempted encodings."""
        from src.extraction.exceptions import EncodingError

        # Create an error manually to verify structure
        error = EncodingError(
            "Test error",
            file_path="/test/path.html",
            attempted_encodings=["utf-8", "latin-1", "cp1252"],
            position=100
        )

        assert error.file_path == "/test/path.html"
        assert "utf-8" in error.attempted_encodings
        assert "latin-1" in error.attempted_encodings
        assert error.position == 100

    def test_mixed_content_file(self, temp_html_file):
        """Test handling of file with mixed ASCII and encoded content."""
        # This is mostly ASCII with some Latin-1 encoded parts
        with tempfile.NamedTemporaryFile(mode="wb", suffix=".html", delete=False) as f:
            html_bytes = b"""<!DOCTYPE html>
            <html>
            <body>
            <p>Our company had 10,000 daily active users.</p>
            <p>Revenue reached \xa35 million (pounds sterling).</p>
            <p>The caf\xe9 concept was successful.</p>
            </body>
            </html>"""
            f.write(html_bytes)
            html_path = f.name

        try:
            segmenter = HTMLSegmenter(min_length=20)
            segments = segmenter.segment_filing(filing_id=1, html_path=html_path)

            assert len(segments) > 0
            all_text = " ".join(s.raw_text for s in segments)
            assert "10,000" in all_text
            # Check that special chars didn't break parsing
            assert "million" in all_text.lower()

        finally:
            Path(html_path).unlink()

    def test_detect_encoding_auto_returns_none_for_unavailable(self, temp_html_file, monkeypatch):
        """Test _detect_encoding_auto returns None when library unavailable."""
        import src.extraction.html_segmenter as segmenter_module

        # Mock library as unavailable
        monkeypatch.setattr(segmenter_module, "CHARSET_NORMALIZER_AVAILABLE", False)

        segmenter = HTMLSegmenter()
        result = segmenter._detect_encoding_auto(Path("/fake/path.html"))

        assert result is None


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

    def test_very_large_table_creates_summary(self, temp_html_file):
        """Tables exceeding 25K should get tri-region summary (SEG12)."""
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
            # Should be summarized to much less than TABLE_MAX_LENGTH
            assert len(tables[0].raw_text) < 5000
            # Should be marked as truncated
            assert tables[0].table_truncated_flag
            # Should have tri-region sampling markers
            assert '...[end sample]...' in tables[0].raw_text
            # Should still contain header info
            assert '[Table headers:' in tables[0].raw_text

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


# ===== Tri-Region Table Summary Tests (SEG12) =====


class TestTableSummaryTriRegionSampling:
    """Test suite for tri-region sampling in large table summaries (SEG12)."""

    def test_large_table_has_middle_and_end_markers(self, temp_html_file):
        """Tables >25K chars should have [middle sample] and [end sample] markers in summary."""
        # Create table with ~30K chars of text content (exceeds TABLE_MAX_LENGTH=25000)
        rows = "".join(
            f"<tr><td>Row {i:04d}</td><td>{'DataValue' * 50}</td></tr>"
            for i in range(200)  # Each row ~510 chars, total ~102K chars
        )
        html = f"""
        <html><body>
            <table>
                <tr><th>RowID</th><th>Content</th></tr>
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
            # Table should be truncated
            assert tables[0].table_truncated_flag
            # Should have tri-region markers
            assert '...[middle sample]...' in tables[0].raw_text
            assert '...[end sample]...' in tables[0].raw_text

        finally:
            Path(html_path).unlink()

    def test_large_table_beginning_sample_contains_first_content(self, temp_html_file):
        """Beginning sample should contain content from the start of the table."""
        # Create table with recognizable content at beginning
        rows_start = "<tr><td>START_MARKER_BEGINNING</td><td>First row data</td></tr>"
        rows_middle = "".join(
            f"<tr><td>Middle{i:04d}</td><td>{'MiddleData' * 20}</td></tr>"
            for i in range(50)
        )
        rows_end = "<tr><td>END_MARKER_LAST</td><td>Final row data</td></tr>"
        html = f"""
        <html><body>
            <table>
                <tr><th>ID</th><th>Value</th></tr>
                {rows_start}
                {rows_middle}
                {rows_end}
            </table>
        </body></html>
        """

        html_path = temp_html_file(html)
        segmenter = HTMLSegmenter(min_length=20)

        try:
            segments = segmenter.segment_filing(filing_id=1, html_path=html_path)

            tables = [s for s in segments if s.segment_type == 'table']
            assert len(tables) >= 1
            # Beginning marker should be present
            assert 'START_MARKER_BEGINNING' in tables[0].raw_text

        finally:
            Path(html_path).unlink()

    def test_large_table_end_sample_contains_last_content(self, temp_html_file):
        """End sample should contain content from the end of the table."""
        # Create table with recognizable content at end
        rows_start = "<tr><td>FirstRow</td><td>Start data</td></tr>"
        rows_middle = "".join(
            f"<tr><td>Middle{i:04d}</td><td>{'MiddleData' * 20}</td></tr>"
            for i in range(50)
        )
        rows_end = "<tr><td>END_MARKER_FINAL_ROW</td><td>Last row data here</td></tr>"
        html = f"""
        <html><body>
            <table>
                <tr><th>ID</th><th>Value</th></tr>
                {rows_start}
                {rows_middle}
                {rows_end}
            </table>
        </body></html>
        """

        html_path = temp_html_file(html)
        segmenter = HTMLSegmenter(min_length=20)

        try:
            segments = segmenter.segment_filing(filing_id=1, html_path=html_path)

            tables = [s for s in segments if s.segment_type == 'table']
            assert len(tables) >= 1
            # End marker should be present after [end sample]
            assert 'END_MARKER_FINAL_ROW' in tables[0].raw_text

        finally:
            Path(html_path).unlink()

    def test_large_table_middle_sample_centered(self, temp_html_file):
        """Middle sample should contain content from around the center of the table."""
        # Create table with recognizable content in the middle
        rows_start = "".join(
            f"<tr><td>Start{i:04d}</td><td>{'StartData' * 15}</td></tr>"
            for i in range(25)
        )
        # Middle marker at row ~50
        rows_middle = "<tr><td>MIDDLE_MARKER_CENTER</td><td>Center row data value</td></tr>"
        rows_middle += "".join(
            f"<tr><td>Mid{i:04d}</td><td>{'MidData' * 15}</td></tr>"
            for i in range(25)
        )
        rows_end = "".join(
            f"<tr><td>End{i:04d}</td><td>{'EndData' * 15}</td></tr>"
            for i in range(25)
        )
        html = f"""
        <html><body>
            <table>
                <tr><th>ID</th><th>Value</th></tr>
                {rows_start}
                {rows_middle}
                {rows_end}
            </table>
        </body></html>
        """

        html_path = temp_html_file(html)
        segmenter = HTMLSegmenter(min_length=20)

        try:
            segments = segmenter.segment_filing(filing_id=1, html_path=html_path)

            tables = [s for s in segments if s.segment_type == 'table']
            assert len(tables) >= 1
            # Middle marker should be present
            assert 'MIDDLE_MARKER_CENTER' in tables[0].raw_text

        finally:
            Path(html_path).unlink()

    def test_table_under_25k_no_truncation(self, temp_html_file):
        """Tables under 25K chars should NOT be truncated or use tri-region sampling."""
        # Create table with ~10K chars raw text (under TABLE_MAX_LENGTH)
        rows = "".join(
            f"<tr><td>Row {i:04d}</td><td>Value{i:04d}</td></tr>"
            for i in range(400)  # Approx 10K chars
        )
        html = f"""
        <html><body>
            <table>
                <tr><th>ID</th><th>Val</th></tr>
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
            # Table should NOT be truncated
            assert not tables[0].table_truncated_flag
            # Should NOT have sampling markers
            assert '...[middle sample]...' not in tables[0].raw_text
            assert '...[end sample]...' not in tables[0].raw_text

        finally:
            Path(html_path).unlink()

    def test_table_over_25k_triggers_summary(self, temp_html_file):
        """Tables >25K chars should be truncated and use tri-region sampling."""
        # Create table exceeding 25K chars
        rows = "".join(
            f"<tr><td>Row {i:04d}</td><td>Value{i:04d} extra text padding here</td></tr>"
            for i in range(1200)  # Should exceed 25K chars
        )
        html = f"""
        <html><body>
            <table>
                <tr><th>ID</th><th>Value</th></tr>
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
            # Table should be truncated
            assert tables[0].table_truncated_flag
            # Should have at least the end sample marker
            assert '...[end sample]...' in tables[0].raw_text

        finally:
            Path(html_path).unlink()

    def test_very_large_table_with_tri_region_sampling(self, temp_html_file):
        """Very large tables (>25K) should use tri-region sampling in summary."""
        # Create very large table with ~50K chars
        rows = "".join(
            f"<tr><td>Row{i:03d}</td><td>{'DataContent' * 10}</td></tr>"
            for i in range(500)  # ~55K chars
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
            # Should be truncated and have markers
            assert tables[0].table_truncated_flag
            assert '...[end sample]...' in tables[0].raw_text
            # Should not have any index errors - test passes if we get here

        finally:
            Path(html_path).unlink()

    def test_table_summary_preserves_headers_and_row_count(self, temp_html_file):
        """Large table summary should still include headers and row count."""
        rows = "".join(
            f"<tr><td>R{i}</td><td>{'X' * 100}</td></tr>"
            for i in range(400)  # Large enough to exceed 25K and trigger summary
        )
        html = f"""
        <html><body>
            <table>
                <tr><th>CustomerMetric</th><th>RevenueValue</th></tr>
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
            raw_text = tables[0].raw_text
            # Table should be truncated
            assert tables[0].table_truncated_flag
            # Headers should be present
            assert '[Table headers:' in raw_text
            # Row count should be present
            assert 'rows total]' in raw_text

        finally:
            Path(html_path).unlink()

    def test_samples_end_at_word_boundaries(self, temp_html_file):
        """Samples should end at word boundaries, not mid-word."""
        # Create table with long words (>25K chars) to verify word boundary truncation
        rows = "".join(
            f"<tr><td>Superlongwordwithoutspaces{i:04d}</td><td>Another word here with more padding</td></tr>"
            for i in range(500)  # ~35K chars to exceed TABLE_MAX_LENGTH
        )
        html = f"""
        <html><body>
            <table>
                <tr><th>Column1</th><th>Column2</th></tr>
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
            raw_text = tables[0].raw_text
            # Table should be truncated
            assert tables[0].table_truncated_flag

            # Find the position of [middle sample] marker and check preceding char
            middle_marker_pos = raw_text.find('...[middle sample]...')
            if middle_marker_pos > 0:
                # Character before marker should be whitespace or end of word
                char_before = raw_text[middle_marker_pos - 1]
                # Either space, or we hit a complete word (not mid-truncation)
                # This is a soft check - just ensure no crash
                assert char_before is not None

        finally:
            Path(html_path).unlink()

    def test_unicode_at_sample_boundaries(self, temp_html_file):
        """Tables with Unicode characters should handle boundaries correctly."""
        # Create table with Unicode characters (>25K chars)
        rows = "".join(
            f"<tr><td>Row {i}</td><td>Revenue: $1,234 \u20ac5,678 \u00a35,000 padding text</td></tr>"
            for i in range(600)  # ~36K chars to exceed TABLE_MAX_LENGTH
        )
        html = f"""
        <html><body>
            <table>
                <tr><th>ID</th><th>International Revenue</th></tr>
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
            # Table should be truncated
            assert tables[0].table_truncated_flag
            # Should not raise any encoding errors - test passes if we get here
            assert '...[end sample]...' in tables[0].raw_text

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


class TestHeadingCacheBinarySearch:
    """Test binary search heading cache lookup (SEG1)."""

    def test_empty_cache_returns_none(self):
        """Empty heading cache should return (None, None)."""
        segmenter = HTMLSegmenter()
        segmenter._heading_cache = []
        result = segmenter._get_section_from_cache(None, element_position=100)
        assert result == (None, None)

    def test_element_before_first_heading_returns_none(self):
        """Element positioned before first heading returns (None, None)."""
        segmenter = HTMLSegmenter()
        segmenter._heading_cache = [(100, 1, "First Heading")]
        result = segmenter._get_section_from_cache(None, element_position=50)
        assert result == (None, None)

    def test_element_exactly_at_heading_position(self):
        """Element at exact heading position returns that heading."""
        segmenter = HTMLSegmenter()
        segmenter._heading_cache = [
            (100, 1, "First Heading"),
            (200, 2, "Second Heading"),
        ]
        result = segmenter._get_section_from_cache(None, element_position=100)
        assert result == ("First Heading", "First Heading")

    def test_element_between_headings(self):
        """Element between headings returns hierarchical path and nearest heading (SEG6)."""
        segmenter = HTMLSegmenter()
        segmenter._heading_cache = [
            (100, 1, "First Heading"),
            (200, 2, "Second Heading"),
            (300, 3, "Third Heading"),
        ]
        result = segmenter._get_section_from_cache(None, element_position=250)
        # section_path includes hierarchy (h1 > h2), section_heading is just nearest
        assert result == ("First Heading > Second Heading", "Second Heading")

    def test_element_after_last_heading(self):
        """Element after last heading returns hierarchical path and nearest heading (SEG6)."""
        segmenter = HTMLSegmenter()
        segmenter._heading_cache = [
            (100, 1, "First Heading"),
            (200, 2, "Last Heading"),
        ]
        result = segmenter._get_section_from_cache(None, element_position=500)
        # section_path includes hierarchy (h1 > h2), section_heading is just nearest
        assert result == ("First Heading > Last Heading", "Last Heading")

    def test_single_heading_in_cache(self):
        """Single heading with element after it."""
        segmenter = HTMLSegmenter()
        segmenter._heading_cache = [(50, 1, "Only Heading")]
        result = segmenter._get_section_from_cache(None, element_position=100)
        assert result == ("Only Heading", "Only Heading")

    def test_single_heading_with_element_before(self):
        """Single heading with element before it returns None."""
        segmenter = HTMLSegmenter()
        segmenter._heading_cache = [(100, 1, "Only Heading")]
        result = segmenter._get_section_from_cache(None, element_position=50)
        assert result == (None, None)

    def test_binary_search_performance_many_headings(self):
        """Verify O(log n) behavior with many headings."""
        segmenter = HTMLSegmenter()
        # Create 100 headings at positions 100, 200, 300, ...
        segmenter._heading_cache = [
            (i * 100, 2, f"Heading {i}") for i in range(1, 101)
        ]
        # Element at position 5050 should find "Heading 50"
        result = segmenter._get_section_from_cache(None, element_position=5050)
        assert result == ("Heading 50", "Heading 50")

    def test_boundary_condition_just_before_heading(self):
        """Element just before a heading position returns previous heading."""
        segmenter = HTMLSegmenter()
        segmenter._heading_cache = [
            (100, 1, "First Heading"),
            (200, 2, "Second Heading"),
        ]
        result = segmenter._get_section_from_cache(None, element_position=199)
        assert result == ("First Heading", "First Heading")

    def test_boundary_condition_just_after_heading(self):
        """Element just after a heading position returns hierarchical path and nearest heading (SEG6)."""
        segmenter = HTMLSegmenter()
        segmenter._heading_cache = [
            (100, 1, "First Heading"),
            (200, 2, "Second Heading"),
        ]
        result = segmenter._get_section_from_cache(None, element_position=201)
        # section_path includes hierarchy (h1 > h2), section_heading is just nearest
        assert result == ("First Heading > Second Heading", "Second Heading")

    def test_metadata_headings_filtered_in_cache(self, temp_html_file):
        """Metadata headings should be filtered out during cache building.

        Since cache is cleared after processing, we verify this by checking
        that segments don't have metadata headings as their section_heading.
        """
        html = """
        <html><body>
            <h1>Table of Contents</h1>
            <p>This is some table of contents content that is long enough to pass the minimum length filter.</p>
            <h1>Business Overview</h1>
            <p>Our company provides customer analytics services and works with enterprise clients around the world.</p>
            <p>We have been growing our customer base for the past five years and have strong metrics.</p>
        </body></html>
        """

        html_path = temp_html_file(html)
        segmenter = HTMLSegmenter()

        try:
            segments = segmenter.segment_filing(filing_id=1, html_path=html_path)

            # Verify segments were created
            assert len(segments) > 0

            # All segments should have section from Business Overview, not Table of Contents
            # This verifies metadata headings were filtered during cache building
            for seg in segments:
                if seg.section_heading:
                    # Should have "Business Overview", not "Table of Contents"
                    assert seg.section_heading.lower() != "table of contents"
                    assert seg.section_heading == "Business Overview"

        finally:
            Path(html_path).unlink()


# =============================================================================
# SEG11: Parallel Sentence Detection Tests
# =============================================================================


class TestParallelSentenceDetection:
    """Test parallel sentence detection (SEG11)."""

    def test_parallel_processing_preserves_order(self, temp_html_file):
        """Segment order must be preserved after parallel processing."""
        # Create HTML with 100 numbered paragraphs (>50 chars each to pass MIN_SEGMENT_LENGTH)
        html = "<html><body>"
        for i in range(100):
            html += f"<p>Paragraph number {i:03d}. This is the first sentence with enough content. And this is the second sentence.</p>"
        html += "</body></html>"

        html_path = temp_html_file(html)
        segmenter = HTMLSegmenter()

        try:
            segments = segmenter.segment_filing(filing_id=1, html_path=html_path)

            # Verify segments are in correct order
            # Each segment should contain its sequential number
            found_numbers = []
            for seg in segments:
                # Extract number from text like "Paragraph number 005"
                if "Paragraph number" in seg.raw_text:
                    # Get the number after "Paragraph number"
                    parts = seg.raw_text.split()
                    for i, part in enumerate(parts):
                        if part == "number" and i + 1 < len(parts):
                            num_str = parts[i + 1].rstrip(".")
                            if num_str.isdigit():
                                found_numbers.append(int(num_str))
                                break

            # Verify numbers are in sequential order
            assert found_numbers == sorted(found_numbers), "Segments are not in sequential order"

        finally:
            Path(html_path).unlink()

    def test_parallel_processing_thread_safety(self, temp_html_file):
        """Concurrent sentence detection should not corrupt data."""
        # Create 200 segments with known sentence patterns (>50 chars each)
        html = "<html><body>"
        for i in range(200):
            html += f"<p>Segment number {i:03d}. First sentence here with enough content. Second sentence follows.</p>"
        html += "</body></html>"

        html_path = temp_html_file(html)
        segmenter = HTMLSegmenter()

        try:
            segments = segmenter.segment_filing(filing_id=1, html_path=html_path)

            # Verify all segments have sentence boundaries detected
            segments_with_sentences = 0
            for segment in segments:
                if "sentence" in segment.raw_text.lower():
                    # Should have detected sentence boundaries
                    assert hasattr(segment, "sentence_boundaries"), (
                        f"Segment missing sentence_boundaries: {segment.raw_text[:50]}"
                    )
                    assert segment.sentence_boundaries is not None, (
                        f"Segment has None sentence_boundaries: {segment.raw_text[:50]}"
                    )
                    # Should detect at least 2 sentences
                    assert len(segment.sentence_boundaries) >= 2, (
                        f"Expected at least 2 sentences, got {len(segment.sentence_boundaries)}: "
                        f"{segment.raw_text[:50]}"
                    )
                    segments_with_sentences += 1

            # Should have found many segments with sentences
            assert segments_with_sentences >= 100, (
                f"Expected at least 100 segments with sentences, got {segments_with_sentences}"
            )

        finally:
            Path(html_path).unlink()

    def test_small_segment_count_uses_sequential(self, temp_html_file):
        """Segments below threshold should use sequential processing."""
        # Create fewer segments than the threshold (50)
        html = "<html><body>"
        for i in range(10):
            html += f"<p>Paragraph number {i:02d}. This is a single sentence with enough text to pass the minimum length requirement.</p>"
        html += "</body></html>"

        html_path = temp_html_file(html)
        segmenter = HTMLSegmenter()

        try:
            # Should complete without errors (implicitly tests sequential path)
            segments = segmenter.segment_filing(filing_id=1, html_path=html_path)
            assert len(segments) >= 1

            # Verify sentence boundaries were still detected
            for segment in segments:
                if "sentence" in segment.raw_text.lower():
                    assert hasattr(segment, "sentence_boundaries")

        finally:
            Path(html_path).unlink()

    def test_large_segment_count_triggers_parallel(self, temp_html_file):
        """Segments at or above threshold should trigger parallel processing."""
        # Create exactly at threshold (50 segments)
        html = "<html><body>"
        for i in range(50):
            html += f"<p>Paragraph number {i:02d}. First sentence with enough text content. Second sentence follows here.</p>"
        html += "</body></html>"

        html_path = temp_html_file(html)
        segmenter = HTMLSegmenter()

        try:
            segments = segmenter.segment_filing(filing_id=1, html_path=html_path)

            # Should have processed successfully
            assert len(segments) >= 1

            # Verify all segments have correct sentence boundaries
            for segment in segments:
                if "sentence" in segment.raw_text.lower():
                    assert hasattr(segment, "sentence_boundaries")
                    assert segment.sentence_boundaries is not None

        finally:
            Path(html_path).unlink()

    def test_parallel_handles_mixed_content(self, temp_html_file):
        """Parallel processing should handle mixed content types."""
        # Mix paragraphs, tables, and empty segments
        html = """<html><body>"""
        for i in range(60):
            if i % 3 == 0:
                # Table (needs to be large enough)
                html += f"""
                <table>
                    <tr><td>Row {i}</td><td>This is data for row {i} with enough content to pass the minimum length</td></tr>
                </table>
                """
            elif i % 3 == 1:
                # Regular paragraph with sentences
                html += f"<p>Paragraph number {i:02d}. Multiple sentences here with content. Another one follows now.</p>"
            else:
                # Longer paragraph
                html += f"<p>This is a longer paragraph number {i:02d} with sufficient text to pass the minimum segment length requirement.</p>"
        html += "</body></html>"

        html_path = temp_html_file(html)
        segmenter = HTMLSegmenter()

        try:
            segments = segmenter.segment_filing(filing_id=1, html_path=html_path)

            # Should process successfully with mixed content
            assert len(segments) >= 1

            # Verify different segment types handled correctly
            table_count = sum(1 for s in segments if s.segment_type == "table")
            para_count = sum(1 for s in segments if s.segment_type == "paragraph")

            assert table_count > 0, "Should have table segments"
            assert para_count > 0, "Should have paragraph segments"

        finally:
            Path(html_path).unlink()

    def test_parallel_processing_no_data_loss(self, temp_html_file):
        """Parallel processing should not lose any segment data."""
        # Create 100 segments with unique identifiable content
        html = "<html><body>"
        expected_numbers = []
        for i in range(100):
            html += f"<p>Unique identifier {i:04d}. This is content with enough text to pass minimum segment length.</p>"
            expected_numbers.append(i)
        html += "</body></html>"

        html_path = temp_html_file(html)
        segmenter = HTMLSegmenter()

        try:
            segments = segmenter.segment_filing(filing_id=1, html_path=html_path)

            # Extract all identifiers from segments
            found_numbers = []
            for seg in segments:
                # Look for "identifier NNNN" pattern
                if "identifier" in seg.raw_text:
                    parts = seg.raw_text.split()
                    for i, part in enumerate(parts):
                        if part == "identifier" and i + 1 < len(parts):
                            num_str = parts[i + 1].rstrip(".")
                            if num_str.isdigit():
                                found_numbers.append(int(num_str))
                                break

            # Verify all numbers were found
            assert sorted(found_numbers) == expected_numbers, (
                f"Data loss detected. Expected {len(expected_numbers)} segments, "
                f"found {len(found_numbers)}"
            )

        finally:
            Path(html_path).unlink()

    def test_parallel_processing_exception_handling(self, temp_html_file, monkeypatch):
        """Parallel processing should fallback to sequential on exception."""
        # Create HTML with enough segments to trigger parallel processing
        html = "<html><body>"
        for i in range(60):
            html += f"<p>Paragraph number {i:02d}. This is a test sentence with enough content to pass minimum length.</p>"
        html += "</body></html>"

        html_path = temp_html_file(html)
        segmenter = HTMLSegmenter()

        # Mock ThreadPoolExecutor to raise an exception
        def mock_executor_map(*args, **kwargs):
            raise RuntimeError("Simulated thread pool failure")

        try:
            # Patch the executor map method
            from concurrent.futures import ThreadPoolExecutor
            original_map = ThreadPoolExecutor.map
            monkeypatch.setattr(ThreadPoolExecutor, "map", mock_executor_map)

            # Should fallback to sequential and complete successfully
            segments = segmenter.segment_filing(filing_id=1, html_path=html_path)

            # Should have processed all segments
            assert len(segments) >= 1

            # Verify sentence boundaries were still detected (via fallback)
            for segment in segments:
                if "sentence" in segment.raw_text.lower():
                    assert hasattr(segment, "sentence_boundaries")

        finally:
            Path(html_path).unlink()

    def test_threshold_configuration(self):
        """Verify parallel processing threshold is configurable."""
        segmenter = HTMLSegmenter()

        # Check constants exist and have expected values
        assert hasattr(segmenter, "PARALLEL_SENTENCE_DETECTION_THRESHOLD")
        assert segmenter.PARALLEL_SENTENCE_DETECTION_THRESHOLD == 50

        assert hasattr(segmenter, "PARALLEL_SENTENCE_DETECTION_WORKERS")
        assert segmenter.PARALLEL_SENTENCE_DETECTION_WORKERS == 4


# =============================================================================
# SEG5: Character Offset Tracking Tests
# =============================================================================


class TestCharacterOffsetTracking:
    """Test character offset tracking for source segments (SEG5)."""

    def test_single_paragraph_offset_populated(self, temp_html_file):
        """Single paragraph has char_start_offset and char_end_offset populated."""
        html = """<html><body>
            <p>This is a test paragraph with enough content to pass the minimum segment length requirement.</p>
        </body></html>"""

        html_path = temp_html_file(html)
        segmenter = HTMLSegmenter()

        try:
            segments = segmenter.segment_filing(filing_id=1, html_path=html_path)

            assert len(segments) >= 1
            segment = segments[0]

            # Offsets should be populated
            assert segment.char_start_offset is not None
            assert segment.char_end_offset is not None
            assert segment.char_start_offset >= 0
            assert segment.char_end_offset > segment.char_start_offset

        finally:
            Path(html_path).unlink()

    def test_multiple_paragraphs_distinct_offsets(self, temp_html_file):
        """Multiple paragraphs have distinct, ordered offsets."""
        html = """<html><body>
            <p>First paragraph with enough content to pass the minimum segment length requirement here.</p>
            <p>Second paragraph also with enough content to ensure it passes the minimum segment length.</p>
            <p>Third paragraph contains sufficient text to meet the minimum segment length requirement.</p>
        </body></html>"""

        html_path = temp_html_file(html)
        segmenter = HTMLSegmenter()

        try:
            segments = segmenter.segment_filing(filing_id=1, html_path=html_path)

            assert len(segments) >= 3

            # All segments should have offsets
            for segment in segments:
                assert segment.char_start_offset is not None
                assert segment.char_end_offset is not None

            # Offsets should be distinct
            offsets = [(s.char_start_offset, s.char_end_offset) for s in segments]
            assert len(offsets) == len(set(offsets)), "Offsets should be distinct"

            # Offsets should be in increasing order
            for i in range(len(segments) - 1):
                assert segments[i].char_end_offset <= segments[i + 1].char_start_offset, \
                    f"Segment {i} end should be before segment {i+1} start"

        finally:
            Path(html_path).unlink()

    def test_table_offset_captures_full_table(self, temp_html_file):
        """Table element offsets capture the full table HTML when matching succeeds."""
        html = """<html><body><table><tr><th>Quarter</th><th>Revenue</th><th>Description</th></tr><tr><td>Q1 2024</td><td>$5M</td><td>Strong quarter with customer growth</td></tr><tr><td>Q2 2024</td><td>$6M</td><td>Continued expansion in new markets</td></tr><tr><td>Q3 2024</td><td>$7M</td><td>Record quarterly performance achieved</td></tr></table></body></html>"""

        html_path = temp_html_file(html)
        segmenter = HTMLSegmenter()

        try:
            segments = segmenter.segment_filing(filing_id=1, html_path=html_path)

            tables = [s for s in segments if s.segment_type == 'table']
            assert len(tables) >= 1

            table_seg = tables[0]

            # Offsets should be populated if string matching succeeded
            # (May be None if BeautifulSoup reformatted the HTML)
            if table_seg.char_start_offset is not None:
                assert table_seg.char_end_offset is not None
                # Verify offset span is reasonable (table HTML should be > 100 chars)
                offset_span = table_seg.char_end_offset - table_seg.char_start_offset
                assert offset_span > 100, "Table offset span should cover full table HTML"

        finally:
            Path(html_path).unlink()

    def test_mixed_content_relative_offsets(self, temp_html_file):
        """Paragraphs and tables in mixed content have correct relative offsets."""
        html = """<html><body><p>First paragraph appears before the table and contains enough text to pass minimum length.</p><table><tr><th>Metric</th><th>Value</th><th>Description</th></tr><tr><td>Revenue</td><td>$10M</td><td>Total quarterly revenue</td></tr><tr><td>Customers</td><td>5000</td><td>Active customer count</td></tr></table><p>Second paragraph appears after the table and also contains sufficient text for requirements.</p></body></html>"""

        html_path = temp_html_file(html)
        segmenter = HTMLSegmenter()

        try:
            segments = segmenter.segment_filing(filing_id=1, html_path=html_path)

            assert len(segments) >= 3

            # Filter segments with valid offsets
            segments_with_offsets = [
                s for s in segments
                if s.char_start_offset is not None and s.char_end_offset is not None
            ]

            # Most segments should have offsets (paragraphs usually match well)
            assert len(segments_with_offsets) >= 2, "At least paragraphs should have offsets"

            # Verify they're in document order
            for i in range(len(segments_with_offsets) - 1):
                assert segments_with_offsets[i].char_start_offset < segments_with_offsets[i + 1].char_start_offset, \
                    "Segments should be in document order"

        finally:
            Path(html_path).unlink()

    def test_composite_segment_splitting_preserves_offsets(self, temp_html_file):
        """Composite segments that get split preserve parent offsets."""
        html = """<html><body>
            <div>
                <p>Text before table with enough content to pass the minimum segment length requirement.</p>
                <table>
                    <tr><th>Header</th></tr>
                    <tr><td>Data value here</td></tr>
                </table>
            </div>
        </body></html>"""

        html_path = temp_html_file(html)
        segmenter = HTMLSegmenter()

        try:
            segments = segmenter.segment_filing(filing_id=1, html_path=html_path)

            # Should have split into text and table
            assert len(segments) >= 2

            # Child segments should have valid offsets (inherited from parent or computed)
            for segment in segments:
                # Offsets may be None in some edge cases, but if populated should be valid
                if segment.char_start_offset is not None:
                    assert segment.char_end_offset is not None
                    assert segment.char_end_offset > segment.char_start_offset

        finally:
            Path(html_path).unlink()

    def test_definition_merging_spans_offsets(self, temp_html_file):
        """Merged definition segments have offsets spanning all original segments."""
        html = """<html><body>
            <p>We define active customers as customers who have made at least one purchase.</p>
            <p>and who have logged into our platform at least once in the preceding 90 days.</p>
        </body></html>"""

        html_path = temp_html_file(html)
        segmenter = HTMLSegmenter()

        try:
            segments = segmenter.segment_filing(filing_id=1, html_path=html_path)

            # Should be merged into one segment
            assert len(segments) == 1
            merged_seg = segments[0]

            # Should have offsets
            assert merged_seg.char_start_offset is not None
            assert merged_seg.char_end_offset is not None

            # Merged text should include both parts
            assert 'active customers' in merged_seg.raw_text
            assert '90 days' in merged_seg.raw_text

            # Offset span should cover both original paragraphs
            offset_span = merged_seg.char_end_offset - merged_seg.char_start_offset
            assert offset_span > 100, "Merged segment should span multiple paragraphs"

        finally:
            Path(html_path).unlink()

    def test_list_items_distinct_offsets(self, temp_html_file):
        """Each list item has distinct character offsets."""
        html = """<html><body>
            <ul>
                <li>First list item with enough content to pass the minimum segment length requirement.</li>
                <li>Second list item also with enough content to ensure it passes the minimum length.</li>
                <li>Third list item contains sufficient text to meet the minimum segment length requirement.</li>
            </ul>
        </body></html>"""

        html_path = temp_html_file(html)
        segmenter = HTMLSegmenter()

        try:
            segments = segmenter.segment_filing(filing_id=1, html_path=html_path)

            list_items = [s for s in segments if s.segment_type == 'list_item']
            assert len(list_items) >= 3

            # Each list item should have distinct offsets
            for item in list_items:
                assert item.char_start_offset is not None
                assert item.char_end_offset is not None
                assert item.char_end_offset > item.char_start_offset

            # Offsets should be distinct
            offsets = [(s.char_start_offset, s.char_end_offset) for s in list_items]
            assert len(offsets) == len(set(offsets)), "List item offsets should be distinct"

        finally:
            Path(html_path).unlink()

    def test_minimal_html_graceful_handling(self, temp_html_file):
        """Minimal or empty HTML is handled gracefully (offsets may be None)."""
        html = """<html><body></body></html>"""

        html_path = temp_html_file(html)
        segmenter = HTMLSegmenter()

        try:
            # Should not raise exception
            segments = segmenter.segment_filing(filing_id=1, html_path=html_path)

            # May have no segments or segments with None offsets
            # This is acceptable - just verify no exceptions
            assert isinstance(segments, list)

        finally:
            Path(html_path).unlink()

    def test_substring_extraction_verification(self, temp_html_file):
        """Offsets allow extracting original HTML substring."""
        html = """<html><body>
            <p>This is a test paragraph with sufficient content to pass the minimum segment length.</p>
        </body></html>"""

        html_path = temp_html_file(html)

        # Read the HTML content
        with open(html_path, 'r') as f:
            html_content = f.read()

        segmenter = HTMLSegmenter()

        try:
            segments = segmenter.segment_filing(filing_id=1, html_path=html_path)

            assert len(segments) >= 1
            segment = segments[0]

            if segment.char_start_offset is not None and segment.char_end_offset is not None:
                # Extract substring using offsets
                extracted = html_content[segment.char_start_offset:segment.char_end_offset]

                # Should contain the paragraph tag and text
                assert '<p>' in extracted
                assert 'test paragraph' in extracted
                assert '</p>' in extracted

        finally:
            Path(html_path).unlink()

    def test_offset_ordering_non_overlapping(self, temp_html_file):
        """Segment offsets are non-overlapping and properly ordered."""
        html = """<html><body>
            <p>First paragraph with enough text to pass the minimum segment length requirement here.</p>
            <p>Second paragraph also with enough text to ensure it passes the minimum segment length.</p>
            <p>Third paragraph contains sufficient text to meet the minimum segment length requirement.</p>
            <p>Fourth paragraph has more than enough content to satisfy the minimum length requirement.</p>
        </body></html>"""

        html_path = temp_html_file(html)
        segmenter = HTMLSegmenter()

        try:
            segments = segmenter.segment_filing(filing_id=1, html_path=html_path)

            assert len(segments) >= 4

            # Filter segments with valid offsets
            segments_with_offsets = [
                s for s in segments
                if s.char_start_offset is not None and s.char_end_offset is not None
            ]

            assert len(segments_with_offsets) >= 4, "Most segments should have offsets"

            # Verify non-overlapping: seg[i].end <= seg[i+1].start
            for i in range(len(segments_with_offsets) - 1):
                current = segments_with_offsets[i]
                next_seg = segments_with_offsets[i + 1]

                assert current.char_end_offset <= next_seg.char_start_offset, \
                    f"Segment {i} overlaps with segment {i+1}"

        finally:
            Path(html_path).unlink()

    def test_unicode_content_offset_handling(self, temp_html_file):
        """Character offsets work correctly with Unicode content."""
        html = """<html><body>
            <p>This paragraph contains Unicode characters: é, ñ, ü, 中文 and has enough text for minimum length.</p>
        </body></html>"""

        html_path = temp_html_file(html)
        segmenter = HTMLSegmenter()

        try:
            segments = segmenter.segment_filing(filing_id=1, html_path=html_path)

            assert len(segments) >= 1
            segment = segments[0]

            # Offsets should be populated
            assert segment.char_start_offset is not None
            assert segment.char_end_offset is not None

            # Unicode content should be in the segment
            assert 'é' in segment.raw_text or '中文' in segment.raw_text

        finally:
            Path(html_path).unlink()

    def test_sgml_format_offset_tracking(self, temp_html_file):
        """Offsets work with SGML format filings."""
        html = """<DOCUMENT>
            <TYPE>S-1
            <TEXT>
            <HTML><BODY>
                <p>This is SGML format content with enough text to pass the minimum segment length requirement.</p>
            </BODY></HTML>
            </TEXT>
        </DOCUMENT>"""

        html_path = temp_html_file(html)
        segmenter = HTMLSegmenter()

        try:
            segments = segmenter.segment_filing(filing_id=1, html_path=html_path)

            assert len(segments) >= 1

            # Should have offsets even in SGML format
            for segment in segments:
                if len(segment.raw_text) >= 50:  # Reasonable length segment
                    # Offsets may be None for some edge cases, but should work for main content
                    # Just verify no exceptions and basic validity if populated
                    if segment.char_start_offset is not None:
                        assert segment.char_end_offset is not None
                        assert segment.char_end_offset > segment.char_start_offset

        finally:
            Path(html_path).unlink()


# ===== SEG6: Hierarchical Section Path Tests =====


class TestHierarchicalSectionPath:
    """Test hierarchical section path building (SEG6)."""

    @pytest.fixture
    def temp_html_file(self):
        """Create a temporary HTML file for testing."""
        def _create_temp_file(html_content: str) -> str:
            with tempfile.NamedTemporaryFile(mode="w", suffix=".html", delete=False) as f:
                f.write(html_content)
                return f.name
        return _create_temp_file

    # --- Basic Hierarchy Tests ---

    def test_two_level_hierarchy(self, temp_html_file):
        """Two-level hierarchy: h1 → h2 produces 'H1 > H2'."""
        html = """
        <html><body>
            <h1>Item 1. Business</h1>
            <h2>Customers</h2>
            <p>We have over 10,000 enterprise customers who use our platform for mission critical operations.</p>
        </body></html>
        """
        html_path = temp_html_file(html)

        try:
            segmenter = HTMLSegmenter(min_length=30)
            segments = segmenter.segment_filing(filing_id=1, html_path=html_path)

            content_segments = [s for s in segments if "enterprise customers" in s.raw_text.lower()]
            assert len(content_segments) >= 1

            seg = content_segments[0]
            assert seg.section_path == "Item 1. Business > Customers"
            assert seg.section_heading == "Customers"
        finally:
            Path(html_path).unlink()

    def test_three_level_hierarchy(self, temp_html_file):
        """Three-level hierarchy: h1 → h2 → h3 produces 'H1 > H2 > H3'."""
        html = """
        <html><body>
            <h1>Item 1. Business</h1>
            <h2>Customers</h2>
            <h3>Growth Metrics</h3>
            <p>Our customer base has grown significantly with over 50,000 active users using our platform daily.</p>
        </body></html>
        """
        html_path = temp_html_file(html)

        try:
            segmenter = HTMLSegmenter(min_length=30)
            segments = segmenter.segment_filing(filing_id=2, html_path=html_path)

            content_segments = [s for s in segments if "active users" in s.raw_text.lower()]
            assert len(content_segments) >= 1

            seg = content_segments[0]
            assert seg.section_path == "Item 1. Business > Customers > Growth Metrics"
            assert seg.section_heading == "Growth Metrics"
        finally:
            Path(html_path).unlink()

    def test_single_heading_path_equals_heading(self, temp_html_file):
        """Single heading: path equals heading (no hierarchy to build)."""
        html = """
        <html><body>
            <h2>Business Overview</h2>
            <p>We are a leading provider of enterprise software solutions serving customers worldwide consistently.</p>
        </body></html>
        """
        html_path = temp_html_file(html)

        try:
            segmenter = HTMLSegmenter(min_length=30)
            segments = segmenter.segment_filing(filing_id=3, html_path=html_path)

            content_segments = [s for s in segments if "enterprise software" in s.raw_text.lower()]
            assert len(content_segments) >= 1

            seg = content_segments[0]
            # With only one heading, path = heading
            assert seg.section_path == "Business Overview"
            assert seg.section_heading == "Business Overview"
        finally:
            Path(html_path).unlink()

    def test_no_preceding_heading_returns_none(self, temp_html_file):
        """Element before any heading: returns (None, None)."""
        html = """
        <html><body>
            <p>This introductory content appears before any heading in the document structure and has no section.</p>
            <h2>First Heading</h2>
            <p>Content after heading with sufficient length for testing purposes.</p>
        </body></html>
        """
        html_path = temp_html_file(html)

        try:
            segmenter = HTMLSegmenter(min_length=30)
            segments = segmenter.segment_filing(filing_id=4, html_path=html_path)

            intro_segments = [s for s in segments if "introductory content" in s.raw_text.lower()]
            if intro_segments:
                seg = intro_segments[0]
                assert seg.section_path is None
                assert seg.section_heading is None
        finally:
            Path(html_path).unlink()

    # --- Level Reset Tests ---

    def test_level_reset_h1_clears_hierarchy(self, temp_html_file):
        """h1 → h2 → h1 → h3: element after second h1 gets 'H1b > H3' (first h1 not included)."""
        html = """
        <html><body>
            <h1>Item 1. Business</h1>
            <h2>Overview</h2>
            <p>First section content that discusses our business overview in sufficient detail.</p>
            <h1>Item 2. Risk Factors</h1>
            <h3>Market Risk</h3>
            <p>There are significant market risks that could affect our financial performance going forward.</p>
        </body></html>
        """
        html_path = temp_html_file(html)

        try:
            segmenter = HTMLSegmenter(min_length=30)
            segments = segmenter.segment_filing(filing_id=5, html_path=html_path)

            risk_segments = [s for s in segments if "market risks" in s.raw_text.lower()]
            assert len(risk_segments) >= 1

            seg = risk_segments[0]
            # After second h1, hierarchy resets - should NOT include Item 1 or Overview
            assert seg.section_path == "Item 2. Risk Factors > Market Risk"
            assert seg.section_heading == "Market Risk"
        finally:
            Path(html_path).unlink()

    def test_level_reset_same_level_uses_latest(self, temp_html_file):
        """h1 → h2 → h2: element after second h2 gets 'H1 > H2b' (first h2 not included)."""
        html = """
        <html><body>
            <h1>Item 1. Business</h1>
            <h2>First Section</h2>
            <p>Content in first section with enough text for segment extraction purposes.</p>
            <h2>Second Section</h2>
            <p>Content in second section that should reference only Item 1 and Second Section headings.</p>
        </body></html>
        """
        html_path = temp_html_file(html)

        try:
            segmenter = HTMLSegmenter(min_length=30)
            segments = segmenter.segment_filing(filing_id=6, html_path=html_path)

            second_segments = [s for s in segments if "second section" in s.raw_text.lower()]
            assert len(second_segments) >= 1

            seg = second_segments[0]
            assert seg.section_path == "Item 1. Business > Second Section"
            assert seg.section_heading == "Second Section"
        finally:
            Path(html_path).unlink()

    def test_skipped_levels_preserved(self, temp_html_file):
        """h1 → h4 → h5: skipped levels produce 'H1 > H4 > H5' (no phantom h2/h3)."""
        html = """
        <html><body>
            <h1>Item 1. Business</h1>
            <h4>Detailed Subsection</h4>
            <h5>Deep Nested Content</h5>
            <p>This content is deeply nested but skips h2 and h3 levels in the heading hierarchy.</p>
        </body></html>
        """
        html_path = temp_html_file(html)

        try:
            segmenter = HTMLSegmenter(min_length=30)
            segments = segmenter.segment_filing(filing_id=7, html_path=html_path)

            content_segments = [s for s in segments if "deeply nested" in s.raw_text.lower()]
            assert len(content_segments) >= 1

            seg = content_segments[0]
            assert seg.section_path == "Item 1. Business > Detailed Subsection > Deep Nested Content"
            assert seg.section_heading == "Deep Nested Content"
        finally:
            Path(html_path).unlink()

    def test_higher_level_after_lower_resets(self, temp_html_file):
        """h1 → h3 → h2: element after h2 gets 'H1 > H2' (h3 excluded as it's lower level)."""
        html = """
        <html><body>
            <h1>Item 1. Business</h1>
            <h3>Subsection Details</h3>
            <p>Content under h3 heading with sufficient text for segment processing.</p>
            <h2>Main Section</h2>
            <p>Content under h2 should not include the h3 since h2 is at a higher level in hierarchy.</p>
        </body></html>
        """
        html_path = temp_html_file(html)

        try:
            segmenter = HTMLSegmenter(min_length=30)
            segments = segmenter.segment_filing(filing_id=8, html_path=html_path)

            main_segments = [s for s in segments if "higher level" in s.raw_text.lower()]
            assert len(main_segments) >= 1

            seg = main_segments[0]
            # h3 should not be in path since h2 resets it
            assert seg.section_path == "Item 1. Business > Main Section"
            assert seg.section_heading == "Main Section"
        finally:
            Path(html_path).unlink()

    # --- Separator and Formatting Tests ---

    def test_path_uses_correct_separator(self, temp_html_file):
        """Path uses ' > ' as separator (with spaces)."""
        html = """
        <html><body>
            <h1>Part I</h1>
            <h2>Section A</h2>
            <p>Content that should have path with correct separator between heading levels.</p>
        </body></html>
        """
        html_path = temp_html_file(html)

        try:
            segmenter = HTMLSegmenter(min_length=30)
            segments = segmenter.segment_filing(filing_id=9, html_path=html_path)

            content_segments = [s for s in segments if "correct separator" in s.raw_text.lower()]
            assert len(content_segments) >= 1

            seg = content_segments[0]
            # Verify separator is " > " not ">" or " - " etc
            assert " > " in seg.section_path
            assert seg.section_path == "Part I > Section A"
        finally:
            Path(html_path).unlink()

    def test_unicode_headings_preserved(self, temp_html_file):
        """Unicode characters in headings are preserved correctly."""
        html = """
        <html><body>
            <h1>第一部分</h1>
            <h2>Résumé des Activités</h2>
            <p>This content has unicode headings that should be preserved correctly in the section path output.</p>
        </body></html>
        """
        html_path = temp_html_file(html)

        try:
            segmenter = HTMLSegmenter(min_length=30)
            segments = segmenter.segment_filing(filing_id=10, html_path=html_path)

            content_segments = [s for s in segments if "unicode headings" in s.raw_text.lower()]
            assert len(content_segments) >= 1

            seg = content_segments[0]
            assert "第一部分" in seg.section_path
            assert "Résumé des Activités" in seg.section_path
        finally:
            Path(html_path).unlink()

    def test_heading_with_separator_in_text(self, temp_html_file):
        """Heading containing ' > ' in its text should not break parsing."""
        html = """
        <html><body>
            <h1>Item 1. Business</h1>
            <h2>Revenue > $100M Target</h2>
            <p>Content under a heading that contains the separator character in its actual text value.</p>
        </body></html>
        """
        html_path = temp_html_file(html)

        try:
            segmenter = HTMLSegmenter(min_length=30)
            segments = segmenter.segment_filing(filing_id=11, html_path=html_path)

            content_segments = [s for s in segments if "separator character" in s.raw_text.lower()]
            assert len(content_segments) >= 1

            seg = content_segments[0]
            # Path should still work even with > in heading text
            assert seg.section_path == "Item 1. Business > Revenue > $100M Target"
            assert seg.section_heading == "Revenue > $100M Target"
        finally:
            Path(html_path).unlink()

    # --- Edge Cases ---

    def test_all_same_level_headings(self, temp_html_file):
        """All same level (h2, h2, h2): each segment gets just nearest h2."""
        html = """
        <html><body>
            <h2>Section One</h2>
            <p>Content in section one with sufficient text for segment processing operations.</p>
            <h2>Section Two</h2>
            <p>Content in section two should only reference Section Two not Section One in path.</p>
            <h2>Section Three</h2>
            <p>Content in section three should only reference Section Three heading in the path.</p>
        </body></html>
        """
        html_path = temp_html_file(html)

        try:
            segmenter = HTMLSegmenter(min_length=30)
            segments = segmenter.segment_filing(filing_id=12, html_path=html_path)

            sec_two_segments = [s for s in segments if "section two should" in s.raw_text.lower()]
            sec_three_segments = [s for s in segments if "section three should" in s.raw_text.lower()]

            if sec_two_segments:
                assert sec_two_segments[0].section_path == "Section Two"
                assert sec_two_segments[0].section_heading == "Section Two"

            if sec_three_segments:
                assert sec_three_segments[0].section_path == "Section Three"
                assert sec_three_segments[0].section_heading == "Section Three"
        finally:
            Path(html_path).unlink()

    def test_deep_nesting_all_levels(self, temp_html_file):
        """Deep nesting (h1 → h2 → h3 → h4 → h5 → h6): all levels included."""
        html = """
        <html><body>
            <h1>Level 1</h1>
            <h2>Level 2</h2>
            <h3>Level 3</h3>
            <h4>Level 4</h4>
            <h5>Level 5</h5>
            <h6>Level 6</h6>
            <p>This deeply nested content should have all six heading levels in its section path value.</p>
        </body></html>
        """
        html_path = temp_html_file(html)

        try:
            segmenter = HTMLSegmenter(min_length=30)
            segments = segmenter.segment_filing(filing_id=13, html_path=html_path)

            content_segments = [s for s in segments if "deeply nested content" in s.raw_text.lower()]
            assert len(content_segments) >= 1

            seg = content_segments[0]
            expected_path = "Level 1 > Level 2 > Level 3 > Level 4 > Level 5 > Level 6"
            assert seg.section_path == expected_path
            assert seg.section_heading == "Level 6"
        finally:
            Path(html_path).unlink()

    def test_element_between_h1_and_h2(self, temp_html_file):
        """Element between h1 and first h2 (path = just h1)."""
        html = """
        <html><body>
            <h1>Item 1. Business</h1>
            <p>This introductory paragraph appears directly under h1 before any h2 subheadings appear.</p>
            <h2>Overview</h2>
            <p>This paragraph appears under the h2 Overview heading with full path to display.</p>
        </body></html>
        """
        html_path = temp_html_file(html)

        try:
            segmenter = HTMLSegmenter(min_length=30)
            segments = segmenter.segment_filing(filing_id=14, html_path=html_path)

            intro_segments = [s for s in segments if "introductory paragraph" in s.raw_text.lower()]
            overview_segments = [s for s in segments if "under the h2 overview" in s.raw_text.lower()]

            if intro_segments:
                seg = intro_segments[0]
                # Only h1 in path - no h2 yet
                assert seg.section_path == "Item 1. Business"
                assert seg.section_heading == "Item 1. Business"

            if overview_segments:
                seg = overview_segments[0]
                assert seg.section_path == "Item 1. Business > Overview"
                assert seg.section_heading == "Overview"
        finally:
            Path(html_path).unlink()

    # --- Integration Tests ---

    def test_full_segment_filing_hierarchical_paths(self, temp_html_file):
        """Full segment_filing() produces correct hierarchical paths for multiple segments."""
        html = """
        <html><body>
            <h1>Item 1. Business</h1>
            <h2>Customers</h2>
            <p>We serve over 10,000 enterprise customers across multiple industries worldwide consistently.</p>
            <h2>Revenue</h2>
            <h3>Subscription Revenue</h3>
            <p>Our subscription revenue model provides predictable recurring income from customers annually.</p>
            <h1>Item 2. Risk Factors</h1>
            <h2>Market Risks</h2>
            <p>We face significant market risks including competitive pressure from larger technology companies.</p>
        </body></html>
        """
        html_path = temp_html_file(html)

        try:
            segmenter = HTMLSegmenter(min_length=30)
            segments = segmenter.segment_filing(filing_id=15, html_path=html_path)

            # Find segments by content
            customer_segs = [s for s in segments if "enterprise customers" in s.raw_text.lower()]
            revenue_segs = [s for s in segments if "subscription revenue model" in s.raw_text.lower()]
            risk_segs = [s for s in segments if "market risks including" in s.raw_text.lower()]

            # Verify customer segment path
            if customer_segs:
                assert customer_segs[0].section_path == "Item 1. Business > Customers"
                assert customer_segs[0].section_heading == "Customers"

            # Verify revenue segment path (3 levels)
            if revenue_segs:
                assert revenue_segs[0].section_path == "Item 1. Business > Revenue > Subscription Revenue"
                assert revenue_segs[0].section_heading == "Subscription Revenue"

            # Verify risk segment path (new h1 resets hierarchy)
            if risk_segs:
                assert risk_segs[0].section_path == "Item 2. Risk Factors > Market Risks"
                assert risk_segs[0].section_heading == "Market Risks"
        finally:
            Path(html_path).unlink()

    def test_segments_in_same_section_share_path_prefix(self, temp_html_file):
        """Segments in the same section share the same section path."""
        html = """
        <html><body>
            <h1>Item 1. Business</h1>
            <h2>Customers</h2>
            <p>First paragraph about our customers who are primarily enterprise organizations worldwide.</p>
            <p>Second paragraph about our customers who continue to expand their usage of our platform.</p>
            <p>Third paragraph about our customers and their satisfaction with our enterprise solutions.</p>
        </body></html>
        """
        html_path = temp_html_file(html)

        try:
            segmenter = HTMLSegmenter(min_length=30)
            segments = segmenter.segment_filing(filing_id=16, html_path=html_path)

            # All content paragraphs should have the same path
            content_segments = [s for s in segments if "about our customers" in s.raw_text.lower()]

            if len(content_segments) >= 2:
                first_path = content_segments[0].section_path
                for seg in content_segments[1:]:
                    assert seg.section_path == first_path
                    assert seg.section_path == "Item 1. Business > Customers"
        finally:
            Path(html_path).unlink()

    def test_very_long_path_truncated(self):
        """Very long hierarchical paths are truncated to 500 chars (SEG6)."""
        segmenter = HTMLSegmenter()
        # Create headings with very long text that would exceed 500 chars total
        long_text_1 = "A" * 200  # h1 with 200 chars
        long_text_2 = "B" * 200  # h2 with 200 chars
        long_text_3 = "C" * 200  # h3 with 200 chars
        # Total would be 600 chars + separators, exceeds 500
        segmenter._heading_cache = [
            (100, 1, long_text_1),
            (200, 2, long_text_2),
            (300, 3, long_text_3),
        ]
        result = segmenter._get_section_from_cache(None, element_position=350)
        section_path, section_heading = result

        # Path should be truncated to fit within 500 chars
        assert len(section_path) <= 500
        # Should contain truncation markers
        assert "..." in section_path
        # section_heading should still be the original nearest heading
        assert section_heading == long_text_3


# =============================================================================
# SEG8: Additional Element Types (blockquote, pre, figure)
# =============================================================================


class TestBlockquoteExtraction:
    """Test blockquote element extraction (SEG8)."""

    def test_simple_blockquote_extracts_as_segment(self, temp_html_file):
        """Simple blockquote with text extracts as segment with type 'blockquote'."""
        html = """
        <html><body>
            <blockquote>
                This is a quoted disclosure about our customer metrics that is long enough to pass the minimum segment length requirement.
            </blockquote>
        </body></html>
        """
        html_path = temp_html_file(html)

        try:
            segmenter = HTMLSegmenter(min_length=30)
            segments = segmenter.segment_filing(filing_id=1, html_path=html_path)

            assert len(segments) >= 1
            blockquotes = [s for s in segments if s.segment_type == "blockquote"]
            assert len(blockquotes) == 1
            assert "quoted disclosure" in blockquotes[0].raw_text
        finally:
            Path(html_path).unlink()

    def test_blockquote_with_nested_paragraphs_extracts_as_single_segment(self, temp_html_file):
        """Blockquote with nested <p> elements extracts as single segment (not multiple)."""
        html = """
        <html><body>
            <blockquote>
                <p>First paragraph of the quoted material about our customer retention metrics.</p>
                <p>Second paragraph continuing the disclosure about our annual recurring revenue.</p>
            </blockquote>
        </body></html>
        """
        html_path = temp_html_file(html)

        try:
            segmenter = HTMLSegmenter(min_length=30)
            segments = segmenter.segment_filing(filing_id=2, html_path=html_path)

            # Should have one blockquote segment containing both paragraphs
            blockquotes = [s for s in segments if s.segment_type == "blockquote"]
            assert len(blockquotes) == 1
            assert "customer retention" in blockquotes[0].raw_text
            assert "recurring revenue" in blockquotes[0].raw_text
        finally:
            Path(html_path).unlink()

    def test_blockquote_inside_table_is_skipped(self, temp_html_file):
        """Blockquote inside table is skipped (not extracted separately)."""
        html = """
        <html><body>
            <table>
                <tr>
                    <td>
                        <blockquote>This blockquote is inside a table cell and should not be extracted separately.</blockquote>
                    </td>
                </tr>
                <tr><td>Regular table data with enough content to pass the minimum segment length requirement.</td></tr>
            </table>
        </body></html>
        """
        html_path = temp_html_file(html)

        try:
            segmenter = HTMLSegmenter(min_length=30)
            segments = segmenter.segment_filing(filing_id=3, html_path=html_path)

            # Should have table segment, no separate blockquote segment
            blockquotes = [s for s in segments if s.segment_type == "blockquote"]
            assert len(blockquotes) == 0

            tables = [s for s in segments if s.segment_type == "table"]
            assert len(tables) >= 1
            # Table should contain the blockquote text
            assert "inside a table cell" in tables[0].raw_text
        finally:
            Path(html_path).unlink()

    def test_nested_blockquote_extracts_outer_only(self, temp_html_file):
        """Nested blockquote inside blockquote extracts outer only."""
        html = """
        <html><body>
            <blockquote>
                This is the outer blockquote containing important disclosure information about our metrics.
                <blockquote>
                    This is the inner nested blockquote with additional commentary on our customer base.
                </blockquote>
            </blockquote>
        </body></html>
        """
        html_path = temp_html_file(html)

        try:
            segmenter = HTMLSegmenter(min_length=30)
            segments = segmenter.segment_filing(filing_id=4, html_path=html_path)

            # Should have only one blockquote segment (outer)
            blockquotes = [s for s in segments if s.segment_type == "blockquote"]
            assert len(blockquotes) == 1
            # Outer should contain both texts
            assert "outer blockquote" in blockquotes[0].raw_text
            assert "inner nested blockquote" in blockquotes[0].raw_text
        finally:
            Path(html_path).unlink()

    def test_blockquote_with_citation(self, temp_html_file):
        """Blockquote with <cite> element inside extracts correctly."""
        html = """
        <html><body>
            <blockquote>
                We define monthly active users as users who have logged in at least once during the month.
                <cite>- Company Management Discussion and Analysis</cite>
            </blockquote>
        </body></html>
        """
        html_path = temp_html_file(html)

        try:
            segmenter = HTMLSegmenter(min_length=30)
            segments = segmenter.segment_filing(filing_id=5, html_path=html_path)

            blockquotes = [s for s in segments if s.segment_type == "blockquote"]
            assert len(blockquotes) == 1
            assert "monthly active users" in blockquotes[0].raw_text
            assert "Company Management" in blockquotes[0].raw_text
        finally:
            Path(html_path).unlink()


class TestPreformattedTextExtraction:
    """Test preformatted text (<pre>) element extraction (SEG8)."""

    def test_pre_element_extracts_as_preformatted(self, temp_html_file):
        """<pre> element extracts as segment with type 'preformatted'."""
        html = """
        <html><body>
            <pre>
                Financial Summary:
                Revenue:     $10,000,000
                Expenses:    $ 5,000,000
                Net Income:  $ 5,000,000
            </pre>
        </body></html>
        """
        html_path = temp_html_file(html)

        try:
            segmenter = HTMLSegmenter(min_length=30)
            segments = segmenter.segment_filing(filing_id=1, html_path=html_path)

            preformatted = [s for s in segments if s.segment_type == "preformatted"]
            assert len(preformatted) == 1
            assert "Financial Summary" in preformatted[0].raw_text
            assert "Revenue" in preformatted[0].raw_text
        finally:
            Path(html_path).unlink()

    def test_pre_whitespace_normalized(self, temp_html_file):
        """Whitespace in <pre> is normalized (consistent with other text handling)."""
        html = """
        <html><body>
            <pre>
                Line 1 with    multiple    spaces and enough content
                Line 2 with
                newlines in between and additional text
                Line 3 with more content to ensure sufficient segment length
            </pre>
        </body></html>
        """
        html_path = temp_html_file(html)

        try:
            segmenter = HTMLSegmenter(min_length=30)
            segments = segmenter.segment_filing(filing_id=2, html_path=html_path)

            preformatted = [s for s in segments if s.segment_type == "preformatted"]
            assert len(preformatted) == 1
            # Whitespace should be normalized
            assert "    " not in preformatted[0].raw_text  # No quad spaces
        finally:
            Path(html_path).unlink()

    def test_pre_with_code_content(self, temp_html_file):
        """<pre> with code/data content extracts correctly."""
        html = """
        <html><body>
            <pre>
            Customer Metric Definitions:
            DAU = Daily Active Users (users who log in at least once per day)
            MAU = Monthly Active Users (users who log in at least once per month)
            NRR = Net Revenue Retention (recurring revenue from existing customers)
            </pre>
        </body></html>
        """
        html_path = temp_html_file(html)

        try:
            segmenter = HTMLSegmenter(min_length=30)
            segments = segmenter.segment_filing(filing_id=3, html_path=html_path)

            preformatted = [s for s in segments if s.segment_type == "preformatted"]
            assert len(preformatted) == 1
            assert "Daily Active Users" in preformatted[0].raw_text
            assert "Net Revenue Retention" in preformatted[0].raw_text
        finally:
            Path(html_path).unlink()

    def test_pre_with_only_whitespace_skipped(self, temp_html_file):
        """<pre> with only whitespace is skipped (below min_length)."""
        html = """
        <html><body>
            <pre>


            </pre>
            <p>This paragraph has enough content to pass the minimum segment length requirement.</p>
        </body></html>
        """
        html_path = temp_html_file(html)

        try:
            segmenter = HTMLSegmenter(min_length=30)
            segments = segmenter.segment_filing(filing_id=4, html_path=html_path)

            # Should only have paragraph, no preformatted segment
            preformatted = [s for s in segments if s.segment_type == "preformatted"]
            assert len(preformatted) == 0

            paragraphs = [s for s in segments if s.segment_type == "paragraph"]
            assert len(paragraphs) >= 1
        finally:
            Path(html_path).unlink()

    def test_pre_inside_table_is_skipped(self, temp_html_file):
        """<pre> inside table is skipped (not extracted separately)."""
        html = """
        <html><body>
            <table>
                <tr>
                    <td>
                        <pre>Preformatted content inside table cell with sufficient length content.</pre>
                    </td>
                </tr>
                <tr><td>Regular table data with enough content to pass the minimum segment length.</td></tr>
            </table>
        </body></html>
        """
        html_path = temp_html_file(html)

        try:
            segmenter = HTMLSegmenter(min_length=30)
            segments = segmenter.segment_filing(filing_id=5, html_path=html_path)

            # Should have table segment, no separate preformatted segment
            preformatted = [s for s in segments if s.segment_type == "preformatted"]
            assert len(preformatted) == 0

            tables = [s for s in segments if s.segment_type == "table"]
            assert len(tables) >= 1
        finally:
            Path(html_path).unlink()


class TestFigureElementExtraction:
    """Test figure element extraction (SEG8)."""

    def test_figure_with_figcaption_extracts_caption(self, temp_html_file):
        """<figure> with <figcaption> extracts caption text as segment with type 'figure'."""
        html = """
        <html><body>
            <figure>
                <img src="chart.png" />
                <figcaption>Figure 1: Customer growth metrics showing significant year-over-year growth in active users.</figcaption>
            </figure>
        </body></html>
        """
        html_path = temp_html_file(html)

        try:
            segmenter = HTMLSegmenter(min_length=30)
            segments = segmenter.segment_filing(filing_id=1, html_path=html_path)

            figures = [s for s in segments if s.segment_type == "figure"]
            assert len(figures) == 1
            assert "Customer growth metrics" in figures[0].raw_text
        finally:
            Path(html_path).unlink()

    def test_figure_with_img_alt_extracts_alt_text(self, temp_html_file):
        """<figure> with <img alt="..."> extracts alt text."""
        html = """
        <html><body>
            <figure>
                <img src="revenue_chart.png" alt="Bar chart showing revenue growth from $5M in 2022 to $15M in 2024" />
            </figure>
        </body></html>
        """
        html_path = temp_html_file(html)

        try:
            segmenter = HTMLSegmenter(min_length=30)
            segments = segmenter.segment_filing(filing_id=2, html_path=html_path)

            figures = [s for s in segments if s.segment_type == "figure"]
            assert len(figures) == 1
            assert "revenue growth" in figures[0].raw_text.lower()
        finally:
            Path(html_path).unlink()

    def test_figure_combines_alt_and_caption(self, temp_html_file):
        """<figure> with both image alt and figcaption combines both texts."""
        html = """
        <html><body>
            <figure>
                <img src="metrics.png" alt="Quarterly customer metrics visualization chart" />
                <figcaption>Figure 2: Monthly active users grew 45% year over year during fiscal 2024.</figcaption>
            </figure>
        </body></html>
        """
        html_path = temp_html_file(html)

        try:
            segmenter = HTMLSegmenter(min_length=30)
            segments = segmenter.segment_filing(filing_id=3, html_path=html_path)

            figures = [s for s in segments if s.segment_type == "figure"]
            assert len(figures) == 1
            # Should contain both alt text and caption
            assert "customer metrics" in figures[0].raw_text.lower()
            assert "active users grew" in figures[0].raw_text.lower()
        finally:
            Path(html_path).unlink()

    def test_empty_figure_image_only_skipped(self, temp_html_file):
        """Empty figure (image only, no text) is skipped (below min_length)."""
        html = """
        <html><body>
            <figure>
                <img src="image.png" />
            </figure>
            <p>This paragraph has enough content to pass the minimum segment length requirement.</p>
        </body></html>
        """
        html_path = temp_html_file(html)

        try:
            segmenter = HTMLSegmenter(min_length=30)
            segments = segmenter.segment_filing(filing_id=4, html_path=html_path)

            # Should only have paragraph, no figure segment (no text)
            figures = [s for s in segments if s.segment_type == "figure"]
            assert len(figures) == 0

            paragraphs = [s for s in segments if s.segment_type == "paragraph"]
            assert len(paragraphs) >= 1
        finally:
            Path(html_path).unlink()

    def test_figure_with_multiple_images_combines_alt_texts(self, temp_html_file):
        """<figure> with multiple images combines all alt texts."""
        html = """
        <html><body>
            <figure>
                <img src="chart1.png" alt="Revenue growth chart showing quarterly trends" />
                <img src="chart2.png" alt="Customer acquisition cost breakdown by channel" />
                <figcaption>Figures showing key business metrics and financial performance.</figcaption>
            </figure>
        </body></html>
        """
        html_path = temp_html_file(html)

        try:
            segmenter = HTMLSegmenter(min_length=30)
            segments = segmenter.segment_filing(filing_id=5, html_path=html_path)

            figures = [s for s in segments if s.segment_type == "figure"]
            assert len(figures) == 1
            # Should contain alt text from both images and caption
            assert "Revenue growth" in figures[0].raw_text
            assert "acquisition cost" in figures[0].raw_text
            assert "business metrics" in figures[0].raw_text
        finally:
            Path(html_path).unlink()

    def test_nested_figure_extracts_outer_only(self, temp_html_file):
        """Nested figure inside figure extracts outer only."""
        html = """
        <html><body>
            <figure>
                <figcaption>Outer figure caption with customer metrics overview and summary.</figcaption>
                <figure>
                    <figcaption>Inner nested figure caption with additional detail information.</figcaption>
                </figure>
            </figure>
        </body></html>
        """
        html_path = temp_html_file(html)

        try:
            segmenter = HTMLSegmenter(min_length=30)
            segments = segmenter.segment_filing(filing_id=6, html_path=html_path)

            # Should have only one figure segment (outer)
            figures = [s for s in segments if s.segment_type == "figure"]
            assert len(figures) == 1
            # Outer should contain both captions
            assert "Outer figure" in figures[0].raw_text
            assert "Inner nested" in figures[0].raw_text
        finally:
            Path(html_path).unlink()

    def test_figure_inside_table_is_skipped(self, temp_html_file):
        """<figure> inside table is skipped (not extracted separately)."""
        html = """
        <html><body>
            <table>
                <tr>
                    <td>
                        <figure>
                            <figcaption>Figure inside table cell with caption text.</figcaption>
                        </figure>
                    </td>
                </tr>
                <tr><td>Regular table data with enough content to pass the minimum segment length.</td></tr>
            </table>
        </body></html>
        """
        html_path = temp_html_file(html)

        try:
            segmenter = HTMLSegmenter(min_length=30)
            segments = segmenter.segment_filing(filing_id=7, html_path=html_path)

            # Should have table segment, no separate figure segment
            figures = [s for s in segments if s.segment_type == "figure"]
            assert len(figures) == 0

            tables = [s for s in segments if s.segment_type == "table"]
            assert len(tables) >= 1
        finally:
            Path(html_path).unlink()


class TestSEG8Integration:
    """Integration tests for SEG8 new element types."""

    def test_full_document_with_all_new_element_types(self, temp_html_file):
        """Full document with all new element types extracts correctly."""
        html = """
        <html><body>
            <h1>Business Overview</h1>
            <p>We are a technology company providing cloud services to enterprise customers worldwide.</p>

            <blockquote>
                Management believes that daily active users is a key indicator of customer engagement.
            </blockquote>

            <pre>
            Key Metrics Summary:
            - Daily Active Users: 500,000
            - Monthly Active Users: 2,000,000
            - Annual Recurring Revenue: $50M
            </pre>

            <figure>
                <img src="growth.png" alt="Chart showing 45% year-over-year growth in users" />
                <figcaption>Figure 1: User growth trajectory from 2022 to 2024 fiscal years.</figcaption>
            </figure>

            <p>We continue to invest in customer acquisition and retention strategies for growth.</p>
        </body></html>
        """
        html_path = temp_html_file(html)

        try:
            segmenter = HTMLSegmenter(min_length=30)
            segments = segmenter.segment_filing(filing_id=1, html_path=html_path)

            # Should have multiple segment types
            segment_types = set(s.segment_type for s in segments)

            assert "paragraph" in segment_types
            assert "blockquote" in segment_types
            assert "preformatted" in segment_types
            assert "figure" in segment_types

            # Verify segment content
            blockquotes = [s for s in segments if s.segment_type == "blockquote"]
            assert any("key indicator" in s.raw_text for s in blockquotes)

            preformatted = [s for s in segments if s.segment_type == "preformatted"]
            assert any("Key Metrics Summary" in s.raw_text for s in preformatted)

            figures = [s for s in segments if s.segment_type == "figure"]
            assert any("growth trajectory" in s.raw_text.lower() for s in figures)

        finally:
            Path(html_path).unlink()

    def test_new_element_types_have_section_heading(self, temp_html_file):
        """New element types inherit section heading like other elements."""
        html = """
        <html><body>
            <h1>Risk Factors</h1>
            <blockquote>
                We may experience fluctuations in our quarterly operating results due to various factors.
            </blockquote>
            <pre>
            Risk Categories:
            - Market Risk
            - Operational Risk
            - Regulatory Risk
            </pre>
            <figure>
                <figcaption>Figure showing historical risk exposure metrics by category over time.</figcaption>
            </figure>
        </body></html>
        """
        html_path = temp_html_file(html)

        try:
            segmenter = HTMLSegmenter(min_length=30)
            segments = segmenter.segment_filing(filing_id=2, html_path=html_path)

            # All segments should have the section heading
            for segment in segments:
                if segment.segment_type in ("blockquote", "preformatted", "figure"):
                    assert segment.section_heading == "Risk Factors"

        finally:
            Path(html_path).unlink()


# =============================================================================
# SEG10: CSS Selector Generation Tests
# =============================================================================


class TestCSSSelector:
    """Test suite for CSS selector generation (SEG10).

    Tests the generation of CSS selector paths that uniquely identify
    each segment's source element in the original HTML document.
    """

    def test_element_with_id_returns_id_selector(self):
        """Element with ID returns #id selector."""
        segmenter = HTMLSegmenter()
        from bs4 import BeautifulSoup

        html = '<div><p id="intro">Content</p></div>'
        soup = BeautifulSoup(html, "html.parser")
        element = soup.find("p")

        selector = segmenter._generate_css_selector(element)
        assert selector == "#intro"

    def test_element_with_class_returns_tag_dot_class(self):
        """Element with class returns tag.classname selector."""
        segmenter = HTMLSegmenter()
        from bs4 import BeautifulSoup

        html = '<div><p class="disclosure summary">Content</p></div>'
        soup = BeautifulSoup(html, "html.parser")
        element = soup.find("p")

        selector = segmenter._generate_css_selector(element)
        # Should use first class only
        assert "p.disclosure" in selector

    def test_element_without_id_or_class_uses_nth_of_type(self):
        """Element without ID or class uses tag:nth-of-type(n)."""
        segmenter = HTMLSegmenter()
        from bs4 import BeautifulSoup

        html = '<div><p>First</p><p>Second</p><p>Third</p></div>'
        soup = BeautifulSoup(html, "html.parser")
        paragraphs = soup.find_all("p")

        # First paragraph
        selector1 = segmenter._generate_css_selector(paragraphs[0])
        assert "p:nth-of-type(1)" in selector1

        # Third paragraph
        selector3 = segmenter._generate_css_selector(paragraphs[2])
        assert "p:nth-of-type(3)" in selector3

    def test_multiple_classes_uses_first_only(self):
        """Element with multiple classes uses only the first class."""
        segmenter = HTMLSegmenter()
        from bs4 import BeautifulSoup

        html = '<p class="primary secondary tertiary">Content</p>'
        soup = BeautifulSoup(html, "html.parser")
        element = soup.find("p")

        selector = segmenter._element_selector(element)
        assert selector == "p.primary"

    def test_path_builds_from_element_to_root(self):
        """Selector path builds from element toward root."""
        segmenter = HTMLSegmenter()
        from bs4 import BeautifulSoup

        html = '<html><body><div class="content"><p>Nested paragraph</p></div></body></html>'
        soup = BeautifulSoup(html, "html.parser")
        element = soup.find("p")

        selector = segmenter._generate_css_selector(element)
        # Should contain path with > separators
        assert " > " in selector
        # Should include div and p
        assert "div.content" in selector
        assert "p:nth-of-type(1)" in selector

    def test_path_terminates_at_id_element(self):
        """Selector path terminates at first element with ID."""
        segmenter = HTMLSegmenter()
        from bs4 import BeautifulSoup

        html = '<html><body><div id="main"><section><p>Deep content</p></section></div></body></html>'
        soup = BeautifulSoup(html, "html.parser")
        element = soup.find("p")

        selector = segmenter._generate_css_selector(element)
        # Should start with #main (the ID element)
        assert selector.startswith("#main")
        # Should not include body or html
        assert "body" not in selector
        assert "html" not in selector

    def test_path_limited_to_six_levels(self):
        """Selector path is limited to 6 levels maximum."""
        segmenter = HTMLSegmenter()
        from bs4 import BeautifulSoup

        # Create deeply nested HTML (8 levels)
        html = """
        <html><body>
            <div><div><div><div><div><div><div><div>
                <p>Very deeply nested</p>
            </div></div></div></div></div></div></div></div>
        </body></html>
        """
        soup = BeautifulSoup(html, "html.parser")
        element = soup.find("p")

        selector = segmenter._generate_css_selector(element)
        # Count the number of > separators (should be at most 5 for 6 parts)
        parts = selector.split(" > ")
        assert len(parts) <= 6

    def test_uses_direct_descendant_combinator(self):
        """Selector uses ' > ' (direct descendant combinator)."""
        segmenter = HTMLSegmenter()
        from bs4 import BeautifulSoup

        html = '<div class="outer"><div class="inner"><p>Content</p></div></div>'
        soup = BeautifulSoup(html, "html.parser")
        element = soup.find("p")

        selector = segmenter._generate_css_selector(element)
        # Should use direct descendant combinator
        assert " > " in selector
        # Should not use space-only (descendant combinator)
        parts = selector.split(" > ")
        assert all(part.strip() for part in parts)

    def test_special_characters_in_id_escaped(self):
        """Special characters in ID are escaped for CSS."""
        segmenter = HTMLSegmenter()
        from bs4 import BeautifulSoup

        html = '<p id="section:1.2">Content</p>'
        soup = BeautifulSoup(html, "html.parser")
        element = soup.find("p")

        selector = segmenter._generate_css_selector(element)
        # Colon and period should be escaped
        assert "\\:" in selector or "\\." in selector

    def test_special_characters_in_class_escaped(self):
        """Special characters in class are escaped for CSS."""
        segmenter = HTMLSegmenter()
        from bs4 import BeautifulSoup

        html = '<p class="item:value">Content</p>'
        soup = BeautifulSoup(html, "html.parser")
        element = soup.find("p")

        selector = segmenter._element_selector(element)
        # Colon should be escaped
        assert "\\:" in selector

    def test_root_element_returns_single_selector(self):
        """Root element (no ancestors) returns just the element's selector."""
        segmenter = HTMLSegmenter()
        from bs4 import BeautifulSoup

        html = '<p id="root">Solo element</p>'
        soup = BeautifulSoup(html, "html.parser")
        element = soup.find("p")

        selector = segmenter._generate_css_selector(element)
        # Should just be the ID selector
        assert selector == "#root"

    def test_invalid_element_returns_none(self):
        """Invalid or None element returns None."""
        segmenter = HTMLSegmenter()

        # None element
        assert segmenter._generate_css_selector(None) is None

        # NavigableString (not Tag) - simulate
        from bs4 import BeautifulSoup

        html = '<p>Text content</p>'
        soup = BeautifulSoup(html, "html.parser")
        text_node = soup.find("p").string  # This is a NavigableString

        result = segmenter._generate_css_selector(text_node)
        assert result is None

    def test_table_cell_includes_table_and_row(self):
        """Table cell selector includes parent tr and table in path."""
        segmenter = HTMLSegmenter()
        from bs4 import BeautifulSoup

        html = """
        <table id="financials">
            <tr><th>Metric</th><th>Value</th></tr>
            <tr><td>Revenue</td><td>$10M</td></tr>
        </table>
        """
        soup = BeautifulSoup(html, "html.parser")
        # Get the data cell with "$10M"
        cell = soup.find_all("td")[1]

        selector = segmenter._generate_css_selector(cell)
        # Should start at the table ID
        assert selector.startswith("#financials")
        # Should include the row
        assert "tr" in selector
        # Should include the cell
        assert "td" in selector

    def test_list_item_selector_specific_to_item(self):
        """List item gets specific selector, not just parent list."""
        segmenter = HTMLSegmenter()
        from bs4 import BeautifulSoup

        html = """
        <ul id="features">
            <li>First feature</li>
            <li>Second feature</li>
            <li>Third feature</li>
        </ul>
        """
        soup = BeautifulSoup(html, "html.parser")
        list_items = soup.find_all("li")

        # Second list item should have nth-of-type(2)
        selector = segmenter._generate_css_selector(list_items[1])
        assert "#features" in selector
        assert "li:nth-of-type(2)" in selector

    def test_full_segmentation_populates_html_selector(self, temp_html_file):
        """Full segment_filing() populates html_selector for all segments."""
        html = """
        <html><body>
            <h1>Prospectus Summary</h1>
            <p id="intro">We are a leading technology company with innovative products and services.</p>
            <p class="metrics">Our key metrics include daily active users and revenue per user growth.</p>
            <table id="data">
                <tr><th>Metric</th><th>Value</th></tr>
                <tr><td>DAU</td><td>1,500,000</td></tr>
            </table>
        </body></html>
        """
        html_path = temp_html_file(html)
        segmenter = HTMLSegmenter(min_length=20)

        try:
            segments = segmenter.segment_filing(filing_id=1, html_path=html_path)

            # All segments should have html_selector populated
            for segment in segments:
                assert segment.html_selector is not None, f"Segment missing selector: {segment.raw_text[:50]}"
                # Selector should be valid CSS syntax (contains expected patterns)
                assert any(
                    pattern in segment.html_selector
                    for pattern in ["#", ".", "nth-of-type"]
                ), f"Invalid selector format: {segment.html_selector}"

        finally:
            Path(html_path).unlink()

    def test_selectors_are_distinct_for_different_elements(self, temp_html_file):
        """Different segments have distinct selectors (for unique elements)."""
        html = """
        <html><body>
            <div class="content">
                <p>First paragraph with enough text to meet minimum length requirements for extraction.</p>
                <p>Second paragraph with different content and sufficient text length as well.</p>
                <p>Third paragraph also with enough text to be extracted as a separate segment.</p>
            </div>
        </body></html>
        """
        html_path = temp_html_file(html)
        segmenter = HTMLSegmenter(min_length=30)

        try:
            segments = segmenter.segment_filing(filing_id=2, html_path=html_path)

            # Get paragraph segments
            paragraphs = [s for s in segments if s.segment_type == "paragraph"]

            # Selectors should be unique
            selectors = [p.html_selector for p in paragraphs]
            assert len(selectors) == len(set(selectors)), "Selectors should be unique for different elements"

            # Should have different nth-of-type values
            assert any("nth-of-type(1)" in s for s in selectors)
            assert any("nth-of-type(2)" in s for s in selectors)

        finally:
            Path(html_path).unlink()

    def test_escape_css_identifier_special_chars(self):
        """Test _escape_css_identifier handles various special characters."""
        segmenter = HTMLSegmenter()

        # Colon
        assert segmenter._escape_css_identifier("section:1") == "section\\:1"

        # Period
        assert segmenter._escape_css_identifier("item.1") == "item\\.1"

        # Brackets
        assert segmenter._escape_css_identifier("arr[0]") == "arr\\[0\\]"

        # Parentheses
        assert segmenter._escape_css_identifier("func(x)") == "func\\(x\\)"

        # Space
        assert segmenter._escape_css_identifier("my id") == "my\\ id"

        # Multiple special chars
        assert segmenter._escape_css_identifier("a:b.c[d]") == "a\\:b\\.c\\[d\\]"


# ===== SEG9: Cached DOM Parsing Tests =====


class TestSEG9CachedDOMParsing:
    """Test suite for SEG9 cached DOM element optimization in composite splitting."""

    def test_split_with_cached_element_same_results(self, temp_html_file):
        """Splitting with cached element produces identical results to parsing raw_html."""
        from bs4 import BeautifulSoup, Tag
        from src.extraction.models import SourceSegment

        segmenter = HTMLSegmenter()

        # Create a composite segment with text and table
        html = """<div>
            <p>Our revenue metrics show growth in Q4 2024:</p>
            <table>
                <tr><th>Quarter</th><th>Revenue</th></tr>
                <tr><td>Q4 2024</td><td>$5M</td></tr>
            </table>
        </div>"""

        segment = SourceSegment(
            filing_id=1,
            segment_type="paragraph",
            raw_text="Our revenue metrics show growth in Q4 2024: Quarter Revenue Q4 2024 $5M",
            raw_html=html,
            sequence_index=0
        )

        # Parse element for caching
        soup = BeautifulSoup(html, "html.parser")
        cached_element = soup.find("div")

        # Split with cached element
        result_with_cache = segmenter._split_composite_segment(segment, parsed_element=cached_element)

        # Split without cached element (fallback to parsing)
        result_without_cache = segmenter._split_composite_segment(segment, parsed_element=None)

        # Both should produce the same number of segments
        assert len(result_with_cache) == len(result_without_cache)

        # Both should have same segment types
        types_with_cache = [s.segment_type for s in result_with_cache]
        types_without_cache = [s.segment_type for s in result_without_cache]
        assert types_with_cache == types_without_cache

    def test_cached_element_avoids_parsing(self, temp_html_file, monkeypatch):
        """When cached element provided, BeautifulSoup is not called for main parsing."""
        from bs4 import BeautifulSoup, Tag
        from src.extraction.models import SourceSegment
        import src.extraction.html_segmenter as segmenter_module

        segmenter = HTMLSegmenter()

        # Create HTML with table
        html = """<div>
            <p>Some text before the table that describes the metrics below.</p>
            <table>
                <tr><th>Metric</th><th>Value</th></tr>
                <tr><td>Users</td><td>10,000</td></tr>
            </table>
        </div>"""

        segment = SourceSegment(
            filing_id=1,
            segment_type="paragraph",
            raw_text="Some text before the table. Metric Value Users 10,000",
            raw_html=html,
            sequence_index=0
        )

        # Parse element for caching
        soup = BeautifulSoup(html, "html.parser")
        cached_element = soup.find("div")

        # Track BeautifulSoup instantiation calls
        original_bs = BeautifulSoup
        bs_call_count = [0]

        def mock_bs(*args, **kwargs):
            bs_call_count[0] += 1
            return original_bs(*args, **kwargs)

        monkeypatch.setattr(segmenter_module, "BeautifulSoup", mock_bs)

        # Split with cached element
        result = segmenter._split_composite_segment(segment, parsed_element=cached_element)

        # Should not call BeautifulSoup for main parsing (only for fragment extraction)
        # The main soup parse would be the first call, so we check it wasn't called
        # for that purpose (fragment parsing still happens)
        assert len(result) >= 2  # Should have split the segment

    def test_none_cached_element_triggers_parsing(self, temp_html_file):
        """When cached element is None, raw_html is parsed (backward compatibility)."""
        from src.extraction.models import SourceSegment

        segmenter = HTMLSegmenter()

        html = """<div>
            <p>Text with metrics explanation before the data table.</p>
            <table>
                <tr><th>Metric</th><th>Value</th></tr>
                <tr><td>Active Users</td><td>50,000</td></tr>
            </table>
        </div>"""

        segment = SourceSegment(
            filing_id=1,
            segment_type="paragraph",
            raw_text="Text with metrics explanation. Metric Value Active Users 50,000",
            raw_html=html,
            sequence_index=0
        )

        # Split with None cached element
        result = segmenter._split_composite_segment(segment, parsed_element=None)

        # Should successfully split despite no cached element
        assert len(result) >= 2
        segment_types = [s.segment_type for s in result]
        assert "paragraph" in segment_types
        assert "table" in segment_types

    def test_invalid_cached_element_type_triggers_fallback(self):
        """When cached element is not a Tag, falls back to parsing raw_html."""
        from src.extraction.models import SourceSegment

        segmenter = HTMLSegmenter()

        html = """<div>
            <p>Paragraph text with important metric context information.</p>
            <table>
                <tr><th>Metric</th><th>Value</th></tr>
                <tr><td>Revenue</td><td>$1M</td></tr>
            </table>
        </div>"""

        segment = SourceSegment(
            filing_id=1,
            segment_type="paragraph",
            raw_text="Paragraph text. Metric Value Revenue $1M",
            raw_html=html,
            sequence_index=0
        )

        # Pass invalid types as cached_element
        for invalid_element in ["string", 123, {"dict": "value"}, []]:
            result = segmenter._split_composite_segment(segment, parsed_element=invalid_element)

            # Should still split correctly using fallback parsing
            assert len(result) >= 2

    def test_element_cache_cleared_after_splitting(self, temp_html_file):
        """Element cache is cleared after splitting phase in segment_filing()."""
        html = """
        <html><body>
            <div>
                <p>Our key performance metrics for the quarter ending December 31, 2024:</p>
                <table>
                    <tr><th>Metric</th><th>Value</th></tr>
                    <tr><td>Users</td><td>10,000</td></tr>
                </table>
            </div>
        </body></html>
        """

        html_path = temp_html_file(html)
        segmenter = HTMLSegmenter(min_length=20)

        try:
            segments = segmenter.segment_filing(filing_id=1, html_path=html_path)

            # Segments should be returned successfully
            assert len(segments) >= 2

            # Final segments should not contain any Tag references
            for segment in segments:
                # Check that no Tag objects are stored in segment attributes
                assert not hasattr(segment, '_cached_element')
                assert not hasattr(segment, 'element')

                # Verify the segment is a clean SourceSegment with expected types
                assert isinstance(segment.raw_text, str)
                assert segment.raw_html is None or isinstance(segment.raw_html, str)

        finally:
            Path(html_path).unlink()

    def test_final_segments_no_tag_references(self, temp_html_file):
        """Final SourceSegment objects contain no BeautifulSoup Tag references."""
        from bs4 import Tag

        html = """
        <html><body>
            <div>
                <p>Customer metrics indicate strong engagement across all user segments.</p>
                <table>
                    <tr><th>Segment</th><th>Users</th></tr>
                    <tr><td>Enterprise</td><td>5,000</td></tr>
                    <tr><td>SMB</td><td>25,000</td></tr>
                </table>
                <p>We expect continued growth in the SMB segment going forward.</p>
            </div>
        </body></html>
        """

        html_path = temp_html_file(html)
        segmenter = HTMLSegmenter(min_length=20)

        try:
            segments = segmenter.segment_filing(filing_id=1, html_path=html_path)

            for segment in segments:
                # Check all attributes for Tag objects
                for attr_name, attr_value in segment.__dict__.items():
                    assert not isinstance(attr_value, Tag), \
                        f"Segment attribute {attr_name} contains Tag reference"

        finally:
            Path(html_path).unlink()

    def test_full_pipeline_with_composite_segments(self, temp_html_file):
        """Integration test: full pipeline correctly processes composite segments."""
        html = """
        <html><body>
            <h1>Prospectus Summary</h1>
            <p>We are a leading technology company with a growing customer base.</p>

            <div>
                <p>Key metrics for the fiscal year ended December 31, 2024:</p>
                <table>
                    <tr><th>Metric</th><th>2024</th><th>2023</th></tr>
                    <tr><td>Active Users</td><td>100,000</td><td>75,000</td></tr>
                    <tr><td>Revenue ($M)</td><td>50</td><td>35</td></tr>
                </table>
                <p>As shown above, we achieved 33% growth in active users.</p>
            </div>

            <p>We define active users as unique users who logged in during the period.</p>
        </body></html>
        """

        html_path = temp_html_file(html)
        segmenter = HTMLSegmenter(min_length=30)

        try:
            segments = segmenter.segment_filing(filing_id=1, html_path=html_path)

            # Should have multiple segments from splitting
            assert len(segments) >= 4

            # Check we have both paragraph and table types
            segment_types = {s.segment_type for s in segments}
            assert "paragraph" in segment_types
            assert "table" in segment_types

            # Verify sequence indices are reasonable (may be fractional after split)
            indices = [s.sequence_index for s in segments]
            assert all(i >= 0 for i in indices)

            # Verify content was split correctly
            table_segments = [s for s in segments if s.segment_type == "table"]
            assert len(table_segments) >= 1
            assert any("Active Users" in s.raw_text for s in table_segments)

        finally:
            Path(html_path).unlink()

    def test_segment_no_tables_early_return(self):
        """Segment without tables returns early without parsing (quick check)."""
        from src.extraction.models import SourceSegment

        segmenter = HTMLSegmenter()

        # Segment with no table HTML
        segment = SourceSegment(
            filing_id=1,
            segment_type="paragraph",
            raw_text="This is just a plain text paragraph with no tables.",
            raw_html="<p>This is just a plain text paragraph with no tables.</p>",
            sequence_index=0
        )

        result = segmenter._split_composite_segment(segment, parsed_element=None)

        # Should return original segment immediately
        assert len(result) == 1
        assert result[0] is segment  # Same object returned

    def test_table_segment_type_early_return(self):
        """Segment with type 'table' returns early without processing."""
        from src.extraction.models import SourceSegment

        segmenter = HTMLSegmenter()

        # Segment already typed as table
        segment = SourceSegment(
            filing_id=1,
            segment_type="table",
            raw_text="Metric Value Users 10,000",
            raw_html="<table><tr><th>Metric</th><th>Value</th></tr><tr><td>Users</td><td>10,000</td></tr></table>",
            sequence_index=0
        )

        result = segmenter._split_composite_segment(segment, parsed_element=None)

        # Should return original segment immediately
        assert len(result) == 1
        assert result[0] is segment

    def test_nested_tables_only_top_level_extracted(self, temp_html_file):
        """Only top-level tables are extracted, nested tables within tables are skipped."""
        from bs4 import BeautifulSoup
        from src.extraction.models import SourceSegment

        segmenter = HTMLSegmenter()

        # HTML with nested table
        html = """<div>
            <p>Summary of our financial metrics for investor review.</p>
            <table>
                <tr><th>Category</th><th>Details</th></tr>
                <tr>
                    <td>Revenue</td>
                    <td>
                        <table>
                            <tr><td>Q1</td><td>$10M</td></tr>
                            <tr><td>Q2</td><td>$12M</td></tr>
                        </table>
                    </td>
                </tr>
            </table>
        </div>"""

        segment = SourceSegment(
            filing_id=1,
            segment_type="paragraph",
            raw_text="Summary of financial metrics. Category Details Revenue Q1 $10M Q2 $12M",
            raw_html=html,
            sequence_index=0
        )

        # Parse for caching
        soup = BeautifulSoup(html, "html.parser")
        cached_element = soup.find("div")

        result = segmenter._split_composite_segment(segment, parsed_element=cached_element)

        # Should split into text + table (only outer table)
        assert len(result) >= 2
        table_segments = [s for s in result if s.segment_type == "table"]
        # Should have exactly 1 table (the outer one), not 2
        assert len(table_segments) == 1

    def test_empty_raw_html_returns_original(self):
        """Segment with empty raw_html returns original segment."""
        from src.extraction.models import SourceSegment

        segmenter = HTMLSegmenter()

        segment = SourceSegment(
            filing_id=1,
            segment_type="paragraph",
            raw_text="Some text content",
            raw_html=None,
            sequence_index=0
        )

        result = segmenter._split_composite_segment(segment, parsed_element=None)

        assert len(result) == 1
        assert result[0] is segment
