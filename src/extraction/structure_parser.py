"""
Structure-preserving HTML parser for DOM-to-text position mapping.

This module provides StructureParser, which parses HTML while preserving
DOM structure information. It enables accurate mapping between text positions
and HTML elements, critical for table-aware extraction.

Key Features:
- Preserves table row and cell boundaries during HTML-to-text conversion
- Maps text positions back to source DOM elements
- Checks if two text positions are in the same table row or cell
- Provides structured access to row and cell boundaries

Usage:
    >>> from src.extraction.structure_parser import StructureParser
    >>>
    >>> html = '<table><tr><td>Revenue</td><td>100</td></tr></table>'
    >>> parser = StructureParser(html)
    >>> text = parser.get_text()
    >>> print(text)
    'Revenue [CELL] 100 [ROW] '
    >>>
    >>> # Check if positions are in same row
    >>> pos_revenue = text.find('Revenue')
    >>> pos_100 = text.find('100')
    >>> parser.are_in_same_row(pos_revenue, pos_100)  # True
    >>>
    >>> # Get DOM element at position
    >>> elem = parser.get_element_at_position(pos_100)
    >>> elem.name  # 'td'

Design:
- TextSpan: Represents a span of text with position mapping to DOM element
- RowSpan: Represents a table row with its constituent cells
- StructureParser: Main parser class with position mapping APIs

This module is a foundation for EA-2 (unified CandidateDetector) and EA-3
(table-aware context extraction). It does NOT modify existing extraction
pipelines - that integration happens in future tasks.
"""

import re
from dataclasses import dataclass, field
from typing import Optional

from bs4 import BeautifulSoup, Tag


@dataclass
class TextSpan:
    """A span of text with its position in both text and DOM.

    Attributes:
        text: The actual text content
        text_start: Start position in the output text
        text_end: End position in the output text (exclusive)
        dom_element: Reference to the source DOM element (Tag object)
        element_type: Type of element ('td', 'th', 'p', 'span', 'text', etc.)
    """

    text: str
    text_start: int
    text_end: int
    dom_element: Optional[Tag] = None
    element_type: str = "text"


@dataclass
class RowSpan:
    """A table row with position information.

    Attributes:
        cells: List of TextSpans representing cells in this row
        row_start: Start position of row in output text
        row_end: End position of row in output text (exclusive)
    """

    cells: list[TextSpan] = field(default_factory=list)
    row_start: int = 0
    row_end: int = 0


