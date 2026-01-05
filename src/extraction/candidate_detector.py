"""
Unified candidate detection for extraction and review.

This module consolidates metric detection logic from:
- src/review/candidate_generator.py
- src/extraction/value_extractor.py

Uses StructureParser (EA-1) for table-aware detection.

Key Features:
- Single CandidateDetector class for consistent detection across modules
- Integrates FalsePositiveFilter for filtering years, dates, page numbers
- Uses StructureParser for table-aware row validation
- Configurable keyword lists and distance thresholds
- DetectedCandidate dataclass with position and confidence information

Usage:
    >>> from src.extraction.candidate_detector import CandidateDetector, DetectedCandidate
    >>>
    >>> # Basic usage
    >>> detector = CandidateDetector()
    >>> text = "We have 50 million active customers"
    >>> candidates = detector.detect(text)
    >>> for c in candidates:
    ...     print(f"{c.keyword}: {c.value} (confidence={c.confidence:.2f})")
    >>>
    >>> # Table-aware detection with HTML
    >>> html = '<table><tr><td>Revenue</td><td>$100 million</td></tr></table>'
    >>> text = 'Revenue [CELL] $100 million [ROW] '
    >>> candidates = detector.detect(text=text, html=html, segment_type='table')
    >>> print(f"Found {len(candidates)} candidates")

Configuration:
    >>> # Disable false positive filtering
    >>> detector = CandidateDetector(use_false_positive_filter=False)
    >>>
    >>> # Custom keywords
    >>> detector = CandidateDetector(keywords=['custom', 'keywords'])
    >>>
    >>> # Disable row validation for tables
    >>> detector = CandidateDetector(use_row_validation=False)

Integration Notes:
    This module is the foundation for EA-2 (unified detection). It does NOT
    replace existing detection in CandidateGenerator or ValueExtractor - that
    integration happens in Phase 2 (separate tasks).

See Also:
    - src/extraction/structure_parser.py: StructureParser for table parsing
    - src/review/candidate_generator.py: Original review detection
    - src/extraction/value_extractor.py: Original extraction detection
"""

import logging
import re
from dataclasses import dataclass
from decimal import Decimal

from src.extraction.structure_parser import StructureParser
from src.review.false_positive_filter import FalsePositiveFilter
from src.review.number_parsing import NumberMatch, NumberParser

logger = logging.getLogger(__name__)


# =============================================================================
# Data Classes
# =============================================================================


@dataclass
class DetectedCandidate:
    """A detected metric candidate with position information.

    Attributes:
        keyword: The matched keyword text (e.g., "active customers")
        keyword_position: Character position of keyword in text
        value: Parsed numeric value as Decimal
        value_position: Character position of value in text
        unit: Detected unit (e.g., "count", "currency", "percentage")
        confidence: Confidence score (0.0-1.0)
        same_row: True if keyword and value are in the same table row
        same_cell: True if keyword and value are in the same table cell
        raw_text: Surrounding context text for debugging
    """

    keyword: str
    keyword_position: int
    value: Decimal
    value_position: int
    unit: str | None
    confidence: float
    same_row: bool
    same_cell: bool
    raw_text: str


# =============================================================================
# Default Keywords
# =============================================================================

# Default metric keywords from existing implementations
# These are intentionally high-level - specific patterns are in MetricClassifier
DEFAULT_KEYWORDS: list[str] = [
    # Customer metrics
    "customers",
    "active customers",
    "paying customers",
    "total customers",
    "enterprise customers",
    # User metrics
    "users",
    "active users",
    "daily active users",
    "monthly active users",
    "dau",
    "mau",
    "wau",
    # Revenue metrics
    "revenue",
    "arr",
    "mrr",
    "arpu",
    "gmv",
    # Retention metrics
    "retention",
    "net revenue retention",
    "gross revenue retention",
    "nrr",
    "grr",
    "churn",
    # Engagement metrics
    "engagement",
    "conversion",
    "subscribers",
    # Growth metrics
    "growth",
    "acquisition",
    "ltv",
    "cac",
]


# =============================================================================
# CandidateDetector Class
# =============================================================================


