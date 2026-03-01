"""
Tests for table-aware context extraction.

Tests ExtractedContext dataclass and ContextExtractor class,
including paragraph and table context extraction.
"""

from src.extraction.context_extractor import ContextExtractor, ExtractedContext
from src.extraction.structure_parser import StructureParser

# =============================================================================
# Paragraph Context Tests
# =============================================================================


class TestParagraphContext:
    """Test character-based context extraction for paragraphs."""

    def test_basic_character_window(self) -> None:
        """Test basic character window extraction."""
        text = "Our company had 10 million daily active users as of December 31, 2024."
        extractor = ContextExtractor(context_chars=20)

        # Position at "10"
        position = text.find("10")
        ctx = extractor.extract(text=text, position=position)

        assert "10 million" in ctx.text
        assert "company had" in ctx.text
        assert ctx.position_start >= 0
        assert ctx.position_end <= len(text)
        assert ctx.row_text is None  # No table structure
        assert ctx.column_header is None
        assert ctx.row_header is None

    def test_context_respects_word_boundaries(self) -> None:
        """Test that context extends to complete words."""
        text = "Revenue increased from 100 to 150 million dollars in 2024."
        extractor = ContextExtractor(context_chars=10)

        position = text.find("150")
        ctx = extractor.extract(text=text, position=position)

        # Should include complete words, not cut mid-word
        assert not ctx.text.startswith(" ")
        assert not ctx.text.endswith(" ")
        # Should contain the target value
        assert "150" in ctx.text

    def test_context_at_start_of_text(self) -> None:
        """Test context extraction when position is near text start."""
        text = "10 million users joined the platform."
        extractor = ContextExtractor(context_chars=50)

        position = 0  # Very start
        ctx = extractor.extract(text=text, position=position)

        assert ctx.text.startswith("10")
        assert ctx.position_start == 0

    def test_context_at_end_of_text(self) -> None:
        """Test context extraction when position is near text end."""
        text = "The company reached 100 million users."
        extractor = ContextExtractor(context_chars=50)

        position = len(text) - 5  # Near end
        ctx = extractor.extract(text=text, position=position)

        assert "users" in ctx.text
        assert ctx.position_end <= len(text)

    def test_very_short_text(self) -> None:
        """Test context extraction from very short text."""
        text = "100 users"
        extractor = ContextExtractor(context_chars=50)

        position = text.find("100")
        ctx = extractor.extract(text=text, position=position)

        assert ctx.text == "100 users"
        assert ctx.position_start == 0
        assert ctx.position_end == len(text)

    def test_empty_text(self) -> None:
        """Test handling of empty text."""
        extractor = ContextExtractor(context_chars=50)

        ctx = extractor.extract(text="", position=0)

        assert ctx.text == ""
        assert ctx.position_start == 0
        assert ctx.position_end == 0


# =============================================================================
# Table Context Tests
# =============================================================================


