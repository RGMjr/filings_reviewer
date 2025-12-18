"""
Table Structure Analysis - Parse HTML tables to understand row/column structure.

This module provides functionality to parse HTML table structure and map
character positions in extracted text back to their table rows. This is
critical for preventing false matches where a keyword in one row gets
associated with a number from a different row.

Example Problem:
    Table HTML:
        <tr><td>Cost of revenues</td><td>450,069</td></tr>
        <tr><td>Gross profit</td><td>262,431</td></tr>

    Extracted text:
        "Cost of revenues 450,069 Gross profit 262,431"

    Without row awareness: "Gross profit" (60 chars from 450,069) gets matched!
    With row awareness: Rejected because they're in different rows.

Usage:
    >>> from src.review.table_structure import TableRowParser
    >>>
    >>> html = '<table><tr><td>Revenue</td><td>100</td></tr></table>'
    >>> text = "Revenue 100"
    >>>
    >>> parser = TableRowParser(html, text)
    >>> rows = parser.get_rows()
    >>>
    >>> # Check if two positions are in the same row
    >>> same_row = parser.are_in_same_row(pos1=0, pos2=8)
"""

import logging
import re
from dataclasses import dataclass
from typing import List, Optional, Tuple

from bs4 import BeautifulSoup, Tag

logger = logging.getLogger(__name__)


@dataclass
class TableRow:
    """Represents a single table row with text position boundaries."""

    row_index: int  # 0-based row number
    text_start: int  # Character position where row text starts in extracted text
    text_end: int  # Character position where row text ends
    row_text: str  # The actual text content of this row
    has_header: bool  # Whether this row contains a row header (first cell)
    header_text: Optional[str] = None  # Text content of the row header (first cell)
    header_start: Optional[int] = None  # Start position of header text
    header_end: Optional[int] = None  # End position of header text


