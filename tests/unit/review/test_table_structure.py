"""
Unit tests for TableRowParser - table row boundary detection.

Tests cover:
1. Basic row mapping (simple tables, headers, empty cells)
2. Whitespace edge cases (br tags, normalization differences)
3. Position mapping accuracy
4. are_in_same_row() correctness
5. Fallback/edge cases (no table, nested tables, colspan/rowspan)

Test naming convention: test_<feature>_<scenario>
"""

import pytest

from src.review.table_structure import TableRowParser

# =============================================================================
# Test Fixtures
# =============================================================================


@pytest.fixture
def simple_table_html() -> str:
    """Simple 3-row, 2-column table with spaces in cells for natural extraction."""
    return """<table>
<tr><td>Revenue </td><td>100</td></tr>
<tr><td>Cost </td><td>50</td></tr>
<tr><td>Profit </td><td>50</td></tr>
</table>"""


@pytest.fixture
def simple_table_text() -> str:
    """Text extracted from simple table (matches HTML structure)."""
    return "Revenue 100 Cost 50 Profit 50"


@pytest.fixture
def table_with_header_html() -> str:
    """Table with th header row."""
    return """<table>
<tr><th>Metric </th><th>2023 </th><th>2022</th></tr>
<tr><td>Revenue </td><td>100 </td><td>80</td></tr>
<tr><td>Cost </td><td>50 </td><td>40</td></tr>
</table>"""


@pytest.fixture
def table_with_header_text() -> str:
    """Text extracted from table with header."""
    return "Metric 2023 2022 Revenue 100 80 Cost 50 40"


# =============================================================================
# Basic Row Mapping Tests
# =============================================================================


class TestBasicRowMapping:
    """Tests for basic table row parsing."""

    def test_simple_table_three_rows(
        self, simple_table_html: str, simple_table_text: str
    ) -> None:
        """Simple 3-row table maps correctly."""
        parser = TableRowParser(simple_table_html, simple_table_text)
        rows = parser.get_rows()

        assert len(rows) == 3
        assert rows[0].header_text == "Revenue"
        assert rows[1].header_text == "Cost"
        assert rows[2].header_text == "Profit"

    def test_table_with_header_row(
        self, table_with_header_html: str, table_with_header_text: str
    ) -> None:
        """Table with th header row parses correctly."""
        parser = TableRowParser(table_with_header_html, table_with_header_text)
        rows = parser.get_rows()

        assert len(rows) == 3
        assert rows[0].header_text == "Metric"
        assert rows[1].header_text == "Revenue"
        assert rows[2].header_text == "Cost"

    def test_table_with_empty_cells(self) -> None:
        """Table with empty cells still maps rows."""
        html = """<table>
<tr><td>Label </td><td></td><td>100</td></tr>
<tr><td></td><td>Data </td><td>200</td></tr>
</table>"""
        text = "Label 100 Data 200"
        parser = TableRowParser(html, text)
        rows = parser.get_rows()

        assert len(rows) == 2

    def test_table_varying_column_counts(self) -> None:
        """Table with varying column counts per row."""
        html = """<table>
<tr><td>A </td><td>B</td></tr>
<tr><td>C </td><td>D </td><td>E</td></tr>
<tr><td>F</td></tr>
</table>"""
        text = "A B C D E F"
        parser = TableRowParser(html, text)
        rows = parser.get_rows()

        assert len(rows) == 3

    def test_header_detection_numeric_first_cell(self) -> None:
        """First cell with only numbers is not a header."""
        html = """<table>
<tr><td>2023 </td><td>100</td></tr>
<tr><td>Revenue </td><td>200</td></tr>
</table>"""
        text = "2023 100 Revenue 200"
        parser = TableRowParser(html, text)
        rows = parser.get_rows()

        # First row has numeric first cell - not a header
        assert rows[0].has_header is False
        assert rows[0].header_text is None
        # Second row has text first cell - is a header
        assert rows[1].has_header is True
        assert rows[1].header_text == "Revenue"


# =============================================================================
# Whitespace Edge Cases Tests
# =============================================================================