class TestTableContext:
    """Test row-based context extraction for tables."""

    def test_full_row_extracted(self) -> None:
        """Test that full row is extracted as context."""
        html = """
        <table>
            <tr><th>Metric</th><th>2023</th><th>2024</th></tr>
            <tr><td>Revenue</td><td>100</td><td>150</td></tr>
        </table>
        """
        parser = StructureParser(html)
        text = parser.get_text()
        extractor = ContextExtractor()

        # Position at "150"
        position = text.find("150")
        ctx = extractor.extract(text=text, position=position, html=html, segment_type="table")

        # Should contain entire row
        assert "Revenue" in ctx.text
        assert "100" in ctx.text
        assert "150" in ctx.text

    def test_cell_markers_removed_from_output(self) -> None:
        """Test that [CELL] markers are removed from clean text."""
        html = """
        <table>
            <tr><td>Metric</td><td>Value</td></tr>
            <tr><td>Revenue</td><td>100</td></tr>
        </table>
        """
        parser = StructureParser(html)
        text = parser.get_text()
        extractor = ContextExtractor()

        position = text.find("100")
        ctx = extractor.extract(text=text, position=position, html=html, segment_type="table")

        # [CELL] should not appear in clean text
        assert "[CELL]" not in ctx.text
        # Should have pipe separator instead
        assert "|" in ctx.text

    def test_row_markers_removed_from_output(self) -> None:
        """Test that [ROW] markers are removed from clean text."""
        html = """
        <table>
            <tr><td>Metric</td><td>Value</td></tr>
            <tr><td>Revenue</td><td>100</td></tr>
        </table>
        """
        parser = StructureParser(html)
        text = parser.get_text()
        extractor = ContextExtractor()

        position = text.find("100")
        ctx = extractor.extract(text=text, position=position, html=html, segment_type="table")

        # [ROW] should not appear in clean text
        assert "[ROW]" not in ctx.text
        assert "[ROW]" not in ctx.text.strip()

    def test_column_header_detected(self) -> None:
        """Test that column header is extracted from first row."""
        html = """
        <table>
            <tr><th>Metric</th><th>2023</th><th>2024</th></tr>
            <tr><td>Revenue</td><td>100</td><td>150</td></tr>
        </table>
        """
        parser = StructureParser(html)
        text = parser.get_text()
        extractor = ContextExtractor(include_headers=True)

        # Position at "150" (third column)
        position = text.find("150")
        ctx = extractor.extract(text=text, position=position, html=html, segment_type="table")

        assert ctx.column_header == "2024"

    def test_row_header_detected(self) -> None:
        """Test that row header is extracted from first cell."""
        html = """
        <table>
            <tr><th>Metric</th><th>Value</th></tr>
            <tr><td>Revenue</td><td>100</td></tr>
            <tr><td>Profit</td><td>50</td></tr>
        </table>
        """
        parser = StructureParser(html)
        text = parser.get_text()
        extractor = ContextExtractor(include_headers=True)

        # Position at "100"
        position = text.find("100")
        ctx = extractor.extract(text=text, position=position, html=html, segment_type="table")

        assert ctx.row_header == "Revenue"

    def test_multi_column_table(self) -> None:
        """Test context extraction from multi-column table."""
        html = """
        <table>
            <tr><th>Metric</th><th>Q1</th><th>Q2</th><th>Q3</th><th>Q4</th></tr>
            <tr><td>Revenue</td><td>100</td><td>120</td><td>140</td><td>160</td></tr>
        </table>
        """
        parser = StructureParser(html)
        text = parser.get_text()
        extractor = ContextExtractor()

        # Position at "140" (Q3)
        position = text.find("140")
        ctx = extractor.extract(text=text, position=position, html=html, segment_type="table")

        # Should contain entire row
        assert "Revenue" in ctx.text
        assert "100" in ctx.text
        assert "120" in ctx.text
        assert "140" in ctx.text
        assert "160" in ctx.text
        assert ctx.column_header == "Q3"
        assert ctx.row_header == "Revenue"

    def test_position_in_different_cells(self) -> None:
        """Test that context works for positions in any cell."""
        html = """
        <table>
            <tr><th>Metric</th><th>Value</th></tr>
            <tr><td>Revenue</td><td>100</td></tr>
            <tr><td>Users</td><td>200</td></tr>
        </table>
        """
        parser = StructureParser(html)
        text = parser.get_text()
        extractor = ContextExtractor()

        # Test first cell
        position = text.find("Revenue")
        ctx = extractor.extract(text=text, position=position, html=html, segment_type="table")
        assert "Revenue" in ctx.text
        assert "100" in ctx.text

        # Test second row
        position = text.find("200")
        ctx = extractor.extract(text=text, position=position, html=html, segment_type="table")
        assert "Users" in ctx.text
        assert "200" in ctx.text

    def test_table_with_th_headers(self) -> None:
        """Test table with <th> header elements."""
        html = """
        <table>
            <tr><th>Year</th><th>Revenue</th></tr>
            <tr><td>2023</td><td>100</td></tr>
            <tr><td>2024</td><td>150</td></tr>
        </table>
        """
        parser = StructureParser(html)
        text = parser.get_text()
        extractor = ContextExtractor(include_headers=True)

        position = text.find("150")
        ctx = extractor.extract(text=text, position=position, html=html, segment_type="table")

        assert ctx.column_header == "Revenue"
        assert ctx.row_header == "2024"


# =============================================================================
# Formatting Tests
# =============================================================================


