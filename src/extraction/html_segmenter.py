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
from src.review.boundary_detection import BoundaryDetector

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

    # Maximum text length for a single text segment
    MAX_SEGMENT_LENGTH = 10000

    # Maximum text length for tables (higher limit to preserve data integrity)
    TABLE_MAX_LENGTH = 25000

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

    # Definition start patterns - detect when a segment begins a definition
    # that may continue into subsequent segments
    DEFINITION_START_PATTERNS = [
        r"\bwe\s+define\s+['\"]?[\w\s]+['\"]?\s+as\b",  # "We define 'X' as..."
        r"\b['\"][\w\s]+['\"]?\s+(?:means|refers\s+to)\b",  # "'X' means..."
        r"\bdefined\s+as\b",  # "...defined as..."
        r"\bthe\s+following\s+(?:table|metrics?|terms?)\b",  # "the following metrics..."
    ]

    # Signals that a segment is a continuation of a previous definition
    DEFINITION_CONTINUATION_PATTERNS = [
        r"^[a-z]",  # Starts with lowercase (likely mid-sentence)
        r"^(?:and|or|but|which|that|who|where|when)\b",  # Starts with conjunction
        r"^\s*\(",  # Starts with parenthetical
        r"^(?:including|excluding|such\s+as)\b",  # Starts with qualifier
        r"^(?:Such|These|Those|This)\b",  # Demonstrative pronouns (SEG4)
        r"^The\s+(?:above|following)\b",  # Referential phrases (SEG4)
    ]

    # Limits for definition merging
    DEFINITION_LOOKAHEAD_MAX = 3  # Max segments to merge
    DEFINITION_MAX_COMBINED_LENGTH = 2000  # Max combined length

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
        # SEG3: Singleton BoundaryDetector to reduce object allocation overhead
        self._boundary_detector = BoundaryDetector()

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
        raw_segments = []
        sequence_index = 0

        # Extract all segments
        for element in main_content.find_all(["p", "table", "div", "ul", "ol"], recursive=True):
            # Skip if element is nested inside a table (we'll capture the whole table)
            if element.name == "p" and element.find_parent("table"):
                continue

            # Skip list items nested inside another list (we'll handle from outer list)
            if element.name in ["ul", "ol"] and element.find_parent(["ul", "ol"]):
                continue

            # Skip elements nested in a div that contains BOTH text and tables (L5 composite splitting)
            # Those elements will be extracted when the parent div is split
            if element.name in ["p", "table"]:
                parent_div = element.find_parent("div")
                if parent_div:
                    # Check if the div has both paragraphs and tables (composite segment)
                    has_table = parent_div.find("table") is not None
                    has_paragraph = parent_div.find("p") is not None
                    if has_table and has_paragraph:
                        # This is a composite segment - skip nested elements
                        # They'll be handled when the div is split
                        continue

            # Handle lists specially - extract individual items with context (Phase 6)
            if element.name in ["ul", "ol"]:
                intro_text = self._get_list_intro_text(element)
                list_segments = self._extract_list_segments(
                    element, filing_id, sequence_index, intro_text
                )
                raw_segments.extend(list_segments)
                sequence_index += len(list_segments) if list_segments else 1
                continue

            segment = self._extract_segment(element, filing_id, sequence_index)
            if segment:
                raw_segments.append(segment)
                sequence_index += 1

        # Apply composite segment splitting (L5 enhancement)
        # This splits segments containing both text and tables into separate segments
        segments = []
        for segment in raw_segments:
            split_segs = self._split_composite_segment(segment)
            segments.extend(split_segs)

        # Apply definition merging (Phase 3 of redesign)
        # This merges segments that split a definition across HTML elements
        segments = self._merge_definition_segments(segments)

        # Apply sentence detection (Phase 2 of redesign)
        # This stores sentence boundaries in segment metadata for:
        # - Preventing mid-sentence truncation
        # - Context overlap extraction
        for segment in segments:
            self._apply_sentence_detection(segment)

        # Handle large tables (Phase 4 of redesign)
        # Tables get a higher limit (25K) and summary generation if exceeded
        for i, segment in enumerate(segments):
            segments[i] = self._handle_large_table(segment)

        # Add context enrichment (Phase 5 of redesign)
        # This adds context overlap and document position
        segments = self._add_context_overlap(segments)
        segments = self._calculate_document_positions(segments)

        # Update metrics after splitting
        self._metrics.total_segments = len(segments)
        self._metrics.total_text_length = sum(len(s.raw_text) for s in segments)
        self._metrics.segment_counts_by_type = {}
        for segment in segments:
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
        # Try to find <TEXT> tag (SGML format) - case insensitive
        # Older filings may use uppercase <TEXT>, newer ones lowercase <text>
        text_tag = soup.find("text") or soup.find("TEXT")
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
        # Tables get a higher limit (TABLE_MAX_LENGTH) than text (max_length)
        effective_max = self.TABLE_MAX_LENGTH if segment_type == 'table' else self.max_length

        if len(raw_text) > effective_max:
            logger.debug(
                f"Truncating {segment_type} segment from {len(raw_text)} to {effective_max} chars"
            )
            if segment_type != 'table':
                # Use sentence-aware truncation to avoid cutting mid-sentence
                raw_text = self._truncate_at_sentence_boundary(raw_text, effective_max)
            else:
                # Tables: simple truncation here, _handle_large_table() creates summary
                raw_text = raw_text[:effective_max]

        # Extract raw HTML (limited to avoid huge storage)
        # Tables get higher limit to preserve structure for downstream extraction
        html_max = self.TABLE_MAX_LENGTH if segment_type == 'table' else self.max_length
        raw_html = str(element)[:html_max]

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

    def _split_composite_segment(self, segment: SourceSegment) -> List[SourceSegment]:
        """
        Split a segment containing both text and tables into separate segments.

        This prevents false positives where keywords in text are matched to numbers
        in tables (or vice versa) during candidate generation.

        Args:
            segment: Original segment that may contain mixed text and table content

        Returns:
            List of segments (single segment if no split needed, multiple if split)
        """
        # Quick check: does the segment contain table tags?
        if not segment.raw_html or '<table' not in segment.raw_html.lower():
            return [segment]

        # Check if segment is already a table - don't split tables themselves
        if segment.segment_type == 'table':
            return [segment]

        try:
            # Parse the HTML to identify table boundaries
            soup = BeautifulSoup(segment.raw_html, 'html.parser')

            # Find all table elements
            # First, get all tables
            all_tables = soup.find_all('table')

            # Filter out tables that are nested within other tables
            tables = []
            for table in all_tables:
                # Check if this table has a table ancestor (other than itself)
                parent_tables = table.find_parents('table')
                if not parent_tables:
                    # Not nested in another table, include it
                    tables.append(table)

            # If no tables found, return original segment
            if not tables:
                return [segment]

            # Build list of content pieces: (is_table, content_html, start_pos)
            content_pieces = []

            # Get the full HTML string for position tracking
            full_html = str(soup)

            # Track table positions in the HTML
            table_positions = []
            for table in tables:
                table_html = str(table)
                # Find start position of this table in the full HTML
                start_pos = full_html.find(table_html)
                if start_pos >= 0:
                    table_positions.append((start_pos, start_pos + len(table_html), table_html))

            # Sort by position
            table_positions.sort(key=lambda x: x[0])

            # Extract text before first table, between tables, and after last table
            current_pos = 0
            for start_pos, end_pos, table_html in table_positions:
                # Extract text before this table
                if start_pos > current_pos:
                    text_before = full_html[current_pos:start_pos]
                    # Parse it to get clean text
                    text_soup = BeautifulSoup(text_before, 'html.parser')
                    text_content = self._normalize_text(text_soup.get_text())
                    if text_content.strip():  # Only add non-empty text
                        content_pieces.append(('text', text_before, text_content))

                # Add the table
                table_soup = BeautifulSoup(table_html, 'html.parser')
                table_text = self._normalize_text(table_soup.get_text())
                if table_text.strip():  # Only add non-empty tables
                    content_pieces.append(('table', table_html, table_text))

                current_pos = end_pos

            # Extract text after last table
            if current_pos < len(full_html):
                text_after = full_html[current_pos:]
                text_soup = BeautifulSoup(text_after, 'html.parser')
                text_content = self._normalize_text(text_soup.get_text())
                if text_content.strip():  # Only add non-empty text
                    content_pieces.append(('text', text_after, text_content))

            # If we only have one piece, return the original segment
            if len(content_pieces) <= 1:
                return [segment]

            # Create new segments from the pieces
            split_segments = []
            base_sequence = segment.sequence_index

            for i, (piece_type, html_content, text_content) in enumerate(content_pieces):
                # Determine segment type
                seg_type = 'table' if piece_type == 'table' else 'paragraph'

                # Check if text meets minimum length for paragraphs
                if seg_type == 'paragraph' and len(text_content) < self.min_length:
                    continue

                # Truncate if needed
                if len(text_content) > self.max_length:
                    text_content = text_content[:self.max_length]
                    html_content = html_content[:self.max_length]

                # Create new segment with fractional sequence index
                new_segment = SourceSegment(
                    filing_id=segment.filing_id,
                    segment_type=seg_type,
                    section_path=segment.section_path,
                    section_heading=segment.section_heading,
                    sequence_index=base_sequence + (i * 0.1),  # Use fractional increments
                    raw_text=text_content,
                    raw_html=html_content[:self.max_length] if html_content else None,
                    html_selector=segment.html_selector,
                    char_start_offset=segment.char_start_offset,
                    char_end_offset=segment.char_end_offset,
                    page_number=segment.page_number,
                    candidate_metric_ids=segment.candidate_metric_ids,
                    contains_definition_flag=segment.contains_definition_flag,
                    contains_methodology_flag=segment.contains_methodology_flag,
                    contains_numeric_disclosure_flag=segment.contains_numeric_disclosure_flag,
                    classifier_confidence=segment.classifier_confidence,
                )

                split_segments.append(new_segment)

            # Return split segments if we created any, otherwise original
            return split_segments if split_segments else [segment]

        except Exception as e:
            # On any error, log warning and return original segment
            logger.warning(
                f"Failed to split composite segment for filing {segment.filing_id}, "
                f"sequence {segment.sequence_index}: {e}. Returning original segment."
            )
            return [segment]

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

    # =========================================================================
    # Sentence Detection Methods (Phase 2 of redesign)
    # =========================================================================

    def _apply_sentence_detection(self, segment: SourceSegment) -> SourceSegment:
        """
        Store sentence boundaries in segment metadata.

        Uses BoundaryDetector to find sentence boundaries, which is useful for:
        - Preventing mid-sentence truncation
        - Extracting context overlap between segments
        - Downstream processing that needs sentence-level granularity

        Args:
            segment: SourceSegment to analyze

        Returns:
            Same segment with sentence_boundaries populated
        """
        # Tables don't need sentence detection (handled differently)
        if segment.segment_type == 'table':
            return segment

        if not segment.raw_text:
            return segment

        boundaries = self._boundary_detector.find_sentence_boundaries(
            segment.raw_text,
            segment_type=segment.segment_type
        )

        # Store as list of (start, end) tuples
        segment.sentence_boundaries = [(b.start, b.end) for b in boundaries]

        return segment

    def _truncate_at_sentence_boundary(self, text: str, max_length: int) -> str:
        """
        Truncate text at the nearest sentence boundary before max_length.

        This prevents cutting off in the middle of a sentence, which would
        create nonsensical segments and lose context.

        Args:
            text: Text to potentially truncate
            max_length: Maximum allowed length

        Returns:
            Text truncated at sentence boundary (or original if under limit)
        """
        if len(text) <= max_length:
            return text

        sentences = self._boundary_detector.find_sentence_boundaries(text)

        # Find the last complete sentence that fits within max_length
        for boundary in reversed(sentences):
            if boundary.end <= max_length:
                return text[:boundary.end].rstrip()

        # No complete sentence fits - fall back to truncation at max_length
        # This should be rare (would mean first sentence is > max_length)
        logger.debug(
            f"No complete sentence fits within {max_length} chars, "
            f"truncating mid-sentence"
        )
        return text[:max_length]

    def _extract_last_sentence(self, text: str) -> Optional[str]:
        """
        Extract the last sentence from text.

        Used for context overlap - adding the last sentence of the previous
        segment to the current segment's context_prefix.

        Args:
            text: Text to extract from

        Returns:
            Last sentence, or None if no sentences found
        """
        if not text:
            return None

        sentences = self._boundary_detector.find_sentence_boundaries(text)

        if not sentences:
            return None

        last_boundary = sentences[-1]
        last_sentence = text[last_boundary.start:last_boundary.end].strip()

        return last_sentence if last_sentence else None

    # =========================================================================
    # Definition Merging Methods (Phase 3 of redesign)
    # =========================================================================

    def _starts_definition(self, text: str) -> bool:
        """
        Check if text starts a definition that may span multiple segments.

        Args:
            text: Text to check

        Returns:
            True if text appears to start a definition
        """
        if not text:
            return False

        text_lower = text.lower()
        for pattern in self.DEFINITION_START_PATTERNS:
            if re.search(pattern, text_lower, re.IGNORECASE):
                return True
        return False

    def _is_continuation(self, text: str) -> bool:
        """
        Check if text appears to be a continuation of a previous definition.

        Args:
            text: Text to check

        Returns:
            True if text appears to be a continuation
        """
        if not text:
            return False

        for pattern in self.DEFINITION_CONTINUATION_PATTERNS:
            # First pattern (lowercase start) should NOT use IGNORECASE
            # All other patterns should use IGNORECASE
            if pattern == r"^[a-z]":
                if re.search(pattern, text):  # No IGNORECASE flag
                    return True
            else:
                if re.search(pattern, text, re.IGNORECASE):
                    return True
        return False

    def _merge_definition_segments(
        self, segments: List[SourceSegment]
    ) -> List[SourceSegment]:
        """
        Merge segments that split a definition across HTML elements.

        When a definition like "We define active customers as customers who..."
        gets split across multiple <p> tags, this method merges them back together.

        Limits:
        - Maximum 3 segments merged
        - Maximum 2000 combined characters
        - Only merges consecutive segments of same type

        Args:
            segments: List of segments to potentially merge

        Returns:
            List of segments with definitions merged
        """
        if not segments:
            return segments

        merged: List[SourceSegment] = []
        i = 0

        while i < len(segments):
            segment = segments[i]

            # Only try to merge paragraph-type segments (not tables, etc.)
            if segment.segment_type not in ('paragraph', 'definition_block') or \
               not self._starts_definition(segment.raw_text):
                merged.append(segment)
                i += 1
                continue

            # Found a definition start - look ahead for continuations
            merged_text = segment.raw_text
            merged_html = segment.raw_html or ""
            merge_count = 1
            j = i + 1

            while (j < len(segments) and
                   merge_count < self.DEFINITION_LOOKAHEAD_MAX and
                   len(merged_text) < self.DEFINITION_MAX_COMBINED_LENGTH):

                next_seg = segments[j]

                # Only merge same-type segments that look like continuations
                if next_seg.segment_type not in ('paragraph', 'definition_block'):
                    break
                if not self._is_continuation(next_seg.raw_text):
                    break

                # Merge this segment
                merged_text += " " + next_seg.raw_text
                if next_seg.raw_html:
                    merged_html += next_seg.raw_html
                merge_count += 1
                j += 1

            # Update the segment with merged content if we merged anything
            if merge_count > 1:
                segment.raw_text = merged_text.strip()
                segment.raw_html = merged_html[:self.max_length] if merged_html else None
                segment.definition_merged_count = merge_count
                logger.debug(
                    f"Merged {merge_count} segments into definition "
                    f"({len(segment.raw_text)} chars)"
                )

            merged.append(segment)
            i = j  # Skip past merged segments

        return merged

    # =========================================================================
    # Table Handling Methods (Phase 4 of redesign)
    # =========================================================================

    def _handle_large_table(self, segment: SourceSegment) -> SourceSegment:
        """
        Handle tables that exceed the maximum length limit.

        For very large tables, creates a summary in raw_text while preserving
        the full table in raw_html. This allows downstream processing to
        access the full data when needed while keeping segment sizes manageable.

        Args:
            segment: Table segment to potentially summarize

        Returns:
            Original segment (if under limit) or segment with summary
        """
        if segment.segment_type != 'table':
            return segment

        if len(segment.raw_text) <= self.TABLE_MAX_LENGTH:
            return segment

        # Table exceeds limit - create summary
        logger.debug(
            f"Large table detected ({len(segment.raw_text)} chars > "
            f"{self.TABLE_MAX_LENGTH} limit), creating summary"
        )

        # Generate summary from the table
        summary = self._create_table_summary(segment.raw_html, segment.raw_text)

        # Update segment
        segment.raw_text = summary
        segment.table_truncated_flag = True

        return segment

    def _create_table_summary(
        self, raw_html: Optional[str], raw_text: str
    ) -> str:
        """
        Create a summary of a large table.

        Includes:
        - Header row(s) if available
        - Row count estimate
        - First few rows of data

        Args:
            raw_html: Original HTML (for structure parsing)
            raw_text: Normalized text content

        Returns:
            Summary string
        """
        summary_parts = []

        # Try to extract headers and structure from HTML
        if raw_html:
            try:
                soup = BeautifulSoup(raw_html, 'html.parser')
                table = soup.find('table')

                if table:
                    # Get header row
                    thead = table.find('thead')
                    header_row = None
                    if thead:
                        header_row = thead.find('tr')
                    else:
                        # Try first row with th elements
                        first_row = table.find('tr')
                        if first_row and first_row.find('th'):
                            header_row = first_row

                    if header_row:
                        headers = [
                            self._normalize_text(cell.get_text())
                            for cell in header_row.find_all(['th', 'td'])
                        ]
                        headers = [h for h in headers if h]  # Remove empty
                        if headers:
                            summary_parts.append(
                                f"[Table headers: {' | '.join(headers[:10])}]"
                            )

                    # Count rows
                    all_rows = table.find_all('tr')
                    row_count = len(all_rows)
                    summary_parts.append(f"[{row_count} rows total]")

            except Exception as e:
                logger.debug(f"Could not parse table HTML for summary: {e}")

        # Include truncated raw text for searchability
        # Take first portion of text (approximately first few rows)
        max_summary_text = 3000
        if len(raw_text) > max_summary_text:
            truncated_text = raw_text[:max_summary_text].rstrip()
            # Try to end at a reasonable break point
            last_space = truncated_text.rfind(' ')
            if last_space > max_summary_text - 200:
                truncated_text = truncated_text[:last_space]
            summary_parts.append(truncated_text + "...")
        else:
            summary_parts.append(raw_text)

        return " ".join(summary_parts)

    # =========================================================================
    # Context Enrichment Methods (Phase 5 of redesign)
    # =========================================================================

    def _add_context_overlap(
        self, segments: List[SourceSegment]
    ) -> List[SourceSegment]:
        """
        Add last sentence from previous segment as context_prefix.

        This preserves context at segment boundaries, allowing downstream
        processing to understand the relationship between segments.

        Args:
            segments: List of segments to enrich

        Returns:
            Same list with context_prefix populated
        """
        max_context_length = 200  # Don't include overly long context

        for i in range(1, len(segments)):
            prev = segments[i - 1]

            # Don't take context from tables (not sentence-structured)
            if prev.segment_type == 'table':
                continue

            # Extract last sentence from previous segment
            last_sentence = self._extract_last_sentence(prev.raw_text)

            if last_sentence and len(last_sentence) <= max_context_length:
                segments[i].context_prefix = last_sentence

        return segments

    def _calculate_document_positions(
        self, segments: List[SourceSegment]
    ) -> List[SourceSegment]:
        """
        Calculate relative position of each segment in the document.

        Position is a float from 0.0 (start) to 1.0 (end) based on
        cumulative text length.

        Args:
            segments: List of segments to enrich

        Returns:
            Same list with document_position populated
        """
        if not segments:
            return segments

        # Calculate total text length
        total_length = sum(len(s.raw_text) for s in segments)

        if total_length == 0:
            return segments

        # Calculate cumulative position for each segment
        cumulative = 0
        for segment in segments:
            segment.document_position = cumulative / total_length
            cumulative += len(segment.raw_text)

        return segments

    # =========================================================================
    # List Handling Methods (Phase 6 of redesign)
    # =========================================================================

    def _extract_list_segments(
        self,
        list_element: Tag,
        filing_id: int,
        base_sequence: int,
        intro_text: Optional[str] = None
    ) -> List[SourceSegment]:
        """
        Extract list items as separate segments with context.

        Each <li> becomes its own segment, with the intro text (the paragraph
        before the list) stored as context_prefix.

        Args:
            list_element: <ul> or <ol> element
            filing_id: Database filing ID
            base_sequence: Base sequence index for the list
            intro_text: Text from preceding paragraph as context

        Returns:
            List of segments, one per list item
        """
        segments = []

        # Find all direct child <li> elements (not nested lists)
        list_items = list_element.find_all('li', recursive=False)

        for i, li in enumerate(list_items):
            text = self._normalize_text(li.get_text())

            # Skip items that are too short
            if len(text) < self.min_length:
                continue

            # Truncate if needed
            if len(text) > self.max_length:
                text = self._truncate_at_sentence_boundary(text, self.max_length)

            # Extract section info
            section_path, section_heading = self._extract_section_info(list_element)

            segment = SourceSegment(
                filing_id=filing_id,
                segment_type='list_item',
                section_path=section_path,
                section_heading=section_heading,
                sequence_index=base_sequence + (i * 0.1),  # Fractional indices
                raw_text=text,
                raw_html=str(li)[:self.max_length],
                context_prefix=intro_text,  # Include intro as context
            )

            segments.append(segment)

        return segments

    def _get_list_intro_text(self, list_element: Tag) -> Optional[str]:
        """
        Get the introductory text before a list.

        This is typically a sentence like "Key metrics include:" that
        provides context for the list items.

        Args:
            list_element: <ul> or <ol> element

        Returns:
            Intro text, or None if not found
        """
        # Look for the immediately preceding sibling paragraph
        prev_sibling = list_element.find_previous_sibling(['p', 'div'])

        if not prev_sibling:
            return None

        intro_text = self._normalize_text(prev_sibling.get_text())

        # Only use if it's reasonably short (likely an intro, not a paragraph)
        if intro_text and len(intro_text) <= 200:
            return intro_text

        # Try to get just the last sentence
        last_sentence = self._extract_last_sentence(intro_text)
        if last_sentence and len(last_sentence) <= 200:
            return last_sentence

        return None

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
