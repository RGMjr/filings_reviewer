"""
Unit tests for IngestionStage (Stage 1).

Tests lxml-based HTML parsing, XPath locators, and segment extraction.
"""

from pathlib import Path

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


class TestTableDetection:
    """Test table detection with div-wrapper deduplication (AC-6)."""

    def test_extract_simple_table(self, tmp_path: Path) -> None:
        """Test extracting a simple table."""
        html_content = b"""
        <html>
        <body>
            <table>
                <tr>
                    <th>Metric</th>
                    <th>2024</th>
                    <th>2023</th>
                </tr>
                <tr>
                    <td>Daily Active Users</td>
                    <td>10 million</td>
                    <td>8 million</td>
                </tr>
                <tr>
                    <td>Paid Customers</td>
                    <td>50,000</td>
                    <td>40,000</td>
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

        segments = stage._extract_table_segments(tree, filing_id=12345)

        assert len(segments) == 1
        assert segments[0].segment_type.value == "table"
        assert "Daily Active Users" in segments[0].text
        assert "10 million" in segments[0].text

    def test_skip_div_only_table_wrapper(self, tmp_path: Path) -> None:
        """Test that divs containing only a table are skipped during paragraph extraction."""
        html_content = b"""
        <html>
        <body>
            <div>
                <table>
                    <tr><th>Metric</th><th>2024</th><th>2023</th></tr>
                    <tr><td>Daily Active Users</td><td>10 million</td><td>8 million</td></tr>
                    <tr><td>Paid Customers</td><td>50,000</td><td>40,000</td></tr>
                </table>
            </div>
        </body>
        </html>
        """
        html_file = tmp_path / "test.html"
        html_file.write_bytes(html_content)

        stage = IngestionStage()
        tree = stage._parse_html(html_file)
        assert tree is not None

        # The div should be skipped in paragraph extraction
        paragraph_segments = stage._extract_paragraph_segments(tree, filing_id=12345)
        assert len(paragraph_segments) == 0

        # But the table should be extracted
        table_segments = stage._extract_table_segments(tree, filing_id=12345)
        assert len(table_segments) == 1
        assert "Daily Active Users" in table_segments[0].text

    def test_extract_div_with_text_and_table(self, tmp_path: Path) -> None:
        """Test that divs with both text and table are extracted (composite segment)."""
        html_content = b"""
        <html>
        <body>
            <div>
                Some introductory text about the table below that provides context.
                <table>
                    <tr><th>Metric</th><th>2024</th><th>2023</th></tr>
                    <tr><td>Daily Active Users</td><td>10 million</td><td>8 million</td></tr>
                    <tr><td>Paid Customers</td><td>50,000</td><td>40,000</td></tr>
                </table>
            </div>
        </body>
        </html>
        """
        html_file = tmp_path / "test.html"
        html_file.write_bytes(html_content)

        stage = IngestionStage()
        tree = stage._parse_html(html_file)
        assert tree is not None

        # The div should be extracted as a paragraph (has text + table)
        paragraph_segments = stage._extract_paragraph_segments(tree, filing_id=12345)
        assert len(paragraph_segments) == 1
        assert "introductory text" in paragraph_segments[0].text

        # The table should also be extracted separately
        table_segments = stage._extract_table_segments(tree, filing_id=12345)
        assert len(table_segments) == 1
        assert "Daily Active Users" in table_segments[0].text

    def test_table_has_xpath_locator(self, tmp_path: Path) -> None:
        """Test that extracted tables have XPath locators."""
        html_content = b"""
        <html>
        <body>
            <table>
                <tr><th>Metric</th><th>Value</th></tr>
                <tr><td>First Table with enough content for extraction</td><td>100</td></tr>
            </table>
            <table>
                <tr><th>Metric</th><th>Value</th></tr>
                <tr><td>Second Table with enough content for extraction</td><td>200</td></tr>
            </table>
        </body>
        </html>
        """
        html_file = tmp_path / "test.html"
        html_file.write_bytes(html_content)

        stage = IngestionStage()
        tree = stage._parse_html(html_file)
        assert tree is not None

        segments = stage._extract_table_segments(tree, filing_id=12345)

        assert len(segments) == 2
        assert segments[0].dom_locator == "/html/body[1]/table[1]"
        assert segments[1].dom_locator == "/html/body[1]/table[2]"

    def test_filter_empty_tables(self, tmp_path: Path) -> None:
        """Test that empty tables are filtered out."""
        html_content = b"""
        <html>
        <body>
            <table>
                <tr><td></td></tr>
            </table>
            <table>
                <tr><td>This table has enough content to be extracted properly</td></tr>
            </table>
        </body>
        </html>
        """
        html_file = tmp_path / "test.html"
        html_file.write_bytes(html_content)

        stage = IngestionStage()
        tree = stage._parse_html(html_file)
        assert tree is not None

        segments = stage._extract_table_segments(tree, filing_id=12345)

        # Only the table with content should be extracted
        assert len(segments) == 1
        assert "enough content" in segments[0].text

    def test_table_sequence_numbering(self, tmp_path: Path) -> None:
        """Test that tables are numbered sequentially."""
        html_content = b"""
        <html>
        <body>
            <table>
                <tr><th>Metric</th><th>Value</th></tr>
                <tr><td>First table with enough content for extraction</td><td>100</td></tr>
            </table>
            <table>
                <tr><th>Metric</th><th>Value</th></tr>
                <tr><td>Second table with enough content for extraction</td><td>200</td></tr>
            </table>
            <table>
                <tr><th>Metric</th><th>Value</th></tr>
                <tr><td>Third table with enough content for extraction</td><td>300</td></tr>
            </table>
        </body>
        </html>
        """
        html_file = tmp_path / "test.html"
        html_file.write_bytes(html_content)

        stage = IngestionStage()
        tree = stage._parse_html(html_file)
        assert tree is not None

        segments = stage._extract_table_segments(tree, filing_id=12345)

        assert len(segments) == 3
        assert segments[0].sequence == 0
        assert segments[1].sequence == 1
        assert segments[2].sequence == 2

    def test_should_skip_div_wrapper_detection(self, tmp_path: Path) -> None:
        """Test _should_skip_div_wrapper helper method."""
        html_content = b"""
        <html>
        <body>
            <div id="wrapper-only">
                <table>
                    <tr><td>Table content only</td></tr>
                </table>
            </div>
            <div id="wrapper-with-text">
                Some text content that makes this more than just a wrapper.
                <table>
                    <tr><td>Table content</td></tr>
                </table>
            </div>
        </body>
        </html>
        """
        html_file = tmp_path / "test.html"
        html_file.write_bytes(html_content)

        stage = IngestionStage()
        tree = stage._parse_html(html_file)
        assert tree is not None

        # Find the two divs
        wrapper_only = tree.xpath("//div[@id='wrapper-only']")[0]
        wrapper_with_text = tree.xpath("//div[@id='wrapper-with-text']")[0]

        # Wrapper-only div should be skipped
        assert stage._should_skip_div_wrapper(wrapper_only) is True

        # Wrapper with additional text should not be skipped
        assert stage._should_skip_div_wrapper(wrapper_with_text) is False


class TestTableCellRowMarkers:
    """Test [CELL] and [ROW] marker insertion for tables (AC-7)."""

    def test_single_row_table_has_cell_markers(self, tmp_path: Path) -> None:
        """Single row table should have [CELL] markers between cells."""
        html_content = b"""
        <html>
        <body>
            <table>
                <tr><td>A</td><td>B</td><td>C</td></tr>
            </table>
        </body>
        </html>
        """
        html_file = tmp_path / "test.html"
        html_file.write_bytes(html_content)

        stage = IngestionStage()
        tree = stage._parse_html(html_file)
        assert tree is not None

        table = tree.xpath("//table")[0]
        result = stage._extract_table_text_with_markers(table)

        assert result == "A [CELL] B [CELL] C"
        assert result.count("[CELL]") == 2
        assert "[ROW]" not in result  # Single row, no row markers

    def test_multi_row_table_has_row_markers(self, tmp_path: Path) -> None:
        """Multi-row table should have [ROW] markers between rows."""
        html_content = b"""
        <html>
        <body>
            <table>
                <tr><td>A</td><td>B</td></tr>
                <tr><td>C</td><td>D</td></tr>
                <tr><td>E</td><td>F</td></tr>
            </table>
        </body>
        </html>
        """
        html_file = tmp_path / "test.html"
        html_file.write_bytes(html_content)

        stage = IngestionStage()
        tree = stage._parse_html(html_file)
        assert tree is not None

        table = tree.xpath("//table")[0]
        result = stage._extract_table_text_with_markers(table)

        # Should have [CELL] markers within rows and [ROW] markers between rows
        assert "[CELL]" in result
        assert "[ROW]" in result
        assert result.count("[ROW]") == 2  # 3 rows = 2 separators
        assert result.count("[CELL]") == 3  # Each row has 1 [CELL] (2 cells per row)
        assert result == "A [CELL] B [ROW] C [CELL] D [ROW] E [CELL] F"

    def test_mixed_th_td_cells_all_marked(self, tmp_path: Path) -> None:
        """Both <th> and <td> cells should get markers."""
        html_content = b"""
        <html>
        <body>
            <table>
                <tr><th>Metric</th><th>2023</th><th>2022</th></tr>
                <tr><td>Retention Rate</td><td>171%</td><td>152%</td></tr>
            </table>
        </body>
        </html>
        """
        html_file = tmp_path / "test.html"
        html_file.write_bytes(html_content)

        stage = IngestionStage()
        tree = stage._parse_html(html_file)
        assert tree is not None

        table = tree.xpath("//table")[0]
        result = stage._extract_table_text_with_markers(table)

        # Both header and data rows should have markers
        assert "Metric [CELL] 2023 [CELL] 2022 [ROW] Retention Rate [CELL] 171% [CELL] 152%" == result

    def test_empty_cells_are_skipped(self, tmp_path: Path) -> None:
        """Empty cells should not create empty markers."""
        html_content = b"""
        <html>
        <body>
            <table>
                <tr><td>A</td><td>  </td><td>C</td></tr>
            </table>
        </body>
        </html>
        """
        html_file = tmp_path / "test.html"
        html_file.write_bytes(html_content)

        stage = IngestionStage()
        tree = stage._parse_html(html_file)
        assert tree is not None

        table = tree.xpath("//table")[0]
        result = stage._extract_table_text_with_markers(table)

        # Should skip empty middle cell
        assert result == "A [CELL] C"
        assert result.count("[CELL]") == 1

    def test_empty_row_is_skipped(self, tmp_path: Path) -> None:
        """Empty rows should not create empty markers."""
        html_content = b"""
        <html>
        <body>
            <table>
                <tr><td>A</td><td>B</td></tr>
                <tr><td></td><td>  </td></tr>
                <tr><td>C</td><td>D</td></tr>
            </table>
        </body>
        </html>
        """
        html_file = tmp_path / "test.html"
        html_file.write_bytes(html_content)

        stage = IngestionStage()
        tree = stage._parse_html(html_file)
        assert tree is not None

        table = tree.xpath("//table")[0]
        result = stage._extract_table_text_with_markers(table)

        # Should skip empty middle row
        assert result == "A [CELL] B [ROW] C [CELL] D"
        assert result.count("[ROW]") == 1  # Only one separator between 2 non-empty rows

    def test_table_with_only_headers(self, tmp_path: Path) -> None:
        """Table with only header row should work correctly."""
        html_content = b"""
        <html>
        <body>
            <table>
                <tr><th>Header 1</th><th>Header 2</th><th>Header 3</th></tr>
            </table>
        </body>
        </html>
        """
        html_file = tmp_path / "test.html"
        html_file.write_bytes(html_content)

        stage = IngestionStage()
        tree = stage._parse_html(html_file)
        assert tree is not None

        table = tree.xpath("//table")[0]
        result = stage._extract_table_text_with_markers(table)

        assert result == "Header 1 [CELL] Header 2 [CELL] Header 3"

    def test_table_segments_include_markers(self, tmp_path: Path) -> None:
        """Integration test: table segments should have markers in their text."""
        html_content = b"""
        <html>
        <body>
            <table>
                <tr><th>Period</th><th>Customers</th></tr>
                <tr><td>Q1</td><td>10,000</td></tr>
                <tr><td>Q2</td><td>15,000</td></tr>
            </table>
        </body>
        </html>
        """
        html_file = tmp_path / "test.html"
        html_file.write_bytes(html_content)

        stage = IngestionStage()
        config = PipelineConfig()
        context = PipelineContext(
            config=config,
            html_path=html_file,
            filing_id=1,
        )

        result = stage.process(context)

        assert result.success is True
        # Find table segments
        table_segments = [s for s in context.segments if s.segment_type.value == "table"]
        assert len(table_segments) == 1

        table_seg = table_segments[0]
        # Should have markers in text
        assert "[ROW]" in table_seg.text
        assert "[CELL]" in table_seg.text
        # Check specific content
        assert "Period [CELL] Customers" in table_seg.text
        assert "Q1 [CELL] 10,000" in table_seg.text
        assert "Q2 [CELL] 15,000" in table_seg.text

    def test_nested_table_markers(self, tmp_path: Path) -> None:
        """Nested tables should still get markers (outer table perspective)."""
        html_content = b"""
        <html>
        <body>
            <table>
                <tr>
                    <td>Outer A</td>
                    <td>
                        <table>
                            <tr><td>Inner 1</td><td>Inner 2</td></tr>
                        </table>
                    </td>
                    <td>Outer B</td>
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

        table = tree.xpath("//table")[0]
        result = stage._extract_table_text_with_markers(table)

        # Outer table should have markers for its cells
        assert "Outer A" in result
        assert "Outer B" in result
        # Nested table content appears as part of middle cell
        assert "Inner 1" in result
        assert "Inner 2" in result
        # Should have [CELL] markers from outer table
        assert "[CELL]" in result

    def test_empty_table_returns_empty_string(self, tmp_path: Path) -> None:
        """Completely empty table should return empty string."""
        html_content = b"""
        <html>
        <body>
            <table>
                <tr><td></td><td></td></tr>
                <tr><td>  </td><td>  </td></tr>
            </table>
        </body>
        </html>
        """
        html_file = tmp_path / "test.html"
        html_file.write_bytes(html_content)

        stage = IngestionStage()
        tree = stage._parse_html(html_file)
        assert tree is not None

        table = tree.xpath("//table")[0]
        result = stage._extract_table_text_with_markers(table)

        assert result == ""

    def test_non_table_element_falls_back_to_normalization(self, tmp_path: Path) -> None:
        """Non-table element should fall back to standard text normalization."""
        html_content = b"""
        <html>
        <body>
            <p>This is a paragraph, not a table.</p>
        </body>
        </html>
        """
        html_file = tmp_path / "test.html"
        html_file.write_bytes(html_content)

        stage = IngestionStage()
        tree = stage._parse_html(html_file)
        assert tree is not None

        para = tree.xpath("//p")[0]
        result = stage._extract_table_text_with_markers(para)

        # Should use standard normalization (no markers)
        assert result == "This is a paragraph, not a table."
        assert "[CELL]" not in result
        assert "[ROW]" not in result


