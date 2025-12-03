"""
HTML Segmenter - Parse filing HTML into semantic segments.

This module breaks down SEC filing HTML documents into atomic source segments
(paragraphs, tables, footnotes) that serve as the basis for metric extraction.
"""

import logging
import re
from pathlib import Path
from typing import List, Optional, Tuple
from bs4 import BeautifulSoup, Tag

from .models import SourceSegment

logger = logging.getLogger(__name__)


class HTMLSegmenter:
    """
    Segment SEC filing HTML into source_segments for metric extraction.

    Segments types:
        - paragraph: Text paragraphs
        - table: HTML tables
        - footnote: Footnotes and endnotes
        - definition_block: Detected definition sections
        - methodology_block: Detected calculation methodology sections
        - other: Fallback for other content
    """

    # Minimum text length for a segment to be included
    MIN_SEGMENT_LENGTH = 50

    # Maximum text length for a single segment
    MAX_SEGMENT_LENGTH = 10000

    # Patterns that indicate definition or methodology blocks
    DEFINITION_PATTERNS = [
        r"\b(we\s+define|defined\s+as|definition\s+of|refers\s+to)\b",
        r"\b(means|meaning|metric\s+definitions)\b",
    ]

    METHODOLOGY_PATTERNS = [
        r"\b(calculated\s+as|calculated\s+by|calculation|computed\s+as)\b",
        r"\b(determined\s+by|formula|methodology)\b",
    ]

    def __init__(
        self, min_length: int = MIN_SEGMENT_LENGTH, max_length: int = MAX_SEGMENT_LENGTH
    ):
        """
        Initialize the HTML segmenter.

        Args:
            min_length: Minimum text length for segments
            max_length: Maximum text length for segments
        """
        self.min_length = min_length
        self.max_length = max_length

    def segment_filing(self, filing_id: int, html_path: str) -> List[SourceSegment]:
        """
        Parse filing HTML and return list of source segments.

        Args:
            filing_id: Database filing ID
            html_path: Path to HTML file

        Returns:
            List of SourceSegment objects (not yet inserted to DB)
        """
        logger.info(f"Segmenting filing {filing_id} from {html_path}")

        # Read HTML file
        html_content = self._read_html_file(html_path)
        if not html_content:
            logger.warning(f"Empty HTML content for filing {filing_id}")
            return []

        # Parse with BeautifulSoup
        soup = BeautifulSoup(html_content, "html.parser")

        # Extract segments
        segments = []
        sequence_index = 0

        # Find the main content area (usually in <BODY> or after <TEXT> tag)
        main_content = self._find_main_content(soup)
        if not main_content:
            logger.warning(f"Could not find main content in filing {filing_id}")
            return []

        # Extract all segments
        for element in main_content.find_all(["p", "table", "div"], recursive=True):
            # Skip if element is nested inside a table (we'll capture the whole table)
            if element.name == "p" and element.find_parent("table"):
                continue

            segment = self._extract_segment(element, filing_id, sequence_index)
            if segment:
                segments.append(segment)
                sequence_index += 1

        logger.info(f"Extracted {len(segments)} segments from filing {filing_id}")
        return segments

    def _read_html_file(self, html_path: str) -> Optional[str]:
        """Read HTML file with proper encoding handling."""
        try:
            path = Path(html_path)
            if not path.exists():
                logger.error(f"HTML file not found: {html_path}")
                return None

            # Try UTF-8 first, fall back to latin-1
            try:
                return path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                logger.warning(f"UTF-8 decode failed, trying latin-1: {html_path}")
                return path.read_text(encoding="latin-1")

        except Exception as e:
            logger.error(f"Error reading HTML file {html_path}: {e}")
            return None

    def _find_main_content(self, soup: BeautifulSoup) -> Optional[Tag]:
        """
        Find the main content area of the filing.

        SEC filings may have different structures:
        - SGML format: <DOCUMENT><TEXT><HTML>...</HTML></TEXT></DOCUMENT>
        - Modern HTML: <!DOCTYPE html><HTML>...</HTML>
        """
        # Try to find <TEXT> tag (SGML format)
        text_tag = soup.find("text")
        if text_tag:
            return text_tag

        # Fall back to <BODY> tag
        body_tag = soup.find("body")
        if body_tag:
            return body_tag

        # Last resort: use the whole soup
        return soup

    def _extract_segment(
        self, element: Tag, filing_id: int, sequence_index: int
    ) -> Optional[SourceSegment]:
        """
        Extract a single segment from an HTML element.

        Args:
            element: BeautifulSoup Tag element
            filing_id: Database filing ID
            sequence_index: Sequence index for this segment

        Returns:
            SourceSegment object or None if segment should be skipped
        """
        # Determine segment type
        segment_type = self._get_segment_type(element)

        # Extract text content
        raw_text = self._normalize_text(element.get_text())

        # Skip segments that are too short
        if len(raw_text) < self.min_length:
            return None

        # Truncate segments that are too long
        if len(raw_text) > self.max_length:
            logger.debug(
                f"Truncating segment from {len(raw_text)} to {self.max_length} chars"
            )
            raw_text = raw_text[: self.max_length]

        # Extract raw HTML (limited to avoid huge storage)
        raw_html = str(element)[: self.max_length]

        # Extract section path and heading
        section_path, section_heading = self._extract_section_info(element)

        # Build segment
        segment = SourceSegment(
            filing_id=filing_id,
            segment_type=segment_type,
            section_path=section_path,
            section_heading=section_heading,
            sequence_index=sequence_index,
            raw_text=raw_text,
            raw_html=raw_html,
        )

        return segment

    def _get_segment_type(self, element: Tag) -> str:
        """Determine segment type from HTML element."""
        if element.name == "table":
            return "table"

        # Check for footnote indicators
        if self._is_footnote(element):
            return "footnote"

        # Check for definition blocks
        text = element.get_text()
        if self._matches_patterns(text, self.DEFINITION_PATTERNS):
            return "definition_block"

        # Check for methodology blocks
        if self._matches_patterns(text, self.METHODOLOGY_PATTERNS):
            return "methodology_block"

        # Default to paragraph
        return "paragraph"

    def _is_footnote(self, element: Tag) -> bool:
        """Check if element is a footnote."""
        # Check for common footnote class names
        classes = element.get("class", [])
        footnote_classes = ["footnote", "endnote", "fn", "note"]

        for cls in classes:
            if any(fn_class in str(cls).lower() for fn_class in footnote_classes):
                return True

        # Check for footnote IDs
        element_id = element.get("id", "")
        if "footnote" in str(element_id).lower() or "fn" in str(element_id).lower():
            return True

        return False

    def _matches_patterns(self, text: str, patterns: List[str]) -> bool:
        """Check if text matches any of the given regex patterns."""
        text_lower = text.lower()
        for pattern in patterns:
            if re.search(pattern, text_lower, re.IGNORECASE):
                return True
        return False

    def _normalize_text(self, text: str) -> str:
        """
        Clean and normalize text content.

        - Remove excess whitespace
        - Normalize line breaks
        - Decode HTML entities (handled by BeautifulSoup)
        """
        # Replace multiple whitespace with single space
        text = re.sub(r"\s+", " ", text)

        # Strip leading/trailing whitespace
        text = text.strip()

        return text

    def _extract_section_info(
        self, element: Tag
    ) -> Tuple[Optional[str], Optional[str]]:
        """
        Extract section path and heading from element's position in DOM.

        Traverses up the DOM tree to find heading tags (h1-h6) to build
        a hierarchical section path.

        Args:
            element: BeautifulSoup element

        Returns:
            (section_path, section_heading) tuple

        Example:
            section_path: "Item 1. Business > Customers"
            section_heading: "Customers"
        """
        headings = []
        current = element

        # Traverse up the tree looking for headings
        while current:
            # Look for heading elements before this element
            for sibling in current.find_all_previous(
                ["h1", "h2", "h3", "h4", "h5", "h6"]
            ):
                heading_text = self._normalize_text(sibling.get_text())
                if heading_text and heading_text not in headings:
                    headings.insert(0, heading_text)
                    # Only take the most recent heading at each level
                    break

            # Move up one level
            current = current.parent
            if current and current.name in ["html", "body", "text"]:
                break

        if not headings:
            return None, None

        # Build section path from headings
        section_path = " > ".join(headings)
        section_heading = headings[-1] if headings else None

        return section_path, section_heading

    def extract_section_path(self, element: Tag) -> str:
        """
        Build hierarchical section path from HTML structure.

        Public method for testing and external use.
        """
        section_path, _ = self._extract_section_info(element)
        return section_path or ""

    def normalize_text(self, raw_html: str) -> str:
        """
        Clean and normalize text content.

        Public method for testing and external use.
        """
        soup = BeautifulSoup(raw_html, "html.parser")
        text = soup.get_text()
        return self._normalize_text(text)


# Convenience function
def segment_filing_html(filing_id: int, html_path: str) -> List[SourceSegment]:
    """
    Convenience function to segment a filing HTML file.

    Args:
        filing_id: Database filing ID
        html_path: Path to HTML file

    Returns:
        List of SourceSegment objects
    """
    segmenter = HTMLSegmenter()
    return segmenter.segment_filing(filing_id, html_path)
