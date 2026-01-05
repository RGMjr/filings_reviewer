"""
Tests for structure_parser.py - DOM structure preservation and position mapping.

Coverage target: ≥90%

Test categories:
1. Basic parsing (simple HTML, paragraphs, empty HTML)
2. Table parsing (single/multi-row, headers, empty cells)
3. Position mapping (element lookup, row/cell checks)
4. Edge cases (colspan, nested elements, large tables)
"""


from src.extraction.structure_parser import RowSpan, StructureParser, TextSpan


class TestBasicParsing:
    """Tests for parsing non-table HTML content."""

    def test_simple_paragraph(self):
        """Parse simple paragraph HTML."""
        html = "<p>This is a test paragraph.</p>"
        parser = StructureParser(html)

        text = parser.get_text()
        assert "This is a test paragraph." in text
        assert parser.is_table() is False

    def test_multiple_paragraphs(self):
        """Parse multiple paragraphs."""
        html = """
        <p>First paragraph.</p>
        <p>Second paragraph.</p>
        """
        parser = StructureParser(html)

        text = parser.get_text()
        assert "First paragraph." in text
        assert "Second paragraph." in text
        assert parser.is_table() is False

    def test_nested_elements(self):
        """Parse nested elements (span inside p)."""
        html = "<p>Text with <span>nested span</span> inside.</p>"
        parser = StructureParser(html)

        text = parser.get_text()
        assert "nested span" in text
        # Should extract text from nested structure
        assert "Text with" in text

    def test_empty_html(self):
        """Handle empty HTML gracefully."""
        html = ""
        parser = StructureParser(html)

        text = parser.get_text()
        assert text == ""
        assert parser.is_table() is False
        assert parser.get_row_boundaries() == []
        assert parser.get_cell_boundaries() == []

    def test_plain_text_no_html(self):
        """Handle plain text with no HTML tags."""
        html = "Just plain text"
        parser = StructureParser(html)

        text = parser.get_text()
        assert "Just plain text" in text
        assert parser.is_table() is False

    def test_whitespace_normalization(self):
        """Normalize excessive whitespace."""
        html = "<p>Text   with    multiple     spaces</p>"
        parser = StructureParser(html)

        text = parser.get_text()
        # Should collapse to single spaces
        assert "Text with multiple spaces" in text


class TestTableParsing:
    """Tests for parsing table HTML."""

    def test_single_row_table(self):
        """Parse simple single-row table."""
        html = """
        <table>
            <tr>
                <td>Cell 1</td>
                <td>Cell 2</td>
            </tr>
        </table>
        """
        parser = StructureParser(html)

        text = parser.get_text()
        assert "Cell 1" in text
        assert "Cell 2" in text
        assert "[CELL]" in text
        assert "[ROW]" in text
        assert parser.is_table() is True

    def test_multi_row_table(self):
        """Parse multi-row table."""
        html = """
        <table>
            <tr><td>Row 1 Col 1</td><td>Row 1 Col 2</td></tr>
            <tr><td>Row 2 Col 1</td><td>Row 2 Col 2</td></tr>
        </table>
        """
        parser = StructureParser(html)

        text = parser.get_text()
        assert "Row 1 Col 1" in text
        assert "Row 2 Col 2" in text

        # Should have 2 rows
        row_boundaries = parser.get_row_boundaries()
        assert len(row_boundaries) == 2

    def test_table_with_headers(self):
        """Parse table with header cells (th)."""
        html = """
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
        """
        parser = StructureParser(html)

        text = parser.get_text()
        assert "Header 1" in text
        assert "Data 1" in text

        # Check element types
        pos_header = text.find("Header 1")
        elem = parser.get_element_at_position(pos_header)
        assert elem is not None
        assert elem.name == "th"

        pos_data = text.find("Data 1")
        elem_data = parser.get_element_at_position(pos_data)
        assert elem_data is not None
        assert elem_data.name == "td"

    def test_mixed_th_td_cells(self):
        """Parse table with mixed th and td cells in same row."""
        html = """
        <table>
            <tr>
                <th>Label</th>
                <td>Value</td>
            </tr>
        </table>
        """
        parser = StructureParser(html)

        text = parser.get_text()
        assert "Label" in text
        assert "Value" in text

        # Should have one row with two cells
        row_boundaries = parser.get_row_boundaries()
        assert len(row_boundaries) == 1

        cell_boundaries = parser.get_cell_boundaries()
        assert len(cell_boundaries) == 2

    def test_empty_cells(self):
        """Handle empty table cells."""
        html = """
        <table>
            <tr>
                <td>Data</td>
                <td></td>
                <td>More data</td>
            </tr>
        </table>
        """
        parser = StructureParser(html)

        text = parser.get_text()
        assert "Data" in text
        assert "More data" in text

    def test_cells_with_multiple_elements(self):
        """Parse cells containing multiple nested elements."""
        html = """
        <table>
            <tr>
                <td><b>Bold</b> and <i>italic</i></td>
                <td>Plain</td>
            </tr>
        </table>
        """
        parser = StructureParser(html)

        text = parser.get_text()
        assert "Bold" in text
        assert "italic" in text
        assert "Plain" in text