class TestDefinitionMethodologyDetection:
    """Test definition and methodology block detection (AC-8)."""

    def test_detect_definition_pattern_we_define(self, tmp_path: Path) -> None:
        """Test detection of 'we define' pattern."""
        html_content = b"""
        <html>
        <body>
            <p>We define active customers as customers who have logged in within the last 30 days.</p>
        </body>
        </html>
        """
        html_file = tmp_path / "test.html"
        html_file.write_bytes(html_content)

        stage = IngestionStage()
        context = PipelineContext(
            config=PipelineConfig(),
            html_path=html_file,
            filing_id=12345,
        )

        result = stage.process(context)
        assert result.success
        assert len(context.segments) > 0

        # Find the segment with definition text
        definition_segment = next(
            (s for s in context.segments if "We define active customers" in s.text),
            None,
        )
        assert definition_segment is not None
        assert definition_segment.segment_type.value == "definition"

    def test_detect_definition_pattern_defined_as(self, tmp_path: Path) -> None:
        """Test detection of 'defined as' pattern."""
        html_content = b"""
        <html>
        <body>
            <p>Retention rate is defined as the percentage of customers who continue their subscription.</p>
        </body>
        </html>
        """
        html_file = tmp_path / "test.html"
        html_file.write_bytes(html_content)

        stage = IngestionStage()
        context = PipelineContext(
            config=PipelineConfig(),
            html_path=html_file,
            filing_id=12345,
        )

        result = stage.process(context)
        assert result.success

        definition_segment = next(
            (s for s in context.segments if "Retention rate" in s.text),
            None,
        )
        assert definition_segment is not None
        assert definition_segment.segment_type.value == "definition"

    def test_detect_methodology_pattern_calculated_as(self, tmp_path: Path) -> None:
        """Test detection of 'calculated as' pattern."""
        html_content = b"""
        <html>
        <body>
            <p>Net retention rate is calculated as the sum of beginning ARR plus expansion ARR minus churn ARR divided by beginning ARR.</p>
        </body>
        </html>
        """
        html_file = tmp_path / "test.html"
        html_file.write_bytes(html_content)

        stage = IngestionStage()
        context = PipelineContext(
            config=PipelineConfig(),
            html_path=html_file,
            filing_id=12345,
        )

        result = stage.process(context)
        assert result.success

        methodology_segment = next(
            (s for s in context.segments if "calculated as" in s.text),
            None,
        )
        assert methodology_segment is not None
        assert methodology_segment.segment_type.value == "methodology"

    def test_detect_methodology_pattern_formula(self, tmp_path: Path) -> None:
        """Test detection of 'formula' pattern."""
        html_content = b"""
        <html>
        <body>
            <p>The formula for lifetime value is average revenue per user multiplied by customer lifetime in months.</p>
        </body>
        </html>
        """
        html_file = tmp_path / "test.html"
        html_file.write_bytes(html_content)

        stage = IngestionStage()
        context = PipelineContext(
            config=PipelineConfig(),
            html_path=html_file,
            filing_id=12345,
        )

        result = stage.process(context)
        assert result.success

        methodology_segment = next(
            (s for s in context.segments if "formula" in s.text),
            None,
        )
        assert methodology_segment is not None
        assert methodology_segment.segment_type.value == "methodology"

    def test_regular_paragraph_not_misclassified(self, tmp_path: Path) -> None:
        """Test that regular paragraphs remain classified as PARAGRAPH."""
        html_content = b"""
        <html>
        <body>
            <p>Our business model focuses on providing software as a service to enterprises worldwide.</p>
        </body>
        </html>
        """
        html_file = tmp_path / "test.html"
        html_file.write_bytes(html_content)

        stage = IngestionStage()
        context = PipelineContext(
            config=PipelineConfig(),
            html_path=html_file,
            filing_id=12345,
        )

        result = stage.process(context)
        assert result.success

        paragraph_segment = next(
            (s for s in context.segments if "business model" in s.text),
            None,
        )
        assert paragraph_segment is not None
        assert paragraph_segment.segment_type.value == "paragraph"

    def test_multiple_definition_patterns_in_document(self, tmp_path: Path) -> None:
        """Test document with multiple definition blocks."""
        html_content = b"""
        <html>
        <body>
            <p>We define active users as users who have logged in within the past 30 days.</p>
            <p>Our products are sold globally to enterprise customers in the technology sector.</p>
            <p>Dollar-based net retention rate is calculated as the ending ARR divided by beginning ARR for the same cohort.</p>
            <p>Paid customers refers to organizations that have an active paid subscription as of the period end.</p>
        </body>
        </html>
        """
        html_file = tmp_path / "test.html"
        html_file.write_bytes(html_content)

        stage = IngestionStage()
        context = PipelineContext(
            config=PipelineConfig(),
            html_path=html_file,
            filing_id=12345,
        )

        result = stage.process(context)
        assert result.success
        assert len(context.segments) == 4

        # Count segment types
        definition_count = sum(1 for s in context.segments if s.segment_type.value == "definition")
        methodology_count = sum(1 for s in context.segments if s.segment_type.value == "methodology")
        paragraph_count = sum(1 for s in context.segments if s.segment_type.value == "paragraph")

        assert definition_count == 2  # "We define" and "refers to"
        assert methodology_count == 1  # "calculated as"
        assert paragraph_count == 1  # Regular business description

    def test_case_insensitive_matching(self, tmp_path: Path) -> None:
        """Test that pattern matching is case-insensitive."""
        html_content = b"""
        <html>
        <body>
            <p>WE DEFINE active customers AS customers with recent activity.</p>
            <p>The metric is CALCULATED AS revenue divided by customer count.</p>
        </body>
        </html>
        """
        html_file = tmp_path / "test.html"
        html_file.write_bytes(html_content)

        stage = IngestionStage()
        context = PipelineContext(
            config=PipelineConfig(),
            html_path=html_file,
            filing_id=12345,
        )

        result = stage.process(context)
        assert result.success

        # Both should be detected despite uppercase
        definition_segment = next(
            (s for s in context.segments if "WE DEFINE" in s.text),
            None,
        )
        assert definition_segment is not None
        assert definition_segment.segment_type.value == "definition"

        methodology_segment = next(
            (s for s in context.segments if "CALCULATED AS" in s.text),
            None,
        )
        assert methodology_segment is not None
        assert methodology_segment.segment_type.value == "methodology"

    def test_definition_in_blockquote(self, tmp_path: Path) -> None:
        """Test definition detection in blockquote element."""
        html_content = b"""
        <html>
        <body>
            <blockquote>Annual Recurring Revenue means the annualized value of all active subscriptions as of the measurement date.</blockquote>
        </body>
        </html>
        """
        html_file = tmp_path / "test.html"
        html_file.write_bytes(html_content)

        stage = IngestionStage()
        context = PipelineContext(
            config=PipelineConfig(),
            html_path=html_file,
            filing_id=12345,
        )

        result = stage.process(context)
        assert result.success

        definition_segment = next(
            (s for s in context.segments if "Annual Recurring Revenue" in s.text),
            None,
        )
        assert definition_segment is not None
        assert definition_segment.segment_type.value == "definition"

    def test_empty_text_does_not_crash(self, tmp_path: Path) -> None:
        """Test that empty or whitespace-only text is handled gracefully."""
        html_content = b"""
        <html>
        <body>
            <p></p>
            <p>   </p>
            <div></div>
        </body>
        </html>
        """
        html_file = tmp_path / "test.html"
        html_file.write_bytes(html_content)

        stage = IngestionStage()
        context = PipelineContext(
            config=PipelineConfig(),
            html_path=html_file,
            filing_id=12345,
        )

        result = stage.process(context)
        assert result.success
        # Empty segments should be filtered by min_length constraint
        assert len(context.segments) == 0


