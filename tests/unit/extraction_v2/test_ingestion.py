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


class TestXPathGeneration:
    """Test stable XPath locator generation (AC-4)."""

    def test_generate_xpath_root_element(self, tmp_path: Path) -> None:
        """Test XPath generation for root element."""
        html_content = b"<html><body><p>Test</p></body></html>"
        html_file = tmp_path / "test.html"
        html_file.write_bytes(html_content)

        stage = IngestionStage()
        tree = stage._parse_html(html_file)
        assert tree is not None

        # Root element should have simple XPath
        xpath = stage._generate_xpath(tree)
        assert xpath == "/html"

    def test_generate_xpath_nested_elements(self, tmp_path: Path) -> None:
        """Test XPath generation for nested elements."""
        html_content = b"""
        <html>
        <body>
            <div>
                <p>First paragraph</p>
                <p>Second paragraph</p>
            </div>
        </body>
        </html>
        """
        html_file = tmp_path / "test.html"
        html_file.write_bytes(html_content)

        stage = IngestionStage()
        tree = stage._parse_html(html_file)
        assert tree is not None

        # Find the second paragraph
        paragraphs = tree.xpath("//p")
        assert len(paragraphs) == 2

        # First paragraph
        xpath1 = stage._generate_xpath(paragraphs[0])
        assert xpath1 == "/html/body[1]/div[1]/p[1]"

        # Second paragraph
        xpath2 = stage._generate_xpath(paragraphs[1])
        assert xpath2 == "/html/body[1]/div[1]/p[2]"

    def test_generate_xpath_multiple_siblings(self, tmp_path: Path) -> None:
        """Test XPath generation with multiple sibling types."""
        html_content = b"""
        <html>
        <body>
            <div>Content 1</div>
            <p>Paragraph 1</p>
            <div>Content 2</div>
            <p>Paragraph 2</p>
            <div>Content 3</div>
        </body>
        </html>
        """
        html_file = tmp_path / "test.html"
        html_file.write_bytes(html_content)

        stage = IngestionStage()
        tree = stage._parse_html(html_file)
        assert tree is not None

        # Find all divs and ps
        divs = tree.xpath("//div")
        ps = tree.xpath("//p")

        # Check each div has correct position
        assert stage._generate_xpath(divs[0]) == "/html/body[1]/div[1]"
        assert stage._generate_xpath(divs[1]) == "/html/body[1]/div[2]"
        assert stage._generate_xpath(divs[2]) == "/html/body[1]/div[3]"

        # Check paragraphs have correct positions
        assert stage._generate_xpath(ps[0]) == "/html/body[1]/p[1]"
        assert stage._generate_xpath(ps[1]) == "/html/body[1]/p[2]"

    def test_generate_xpath_table_cells(self, tmp_path: Path) -> None:
        """Test XPath generation for table cells."""
        html_content = b"""
        <html>
        <body>
            <table>
                <tr>
                    <th>Header 1</th>
                    <th>Header 2</th>
                </tr>
                <tr>
                    <td>Data 1</td>
                    <td>Data 2</td>
                </tr>
            </table>
        </body>
        </html>
        """
        html_file = tmp_path / "test.html"
        html_file.write_bytes(html_content)

        stage = IngestionStage()
        tree = stage._parse_html(html_file)
        assert tree is not None

        # Find table cells
        ths = tree.xpath("//th")
        tds = tree.xpath("//td")

        # Check header cells
        assert stage._generate_xpath(ths[0]) == "/html/body[1]/table[1]/tr[1]/th[1]"
        assert stage._generate_xpath(ths[1]) == "/html/body[1]/table[1]/tr[1]/th[2]"

        # Check data cells
        assert stage._generate_xpath(tds[0]) == "/html/body[1]/table[1]/tr[2]/td[1]"
        assert stage._generate_xpath(tds[1]) == "/html/body[1]/table[1]/tr[2]/td[2]"

    def test_xpath_locator_stability(self, tmp_path: Path) -> None:
        """Test that XPath locators are stable across re-parsing."""
        html_content = b"""
        <html>
        <body>
            <div>
                <p>Target paragraph</p>
            </div>
        </body>
        </html>
        """
        html_file = tmp_path / "test.html"
        html_file.write_bytes(html_content)

        stage = IngestionStage()

        # Parse twice
        tree1 = stage._parse_html(html_file)
        tree2 = stage._parse_html(html_file)

        assert tree1 is not None
        assert tree2 is not None

        # Find same element in both trees
        p1 = tree1.xpath("//p")[0]
        p2 = tree2.xpath("//p")[0]

        # Generate XPaths
        xpath1 = stage._generate_xpath(p1)
        xpath2 = stage._generate_xpath(p2)

        # Should be identical
        assert xpath1 == xpath2
        assert xpath1 == "/html/body[1]/div[1]/p[1]"

    def test_xpath_can_locate_element(self, tmp_path: Path) -> None:
        """Test that generated XPath can locate the original element."""
        html_content = b"""
        <html>
        <body>
            <div>
                <p>First</p>
                <p>Second</p>
                <p>Target paragraph with unique text</p>
            </div>
        </body>
        </html>
        """
        html_file = tmp_path / "test.html"
        html_file.write_bytes(html_content)

        stage = IngestionStage()
        tree = stage._parse_html(html_file)
        assert tree is not None

        # Find the target paragraph
        target = tree.xpath("//p[contains(text(), 'unique text')]")[0]

        # Generate XPath
        xpath = stage._generate_xpath(target)

        # Use XPath to find element again
        found = tree.xpath(xpath)

        assert len(found) == 1
        assert found[0] is target
        assert "unique text" in found[0].text_content()