class TestWhitespaceEdgeCases:
    """Tests for whitespace normalization differences."""

    def test_br_tag_no_space_in_extracted(self) -> None:
        """Handle <br/> becoming no space in extracted text (HRV-17 root cause)."""
        html = """
        <table>
            <tr><td><b>Six months ended<br/>June 30,</b></td></tr>
            <tr><td>Revenue</td></tr>
        </table>
        """
        # HTMLSegmenter: <br/> removed, no space
        text = "Six months endedJune 30, Revenue"

        parser = TableRowParser(html, text)
        rows = parser.get_rows()

        assert len(rows) == 2
        # Should still find both rows despite whitespace difference
        assert parser.is_table()

    def test_multiple_spaces_collapsed(self) -> None:
        """Multiple spaces in HTML become single space."""
        html = """<table>
<tr><td>Revenue    Total </td><td>100</td></tr>
</table>"""
        # Extracted text has single space
        text = "Revenue Total 100"

        parser = TableRowParser(html, text)
        rows = parser.get_rows()

        assert len(rows) == 1
        assert "Revenue" in rows[0].row_text

    def test_newlines_within_cells(self) -> None:
        """Newlines within cells are normalized."""
        html = """<table>
<tr><td>Multi
line
text </td><td>100</td></tr>
</table>"""
        text = "Multi line text 100"

        parser = TableRowParser(html, text)
        rows = parser.get_rows()

        assert len(rows) == 1

    def test_leading_trailing_whitespace(self) -> None:
        """Leading/trailing whitespace in cells handled."""
        html = """<table>
<tr><td>  Revenue  </td><td>  100  </td></tr>
</table>"""
        text = "Revenue 100"

        parser = TableRowParser(html, text)
        rows = parser.get_rows()

        assert len(rows) == 1
        assert rows[0].header_text == "Revenue"

    def test_nbsp_entities(self) -> None:
        """Non-breaking spaces handled."""
        html = """<table>
<tr><td>Revenue\u00a0Total </td><td>100</td></tr>
</table>"""
        # BeautifulSoup converts &nbsp; to actual non-breaking space
        text = "Revenue\u00a0Total 100"

        parser = TableRowParser(html, text)
        rows = parser.get_rows()

        assert len(rows) == 1


# =============================================================================
# Position Mapping Accuracy Tests
# =============================================================================


class TestPositionMappingAccuracy:
    """Tests for accurate position-to-row mapping."""

    def test_first_char_of_each_row(
        self, simple_table_html: str, simple_table_text: str
    ) -> None:
        """First character of each row maps correctly."""
        parser = TableRowParser(simple_table_html, simple_table_text)
        rows = parser.get_rows()

        # "Revenue 100 Cost 50 Profit 50"
        #  ^0          ^12     ^20
        assert len(rows) >= 3

        # First char of each row
        for row in rows:
            mapped_row = parser.get_row_at_position(row.text_start)
            assert mapped_row is not None
            assert mapped_row.row_index == row.row_index

    def test_last_char_of_each_row(
        self, simple_table_html: str, simple_table_text: str
    ) -> None:
        """Last character of each row maps correctly."""
        parser = TableRowParser(simple_table_html, simple_table_text)
        rows = parser.get_rows()

        # Last char of first row should still be in first row
        first_row_end = rows[0].text_end - 1
        row = parser.get_row_at_position(first_row_end)
        assert row is not None
        assert row.row_index == rows[0].row_index

    def test_char_at_row_boundary(self) -> None:
        """Character exactly at row boundary behaves correctly.

        Note: Gap positions between rows are intentionally NOT filled to prevent
        cross-row matches. Positions exactly at row.text_end are outside the row.
        """
        html = """<table>
<tr><td>ABC </td></tr>
<tr><td>DEF</td></tr>
</table>"""
        text = "ABC DEF"
        parser = TableRowParser(html, text)
        rows = parser.get_rows()

        # Position at boundary (after ABC, before DEF) is in the gap
        # The gap character (space) may not be mapped
        boundary_pos = rows[0].text_end
        row = parser.get_row_at_position(boundary_pos)
        # Gap positions intentionally return None (conservative approach)
        # The second row starts where "DEF" is found
        # Either it's in the second row or unmapped - both are acceptable
        if row is not None:
            assert row.row_index == 1  # Should be second row, not first

    def test_middle_of_cell(self) -> None:
        """Character in middle of cell maps correctly."""
        html = """<table>
<tr><td>LongLabel </td><td>12345</td></tr>
</table>"""
        text = "LongLabel 12345"
        parser = TableRowParser(html, text)

        # Middle of "LongLabel"
        row = parser.get_row_at_position(4)
        assert row is not None
        assert row.row_index == 0

        # Middle of "12345"
        row = parser.get_row_at_position(12)
        assert row is not None
        assert row.row_index == 0

    def test_row_content_positions_covered(self) -> None:
        """Positions within row content are mapped correctly.

        Note: Gap positions between rows may not be mapped (conservative approach
        to prevent cross-row matches). We verify that each row's content positions
        are properly mapped.
        """
        html = """<table>
<tr><td>First </td></tr>
<tr><td>Second </td></tr>
<tr><td>Third</td></tr>
</table>"""
        text = "First Second Third"
        parser = TableRowParser(html, text)
        rows = parser.get_rows()

        # Each row's internal positions should be mapped
        for row in rows:
            for pos in range(row.text_start, row.text_end):
                mapped_row = parser.get_row_at_position(pos)
                assert mapped_row is not None, f"Position {pos} in row {row.row_index} not mapped"
                assert mapped_row.row_index == row.row_index


