"""
Parse table row boundaries from [ROW]/[CELL] markers in pre-marked text.

This module provides MarkerRowParser, a lightweight parser for text that
already contains structural markers from the V2 ingestion stage. Unlike
TableRowParser which parses HTML, this parser directly uses the markers to
identify row boundaries.

Marker format (from the V2 ingestion stage):
    - Cells separated by: " [CELL] "
    - Rows separated by: " [ROW] "
    - First row has no leading [ROW] marker

Example:
    >>> from src.review.marker_row_parser import MarkerRowParser
    >>>
    >>> text = "Paid Customers [CELL] 37,000 [ROW] Revenue [CELL] $100M"
    >>> parser = MarkerRowParser(text)
    >>>
    >>> # Check if positions are in same row
    >>> pos_paid = text.find("Paid Customers")
    >>> pos_37k = text.find("37,000")
    >>> pos_revenue = text.find("Revenue")
    >>>
    >>> parser.are_in_same_row(pos_paid, pos_37k)  # True - same row
    >>> parser.are_in_same_row(pos_paid, pos_revenue)  # False - different rows

This module is used by CandidateGenerator when segment text contains markers,
providing accurate row boundary detection for keyword matching.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class MarkerRow:
    """A table row parsed from markers.

    Attributes:
        row_index: 0-based row number
        text_start: Character position where row starts in original text
        text_end: Character position where row ends (exclusive)
        row_text: Actual text content of this row
        header_text: Text of row header (first cell), if non-numeric
        header_start: Start position of header in original text
        header_end: End position of header in original text
    """

    row_index: int
    text_start: int
    text_end: int
    row_text: str
    header_text: str | None = None
    header_start: int | None = None
    header_end: int | None = None


class MarkerRowParser:
    """Parse row boundaries from [ROW]/[CELL] markers in text.

    This is a lightweight parser for text that already contains structural
    markers from the V2 ingestion stage. It does NOT parse HTML - just splits
    on markers.

    Attributes:
        text: Original marked text
        ROW_MARKER: Marker string between rows (" [ROW] ")
        CELL_MARKER: Marker string between cells (" [CELL] ")
    """

    ROW_MARKER: str = " [ROW] "
    CELL_MARKER: str = " [CELL] "

    def __init__(self, marked_text: str) -> None:
        """Initialize parser with marked text.

        Args:
            marked_text: Text containing [ROW]/[CELL] markers
        """
        self.text = marked_text
        self._rows: list[MarkerRow] = []
        self._parse()

    def _parse(self) -> None:
        """Parse row boundaries from markers."""
        if not self.text.strip():
            logger.debug("Empty text provided, no rows to parse")
            return

        # Split text by [ROW] markers
        # Note: rows are JOINED by [ROW], not prefixed
        row_texts = self.text.split(self.ROW_MARKER)

        current_pos = 0
        row_marker_len = len(self.ROW_MARKER)

        for row_idx, row_text in enumerate(row_texts):
            if not row_text.strip():
                # Skip empty rows but account for marker length
                if row_idx > 0:
                    current_pos += row_marker_len
                continue

            row_start = current_pos
            row_end = current_pos + len(row_text)

            # Extract header (first cell) if non-numeric
            header_text, header_start, header_end = self._extract_header(
                row_text, row_start
            )

            self._rows.append(
                MarkerRow(
                    row_index=len(self._rows),  # Use actual parsed row count
                    text_start=row_start,
                    text_end=row_end,
                    row_text=row_text,
                    header_text=header_text,
                    header_start=header_start,
                    header_end=header_end,
                )
            )

            # Move past row text
            current_pos = row_end
            # Add marker length if not last row
            if row_idx < len(row_texts) - 1:
                current_pos += row_marker_len

        logger.debug(f"Parsed {len(self._rows)} rows from markers")

    def _extract_header(
        self, row_text: str, row_start: int
    ) -> tuple[str | None, int | None, int | None]:
        """Extract header (first cell) if non-numeric.

        Args:
            row_text: Text content of the row
            row_start: Starting position of row in original text

        Returns:
            Tuple of (header_text, header_start, header_end) or (None, None, None)
        """
        # Header is text before first [CELL] marker
        if self.CELL_MARKER in row_text:
            cell_marker_pos = row_text.find(self.CELL_MARKER)
            header_text = row_text[:cell_marker_pos].strip()
        else:
            # Single-cell row: entire row is potential header
            header_text = row_text.strip()

        if not header_text:
            return None, None, None

        # Check if header is meaningful (not just numbers/punctuation)
        stripped = (
            header_text.replace(",", "")
            .replace(".", "")
            .replace("(", "")
            .replace(")", "")
            .replace("-", "")
            .replace("%", "")
            .replace("$", "")
            .replace(" ", "")
        )

        # If it's purely numeric, not a meaningful header
        if stripped.isdigit():
            return None, None, None

        # Find header position within the row
        header_offset = row_text.find(header_text)
        if header_offset == -1:
            return None, None, None

        header_start = row_start + header_offset
        header_end = header_start + len(header_text)

        return header_text, header_start, header_end

    def _get_row_at_position(self, position: int) -> MarkerRow | None:
        """Get the row containing the given position.

        Args:
            position: Character position in original text

        Returns:
            MarkerRow containing this position, or None if not found
        """
        for row in self._rows:
            if row.text_start <= position < row.text_end:
                return row
        return None

    def are_in_same_row(self, pos1: int, pos2: int) -> bool:
        """Check if two positions are in the same table row.

        Unlike TableRowParser which returns True when uncertain, this
        implementation is strict: if we can't determine the row for
        either position, we return False to prevent cross-row matches.

        Args:
            pos1: First character position
            pos2: Second character position

        Returns:
            True if both positions are in the same row, False otherwise
        """
        row1 = self._get_row_at_position(pos1)
        row2 = self._get_row_at_position(pos2)

        if row1 is None or row2 is None:
            # Strict: if can't determine, don't allow match
            logger.debug(
                f"Could not determine row for position(s): "
                f"pos1={pos1} -> {row1}, pos2={pos2} -> {row2}"
            )
            return False

        return row1.row_index == row2.row_index

    def is_row_heading(self, position: int) -> bool:
        """Check if a position is within a row heading (first cell).

        Row headings are the first cell in a row, if that cell contains
        non-numeric text. This is useful for prioritizing row headings
        over other keywords when multiple matches are found.

        Args:
            position: Character position in original text

        Returns:
            True if position is within a row heading, False otherwise
        """
        for row in self._rows:
            if row.header_start is not None and row.header_end is not None:
                if row.header_start <= position < row.header_end:
                    return True
        return False

    def is_table(self) -> bool:
        """Check if this represents a multi-row table.

        Returns:
            True if 2+ rows were parsed, False otherwise
        """
        return len(self._rows) > 1

    def get_rows(self) -> list[MarkerRow]:
        """Get all parsed rows.

        Returns:
            List of MarkerRow objects
        """
        return self._rows

    def get_row_at_position(self, position: int) -> MarkerRow | None:
        """Get the table row containing the given position.

        Public version of _get_row_at_position for external use.

        Args:
            position: Character position in original text

        Returns:
            MarkerRow containing this position, or None if not found
        """
        return self._get_row_at_position(position)