class TestContextFormatting:
    """Test context formatting methods."""

    def test_format_table_context_with_headers(self) -> None:
        """Test formatting with both column and row headers."""
        extractor = ContextExtractor(include_headers=True)

        formatted = extractor.format_table_context(
            row_text="Revenue [CELL] 100 [CELL] 150", column_header="2024", row_header="Revenue"
        )

        assert "[2024]" in formatted
        assert "Revenue:" in formatted
        assert "100" in formatted
        assert "150" in formatted
        assert "[CELL]" not in formatted  # Markers cleaned

    def test_format_table_context_without_headers(self) -> None:
        """Test formatting with no headers."""
        extractor = ContextExtractor(include_headers=False)

        formatted = extractor.format_table_context(
            row_text="Revenue [CELL] 100 [CELL] 150", column_header=None, row_header=None
        )

        assert "Revenue" in formatted
        assert "100" in formatted
        assert "150" in formatted
        assert "[" not in formatted  # No header brackets

    def test_headers_excluded_when_not_requested(self) -> None:
        """Test that headers are not extracted when include_headers=False."""
        html = """
        <table>
            <tr><th>Metric</th><th>Value</th></tr>
            <tr><td>Revenue</td><td>100</td></tr>
        </table>
        """
        parser = StructureParser(html)
        text = parser.get_text()
        extractor = ContextExtractor(include_headers=False)

        position = text.find("100")
        ctx = extractor.extract(text=text, position=position, html=html, segment_type="table")

        assert ctx.column_header is None
        assert ctx.row_header is None

    def test_very_long_row_formatting(self) -> None:
        """Test formatting of very long table rows."""
        long_row = " [CELL] ".join([f"col{i}" for i in range(50)])
        extractor = ContextExtractor()

        formatted = extractor.format_table_context(row_text=long_row)

        # Should be cleaned and formatted
        assert "[CELL]" not in formatted
        assert "|" in formatted
        assert "col0" in formatted
        assert "col49" in formatted

    def test_special_characters_in_context(self) -> None:
        """Test handling of special characters in context."""
        html = """
        <table>
            <tr><td>Revenue & Profit</td><td>$100</td></tr>
        </table>
        """
        parser = StructureParser(html)
        text = parser.get_text()
        extractor = ContextExtractor()

        position = text.find("100")
        ctx = extractor.extract(text=text, position=position, html=html, segment_type="table")

        assert "&" in ctx.text or "amp" in ctx.text  # BeautifulSoup may decode
        assert "$" in ctx.text or "100" in ctx.text


# =============================================================================
# Edge Cases
# =============================================================================