class CandidateDetector:
    """Unified metric candidate detection for extraction and review.

    This class consolidates detection logic that was previously duplicated
    between CandidateGenerator (review module) and ValueExtractor (extraction
    module). It provides a single, consistent interface for finding metric
    candidates in text.

    Key capabilities:
    - Number detection with FalsePositiveFilter integration
    - Keyword matching with configurable distance threshold
    - Table-aware detection using StructureParser
    - Confidence scoring based on proximity and context

    Attributes:
        MAX_KEYWORD_DISTANCE: Maximum characters between keyword and value
        use_fp_filter: Whether to apply false positive filtering
        use_row_validation: Whether to enforce same-row constraint for tables
        keywords: List of keywords to search for
    """

    MAX_KEYWORD_DISTANCE: int = 100  # Max chars between keyword and value

    def __init__(
        self,
        use_false_positive_filter: bool = True,
        use_row_validation: bool = True,
        keywords: list[str] | None = None,
        max_keyword_distance: int = 100,
    ) -> None:
        """Initialize the candidate detector.

        Args:
            use_false_positive_filter: Whether to filter false positives
                (years, dates, page numbers). Default: True
            use_row_validation: Whether to require keyword and value in
                same table row for table segments. Default: True
            keywords: List of keywords to search for. If None, uses
                DEFAULT_KEYWORDS.
            max_keyword_distance: Maximum character distance between
                keyword and value for a valid match. Default: 100
        """
        self.use_fp_filter = use_false_positive_filter
        self.use_row_validation = use_row_validation
        self.keywords = keywords if keywords is not None else DEFAULT_KEYWORDS
        self.MAX_KEYWORD_DISTANCE = max_keyword_distance

        # Initialize components
        self._fp_filter: FalsePositiveFilter | None = (
            FalsePositiveFilter() if use_false_positive_filter else None
        )
        self._number_parser = NumberParser()

        # Pre-compile keyword patterns for efficiency
        self._keyword_patterns: list[tuple[re.Pattern[str], str]] = []
        for kw in self.keywords:
            pattern = re.compile(rf"\b{re.escape(kw)}\b", re.IGNORECASE)
            self._keyword_patterns.append((pattern, kw))

    def detect(
        self,
        text: str,
        html: str | None = None,
        segment_type: str = "paragraph",
    ) -> list[DetectedCandidate]:
        """Detect metric candidates in text.

        This is the main detection method. It finds all numbers in text,
        filters false positives, matches them with nearby keywords, and
        returns DetectedCandidate objects.

        Args:
            text: The text content to analyze
            html: Optional HTML for structure-aware detection in tables
            segment_type: Type of segment ("paragraph", "table", etc.)

        Returns:
            List of detected candidates with positions and confidence

        Examples:
            >>> detector = CandidateDetector()
            >>> candidates = detector.detect("We have 50 million customers")
            >>> len(candidates)
            1
            >>> candidates[0].keyword
            'customers'
            >>> candidates[0].value
            Decimal('50000000')
        """
        if not text or not text.strip():
            return []

        # Parse structure if HTML available and segment is table
        parser: StructureParser | None = None
        if html and segment_type == "table":
            try:
                temp_parser = StructureParser(html)
                # Only use parser if it actually found table structure
                if temp_parser.is_table():
                    parser = temp_parser
                else:
                    logger.debug("HTML parsed but no table structure found")
            except Exception as e:
                logger.warning(f"Failed to parse HTML structure: {e}")
                parser = None

        # Find all numbers in text
        numbers = self._number_parser.find_numbers(text)

        # Apply false positive filter
        if self._fp_filter:
            filtered_numbers: list[NumberMatch] = []
            for num in numbers:
                is_fp, reason = self._fp_filter.is_false_positive(text, num)
                if not is_fp:
                    filtered_numbers.append(num)
                else:
                    logger.debug(
                        f"Filtered false positive: {num.raw_text!r} ({reason})"
                    )
            numbers = filtered_numbers

        if not numbers:
            return []

        # Find all keywords in text
        keyword_positions = self._find_keywords(text)

        if not keyword_positions:
            return []

        # Match keywords to numbers
        candidates: list[DetectedCandidate] = []
        for num in numbers:
            for kw, kw_pos in keyword_positions:
                if self._is_valid_match(num, kw_pos, text, parser):
                    same_row = self._check_same_row(num.start, kw_pos, parser)
                    same_cell = self._check_same_cell(num.start, kw_pos, parser)
                    confidence = self._calculate_confidence(
                        num, kw_pos, same_row, same_cell
                    )

                    # Extract context for debugging
                    context_start = max(0, min(kw_pos, num.start) - 20)
                    context_end = min(len(text), max(kw_pos + len(kw), num.end) + 20)
                    raw_context = text[context_start:context_end]

                    candidates.append(
                        DetectedCandidate(
                            keyword=kw,
                            keyword_position=kw_pos,
                            value=num.value if num.value is not None else Decimal(0),
                            value_position=num.start,
                            unit=num.unit,
                            confidence=confidence,
                            same_row=same_row,
                            same_cell=same_cell,
                            raw_text=raw_context,
                        )
                    )

        return candidates

    def detect_in_segment(self, segment: dict[str, object]) -> list[DetectedCandidate]:
        """Convenience method to detect from segment dict.

        This method extracts the relevant fields from a segment dictionary
        (as returned by database queries) and calls detect().

        Args:
            segment: Segment dictionary with keys:
                - raw_text: The text content
                - raw_html: Optional HTML content
                - segment_type: Type of segment

        Returns:
            List of detected candidates
        """
        raw_text = segment.get("raw_text")
        text = raw_text if isinstance(raw_text, str) else ""

        raw_html = segment.get("raw_html")
        html = raw_html if isinstance(raw_html, str) else None

        segment_type_val = segment.get("segment_type")
        segment_type = segment_type_val if isinstance(segment_type_val, str) else "paragraph"

        return self.detect(
            text=text,
            html=html,
            segment_type=segment_type,
        )

    def _find_keywords(self, text: str) -> list[tuple[str, int]]:
        """Find all keyword positions in text.

        Args:
            text: The text to search

        Returns:
            List of (keyword, position) tuples, sorted by position
        """
        results: list[tuple[str, int]] = []
        for pattern, kw in self._keyword_patterns:
            for match in pattern.finditer(text):
                results.append((kw, match.start()))

        # Sort by position
        results.sort(key=lambda x: x[1])
        return results

    def _is_valid_match(
        self,
        num: NumberMatch,
        kw_pos: int,
        text: str,
        parser: StructureParser | None,
    ) -> bool:
        """Check if keyword-number pair is a valid match.

        A match is valid if:
        1. The distance between keyword and number is within threshold
        2. For tables with row validation: keyword and value are in same row

        Args:
            num: The NumberMatch to check
            kw_pos: Position of the keyword
            text: The full text (for context)
            parser: Optional StructureParser for tables

        Returns:
            True if the match is valid, False otherwise
        """
        distance = abs(num.start - kw_pos)
        if distance > self.MAX_KEYWORD_DISTANCE:
            return False

        # For tables, require same row if row validation enabled
        if parser and self.use_row_validation:
            if not parser.are_in_same_row(kw_pos, num.start):
                return False

        return True

    def _check_same_row(
        self, pos1: int, pos2: int, parser: StructureParser | None
    ) -> bool:
        """Check if two positions are in the same table row.

        Args:
            pos1: First position
            pos2: Second position
            parser: StructureParser (may be None for non-table content)

        Returns:
            True if in same row or no table structure. False if cross-row.
        """
        if parser:
            result: bool = parser.are_in_same_row(pos1, pos2)
            return result
        # For non-table content, assume same row (no structure to check)
        return True

    def _check_same_cell(
        self, pos1: int, pos2: int, parser: StructureParser | None
    ) -> bool:
        """Check if two positions are in the same table cell.

        Args:
            pos1: First position
            pos2: Second position
            parser: StructureParser (may be None for non-table content)

        Returns:
            True if in same cell or no table structure. False if different cells.
        """
        if parser:
            result: bool = parser.are_in_same_cell(pos1, pos2)
            return result
        # For non-table content, assume same cell (no structure to check)
        return True

    def _calculate_confidence(
        self,
        num: NumberMatch,
        kw_pos: int,
        same_row: bool,
        same_cell: bool,
    ) -> float:
        """Calculate confidence score for a candidate.

        Confidence is based on:
        - Base score: 0.5
        - Proximity bonus: +0.3 (very close) to +0.15 (close)
        - Same cell bonus: +0.15
        - Same row bonus: +0.05 (if not same cell)

        Args:
            num: The NumberMatch
            kw_pos: Keyword position
            same_row: Whether keyword and value are in same row
            same_cell: Whether keyword and value are in same cell

        Returns:
            Confidence score between 0.0 and 1.0
        """
        base = 0.5
        distance = abs(num.start - kw_pos)

        # Proximity bonus
        if distance < 20:
            base += 0.3
        elif distance < 50:
            base += 0.15

        # Structure bonuses
        if same_cell:
            base += 0.15
        elif same_row:
            base += 0.05

        return min(1.0, base)