class TestParagraphDetection:
    """Test paragraph detection from V1 (AC-5)."""

    def test_extract_simple_paragraph(self, tmp_path: Path) -> None:
        """Test extracting a simple paragraph."""
        html_content = b"""
        <html>
        <body>
            <p>This is a test paragraph with enough content to meet the minimum length requirement of 50 characters.</p>
        </body>
        </html>
        """
        html_file = tmp_path / "test.html"
        html_file.write_bytes(html_content)

        stage = IngestionStage()
        tree = stage._parse_html(html_file)
        assert tree is not None

        segments = stage._extract_paragraph_segments(tree, filing_id=12345)

        assert len(segments) == 1
        assert segments[0].segment_type.value == "paragraph"
        assert "test paragraph" in segments[0].text
        assert segments[0].sequence == 0

    def test_filter_short_paragraphs(self, tmp_path: Path) -> None:
        """Test that paragraphs below 50 chars are filtered out."""
        html_content = b"""
        <html>
        <body>
            <p>Short</p>
            <p>This is a longer paragraph with enough content to meet the minimum length requirement.</p>
        </body>
        </html>
        """
        html_file = tmp_path / "test.html"
        html_file.write_bytes(html_content)

        stage = IngestionStage()
        tree = stage._parse_html(html_file)
        assert tree is not None

        segments = stage._extract_paragraph_segments(tree, filing_id=12345)

        # Only the long paragraph should be extracted
        assert len(segments) == 1
        assert "longer paragraph" in segments[0].text
        assert "Short" not in segments[0].text

    def test_truncate_long_paragraphs(self, tmp_path: Path) -> None:
        """Test that paragraphs over 10000 chars are truncated."""
        # Create a paragraph with 12000 characters
        long_text = "A" * 12000
        html_content = f"""
        <html>
        <body>
            <p>{long_text}</p>
        </body>
        </html>
        """.encode()
        html_file = tmp_path / "test.html"
        html_file.write_bytes(html_content)

        stage = IngestionStage()
        tree = stage._parse_html(html_file)
        assert tree is not None

        segments = stage._extract_paragraph_segments(tree, filing_id=12345)

        assert len(segments) == 1
        # Should be truncated to 10000 chars
        assert len(segments[0].text) == 10000

    def test_skip_paragraphs_in_tables(self, tmp_path: Path) -> None:
        """Test that paragraphs inside tables are skipped."""
        html_content = b"""
        <html>
        <body>
            <p>This paragraph is outside the table and should be extracted because it has enough content.</p>
            <table>
                <tr>
                    <td>
                        <p>This paragraph is inside a table and should be skipped even though it has enough content.</p>
                    </td>
                </tr>
            </table>
        </body>
        </html>
        """
        html_file = tmp_path / "test.html"
        html_file.write_bytes(html_content)

        stage = IngestionStage()
        tree = stage._parse_html(html_file)
        assert tree is not None

        segments = stage._extract_paragraph_segments(tree, filing_id=12345)

        # Only the paragraph outside the table should be extracted
        assert len(segments) == 1
        assert "outside the table" in segments[0].text
        assert "inside a table" not in segments[0].text

    def test_extract_multiple_paragraph_types(self, tmp_path: Path) -> None:
        """Test extracting different paragraph element types (p, div, blockquote, pre, figure)."""
        html_content = b"""
        <html>
        <body>
            <p>This is a regular paragraph with sufficient content for extraction.</p>
            <div>This is a div element with sufficient content for extraction.</div>
            <blockquote>This is a blockquote element with sufficient content for extraction.</blockquote>
            <pre>This is a pre element with sufficient content for extraction.</pre>
            <figure>This is a figure element with sufficient content for extraction.</figure>
        </body>
        </html>
        """
        html_file = tmp_path / "test.html"
        html_file.write_bytes(html_content)

        stage = IngestionStage()
        tree = stage._parse_html(html_file)
        assert tree is not None

        segments = stage._extract_paragraph_segments(tree, filing_id=12345)

        # Should extract all 5 element types
        assert len(segments) == 5
        assert any("regular paragraph" in s.text for s in segments)
        assert any("div element" in s.text for s in segments)
        assert any("blockquote element" in s.text for s in segments)
        assert any("pre element" in s.text for s in segments)
        assert any("figure element" in s.text for s in segments)

    def test_normalize_whitespace(self, tmp_path: Path) -> None:
        """Test that whitespace is normalized (multiple spaces/newlines to single space)."""
        html_content = b"""
        <html>
        <body>
            <p>This    has     multiple
            spaces   and
            newlines   that should be normalized to single spaces for extraction.</p>
        </body>
        </html>
        """
        html_file = tmp_path / "test.html"
        html_file.write_bytes(html_content)

        stage = IngestionStage()
        tree = stage._parse_html(html_file)
        assert tree is not None

        segments = stage._extract_paragraph_segments(tree, filing_id=12345)

        assert len(segments) == 1
        # Multiple whitespace should be collapsed
        assert "multiple   spaces" not in segments[0].text
        assert "multiple spaces" in segments[0].text

    def test_paragraph_has_xpath_locator(self, tmp_path: Path) -> None:
        """Test that extracted paragraphs have XPath locators."""
        html_content = b"""
        <html>
        <body>
            <div>
                <p>First paragraph with enough content to meet minimum requirements.</p>
                <p>Second paragraph with enough content to meet minimum requirements.</p>
            </div>
        </body>
        </html>
        """
        html_file = tmp_path / "test.html"
        html_file.write_bytes(html_content)

        stage = IngestionStage()
        tree = stage._parse_html(html_file)
        assert tree is not None

        segments = stage._extract_paragraph_segments(tree, filing_id=12345)

        assert len(segments) == 2
        # Each segment should have an XPath locator
        assert segments[0].dom_locator == "/html/body[1]/div[1]/p[1]"
        assert segments[1].dom_locator == "/html/body[1]/div[1]/p[2]"

    def test_paragraph_sequence_numbering(self, tmp_path: Path) -> None:
        """Test that paragraphs are numbered sequentially."""
        html_content = b"""
        <html>
        <body>
            <p>First paragraph with enough content to meet minimum requirements.</p>
            <p>Second paragraph with enough content to meet minimum requirements.</p>
            <p>Third paragraph with enough content to meet minimum requirements.</p>
        </body>
        </html>
        """
        html_file = tmp_path / "test.html"
        html_file.write_bytes(html_content)

        stage = IngestionStage()
        tree = stage._parse_html(html_file)
        assert tree is not None

        segments = stage._extract_paragraph_segments(tree, filing_id=12345)

        assert len(segments) == 3
        assert segments[0].sequence == 0
        assert segments[1].sequence == 1
        assert segments[2].sequence == 2