class TestEdgeCases:
    """Test edge cases and error conditions."""

    def test_empty_cells_in_row(self) -> None:
        """Test row with empty cells."""
        html = """
        <table>
            <tr><td>Metric</td><td></td><td>100</td></tr>
        </table>
        """
        parser = StructureParser(html)
        text = parser.get_text()
        extractor = ContextExtractor()

        position = text.find("100")
        ctx = extractor.extract(text=text, position=position, html=html, segment_type="table")

        assert "100" in ctx.text
        assert ctx.text is not None

    def test_single_cell_row(self) -> None:
        """Test row with only one cell."""
        html = """
        <table>
            <tr><td>Single value: 100</td></tr>
        </table>
        """
        parser = StructureParser(html)
        text = parser.get_text()
        extractor = ContextExtractor()

        position = text.find("100")
        ctx = extractor.extract(text=text, position=position, html=html, segment_type="table")

        assert "100" in ctx.text
        assert ctx.row_header == "Single value: 100"

    def test_very_large_table(self) -> None:
        """Test extraction from large table."""
        # Create 100-row table
        rows = ["<tr><td>Row</td><td>Value</td></tr>"]
        for i in range(100):
            rows.append(f"<tr><td>Row{i}</td><td>{i * 100}</td></tr>")

        html = f"<table>{''.join(rows)}</table>"
        parser = StructureParser(html)
        text = parser.get_text()
        extractor = ContextExtractor()

        # Extract context from middle row
        position = text.find("5000")  # Row 50
        ctx = extractor.extract(text=text, position=position, html=html, segment_type="table")

        # Should only contain the single row, not entire table
        assert "5000" in ctx.text
        assert "Row50" in ctx.text
        # Should not contain other rows
        assert "Row0" not in ctx.text
        assert "Row99" not in ctx.text

    def test_nested_tables(self) -> None:
        """Test handling of nested tables (flatten)."""
        html = """
        <table>
            <tr>
                <td>Outer</td>
                <td>
                    <table>
                        <tr><td>Inner</td><td>100</td></tr>
                    </table>
                </td>
            </tr>
        </table>
        """
        parser = StructureParser(html)
        text = parser.get_text()
        extractor = ContextExtractor()

        # Should handle without error
        position = text.find("100") if "100" in text else 0
        ctx = extractor.extract(text=text, position=position, html=html, segment_type="table")

        assert ctx.text is not None

    def test_position_exactly_on_cell_marker(self) -> None:
        """Test position exactly on [CELL] marker."""
        html = """
        <table>
            <tr><td>Value1</td><td>Value2</td></tr>
        </table>
        """
        parser = StructureParser(html)
        text = parser.get_text()
        extractor = ContextExtractor()

        # Position on [CELL] marker
        cell_pos = text.find("[CELL]")
        if cell_pos >= 0:
            ctx = extractor.extract(text=text, position=cell_pos, html=html, segment_type="table")

            # Should handle gracefully
            assert ctx.text is not None
            assert "[CELL]" not in ctx.text

    def test_row_with_all_empty_cells(self) -> None:
        """Test row where all cells are empty."""
        html = """
        <table>
            <tr><td></td><td></td><td></td></tr>
        </table>
        """
        parser = StructureParser(html)
        text = parser.get_text()
        extractor = ContextExtractor()

        # Position in the row
        position = 0
        ctx = extractor.extract(text=text, position=position, html=html, segment_type="table")

        # Should handle without error
        assert ctx.text is not None

    def test_table_with_no_header_row(self) -> None:
        """Test table without a header row."""
        html = """
        <table>
            <tr><td>Revenue</td><td>100</td></tr>
            <tr><td>Profit</td><td>50</td></tr>
        </table>
        """
        parser = StructureParser(html)
        text = parser.get_text()
        extractor = ContextExtractor(include_headers=True)

        position = text.find("50")
        ctx = extractor.extract(text=text, position=position, html=html, segment_type="table")

        # Should extract headers from data rows
        assert ctx.row_header == "Profit"
        # Column header will be from first row's second cell
        assert ctx.column_header is not None

    def test_fallback_to_basic_on_parser_error(self) -> None:
        """Test fallback to basic extraction when StructureParser fails."""
        # Invalid HTML that might cause parsing issues
        text = "Revenue [CELL] 100 [CELL] 150 [ROW]"
        html = "<table><invalid>stuff</invalid></table>"
        extractor = ContextExtractor(context_chars=20)

        position = text.find("100")
        ctx = extractor.extract(text=text, position=position, html=html, segment_type="table")

        # Should fall back to basic extraction
        assert "100" in ctx.text
        assert ctx.text is not None

    def test_fallback_when_position_outside_rows(self) -> None:
        """Test fallback when position is not within any row."""
        html = """
        <table>
            <tr><td>Value1</td><td>100</td></tr>
        </table>
        """
        parser = StructureParser(html)
        text = parser.get_text() + " Extra text outside table 200"
        extractor = ContextExtractor(context_chars=30)

        # Position in text outside table structure
        position = text.find("200")
        ctx = extractor.extract(text=text, position=position, html=html, segment_type="table")

        # Should fall back to basic extraction
        assert "200" in ctx.text

    def test_position_clamping(self) -> None:
        """Test that position is clamped to valid range."""
        text = "Short text with 100"
        extractor = ContextExtractor()

        # Position beyond text length
        ctx = extractor.extract(text=text, position=1000)

        # Should clamp and not error
        assert ctx.text is not None
        assert len(ctx.text) > 0


# =============================================================================
# Integration Tests
# =============================================================================


class TestContextExtractorIntegration:
    """Test integration scenarios."""

    def test_paragraph_without_html(self) -> None:
        """Test that paragraph extraction works without HTML."""
        text = "Our revenue grew to 150 million in 2024."
        extractor = ContextExtractor(context_chars=30)

        position = text.find("150")
        ctx = extractor.extract(text=text, position=position, segment_type="paragraph")

        assert "150 million" in ctx.text
        assert ctx.row_text is None

    def test_table_without_html_falls_back(self) -> None:
        """Test that table extraction without HTML falls back to basic."""
        text = "Revenue [CELL] 100 [CELL] 150 [ROW]"
        extractor = ContextExtractor(context_chars=20)

        position = text.find("150")
        ctx = extractor.extract(text=text, position=position, segment_type="table")

        # Should use basic extraction and clean markers
        assert "150" in ctx.text
        assert "|" in ctx.text  # [CELL] converted to pipe

    def test_extractedcontext_dataclass_defaults(self) -> None:
        """Test ExtractedContext with default values."""
        ctx = ExtractedContext(text="test content")

        assert ctx.text == "test content"
        assert ctx.row_text is None
        assert ctx.column_header is None
        assert ctx.row_header is None
        assert ctx.position_start == 0
        assert ctx.position_end == 0

    def test_extractedcontext_all_fields(self) -> None:
        """Test ExtractedContext with all fields populated."""
        ctx = ExtractedContext(
            text="clean text",
            row_text="raw [CELL] text",
            column_header="2024",
            row_header="Revenue",
            position_start=10,
            position_end=50,
        )

        assert ctx.text == "clean text"
        assert ctx.row_text == "raw [CELL] text"
        assert ctx.column_header == "2024"
        assert ctx.row_header == "Revenue"
        assert ctx.position_start == 10
        assert ctx.position_end == 50