class TableRowParser:
    """
    Parse HTML table structure to identify row boundaries in extracted text.

    This allows us to check whether two character positions (e.g., a number
    and a keyword) are in the same table row, preventing cross-row matches.
    """

    def __init__(self, html: str, extracted_text: str):
        """
        Initialize parser with table HTML and its extracted text.

        Args:
            html: Raw HTML string (may contain a table)
            extracted_text: Text extracted from the HTML (e.g., via .get_text())
        """
        self.html = html
        self.extracted_text = extracted_text
        self.rows: Optional[List[TableRow]] = None
        self._parse_rows()

    def _parse_rows(self) -> None:
        """Parse table structure and map row boundaries to text positions."""
        self.rows = []

        # Check if HTML contains a table
        soup = BeautifulSoup(self.html, 'html.parser')
        table = soup.find('table')

        if not table:
            # Not a table - treat entire text as single "row"
            logger.debug("No table found in HTML, treating as single row")
            self.rows.append(TableRow(
                row_index=0,
                text_start=0,
                text_end=len(self.extracted_text),
                row_text=self.extracted_text,
                has_header=False
            ))
            return

        # Find all table rows
        tr_elements = table.find_all('tr', recursive=True)

        if not tr_elements:
            logger.debug("Table found but no <tr> elements, treating as single row")
            self.rows.append(TableRow(
                row_index=0,
                text_start=0,
                text_end=len(self.extracted_text),
                row_text=self.extracted_text,
                has_header=False
            ))
            return

        # Track current position in extracted text
        current_pos = 0

        for row_idx, tr in enumerate(tr_elements):
            # Extract text from this row
            row_text = self._normalize_text(tr.get_text())

            if not row_text.strip():
                # Skip empty rows
                continue

            # Find where this row's text appears in the extracted text
            # We search from current_pos forward to handle duplicate text
            row_start = self.extracted_text.find(row_text, current_pos)

            if row_start == -1:
                # Row text not found in extracted text (might be normalized differently)
                # Try a more flexible search by looking for key parts
                row_start = self._find_row_approximate(row_text, current_pos)

            if row_start == -1:
                logger.debug(f"Could not locate row {row_idx} text in extracted text")
                continue

            row_end = row_start + len(row_text)

            # Check if row has a header cell (th or first td with text)
            cells = tr.find_all(['th', 'td'])
            has_header = False
            header_text = None
            header_start = None
            header_end = None

            if cells:
                first_cell_text = self._normalize_text(cells[0].get_text()).strip()
                has_header = bool(first_cell_text and not first_cell_text.replace(',', '').replace('.', '').replace('(', '').replace(')', '').replace('-', '').replace('%', '').replace('$', '').isdigit())

                if has_header:
                    header_text = first_cell_text
                    # Find position of header text within the row text
                    # It should be at or near the start of the row
                    header_offset = row_text.find(header_text)
                    if header_offset != -1:
                        header_start = row_start + header_offset
                        header_end = header_start + len(header_text)

            self.rows.append(TableRow(
                row_index=row_idx,
                text_start=row_start,
                text_end=row_end,
                row_text=row_text,
                has_header=has_header,
                header_text=header_text,
                header_start=header_start,
                header_end=header_end
            ))

            current_pos = row_end

        logger.debug(f"Parsed {len(self.rows)} table rows")

    def _normalize_text(self, text: str) -> str:
        """Normalize text the same way as HTMLSegmenter does."""
        # Collapse multiple whitespace into single space
        text = re.sub(r'\s+', ' ', text)
        return text.strip()

    def _find_row_approximate(self, row_text: str, start_pos: int) -> int:
        """
        Try to find row text approximately by looking for distinctive parts.

        This handles cases where normalization differences prevent exact match.
        """
        # Try to find the first few distinctive words
        words = row_text.split()[:3]  # First 3 words
        if not words:
            return -1

        search_pattern = r'\s+'.join(re.escape(w) for w in words)
        match = re.search(search_pattern, self.extracted_text[start_pos:])

        if match:
            return start_pos + match.start()

        return -1

    def get_row_at_position(self, position: int) -> Optional[TableRow]:
        """
        Get the table row that contains the given character position.

        Args:
            position: Character position in extracted text

        Returns:
            TableRow containing this position, or None if not found
        """
        if not self.rows:
            return None

        for row in self.rows:
            if row.text_start <= position < row.text_end:
                return row

        return None

    def are_in_same_row(self, pos1: int, pos2: int) -> bool:
        """
        Check if two character positions are in the same table row.

        Args:
            pos1: First character position
            pos2: Second character position

        Returns:
            True if both positions are in the same row, False otherwise
            Returns True if no table structure detected (single "row")
        """
        row1 = self.get_row_at_position(pos1)
        row2 = self.get_row_at_position(pos2)

        if row1 is None or row2 is None:
            # If we can't determine row, err on the side of allowing the match
            # This handles edge cases in text position mapping
            logger.debug(f"Could not determine row for positions {pos1} and/or {pos2}")
            return True

        return row1.row_index == row2.row_index

    def get_rows(self) -> List[TableRow]:
        """Get list of all parsed table rows."""
        return self.rows or []

    def is_table(self) -> bool:
        """Check if the HTML contains a table structure."""
        return '<table' in self.html.lower() and len(self.rows or []) > 1

    def is_row_heading(self, position: int) -> bool:
        """
        Check if a character position is within a row heading (first cell).

        This is useful for prioritizing row headings over other keywords when
        multiple matches are found. Row headings are typically the most specific
        and relevant labels for values in the same row.

        Args:
            position: Character position in extracted text

        Returns:
            True if position is within a row heading, False otherwise

        Example:
            >>> parser = TableRowParser(html, text)
            >>> # Check if "Gross profit" keyword position is a row heading
            >>> if parser.is_row_heading(keyword_pos):
            ...     # Give this keyword priority
        """
        if not self.rows:
            return False

        for row in self.rows:
            if row.header_start is not None and row.header_end is not None:
                if row.header_start <= position < row.header_end:
                    return True

        return False