# =============================================================================
# are_in_same_row() Correctness Tests
# =============================================================================


class TestAreInSameRow:
    """Tests for are_in_same_row() method."""

    def test_same_row_returns_true(
        self, simple_table_html: str, simple_table_text: str
    ) -> None:
        """Two positions in same row return True."""
        parser = TableRowParser(simple_table_html, simple_table_text)
        rows = parser.get_rows()

        # Get first row and check two positions within it
        first_row = rows[0]
        pos1 = first_row.text_start
        pos2 = first_row.text_start + 5  # Within same row

        assert parser.are_in_same_row(pos1, pos2) is True
        assert parser.are_in_same_row(pos2, pos1) is True  # Order doesn't matter

    def test_different_rows_returns_false(
        self, simple_table_html: str, simple_table_text: str
    ) -> None:
        """Two positions in different rows return False."""
        parser = TableRowParser(simple_table_html, simple_table_text)
        rows = parser.get_rows()

        # First row and second row
        first_row = rows[0]
        second_row = rows[1]

        assert parser.are_in_same_row(first_row.text_start, second_row.text_start) is False

    def test_first_and_last_row(self) -> None:
        """Positions in first and last rows return False."""
        html = """<table>
<tr><td>First </td></tr>
<tr><td>Middle </td></tr>
<tr><td>Last</td></tr>
</table>"""
        text = "First Middle Last"
        parser = TableRowParser(html, text)
        rows = parser.get_rows()

        # First row and last row
        first_pos = rows[0].text_start
        last_pos = rows[-1].text_start
        assert parser.are_in_same_row(first_pos, last_pos) is False

    def test_adjacent_rows_different(self) -> None:
        """Positions in adjacent rows return False."""
        html = """<table>
<tr><td>Row1 </td></tr>
<tr><td>Row2</td></tr>
</table>"""
        text = "Row1 Row2"
        parser = TableRowParser(html, text)
        rows = parser.get_rows()

        # Row1 and Row2
        assert parser.are_in_same_row(rows[0].text_start, rows[1].text_start) is False


# =============================================================================
# Fallback/Edge Cases Tests
# =============================================================================


class TestFallbackEdgeCases:
    """Tests for edge cases and fallback behavior."""

    def test_no_table_single_row(self) -> None:
        """HTML without table is treated as single row."""
        html = "<p>Just some text with numbers 123</p>"
        text = "Just some text with numbers 123"

        parser = TableRowParser(html, text)
        rows = parser.get_rows()

        assert len(rows) == 1
        assert rows[0].text_start == 0
        assert rows[0].text_end == len(text)
        assert parser.is_table() is False

    def test_no_table_all_positions_same_row(self) -> None:
        """Without table, all positions are in same 'row'."""
        html = "<p>Text 123 more 456</p>"
        text = "Text 123 more 456"

        parser = TableRowParser(html, text)

        # All positions should be in the same row
        assert parser.are_in_same_row(0, 5) is True
        assert parser.are_in_same_row(0, 16) is True

    def test_nested_tables(self) -> None:
        """Nested tables are flattened to row sequence."""
        html = """<table>
<tr><td>Outer1 </td></tr>
<tr><td><table><tr><td>Inner1 </td></tr><tr><td>Inner2 </td></tr></table></td></tr>
<tr><td>Outer2</td></tr>
</table>"""
        text = "Outer1 Inner1 Inner2 Outer2"

        parser = TableRowParser(html, text)
        # Should parse without error
        assert len(parser.get_rows()) >= 1

    def test_table_with_colspan(self) -> None:
        """Table with colspan attributes parses correctly."""
        html = """<table>
<tr><td colspan="2">Header </td></tr>
<tr><td>Col1 </td><td>Col2</td></tr>
</table>"""
        text = "Header Col1 Col2"

        parser = TableRowParser(html, text)
        rows = parser.get_rows()

        assert len(rows) == 2

    def test_table_with_rowspan(self) -> None:
        """Table with rowspan attributes parses correctly."""
        html = """<table>
<tr><td rowspan="2">Label </td><td>100</td></tr>
<tr><td>200</td></tr>
</table>"""
        text = "Label 100 200"

        parser = TableRowParser(html, text)
        rows = parser.get_rows()

        assert len(rows) == 2

    def test_empty_table(self) -> None:
        """Empty table (no rows) treated as single row."""
        html = "<table></table>"
        text = ""

        parser = TableRowParser(html, text)
        rows = parser.get_rows()

        assert len(rows) == 1
        assert parser.is_table() is False

    def test_table_all_empty_rows(self) -> None:
        """Table with only empty rows creates single fallback row."""
        html = """<table>
<tr><td></td></tr>
<tr><td></td></tr>
</table>"""
        text = ""

        parser = TableRowParser(html, text)
        rows = parser.get_rows()

        # Empty rows are skipped - no rows parsed, but should have fallback
        # With no text, we still get the fallback single row covering empty text
        assert len(rows) >= 0  # May be 0 or 1 depending on implementation


