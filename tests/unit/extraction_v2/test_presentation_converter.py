"""
Unit tests for presentation_converter.

Tests cover:
- Multi-page PDF → correct number of sections and data-page attributes
- Tables → <table> elements in output
- Empty pages → section with HTML comment
- Title slide detection heuristic
- Error handling for unreadable PDFs

All tests mock pdfplumber.open() to avoid requiring a real PDF file.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.extraction_v2.presentation_converter import (
    DocumentType,
    PresentationMetadata,
    _escape_html,
    _is_title_slide,
    _table_to_html,
    convert_presentation_to_html,
)

# ============================================================================
# Helpers
# ============================================================================


def _make_page(
    text: str = "",
    tables: list[list[list[str | None]]] | None = None,
    images: list[dict] | None = None,
) -> MagicMock:
    """Create a mock pdfplumber page."""
    page = MagicMock()
    page.extract_text.return_value = text
    page.extract_tables.return_value = tables or []
    page.images = images or []
    return page


def _make_pdf(pages: list[MagicMock]) -> MagicMock:
    """Create a mock pdfplumber PDF context manager."""
    pdf = MagicMock()
    pdf.pages = pages
    pdf.__enter__ = MagicMock(return_value=pdf)
    pdf.__exit__ = MagicMock(return_value=False)
    return pdf


# ============================================================================
# HTML Escaping
# ============================================================================


class TestEscapeHtml:
    def test_escapes_ampersand(self) -> None:
        assert _escape_html("A & B") == "A &amp; B"

    def test_escapes_angle_brackets(self) -> None:
        assert _escape_html("<b>") == "&lt;b&gt;"

    def test_escapes_double_quotes(self) -> None:
        assert _escape_html('"value"') == "&quot;value&quot;"

    def test_plain_text_unchanged(self) -> None:
        assert _escape_html("Hello world 123") == "Hello world 123"


# ============================================================================
# Table to HTML
# ============================================================================


class TestTableToHtml:
    def test_single_row(self) -> None:
        rows = [["A", "B", "C"]]
        html = _table_to_html(rows)
        assert "<table>" in html
        assert "<td>A</td>" in html
        assert "<td>B</td>" in html
        assert "</table>" in html

    def test_multiple_rows(self) -> None:
        rows = [["Q1", "Q2"], ["100", "200"]]
        html = _table_to_html(rows)
        assert html.count("<tr>") == 2
        assert "<td>100</td>" in html

    def test_none_cells_become_empty(self) -> None:
        rows = [["A", None, "C"]]
        html = _table_to_html(rows)
        # None should become empty <td></td>
        assert "<td></td>" in html

    def test_empty_rows_returns_empty_string(self) -> None:
        assert _table_to_html([]) == ""

    def test_html_escaping_in_cells(self) -> None:
        rows = [["Revenue & Growth", "<20%"]]
        html = _table_to_html(rows)
        assert "&amp;" in html
        assert "&lt;" in html


# ============================================================================
# Title Slide Heuristic
# ============================================================================


class TestIsTitleSlide:
    def test_few_lines_is_title(self) -> None:
        # < 5 non-empty lines → title slide
        lines = ["ACME Corp", "Q3 2025 Investor Presentation"]
        assert _is_title_slide(lines) is True

    def test_exactly_5_lines_not_title_by_count(self) -> None:
        # 5 lines that don't trigger other heuristics → not a title slide
        lines = [
            "Line one with numbers 123",
            "Line two with numbers 456",
            "Line three numbers 789",
            "Line four numbers 321",
            "Line five numbers 654",
        ]
        # All lowercase, have numbers, 5 lines — should NOT be title
        assert _is_title_slide(lines) is False

    def test_all_caps_first_line_is_title(self) -> None:
        lines = [
            "SALESFORCE INC",
            "Annual Revenue Review 2025",
            "Financial Performance Summary",
            "Customer Metrics Overview",
            "Market Position Analysis",
            "Forward Looking Guidance",
        ]
        assert _is_title_slide(lines) is True

    def test_first_line_no_numbers_is_title(self) -> None:
        # First line with no digits triggers title heuristic
        lines = [
            "Investor Day Presentation",
            "Revenue grew 25% in Q3",
            "Customers exceeded 1000",
            "ARR at $500M milestone",
            "NRR stable at 120%",
            "Outlook positive for FY2026",
        ]
        assert _is_title_slide(lines) is True

    def test_first_line_has_numbers_and_not_caps_not_title(self) -> None:
        # First line has numbers, is not all-caps, and there are >= 5 lines
        lines = [
            "Q3 2025 results: revenue $500M",
            "Customer count: 12,000",
            "NRR: 120%",
            "ARR: $240M",
            "Operating margin: 15%",
            "Free cash flow: $80M",
        ]
        assert _is_title_slide(lines) is False

    def test_empty_lines_returns_false(self) -> None:
        assert _is_title_slide([]) is False

    def test_blank_lines_only_returns_false(self) -> None:
        assert _is_title_slide(["", "  ", "\t"]) is False


# ============================================================================
# Multi-page PDF → correct sections
# ============================================================================


class TestConvertPresentationMultiPage:
    def test_correct_number_of_sections(self) -> None:
        pages = [
            _make_page("Title Slide"),
            _make_page("Financial Summary\nRevenue $500M"),
            _make_page("Customer Metrics\nARR $240M NRR 120%"),
        ]
        pdf = _make_pdf(pages)

        with patch("pdfplumber.open", return_value=pdf):
            html, meta = convert_presentation_to_html(Path("/fake/deck.pdf"))

        assert html.count('data-section-type="presentation_slide"') == 3
        assert meta.page_count == 3

    def test_data_page_attributes(self) -> None:
        pages = [
            _make_page("Slide One"),
            _make_page("Slide Two"),
        ]
        pdf = _make_pdf(pages)

        with patch("pdfplumber.open", return_value=pdf):
            html, meta = convert_presentation_to_html(Path("/fake/deck.pdf"))

        assert 'data-page="1"' in html
        assert 'data-page="2"' in html

    def test_data_page_count_on_every_section(self) -> None:
        pages = [_make_page("A"), _make_page("B"), _make_page("C")]
        pdf = _make_pdf(pages)

        with patch("pdfplumber.open", return_value=pdf):
            html, _ = convert_presentation_to_html(Path("/fake/deck.pdf"))

        # Every section should carry data-page-count="3"
        assert html.count('data-page-count="3"') == 3

    def test_metadata_source_id_is_pdf_path(self) -> None:
        pages = [_make_page("Content")]
        pdf = _make_pdf(pages)

        with patch("pdfplumber.open", return_value=pdf):
            _, meta = convert_presentation_to_html(Path("/some/path/report.pdf"))

        assert meta.source_id == "/some/path/report.pdf"

    def test_metadata_source_type_is_presentation(self) -> None:
        pages = [_make_page("Content")]
        pdf = _make_pdf(pages)

        with patch("pdfplumber.open", return_value=pdf):
            _, meta = convert_presentation_to_html(Path("/fake/deck.pdf"))

        assert meta.source_type == DocumentType.PRESENTATION

    def test_title_from_first_page_first_line(self) -> None:
        pages = [_make_page("ACME Investor Day\nMore content")]
        pdf = _make_pdf(pages)

        with patch("pdfplumber.open", return_value=pdf):
            _, meta = convert_presentation_to_html(Path("/fake/deck.pdf"))

        assert meta.title == "ACME Investor Day"

    def test_title_falls_back_to_stem_when_no_text(self) -> None:
        pages = [_make_page("")]  # first page has no text
        pdf = _make_pdf(pages)

        with patch("pdfplumber.open", return_value=pdf):
            _, meta = convert_presentation_to_html(Path("/fake/my_deck.pdf"))

        assert meta.title == "my_deck"


# ============================================================================
# Tables → <table> elements
# ============================================================================


class TestConvertPresentationTables:
    def test_table_appears_in_output(self) -> None:
        table = [["Metric", "Q3 2025"], ["ARR", "$240M"], ["NRR", "120%"]]
        pages = [_make_page("Financial Highlights", tables=[table])]
        pdf = _make_pdf(pages)

        with patch("pdfplumber.open", return_value=pdf):
            html, _ = convert_presentation_to_html(Path("/fake/deck.pdf"))

        assert "<table>" in html
        assert "<td>ARR</td>" in html
        assert "<td>$240M</td>" in html

    def test_multiple_tables_on_one_page(self) -> None:
        t1 = [["A", "B"]]
        t2 = [["C", "D"]]
        pages = [_make_page("Dual tables slide", tables=[t1, t2])]
        pdf = _make_pdf(pages)

        with patch("pdfplumber.open", return_value=pdf):
            html, _ = convert_presentation_to_html(Path("/fake/deck.pdf"))

        assert html.count("<table>") == 2

    def test_table_and_text_on_same_page(self) -> None:
        table = [["Metric", "Value"]]
        pages = [_make_page("Summary\nKey metrics", tables=[table])]
        pdf = _make_pdf(pages)

        with patch("pdfplumber.open", return_value=pdf):
            html, _ = convert_presentation_to_html(Path("/fake/deck.pdf"))

        assert "<table>" in html
        assert "<p>Summary</p>" in html


# ============================================================================
# Empty pages
# ============================================================================


class TestConvertPresentationEmptyPages:
    def test_empty_page_has_comment(self) -> None:
        pages = [
            _make_page("Real slide"),
            _make_page(""),  # empty page
        ]
        pdf = _make_pdf(pages)

        with patch("pdfplumber.open", return_value=pdf):
            html, _ = convert_presentation_to_html(Path("/fake/deck.pdf"))

        assert "<!-- empty page -->" in html

    def test_empty_page_still_generates_section(self) -> None:
        pages = [_make_page("")]
        pdf = _make_pdf(pages)

        with patch("pdfplumber.open", return_value=pdf):
            html, _ = convert_presentation_to_html(Path("/fake/deck.pdf"))

        assert 'data-section-type="presentation_slide"' in html
        assert "<!-- empty page -->" in html

    def test_empty_page_does_not_produce_spurious_p_tags(self) -> None:
        pages = [_make_page("")]
        pdf = _make_pdf(pages)

        with patch("pdfplumber.open", return_value=pdf):
            html, _ = convert_presentation_to_html(Path("/fake/deck.pdf"))

        assert "<p>" not in html


# ============================================================================
# Title slide detection in full conversion
# ============================================================================


class TestConvertPresentationTitleSlide:
    def test_first_page_sparse_gets_title_attr(self) -> None:
        # < 5 lines → title slide
        pages = [
            _make_page("ACME Corp\nInvestor Day 2025"),
            _make_page("Revenue $500M\nQ3 results\nARR $240M\nNRR 120%\nCustomers 12000"),
        ]
        pdf = _make_pdf(pages)

        with patch("pdfplumber.open", return_value=pdf):
            html, _ = convert_presentation_to_html(Path("/fake/deck.pdf"))

        assert 'data-is-title="true"' in html

    def test_first_page_dense_no_title_attr(self) -> None:
        # >= 5 lines with numbers → not a title slide
        dense_text = (
            "Q3 2025 revenue grew 25%\n"
            "ARR reached $240M milestone\n"
            "NRR stable at 120% level\n"
            "Customer count 12000 total\n"
            "Operating margin 15% achieved\n"
            "FCF $80M year to date"
        )
        pages = [_make_page(dense_text)]
        pdf = _make_pdf(pages)

        with patch("pdfplumber.open", return_value=pdf):
            html, _ = convert_presentation_to_html(Path("/fake/deck.pdf"))

        assert 'data-is-title="true"' not in html

    def test_only_first_page_can_have_title_attr(self) -> None:
        pages = [
            _make_page("ACME Corp"),  # sparse → title
            _make_page("ACME Corp"),  # sparse → but NOT first page
        ]
        pdf = _make_pdf(pages)

        with patch("pdfplumber.open", return_value=pdf):
            html, _ = convert_presentation_to_html(Path("/fake/deck.pdf"))

        # data-is-title should appear at most once (only on page 1)
        assert html.count('data-is-title="true"') <= 1


# ============================================================================
# Error handling
# ============================================================================


class TestConvertPresentationErrors:
    def test_raises_value_error_on_bad_pdf(self) -> None:
        with patch("pdfplumber.open", side_effect=Exception("corrupt file")):
            with pytest.raises(ValueError, match="Failed to open PDF"):
                convert_presentation_to_html(Path("/fake/bad.pdf"))

    def test_page_text_failure_logged_as_warning(self, caplog: pytest.LogCaptureFixture) -> None:
        import logging

        page = _make_page()
        page.extract_text.side_effect = Exception("parse error")
        page.extract_tables.return_value = []
        page.images = []
        pdf = _make_pdf([page])

        with patch("pdfplumber.open", return_value=pdf):
            with caplog.at_level(logging.WARNING):
                html, _ = convert_presentation_to_html(Path("/fake/deck.pdf"))

        # Should still produce a section (with empty page comment)
        assert 'data-section-type="presentation_slide"' in html
        assert "<!-- empty page -->" in html

    def test_page_table_failure_logged_as_warning(self, caplog: pytest.LogCaptureFixture) -> None:
        import logging

        page = _make_page("Some text")
        page.extract_tables.side_effect = Exception("table parse error")
        page.images = []
        pdf = _make_pdf([page])

        with patch("pdfplumber.open", return_value=pdf):
            with caplog.at_level(logging.WARNING):
                html, _ = convert_presentation_to_html(Path("/fake/deck.pdf"))

        # Text should still appear despite table failure
        assert "<p>Some text</p>" in html


# ============================================================================
# PresentationMetadata
# ============================================================================


class TestPresentationMetadata:
    def test_default_source_type(self) -> None:
        meta = PresentationMetadata()
        assert meta.source_type == DocumentType.PRESENTATION

    def test_fields_settable(self) -> None:
        meta = PresentationMetadata(
            title="My Deck",
            source_id="/path/to/deck.pdf",
            page_count=42,
        )
        assert meta.title == "My Deck"
        assert meta.source_id == "/path/to/deck.pdf"
        assert meta.page_count == 42