class TestPositionMapping:
    """Tests for position-to-element mapping."""

    def test_get_element_at_position_found(self):
        """Get element at a valid position."""
        html = """
        <table>
            <tr><td>Revenue</td><td>100</td></tr>
        </table>
        """
        parser = StructureParser(html)

        text = parser.get_text()
        pos = text.find("Revenue")

        elem = parser.get_element_at_position(pos)
        assert elem is not None
        assert elem.name == "td"
        assert "Revenue" in elem.get_text()

    def test_get_element_at_position_not_found(self):
        """Return None for position outside any span."""
        html = "<table><tr><td>Test</td></tr></table>"
        parser = StructureParser(html)

        text = parser.get_text()
        # Position beyond text length
        elem = parser.get_element_at_position(len(text) + 100)
        assert elem is None

    def test_are_in_same_row_true(self):
        """Two positions in same row return True."""
        html = """
        <table>
            <tr><td>Revenue</td><td>100</td></tr>
            <tr><td>Cost</td><td>50</td></tr>
        </table>
        """
        parser = StructureParser(html)

        text = parser.get_text()
        pos_revenue = text.find("Revenue")
        pos_100 = text.find("100")

        assert parser.are_in_same_row(pos_revenue, pos_100) is True

    def test_are_in_same_row_false(self):
        """Two positions in different rows return False."""
        html = """
        <table>
            <tr><td>Revenue</td><td>100</td></tr>
            <tr><td>Cost</td><td>50</td></tr>
        </table>
        """
        parser = StructureParser(html)

        text = parser.get_text()
        pos_revenue = text.find("Revenue")
        pos_cost = text.find("Cost")

        assert parser.are_in_same_row(pos_revenue, pos_cost) is False

    def test_are_in_same_row_no_table(self):
        """Return False when no table structure exists."""
        html = "<p>Revenue 100 Cost 50</p>"
        parser = StructureParser(html)

        text = parser.get_text()
        pos_revenue = text.find("Revenue")
        pos_100 = text.find("100")

        # No table structure, so cannot be in same row
        assert parser.are_in_same_row(pos_revenue, pos_100) is False

    def test_are_in_same_cell_true(self):
        """Two positions in same cell return True."""
        html = """
        <table>
            <tr><td>Revenue increased</td><td>100</td></tr>
        </table>
        """
        parser = StructureParser(html)

        text = parser.get_text()
        pos_revenue = text.find("Revenue")
        pos_increased = text.find("increased")

        assert parser.are_in_same_cell(pos_revenue, pos_increased) is True

    def test_are_in_same_cell_false(self):
        """Two positions in different cells return False."""
        html = """
        <table>
            <tr><td>Revenue</td><td>100</td></tr>
        </table>
        """
        parser = StructureParser(html)

        text = parser.get_text()
        pos_revenue = text.find("Revenue")
        pos_100 = text.find("100")

        assert parser.are_in_same_cell(pos_revenue, pos_100) is False

    def test_positions_at_boundaries(self):
        """Handle positions at cell/row boundaries."""
        html = """
        <table>
            <tr><td>A</td><td>B</td></tr>
        </table>
        """
        parser = StructureParser(html)

        text = parser.get_text()
        # Position at start of first cell
        assert parser.get_element_at_position(0) is not None

        # Position at very end of text
        last_pos = len(text) - 1
        # May or may not return element depending on boundary logic
        # Just verify it doesn't crash
        parser.get_element_at_position(last_pos)