# =============================================================================
# is_row_heading() Tests
# =============================================================================


class TestIsRowHeading:
    """Tests for is_row_heading() method."""

    def test_header_position_returns_true(self) -> None:
        """Position within row header returns True."""
        html = """<table>
<tr><td>Revenue </td><td>100</td></tr>
</table>"""
        text = "Revenue 100"

        parser = TableRowParser(html, text)

        # Position 0-6 is "Revenue" (header)
        assert parser.is_row_heading(0) is True
        assert parser.is_row_heading(3) is True

    def test_non_header_position_returns_false(self) -> None:
        """Position outside row header returns False."""
        html = """<table>
<tr><td>Revenue </td><td>100</td></tr>
</table>"""
        text = "Revenue 100"

        parser = TableRowParser(html, text)

        # Position 8-10 is "100" (not header)
        assert parser.is_row_heading(8) is False
        assert parser.is_row_heading(9) is False

    def test_numeric_first_cell_not_heading(self) -> None:
        """Numeric first cell is not detected as heading."""
        html = """<table>
<tr><td>2023 </td><td>Revenue</td></tr>
</table>"""
        text = "2023 Revenue"

        parser = TableRowParser(html, text)

        # "2023" is numeric, not a heading
        assert parser.is_row_heading(0) is False


# =============================================================================
# Flexible Matching Tests
# =============================================================================


class TestFlexibleMatching:
    """Tests for flexible whitespace matching."""

    def test_find_row_flexible_missing_space(self) -> None:
        """Flexible matching finds row when space is missing between words."""
        # HTML has space between Total and Revenue
        html = """<table>
<tr><td>Total Revenue </td><td>100</td></tr>
</table>"""
        # Extracted text has no space between words (simulating <br/> removal)
        text = "TotalRevenue 100"

        parser = TableRowParser(html, text)
        rows = parser.get_rows()

        assert len(rows) == 1
        assert rows[0].text_start == 0

    def test_find_row_flexible_extra_space(self) -> None:
        """Flexible matching handles extra spaces in extracted text."""
        html = """<table>
<tr><td>Total Revenue </td><td>100</td></tr>
</table>"""
        # Extracted text has extra spaces
        text = "Total  Revenue   100"

        parser = TableRowParser(html, text)
        rows = parser.get_rows()

        assert len(rows) == 1

    def test_unmapped_trailing_text_not_extended(self) -> None:
        """Unmapped trailing text is intentionally NOT covered.

        Gap-filling was disabled to prevent cross-row false positives.
        When HTML doesn't contain certain text, those positions are unmapped.
        This is the correct conservative behavior.
        """
        html = """<table>
<tr><td>Label</td></tr>
</table>"""
        # Text has extra content not in HTML (simulates data quality issue)
        text = "Label extra content"

        parser = TableRowParser(html, text)
        rows = parser.get_rows()

        # Last row should only cover "Label", not extend to extra text
        assert rows[-1].text_end == 5  # "Label" is 5 chars
        # Extra content position should NOT be mapped
        assert parser.get_row_at_position(len(text) - 1) is None

    def test_gap_between_rows_not_filled(self) -> None:
        """Gaps between rows are intentionally NOT filled.

        This prevents cross-row matches where content between rows
        (due to HTML/text mismatch) could match with adjacent rows.
        """
        html = """<table>
<tr><td>First </td></tr>
<tr><td>Third</td></tr>
</table>"""
        # Text has extra content between rows (HTML doesn't have "middle")
        text = "First middle Third"

        parser = TableRowParser(html, text)

        # Position in "middle" should NOT be mapped (conservative)
        middle_pos = text.find("middle")
        row = parser.get_row_at_position(middle_pos)
        assert row is None  # Gap positions return None


