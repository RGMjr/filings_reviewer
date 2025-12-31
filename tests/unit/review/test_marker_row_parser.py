"""
Tests for marker_row_parser.py - Parse row boundaries from [ROW]/[CELL] markers.

Coverage target: >= 90% for src/review/marker_row_parser.py

Test categories:
1. Basic Parsing - Row boundary detection from markers
2. Same-Row Detection - are_in_same_row() method
3. Header Detection - is_row_heading() method
4. Edge Cases - Empty text, single rows, boundary conditions
"""

import pytest

from src.review.marker_row_parser import MarkerRow, MarkerRowParser


class TestBasicParsing:
    """Tests for basic row parsing from markers."""

    def test_parse_two_row_table(self) -> None:
        """Parse simple two-row table with markers."""
        text = "Paid Customers [CELL] 37,000 [ROW] Revenue [CELL] $100M"
        parser = MarkerRowParser(text)

        rows = parser.get_rows()
        assert len(rows) == 2

        # First row
        assert rows[0].row_index == 0
        assert rows[0].row_text == "Paid Customers [CELL] 37,000"
        assert rows[0].text_start == 0
        assert rows[0].text_end == 28

        # Second row
        assert rows[1].row_index == 1
        assert rows[1].row_text == "Revenue [CELL] $100M"
        assert rows[1].text_start == 35  # After " [ROW] "

    def test_parse_three_row_table(self) -> None:
        """Parse table with three rows."""
        text = "A [CELL] 1 [ROW] B [CELL] 2 [ROW] C [CELL] 3"
        parser = MarkerRowParser(text)

        rows = parser.get_rows()
        assert len(rows) == 3
        assert rows[0].row_text == "A [CELL] 1"
        assert rows[1].row_text == "B [CELL] 2"
        assert rows[2].row_text == "C [CELL] 3"

    def test_parse_single_row_no_row_marker(self) -> None:
        """Single row table has no [ROW] marker."""
        text = "Metric Name [CELL] 100 [CELL] 200"
        parser = MarkerRowParser(text)

        rows = parser.get_rows()
        assert len(rows) == 1
        assert rows[0].row_text == text
        assert rows[0].text_start == 0
        assert rows[0].text_end == len(text)

    def test_parse_multiple_cells_per_row(self) -> None:
        """Parse rows with multiple cells."""
        text = "Header [CELL] 2017 [CELL] 2018 [CELL] 2019 [ROW] Value [CELL] 100 [CELL] 200 [CELL] 300"
        parser = MarkerRowParser(text)

        rows = parser.get_rows()
        assert len(rows) == 2
        assert "[CELL]" in rows[0].row_text
        assert "[CELL]" in rows[1].row_text

    def test_is_table_multi_row(self) -> None:
        """is_table() returns True for multi-row tables."""
        text = "A [ROW] B"
        parser = MarkerRowParser(text)
        assert parser.is_table() is True

    def test_is_table_single_row(self) -> None:
        """is_table() returns False for single row."""
        text = "A [CELL] B"
        parser = MarkerRowParser(text)
        assert parser.is_table() is False