class StructureParser:
    """Parse HTML while preserving DOM structure for position mapping.

    This parser converts HTML to text while maintaining structural information,
    allowing text positions to be mapped back to their source DOM elements.

    Special markers are inserted to preserve structure:
    - [CELL] separates table cells
    - [ROW] separates table rows

    Attributes:
        html: Original HTML string
        soup: BeautifulSoup parse tree
        CELL_MARKER: Marker inserted between table cells
        ROW_MARKER: Marker inserted between table rows
    """

    CELL_MARKER = " [CELL] "
    ROW_MARKER = " [ROW] "

    def __init__(self, html: str):
        """Initialize parser and parse the HTML.

        Args:
            html: HTML string to parse
        """
        self.html = html
        self.soup = BeautifulSoup(html, "html.parser")
        self._spans: list[TextSpan] = []
        self._rows: list[RowSpan] = []
        self._text = ""
        self._parse()

    def _parse(self) -> None:
        """Parse HTML and build position mappings."""
        # Find all tables
        tables = self.soup.find_all("table")

        if tables:
            self._parse_tables(tables)
        else:
            self._parse_non_table()

    def _parse_tables(self, tables: list[Tag]) -> None:
        """Parse table elements with structure preservation.

        Args:
            tables: List of table Tag elements from BeautifulSoup
        """
        current_pos = 0
        text_parts: list[str] = []

        for table in tables:
            # Get direct child rows (don't recurse into nested tables)
            for tr in table.find_all("tr"):
                row_start = current_pos
                row = RowSpan(row_start=row_start)

                # Get direct cell children (td or th)
                cells = tr.find_all(["td", "th"], recursive=False)

                for i, cell in enumerate(cells):
                    cell_text = self._normalize_text(cell.get_text())
                    cell_start = current_pos

                    span = TextSpan(
                        text=cell_text,
                        text_start=cell_start,
                        text_end=cell_start + len(cell_text),
                        dom_element=cell,
                        element_type=cell.name,
                    )
                    self._spans.append(span)
                    row.cells.append(span)

                    text_parts.append(cell_text)
                    current_pos += len(cell_text)

                    # Add cell marker between cells (but not after last cell)
                    if i < len(cells) - 1:
                        text_parts.append(self.CELL_MARKER)
                        current_pos += len(self.CELL_MARKER)

                row.row_end = current_pos
                self._rows.append(row)

                # Add row marker after each row
                text_parts.append(self.ROW_MARKER)
                current_pos += len(self.ROW_MARKER)

        self._text = "".join(text_parts)

    def _parse_non_table(self) -> None:
        """Parse non-table HTML (paragraphs, divs, etc.).

        For non-table content, we extract text from block elements
        and create TextSpans for position tracking.
        """
        current_pos = 0
        text_parts: list[str] = []

        # Find all block-level elements
        block_elements = self.soup.find_all(["p", "div", "span", "h1", "h2", "h3", "h4", "h5", "h6"])

        if not block_elements:
            # No block elements - just extract all text
            text = self._normalize_text(self.soup.get_text())
            if text:  # Only create span if there's actual text
                span = TextSpan(
                    text=text,
                    text_start=0,
                    text_end=len(text),
                    dom_element=None,
                    element_type="text",
                )
                self._spans.append(span)
            self._text = text
            return

        # Process block elements
        for elem in block_elements:
            elem_text = self._normalize_text(elem.get_text())

            if not elem_text:
                continue

            elem_start = current_pos
            span = TextSpan(
                text=elem_text,
                text_start=elem_start,
                text_end=elem_start + len(elem_text),
                dom_element=elem,
                element_type=elem.name,
            )
            self._spans.append(span)

            text_parts.append(elem_text)
            current_pos += len(elem_text)

            # Add space between block elements
            text_parts.append(" ")
            current_pos += 1

        self._text = "".join(text_parts)

    def _normalize_text(self, text: str) -> str:
        """Normalize text content (remove excess whitespace).

        Args:
            text: Raw text to normalize

        Returns:
            Normalized text with single spaces
        """
        # Replace multiple whitespace with single space
        text = re.sub(r"\s+", " ", text)
        return text.strip()

    def get_text(self) -> str:
        """Return the extracted text with structure markers.

        Returns:
            Normalized text with [CELL] and [ROW] markers for tables
        """
        return self._text

    def get_element_at_position(self, text_pos: int) -> Optional[Tag]:
        """Get DOM element containing the given text position.

        Args:
            text_pos: Position in the output text

        Returns:
            Tag object containing this position, or None if not found
        """
        for span in self._spans:
            if span.text_start <= text_pos < span.text_end:
                return span.dom_element
        return None

    def are_in_same_row(self, pos1: int, pos2: int) -> bool:
        """Check if two text positions are in the same table row.

        Args:
            pos1: First text position
            pos2: Second text position

        Returns:
            True if both positions are in the same row, False otherwise.
            Returns False if no table structure exists.
        """
        if not self._rows:
            # No table structure - cannot be in same row
            return False

        for row in self._rows:
            if row.row_start <= pos1 < row.row_end:
                return row.row_start <= pos2 < row.row_end

        return False

    def are_in_same_cell(self, pos1: int, pos2: int) -> bool:
        """Check if two text positions are in the same table cell.

        Args:
            pos1: First text position
            pos2: Second text position

        Returns:
            True if both positions are in the same cell, False otherwise
        """
        for span in self._spans:
            if span.text_start <= pos1 < span.text_end:
                return span.text_start <= pos2 < span.text_end

        return False

    def get_row_boundaries(self) -> list[tuple[int, int]]:
        """Return (start, end) positions for each table row.

        Returns:
            List of (row_start, row_end) tuples
        """
        return [(row.row_start, row.row_end) for row in self._rows]

    def get_cell_boundaries(self) -> list[tuple[int, int]]:
        """Return (start, end) positions for each cell.

        Returns:
            List of (cell_start, cell_end) tuples
        """
        return [(span.text_start, span.text_end) for span in self._spans]

    def get_row_at_position(self, position: int) -> Optional[RowSpan]:
        """Get the table row containing the given position.

        Args:
            position: Text position

        Returns:
            RowSpan containing this position, or None if not found
        """
        for row in self._rows:
            if row.row_start <= position < row.row_end:
                return row
        return None

    def get_span_at_position(self, position: int) -> Optional[TextSpan]:
        """Get the text span containing the given position.

        Args:
            position: Text position

        Returns:
            TextSpan containing this position, or None if not found
        """
        for span in self._spans:
            if span.text_start <= position < span.text_end:
                return span
        return None

    def is_table(self) -> bool:
        """Check if the HTML contains table structure.

        Returns:
            True if tables were parsed, False otherwise
        """
        return len(self._rows) > 0