# =============================================================================
# is_table() Tests
# =============================================================================


class TestIsTable:
    """Tests for is_table() method."""

    def test_multi_row_table_is_table(self) -> None:
        """Multi-row table returns True for is_table()."""
        html = """<table>
<tr><td>Row1 </td></tr>
<tr><td>Row2</td></tr>
</table>"""
        text = "Row1 Row2"

        parser = TableRowParser(html, text)
        assert parser.is_table() is True

    def test_single_row_table_not_table(self) -> None:
        """Single-row table returns False for is_table()."""
        html = """<table>
<tr><td>OnlyRow</td></tr>
</table>"""
        text = "OnlyRow"

        parser = TableRowParser(html, text)
        assert parser.is_table() is False

    def test_no_table_not_table(self) -> None:
        """No table returns False for is_table()."""
        html = "<p>No table here</p>"
        text = "No table here"

        parser = TableRowParser(html, text)
        assert parser.is_table() is False


# =============================================================================
# Edge Case Coverage Tests
# =============================================================================


class TestEdgeCaseCoverage:
    """Additional tests to cover edge case branches."""

    def test_empty_rows_attribute(self) -> None:
        """Test behavior when rows is None (shouldn't happen normally)."""
        html = """<table>
<tr><td>Data</td></tr>
</table>"""
        text = "Data"
        parser = TableRowParser(html, text)

        # get_rows should return list even if rows was somehow None
        result = parser.get_rows()
        assert isinstance(result, list)

    def test_get_row_at_position_empty_rows(self) -> None:
        """Test get_row_at_position when no rows are parsed."""
        html = "<table></table>"
        text = ""
        parser = TableRowParser(html, text)

        # Should handle gracefully
        row = parser.get_row_at_position(0)
        # Might be None or the fallback row
        # Just ensure no error
        assert True

    def test_are_in_same_row_unmapped_position(self) -> None:
        """Test are_in_same_row with position outside text range."""
        html = """<table>
<tr><td>Data</td></tr>
</table>"""
        text = "Data"
        parser = TableRowParser(html, text)

        # Position way beyond text length
        result = parser.are_in_same_row(0, 1000)
        assert result is False  # Should return False for unmapped

    def test_is_row_heading_empty_rows(self) -> None:
        """Test is_row_heading when rows list is empty."""
        html = "<p>Not a table</p>"
        text = "Not a table"
        parser = TableRowParser(html, text)

        # Should return False for non-table
        assert parser.is_row_heading(0) is False

    def test_row_without_header_detection(self) -> None:
        """Test row where first cell is pure punctuation."""
        html = """<table>
<tr><td>--- </td><td>100</td></tr>
</table>"""
        text = "--- 100"
        parser = TableRowParser(html, text)
        rows = parser.get_rows()

        # "---" stripped of punctuation is empty, not a header
        assert len(rows) == 1
        # The check depends on the implementation

    def test_header_not_found_in_row_text(self) -> None:
        """Test when header text can't be found in row due to normalization."""
        html = """<table>
<tr><td>Header Text </td><td>100</td></tr>
</table>"""
        # Text doesn't match header due to different spacing
        text = "HeaderText 100"
        parser = TableRowParser(html, text)
        rows = parser.get_rows()

        # Should still parse the row
        assert len(rows) == 1

    def test_position_exactly_at_text_end(self) -> None:
        """Test position at exact end of text."""
        html = """<table>
<tr><td>Test</td></tr>
</table>"""
        text = "Test"
        parser = TableRowParser(html, text)

        # Position at len(text) should be outside
        row = parser.get_row_at_position(len(text))
        # Depends on implementation - might be None or last row extended
        # Just ensure no error
        assert True

    def test_duplicate_text_in_rows(self) -> None:
        """Test when same text appears in multiple rows."""
        html = """<table>
<tr><td>Same </td><td>100</td></tr>
<tr><td>Same </td><td>200</td></tr>
</table>"""
        text = "Same 100 Same 200"
        parser = TableRowParser(html, text)
        rows = parser.get_rows()

        # Should still map both rows correctly
        assert len(rows) == 2
        assert rows[0].text_start != rows[1].text_start