class TestSameRowDetection:
    """Tests for are_in_same_row() method."""

    def test_same_row_positions_return_true(self) -> None:
        """Positions in same row return True."""
        text = "Paid Customers [CELL] 37,000 [ROW] Revenue [CELL] $100M"
        parser = MarkerRowParser(text)

        pos_paid = text.find("Paid Customers")
        pos_37k = text.find("37,000")

        assert parser.are_in_same_row(pos_paid, pos_37k) is True

    def test_different_row_positions_return_false(self) -> None:
        """Positions in different rows return False."""
        text = "Paid Customers [CELL] 37,000 [ROW] Revenue [CELL] $100M"
        parser = MarkerRowParser(text)

        pos_paid = text.find("Paid Customers")
        pos_revenue = text.find("Revenue")

        assert parser.are_in_same_row(pos_paid, pos_revenue) is False

    def test_cross_row_value_keyword_detection(self) -> None:
        """Correctly detect cross-row matching scenario."""
        # This is the exact scenario we're fixing
        text = "Total customers [CELL] 948 [CELL] 2,392 [ROW] Net revenue retention rate [CELL] 180 [CELL] %"
        parser = MarkerRowParser(text)

        pos_948 = text.find("948")
        pos_nrr = text.find("Net revenue retention")

        # 948 is in row 0, Net revenue retention is in row 1
        assert parser.are_in_same_row(pos_948, pos_nrr) is False

        # 180 and Net revenue retention are in same row
        pos_180 = text.find("180")
        assert parser.are_in_same_row(pos_180, pos_nrr) is True

    def test_position_at_row_start(self) -> None:
        """Position at start of row is correctly identified."""
        text = "A [ROW] B"
        parser = MarkerRowParser(text)

        # Position 0 is in row 0
        # Position 8 (start of "B") is in row 1
        assert parser.are_in_same_row(0, 0) is True
        assert parser.are_in_same_row(8, 8) is True
        assert parser.are_in_same_row(0, 8) is False

    def test_position_out_of_range_returns_false(self) -> None:
        """Position outside text range returns False."""
        text = "A [ROW] B"
        parser = MarkerRowParser(text)

        assert parser.are_in_same_row(0, 1000) is False
        assert parser.are_in_same_row(-1, 0) is False

    def test_both_positions_out_of_range(self) -> None:
        """Both positions out of range returns False."""
        text = "A [ROW] B"
        parser = MarkerRowParser(text)

        assert parser.are_in_same_row(1000, 2000) is False


class TestHeaderDetection:
    """Tests for header detection and is_row_heading()."""

    def test_non_numeric_header_detected(self) -> None:
        """Non-numeric first cell is detected as header."""
        text = "Gross Profit [CELL] 100 [CELL] 200"
        parser = MarkerRowParser(text)

        rows = parser.get_rows()
        assert rows[0].header_text == "Gross Profit"
        assert rows[0].header_start == 0
        assert rows[0].header_end == len("Gross Profit")

    def test_numeric_header_not_detected(self) -> None:
        """Numeric-only first cell is NOT a header."""
        text = "2023 [CELL] 100 [CELL] 200"
        parser = MarkerRowParser(text)

        rows = parser.get_rows()
        assert rows[0].header_text is None
        assert rows[0].header_start is None

    def test_mixed_alphanumeric_is_header(self) -> None:
        """Mixed alphanumeric first cell IS a header."""
        text = "$100K ARR [CELL] 500 [CELL] 600"
        parser = MarkerRowParser(text)

        rows = parser.get_rows()
        assert rows[0].header_text == "$100K ARR"

    def test_is_row_heading_returns_true_for_header_position(self) -> None:
        """is_row_heading() returns True for header positions."""
        text = "Net Dollar Retention [CELL] 171 [CELL] %"
        parser = MarkerRowParser(text)

        pos_ndr = text.find("Net Dollar Retention")
        pos_171 = text.find("171")

        assert parser.is_row_heading(pos_ndr) is True
        assert parser.is_row_heading(pos_171) is False

    def test_is_row_heading_multiple_rows(self) -> None:
        """is_row_heading() works across multiple rows."""
        text = "Customers [CELL] 100 [ROW] Revenue [CELL] $50M"
        parser = MarkerRowParser(text)

        pos_customers = text.find("Customers")
        pos_revenue = text.find("Revenue")

        assert parser.is_row_heading(pos_customers) is True
        assert parser.is_row_heading(pos_revenue) is True

    def test_single_cell_row_header(self) -> None:
        """Single-cell row can have a header."""
        text = "Summary Row [ROW] Data [CELL] 100"
        parser = MarkerRowParser(text)

        rows = parser.get_rows()
        assert rows[0].header_text == "Summary Row"


