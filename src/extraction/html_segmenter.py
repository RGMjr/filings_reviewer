"""
HTML Segmenter - Parse filing HTML into semantic segments.

This module breaks down SEC filing HTML documents into atomic source segments
(paragraphs, tables, footnotes) that serve as the basis for metric extraction.
"""

import bisect
import logging
import re
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

from bs4 import BeautifulSoup, Tag

from src.review.boundary_detection import BoundaryDetector

from .exceptions import EncodingError, HTMLParsingError, ValidationError
from .models import SourceSegment
from .validators import SegmentValidator

logger = logging.getLogger(__name__)

# Conditional import for charset-normalizer (graceful degradation)
try:
    from charset_normalizer import from_bytes
    CHARSET_NORMALIZER_AVAILABLE = True
except ImportError:
    CHARSET_NORMALIZER_AVAILABLE = False
    logger.warning(
        "charset-normalizer not available, using fallback encoding detection "
        "(UTF-8 → Latin-1 cascade)"
    )

# Minimum confidence threshold for auto-detection (0.0 to 1.0)
ENCODING_CONFIDENCE_THRESHOLD = 0.80

# Maximum bytes to read for encoding detection (64KB for large files)
ENCODING_DETECTION_MAX_BYTES = 65536


@dataclass
class SegmentationMetrics:
    """Metrics collected during HTML segmentation.

    Tracks performance, segment distribution, and warnings for observability.
    """

    filing_id: int
    total_segments: int = 0
    segment_counts_by_type: dict[str, int] = field(default_factory=dict)
    total_text_length: int = 0
    parse_time_seconds: float = 0.0
    encoding_used: str = "utf-8"
    warnings: list[str] = field(default_factory=list)

    def avg_segment_length(self) -> float:
        """Calculate average segment text length."""
        if self.total_segments == 0:
            return 0.0
        return self.total_text_length / self.total_segments

    def summary(self) -> str:
        """Generate human-readable summary."""
        type_counts = ", ".join(
            f"{count} {seg_type}s"
            for seg_type, count in sorted(self.segment_counts_by_type.items())
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

    # Parallel processing configuration (SEG11)
    PARALLEL_SENTENCE_DETECTION_WORKERS = 4
    PARALLEL_SENTENCE_DETECTION_THRESHOLD = 50

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
    METADATA_HEADINGS = frozenset(
        {
            "table of contents",
            "index",
            "cover page",
            "prospectus cover",
            "part of prospectus",
            "explanatory note",
            "forward-looking statements",
            "about this prospectus",
        }
    )

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

    def __init__(self, min_length: int = MIN_SEGMENT_LENGTH, max_length: int = MAX_SEGMENT_LENGTH):
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
        self._metrics: SegmentationMetrics | None = None
        # SEG3: Singleton BoundaryDetector to reduce object allocation overhead
        self._boundary_detector = BoundaryDetector()

    def segment_filing(
        self,
        filing_id: int,
        html_path: str = "",
        raise_on_error: bool = False,
        *,
        html_content: str | None = None,
    ) -> list[SourceSegment]:
        """
        Parse filing HTML and return list of source segments.

        Args:
            filing_id: Database filing ID
            html_path: Path to HTML file. Required when html_content is None.
            raise_on_error: If True, raise exceptions instead of returning empty list
                (default: False for backward compatibility)
            html_content: Pre-loaded HTML string. When provided, file reading and
                path validation are skipped; html_path is used only for log messages.
                The caller is responsible for correct decoding.

        Returns:
            List of SourceSegment objects (not yet inserted to DB)

        Raises:
            ValidationError: If filing_id or html_path is invalid (only if raise_on_error=True)
            EncodingError: If file encoding cannot be determined (only if raise_on_error=True)
            HTMLParsingError: If HTML structure is invalid (only if raise_on_error=True)
        """
        start_time = time.time()

        # Validate inputs
        validated_path = None
        try:
            SegmentValidator.validate_filing_id(filing_id)
            if html_content is None:
                validated_path = SegmentValidator.validate_html_path(html_path)
        except (ValidationError, FileNotFoundError, PermissionError) as e:
            if raise_on_error:
                raise
            logger.error(f"Validation failed for filing {filing_id}: {e}")
            return []

        # Determine label used in log messages and error objects
        path_label = str(validated_path) if validated_path is not None else (html_path or "<provided content>")

        logger.info(f"Segmenting filing {filing_id} from {path_label}")

        # Initialize metrics
        self._metrics = SegmentationMetrics(filing_id=filing_id)

        # Resolve HTML content: from provided string or file
        if html_content is None:
            try:
                html_content, encoding_used = self._read_html_file_with_encoding(path_label)
                self._metrics.encoding_used = encoding_used
            except EncodingError as e:
                if raise_on_error:
                    raise
                logger.error(f"Encoding error for filing {filing_id}: {e}")
                self._metrics.warnings.append(f"Encoding error: {e}")
                return []
        else:
            self._metrics.encoding_used = "provided"

        if not html_content:
            msg = f"Empty HTML content for filing {filing_id}"
            if raise_on_error:
                raise HTMLParsingError(msg, filing_id=filing_id, html_path=path_label)
            logger.warning(msg)
            self._metrics.warnings.append("Empty HTML content")
            return []

        # Parse with BeautifulSoup
        try:
            soup = BeautifulSoup(html_content, "html.parser")
        except Exception as e:
            msg = f"Failed to parse HTML for filing {filing_id}: {e}"
            if raise_on_error:
                raise HTMLParsingError(
                    msg, filing_id=filing_id, html_path=path_label
                ) from e
            logger.error(msg)
            self._metrics.warnings.append(f"Parse error: {e}")
            return []

        # Find the main content area (usually in <BODY> or after <TEXT> tag)
        main_content = self._find_main_content(soup)
        if not main_content:
            msg = f"Could not find main content in filing {filing_id}"
            if raise_on_error:
                raise HTMLParsingError(msg, filing_id=filing_id, html_path=path_label)
            logger.warning(msg)
            self._metrics.warnings.append("No main content found")
            return []

        # Pre-build heading cache for O(1) lookups (performance optimization)
        self._heading_cache = self._build_heading_cache(main_content)

        # Extract segments
        raw_segments = []
        sequence_index = 0

        # Cache elements by sequence index for composite splitting (SEG9 optimization)
        # This avoids redundant BeautifulSoup parsing in _split_composite_segment()
        # The cache is cleared after splitting to release DOM references
        element_cache: dict[int, Tag] = {}

        # Extract all segments
        for element in main_content.find_all(
            ["p", "table", "div", "ul", "ol", "blockquote", "pre", "figure"],
            recursive=True
        ):
            # Skip if element is nested inside a table (we'll capture the whole table)
            if element.name in ("p", "blockquote", "pre", "figure") and element.find_parent("table"):
                continue

            # Skip list items nested inside another list (we'll handle from outer list)
            if element.name in ["ul", "ol"] and element.find_parent(["ul", "ol"]):
                continue

            # Skip nested blockquote/figure inside same element type (extract outer only)
            if element.name == "blockquote" and element.find_parent("blockquote"):
                continue
            if element.name == "figure" and element.find_parent("figure"):
                continue

            # Skip div that only wraps a table with no additional text content
            # This prevents duplicate extraction - the inner table will be extracted separately
            # with correct type and [ROW]/[CELL] markers
            if element.name == "div":
                inner_table = element.find("table")
                if inner_table:
                    div_text = self._normalize_text(element.get_text())
                    table_text = self._normalize_text(inner_table.get_text())
                    if div_text == table_text:
                        # Div adds nothing beyond the table - skip it
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
                # Cache element for composite splitting (SEG9)
                element_cache[sequence_index] = element
                sequence_index += 1

        # Apply composite segment splitting (L5 enhancement)
        # This splits segments containing both text and tables into separate segments
        # Pass cached elements to avoid re-parsing HTML (SEG9 optimization)
        segments = []
        for segment in raw_segments:
            # Get cached element by integer sequence index
            cached_element = element_cache.get(int(segment.sequence_index))
            split_segs = self._split_composite_segment(segment, parsed_element=cached_element)
            segments.extend(split_segs)

        # Clear element cache - DOM elements no longer needed (SEG9 memory cleanup)
        # This releases references to the parsed DOM tree
        element_cache.clear()

        # Apply definition merging (Phase 3 of redesign)
        # This merges segments that split a definition across HTML elements
        segments = self._merge_definition_segments(segments)

        # Apply sentence detection (Phase 2 of redesign)
        # This stores sentence boundaries in segment metadata for:
        # - Preventing mid-sentence truncation
        # - Context overlap extraction
        # Use parallel processing for large filings (SEG11)
        if len(segments) >= self.PARALLEL_SENTENCE_DETECTION_THRESHOLD:
            segments = self._apply_sentence_detection_parallel(segments)
        else:
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
        logger.info(
            f"Extracted {len(segments)} segments from filing {filing_id}: {self._metrics.summary()}"
        )

        if self._metrics.warnings:
            logger.warning(
                f"Segmentation warnings for filing {filing_id}: {', '.join(self._metrics.warnings)}"
            )

        return segments

    def _read_html_file_with_encoding(self, html_path: str) -> tuple[str | None, str]:
        """Read HTML file with automatic encoding detection and fallback cascade.

        Detection order (SEG7):
        1. charset-normalizer auto-detection (if confidence >= 80%)
        2. UTF-8 explicit attempt
        3. Latin-1 fallback
        4. EncodingError (only if all above fail)

        Args:
            html_path: Path to HTML file

        Returns:
            Tuple of (content, encoding_used)

        Raises:
            EncodingError: If all encoding attempts fail
        """
        path = Path(html_path)
        attempted_encodings: list[str] = []

        # Step 1: Try auto-detection if charset-normalizer is available
        if CHARSET_NORMALIZER_AVAILABLE:
            detected_encoding = self._detect_encoding_auto(path)
            if detected_encoding:
                try:
                    content = path.read_text(encoding=detected_encoding)
                    logger.debug(
                        f"Successfully read {html_path} with auto-detected "
                        f"encoding: {detected_encoding}"
                    )
                    return (content, detected_encoding)
                except (UnicodeDecodeError, LookupError) as e:
                    attempted_encodings.append(detected_encoding)
                    logger.debug(
                        f"Auto-detected encoding {detected_encoding} failed for "
                        f"{html_path}: {e}. Falling back to explicit encodings."
                    )

        # Step 2: Try UTF-8 explicitly
        try:
            content = path.read_text(encoding="utf-8")
            logger.debug(f"Successfully read {html_path} with UTF-8 encoding")
            return (content, "utf-8")
        except UnicodeDecodeError as e:
            if "utf-8" not in attempted_encodings:
                attempted_encodings.append("utf-8")
            position = e.start if hasattr(e, "start") else None
            logger.debug(
                f"UTF-8 decode failed for {html_path} at position {position}: {e}. "
                f"Trying latin-1 fallback..."
            )

        # Step 3: Fall back to latin-1
        try:
            content = path.read_text(encoding="latin-1")
            logger.info(
                f"Successfully read {html_path} with latin-1 encoding "
                f"(tried: {', '.join(attempted_encodings)})"
            )
            return (content, "latin-1")
        except UnicodeDecodeError as e:
            if "latin-1" not in attempted_encodings:
                attempted_encodings.append("latin-1")
            position = e.start if hasattr(e, "start") else None

            # Step 4: All encodings failed - raise EncodingError
            raise EncodingError(
                f"Failed to decode {html_path}. Attempted encodings: "
                f"{', '.join(attempted_encodings)}. File may have mixed or invalid encoding.",
                file_path=html_path,
                attempted_encodings=attempted_encodings,
                position=position,
            ) from e

    def _detect_encoding_auto(self, path: Path) -> str | None:
        """Detect file encoding using charset-normalizer library.

        Reads up to ENCODING_DETECTION_MAX_BYTES (64KB) for detection to handle
        large files efficiently.

        Args:
            path: Path to file

        Returns:
            Detected encoding name if confidence >= threshold, None otherwise
        """
        if not CHARSET_NORMALIZER_AVAILABLE:
            return None

        try:
            # Read file bytes (limited for large files)
            file_size = path.stat().st_size
            bytes_to_read = min(file_size, ENCODING_DETECTION_MAX_BYTES)

            with open(path, "rb") as f:
                raw_bytes = f.read(bytes_to_read)

            # Empty file - no detection needed
            if not raw_bytes:
                return None

            # Run charset detection
            result = from_bytes(raw_bytes)
            best_match = result.best()

            if best_match is None:
                logger.debug(f"charset-normalizer found no encoding match for {path}")
                return None

            encoding = best_match.encoding
            # charset-normalizer uses 0.0-1.0 for coherence, but we want confidence
            # The 'encoding' property returns the encoding, and we can check coherence
            # from the CharsetMatch object
            confidence = getattr(best_match, "coherence", 0.0)

            # Adjust threshold check - charset-normalizer's coherence is typically
            # high for valid text, but we use encoding_aliases for common aliases
            # Some encodings report as aliases (cp1252 = windows-1252)
            if confidence < ENCODING_CONFIDENCE_THRESHOLD:
                logger.debug(
                    f"Auto-detected {encoding} for {path} but confidence "
                    f"({confidence:.2f}) below threshold ({ENCODING_CONFIDENCE_THRESHOLD})"
                )
                return None

            logger.debug(
                f"Auto-detected encoding {encoding} for {path} "
                f"(confidence: {confidence:.2f})"
            )
            return encoding

        except Exception as e:
            # Any error in detection should not break the pipeline
            logger.debug(f"Encoding auto-detection failed for {path}: {e}")
            return None

    def _find_main_content(self, soup: BeautifulSoup) -> Tag | None:
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

    # =========================================================================
    # CSS Selector Generation Methods (SEG10)
    # =========================================================================

    def _element_selector(self, element: Tag) -> str:
        """
        Generate a CSS selector for a single element.

        Strategy:
        - If element has ID, use #id (most specific, globally unique)
        - If element has class(es), use tag.classname (first class only)
        - Otherwise use tag:nth-of-type(n) for uniqueness among siblings

        Args:
            element: BeautifulSoup Tag element

        Returns:
            CSS selector string for this element
        """
        tag = element.name

        # ID is most specific - use it alone
        element_id = element.get("id")
        if element_id:
            # Escape special CSS characters in ID
            escaped_id = self._escape_css_identifier(str(element_id))
            return f"#{escaped_id}"

        # Class adds specificity - use first class
        classes = element.get("class", [])
        if classes and isinstance(classes, list) and len(classes) > 0:
            # Use first class, escape if needed
            first_class = self._escape_css_identifier(str(classes[0]))
            return f"{tag}.{first_class}"

        # Fall back to nth-of-type for uniqueness among siblings
        # Count same-tag siblings before this element
        nth = 1
        if element.parent:
            for sibling in element.parent.children:
                if sibling is element:
                    break
                if hasattr(sibling, "name") and sibling.name == tag:
                    nth += 1

        return f"{tag}:nth-of-type({nth})"

    def _escape_css_identifier(self, identifier: str) -> str:
        """
        Escape special characters in CSS identifiers.

        CSS selectors need certain characters escaped (colons, periods, etc.)

        Args:
            identifier: Raw identifier string (ID or class name)

        Returns:
            Escaped string safe for use in CSS selectors
        """
        # Characters that need escaping in CSS identifiers
        # Note: We escape with backslash for CSS compliance
        special_chars = [":", ".", "[", "]", "(", ")", "#", ">", "+", "~", " ", ","]
        result = identifier
        for char in special_chars:
            result = result.replace(char, f"\\{char}")
        return result

    def _generate_css_selector(self, element: Tag) -> str | None:
        """
        Generate a CSS selector path to uniquely identify this element.

        Builds a path from the element up toward the root (or to first element
        with an ID, which terminates the path since IDs are globally unique).

        Path is limited to 6 levels to avoid overly long selectors.

        Args:
            element: BeautifulSoup Tag element

        Returns:
            CSS selector string like "#content > div.section > p:nth-of-type(2)"
            or None if element is invalid
        """
        if not element or not hasattr(element, "name") or not element.name:
            return None

        parts = []
        current = element
        depth = 0
        max_depth = 6

        try:
            while current and hasattr(current, "name") and current.name and depth < max_depth:
                selector = self._element_selector(current)
                parts.insert(0, selector)

                # Stop at element with ID (globally unique, no need to go higher)
                if current.get("id"):
                    break

                current = current.parent
                depth += 1

            return " > ".join(parts) if parts else None

        except Exception as e:
            # Selector generation is non-critical - log and return None
            logger.debug(f"Error generating CSS selector: {e}")
            return None

    def _extract_segment(
        self, element: Tag, filing_id: int, sequence_index: int
    ) -> SourceSegment | None:
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

        full_html = str(element)

        # Tables use a separate summarization flow (_handle_large_table) that needs
        # the full element, so we preserve original behavior for tables.
        # For non-tables, apply HRV-22 FIX: Truncate HTML FIRST, then extract text
        # from truncated HTML to ensure consistency.
        if segment_type == "table" or element.name == "table":
            # Tables: extract from FULL element, let _handle_large_table handle summarization
            raw_html = full_html[:self.TABLE_MAX_LENGTH]
            raw_text = self._extract_table_text_with_markers(element)
        else:
            # Non-tables: HRV-22 FIX - truncate HTML first, then extract text
            html_max = self.max_length
            raw_html = full_html[:html_max]
            truncated_soup = BeautifulSoup(raw_html, "html.parser")

            if element.name == "figure":
                figure_elem = truncated_soup.find("figure") or truncated_soup
                raw_text = self._normalize_text(self._extract_figure_text(figure_elem))
            else:
                raw_text = self._normalize_text(truncated_soup.get_text())

        # Skip segments that are too short
        if len(raw_text) < self.min_length:
            return None

        # Text extracted from truncated HTML is already consistent with raw_html
        # Apply sentence-aware truncation for non-tables to ensure clean sentence endings
        # This runs AFTER HTML truncation to maintain consistency while improving readability
        effective_max = self.TABLE_MAX_LENGTH if segment_type == "table" else self.max_length
        if segment_type != "table":
            # Find the last complete sentence in the text for cleaner output
            # This is especially important when HTML truncation cuts mid-sentence
            truncated_text = self._find_last_complete_sentence(raw_text, effective_max)
            if truncated_text and len(truncated_text) >= self.min_length:
                raw_text = truncated_text

        # Extract section path and heading
        section_path, section_heading = self._extract_section_info(element)

        # Generate CSS selector for DOM location (SEG10)
        html_selector = self._generate_css_selector(element)

        # Build segment
        # Note: char_start_offset and char_end_offset are intentionally None.
        # Offset computation was removed (INV-1-FIX-v2) as it caused O(n*m)
        # performance issues and the data was not used by any feature.
        # Use html_selector for source location if needed.
        segment = SourceSegment(
            filing_id=filing_id,
            segment_type=segment_type,
            section_path=section_path,
            section_heading=section_heading,
            sequence_index=sequence_index,
            raw_text=raw_text,
            raw_html=raw_html,
            html_selector=html_selector,
            char_start_offset=None,
            char_end_offset=None,
        )

        # Validate text/HTML consistency (HRV-22 monitoring)
        self._validate_text_html_consistency(raw_text, raw_html, segment_type)

        return segment

    def _validate_text_html_consistency(
        self,
        raw_text: str,
        raw_html: str | None,
        segment_type: str,
    ) -> bool:
        """
        Validate that raw_text content is consistent with raw_html.

        Checks that the text length doesn't exceed what could reasonably be
        extracted from the HTML. This detects data corruption where raw_text
        contains content that doesn't exist in raw_html (e.g., due to
        inconsistent truncation limits).

        Args:
            raw_text: The normalized text content
            raw_html: The HTML content (may be truncated)
            segment_type: Type of segment (for logging context)

        Returns:
            True if consistent, False if mismatch detected.
            Logs warning on mismatch for monitoring.
        """
        if not raw_html:
            return True  # No HTML to validate against

        try:
            # Extract text from stored HTML
            soup = BeautifulSoup(raw_html, "html.parser")
            html_text = soup.get_text()

            # Check if raw_text is significantly longer than extractable from HTML
            # Allow 50 char tolerance for whitespace normalization differences
            if len(raw_text) > len(html_text) + 50:
                logger.warning(
                    f"HRV-22: Text/HTML mismatch detected: raw_text={len(raw_text)} chars, "
                    f"extractable from raw_html={len(html_text)} chars, "
                    f"segment_type={segment_type}"
                )
                return False
        except Exception as e:
            logger.debug(f"Could not validate text/HTML consistency: {e}")

        return True

    def _split_composite_segment(
        self,
        segment: SourceSegment,
        parsed_element: Tag | None = None
    ) -> list[SourceSegment]:
        """
        Split a segment containing both text and tables into separate segments.

        This prevents false positives where keywords in text are matched to numbers
        in tables (or vice versa) during candidate generation.

        Args:
            segment: Original segment that may contain mixed text and table content
            parsed_element: Optional pre-parsed Tag element to avoid re-parsing raw_html.
                           If provided, uses this element directly instead of parsing.
                           This is a performance optimization (SEG9) - the element is
                           temporarily cached during extraction and cleared after splitting.

        Returns:
            List of segments (single segment if no split needed, multiple if split)
        """
        # Quick check: does the segment contain table tags?
        if not segment.raw_html or "<table" not in segment.raw_html.lower():
            return [segment]

        # Check if segment is already a table - don't split tables themselves
        if segment.segment_type == "table":
            return [segment]

        try:
            # Use cached element if available, otherwise parse raw_html (SEG9)
            # This avoids redundant BeautifulSoup parsing for composite segments
            if parsed_element is not None and isinstance(parsed_element, Tag):
                soup = parsed_element
            else:
                soup = BeautifulSoup(segment.raw_html, "html.parser")

            # Find all table elements
            # First, get all tables
            all_tables = soup.find_all("table")

            # Filter out tables that are nested within other tables
            tables = []
            for table in all_tables:
                # Check if this table has a table ancestor (other than itself)
                parent_tables = table.find_parents("table")
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
                    text_soup = BeautifulSoup(text_before, "html.parser")
                    text_content = self._normalize_text(text_soup.get_text())
                    if text_content.strip():  # Only add non-empty text
                        content_pieces.append(("text", text_before, text_content))

                # Add the table with [ROW]/[CELL] markers for row-aware matching
                table_soup = BeautifulSoup(table_html, "html.parser")
                table_elem = table_soup.find("table")
                if table_elem:
                    table_text = self._extract_table_text_with_markers(table_elem)
                else:
                    table_text = self._normalize_text(table_soup.get_text())
                if table_text.strip():  # Only add non-empty tables
                    content_pieces.append(("table", table_html, table_text))

                current_pos = end_pos

            # Extract text after last table
            if current_pos < len(full_html):
                text_after = full_html[current_pos:]
                text_soup = BeautifulSoup(text_after, "html.parser")
                text_content = self._normalize_text(text_soup.get_text())
                if text_content.strip():  # Only add non-empty text
                    content_pieces.append(("text", text_after, text_content))

            # If we only have one piece, return the original segment
            if len(content_pieces) <= 1:
                return [segment]

            # Create new segments from the pieces
            split_segments = []
            base_sequence = segment.sequence_index

            for i, (piece_type, html_content, text_content) in enumerate(content_pieces):
                # Determine segment type
                seg_type = "table" if piece_type == "table" else "paragraph"

                # Check if text meets minimum length for paragraphs
                if seg_type == "paragraph" and len(text_content) < self.min_length:
                    continue

                # HRV-22 FIX: Truncate HTML first, then extract text from it
                # This ensures raw_text only contains content that exists in raw_html
                effective_max = self.TABLE_MAX_LENGTH if seg_type == "table" else self.max_length
                if html_content and len(html_content) > effective_max:
                    html_content = html_content[:effective_max]
                    # Re-extract text from truncated HTML to ensure consistency
                    truncated_soup = BeautifulSoup(html_content, "html.parser")
                    if seg_type == "table":
                        table_elem = truncated_soup.find("table")
                        if table_elem:
                            text_content = self._extract_table_text_with_markers(table_elem)
                        else:
                            text_content = self._normalize_text(truncated_soup.get_text())
                    else:
                        text_content = self._normalize_text(truncated_soup.get_text())
                elif len(text_content) > effective_max:
                    # Text somehow longer than HTML limit - truncate
                    text_content = text_content[:effective_max]

                # Create new segment with fractional sequence index
                new_segment = SourceSegment(
                    filing_id=segment.filing_id,
                    segment_type=seg_type,
                    section_path=segment.section_path,
                    section_heading=segment.section_heading,
                    sequence_index=base_sequence + (i * 0.1),  # Use fractional increments
                    raw_text=text_content,
                    raw_html=html_content if html_content else None,
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

        # Handle new element types (SEG8)
        if element.name == "blockquote":
            return "blockquote"
        if element.name == "pre":
            return "preformatted"
        if element.name == "figure":
            return "figure"

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

    def _extract_figure_text(self, element: Tag) -> str:
        """
        Extract text from figure element including alt text and captions.

        Combines:
        - Alt text from <img> elements
        - Text from <figcaption> elements
        - Any other visible text in the figure

        Args:
            element: BeautifulSoup Tag element (figure)

        Returns:
            Combined text from figure element
        """
        texts = []

        # Get alt text from all images
        for img in element.find_all("img"):
            alt = img.get("alt", "")
            if alt and isinstance(alt, str):
                texts.append(alt.strip())

        # Get figcaption text
        for figcaption in element.find_all("figcaption"):
            caption_text = figcaption.get_text()
            if caption_text:
                texts.append(caption_text.strip())

        # If we have specific extracted content, use it
        if texts:
            return " ".join(texts)

        # Fallback to standard get_text() for any other text content
        return element.get_text()

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

    def _matches_patterns(self, text: str, patterns: list[str]) -> bool:
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

    def _extract_table_text_with_markers(self, element: Tag) -> str:
        """
        Extract table text with cell/row boundary markers.

        Preserves table cell boundaries by adding [CELL] and [ROW] markers
        during HTML-to-text conversion. This prevents adjacent numeric values
        from merging together when table structure is lost.

        Args:
            element: BeautifulSoup Tag element (table or element containing table)

        Returns:
            Text with cell boundaries marked: "Value [CELL] 171% [CELL] 152% [ROW] ..."
            Empty string if table has no content or parsing fails

        Marker format:
            - Cell separator: " [CELL] " between cells in same row
            - Row separator: " [ROW] " between table rows
            - Empty/whitespace-only cells are skipped (no empty markers)
            - No markers at start or end of text (only between content)

        Example:
            Input HTML:
                <table>
                  <tr><td>Metric</td><td>2023</td><td>2022</td></tr>
                  <tr><td>Retention Rate</td><td>171%</td><td>152%</td></tr>
                </table>

            Output text:
                "Metric [CELL] 2023 [CELL] 2022 [ROW] Retention Rate [CELL] 171% [CELL] 152%"
        """
        try:
            # Find the table element (may be element itself or nested)
            table = element if element.name == "table" else element.find("table")

            if not table:
                # No table found - fall back to standard normalization
                logger.debug("No table found in element, using standard normalization")
                return self._normalize_text(element.get_text())

            # Find all table rows
            tr_elements = table.find_all("tr", recursive=True)

            if not tr_elements:
                # Table with no rows - return empty string
                logger.debug("Table found but no <tr> elements")
                return ""

            # Extract text from each row
            row_texts = []
            for tr in tr_elements:
                # Find all cells (both <td> and <th>)
                cells = tr.find_all(["td", "th"], recursive=False)

                if not cells:
                    # Row with no cells - skip it
                    continue

                # Extract and normalize text from each cell
                cell_texts = []
                for cell in cells:
                    cell_text = self._normalize_text(cell.get_text())
                    # Skip empty cells (no empty markers)
                    if cell_text:
                        cell_texts.append(cell_text)

                # Join cells with [CELL] marker
                if cell_texts:
                    row_text = " [CELL] ".join(cell_texts)
                    row_texts.append(row_text)

            # Join rows with [ROW] marker
            if row_texts:
                return " [ROW] ".join(row_texts)
            else:
                # Empty table - no content
                return ""

        except Exception as e:
            # Any error in table parsing should fall back to standard normalization
            logger.warning(f"Error extracting table text with markers: {e}, falling back to standard normalization")
            return self._normalize_text(element.get_text())

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
        if segment.segment_type == "table":
            return segment

        if not segment.raw_text:
            return segment

        boundaries = self._boundary_detector.find_sentence_boundaries(
            segment.raw_text, segment_type=segment.segment_type
        )

        # Store as list of (start, end) tuples
        segment.sentence_boundaries = [(b.start, b.end) for b in boundaries]

        return segment

    def _apply_sentence_detection_parallel(
        self, segments: list[SourceSegment]
    ) -> list[SourceSegment]:
        """
        Apply sentence detection in parallel for performance (SEG11).

        Uses ThreadPoolExecutor to process segments concurrently, achieving
        2-4x speedup for large filings (200+ segments). Falls back to
        sequential processing on error.

        Thread Safety: BoundaryDetector.find_sentence_boundaries() is stateless
        and thread-safe - it only uses input parameters and local variables,
        with no shared mutable state.

        Args:
            segments: List of segments to process

        Returns:
            Processed segments (same list, mutated in place)
        """
        try:
            with ThreadPoolExecutor(
                max_workers=self.PARALLEL_SENTENCE_DETECTION_WORKERS
            ) as executor:
                # map() preserves order and processes in parallel
                # Returns an iterator, we consume it to trigger execution
                list(executor.map(self._apply_sentence_detection, segments))
        except Exception as e:
            # Fallback to sequential processing on any ThreadPoolExecutor failure
            logger.warning(f"Parallel sentence detection failed, using sequential: {e}")
            for segment in segments:
                self._apply_sentence_detection(segment)

        return segments

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
                return text[: boundary.end].rstrip()

        # No complete sentence fits - fall back to truncation at max_length
        # This should be rare (would mean first sentence is > max_length)
        logger.debug(
            f"No complete sentence fits within {max_length} chars, " f"truncating mid-sentence"
        )
        return text[:max_length]

    def _find_last_complete_sentence(self, text: str, max_length: int) -> str:
        """
        Find text up to the last complete sentence.

        Unlike _truncate_at_sentence_boundary (which only truncates when text > max_length),
        this method always ensures the text ends at a sentence boundary. This is used
        after HTML truncation to ensure clean sentence endings (HRV-22).

        Args:
            text: Text to potentially trim
            max_length: Maximum allowed length

        Returns:
            Text ending at a complete sentence, or original if text already ends properly
        """
        if not text:
            return text

        # Check if text already ends with sentence-ending punctuation
        stripped = text.rstrip()
        if stripped and stripped[-1] in ".!?":
            # Text already ends at sentence boundary
            return text if len(text) <= max_length else self._truncate_at_sentence_boundary(
                text, max_length
            )

        # Text was cut mid-sentence - find the last complete sentence
        sentences = self._boundary_detector.find_sentence_boundaries(text)

        if not sentences:
            # No sentences found - return as-is
            return text

        # Check if the last detected sentence is complete
        last_boundary = sentences[-1]
        last_sentence_text = text[last_boundary.start : last_boundary.end].rstrip()

        if last_sentence_text and last_sentence_text[-1] in ".!?":
            # Last sentence is complete - return up to its end
            result = text[: last_boundary.end].rstrip()
            return result if len(result) <= max_length else self._truncate_at_sentence_boundary(
                result, max_length
            )

        # Last sentence is incomplete - find the previous complete sentence
        for boundary in reversed(sentences[:-1]):
            sentence_text = text[boundary.start : boundary.end].rstrip()
            if sentence_text and sentence_text[-1] in ".!?":
                result = text[: boundary.end].rstrip()
                return result if len(result) <= max_length else self._truncate_at_sentence_boundary(
                    result, max_length
                )

        # No complete sentences found - return original
        return text

    def _extract_last_sentence(self, text: str) -> str | None:
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
        last_sentence = text[last_boundary.start : last_boundary.end].strip()

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

    def _merge_definition_segments(self, segments: list[SourceSegment]) -> list[SourceSegment]:
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

        merged: list[SourceSegment] = []
        i = 0

        while i < len(segments):
            segment = segments[i]

            # Only try to merge paragraph-type segments (not tables, etc.)
            if segment.segment_type not in (
                "paragraph",
                "definition_block",
            ) or not self._starts_definition(segment.raw_text):
                merged.append(segment)
                i += 1
                continue

            # Found a definition start - look ahead for continuations
            merged_text = segment.raw_text
            merged_html = segment.raw_html or ""
            merge_count = 1
            j = i + 1

            while (
                j < len(segments)
                and merge_count < self.DEFINITION_LOOKAHEAD_MAX
                and len(merged_text) < self.DEFINITION_MAX_COMBINED_LENGTH
            ):

                next_seg = segments[j]

                # Only merge same-type segments that look like continuations
                if next_seg.segment_type not in ("paragraph", "definition_block"):
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
                # HRV-22 FIX: Truncate HTML first, then extract text from it
                # This ensures raw_text only contains content that exists in raw_html
                if merged_html:
                    truncated_html = merged_html[: self.max_length]
                    # Re-extract text from truncated HTML to ensure consistency
                    truncated_soup = BeautifulSoup(truncated_html, "html.parser")
                    segment.raw_text = self._normalize_text(truncated_soup.get_text())
                    segment.raw_html = truncated_html
                else:
                    segment.raw_text = merged_text.strip()
                    segment.raw_html = None
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
        if segment.segment_type != "table":
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

    def _create_table_summary(self, raw_html: str | None, raw_text: str) -> str:
        """
        Create a summary of a large table with tri-region sampling.

        For tables >3000 chars, samples from beginning, middle, and end
        to provide better coverage of table content.

        Includes:
        - Header row(s) if available
        - Row count estimate
        - Sampled text from beginning, middle, and end regions

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
                soup = BeautifulSoup(raw_html, "html.parser")
                table = soup.find("table")

                if table:
                    # Get header row
                    thead = table.find("thead")
                    header_row = None
                    if thead:
                        header_row = thead.find("tr")
                    else:
                        # Try first row with th elements
                        first_row = table.find("tr")
                        if first_row and first_row.find("th"):
                            header_row = first_row

                    if header_row:
                        headers = [
                            self._normalize_text(cell.get_text())
                            for cell in header_row.find_all(["th", "td"])
                        ]
                        headers = [h for h in headers if h]  # Remove empty
                        if headers:
                            summary_parts.append(f"[Table headers: {' | '.join(headers[:10])}]")

                    # Count rows
                    all_rows = table.find_all("tr")
                    row_count = len(all_rows)
                    summary_parts.append(f"[{row_count} rows total]")

            except Exception as e:
                logger.debug(f"Could not parse table HTML for summary: {e}")

        # Include sampled raw text for searchability
        max_summary_text = 3000
        if len(raw_text) > max_summary_text:
            # Tri-region sampling for better coverage
            sample_size = 1000

            # Beginning sample (~1000 chars)
            first_sample = self._truncate_at_word_boundary(
                raw_text[:sample_size], sample_size
            )

            # Calculate middle position, ensuring no overlap with beginning
            text_len = len(raw_text)
            mid_start = max(sample_size, text_len // 2 - sample_size // 2)
            mid_end = min(text_len - sample_size, mid_start + sample_size)

            # Check if middle region would overlap with beginning or end
            if mid_start >= text_len - sample_size:
                # Text not long enough for distinct middle - skip middle sample
                middle_sample = ""
            else:
                middle_sample = self._truncate_at_word_boundary(
                    raw_text[mid_start:mid_end], sample_size
                )

            # End sample (~1000 chars)
            end_start = max(mid_end if middle_sample else sample_size, text_len - sample_size)
            last_sample = raw_text[end_start:].strip()
            # Truncate at word boundary from the start for end sample
            if len(last_sample) > sample_size:
                # Find first space after position 0 to start at word boundary
                first_space = last_sample.find(" ")
                if 0 < first_space < 100:
                    last_sample = last_sample[first_space + 1:]

            # Build the summary with markers
            summary_parts.append(first_sample)
            if middle_sample:
                summary_parts.append("...[middle sample]...")
                summary_parts.append(middle_sample)
            summary_parts.append("...[end sample]...")
            summary_parts.append(last_sample)
        else:
            summary_parts.append(raw_text)

        return " ".join(summary_parts)

    def _truncate_at_word_boundary(self, text: str, max_length: int) -> str:
        """
        Truncate text at a word boundary.

        Args:
            text: Text to truncate
            max_length: Maximum length

        Returns:
            Truncated text ending at a word boundary
        """
        if len(text) <= max_length:
            return text.rstrip()

        truncated = text[:max_length].rstrip()
        # Look for whitespace within last 100 characters for clean break
        last_space = truncated.rfind(" ")
        if last_space > max_length - 100:
            truncated = truncated[:last_space]

        return truncated

    # =========================================================================
    # Context Enrichment Methods (Phase 5 of redesign)
    # =========================================================================

    def _add_context_overlap(self, segments: list[SourceSegment]) -> list[SourceSegment]:
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
            if prev.segment_type == "table":
                continue

            # Extract last sentence from previous segment
            last_sentence = self._extract_last_sentence(prev.raw_text)

            if last_sentence and len(last_sentence) <= max_context_length:
                segments[i].context_prefix = last_sentence

        return segments

    def _calculate_document_positions(self, segments: list[SourceSegment]) -> list[SourceSegment]:
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
        intro_text: str | None = None,
    ) -> list[SourceSegment]:
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
        list_items = list_element.find_all("li", recursive=False)

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

            # Generate CSS selector for DOM location (SEG10)
            html_selector = self._generate_css_selector(li)

            segment = SourceSegment(
                filing_id=filing_id,
                segment_type="list_item",
                section_path=section_path,
                section_heading=section_heading,
                sequence_index=base_sequence + (i * 0.1),  # Fractional indices
                raw_text=text,
                raw_html=str(li)[: self.max_length],
                html_selector=html_selector,
                context_prefix=intro_text,  # Include intro as context
                char_start_offset=None,
                char_end_offset=None,
            )

            segments.append(segment)

        return segments

    def _get_list_intro_text(self, list_element: Tag) -> str | None:
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
        prev_sibling = list_element.find_previous_sibling(["p", "div"])

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

    def _build_heading_cache(self, main_content: Tag) -> list[tuple[int, str, str]]:
        """
        Pre-build a cache of all headings with their source line positions.

        This is a performance optimization to avoid O(n²) find_all_previous() calls.
        We traverse the document once and store headings with their positions,
        then use binary search for O(log n) lookups.

        Also builds an element-to-position map for all descendants to enable
        O(1) position lookups.

        Args:
            main_content: The main content area of the filing

        Returns:
            List of (source_position, heading_level, heading_text) tuples,
            sorted by source_position
        """
        headings = []
        # Build position map for all elements (enables O(1) position lookup)
        self._element_position_map: dict[int, int] = {}

        for i, element in enumerate(main_content.descendants):
            # Store position for all elements
            if hasattr(element, "name"):
                self._element_position_map[id(element)] = i

            # Store headings in cache
            if hasattr(element, "name") and element.name in ["h1", "h2", "h3", "h4", "h5", "h6"]:
                heading_text = self._normalize_text(element.get_text())
                if heading_text:
                    # Skip metadata headings at cache build time
                    if heading_text.lower() not in self.METADATA_HEADINGS:
                        # Store position, level (h1=1, h2=2, etc.), and text
                        level = int(element.name[1])
                        headings.append((i, level, heading_text))

        return headings

    def _build_hierarchical_path(self, nearest_idx: int) -> str:
        """
        Build hierarchical section path from heading cache (SEG6).

        Walks backwards from the nearest heading, collecting one heading per level
        to form a complete document hierarchy path like "Item 1 > Business > Customers".

        Args:
            nearest_idx: Index of the nearest preceding heading in _heading_cache

        Returns:
            Hierarchical path string with " > " separators

        Algorithm:
            1. Start with the nearest heading
            2. Walk backwards through the cache
            3. Collect headings at higher levels (lower numbers) than the nearest
            4. Stop when h1 is collected or no more headings
            5. Build path from highest to lowest level
        """
        if nearest_idx < 0 or nearest_idx >= len(self._heading_cache):
            return ""

        # Get the nearest heading
        _, nearest_level, nearest_text = self._heading_cache[nearest_idx]

        # Collect headings: level -> text (nearest heading is always included)
        collected: dict[int, str] = {nearest_level: nearest_text}

        # Track the minimum level we've seen so far (to handle level resets)
        # A heading at level L only contributes if it's at a higher level (smaller number)
        # than the most recent heading that could affect the hierarchy
        min_level_seen = nearest_level

        # Walk backwards, collecting higher-level headings
        for i in range(nearest_idx - 1, -1, -1):
            _, level, text = self._heading_cache[i]

            # Only collect if this level is higher (smaller number) than what we've seen
            # and we haven't already collected this level
            if level < min_level_seen and level not in collected:
                collected[level] = text
                min_level_seen = level
                # Stop if we've collected h1 (can't go higher)
                if level == 1:
                    break

        # Build path from highest to lowest level (h1 -> h2 -> h3 -> ...)
        path_parts = [collected[lvl] for lvl in sorted(collected.keys())]

        # Join with separator, truncating if path exceeds 500 chars
        path = " > ".join(path_parts)
        if len(path) > 500:
            # Truncate individual parts to fit, keeping structure
            # Account for separators: (n-1) * 3 chars for " > "
            # Account for ellipsis: 3 chars per truncated part
            separator_len = (len(path_parts) - 1) * 3
            available_for_parts = 500 - separator_len
            # Each truncated part needs 3 chars for "...", so max_part_len is base + "..."
            max_part_len = max(10, (available_for_parts // len(path_parts)) - 3)
            truncated_parts = [
                p[:max_part_len] + "..." if len(p) > max_part_len else p for p in path_parts
            ]
            path = " > ".join(truncated_parts)

        return path

    def _get_section_from_cache(
        self, element: Tag | None, element_position: int
    ) -> tuple[str | None, str | None]:
        """
        Use binary search to find nearest preceding heading (SEG1) and build
        hierarchical section path (SEG6).

        This replaces the O(n) find_previous() approach with O(log n) binary search
        on the pre-built heading cache, significantly improving performance for
        large filings.

        Args:
            element: The BeautifulSoup element (kept for signature compatibility, may be None)
            element_position: Position of element in document (from _element_position_map)

        Returns:
            Tuple of (section_path, section_heading) or (None, None) if no heading found
            - section_path: Full hierarchical path (e.g., "Item 1 > Business > Customers")
            - section_heading: Just the nearest heading (e.g., "Customers")

        Note:
            Metadata headings are already filtered out during cache building.
        """
        if not self._heading_cache:
            return None, None

        # Extract positions for binary search
        positions = [pos for pos, _, _ in self._heading_cache]

        # bisect_right returns insertion point; we want the element before it
        idx = bisect.bisect_right(positions, element_position) - 1

        if idx >= 0:
            pos, level, text = self._heading_cache[idx]
            # Build hierarchical path from heading hierarchy (SEG6)
            section_path = self._build_hierarchical_path(idx)
            # section_heading remains just the nearest heading
            return section_path, text

        return None, None

    def _extract_section_info(self, element: Tag) -> tuple[str | None, str | None]:
        """
        Extract section path and heading from element's position in DOM.

        Uses pre-built heading cache with binary search for O(log n) performance.
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
        if hasattr(self, "_heading_cache") and self._heading_cache is not None:
            # Get element position from position map (O(1) lookup)
            element_position = self._element_position_map.get(id(element), -1)
            if element_position >= 0:
                return self._get_section_from_cache(element, element_position)

        # Fallback: iterate through previous headings, skipping metadata
        prev_heading = element.find_previous(["h1", "h2", "h3", "h4", "h5", "h6"])
        while prev_heading:
            heading_text = self._normalize_text(prev_heading.get_text())
            if heading_text and heading_text.lower() not in self.METADATA_HEADINGS:
                return heading_text, heading_text
            prev_heading = prev_heading.find_previous(["h1", "h2", "h3", "h4", "h5", "h6"])

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

    def get_metrics(self) -> SegmentationMetrics | None:
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
def segment_filing_html(filing_id: int, html_path: str) -> list[SourceSegment]:
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