class TestImageAssetExtraction:
    """Test ImageAsset extraction (AC-9)."""

    def test_extract_basic_image(self, tmp_path: Path) -> None:
        """Test extracting a basic image with nearby text."""
        html_content = b"""
        <html>
        <body>
            <p>This chart shows customer growth over time.</p>
            <img src="customer_chart.png" width="600" height="400" />
            <p>As shown above, we have strong retention metrics.</p>
        </body>
        </html>
        """
        html_file = tmp_path / "test.html"
        html_file.write_bytes(html_content)

        stage = IngestionStage()
        tree = stage._parse_html(html_file)
        assets = stage._extract_image_assets(tree, 12345)

        assert len(assets) == 1
        asset = assets[0]
        assert asset.filename == "customer_chart.png"
        assert asset.width == 600
        assert asset.height == 400
        assert "customer" in asset.nearby_text.lower()
        assert "chart" in asset.nearby_text.lower()
        assert asset.relevance_score > 0.0

    def test_filter_decorative_images(self, tmp_path: Path) -> None:
        """Test filtering decorative images (logo, icon, etc.)."""
        html_content = b"""
        <html>
        <body>
            <img src="logo.png" width="100" height="50" />
            <img src="icon_bullet.png" width="16" height="16" />
            <img src="chart_data.png" width="800" height="600" />
            <img src="header_banner.png" width="1200" height="80" />
        </body>
        </html>
        """
        html_file = tmp_path / "test.html"
        html_file.write_bytes(html_content)

        stage = IngestionStage()
        tree = stage._parse_html(html_file)
        assets = stage._extract_image_assets(tree, 12345)

        # Should only extract chart_data.png (others filtered by decorative patterns or size)
        assert len(assets) == 1
        assert "chart_data.png" in assets[0].filename

    def test_filter_small_images(self, tmp_path: Path) -> None:
        """Test filtering images below minimum size threshold."""
        html_content = b"""
        <html>
        <body>
            <img src="small.png" width="50" height="50" />
            <img src="large.png" width="800" height="600" />
        </body>
        </html>
        """
        html_file = tmp_path / "test.html"
        html_file.write_bytes(html_content)

        stage = IngestionStage()
        tree = stage._parse_html(html_file)
        assets = stage._extract_image_assets(tree, 12345)

        # Should only extract large.png
        assert len(assets) == 1
        assert assets[0].filename == "large.png"

    def test_extract_caption_from_figure(self, tmp_path: Path) -> None:
        """Test extracting caption from figure element."""
        html_content = b"""
        <html>
        <body>
            <figure>
                <img src="cohort_analysis.png" width="700" height="500" />
                <figcaption>Figure 1: Annual cohort retention analysis showing strong performance</figcaption>
            </figure>
        </body>
        </html>
        """
        html_file = tmp_path / "test.html"
        html_file.write_bytes(html_content)

        stage = IngestionStage()
        tree = stage._parse_html(html_file)
        assets = stage._extract_image_assets(tree, 12345)

        assert len(assets) == 1
        asset = assets[0]
        assert "cohort" in asset.nearby_text.lower()
        assert "retention" in asset.nearby_text.lower()
        assert "Figure 1" in asset.nearby_text

    def test_compute_relevance_score_high(self, tmp_path: Path) -> None:
        """Test high relevance score for images with metric keywords."""
        html_content = b"""
        <html>
        <body>
            <p>The following chart illustrates our cohort retention rates and customer growth metrics.</p>
            <img src="retention_chart.png" width="800" height="600" />
        </body>
        </html>
        """
        html_file = tmp_path / "test.html"
        html_file.write_bytes(html_content)

        stage = IngestionStage()
        tree = stage._parse_html(html_file)
        assets = stage._extract_image_assets(tree, 12345)

        assert len(assets) == 1
        asset = assets[0]
        # Should have high score due to: cohort, retention, chart, customer keywords
        assert asset.relevance_score >= 0.5

    def test_compute_relevance_score_low(self, tmp_path: Path) -> None:
        """Test low relevance score for images without metric keywords."""
        html_content = b"""
        <html>
        <body>
            <p>This is a generic company photo.</p>
            <img src="office_photo.png" width="800" height="600" />
        </body>
        </html>
        """
        html_file = tmp_path / "test.html"
        html_file.write_bytes(html_content)

        stage = IngestionStage()
        tree = stage._parse_html(html_file)
        assets = stage._extract_image_assets(tree, 12345)

        assert len(assets) == 1
        asset = assets[0]
        # Should have low score (only base score for having text)
        assert asset.relevance_score < 0.3

    def test_skip_images_without_src(self, tmp_path: Path) -> None:
        """Test skipping images without src attribute."""
        html_content = b"""
        <html>
        <body>
            <img width="800" height="600" />
            <img src="" width="800" height="600" />
            <img src="valid.png" width="800" height="600" />
        </body>
        </html>
        """
        html_file = tmp_path / "test.html"
        html_file.write_bytes(html_content)

        stage = IngestionStage()
        tree = stage._parse_html(html_file)
        assets = stage._extract_image_assets(tree, 12345)

        # Should only extract valid.png
        assert len(assets) == 1
        assert assets[0].filename == "valid.png"

    def test_generate_xpath_for_images(self, tmp_path: Path) -> None:
        """Test XPath generation for image elements."""
        html_content = b"""
        <html>
        <body>
            <div>
                <p>First paragraph</p>
                <img src="chart1.png" width="600" height="400" />
            </div>
            <div>
                <img src="chart2.png" width="700" height="500" />
            </div>
        </body>
        </html>
        """
        html_file = tmp_path / "test.html"
        html_file.write_bytes(html_content)

        stage = IngestionStage()
        tree = stage._parse_html(html_file)
        assets = stage._extract_image_assets(tree, 12345)

        assert len(assets) == 2
        # Both images should have unique XPath locators
        assert assets[0].dom_locator != assets[1].dom_locator
        # XPaths should be absolute and contain 'img'
        for asset in assets:
            assert asset.dom_locator.startswith("/")
            assert "img" in asset.dom_locator

    def test_integration_with_process_method(self, tmp_path: Path) -> None:
        """Test that process() method calls image extraction and stores in context."""
        html_content = b"""
        <html>
        <body>
            <p>This is a long enough paragraph to meet the minimum character requirement for extraction as a segment.</p>
            <img src="cohort_chart.png" width="800" height="600" />
            <p>Another paragraph describing our retention metrics in detail with sufficient length to be extracted.</p>
        </body>
        </html>
        """
        html_file = tmp_path / "test.html"
        html_file.write_bytes(html_content)

        stage = IngestionStage()
        context = PipelineContext(
            config=PipelineConfig(),
            html_path=html_file,
            filing_id=12345,
        )

        result = stage.process(context)

        assert result.success
        # Should have extracted paragraphs
        assert len(context.segments) > 0
        # Should have extracted image
        assert len(context.images) == 1
        assert context.images[0].filename == "cohort_chart.png"
        # Metadata should reflect image count
        assert result.metadata["image_count"] == 1
