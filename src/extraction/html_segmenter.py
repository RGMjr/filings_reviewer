"""
HTML Segmenter - Parse filing HTML into semantic segments.

This module breaks down SEC filing HTML documents into atomic source segments
(paragraphs, tables, footnotes) that serve as the basis for metric extraction.
"""

import logging
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from bs4 import BeautifulSoup, Tag

from .models import SourceSegment
from .validators import SegmentValidator
from .exceptions import ValidationError, EncodingError, HTMLParsingError

logger = logging.getLogger(__name__)


@dataclass
class SegmentationMetrics:
    """Metrics collected during HTML segmentation.

    Tracks performance, segment distribution, and warnings for observability.
    """

    filing_id: int
    total_segments: int = 0
    segment_counts_by_type: Dict[str, int] = field(default_factory=dict)
    total_text_length: int = 0
    parse_time_seconds: float = 0.0
    encoding_used: str = "utf-8"
    warnings: List[str] = field(default_factory=list)

    def avg_segment_length(self) -> float:
        """Calculate average segment text length."""
        if self.total_segments == 0:
            return 0.0
        return self.total_text_length / self.total_segments

    def summary(self) -> str:
        """Generate human-readable summary."""
        type_counts = ", ".join(
            f"{count} {seg_type}s" for seg_type, count in sorted(self.segment_counts_by_type.items())
        )
        return (
            f"{self.total_segments} segments in {self.parse_time_seconds:.3f}s "
            f"({type_counts}, avg length: {self.avg_segment_length():.0f} chars)"
        )


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

    # Metadata headings to skip when determining section context
    # These are navigation/structural elements, not content sections
    METADATA_HEADINGS = frozenset({
        'table of contents',
        'index',
        'cover page',
        'prospectus cover',
        'part of prospectus',
        'explanatory note',
        'forward-looking statements',
        'about this prospectus',
    })

    def __init__(
        self, min_length: int = MIN_SEGMENT_LENGTH, max_length: int = MAX_SEGMENT_LENGTH
    ):
        """
        Initialize the HTML segmenter.

        Args:
            min_length: Minimum text length for segments
            max_length: Maximum text length for segments
        """
        # Validate length parameters
        SegmentValidator.validate_min_max_length(min_length, max_length)
        self.min_length = min_length
        self.max_length = max_length
        self._metrics: Optional[SegmentationMetrics] = None

    def segment_filing(
        self, filing_id: int, html_path: str, raise_on_error: bool = False
    ) -> List[SourceSegment]:
        """
        Parse filing HTML and return list of source segments.

        Args:
            filing_id: Database filing ID
            html_path: Path to HTML file
            raise_on_error: If True, raise exceptions instead of returning empty list
                (default: False for backward compatibility)

        Returns:
            List of SourceSegment objects (not yet inserted to DB)

        Raises:
            ValidationError: If filing_id or html_path is invalid (only if raise_on_error=True)
            EncodingError: If file encoding cannot be determined (only if raise_on_error=True)
            HTMLParsingError: If HTML structure is invalid (only if raise_on_error=True)
        """
        start_time = time.time()

        # Validate inputs
        try:
            SegmentValidator.validate_filing_id(filing_id)
            validated_path = SegmentValidator.validate_html_path(html_path)
        except (ValidationError, FileNotFoundError, PermissionError) as e:
            if raise_on_error:
                raise
            logger.error(f"Validation failed for filing {filing_id}: {e}")
            return []

        logger.info(f"Segmenting filing {filing_id} from {html_path}")

        # Initialize metrics
        self._metrics = SegmentationMetrics(filing_id=filing_id)

        # Read HTML file with encoding detection
        try:
            html_content, encoding_used = self._read_html_file_with_encoding(str(validated_path))
            self._metrics.encoding_used = encoding_used
        except EncodingError as e:
            if raise_on_error:
                raise
            logger.error(f"Encoding error for filing {filing_id}: {e}")
            self._metrics.warnings.append(f"Encoding error: {e}")
            return []

        if not html_content:
            msg = f"Empty HTML content for filing {filing_id}"
            if raise_on_error:
                raise HTMLParsingError(msg, filing_id=filing_id, html_path=str(validated_path))
            logger.warning(msg)
            self._metrics.warnings.append("Empty HTML content")
            return []

        # Parse with BeautifulSoup
        try:
            soup = BeautifulSoup(html_content, "html.parser")
        except Exception as e:
            msg = f"Failed to parse HTML for filing {filing_id}: {e}"
            if raise_on_error:
                raise HTMLParsingError(msg, filing_id=filing_id, html_path=str(validated_path))
            logger.error(msg)
            self._metrics.warnings.append(f"Parse error: {e}")
            return []

        # Find the main content area (usually in <BODY> or after <TEXT> tag)
        main_content = self._find_main_content(soup)
        if not main_content:
            msg = f"Could not find main content in filing {filing_id}"
            if raise_on_error:
                raise HTMLParsingError(msg, filing_id=filing_id, html_path=str(validated_path))
            logger.warning(msg)
            self._metrics.warnings.append("No main content found")
            return []

        # Pre-build heading cache for O(1) lookups (performance optimization)
        self._heading_cache = self._build_heading_cache(main_content)

        # Extract segments
        segments = []
        sequence_index = 0

        # Extract all segments
        for element in main_content.find_all(["p", "table", "div"], recursive=True):
            # Skip if element is nested inside a table (we'll capture the whole table)
            if element.name == "p" and element.find_parent("table"):
                continue

            segment = self._extract_segment(element, filing_id, sequence_index)
            if segment:
                segments.append(segment)
                sequence_index += 1

                # Update metrics
                self._metrics.total_segments += 1
                self._metrics.total_text_length += len(segment.raw_text)
                seg_type = segment.segment_type
                self._metrics.segment_counts_by_type[seg_type] = (
                    self._metrics.segment_counts_by_type.get(seg_type, 0) + 1
                )

        # Clear cache after processing
        self._heading_cache = None

        # Finalize metrics
        self._metrics.parse_time_seconds = time.time() - start_time

        # Enhanced logging
        logger.info(f"Extracted {len(segments)} segments from filing {filing_id}: {self._metrics.summary()}")

        if self._metrics.warnings:
            logger.warning(f"Segmentation warnings for filing {filing_id}: {', '.join(self._metrics.warnings)}")

        return segments

    def _read_html_file_with_encoding(self, html_path: str) -> Tuple[Optional[str], str]:
        """Read HTML file with enhanced encoding detection and error reporting.

        Args:
            html_path: Path to HTML file

        Returns:
            Tuple of (content, encoding_used)

        Raises:
            EncodingError: If both UTF-8 and latin-1 encodings fail
        """
        path = Path(html_path)
        attempted_encodings = []

        # Try UTF-8 first
        try:
            content = path.read_text(encoding="utf-8")
            logger.debug(f"Successfully read {html_path} with UTF-8 encoding")
            return (content, "utf-8")
        except UnicodeDecodeError as e:
            attempted_encodings.append("utf-8")
            position = e.start if hasattr(e, 'start') else None
            logger.warning(
                f"UTF-8 decode failed for {html_path} at position {position}: {e}. "
                f"Trying latin-1 fallback..."
            )

        # Fall back to latin-1
        try:
            content = path.read_text(encoding="latin-1")
            logger.info(f"Successfully read {html_path} with latin-1 encoding (UTF-8 failed)")
            return (content, "latin-1")
        except UnicodeDecodeError as e:
            attempted_encodings.append("latin-1")
            position = e.start if hasattr(e, 'start') else None

            # Both encodings failed - raise EncodingError
            raise EncodingError(
                f"Failed to decode {html_path} with UTF-8 and latin-1 encodings. "
                f"File may have mixed or invalid encoding.",
                file_path=html_path,
                attempted_encodings=attempted_encodings,
                position=position
            )

    def _read_html_file(self, html_path: str) -> Optional[str]:
        """DEPRECATED: Use _read_html_file_with_encoding() instead.

        Kept for backward compatibility with external callers.
        """
        try:
            content, _ = self._read_html_file_with_encoding(html_path)
            return content
        except EncodingError:
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

    def _build_heading_cache(self, main_content: Tag) -> List[Tuple[int, str, str]]:
        """
        Pre-build a cache of all headings with their source line positions.

        This is a performance optimization to avoid O(n²) find_all_previous() calls.
        We traverse the document once and store headings with their positions,
        then use binary search for O(log n) lookups.

        Args:
            main_content: The main content area of the filing

        Returns:
            List of (source_position, heading_level, heading_text) tuples,
            sorted by source_position
        """
        headings = []

        for i, element in enumerate(main_content.descendants):
            if hasattr(element, 'name') and element.name in ['h1', 'h2', 'h3', 'h4', 'h5', 'h6']:
                heading_text = self._normalize_text(element.get_text())
                if heading_text:
                    # Store position, level (h1=1, h2=2, etc.), and text
                    level = int(element.name[1])
                    headings.append((i, level, heading_text))

        return headings

    def _get_section_from_cache(self, element: Tag) -> Tuple[Optional[str], Optional[str]]:
        """
        Get section info using find_previous, skipping metadata headings.

        For performance, we iterate through previous headings until we find
        a meaningful content section (not 'Table of Contents', 'Index', etc.).

        Args:
            element: BeautifulSoup element

        Returns:
            (section_path, section_heading) tuple
        """
        prev_heading = element.find_previous(['h1', 'h2', 'h3', 'h4', 'h5', 'h6'])

        while prev_heading:
            heading_text = self._normalize_text(prev_heading.get_text())
            if heading_text:
                # Skip metadata headings (Table of Contents, Index, etc.)
                if heading_text.lower() not in self.METADATA_HEADINGS:
                    return heading_text, heading_text
            # Keep searching backwards for a real content heading
            prev_heading = prev_heading.find_previous(['h1', 'h2', 'h3', 'h4', 'h5', 'h6'])

        return None, None

    def _extract_section_info(
        self, element: Tag
    ) -> Tuple[Optional[str], Optional[str]]:
        """
        Extract section path and heading from element's position in DOM.

        Uses pre-built heading cache for O(n) performance instead of O(n²).
        Skips metadata headings like 'Table of Contents'.

        Args:
            element: BeautifulSoup element

        Returns:
            (section_path, section_heading) tuple

        Example:
            section_path: "Item 1. Business > Customers"
            section_heading: "Customers"
        """
        # Use cache if available (set during segment_filing)
        if hasattr(self, '_heading_cache') and self._heading_cache is not None:
            return self._get_section_from_cache(element)

        # Fallback: iterate through previous headings, skipping metadata
        prev_heading = element.find_previous(['h1', 'h2', 'h3', 'h4', 'h5', 'h6'])
        while prev_heading:
            heading_text = self._normalize_text(prev_heading.get_text())
            if heading_text and heading_text.lower() not in self.METADATA_HEADINGS:
                return heading_text, heading_text
            prev_heading = prev_heading.find_previous(['h1', 'h2', 'h3', 'h4', 'h5', 'h6'])

        return None, None

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

    def get_metrics(self) -> Optional[SegmentationMetrics]:
        """Get metrics from most recent segmentation.

        Returns:
            SegmentationMetrics object or None if no segmentation has been performed

        Example:
            segmenter = HTMLSegmenter()
            segments = segmenter.segment_filing(1, "path/to/filing.html")
            metrics = segmenter.get_metrics()
            print(f"Processed {metrics.total_segments} segments in {metrics.parse_time_seconds:.2f}s")
        """
        return self._metrics


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