# =============================================================================
# DFP-1: ROW Marker Stripping Tests
# =============================================================================


class TestRowMarkerStripping:
    """DFP-1: Tests for ROW marker stripping that preserves word boundaries.

    Bug fix: [ROW] markers were being replaced with empty string, causing
    adjacent values to concatenate (e.g., "2019 [ROW] 2020" -> "20192020").
    Fix: Replace [ROW] with space to preserve word boundaries.
    """

    def test_row_marker_preserves_space_between_values(self) -> None:
        """'2019 [ROW] 2020' should become '2019 2020', not '20192020'."""
        extractor = ContextExtractor()
        text = "2019 [ROW] 2020"
        cleaned = extractor._clean_markers(text)

        assert cleaned == "2019 2020"
        assert "20192020" not in cleaned  # No concatenation

    def test_row_marker_preserves_space_between_words(self) -> None:
        """'Header [ROW] Data' should become 'Header Data', not 'HeaderData'."""
        extractor = ContextExtractor()
        text = "Header [ROW] Data"
        cleaned = extractor._clean_markers(text)

        assert cleaned == "Header Data"
        assert "HeaderData" not in cleaned

    def test_multiple_row_markers_preserved(self) -> None:
        """'A [ROW] B [ROW] C' should become 'A B C'."""
        extractor = ContextExtractor()
        text = "A [ROW] B [ROW] C"
        cleaned = extractor._clean_markers(text)

        assert cleaned == "A B C"

    def test_cell_markers_still_work(self) -> None:
        """[CELL] markers should still convert to pipe separators."""
        extractor = ContextExtractor()
        text = "Revenue [CELL] 100 [CELL] 150"
        cleaned = extractor._clean_markers(text)

        assert cleaned == "Revenue | 100 | 150"
        assert "[CELL]" not in cleaned

    def test_combined_cell_and_row_markers(self) -> None:
        """'A [CELL] B [ROW] C [CELL] D' should work correctly."""
        extractor = ContextExtractor()
        text = "A [CELL] B [ROW] C [CELL] D"
        cleaned = extractor._clean_markers(text)

        # [CELL] becomes " | ", [ROW] becomes space, then whitespace normalized
        assert "A | B C | D" == cleaned
        assert "[CELL]" not in cleaned
        assert "[ROW]" not in cleaned

    def test_row_marker_at_start(self) -> None:
        """[ROW] at start should not leave leading space."""
        extractor = ContextExtractor()
        text = "[ROW] Content here"
        cleaned = extractor._clean_markers(text)

        assert cleaned == "Content here"
        assert not cleaned.startswith(" ")

    def test_row_marker_at_end(self) -> None:
        """[ROW] at end should not leave trailing space."""
        extractor = ContextExtractor()
        text = "Content here [ROW]"
        cleaned = extractor._clean_markers(text)

        assert cleaned == "Content here"
        assert not cleaned.endswith(" ")

    def test_multiple_consecutive_row_markers(self) -> None:
        """Multiple consecutive [ROW] markers should normalize to single space."""
        extractor = ContextExtractor()
        text = "A [ROW] [ROW] B"
        cleaned = extractor._clean_markers(text)

        assert cleaned == "A B"

    def test_real_world_table_row(self) -> None:
        """Test with realistic table row data."""
        extractor = ContextExtractor()
        # Simulates a row with fiscal year headers
        text = "Revenue [CELL] January 31, [CELL] 2019 [ROW] 2020 [ROW] 2021"
        cleaned = extractor._clean_markers(text)

        # Should preserve years as separate tokens
        assert "2019" in cleaned
        assert "2020" in cleaned
        assert "2021" in cleaned
        assert "20192020" not in cleaned  # No year concatenation
        assert "20202021" not in cleaned

    def test_snowflake_filing_example(self) -> None:
        """Test case from Snowflake filing that triggered the bug.

        Original text had '2019 [ROW] 2020' becoming '20192020'.
        """
        extractor = ContextExtractor()
        text = "Fiscal Year Ended January 31, [CELL] 2019 [ROW] 2020"
        cleaned = extractor._clean_markers(text)

        # Years should be separate
        assert "2019" in cleaned
        assert "2020" in cleaned
        # Should NOT have concatenated years
        assert "20192020" not in cleaned