class TestEdgeCases:
    """Tests for edge cases and special scenarios."""

    def test_empty_text(self) -> None:
        """Handle empty text gracefully."""
        parser = MarkerRowParser("")

        assert len(parser.get_rows()) == 0
        assert parser.is_table() is False
        assert parser.are_in_same_row(0, 1) is False

    def test_whitespace_only_text(self) -> None:
        """Handle whitespace-only text."""
        parser = MarkerRowParser("   \n\t  ")

        assert len(parser.get_rows()) == 0
        assert parser.is_table() is False

    def test_only_cell_markers_no_row(self) -> None:
        """Text with only [CELL] markers (single row)."""
        text = "A [CELL] B [CELL] C"
        parser = MarkerRowParser(text)

        assert len(parser.get_rows()) == 1
        assert parser.is_table() is False
        assert parser.are_in_same_row(0, len(text) - 1) is True

    def test_text_without_any_markers(self) -> None:
        """Text without markers treated as single row."""
        text = "Just plain text with no markers"
        parser = MarkerRowParser(text)

        assert len(parser.get_rows()) == 1
        assert parser.is_table() is False
        rows = parser.get_rows()
        assert rows[0].row_text == text

    def test_consecutive_row_markers(self) -> None:
        """Handle consecutive [ROW] markers (empty rows)."""
        text = "A [ROW]  [ROW] B"
        parser = MarkerRowParser(text)

        # Empty rows should be skipped
        rows = parser.get_rows()
        assert len(rows) == 2
        assert rows[0].row_text == "A"
        assert rows[1].row_text == "B"

    def test_trailing_row_marker(self) -> None:
        """Handle trailing [ROW] marker."""
        text = "A [CELL] 1 [ROW] "
        parser = MarkerRowParser(text)

        rows = parser.get_rows()
        assert len(rows) == 1
        assert rows[0].row_text == "A [CELL] 1"

    def test_get_row_at_position(self) -> None:
        """get_row_at_position returns correct row."""
        text = "A [ROW] B"
        parser = MarkerRowParser(text)

        row_a = parser.get_row_at_position(0)
        row_b = parser.get_row_at_position(8)

        assert row_a is not None
        assert row_a.row_text == "A"
        assert row_b is not None
        assert row_b.row_text == "B"

    def test_get_row_at_position_not_found(self) -> None:
        """get_row_at_position returns None for out-of-range."""
        text = "A [ROW] B"
        parser = MarkerRowParser(text)

        assert parser.get_row_at_position(1000) is None
        assert parser.get_row_at_position(-1) is None

    def test_complex_real_world_table(self) -> None:
        """Parse complex table matching real-world format from Slack S-1."""
        text = (
            "Paid Customers [CELL] 37,000 [CELL] 59,000 [CELL] 88,000 [ROW] "
            "Paid Customers >$100,000 [CELL] 135 [CELL] 298 [CELL] 575 [ROW] "
            "Net Dollar Retention Rate [CELL] 171 [CELL] % [CELL] 152 [CELL] % [CELL] 143 [CELL] %"
        )
        parser = MarkerRowParser(text)

        rows = parser.get_rows()
        assert len(rows) == 3

        # Verify headers
        assert rows[0].header_text == "Paid Customers"
        assert rows[1].header_text == "Paid Customers >$100,000"
        assert rows[2].header_text == "Net Dollar Retention Rate"

        # Verify cross-row detection
        pos_37k = text.find("37,000")
        pos_135 = text.find("135")
        pos_171 = text.find("171")

        assert parser.are_in_same_row(pos_37k, pos_135) is False
        assert parser.are_in_same_row(pos_135, pos_171) is False

        # Verify same-row detection
        pos_59k = text.find("59,000")
        assert parser.are_in_same_row(pos_37k, pos_59k) is True


class TestMarkerRowDataclass:
    """Tests for MarkerRow dataclass."""

    def test_marker_row_creation(self) -> None:
        """MarkerRow can be created with all fields."""
        row = MarkerRow(
            row_index=0,
            text_start=0,
            text_end=10,
            row_text="Test Row",
            header_text="Test",
            header_start=0,
            header_end=4,
        )

        assert row.row_index == 0
        assert row.text_start == 0
        assert row.text_end == 10
        assert row.row_text == "Test Row"
        assert row.header_text == "Test"

    def test_marker_row_optional_fields(self) -> None:
        """MarkerRow optional fields default to None."""
        row = MarkerRow(
            row_index=0,
            text_start=0,
            text_end=5,
            row_text="Test",
        )

        assert row.header_text is None
        assert row.header_start is None
        assert row.header_end is None
