"""
Unit tests for IngestionStage (Stage 1).

Tests lxml-based HTML parsing, XPath locators, and segment extraction.
"""

import tempfile
from pathlib import Path

import pytest
from lxml import etree

from src.extraction_v2.pipeline import PipelineConfig, PipelineContext, PipelineStage
from src.extraction_v2.stages.ingestion import IngestionStage


class TestLxmlHtmlParser:
    """Test lxml-based HTML parsing (AC-3)."""

    def test_parse_valid_html(self, tmp_path: Path) -> None:
        """Test parsing valid HTML file."""
        html_content = b"""
        <html>
        <head><title>Test Filing</title></head>
        <body>
            <p>This is a test paragraph with some content.</p>
            <table>
                <tr><th>Header</th></tr>
                <tr><td>Data</td></tr>
            </table>
        </body>
        </html>
        """
        html_file = tmp_path / "test.html"
        html_file.write_bytes(html_content)

        stage = IngestionStage()
        tree = stage._parse_html(html_file)

        assert tree is not None
        assert tree.tag == "html"
        # Check that we can find elements
        paragraphs = tree.xpath("//p")
        assert len(paragraphs) == 1
        assert "test paragraph" in paragraphs[0].text_content()

    def test_parse_malformed_html(self, tmp_path: Path) -> None:
        """Test parsing malformed HTML (unclosed tags, etc.)."""
        # lxml.html should auto-fix this
        html_content = b"""
        <html>
        <body>
            <p>Unclosed paragraph
            <div>Nested div without closing
            <table><tr><td>Data
        </body>
        """
        html_file = tmp_path / "malformed.html"
        html_file.write_bytes(html_content)

        stage = IngestionStage()
        tree = stage._parse_html(html_file)

        # lxml should recover and parse this
        assert tree is not None
        assert tree.tag == "html"

    def test_parse_empty_html(self, tmp_path: Path) -> None:
        """Test parsing empty HTML file."""
        html_content = b""
        html_file = tmp_path / "empty.html"
        html_file.write_bytes(html_content)

        stage = IngestionStage()
        tree = stage._parse_html(html_file)

        # lxml.html.fromstring should handle empty content
        assert tree is not None

    def test_parse_nonexistent_file(self, tmp_path: Path) -> None:
        """Test parsing nonexistent file."""
        html_file = tmp_path / "nonexistent.html"

        stage = IngestionStage()
        tree = stage._parse_html(html_file)

        # Should return None on file not found
        assert tree is None

    def test_parse_sec_filing_structure(self, tmp_path: Path) -> None:
        """Test parsing typical SEC filing HTML structure."""
        html_content = b"""
        <html>
        <head><title>S-1 Filing</title></head>
        <body>
            <div>
                <p>Risk Factors</p>
                <p>We had 10 million daily active users as of December 31, 2024.</p>
            </div>
            <table>
                <tr>
                    <th>Metric</th>
                    <th>2024</th>
                    <th>2023</th>
                </tr>
                <tr>
                    <td>Revenue</td>
                    <td>$100M</td>
                    <td>$75M</td>
                </tr>
            </table>
            <img src="chart.png" alt="Customer Growth Chart" />
        </body>
        </html>
        """
        html_file = tmp_path / "filing.html"
        html_file.write_bytes(html_content)

        stage = IngestionStage()
        tree = stage._parse_html(html_file)

        assert tree is not None

        # Verify we can find different element types
        paragraphs = tree.xpath("//p")
        assert len(paragraphs) == 2

        tables = tree.xpath("//table")
        assert len(tables) == 1

        images = tree.xpath("//img")
        assert len(images) == 1

        # Verify text content extraction
        text = tree.text_content()
        assert "10 million daily active users" in text
        assert "Revenue" in text


class TestIngestionStageProcess:
    """Test IngestionStage.process() method integration."""

    def test_process_creates_document(self, tmp_path: Path) -> None:
        """Test that process() creates a Document object."""
        html_content = b"""
        <html>
        <body>
            <p>Test filing content</p>
        </body>
        </html>
        """
        html_file = tmp_path / "test.html"
        html_file.write_bytes(html_content)

        context = PipelineContext(
            filing_id=12345,
            html_path=html_file,
            config=PipelineConfig(),
        )

        stage = IngestionStage()
        result = stage.process(context)

        # Should succeed
        assert result.success is True
        assert result.stage == PipelineStage.INGESTION

        # Should create document
        assert context.document is not None
        assert context.document.doc_id == "12345"
        assert context.document.html_path == str(html_file)

    def test_process_handles_missing_file(self, tmp_path: Path) -> None:
        """Test that process() handles missing HTML file gracefully."""
        html_file = tmp_path / "missing.html"

        context = PipelineContext(
            filing_id=12345,
            html_path=html_file,
            config=PipelineConfig(),
        )

        stage = IngestionStage()
        result = stage.process(context)

        # Should fail gracefully
        assert result.success is False
        assert len(result.errors) > 0
        assert "not found" in result.errors[0].lower()

    def test_process_reports_metrics(self, tmp_path: Path) -> None:
        """Test that process() reports correct metrics."""
        html_content = b"<html><body><p>Test</p></body></html>"
        html_file = tmp_path / "test.html"
        html_file.write_bytes(html_content)

        context = PipelineContext(
            filing_id=12345,
            html_path=html_file,
            config=PipelineConfig(),
        )

        stage = IngestionStage()
        result = stage.process(context)

        # Should report processing metrics
        assert result.items_processed == 1  # 1 HTML file
        assert result.duration_ms >= 0  # Can be 0 for very fast operations
        assert "html_path" in result.metadata