class TestEdgeCases:
    """Tests for edge cases and special scenarios."""

    def test_colspan_handling(self):
        """Handle cells with colspan attribute (basic support)."""
        html = """
        <table>
            <tr>
                <td colspan="2">Wide cell</td>
            </tr>
            <tr>
                <td>Normal 1</td>
                <td>Normal 2</td>
            </tr>
        </table>
        """
        parser = StructureParser(html)

        text = parser.get_text()
        assert "Wide cell" in text
        assert "Normal 1" in text

        # Should have 2 rows
        assert len(parser.get_row_boundaries()) == 2

    def test_rowspan_handling(self):
        """Handle cells with rowspan attribute (basic support)."""
        html = """
        <table>
            <tr>
                <td rowspan="2">Tall cell</td>
                <td>Row 1</td>
            </tr>
            <tr>
                <td>Row 2</td>
            </tr>
        </table>
        """
        parser = StructureParser(html)

        text = parser.get_text()
        assert "Tall cell" in text
        assert "Row 1" in text
        assert "Row 2" in text

    def test_deeply_nested_elements(self):
        """Parse deeply nested HTML structure."""
        html = """
        <div>
            <div>
                <div>
                    <p>Deeply nested text</p>
                </div>
            </div>
        </div>
        """
        parser = StructureParser(html)

        text = parser.get_text()
        assert "Deeply nested text" in text

    def test_very_large_table(self):
        """Handle large table (100+ rows) efficiently."""
        # Generate 100-row table
        rows = []
        for i in range(100):
            rows.append(f"<tr><td>Row {i}</td><td>{i * 10}</td></tr>")

        html = f"<table>{''.join(rows)}</table>"
        parser = StructureParser(html)

        text = parser.get_text()
        assert "Row 0" in text
        assert "Row 99" in text

        # Should have 100 rows
        assert len(parser.get_row_boundaries()) == 100

    def test_whitespace_only_cells(self):
        """Handle cells containing only whitespace."""
        html = """
        <table>
            <tr>
                <td>Data</td>
                <td>   </td>
                <td>More</td>
            </tr>
        </table>
        """
        parser = StructureParser(html)

        text = parser.get_text()
        assert "Data" in text
        assert "More" in text

    def test_malformed_html_unclosed_tags(self):
        """BeautifulSoup handles malformed HTML gracefully."""
        html = "<table><tr><td>Unclosed cell<tr><td>Another row</td></tr>"
        parser = StructureParser(html)

        text = parser.get_text()
        # BeautifulSoup should auto-close tags
        assert "Unclosed cell" in text
        assert "Another row" in text

    def test_table_with_caption(self):
        """Handle table with caption element."""
        html = """
        <table>
            <caption>Table Caption</caption>
            <tr><td>Data 1</td><td>Data 2</td></tr>
        </table>
        """
        parser = StructureParser(html)

        text = parser.get_text()
        # Caption may or may not be included depending on implementation
        assert "Data 1" in text
        assert "Data 2" in text


