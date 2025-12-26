"""
Table-aware context extraction for metric values.

This module provides the ContextExtractor class which extracts context around
metric values while respecting table structure. It uses StructureParser (EA-1)
to provide clean, row-aware context extraction for table data.

Key Features:
- Table-aware context extraction using row boundaries
- Clean output without [CELL] and [ROW] markers
- Column and row header extraction for tables
- Fallback to character-based context for paragraphs
- Configurable context window sizes

Usage:
    >>> from src.extraction.context_extractor import ContextExtractor
    >>>
    >>> # Paragraph context
    >>> text = "Our company had 10 million daily active users as of December 31, 2024."
    >>> extractor = ContextExtractor(context_chars=50)
    >>> ctx = extractor.extract(text=text, position=16)
    >>> print(ctx.text)
    'company had 10 million daily active users'
    >>>
    >>> # Table context
    >>> table_html = '<table><tr><th>Metric</th><th>2024</th></tr>' \\
    ...              '<tr><td>Revenue</td><td>150</td></tr></table>'
    >>> table_text = 'Metric [CELL] 2024 [ROW] Revenue [CELL] 150 [ROW]'
    >>> ctx = extractor.extract(
    ...     text=table_text,
    ...     position=table_text.find('150'),
    ...     html=table_html,
    ...     segment_type='table'
    ... )
    >>> print(ctx.text)  # Clean output without markers
    'Revenue | 150'
    >>> print(ctx.row_header)
    'Revenue'
    >>> print(ctx.column_header)
    '2024'

This module is part of EA-3 (table-aware context extraction) and builds on
EA-1 (StructureParser). It does NOT integrate with existing extraction
pipelines yet - that will happen in future integration tasks.
"""

import re
from dataclasses import dataclass
from typing import Optional

from src.extraction.structure_parser import StructureParser


@dataclass
class ExtractedContext:
    """Context around an extracted value.

    Attributes:
        text: Clean context text without [CELL]/[ROW] markers
        row_text: Full row text for table values (includes markers)
        column_header: Column header from table's first row (if available)
        row_header: Row header from row's first cell (if available)
        position_start: Start position in original text
        position_end: End position in original text (exclusive)
    """

    text: str
    row_text: Optional[str] = None
    column_header: Optional[str] = None
    row_header: Optional[str] = None
    position_start: int = 0
    position_end: int = 0


class ContextExtractor:
    """Extract context around metric values with table awareness.

    This class provides context extraction that respects table structure
    when HTML is available, falling back to character-based windows for
    plain text or paragraphs.
    """

    # Regex patterns for cleaning markers
    CELL_MARKER_PATTERN = re.compile(r"\s*\[CELL\]\s*")
    ROW_MARKER_PATTERN = re.compile(r"\s*\[ROW\]\s*")

    def __init__(
        self,
        context_chars: int = 100,
        include_headers: bool = True,
    ):
        """Initialize the context extractor.

        Args:
            context_chars: Number of characters for context window (for paragraphs)
            include_headers: Whether to extract column/row headers for tables
        """
        self.context_chars = context_chars
        self.include_headers = include_headers

    def extract(
        self,
        text: str,
        position: int,
        html: Optional[str] = None,
        segment_type: str = "paragraph",
    ) -> ExtractedContext:
        """Extract context around a position in text.

        For table segments with HTML, uses row-based extraction with headers.
        For paragraphs or when HTML is unavailable, uses character-based windows.

        Args:
            text: Full text content (may include [CELL]/[ROW] markers)
            position: Character position of the value
            html: Optional HTML source for table-aware extraction
            segment_type: Type of segment ('paragraph' or 'table')

        Returns:
            ExtractedContext with clean, structured context
        """
        if not text:
            return ExtractedContext(text="", position_start=0, position_end=0)

        # Clamp position to valid range
        position = max(0, min(position, len(text) - 1))

        # Use table-aware extraction for tables with HTML
        if segment_type == "table" and html:
            try:
                parser = StructureParser(html)
                return self.extract_row_context(text, position, parser)
            except Exception:
                # Fall back to basic extraction on any error
                pass

        # Basic character-window extraction for paragraphs
        return self._extract_basic(text, position)

    def _extract_basic(self, text: str, position: int) -> ExtractedContext:
        """Extract context using a character-based window.

        Used for paragraphs or as fallback when table parsing fails.

        Args:
            text: Full text content
            position: Character position to center on

        Returns:
            ExtractedContext with character-window context
        """
        start = max(0, position - self.context_chars)
        end = min(len(text), position + self.context_chars)

        # Extend to word boundaries to avoid cutting words
        while start > 0 and text[start - 1].isalnum():
            start -= 1
        while end < len(text) and text[end].isalnum():
            end += 1

        context_text = text[start:end].strip()

        # Clean any markers that might be present
        context_text = self._clean_markers(context_text)

        return ExtractedContext(
            text=context_text,
            position_start=start,
            position_end=end,
        )

    def extract_row_context(
        self,
        text: str,
        position: int,
        parser: StructureParser,
    ) -> ExtractedContext:
        """Extract full row as context for table segments.

        Uses StructureParser to find the row containing the position,
        extracts the full row, and includes column/row headers if available.

        Args:
            text: Full text with [CELL]/[ROW] markers
            position: Character position of the value
            parser: StructureParser instance for this segment's HTML

        Returns:
            ExtractedContext with row-based context and headers
        """
        # Get the row containing this position
        row = parser.get_row_at_position(position)

        if row is None:
            # Position not in any row - fall back to basic extraction
            return self._extract_basic(text, position)

        # Extract full row text
        row_text = text[row.row_start : row.row_end]
        clean_text = self._clean_markers(row_text)

        # Initialize headers
        row_header: Optional[str] = None
        column_header: Optional[str] = None

        # Extract headers if requested
        if self.include_headers and row.cells:
            # Row header is the first cell of this row
            row_header = row.cells[0].text.strip()

            # Find which cell contains the position
            cell_index = None
            for i, cell in enumerate(row.cells):
                if cell.text_start <= position < cell.text_end:
                    cell_index = i
                    break

            # Get column header from first row
            if cell_index is not None and parser._rows:
                first_row = parser._rows[0]
                if cell_index < len(first_row.cells):
                    column_header = first_row.cells[cell_index].text.strip()

        return ExtractedContext(
            text=clean_text,
            row_text=row_text,
            row_header=row_header,
            column_header=column_header,
            position_start=row.row_start,
            position_end=row.row_end,
        )

    def _clean_markers(self, text: str) -> str:
        """Remove [CELL] and [ROW] markers from text.

        Replaces [CELL] with pipe separators and removes [ROW] markers,
        then normalizes whitespace.

        Args:
            text: Text possibly containing markers

        Returns:
            Cleaned text with normalized whitespace
        """
        # Replace [CELL] with pipe separator
        text = self.CELL_MARKER_PATTERN.sub(" | ", text)
        # Remove [ROW] markers
        text = self.ROW_MARKER_PATTERN.sub("", text)
        # Normalize whitespace
        return " ".join(text.split())

    def format_table_context(
        self,
        row_text: str,
        column_header: Optional[str] = None,
        row_header: Optional[str] = None,
    ) -> str:
        """Format table context for display with headers.

        Combines headers and row text into a readable format.

        Args:
            row_text: The row text (with or without markers)
            column_header: Optional column header to prepend
            row_header: Optional row header to prepend

        Returns:
            Formatted context string
        """
        parts = []

        if column_header:
            parts.append(f"[{column_header}]")

        if row_header:
            parts.append(f"{row_header}:")

        parts.append(self._clean_markers(row_text))

        return " ".join(parts)
