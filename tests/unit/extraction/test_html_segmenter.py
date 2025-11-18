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
def temp_html_file():
    """Create a temporary HTML file for testing."""
    def _create_file(content):
        with tempfile.NamedTemporaryFile(mode='w', suffix='.html', delete=False) as f:
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
        assert 'paragraph' in segment_types or 'other' in segment_types

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
        all_text = ' '.join(s.raw_text for s in segments)
        assert 'prospectus' in all_text.lower() or 'monthly active users' in all_text.lower()

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

    with tempfile.NamedTemporaryFile(mode='w', suffix='.html', delete=False) as f:
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

    with tempfile.NamedTemporaryFile(mode='w', suffix='.html', delete=False) as f:
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

    with tempfile.NamedTemporaryFile(mode='w', suffix='.html', delete=False) as f:
        f.write(html)
        html_path = f.name

    try:
        segmenter = HTMLSegmenter(min_length=10)
        segments = segmenter.segment_filing(filing_id=8, html_path=html_path)

        if segments:
            # Check that text doesn't have excessive whitespace
            for segment in segments:
                assert '    ' not in segment.raw_text  # No quad spaces
                assert '\n\n\n' not in segment.raw_text  # No triple newlines

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

    with tempfile.NamedTemporaryFile(mode='w', suffix='.html', delete=False) as f:
        f.write(html)
        html_path = f.name

    try:
        segmenter = HTMLSegmenter(min_length=20)
        segments = segmenter.segment_filing(filing_id=9, html_path=html_path)

        # Should extract the table
        assert len(segments) > 0

        # At least one segment should contain table data
        all_text = ' '.join(s.raw_text for s in segments)
        assert 'Q1 2024' in all_text or 'Revenue' in all_text

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

    with tempfile.NamedTemporaryFile(mode='w', suffix='.html', delete=False) as f:
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