class TestRowAndCellBoundaries:
    """Tests for row and cell boundary extraction."""

    def test_get_row_boundaries_multiple_rows(self):
        """Get boundaries for multi-row table."""
        html = """
        <table>
            <tr><td>R1C1</td><td>R1C2</td></tr>
            <tr><td>R2C1</td><td>R2C2</td></tr>
            <tr><td>R3C1</td><td>R3C2</td></tr>
        </table>
        """
        parser = StructureParser(html)

        boundaries = parser.get_row_boundaries()
        assert len(boundaries) == 3

        # Each boundary should be (start, end) tuple
        for start, end in boundaries:
            assert isinstance(start, int)
            assert isinstance(end, int)
            assert start < end

    def test_get_cell_boundaries_multiple_cells(self):
        """Get boundaries for all cells."""
        html = """
        <table>
            <tr><td>A</td><td>B</td><td>C</td></tr>
            <tr><td>D</td><td>E</td><td>F</td></tr>
        </table>
        """
        parser = StructureParser(html)

        boundaries = parser.get_cell_boundaries()
        # 2 rows × 3 cells = 6 cells
        assert len(boundaries) == 6

    def test_get_row_at_position(self):
        """Get row object at specific position."""
        html = """
        <table>
            <tr><td>Row 1</td></tr>
            <tr><td>Row 2</td></tr>
        </table>
        """
        parser = StructureParser(html)

        text = parser.get_text()
        pos_row1 = text.find("Row 1")

        row = parser.get_row_at_position(pos_row1)
        assert row is not None
        assert len(row.cells) == 1
        assert "Row 1" in row.cells[0].text

    def test_get_row_at_position_not_found(self):
        """Return None for position outside any row."""
        html = "<table><tr><td>Test</td></tr></table>"
        parser = StructureParser(html)

        text = parser.get_text()
        row = parser.get_row_at_position(len(text) + 100)
        assert row is None


class TestDataClasses:
    """Tests for TextSpan and RowSpan dataclasses."""

    def test_text_span_creation(self):
        """Create TextSpan with all attributes."""
        span = TextSpan(
            text="Sample text",
            text_start=0,
            text_end=11,
            dom_element=None,
            element_type="td",
        )

        assert span.text == "Sample text"
        assert span.text_start == 0
        assert span.text_end == 11
        assert span.element_type == "td"

    def test_text_span_defaults(self):
        """TextSpan uses default values for optional fields."""
        span = TextSpan(text="Text", text_start=0, text_end=4)

        assert span.dom_element is None
        assert span.element_type == "text"

    def test_row_span_creation(self):
        """Create RowSpan with cells."""
        cell1 = TextSpan(text="Cell 1", text_start=0, text_end=6)
        cell2 = TextSpan(text="Cell 2", text_start=7, text_end=13)

        row = RowSpan(cells=[cell1, cell2], row_start=0, row_end=13)

        assert len(row.cells) == 2
        assert row.row_start == 0
        assert row.row_end == 13

    def test_row_span_defaults(self):
        """RowSpan uses default values."""
        row = RowSpan()

        assert row.cells == []
        assert row.row_start == 0
        assert row.row_end == 0


class TestRealWorldScenarios:
    """Tests with realistic filing data scenarios."""

    def test_financial_table_structure(self):
        """Parse realistic financial table structure."""
        html = """
        <table>
            <tr>
                <th>Metric</th>
                <th>2021</th>
                <th>2022</th>
            </tr>
            <tr>
                <td>Revenue</td>
                <td>$100,000</td>
                <td>$150,000</td>
            </tr>
            <tr>
                <td>Gross profit</td>
                <td>$60,000</td>
                <td>$90,000</td>
            </tr>
        </table>
        """
        parser = StructureParser(html)

        text = parser.get_text()

        # Check structure preservation
        pos_revenue = text.find("Revenue")
        pos_100k = text.find("100,000")
        pos_gross = text.find("Gross profit")
        pos_60k = text.find("60,000")

        # Revenue and 100,000 should be in same row
        assert parser.are_in_same_row(pos_revenue, pos_100k)

        # Revenue and Gross profit should NOT be in same row
        assert not parser.are_in_same_row(pos_revenue, pos_gross)

        # Gross profit and 60,000 should be in same row
        assert parser.are_in_same_row(pos_gross, pos_60k)

        # 100,000 and 60,000 should NOT be in same row
        assert not parser.are_in_same_row(pos_100k, pos_60k)

    def test_mixed_content_table_and_paragraphs(self):
        """Parse document with both tables and paragraphs."""
        html = """
        <p>This is introductory text about metrics.</p>
        <table>
            <tr><td>DAU</td><td>1,000,000</td></tr>
            <tr><td>MAU</td><td>5,000,000</td></tr>
        </table>
        <p>Additional commentary after the table.</p>
        """
        parser = StructureParser(html)

        text = parser.get_text()

        # Should find table structure
        assert parser.is_table()

        # Check row separation in table
        pos_dau = text.find("DAU")
        pos_mau = text.find("MAU")
        assert not parser.are_in_same_row(pos_dau, pos_mau)
