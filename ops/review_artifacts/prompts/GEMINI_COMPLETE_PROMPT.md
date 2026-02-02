# Gemini Code Review: All 6 Dimensions

**Gemini 1.5 Pro has ~1M token context - use this single prompt to review all dimensions at once.**

---

You are a comprehensive code reviewer analyzing a Python SEC filing extraction system. Review all 6 dimensions in a single pass.

## Project Overview

**Purpose**: Extract customer metrics (retention, churn, ARR, cohort data) from SEC S-1/F-1 IPO filings to support the Customer Metrics Accounting Standards Board (CMASB).

**Scale**:
- 39,847 LOC source code
- 81,244 LOC tests (2:1 ratio)
- 81.57% test coverage
- 7,304 target filings (2015-2025)
- Processing: 9-17 seconds per filing

**Current Performance**:
- Precision: 91%
- Recall: 85%
- F1: 88%

## Static Analysis Summary

### Complexity Hotspots (Top 10)

| Rank | Function | CC | File |
|------|----------|-----|------|
| 1 | `_process_segment` | 57 | candidate_generator.py:481 |
| 2 | `find_keywords_near_number` | 46 | keyword_matching.py:523 |
| 3 | `bulk_insert_review_candidates` | 42 | db.py:1421 |
| 4 | `_generate_two_feature_patterns` | 38 | pattern_analyzer.py:1600 |
| 5 | `segment_filing` | 37 | html_segmenter.py:168 |
| 6 | `_validate_config` | 35 | keyword_config.py:82 |
| 7 | `_parse_table_row` | 34 | value_extractor.py:1179 |
| 8 | `is_false_positive` | 32 | false_positive_filter.py:722 |
| 9 | `_split_composite_segment` | 32 | html_segmenter.py:795 |
| 10 | `discover_patterns` | 31 | pattern_analyzer.py:939 |

### Maintainability (MI=0 means unmaintainable)

| File | LOC | MI Score |
|------|-----|----------|
| db.py | 4,006 | 0.0 |
| html_segmenter.py | 2,028 | 0.0 |
| pattern_analyzer.py | 2,544 | 0.0 |

### Test Failures

**19 failing tests** in `tests/unit/web/test_api_images_routes.py` - all returning 409 CONFLICT.

### Coverage Gaps

- extraction_v2/: 0% (new pipeline)
- value_extractor.py: 66% (core extraction)

## Architecture Overview

```
src/
├── infra/           # DB (4,006 LOC), HTTP, SEC client
├── extraction/      # V1 pipeline (20 files, production)
├── extraction_v2/   # V2 pipeline (6 files, 0% coverage)
├── review/          # Human review (20 files, 98% coverage)
├── web/             # Flask UI
└── llm/             # OpenAI integration
```

**Pipeline Flow**:
```
HTML → Segmentation → Classification → Enrichment → Value Extraction (LLM) → Quality Scoring → DB
```

**Known Issues**:
1. Circular dependency: extraction ↔ review
2. V1 vs V2 strategy undefined
3. db.py monolith (4,006 LOC, 50+ methods)

## Dimension-Specific Questions

### D1: Architecture
1. Is db.py (4,006 LOC) acceptable? How to decompose?
2. What's the V1 → V2 migration strategy?
3. How serious is the circular dependency?

### D2: Extraction Quality
1. What causes 9% false positives?
2. What causes 15% false negatives?
3. Is table row estimation reliable?
4. Is the 170+ entry LLM mapping sustainable?

### D3: Code Quality
1. How should CC=57 `_process_segment` be refactored?
2. Which modules need mypy --strict?
3. Are error handling patterns consistent?

### D4: Testing
1. Why are 19 image route tests failing?
2. Why is extraction_v2 at 0% coverage?
3. Is 12-company gold standard representative?

### D5: Performance
1. Can LLM caching reduce the 50-70% bottleneck?
2. What's blocking filing parallelization?
3. Are there N+1 query patterns?

### D6: Security
1. Is no authentication acceptable?
2. How bad is the weak SECRET_KEY default?
3. Should APIs have CSRF/rate limiting?

## Output Format

Return findings for ALL 6 dimensions in a single JSON response:

```json
{
  "review_summary": {
    "overall_health": "A-F grade",
    "critical_count": 0,
    "high_count": 0,
    "medium_count": 0,
    "low_count": 0,
    "top_3_priorities": ["...", "...", "..."]
  },
  "dimensions": {
    "D1_ARCHITECTURE": {
      "findings": [
        {
          "id": "M-D1-001",
          "severity": "Critical|High|Medium|Low",
          "title": "...",
          "description": "...",
          "file": "...",
          "recommendation": "...",
          "effort": "XS|S|M|L|XL"
        }
      ],
      "summary": "..."
    },
    "D2_EXTRACTION": { ... },
    "D3_CODE_QUALITY": { ... },
    "D4_TESTING": { ... },
    "D5_PERFORMANCE": { ... },
    "D6_SECURITY": { ... }
  },
  "cross_cutting_concerns": [
    {
      "theme": "...",
      "affected_dimensions": ["D1", "D3"],
      "recommendation": "..."
    }
  ]
}
```

Provide 5-10 findings per dimension (30-60 total), with emphasis on cross-cutting concerns that span multiple dimensions.


---

# SOURCE CODE FOR REVIEW


# Source Code Bundle for Gemini Review

This file contains the critical source code for the comprehensive code review.

---

## File 1: src/extraction/html_segmenter.py (Top Complexity)

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
        self, filing_id: int, html_path: str, raise_on_error: bool = False
    ) -> list[SourceSegment]:
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
                raise HTMLParsingError(
                    msg, filing_id=filing_id, html_path=str(validated_path)
                ) from e
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

    def _read_html_file(self, html_path: str) -> str | None:
        """DEPRECATED: Use _read_html_file_with_encoding() instead.

        Kept for backward compatibility with external callers.
        """
        try:
            content, _ = self._read_html_file_with_encoding(html_path)
            return content
        except EncodingError:
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


---

## File 2: src/extraction/keyword_config.py

"""
Keyword Configuration Loader

Loads metric keyword patterns from external YAML configuration files,
allowing pattern updates without code changes.

Usage:
    from src.extraction.keyword_config import get_metric_keywords, get_exclusion_patterns

    # Get all keyword patterns
    keywords = get_metric_keywords()  # Returns dict[str, list[str]]

    # Get exclusion patterns
    exclusions = get_exclusion_patterns()  # Returns dict[str, list[str]]

    # Get specific patterns (for confidence bonuses)
    specific = get_specific_patterns()  # Returns list[str]
"""

from __future__ import annotations

import logging
import os
from functools import lru_cache
from pathlib import Path
from typing import Any, cast

import yaml

logger = logging.getLogger(__name__)

# Default config file location
DEFAULT_CONFIG_PATH = Path(__file__).parent.parent.parent / "config" / "metric_keywords.yaml"


class KeywordConfigError(Exception):
    """Raised when keyword configuration is invalid or cannot be loaded."""

    pass


@lru_cache(maxsize=1)
def _load_config(config_path: str | None = None) -> dict[str, Any]:
    """
    Load and cache the keyword configuration from YAML.

    Args:
        config_path: Optional path to config file. Uses default if not provided.

    Returns:
        Parsed YAML configuration dictionary.

    Raises:
        KeywordConfigError: If file cannot be loaded or parsed.
    """
    path = Path(config_path) if config_path else DEFAULT_CONFIG_PATH

    # Allow override via environment variable
    env_path = os.environ.get("METRIC_KEYWORDS_CONFIG")
    if env_path:
        path = Path(env_path)

    if not path.exists():
        raise KeywordConfigError(f"Keyword config file not found: {path}")

    try:
        with open(path, encoding="utf-8") as f:
            config = yaml.safe_load(f)
    except yaml.YAMLError as e:
        raise KeywordConfigError(f"Failed to parse keyword config: {e}") from e

    if not isinstance(config, dict):
        raise KeywordConfigError(f"Invalid config format: expected dict, got {type(config)}")

    # Validate structure
    _validate_config(config)

    logger.info(f"Loaded keyword config from {path}: {len(config)} metrics")
    return config


def _validate_config(config: dict[str, Any]) -> None:
    """
    Validate the configuration structure.

    Args:
        config: Parsed YAML configuration.

    Raises:
        KeywordConfigError: If configuration is invalid.
    """
    for metric_id, metric_config in config.items():
        # Skip YAML anchor keys (starting with underscore)
        if metric_id.startswith("_"):
            continue

        if not isinstance(metric_config, dict):
            raise KeywordConfigError(
                f"Invalid config for {metric_id}: expected dict, got {type(metric_config)}"
            )

        if "patterns" not in metric_config:
            raise KeywordConfigError(f"Missing 'patterns' for metric {metric_id}")

        patterns = metric_config["patterns"]
        if not isinstance(patterns, list) or not patterns:
            raise KeywordConfigError(
                f"Invalid 'patterns' for {metric_id}: expected non-empty list"
            )

        # Validate each pattern is a string
        for i, pattern in enumerate(patterns):
            if not isinstance(pattern, str):
                raise KeywordConfigError(
                    f"Invalid pattern {i} for {metric_id}: expected string, got {type(pattern)}"
                )

        # Validate exclusions if present
        if "exclusions" in metric_config:
            exclusions = metric_config["exclusions"]
            if not isinstance(exclusions, list):
                raise KeywordConfigError(
                    f"Invalid 'exclusions' for {metric_id}: expected list"
                )
            for i, exc in enumerate(exclusions):
                if not isinstance(exc, str):
                    raise KeywordConfigError(
                        f"Invalid exclusion {i} for {metric_id}: expected string"
                    )

        # Validate specific_patterns if present
        if "specific_patterns" in metric_config:
            specific = metric_config["specific_patterns"]
            if not isinstance(specific, list):
                raise KeywordConfigError(
                    f"Invalid 'specific_patterns' for {metric_id}: expected list"
                )

        # Validate required_context if present
        if "required_context" in metric_config:
            req_ctx = metric_config["required_context"]
            if not isinstance(req_ctx, dict):
                raise KeywordConfigError(
                    f"Invalid 'required_context' for {metric_id}: expected dict"
                )
            if "patterns" not in req_ctx:
                raise KeywordConfigError(
                    f"Missing 'patterns' in required_context for {metric_id}"
                )
            ctx_patterns = req_ctx["patterns"]
            if not isinstance(ctx_patterns, list) or not ctx_patterns:
                raise KeywordConfigError(
                    f"Invalid 'patterns' in required_context for {metric_id}: "
                    "expected non-empty list"
                )
            for j, ctx_pattern in enumerate(ctx_patterns):
                if not isinstance(ctx_pattern, str):
                    raise KeywordConfigError(
                        f"Invalid required_context pattern {j} for {metric_id}: "
                        "expected string"
                    )
            # Validate proximity_chars if present
            if "proximity_chars" in req_ctx:
                prox = req_ctx["proximity_chars"]
                if not isinstance(prox, int) or prox <= 0:
                    raise KeywordConfigError(
                        f"Invalid 'proximity_chars' in required_context for {metric_id}: "
                        "expected positive int"
                    )

        # Validate aliases if present
        if "aliases" in metric_config:
            aliases_list = metric_config["aliases"]
            if not isinstance(aliases_list, list):
                raise KeywordConfigError(
                    f"Invalid 'aliases' for {metric_id}: expected list"
                )
            for i, alias in enumerate(aliases_list):
                if not isinstance(alias, str):
                    raise KeywordConfigError(
                        f"Invalid alias {i} for {metric_id}: expected string"
                    )
                if not alias.startswith("cm_"):
                    raise KeywordConfigError(
                        f"Invalid alias '{alias}' for {metric_id}: must start with 'cm_'"
                    )

        # Validate status if present
        if "status" in metric_config:
            status = metric_config["status"]
            if not isinstance(status, str):
                raise KeywordConfigError(
                    f"Invalid 'status' for {metric_id}: expected string"
                )
            if status not in ("active", "deprecated"):
                raise KeywordConfigError(
                    f"Invalid 'status' value for {metric_id}: expected 'active' or 'deprecated'"
                )

        # Validate deprecation_reason if present
        if "deprecation_reason" in metric_config:
            reason = metric_config["deprecation_reason"]
            if not isinstance(reason, str):
                raise KeywordConfigError(
                    f"Invalid 'deprecation_reason' for {metric_id}: expected string"
                )


def _is_metric_key(key: str) -> bool:
    """Check if a key is a metric (not a YAML anchor starting with underscore)."""
    return not key.startswith("_")


def is_metric_deprecated(metric_id: str, config_path: str | None = None) -> bool:
    """
    Check if a metric is deprecated.

    Args:
        metric_id: The metric identifier to check.
        config_path: Optional path to config file.

    Returns:
        True if the metric has status='deprecated', False otherwise.
    """
    config = _load_config(config_path)
    metric_config = config.get(metric_id)
    if not metric_config:
        return False
    return metric_config.get("status") == "deprecated"


def get_active_metrics(config_path: str | None = None) -> list[str]:
    """
    Get all active (non-deprecated) metric IDs.

    Args:
        config_path: Optional path to config file.

    Returns:
        List of metric IDs that are not deprecated.
        Excludes YAML anchor keys (starting with underscore).
    """
    config = _load_config(config_path)
    return [
        metric_id
        for metric_id in config.keys()
        if _is_metric_key(metric_id) and config[metric_id].get("status") != "deprecated"
    ]


def get_metric_keywords(config_path: str | None = None) -> dict[str, list[str]]:
    """
    Get all metric keyword patterns.

    Args:
        config_path: Optional path to config file.

    Returns:
        Dictionary mapping metric_id to list of regex patterns.
        Excludes YAML anchor keys (starting with underscore).
    """
    config = _load_config(config_path)
    # Cast is safe: _validate_config() ensures patterns are list[str]
    return {
        metric_id: cast(list[str], metric_config["patterns"])
        for metric_id, metric_config in config.items()
        if _is_metric_key(metric_id)
    }


def get_exclusion_patterns(config_path: str | None = None) -> dict[str, list[str]]:
    """
    Get exclusion patterns for metrics.

    Args:
        config_path: Optional path to config file.

    Returns:
        Dictionary mapping metric_id to list of exclusion regex patterns.
        Only includes metrics that have exclusions defined.
        Excludes YAML anchor keys (starting with underscore).
    """
    config = _load_config(config_path)
    return {
        metric_id: metric_config["exclusions"]
        for metric_id, metric_config in config.items()
        if _is_metric_key(metric_id) and "exclusions" in metric_config
    }


def get_specific_patterns(config_path: str | None = None) -> list[str]:
    """
    Get all specific (multi-word) patterns that get confidence bonuses.

    Args:
        config_path: Optional path to config file.

    Returns:
        List of specific pattern strings (not compiled regex).
        Excludes YAML anchor keys (starting with underscore).
    """
    config = _load_config(config_path)
    patterns: list[str] = []
    for metric_id, metric_config in config.items():
        if _is_metric_key(metric_id) and "specific_patterns" in metric_config:
            patterns.extend(metric_config["specific_patterns"])
    return patterns


def get_required_context(config_path: str | None = None) -> dict[str, dict[str, Any]]:
    """
    Get required context patterns for metrics.

    Metrics with required_context only generate review candidates when
    at least one of the context patterns appears within proximity of the
    keyword match. This filters out revenue synonyms (GMV, TCV, etc.)
    that appear without cohort or per-customer context.

    Args:
        config_path: Optional path to config file.

    Returns:
        Dictionary mapping metric_id to required context configuration.
        Only includes metrics that have required_context defined.
        Each config contains:
        - 'patterns': list of regex patterns (at least one must match)
        - 'proximity_chars': max distance for context check (default: 1500)
        Excludes YAML anchor keys (starting with underscore).
    """
    config = _load_config(config_path)
    return {
        metric_id: metric_config["required_context"]
        for metric_id, metric_config in config.items()
        if _is_metric_key(metric_id) and "required_context" in metric_config
    }


def reload_config() -> None:
    """
    Clear the cached configuration, forcing a reload on next access.

    Useful for testing or when the config file has been updated.
    """
    _load_config.cache_clear()
    logger.info("Keyword config cache cleared")


def get_metric_config(metric_id: str, config_path: str | None = None) -> dict[str, Any] | None:
    """
    Get the full configuration for a specific metric.

    Args:
        metric_id: The metric identifier (e.g., 'cm_customer_acquisition_cost').
        config_path: Optional path to config file.

    Returns:
        Dictionary with 'patterns', optional 'exclusions', and optional 'specific_patterns'.
        Returns None if metric not found.
    """
    config = _load_config(config_path)
    return config.get(metric_id)


def list_metrics(config_path: str | None = None) -> list[str]:
    """
    List all metric IDs defined in the configuration.

    Args:
        config_path: Optional path to config file.

    Returns:
        List of metric IDs.
        Excludes YAML anchor keys (starting with underscore).
    """
    config = _load_config(config_path)
    return [k for k in config.keys() if _is_metric_key(k)]


# =============================================================================
# Metric ID Alias Functions
# =============================================================================


def get_aliases(config_path: str | None = None) -> dict[str, list[str]]:
    """
    Get aliases for metrics.

    Aliases allow a single canonical metric ID to match against alternative
    identifiers used in external sources (e.g., gold standard files).

    Args:
        config_path: Optional path to config file.

    Returns:
        Dictionary mapping canonical metric_id to list of alias IDs.
        Only includes metrics that have aliases defined.
        Excludes YAML anchor keys (starting with underscore).

    Example:
        >>> aliases = get_aliases()
        >>> aliases.get("cm_example_metric")
        ["cm_example_alias"]  # If defined in YAML
    """
    config = _load_config(config_path)
    return {
        metric_id: metric_config["aliases"]
        for metric_id, metric_config in config.items()
        if _is_metric_key(metric_id) and "aliases" in metric_config
    }


def resolve_to_canonical(metric_id: str, config_path: str | None = None) -> str:
    """
    Resolve an alias to its canonical metric ID.

    If the input is already a canonical ID or not found in aliases,
    returns the input unchanged.

    Args:
        metric_id: The metric ID to resolve (may be canonical or alias).
        config_path: Optional path to config file.

    Returns:
        The canonical metric ID if input was an alias, otherwise the input.

    Example:
        >>> resolve_to_canonical("cm_example_alias")
        "cm_example_metric"  # If alias is defined

        >>> resolve_to_canonical("cm_arr")
        "cm_arr"  # No alias, returns unchanged
    """
    aliases = get_aliases(config_path)

    # Build reverse lookup: alias -> canonical
    alias_to_canonical: dict[str, str] = {}
    for canonical, alias_list in aliases.items():
        for alias in alias_list:
            alias_to_canonical[alias] = canonical

    # Return canonical if found, otherwise return input
    return alias_to_canonical.get(metric_id, metric_id)


def get_all_equivalent_ids(metric_id: str, config_path: str | None = None) -> set[str]:
    """
    Get all equivalent metric IDs (canonical + aliases) for a given ID.

    Works whether input is canonical or alias.

    Args:
        metric_id: Any metric ID (canonical or alias).
        config_path: Optional path to config file.

    Returns:
        Set containing the canonical ID and all aliases.
        If metric has no aliases, returns set with just the input.

    Example:
        >>> get_all_equivalent_ids("cm_example_metric")
        {"cm_example_metric", "cm_example_alias"}  # If aliases defined

        >>> get_all_equivalent_ids("cm_arr")
        {"cm_arr"}  # No aliases, returns just the input
    """
    aliases = get_aliases(config_path)

    # First resolve to canonical
    canonical = resolve_to_canonical(metric_id, config_path)

    # Get all aliases for the canonical ID
    result = {canonical}
    if canonical in aliases:
        result.update(aliases[canonical])

    return result


def metrics_are_equivalent(
    metric_id_1: str, metric_id_2: str, config_path: str | None = None
) -> bool:
    """
    Check if two metric IDs are equivalent (same canonical or aliased).

    Args:
        metric_id_1: First metric ID.
        metric_id_2: Second metric ID.
        config_path: Optional path to config file.

    Returns:
        True if the metrics are equivalent (both resolve to same canonical).

    Example:
        >>> metrics_are_equivalent("cm_example_metric", "cm_example_alias")
        True  # If alias is defined

        >>> metrics_are_equivalent("cm_arr", "cm_mrr")
        False  # Different metrics
    """
    return (
        resolve_to_canonical(metric_id_1, config_path)
        == resolve_to_canonical(metric_id_2, config_path)
    )


---

## File 3: config/metric_keywords.yaml

# Metric Keywords Configuration
# ==============================
# This file defines the keyword patterns used to identify customer metrics in SEC filings.
#
# Structure:
#   metric_id:
#     patterns: List of regex patterns (case-insensitive, use \b for word boundaries)
#     exclusions: Optional list of patterns that should NOT match this metric
#     specific_patterns: Optional list of multi-word patterns that get confidence bonus
#
# Notes:
# - All patterns are case-insensitive
# - Use \b for word boundaries to prevent partial matches
# - Use \s+ for flexible whitespace between words
# - Patterns are compiled with re.IGNORECASE
#
# To add a new metric:
# 1. Add a new metric_id key (use cm_ prefix for customer metrics)
# 2. Add patterns list with at least one regex pattern
# 3. Optionally add exclusions to prevent false positives
# 4. Optionally add specific_patterns for multi-word phrases that get bonus confidence

---
# =============================================================================
# Shared Context Requirements (YAML Anchors)
# =============================================================================
# Revenue synonym metrics require cohort or per-customer context to generate
# review candidates. Without this context, they are just revenue measures,
# not customer metrics. This anchor defines the shared context patterns.

_revenue_synonym_context: &revenue_synonym_context
  required_context:
    patterns:
      # Cohort keywords (from cohort_chart_detector.py)
      - '\bcohort\b'
      - '\bby\s+vintage\b'
      - '\bacquisition\s+year\b'
      - '\brevenue\s+(?:by|per)\s+cohort\b'
      - '\bretention\s+(?:by|per)\s+cohort\b'
      - '\bARR\s+(?:by|of\s+each)\s+cohort\b'
      - '\bLTV[/ ]CAC\b'
      # Per-customer keywords
      - '\bper\s+customer\b'
      - '\bper\s+user\b'
      - '\bper\s+account\b'
      - '\bper\s+subscriber\b'
      - '\bper\s+client\b'
      - '\baverage\s+per\b'
      - '\bby\s+customer\b'
      - '\bby\s+account\b'
      - '\bcustomer[- ]level\b'
      - '\baccount[- ]level\b'
    proximity_chars: 1500

# =============================================================================
# Core Metrics
# =============================================================================
# SEMANTIC DISTINCTIONS - Customer Count Metrics:
#   cm_customers_period_end: Stock count at period end ("total customers", "paid customers")
#   cm_active_customers_total: Engagement-based count ("active customers" - implies activity criteria)
#   These are DISTINCT metrics, not aliases. "Total" ≠ "Active"
# =============================================================================

cm_new_customers_acquired:
  patterns:
    - '\bnew\s+customers?\b'
    - '\bcustomers?\s+acquired\b'
    - '\bcustomer\s+acquisition[s]?\b'
    - '\bacquired\s+customers?\b'
    - '\bnewly\s+acquired\b'
    - '\bnew\s+customer\s+additions?\b'
    - '\bnet\s+new\s+customers?\b'
    - '\bcustomers?\s+added\b'
    - '\bacquisition\s+of\s+customers?\b'
    - '\bnew\s+users?\s+acquired\b'
    - '\bacquired\s+users?\b'
    - '\bnew\s+accounts?\s+acquired\b'
    - '\bnew\s+clients?\s+acquired\b'
    - '\bnew\s+logos?\b'
    # Consumer synonyms (e-commerce terminology)
    - '\bnew\s+consumers?\b'
    - '\bconsumers?\s+acquired\b'
    - '\bconsumer\s+acquisition[s]?\b'
    - '\bacquired\s+consumers?\b'
    - '\bconsumers?\s+added\b'
  exclusions:
    - '\bacquisition\s+cost\b'
    - '\bcac\b'
    - '\bcost\s+to\s+acquire\b'
    # FIX-FP: Exclude numbers followed by non-metric units (applications, integrations)
    - '\b\d[\d,]*(?:\s+[\w-]+){0,2}\s+(?:applications?|integrations?)\b'

cm_customers_period_end:
  # Period-end customer count (stock count at end of period)
  # Distinct from cm_active_customers_total which is engagement-based
  patterns:
    - '\bpaid\s+customers?\b'
    - '\bfree\s+(?:subscription\s+)?(?:plan\s+)?(?:organizations?|customers?)\b'
    - '\borganizations?\s+on\s+(?:our\s+)?free\s+(?:subscription\s+)?plan\b'
    - '\borganizations?\s+(?:with\s+)?(?:three|\d+)\s+(?:or\s+more\s+)?users?\b'
    - '\bcustomers?\s+\(?period\s*end\)?\b'
    - '\bend[- ]of[- ]period\s+customers?\b'
    - '\b(?:total\s+)?(?:paying|paid)\s+(?:organizations?|customers?)\b'
    - '\bactive\s+consumers?\b'
    # Total customer count patterns (moved from cm_active_customers_total 2026-01-07)
    # "Total customers" represents a stock count, not engagement-based "active" customers
    - '\btotal\s+customers?\b'
    - '\btotal\s+consumers?\b'
    - '\bcustomer\s+base\b'
    - '\bconsumer\s+base\b'
    - '\btotal\s+accounts?\b'
    - '\btotal\s+clients?\b'
  exclusions:
    - '\bretention\s+rate\b'
    - '\bnet\s+dollar\s+retention\b'
    - '\bndr\b'
    - '\bnrr\b'
    - '\b\d+%\s*(?:as\s+of|for|during)\b'
    # FIX-3: Exclude word-form numbers in non-customer contexts (languages, time periods, etc.)
    - '\b(?:eight|twelve|ten)\s+(?:languages?|months?|countries?|weeks?|days?)\b'
    - '\btrailing\s+twelve\s+months?\b'
    - '\bavailable\s+in\s+\w+\s+(?:languages?|countries?)\b'
    # FIX-FP: Exclude numbers followed by time units (e.g., "50 million hours")
    - '\b\d[\d,]*(?:\s+[\w-]+){0,2}\s+(?:hours?)\b'
  specific_patterns:
    - 'paid\s+customers?'
    - 'paying\s+customers?'
    - 'total\s+customers?'
    - 'total\s+consumers?'
    - 'customer\s+base'

cm_large_customers_period_end:
  patterns:
    - '\bpaid\s+customers?\s*>\s*\$[\d,]+'
    - '\bcustomers?\s*>\s*\$\d+(?:,\d+)*\s*(?:of\s+)?(?:arr|annual\s+recurring\s+revenue)\b'
    - '\blarge\s+(?:enterprise\s+)?customers?\b'
    - '\benterprise\s+customers?\b'
    - '\b\$\d+(?:,\d+)*(?:k|K)?\+?\s*arr\s+customers?\b'
    - '\bcustomers?\s+(?:with\s+)?(?:over|above|greater\s+than|>)\s*\$[\d,]+'
    - '\bpaid\s+customers?\s+(?:with|of)\s+\$[\d,]+\s*(?:\+|or\s+more)?'
  exclusions:
    - '\bretention\s+rate\b'
    - '\bnet\s+dollar\s+retention\b'
    - '\bndr\b'
    - '\bnrr\b'
    - '\b\d+%\s*(?:as\s+of|for|during)\b'
  specific_patterns:
    - 'enterprise\s+customers?'
    - 'large\s+customers?'

cm_customers_period_end_by_tenure:
  patterns:
    - '\bcustomers?\s+by\s+tenure\b'
    - '\btenure\s+cohort\b'
    - '\bcustomers?\s+at\s+period\s+end\b'
    - '\bby\s+age\b'
    - '\btime\s+since\b'

cm_revenue_by_cohort:
  patterns:
    - '\brevenue\s+by\s+cohort\b'
    - '\bcohort\s+revenue\b'
    - '\brevenue[^.;]{0,100}\bcohort\b'
    - '\bcohort[^.;]{0,100}\brevenue\b'

cm_transactions_by_cohort:
  patterns:
    - '\btransactions?\s+by\s+cohort\b'
    - '\bcohort\s+transactions?\b'
    - '\btransactions?[^.;]{0,100}\bcohort\b'
    # Orders variants for Farfetch terminology (orders = transactions)
    - '\borders?\s+by\s+cohort\b'
    - '\bcohort\s+orders?\b'
    - '\bnumber\s+of\s+orders?[^.;]{0,50}\bcohort\b'
  # NOTE: Plain 'number of orders' (without cohort) in cm_purchase_transactions_overall

cm_purchase_transactions_overall:
  patterns:
    - '\bnumber\s+of\s+orders?\b'
    - '\btotal\s+orders?\b'
    - '\bpurchase\s+transactions?\b(?!\s+by\s+cohort)'
    - '\border\s+count\b'
    - '\border\s+volume\b'
  exclusions:
    - '\bby\s+cohort\b'
    - '\bby\s+vintage\b'
  specific_patterns:
    - 'number\s+of\s+orders?'

# =============================================================================
# Extended Metrics
# =============================================================================

cm_active_customers_total:
  # "Active" customers implies engagement-based measurement (e.g., logged in, made purchase)
  # Distinct from "total" customers which is a simple headcount at period end
  # "Total" patterns moved to cm_customers_period_end (2026-01-07)
  patterns:
    - '\bactive\s+customers?\b'
    - '\bactive\s+consumers?\b'
    - '\bactive\s+accounts?\b'
    - '\bactive\s+clients?\b'
    - '\bactive\s+users?\b'
    - '\bactive\s+subscribers?\b'
  exclusions:
    # FIX-FP: Exclude numbers followed by non-metric units (hours, countries, languages)
    - '\b\d[\d,]*(?:\s+[\w-]+){0,2}\s+(?:hours?|countries?|languages?)\b'
  specific_patterns:
    - 'active\s+customers?'
    - 'active\s+consumers?'
    - 'active\s+accounts?'

cm_revenue_per_customer:
  patterns:
    - '\barpu\b'
    - '\baverage\s+revenue\s+per\s+user\b'
    - '\brevenue\s+per\s+customer\b'
    - '\brevenue\s+per\s+user\b'
    - '\bper\s+customer\s+revenue\b'
  exclusions:
    - '\bcost\s+per\s+customer\b'
    - '\bcost\s+per\s+user\b'
  specific_patterns:
    - 'average\s+revenue\s+per'

cm_customer_acquisition_cost:
  patterns:
    - '\bcac\b'
    - '\bcustomer\s+acquisition\s+cost\b'
    - '\bacquisition\s+cost\b'
    - '\bcost\s+to\s+acquire\b'
    # Consumer synonyms (e-commerce terminology)
    - '\bconsumer\s+acquisition\s+cost\b'
  exclusions:
    - '\bcontribution\s+margin\b'
    - '\bgross\s+margin\b'
    - '\bprofit\s+margin\b'
    - '\boperating\s+margin\b'
    - '\bplatform\s+order\s+contribution\b'
  specific_patterns:
    - 'customer\s+acquisition\s+cost'
    - 'consumer\s+acquisition\s+cost'

cm_cac_payback_period:
  patterns:
    - '\bcac\s+payback\b'
    - '\bpayback\s+period\b'
    - '\btime\s+to\s+recover\b'
    - '\bpayback\s+period\s+(?:on|for)\s+cac\b'
  specific_patterns:
    - 'payback period on CAC'
    - 'CAC payback period'

cm_customer_retention_rate:
  patterns:
    - '\bretention\s+rate\b'
    - '\bcustomer\s+retention\b'
    - '\bretained\s+customers?\b'
    # Consumer synonyms (e-commerce terminology)
    - '\bconsumer\s+retention\b'
    - '\bretained\s+consumers?\b'
  exclusions:
    - '\brevenue\s+retention\b'
    - '\bdollar\s+retention\b'
    - '\bnrr\b'
    - '\bgrr\b'

cm_customer_churn_rate:
  patterns:
    - '\bchurn\s+rate\b'
    - '\bcustomer\s+churn\b'
    - '\battrition\s+rate\b'
    # Consumer synonyms (e-commerce terminology)
    - '\bconsumer\s+churn\b'
    - '\bconsumer\s+attrition\b'

cm_net_revenue_retention:
  patterns:
    - '\bnrr\b'
    - '\bnet\s+revenue\s+retention\b'
    - '\bnet\s+retention\b'
    - '\bnet\s+dollar\s+retention\b'
    - '\bndr\b'
    - '\bretention\s+rate[^.;]{0,50}\d+%'
    - '\bnet\s+retention\s+rate\b'
  specific_patterns:
    - 'net\s+revenue\s+retention'
    - 'net\s+dollar\s+retention'

cm_gross_revenue_retention:
  patterns:
    - '\bgrr\b'
    - '\bgross\s+revenue\s+retention\b'
    - '\bgross\s+retention\b'
  specific_patterns:
    - 'gross\s+revenue\s+retention'

cm_monthly_active_users:
  patterns:
    - '\bmau\b'
    - '\bmonthly\s+active\s+users?\b'
  specific_patterns:
    - 'monthly\s+active\s+users?'

cm_daily_active_users:
  patterns:
    - '\bdau\b'
    - '\bdaily\s+active\s+users?\b'
  exclusions:
    # FIX-FP: Exclude numbers followed by non-metric units (applications, countries, languages)
    - '\b\d[\d,]*(?:\s+[\w-]+){0,2}\s+(?:applications?|countries?|languages?|integrations?)\b'
  specific_patterns:
    - 'daily\s+active\s+users?'

cm_gross_margin_by_cohort:
  # Only patterns that explicitly require "cohort" or "vintage" context
  # REMOVED (2026-01-02): '\border\s+contribution\s+margin\b' and
  # '\bplatform\s+order\s+contribution(?:\s+margin)?\b' - not cohort-specific
  patterns:
    - '\bgross\s+margin\s+by\s+cohort\b'
    - '\bcohort\s+(?:gross\s+)?margin\b'
    - '\bmargin\s+by\s+(?:acquisition\s+)?(?:vintage|cohort)\b'

cm_arr:
  patterns:
    - '\barr\b'
    - '\bannual\s+recurring\s+revenue\b'
    - '\bannualized\s+recurring\s+revenue\b'
    - '\bannual\s+run[- ]?rate\b'
  specific_patterns:
    - 'annual\s+recurring\s+revenue'

cm_mrr:
  patterns:
    - '\bmrr\b'
    - '\bmonthly\s+recurring\s+revenue\b'
  specific_patterns:
    - 'monthly\s+recurring\s+revenue'

cm_expansion_revenue:
  patterns:
    - '\bexpansion\s+revenue\b'
    - '\bcross[- ]sell\b'
    - '\bupsell\b'
    - '\bproducts?\s+per\s+customer\b'
    - '\baverage\s+products?\s+owned\b'
    - '\bexpand\b[^.;]{0,100}\brevenue\b'
    - '\badditional\s+products?\b'
    - '\bmulti[- ]product\b'

cm_revenue_concentration:
  patterns:
    - '\brevenue\s+concentration\b'
    - '\bcustomer\s+concentration\b'
    - '\btop\s+\d+\s+customers?\b'
    - '\blargest\s+customers?\b'
    - '\b\d+%\s+of\s+revenue\b'
    - '\bconcentration\s+risk\b'
    - '\bconcentration\s+of\s+revenue\b'
    - '\bmajor\s+customers?\b'
    - '\bcustomer\s+[A-D]\b'

# =============================================================================
# Revenue Predictability Metrics (DEPRECATED 2026-01-07)
# =============================================================================
# These are financial metrics, not customer metrics unless cohort-specific.
# Patterns retained for historical data interpretation but metrics are deprecated
# in the database and excluded from UI dropdowns.

cm_bookings:
  # DEPRECATED 2026-01-07: Financial metric, not customer metric unless cohort-specific
  <<: *revenue_synonym_context
  patterns:
    - '\bbookings\b'
    - '\btotal\s+bookings\b'
    - '\bnew\s+bookings\b'
    - '\bcontract\s+bookings\b'
    - '\bnet\s+new\s+bookings\b'
    - '\bquarterly\s+bookings\b'
    - '\bannual\s+bookings\b'

cm_billings:
  status: deprecated
  deprecation_reason: "GAAP financial metric, not customer-specific. Use ARR/MRR for recurring revenue metrics."
  # DEPRECATED 2026-01-07: Financial metric, not customer metric unless cohort-specific
  <<: *revenue_synonym_context
  patterns:
    - '\bbillings\b'
    - '\btotal\s+billings\b'
    - '\bcalculated\s+billings\b'
    - '\badjusted\s+billings\b'
  exclusions:
    # Cash flow metrics (from Slack table - these appear in same segment as "Calculated Billings")
    - '\bfree\s+cash\s+flows?\b'
    - '\badjusted\s+free\s+cash\s+flows?\b'
    - '\bcash\s+flows?\b'
    - '\boperating\s+(?:activities|cash|assets)\b'
    - '\bnet\s+loss\b'
    # Cash flow statement line items (common accounting terms)
    - '\bnon[- ]cash\s+charges?\b'
    - '\bdepreciation\s+and\s+amortization\b'
    - '\bstock[- ]based\s+compensation\b'
    - '\baccounts\s+(?:payable|receivable)\b'
    - '\bprepaid\s+expenses?\b'
    - '\baccrued\s+expenses?\b'
    # Tender offer / compensation items
    - '\btender\s+offer\b'
    - '\brepurchases?\s+deemed\s+compensation\b'
    # Revenue line items (general financial statements)
    - '\brevenue\b'
    - '\bdeferred\s+revenue\b'
    - '\bcost\s+of\s+(?:revenue|sales)\b'
    - '\bnet\s+revenue\b'
    # Period markers (accounting context)
    - '\b(?:beginning|end)\s+of\s+period\b'

# =============================================================================
# E-Commerce / Consumer Metrics
# =============================================================================

cm_average_order_value:
  patterns:
    - '\baov\b'
    - '\baverage\s+order\s+value\b'
    - '\baverage\s+order\s+size\b'
    - '\baverage\s+ticket\s+(?:size|value)?\b'
    - '\baverage\s+basket\s+(?:size|value)?\b'
    - '\border\s+value\s+per\s+(?:customer|user|transaction)\b'
    - '\baverage\s+transaction\s+value\b'

cm_repeat_purchase_rate:
  patterns:
    - '\brepeat\s+purchase\s+rate\b'
    - '\brepeat\s+purchase(?:s)?\b'
    - '\bpurchase\s+frequency\b'
    - '\brepeat\s+customers?\b'
    - '\brepeat\s+buyers?\b'
    - '\brepeat\s+order\s+rate\b'
    - '\breorder\s+rate\b'
    - '\brepurchase\s+rate\b'

# =============================================================================
# Marketplace / Platform Metrics (DEPRECATED 2026-01-07)
# =============================================================================
# GMV is a financial metric, not a customer metric unless cohort-specific.
# Patterns retained for historical data interpretation but metric is deprecated.

cm_gmv:
  # DEPRECATED 2026-01-07: Financial metric, not customer metric unless cohort-specific
  <<: *revenue_synonym_context
  patterns:
    - '\bgmv\b'
    - '\bgross\s+merchandise\s+value\b'
    - '\bgross\s+merchandise\s+volume\b'
    - '\bgross\s+booking\s+value\b'
    - '\bgross\s+bookings\s+value\b'
    - '\bgross\s+transaction\s+value\b'
    - '\btotal\s+transaction\s+value\b'
    - '\bgross\s+order\s+value\b'
    - '\bplatform\s+(?:transaction\s+)?volume\b'

# cm_take_rate: REMOVED (2026-01-02)
# Rationale: Take rate is a platform/marketplace revenue metric, not a customer metric.
# It measures the platform's revenue percentage, not customer behavior or value.

# =============================================================================
# SaaS Contract Metrics (DEPRECATED 2026-01-07)
# =============================================================================
# These are financial metrics, not customer metrics unless cohort-specific.
# Patterns retained for historical data interpretation but metrics are deprecated.

cm_acv:
  # DEPRECATED 2026-01-07: Financial metric, not customer metric unless cohort-specific
  <<: *revenue_synonym_context
  patterns:
    - '\bacv\b'
    - '\bannual\s+contract\s+value\b'
    - '\baverage\s+contract\s+value\b'
    - '\bannualized\s+contract\s+value\b'
    - '\baverage\s+annual\s+contract\b'
    - '\bcontract\s+value\s+per\s+customer\b'

cm_tcv:
  # DEPRECATED 2026-01-07: Financial metric, not customer metric unless cohort-specific
  <<: *revenue_synonym_context
  patterns:
    - '\btcv\b'
    - '\btotal\s+contract\s+value\b'
    - '\blifetime\s+contract\s+value\b'
    - '\bcontract\s+lifetime\s+value\b'

# =============================================================================
# Customer Value Metrics
# =============================================================================

cm_lifetime_value_per_customer:
  patterns:
    - '\bltv\b'
    - '\blifetime\s+value\b'
    - '\bcustomer\s+lifetime\s+value\b'
    - '\bclv\b'
    # Consumer synonyms and alternate phrasings
    - '\bconsumer\s+lifetime\s+value\b'
    - '\blifetime\s+value\s+of\s+a\s+(?:customer|consumer)\b'
  exclusions:
    - '\bltv\s*/\s*cac\b'
    - '\bltv\s+to\s+cac\b'
    - '\blifetime\s+value\s+to\s+(?:customer\s+)?acquisition\s+cost\b'
  specific_patterns:
    - 'lifetime\s+value'
    - 'customer\s+lifetime\s+value'
    - 'consumer\s+lifetime\s+value'
    - 'lifetime\s+value\s+of\s+a'

cm_ltv_to_cac_ratio:
  patterns:
    - '\bltv\s*[:/]\s*cac(?:\s+ratio)?\b'
    - '\bltv\s+to\s+cac(?:\s+ratio)?\b'
    - '\blifetime\s+value\s+to\s+acquisition\s+cost\b'

cm_ltv_to_cac_ratio_by_cohort:
  # LTV/CAC ratio analyzed by acquisition cohort (added 2026-01-07)
  patterns:
    - '\bltv\s*[:/]\s*cac\s+by\s+cohort\b'
    - '\bltv\s+to\s+cac\s+(?:ratio\s+)?by\s+cohort\b'
    - '\bcohort\s+ltv\s*[:/]\s*cac\b'
    - '\bltv[:/]cac[^.;]{0,50}\bcohort\b'
    - '\bcohort[^.;]{0,50}\bltv[:/]cac\b'
  specific_patterns:
    - 'ltv\s*[:/]\s*cac\s+by\s+cohort'
    - 'cohort\s+ltv\s*[:/]\s*cac'

# =============================================================================
# Growth Metrics - INTENTIONALLY NOT DETECTED
# =============================================================================
# Decision (2026-01-02): Growth metrics are not tracked separately because:
# 1. They always appear alongside base metrics (e.g., "1.1M customers, up 57%")
# 2. Growth can be calculated from period-over-period base metric values
# 3. Detecting both creates duplicate/confusing review candidates
#
# Previously removed metrics:
# - cm_active_customers_growth
# - cm_purchase_transactions_overall_growth
# =============================================================================


---

## File 4: src/infra/db.py (First 1500 lines - Database Layer)

"""
Database adapter for Customer Metrics Filings Analysis.

Provides a clean interface for database operations using psycopg3.
"""

from __future__ import annotations

import json
import logging
import os
from contextlib import contextmanager
from typing import TYPE_CHECKING, Any

import psycopg
from psycopg.rows import dict_row

from src.infra.validation import ValidationError, validate_enum, validate_score
from src.review.models import (
    DECISION_TYPES,
    IMAGE_CHART_TYPES,
    IMAGE_DECISIONS,
    IMAGE_REJECTION_REASONS,
    IMAGE_REVIEW_STATUSES,
    IMAGE_TIER_PRIORITY,
    KEYWORD_POSITIONS,
    PATTERN_STATUSES,
    PATTERN_TYPES,
    REJECTION_CATEGORIES,
    REVIEW_STATUSES,
)

if TYPE_CHECKING:
    from psycopg_pool import ConnectionPool

logger = logging.getLogger(__name__)


class DatabaseAdapter:
    """
    Database adapter for Postgres operations.

    Provides connection management and common query patterns for the filings
    analysis system. Supports both per-operation connections (default) and
    connection pooling via psycopg_pool.

    Usage without pooling (per-operation connections):
        adapter = DatabaseAdapter(connection_string)

    Usage with pooling (recommended for Flask apps and scripts):
        from src.infra.pool import create_pool
        pool = create_pool(connection_string)
        adapter = DatabaseAdapter(connection_string, pool=pool)
    """

    def __init__(
        self,
        connection_string: str,
        pool: ConnectionPool | None = None,
    ):
        """
        Initialize the database adapter.

        Args:
            connection_string: PostgreSQL connection string
                (e.g., "postgresql://user:password@localhost/dbname")
            pool: Optional connection pool. If provided, connections are
                borrowed from the pool instead of being created per operation.
        """
        self.connection_string = connection_string
        self._pool = pool
        self._connection = None

    @contextmanager
    def get_connection(self):
        """
        Get a database connection context manager.

        If a connection pool was provided to __init__, connections are borrowed
        from the pool and automatically returned when the context exits.
        Otherwise, a new connection is created and closed per operation.

        Yields:
            psycopg connection object
        """
        if self._pool is not None:
            # Use pooled connection - returned to pool on exit
            with self._pool.connection() as conn:
                try:
                    yield conn
                    conn.commit()
                except Exception as e:
                    conn.rollback()
                    logger.error(f"Database error, rolling back: {e}")
                    raise
        else:
            # Original behavior: create/close connection per operation
            conn = psycopg.connect(self.connection_string, row_factory=dict_row)
            try:
                yield conn
                conn.commit()
            except Exception as e:
                conn.rollback()
                logger.error(f"Database error, rolling back: {e}")
                raise
            finally:
                conn.close()

    @contextmanager
    def transaction(self):
        """
        Get a transaction context for multi-step operations.

        Use this when you need multiple database operations to succeed or fail
        together as an atomic unit. All operations within the context share
        a single connection and transaction.

        The transaction commits automatically on clean exit and rolls back
        on any exception.

        Yields:
            psycopg connection object with an open transaction

        Example:
            with db.transaction() as conn:
                with conn.cursor() as cur:
                    cur.execute("INSERT INTO table1 ...")
                    cur.execute("UPDATE table2 ...")
                # Both operations commit together

            # Or for complex workflows:
            with db.transaction() as conn:
                # Multiple related operations
                # All succeed or all fail
        """
        with self.get_connection() as conn:
            yield conn
            # Commit/rollback handled by get_connection()

    def execute_script(self, sql_file_path: str) -> None:
        """
        Execute a SQL script file.

        Args:
            sql_file_path: Path to SQL file

        Raises:
            ValueError: If path contains traversal sequences or doesn't end in .sql
        """
        # Security: Validate file path
        from pathlib import Path

        path = Path(sql_file_path)

        # Check for path traversal
        try:
            # Resolve to absolute path and check it doesn't escape expected directories
            path.resolve()
            # Ensure the path is within the project directory or is an absolute path to a .sql file
            if ".." in sql_file_path:
                raise ValueError("Path traversal not allowed in SQL script paths")
        except (ValueError, OSError) as e:
            raise ValueError(f"Invalid SQL script path: {e}") from e

        # Validate file extension
        if not sql_file_path.endswith(".sql"):
            raise ValueError("SQL script files must have .sql extension")

        # Validate file exists
        if not path.exists():
            raise ValueError(f"SQL script file not found: {sql_file_path}")

        with open(sql_file_path) as f:
            sql = f.read()

        with self.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(sql)

        logger.info(f"Executed SQL script: {sql_file_path}")

    def upsert_company(
        self,
        cik: str,
        company_name: str,
        ticker: str | None = None,
        country_of_domicile: str | None = None,
        industry_code: str | None = None,
        industry_classification_source: str | None = None,
    ) -> int:
        """
        Insert or update a company record.

        Args:
            cik: SEC Central Index Key
            company_name: Official issuer name
            ticker: Stock ticker symbol
            country_of_domicile: Country of incorporation
            industry_code: Industry classification code
            industry_classification_source: Source of industry code

        Returns:
            company_id of the upserted record
        """
        sql = """
            INSERT INTO companies (
                cik, company_name, ticker, country_of_domicile,
                industry_code, industry_classification_source, updated_at
            )
            VALUES (%(cik)s, %(company_name)s, %(ticker)s, %(country_of_domicile)s,
                    %(industry_code)s, %(industry_classification_source)s, now())
            ON CONFLICT (cik) DO UPDATE SET
                company_name = EXCLUDED.company_name,
                ticker = COALESCE(EXCLUDED.ticker, companies.ticker),
                country_of_domicile = COALESCE(EXCLUDED.country_of_domicile, companies.country_of_domicile),
                industry_code = COALESCE(EXCLUDED.industry_code, companies.industry_code),
                industry_classification_source = COALESCE(EXCLUDED.industry_classification_source, companies.industry_classification_source),
                updated_at = now()
            RETURNING company_id
        """

        with self.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    sql,
                    {
                        "cik": cik,
                        "company_name": company_name,
                        "ticker": ticker,
                        "country_of_domicile": country_of_domicile,
                        "industry_code": industry_code,
                        "industry_classification_source": industry_classification_source,
                    },
                )
                result = cur.fetchone()
                company_id = result["company_id"]

        logger.debug(f"Upserted company: cik={cik}, company_id={company_id}")
        return company_id

    def upsert_filing(
        self,
        company_id: int,
        cik: str,
        accession_number: str,
        form_type: str,
        filing_date: str,
        sec_html_url: str,
        period_end_date: str | None = None,
        sec_txt_url: str | None = None,
        is_in_scope_phase1: bool = False,
        is_first_time_issuer: bool | None = None,
        is_spac: bool | None = None,
        is_post_combination: bool | None = None,
        is_investment_vehicle: bool | None = None,
        is_resource_extraction: bool | None = None,
        offering_type: str | None = None,
        classification_method: str | None = None,
        processing_status: str = "pending",
    ) -> int:
        """
        Insert or update a filing record.

        Args:
            company_id: Foreign key to companies table
            cik: SEC Central Index Key
            accession_number: SEC accession number
            form_type: SEC form type (e.g., 'S-1', 'F-1')
            filing_date: Date filed with SEC (ISO format)
            sec_html_url: URL to HTML filing
            period_end_date: Period end date (ISO format)
            sec_txt_url: URL to text filing
            is_in_scope_phase1: Whether filing is in Phase 1 scope
            is_first_time_issuer: Whether this is a first-time issuer
            is_spac: Whether issuer is a SPAC
            is_post_combination: Whether this is a post-combination SPAC (de-SPAC)
            is_investment_vehicle: Whether company is an investment vehicle
            is_resource_extraction: Whether company is in resource extraction
            offering_type: Type of offering ('primary', 'secondary', 'mixed')
            classification_method: How flags were determined
            processing_status: Current processing status

        Returns:
            filing_id of the upserted record
        """
        sql = """
            INSERT INTO filings (
                company_id, cik, accession_number, form_type, filing_date,
                period_end_date, sec_html_url, sec_txt_url,
                is_in_scope_phase1, is_first_time_issuer, is_spac, is_post_combination,
                is_investment_vehicle, is_resource_extraction,
                offering_type, classification_method, processing_status, updated_at
            )
            VALUES (
                %(company_id)s, %(cik)s, %(accession_number)s, %(form_type)s, %(filing_date)s,
                %(period_end_date)s, %(sec_html_url)s, %(sec_txt_url)s,
                %(is_in_scope_phase1)s, %(is_first_time_issuer)s, %(is_spac)s, %(is_post_combination)s,
                %(is_investment_vehicle)s, %(is_resource_extraction)s,
                %(offering_type)s, %(classification_method)s, %(processing_status)s, now()
            )
            ON CONFLICT (company_id, accession_number) DO UPDATE SET
                form_type = EXCLUDED.form_type,
                filing_date = EXCLUDED.filing_date,
                period_end_date = COALESCE(EXCLUDED.period_end_date, filings.period_end_date),
                sec_html_url = EXCLUDED.sec_html_url,
                sec_txt_url = COALESCE(EXCLUDED.sec_txt_url, filings.sec_txt_url),
                is_in_scope_phase1 = EXCLUDED.is_in_scope_phase1,
                is_first_time_issuer = COALESCE(EXCLUDED.is_first_time_issuer, filings.is_first_time_issuer),
                is_spac = COALESCE(EXCLUDED.is_spac, filings.is_spac),
                is_post_combination = COALESCE(EXCLUDED.is_post_combination, filings.is_post_combination),
                is_investment_vehicle = COALESCE(EXCLUDED.is_investment_vehicle, filings.is_investment_vehicle),
                is_resource_extraction = COALESCE(EXCLUDED.is_resource_extraction, filings.is_resource_extraction),
                offering_type = COALESCE(EXCLUDED.offering_type, filings.offering_type),
                classification_method = COALESCE(EXCLUDED.classification_method, filings.classification_method),
                processing_status = EXCLUDED.processing_status,
                updated_at = now()
            RETURNING filing_id
        """

        with self.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    sql,
                    {
                        "company_id": company_id,
                        "cik": cik,
                        "accession_number": accession_number,
                        "form_type": form_type,
                        "filing_date": filing_date,
                        "period_end_date": period_end_date,
                        "sec_html_url": sec_html_url,
                        "sec_txt_url": sec_txt_url,
                        "is_in_scope_phase1": is_in_scope_phase1,
                        "is_first_time_issuer": is_first_time_issuer,
                        "is_spac": is_spac,
                        "is_post_combination": is_post_combination,
                        "is_investment_vehicle": is_investment_vehicle,
                        "is_resource_extraction": is_resource_extraction,
                        "offering_type": offering_type,
                        "classification_method": classification_method,
                        "processing_status": processing_status,
                    },
                )
                result = cur.fetchone()
                filing_id = result["filing_id"]

        logger.debug(
            f"Upserted filing: accession={accession_number}, filing_id={filing_id}"
        )
        return filing_id

    def execute(
        self,
        sql: str,
        params: dict[str, Any] | None = None,
        *,
        fetch: bool = False,
    ) -> list[dict[str, Any]] | None:
        """
        Execute a SQL statement.

        Args:
            sql: SQL statement
            params: Query parameters
            fetch: If True, return fetched rows (for statements with RETURNING)

        Returns:
            List of rows when fetch=True, otherwise None.
        """
        with self.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, params or {})
                if fetch:
                    return cur.fetchall()
        return None

    def query(self, sql: str, params: dict[str, Any] | None = None) -> list[dict]:
        """
        Execute a SELECT query and return results as list of dicts.

        Args:
            sql: SQL query string
            params: Query parameters

        Returns:
            List of result rows as dictionaries
        """
        result = self.execute(sql, params, fetch=True)
        return result or []

    def get_company_by_cik(self, cik: str) -> dict | None:
        """
        Get a company record by CIK.

        Args:
            cik: SEC Central Index Key

        Returns:
            Company record as dict, or None if not found
        """
        sql = "SELECT * FROM companies WHERE cik = %(cik)s"
        results = self.query(sql, {"cik": cik})
        return results[0] if results else None

    def get_first_ipo_filing_date(self, cik: str) -> str | None:
        """
        Get the filing date of the first IPO-type filing for a CIK.

        Used to determine if a filing is from a first-time issuer.

        Args:
            cik: SEC Central Index Key

        Returns:
            ISO date string of first IPO filing, or None if not found
        """
        sql = """
            SELECT MIN(filing_date) as first_filing_date
            FROM filings
            WHERE cik = %(cik)s
            AND form_type IN ('S-1', 'S-1/A', 'F-1', 'F-1/A')
        """
        results = self.query(sql, {"cik": cik})
        if results and results[0]["first_filing_date"]:
            return str(results[0]["first_filing_date"])
        return None

    def has_prior_spac_filing(self, cik: str, filing_date: str) -> bool:
        """
        Check if a CIK has any prior SPAC filings before the given date.

        This is used to detect post-combination SPACs (de-SPACs) where the
        same CIK was previously used for a blank check SPAC entity.

        Args:
            cik: SEC Central Index Key
            filing_date: ISO date string to check before

        Returns:
            True if CIK has prior SPAC filings, False otherwise
        """
        sql = """
            SELECT COUNT(*) as count
            FROM filings
            WHERE cik = %(cik)s
              AND is_spac = true
              AND filing_date < %(filing_date)s
        """
        results = self.query(sql, {"cik": cik, "filing_date": filing_date})
        return bool(results and results[0]["count"] > 0)

    def get_in_scope_filing_count(self) -> int:
        """
        Get count of filings where is_in_scope_phase1 = true.

        Returns:
            Count of in-scope filings
        """
        sql = "SELECT COUNT(*) as count FROM filings WHERE is_in_scope_phase1 = true"
        results = self.query(sql)
        return results[0]["count"] if results else 0

    # =========================================================================
    # Review Candidates Methods
    # =========================================================================

    def insert_review_candidate(
        self,
        filing_id: int,
        company_id: int,
        char_position: int,
        context_text: str,
        raw_number_text: str,
        triggering_keyword: str,
        keyword_distance: int,
        keyword_position: str,
        source_segment_id: int | None = None,
        parsed_value: Any | None = None,
        parsed_unit: str | None = None,
        suggested_metric_id: str | None = None,
        suggestion_confidence: float | None = None,
        features: dict[str, Any] | None = None,
        review_batch_id: int | None = None,
    ) -> int:
        """
        Insert a new review candidate.

        Args:
            filing_id: Foreign key to filings table
            company_id: Foreign key to companies table
            char_position: Character position of number in segment
            context_text: Surrounding text for context
            raw_number_text: The raw number string found
            triggering_keyword: Keyword that triggered this candidate
            keyword_distance: Characters from number to keyword
            keyword_position: 'before' or 'after' the number
            source_segment_id: Optional foreign key to source_segments
            parsed_value: Parsed numeric value
            parsed_unit: Detected unit
            suggested_metric_id: Initial suggested metric
            suggestion_confidence: 0-1 confidence score
            features: ML features as dict (stored as JSONB)
            review_batch_id: Optional batch grouping

        Returns:
            candidate_id of the inserted record

        Raises:
            ValidationError: If keyword_position is not 'before' or 'after'
            ValidationError: If suggestion_confidence is not between 0 and 1
        """
        # Validate enum values
        validate_enum(keyword_position, KEYWORD_POSITIONS, "keyword_position")

        # Validate confidence range
        validate_score(suggestion_confidence, "suggestion_confidence")

        sql = """
            INSERT INTO review_candidates (
                filing_id, company_id, source_segment_id,
                char_position, context_text, raw_number_text,
                parsed_value, parsed_unit,
                triggering_keyword, keyword_distance, keyword_position,
                suggested_metric_id, suggestion_confidence, features,
                review_batch_id
            )
            VALUES (
                %(filing_id)s, %(company_id)s, %(source_segment_id)s,
                %(char_position)s, %(context_text)s, %(raw_number_text)s,
                %(parsed_value)s, %(parsed_unit)s,
                %(triggering_keyword)s, %(keyword_distance)s, %(keyword_position)s,
                %(suggested_metric_id)s, %(suggestion_confidence)s, %(features)s,
                %(review_batch_id)s
            )
            RETURNING candidate_id
        """

        with self.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    sql,
                    {
                        "filing_id": filing_id,
                        "company_id": company_id,
                        "source_segment_id": source_segment_id,
                        "char_position": char_position,
                        "context_text": context_text,
                        "raw_number_text": raw_number_text,
                        "parsed_value": parsed_value,
                        "parsed_unit": parsed_unit,
                        "triggering_keyword": triggering_keyword,
                        "keyword_distance": keyword_distance,
                        "keyword_position": keyword_position,
                        "suggested_metric_id": suggested_metric_id,
                        "suggestion_confidence": suggestion_confidence,
                        "features": json.dumps(features) if features else None,
                        "review_batch_id": review_batch_id,
                    },
                )
                result = cur.fetchone()
                candidate_id = result["candidate_id"]

        logger.debug(f"Inserted review candidate: candidate_id={candidate_id}")
        return candidate_id

    def get_review_candidate(self, candidate_id: int) -> dict | None:
        """
        Get a review candidate by ID.

        Args:
            candidate_id: Primary key

        Returns:
            Candidate record as dict, or None if not found
        """
        sql = "SELECT * FROM review_candidates WHERE candidate_id = %(candidate_id)s"
        results = self.query(sql, {"candidate_id": candidate_id})
        return results[0] if results else None

    def get_expanded_context_for_candidate(
        self, candidate_id: int, num_adjacent: int = 2
    ) -> dict[str, Any] | None:
        """
        Get expanded context for a candidate by fetching adjacent segments.

        Fetches segments before and after the candidate's source segment
        and concatenates their text to provide broader context.

        Args:
            candidate_id: Candidate ID to expand context for
            num_adjacent: Number of adjacent segments to fetch on each side (default: 2)

        Returns:
            Dict with:
                - expanded_context: str - Concatenated text from adjacent segments
                - segment_count: int - Number of segments included
                - can_expand: bool - Whether expansion was possible
            Or None if candidate or source segment not found
        """
        # First, get the candidate and its source segment info
        candidate = self.get_review_candidate(candidate_id)
        if not candidate:
            return None

        source_segment_id = candidate.get("source_segment_id")
        if not source_segment_id:
            # No source segment linked - return current context only
            return {
                "expanded_context": candidate.get("context_text", ""),
                "segment_count": 0,
                "can_expand": False,
            }

        # Get the source segment to find its filing_id and sequence_index
        segment_sql = """
            SELECT filing_id, sequence_index
            FROM source_segments
            WHERE source_segment_id = %(source_segment_id)s
        """
        segment_results = self.query(
            segment_sql, {"source_segment_id": source_segment_id}
        )

        if not segment_results:
            # Source segment not found - return current context
            return {
                "expanded_context": candidate.get("context_text", ""),
                "segment_count": 0,
                "can_expand": False,
            }

        filing_id = segment_results[0]["filing_id"]
        sequence_index = segment_results[0]["sequence_index"]

        # Fetch adjacent segments (num_adjacent before and after)
        adjacent_sql = """
            SELECT sequence_index, raw_text
            FROM source_segments
            WHERE filing_id = %(filing_id)s
              AND sequence_index >= %(min_index)s
              AND sequence_index <= %(max_index)s
            ORDER BY sequence_index ASC
        """

        min_index = max(0, sequence_index - num_adjacent)
        max_index = sequence_index + num_adjacent

        adjacent_results = self.query(
            adjacent_sql,
            {
                "filing_id": filing_id,
                "min_index": min_index,
                "max_index": max_index,
            },
        )

        if not adjacent_results:
            # No adjacent segments found - return current context
            return {
                "expanded_context": candidate.get("context_text", ""),
                "segment_count": 0,
                "can_expand": False,
            }

        # Concatenate all segment texts with separator
        expanded_text = " ... ".join(
            seg["raw_text"] for seg in adjacent_results if seg["raw_text"]
        )

        return {
            "expanded_context": expanded_text,
            "segment_count": len(adjacent_results),
            "can_expand": True,
        }

    def get_review_candidates_for_filing(
        self,
        filing_id: int,
        status: str | None = None,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[dict]:
        """
        Get review candidates for a filing.

        Args:
            filing_id: Filing to get candidates for
            status: Optional filter by review_status
            limit: Maximum number to return
            offset: Number to skip (for pagination)

        Returns:
            List of candidate records

        Raises:
            ValidationError: If status is provided but not a valid review status
        """
        # Validate status if provided
        if status is not None:
            validate_enum(status, REVIEW_STATUSES, "review_status")

        sql = """
            SELECT * FROM review_candidates
            WHERE filing_id = %(filing_id)s
        """
        params: dict[str, Any] = {"filing_id": filing_id}

        if status:
            sql += " AND review_status = %(status)s"
            params["status"] = status

        sql += " ORDER BY char_position"

        if limit:
            sql += " LIMIT %(limit)s OFFSET %(offset)s"
            params["limit"] = limit
            params["offset"] = offset

        return self.query(sql, params)

    def get_review_candidates_with_decisions(
        self,
        filing_id: int,
        status: str | None = None,
        metric_id: str | None = None,
        confidence_level: str | None = None,
        sort_by: str = "position",
        limit: int | None = None,
        offset: int = 0,
    ) -> list[dict]:
        """
        Get review candidates for a filing WITH their decisions (if any).

        This method uses a LEFT JOIN to fetch candidates and decisions in a single
        query, eliminating the N+1 query pattern when displaying candidates with
        their review decisions.

        Args:
            filing_id: Filing to get candidates for
            status: Optional filter by review_status
            metric_id: Optional filter by suggested_metric_id
            confidence_level: Optional filter by confidence tier ('high', 'medium', 'low')
            sort_by: Sort order ('position', 'confidence_asc', 'confidence_desc',
                     'value_asc', 'value_desc')
            limit: Maximum number to return
            offset: Number to skip (for pagination)

        Returns:
            List of candidate records with segment fields (segment_type, segment_html)
            and decision fields (decision_id, decision, assigned_metric_id,
            rejection_category, rejection_reason, reviewer_notes, reviewer_id,
            review_time_seconds, decision_created_at).
            Segment and decision fields are NULL if no source segment or decision exists.

        Raises:
            ValidationError: If status is provided but not a valid review status
        """
        # Validate status if provided
        if status is not None:
            validate_enum(status, REVIEW_STATUSES, "review_status")

        sql = """
            SELECT
                rc.*,
                ss.segment_type,
                ss.raw_html as segment_html,
                rd.decision_id,
                rd.decision,
                rd.assigned_metric_id,
                rd.rejection_category,
                rd.rejection_reason,
                rd.reviewer_notes,
                rd.reviewer_id,
                rd.review_time_seconds,
                rd.created_at as decision_created_at
            FROM review_candidates rc
            LEFT JOIN source_segments ss ON rc.source_segment_id = ss.source_segment_id
            LEFT JOIN (
                SELECT DISTINCT ON (candidate_id)
                    candidate_id,
                    decision_id,
                    decision,
                    assigned_metric_id,
                    rejection_category,
                    rejection_reason,
                    reviewer_notes,
                    reviewer_id,
                    review_time_seconds,
                    created_at
                FROM review_decisions
                ORDER BY candidate_id, created_at DESC
            ) rd ON rc.candidate_id = rd.candidate_id
            WHERE rc.filing_id = %(filing_id)s
        """
        params: dict[str, Any] = {"filing_id": filing_id}

        if status:
            sql += " AND rc.review_status = %(status)s"
            params["status"] = status

        # Add metric filter
        if metric_id:
            sql += " AND rc.suggested_metric_id = %(metric_id)s"
            params["metric_id"] = metric_id

        # Add confidence filter
        if confidence_level == "high":
            sql += " AND rc.suggestion_confidence >= 0.7"
        elif confidence_level == "medium":
            sql += " AND rc.suggestion_confidence >= 0.4 AND rc.suggestion_confidence < 0.7"
        elif confidence_level == "low":
            sql += " AND rc.suggestion_confidence < 0.4"

        # Dynamic ORDER BY based on sort_by parameter
        sort_clauses = {
            "position": "rc.char_position",
            "confidence_asc": "rc.suggestion_confidence ASC, rc.char_position",
            "confidence_desc": "rc.suggestion_confidence DESC, rc.char_position",
            "value_asc": "rc.parsed_value ASC, rc.char_position",
            "value_desc": "rc.parsed_value DESC, rc.char_position",
        }
        order_by = sort_clauses.get(sort_by, "rc.char_position")
        sql += f" ORDER BY {order_by}"

        if limit:
            sql += " LIMIT %(limit)s OFFSET %(offset)s"
            params["limit"] = limit
            params["offset"] = offset

        results = self.query(sql, params)

        # Post-process: Check if segment HTML contains the value/keyword
        # If not, clear segment_html so the UI falls back to context_text display.
        # This handles cases where:
        # - HTML is truncated and the number appears beyond the truncation point
        # - Number appears in context_prefix from a different segment
        # - HTML markup inflates size, causing earlier truncation than raw_text
        for result in results:
            segment_html = result.get('segment_html')
            raw_number_text = result.get('raw_number_text')
            triggering_keyword = result.get('triggering_keyword')

            # Initialize dual display field
            result['segment_html_table_only'] = None

            # Check any segment with HTML (regardless of segment_type)
            if segment_html and raw_number_text and triggering_keyword:
                # Check if the HTML actually contains the value and keyword
                # If not, clear it so UI falls back to context_text (which always has them)
                has_value = raw_number_text in segment_html
                # Case-insensitive keyword check to match _highlight_html behavior
                has_keyword = triggering_keyword.lower() in segment_html.lower()

                if not (has_value and has_keyword):
                    # Check if the HTML contains a table - if so, preserve it for dual display
                    # This allows showing table structure alongside context_text with highlighting
                    has_table = '<table' in segment_html.lower()

                    if has_table and has_keyword:
                        # Table structure is useful even without the value highlighted
                        # Store it for dual display mode in the UI
                        logger.debug(
                            f"Segment HTML for candidate {result.get('candidate_id')} has table "
                            f"with keyword but value is truncated. Enabling dual display mode."
                        )
                        result['segment_html_table_only'] = segment_html
                    else:
                        logger.debug(
                            f"Segment HTML for candidate {result.get('candidate_id')} doesn't contain "
                            f"value={has_value}, keyword={has_keyword}. Clearing for context_text fallback."
                        )

                    # Clear segment_html to force display of context_text instead
                    result['segment_html'] = None
                    result['segment_type'] = None

        return results

    def get_all_reviewed_candidates_with_decisions(
        self,
        metric_id: str | None = None,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[dict]:
        """
        Get all reviewed candidates with decisions across all filings.

        Similar to get_review_candidates_with_decisions() but not filtered
        by filing_id. Used for pattern analysis across the full dataset.

        Only returns candidates that have been reviewed (have decisions).
        Uses an INNER JOIN instead of LEFT JOIN to ensure all returned
        candidates have a decision.

        Args:
            metric_id: Optional filter by suggested_metric_id
            limit: Maximum number to return
            offset: Number to skip (for pagination)

        Returns:
            List of candidate records with decision fields (decision_id, decision,
            assigned_metric_id, rejection_category, rejection_reason, reviewer_notes,
            reviewer_id, review_time_seconds, decision_created_at).

        Example:
            >>> db = DatabaseAdapter(connection_string)
            >>> # Get all reviewed candidates
            >>> all_decisions = db.get_all_reviewed_candidates_with_decisions()
            >>> # Get reviewed candidates for specific metric
            >>> arr_decisions = db.get_all_reviewed_candidates_with_decisions(
            ...     metric_id="annual_recurring_revenue"
            ... )
            >>> # Get first 100 with pagination
            >>> batch = db.get_all_reviewed_candidates_with_decisions(limit=100)
        """
        sql = """
            SELECT
                rc.*,
                rd.decision_id,
                rd.decision,
                rd.assigned_metric_id,
                rd.rejection_category,
                rd.rejection_reason,
                rd.reviewer_notes,
                rd.reviewer_id,
                rd.review_time_seconds,
                rd.created_at as decision_created_at
            FROM review_candidates rc
            INNER JOIN (
                SELECT DISTINCT ON (candidate_id)
                    candidate_id,
                    decision_id,
                    decision,
                    assigned_metric_id,
                    rejection_category,
                    rejection_reason,
                    reviewer_notes,
                    reviewer_id,
                    review_time_seconds,
                    created_at
                FROM review_decisions
                ORDER BY candidate_id, created_at DESC
            ) rd ON rc.candidate_id = rd.candidate_id
            WHERE 1=1
        """
        params: dict[str, Any] = {}

        if metric_id:
            sql += " AND rc.suggested_metric_id = %(metric_id)s"
            params["metric_id"] = metric_id

        sql += " ORDER BY rc.candidate_id"

        if limit:
            sql += " LIMIT %(limit)s OFFSET %(offset)s"
            params["limit"] = limit
            params["offset"] = offset

        return self.query(sql, params)

    def get_pending_candidates(
        self,
        filing_id: int | None = None,
        batch_id: int | None = None,
        limit: int = 50,
    ) -> list[dict]:
        """
        Get candidates pending review.

        Args:
            filing_id: Optional filter by filing
            batch_id: Optional filter by batch
            limit: Maximum number to return

        Returns:
            List of pending candidate records
        """
        sql = """
            SELECT rc.*, f.accession_number, c.company_name
            FROM review_candidates rc
            JOIN filings f ON rc.filing_id = f.filing_id
            JOIN companies c ON rc.company_id = c.company_id
            WHERE rc.review_status = 'pending'
        """
        params: dict[str, Any] = {"limit": limit}

        if filing_id:
            sql += " AND rc.filing_id = %(filing_id)s"
            params["filing_id"] = filing_id

        if batch_id:
            sql += " AND rc.review_batch_id = %(batch_id)s"
            params["batch_id"] = batch_id

        sql += " ORDER BY rc.filing_id, rc.char_position LIMIT %(limit)s"

        return self.query(sql, params)

    def update_candidate_status(
        self, candidate_id: int, status: str
    ) -> bool:
        """
        Update a candidate's review status.

        Args:
            candidate_id: Candidate to update
            status: New status ('pending', 'in_progress', 'reviewed', 'skipped')

        Returns:
            True if a row was updated, False if no candidate found with given ID

        Raises:
            ValidationError: If status is not a valid review status
        """
        # Validate status
        validate_enum(status, REVIEW_STATUSES, "review_status")

        sql = """
            UPDATE review_candidates
            SET review_status = %(status)s, updated_at = now()
            WHERE candidate_id = %(candidate_id)s
            RETURNING candidate_id
        """
        result = self.execute(
            sql, {"candidate_id": candidate_id, "status": status}, fetch=True
        )
        updated = bool(result)
        if updated:
            logger.debug(f"Updated candidate {candidate_id} status to {status}")
        else:
            logger.warning(f"No candidate found with id {candidate_id}")
        return updated

    def bulk_update_candidate_status(
        self, candidate_ids: list[int], status: str
    ) -> int:
        """
        Update status for multiple candidates efficiently.

        Uses PostgreSQL ANY() for single-statement bulk update.

        Args:
            candidate_ids: List of candidate IDs to update
            status: New status ('pending', 'in_progress', 'reviewed', 'skipped')

        Returns:
            Number of rows updated

        Raises:
            ValidationError: If status is not a valid review status
        """
        if not candidate_ids:
            return 0

        # Validate status
        validate_enum(status, REVIEW_STATUSES, "review_status")

        sql = """
            UPDATE review_candidates
            SET review_status = %(status)s, updated_at = now()
            WHERE candidate_id = ANY(%(candidate_ids)s)
        """

        with self.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    sql,
                    {"candidate_ids": candidate_ids, "status": status},
                )
                rows_updated = cur.rowcount

        logger.debug(
            f"Bulk updated {rows_updated} candidates to status '{status}'"
        )
        return rows_updated

    # =========================================================================
    # Private Helpers for Conflict Resolution
    # =========================================================================

    def _fetch_conflicting_candidates(
        self,
        cur,
        uniqueness_keys: list[tuple],
        has_segment: bool,
    ) -> dict[tuple, dict[str, Any]]:
        """
        Fetch existing candidates that would conflict with the given keys.

        Args:
            cur: Database cursor
            uniqueness_keys: List of uniqueness key tuples:
                - If has_segment=True: (filing_id, segment_id, char_pos, metric_id)
                - If has_segment=False: (filing_id, char_pos, metric_id)
            has_segment: If True, keys include segment_id (non-NULL case)

        Returns:
            Dict mapping uniqueness_key -> existing candidate row dict
        """
        if not uniqueness_keys:
            return {}

        if has_segment:
            # Candidates WITH source_segment_id
            sql = """
                SELECT candidate_id, filing_id, source_segment_id, char_position,
                       suggested_metric_id, suggestion_confidence, context_text,
                       raw_number_text, parsed_value, parsed_unit,
                       triggering_keyword, keyword_distance, keyword_position,
                       features, company_id
                FROM review_candidates
                WHERE (filing_id, source_segment_id, char_position, suggested_metric_id)
                      IN (SELECT * FROM UNNEST(
                          %(filing_ids)s::bigint[],
                          %(segment_ids)s::bigint[],
                          %(char_positions)s::int[],
                          %(metric_ids)s::text[]
                      ))
                  AND source_segment_id IS NOT NULL
            """
            params = {
                "filing_ids": [k[0] for k in uniqueness_keys],
                "segment_ids": [k[1] for k in uniqueness_keys],
                "char_positions": [k[2] for k in uniqueness_keys],
                "metric_ids": [k[3] for k in uniqueness_keys],
            }
        else:
            # Candidates WITHOUT source_segment_id (NULL case)
            sql = """
                SELECT candidate_id, filing_id, source_segment_id, char_position,
                       suggested_metric_id, suggestion_confidence, context_text,
                       raw_number_text, parsed_value, parsed_unit,
                       triggering_keyword, keyword_distance, keyword_position,
                       features, company_id
                FROM review_candidates
                WHERE (filing_id, char_position, suggested_metric_id)
                      IN (SELECT * FROM UNNEST(
                          %(filing_ids)s::bigint[],
                          %(char_positions)s::int[],
                          %(metric_ids)s::text[]
                      ))
                  AND source_segment_id IS NULL
            """
            params = {
                "filing_ids": [k[0] for k in uniqueness_keys],
                "char_positions": [k[1] for k in uniqueness_keys],
                "metric_ids": [k[2] for k in uniqueness_keys],
            }

        cur.execute(sql, params)
        rows = cur.fetchall()

        # Map uniqueness_key -> row
        result: dict[tuple, dict[str, Any]] = {}
        for row in rows:
            if has_segment:
                key = (
                    row["filing_id"],
                    row["source_segment_id"],
                    row["char_position"],
                    row["suggested_metric_id"],
                )
            else:
                key = (
                    row["filing_id"],
                    row["char_position"],
                    row["suggested_metric_id"],
                )
            result[key] = dict(row)

        return result

    def _bulk_log_suppressed(
        self,
        cur,
        entries: list[dict[str, Any]],
    ) -> list[int]:
        """
        Bulk insert suppressed candidate records.

        Args:
            cur: Database cursor
            entries: List of dicts with suppressed_candidates columns

        Returns:
            List of suppressed_id values
        """
        if not entries:
            return []

        # Build arrays for UNNEST
        filing_ids = []
        company_ids = []
        source_segment_ids = []
        char_positions = []
        context_texts = []
        raw_number_texts = []
        parsed_values = []
        parsed_units = []
        triggering_keywords = []
        keyword_distances = []
        keyword_positions = []
        suggested_metric_ids = []
        suggestion_confidences = []
        features_list = []
        winner_candidate_ids = []
        suppression_reasons = []
        winner_confidences = []

        for entry in entries:
            filing_ids.append(entry["filing_id"])
            company_ids.append(entry["company_id"])
            source_segment_ids.append(entry.get("source_segment_id"))
            char_positions.append(entry["char_position"])
            context_texts.append(entry["context_text"])
            raw_number_texts.append(entry["raw_number_text"])
            parsed_values.append(entry.get("parsed_value"))
            parsed_units.append(entry.get("parsed_unit"))
            triggering_keywords.append(entry["triggering_keyword"])
            keyword_distances.append(entry["keyword_distance"])
            keyword_positions.append(entry["keyword_position"])
            suggested_metric_ids.append(entry.get("suggested_metric_id"))
            suggestion_confidences.append(entry.get("suggestion_confidence"))
            features = entry.get("features")
            features_list.append(json.dumps(features) if features else None)
            winner_candidate_ids.append(entry["winner_candidate_id"])
            suppression_reasons.append(entry["suppression_reason"])
            winner_confidences.append(entry.get("winner_confidence"))

        sql = """
            INSERT INTO suppressed_candidates (
                filing_id, company_id, source_segment_id,
                char_position, context_text, raw_number_text,
                parsed_value, parsed_unit,
                triggering_keyword, keyword_distance, keyword_position,
                suggested_metric_id, suggestion_confidence, features,
                winner_candidate_id, suppression_reason, winner_confidence
            )
            SELECT
                filing_id, company_id, source_segment_id,
                char_position, context_text, raw_number_text,
                parsed_value, parsed_unit,
                triggering_keyword, keyword_distance, keyword_position,
                suggested_metric_id, suggestion_confidence, features,
                winner_candidate_id, suppression_reason, winner_confidence
            FROM UNNEST(
                %(filing_ids)s::bigint[],
                %(company_ids)s::bigint[],
                %(source_segment_ids)s::bigint[],
                %(char_positions)s::int[],
                %(context_texts)s::text[],
                %(raw_number_texts)s::text[],
                %(parsed_values)s::numeric[],
                %(parsed_units)s::text[],
                %(triggering_keywords)s::text[],
                %(keyword_distances)s::int[],
                %(keyword_positions)s::text[],
                %(suggested_metric_ids)s::text[],
                %(suggestion_confidences)s::numeric[],
                %(features_list)s::jsonb[],
                %(winner_candidate_ids)s::bigint[],
                %(suppression_reasons)s::text[],
                %(winner_confidences)s::numeric[]
            ) WITH ORDINALITY AS t(
                filing_id, company_id, source_segment_id,
                char_position, context_text, raw_number_text,
                parsed_value, parsed_unit,
                triggering_keyword, keyword_distance, keyword_position,
                suggested_metric_id, suggestion_confidence, features,
                winner_candidate_id, suppression_reason, winner_confidence,
                ord
            )
            ORDER BY ord
            RETURNING suppressed_id
        """

        cur.execute(
            sql,
            {
                "filing_ids": filing_ids,
                "company_ids": company_ids,
                "source_segment_ids": source_segment_ids,
                "char_positions": char_positions,
                "context_texts": context_texts,
                "raw_number_texts": raw_number_texts,
                "parsed_values": parsed_values,
                "parsed_units": parsed_units,
                "triggering_keywords": triggering_keywords,
                "keyword_distances": keyword_distances,
                "keyword_positions": keyword_positions,
                "suggested_metric_ids": suggested_metric_ids,
                "suggestion_confidences": suggestion_confidences,
                "features_list": features_list,
                "winner_candidate_ids": winner_candidate_ids,
                "suppression_reasons": suppression_reasons,
                "winner_confidences": winner_confidences,
            },
        )
        results = cur.fetchall()
        return [row["suppressed_id"] for row in results]

    def _identify_runner_ups(
        self,
        candidates: list[dict[str, Any]],
        final_ids: list[int],
        winner_metrics: dict[int, tuple[str | None, float | None]],
    ) -> list[dict[str, Any]]:
        """
        Identify runner-up candidates for each position.

        Groups by position_key (filing_id, segment_id, char_position).
        For each position with multiple metric suggestions, finds the
        best alternative to the winner.

        Args:
            candidates: Original input candidates
            final_ids: Final candidate_id for each input (in same order)
            winner_metrics: Dict of candidate_id -> (metric_id, confidence)

        Returns:
            List of suppression entries for runner-ups
        """
        # Group candidates by position_key
        # position_key = (filing_id, source_segment_id, char_position)
        from collections import defaultdict

        position_groups: dict[tuple, list[tuple[int, dict[str, Any]]]] = defaultdict(
            list
        )

        for idx, candidate in enumerate(candidates):
            position_key = (
                candidate["filing_id"],
                candidate.get("source_segment_id"),
                candidate["char_position"],
            )
            position_groups[position_key].append((idx, candidate))

        runner_up_entries: list[dict[str, Any]] = []

        for position_key, group in position_groups.items():
            if len(group) < 2:
                # No alternatives at this position
                continue

            # Find the winner at this position
            # The winner is the one whose final_id is in winner_metrics
            # and has the highest confidence
            winner_idx = None
            winner_id = None
            winner_metric = None
            winner_conf = None

            for idx, cand in group:
                cand_id = final_ids[idx]
                if cand_id in winner_metrics:
                    metric_id, conf = winner_metrics[cand_id]
                    if winner_idx is None or (conf or 0) > (winner_conf or 0):
                        winner_idx = idx
                        winner_id = cand_id
                        winner_metric = metric_id
                        winner_conf = conf

            if winner_id is None:
                # No winner found (shouldn't happen)
                continue

            # Find the best runner-up: highest confidence with different metric
            runner_up_idx = None
            runner_up_conf = -1.0

            for idx, cand in group:
                cand_metric = cand.get("suggested_metric_id")
                cand_conf = cand.get("suggestion_confidence") or 0

                # Must have different metric than winner
                if cand_metric == winner_metric:
                    continue

                # Must be a different candidate (not the winner)
                if idx == winner_idx:
                    continue

                if cand_conf > runner_up_conf:
                    runner_up_idx = idx
                    runner_up_conf = cand_conf

            if runner_up_idx is not None:
                runner_cand = candidates[runner_up_idx]
                runner_up_entries.append(
                    {
                        "filing_id": runner_cand["filing_id"],
                        "company_id": runner_cand["company_id"],
                        "source_segment_id": runner_cand.get("source_segment_id"),
                        "char_position": runner_cand["char_position"],
                        "context_text": runner_cand["context_text"],
                        "raw_number_text": runner_cand["raw_number_text"],
                        "parsed_value": runner_cand.get("parsed_value"),
                        "parsed_unit": runner_cand.get("parsed_unit"),
                        "triggering_keyword": runner_cand["triggering_keyword"],
                        "keyword_distance": runner_cand["keyword_distance"],
                        "keyword_position": runner_cand["keyword_position"],
                        "suggested_metric_id": runner_cand.get("suggested_metric_id"),
                        "suggestion_confidence": runner_cand.get(
                            "suggestion_confidence"
                        ),
                        "features": runner_cand.get("features"),
                        "winner_candidate_id": winner_id,
                        "suppression_reason": "runner_up",
                        "winner_confidence": winner_conf,
                        "input_index": runner_up_idx,
                    }
                )

        return runner_up_entries

    # =========================================================================
    # Review Candidates - Public Methods
    # =========================================================================

    def bulk_insert_review_candidates(
        self,
        candidates: list[dict[str, Any]],
        *,
        log_suppressed: bool = False,
    ) -> list[int] | tuple[list[int], list[dict[str, Any]]]:
        """
        Bulk insert review candidates with conflict resolution.

        Handles conflicts by keeping higher-confidence candidates. When
        log_suppressed=True, also captures suppressed alternatives and
        runner-ups for UI display.

        Uses a two-phase algorithm:
        1. Conflict Detection: Pre-fetch existing candidates, resolve by confidence
        2. Runner-Up Capture: Log best alternative metric at each position

        Args:
            candidates: List of candidate dicts. Required keys:
                - filing_id, company_id, char_position, context_text
                - raw_number_text, triggering_keyword, keyword_distance
                - keyword_position
              Optional keys:
                - source_segment_id, parsed_value, parsed_unit
                - suggested_metric_id, suggestion_confidence, features
                - review_batch_id

            log_suppressed: If True, log suppressed candidates to
                suppressed_candidates table and return detailed info.

        Returns:
            If log_suppressed=False (default):
                list[int] - candidate_ids, one per input, in input order.
                           For conflicts where input loses, returns winner's ID.

            If log_suppressed=True:
                tuple[list[int], list[dict]] where:
                    - list[int]: candidate_ids as above
                    - list[dict]: suppression log entries with keys:
                        - suppressed_id: ID in suppressed_candidates table
                        - winner_candidate_id: ID of winning candidate
                        - suppression_reason: 'lower_confidence' | 'runner_up'
                        - input_index: index in original candidates list (or None)

        Guarantees:
            - len(returned_ids) == len(candidates) ALWAYS
            - returned_ids[i] is the candidate_id for candidates[i]
            - Order preserved: zip(candidates, returned_ids, strict=True) is safe

        Raises:
            ValidationError: If any candidate has invalid keyword_position
            ValidationError: If any candidate has invalid suggestion_confidence
        """
        if not candidates:
            return ([], []) if log_suppressed else []

        # Validate all candidates first (fail fast before any DB work)
        for i, candidate in enumerate(candidates):
            keyword_position = candidate["keyword_position"]
            validate_enum(
                keyword_position,
                KEYWORD_POSITIONS,
                f"keyword_position (candidate {i})",
            )

            validate_score(
                candidate.get("suggestion_confidence"),
                "suggestion_confidence",
                context=f"candidate {i}",
            )

        # =====================================================================
        # Phase 1: Within-Batch Deduplication
        # =====================================================================
        # Before checking the database, we first deduplicate within the input batch.
        # This handles the case where the same candidate appears multiple times in
        # a single call (e.g., from overlapping keyword matches).
        #
        # Uniqueness is determined by:
        #   - WITH segment: (filing_id, source_segment_id, char_position, metric_id)


---

## File 5: src/review/candidate_generator.py (If exists)

"""
Candidate Generator - Generate review candidates from filing segments.

This module scans source segments for numbers near metric keywords,
creating candidates for human review. It implements a high-recall
detection strategy to catch potential metrics.

Algorithm:
1. For each segment, find all numbers using regex
2. For each number, find metric keywords within 100 characters
3. Deduplicate by (number_position, metric_id)
4. Extract context (30-50 words each direction)
5. Create ReviewCandidate objects for bulk insert

Basic Usage:
    >>> from src.review import CandidateGenerator
    >>> from src.infra.db import DatabaseAdapter
    >>>
    >>> # Initialize with default config
    >>> db = DatabaseAdapter("postgresql://user:pass@localhost/filings_analysis")
    >>> generator = CandidateGenerator()
    >>>
    >>> # Fetch segments for a filing
    >>> segments = db.get_source_segments_for_filing(filing_id=123)
    >>>
    >>> # Generate candidates
    >>> candidates = generator.generate_for_filing(
    ...     filing_id=123,
    ...     company_id=456,
    ...     segments=segments,
    ... )
    >>>
    >>> # Save to database
    >>> db.bulk_insert_review_candidates([c.to_dict() for c in candidates])
    >>> print(f"Generated {len(candidates)} candidates")

Using Configuration Presets:
    >>> from src.review.config import (
    ...     get_high_precision_config,
    ...     get_high_recall_config,
    ...     get_fast_config,
    ... )
    >>>
    >>> # High precision: Fewer false positives, stricter matching
    >>> hp_generator = CandidateGenerator(config=get_high_precision_config())
    >>> hp_candidates = hp_generator.generate_for_filing(
    ...     filing_id=123, company_id=456, segments=segments
    ... )
    >>>
    >>> # High recall: Maximum coverage, more false positives
    >>> hr_generator = CandidateGenerator(config=get_high_recall_config())
    >>> hr_candidates = hr_generator.generate_for_filing(
    ...     filing_id=123, company_id=456, segments=segments
    ... )
    >>>
    >>> # Fast: Optimized for speed, no confidence scoring
    >>> fast_generator = CandidateGenerator(config=get_fast_config())
    >>> fast_candidates = fast_generator.generate_for_filing(
    ...     filing_id=123, company_id=456, segments=segments
    ... )

Custom Configuration:
    >>> from src.review.config import CandidateGenerationConfig
    >>>
    >>> # Create custom config for your use case
    >>> custom_config = CandidateGenerationConfig(
    ...     max_keyword_distance=75,        # Moderate proximity
    ...     min_metric_value=50,            # Filter small numbers
    ...     filter_false_positives=True,    # Enable filtering
    ...     compute_confidence=True,        # Enable confidence scoring
    ...     apply_learned_rules=True,       # Apply E2 patterns
    ...     min_pattern_precision=0.80,     # High-confidence patterns only
    ... )
    >>> custom_generator = CandidateGenerator(config=custom_config)
    >>> candidates = custom_generator.generate_for_filing(
    ...     filing_id=123, company_id=456, segments=segments
    ... )

Getting Statistics:
    >>> # Request processing statistics
    >>> candidates, stats = generator.generate_for_filing(
    ...     filing_id=123,
    ...     company_id=456,
    ...     segments=segments,
    ...     return_stats=True,
    ... )
    >>> print(f"Segments processed: {stats.segments_processed}")
    >>> print(f"Numbers found: {stats.numbers_found}")
    >>> print(f"False positives filtered: {stats.false_positives_filtered}")
    >>> print(f"Candidates generated: {stats.candidates_generated}")
    >>> print(f"Success rate: {stats.segment_success_rate:.1%}")

Convenience Wrapper (Recommended for simple workflows):
    >>> from src.review.helpers import generate_candidates_for_filing
    >>>
    >>> # One-liner that fetches segments and generates candidates
    >>> candidates = generate_candidates_for_filing(
    ...     db=db,
    ...     filing_id=123,
    ...     company_id=456,
    ... )

Backward Compatibility (Old API still works):
    >>> # Old style: individual parameters
    >>> generator = CandidateGenerator(
    ...     max_keyword_distance=50,
    ...     filter_false_positives=True,
    ...     min_value=100,  # Old parameter name
    ... )
    >>>
    >>> # New style: config object (recommended)
    >>> from src.review.config import CandidateGenerationConfig
    >>> config = CandidateGenerationConfig(
    ...     max_keyword_distance=50,
    ...     filter_false_positives=True,
    ...     min_metric_value=100,  # New parameter name
    ... )
    >>> generator = CandidateGenerator(config=config)

See Also:
    - config.py: Configuration presets and CandidateGenerationConfig
    - helpers.py: Convenience wrappers for common workflows
    - models.py: ReviewCandidate and ProcessingStats data structures
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from src.review.marker_row_parser import MarkerRowParser
    from src.review.table_structure import TableRowParser

from src.review.confidence_scoring import ConfidenceScorer
from src.review.config import (
    DEFAULT_CONFIG,
    DEFAULT_CONTEXT_WORDS,
    MAX_KEYWORD_DISTANCE,
    CandidateGenerationConfig,
)
from src.review.context_extraction import ContextExtractor
from src.review.deduplicator import deduplicate_candidates
from src.review.exceptions import (
    NumberProcessingError,
    SegmentProcessingError,
)
from src.review.false_positive_filter import (
    COUNT_ONLY_METRICS,
    DOLLAR_ONLY_METRICS,
    PERCENTAGE_ONLY_METRICS,
    FalsePositiveFilter,
    is_count_format,
    is_dollar_format,
    is_percentage_format,
    should_treat_as_percentage,
)
from src.review.feature_extractor import (
    FeatureExtractor,
)
from src.review.keyword_matching import (
    KeywordMatch,
    KeywordMatcher,
)
from src.review.models import (
    CandidateFeatures,
    ProcessingStats,
    ReviewCandidate,
    SegmentDict,
)
from src.review.number_parsing import NumberMatch, NumberParser

logger = logging.getLogger(__name__)


# =============================================================================
# Number Detection Patterns
# =============================================================================

# Number parsing functionality moved to src/review/number_parsing.py (P1.3)
# NUMBER_REGEX and NumberMatch are now imported from that module


# =============================================================================
# Metric Keywords (imported from keyword_matching.py)
# =============================================================================

# METRIC_KEYWORDS and SPECIFIC_KEYWORD_PATTERNS moved to
# src/review/keyword_matching.py (P1.3)
# They are imported from that module to maintain single source of truth


# =============================================================================
# Feature Detection Patterns (imported from feature_extractor)
# =============================================================================
# DEFINITION_PATTERNS, PERIOD_PATTERNS, and RISK_FACTORS_PATTERNS are now
# imported from src.review.feature_extractor to maintain single source of truth.


# =============================================================================
# False Positive Detection (imported from false_positive_filter.py)
# =============================================================================

# DATE_CONTEXT_PATTERNS, FALSE_POSITIVE_CONTEXT_PATTERNS, YEAR_MIN,
# YEAR_MAX, and MIN_METRIC_VALUE moved to src/review/false_positive_filter.py (P1.3)
# They are imported from that module to maintain single source of truth


# =============================================================================
# Configuration
# =============================================================================

# METRIC_EXPECTED_FORMATS moved to src/review/confidence_scoring.py
# ConfidenceScorer moved to src/review/confidence_scoring.py
# SPECIFIC_KEYWORD_PATTERNS moved to src/review/keyword_matching.py (P1.3)
# NumberMatch dataclass moved to src/review/number_parsing.py (P1.3)
# KeywordMatch dataclass moved to src/review/keyword_matching.py (P1.3)


# =============================================================================
# CandidateGenerator Class
# =============================================================================


class CandidateGenerator:
    """
    Generates review candidates from source segments.

    The generator scans text for numbers near metric keywords and creates
    ReviewCandidate objects for human review. It uses a high-recall strategy
    to avoid missing potential metrics.
    """

    # Maximum character distance between number and keyword
    # (imported from config.py for centralized configuration)
    MAX_KEYWORD_DISTANCE = MAX_KEYWORD_DISTANCE

    # Context extraction settings (imported from config.py)
    CONTEXT_WORDS = DEFAULT_CONTEXT_WORDS  # Words to extract each direction

    def __init__(
        self,
        config: CandidateGenerationConfig | None = None,
        # Deprecated parameters (for backward compatibility)
        max_keyword_distance: int | None = None,
        context_words: int | None = None,
        filter_false_positives: bool | None = None,
        min_value: int | None = None,
        filter_years: bool | None = None,
        compute_confidence: bool | None = None,
        apply_learned_rules: bool | None = None,
    ):
        """
        Initialize the candidate generator.

        Args:
            config: Configuration object. If None, uses DEFAULT_CONFIG or builds from deprecated params.

            # Deprecated parameters (use config instead):
            max_keyword_distance: DEPRECATED - Use config.max_keyword_distance
            context_words: DEPRECATED - Use config.context_words
            filter_false_positives: DEPRECATED - Use config.filter_false_positives
            min_value: DEPRECATED - Use config.min_metric_value
            filter_years: DEPRECATED - Use config.filter_years
            compute_confidence: DEPRECATED - Use config.compute_confidence
            apply_learned_rules: DEPRECATED - Use config.apply_learned_rules
        """
        # Handle config parameter vs deprecated individual parameters
        if config is not None:
            # Use provided config
            self.config = config
        elif any(
            param is not None
            for param in [
                max_keyword_distance,
                context_words,
                filter_false_positives,
                min_value,
                filter_years,
                compute_confidence,
                apply_learned_rules,
            ]
        ):
            # Build config from deprecated parameters (backward compatibility)
            self.config = CandidateGenerationConfig(
                max_keyword_distance=max_keyword_distance
                if max_keyword_distance is not None
                else DEFAULT_CONFIG.max_keyword_distance,
                context_words=context_words
                if context_words is not None
                else DEFAULT_CONFIG.context_words,
                filter_false_positives=filter_false_positives
                if filter_false_positives is not None
                else DEFAULT_CONFIG.filter_false_positives,
                min_metric_value=min_value
                if min_value is not None
                else DEFAULT_CONFIG.min_metric_value,
                filter_years=filter_years
                if filter_years is not None
                else DEFAULT_CONFIG.filter_years,
                compute_confidence=compute_confidence
                if compute_confidence is not None
                else DEFAULT_CONFIG.compute_confidence,
                apply_learned_rules=apply_learned_rules
                if apply_learned_rules is not None
                else DEFAULT_CONFIG.apply_learned_rules,
            )
        else:
            # Use default config
            self.config = DEFAULT_CONFIG

        # Set convenience attributes for backward compatibility
        self.max_keyword_distance = self.config.max_keyword_distance
        self.context_words = self.config.context_words
        self.filter_false_positives = self.config.filter_false_positives
        self.min_value = self.config.min_metric_value
        self.filter_years = self.config.filter_years
        self.compute_confidence = self.config.compute_confidence
        self.apply_learned_rules = self.config.apply_learned_rules

        # Initialize confidence scorer with config
        self._confidence_scorer = ConfidenceScorer(
            max_keyword_distance=self.config.max_keyword_distance,
            config=self.config,
        )

        # Initialize feature extractor
        self._feature_extractor = FeatureExtractor()

        # Initialize number parser (P1.3 - extracted to separate module)
        self._number_parser = NumberParser()

        # Initialize keyword matcher (P1.3 - extracted to separate module, P1 enhanced, P1.5 sentence-aware, L4 multiplier)
        self._keyword_matcher = KeywordMatcher(
            max_keyword_distance=self.config.max_keyword_distance,
            prefer_closest_keyword=self.config.prefer_closest_keyword,
            respect_bullet_boundaries=self.config.respect_bullet_boundaries,
            respect_sentence_boundaries=self.config.respect_sentence_boundaries,
            log_ambiguous_matches=self.config.log_ambiguous_matches,
            ambiguity_threshold=self.config.ambiguity_threshold,
            post_value_distance_multiplier=self.config.post_value_distance_multiplier,
        )

        # Initialize false positive filter (P1.3 - extracted to separate module)
        self._false_positive_filter = FalsePositiveFilter(
            filter_enabled=self.config.filter_false_positives,
            min_value=self.config.min_metric_value,
            filter_years=self.config.filter_years,
            toc_proximity_chars=self.config.toc_proximity_chars,
            toc_dot_leader_window=self.config.toc_dot_leader_window,
            filter_financial_statements=self.config.filter_financial_statements,  # HRV-10/11
            financial_statement_proximity_chars=self.config.financial_statement_proximity_chars,
        )

        # Initialize context extractor (P1.3 - extracted to separate module)
        self._context_extractor = ContextExtractor(context_words=self.config.context_words)

        # Cache for word positions during segment processing (optimization for P1.2)
        # This avoids re-parsing text into words for every number in a segment
        self._current_segment_words: list[tuple[int, int, str]] | None = None

        # Lazy-loaded RuleApplicator (E2 integration)
        self._rule_applicator: Any | None = None

    def _get_rule_applicator(self, db: Any) -> Any | None:
        """
        Lazy-load RuleApplicator for E2 learned pattern filtering.

        Args:
            db: DatabaseAdapter instance (needed for pattern loading)

        Returns:
            RuleApplicator instance

        Note:
            Only loads RuleApplicator if apply_learned_rules=True.
            Caches the instance for reuse across segments.
        """
        if self._rule_applicator is None and self.apply_learned_rules:
            from src.review.rule_applicator import RuleApplicator

            self._rule_applicator = RuleApplicator(db)
        return self._rule_applicator

    def generate_for_filing(
        self,
        filing_id: int,
        company_id: int,
        segments: list[SegmentDict],
        return_stats: bool = False,
        db: Any | None = None,
    ) -> list[ReviewCandidate] | tuple[list[ReviewCandidate], ProcessingStats]:
        """
        Generate candidates from all segments of a filing.

        Args:
            filing_id: The filing ID
            company_id: The company ID
            segments: List of segment dicts from database
            return_stats: If True, return (candidates, stats) tuple
            db: Optional DatabaseAdapter for learned rules filtering (E2)

        Returns:
            List of ReviewCandidate objects (not yet saved to DB)
            If return_stats=True, returns tuple of (candidates, ProcessingStats)
        """
        candidates = []
        stats = ProcessingStats()

        for segment in segments:
            # Safely get segment_id for logging (segment might not be a dict)
            segment_id = (
                segment.get("source_segment_id")
                if isinstance(segment, dict)
                else None
            )
            try:
                segment_candidates, segment_stats = self._process_segment(
                    filing_id=filing_id,
                    company_id=company_id,
                    segment=segment,
                    db=db,
                )
                candidates.extend(segment_candidates)
                stats.segments_processed += 1
                stats.numbers_found += segment_stats.get("numbers_found", 0)
                stats.numbers_failed += segment_stats.get("numbers_failed", 0)
                stats.false_positives_filtered += segment_stats.get(
                    "false_positives_filtered", 0
                )
                stats.filtered_by_learned_rules += segment_stats.get(
                    "filtered_by_learned_rules", 0
                )
                stats.candidates_generated += len(segment_candidates)
            except SegmentProcessingError as e:
                # Known segment-level error (validation failures, etc.)
                stats.segments_failed += 1
                logger.error(
                    f"Segment processing error for segment {segment_id} in filing {filing_id}: {e}"
                )
                # Continue processing other segments
            except (ValueError, TypeError, AttributeError) as e:
                # Unexpected but recoverable error in segment processing
                stats.segments_failed += 1
                logger.error(
                    f"Unexpected error processing segment {segment_id} in filing {filing_id}: "
                    f"{type(e).__name__}: {e}"
                )
                # Continue processing other segments

        # Deduplicate candidates across segments
        candidates, duplicates_removed = self._deduplicate_candidates(candidates)
        stats.duplicates_removed = duplicates_removed

        stats.log_summary(filing_id)

        if return_stats:
            return candidates, stats
        return candidates

    def _deduplicate_candidates(
        self, candidates: list[ReviewCandidate]
    ) -> tuple[list[ReviewCandidate], int]:
        """
        Remove duplicate candidates based on (parsed_value, suggested_metric_id, detected_period).

        Delegates to the standalone deduplicate_candidates function for reusability.
        P1.6: Passes prefer_same_sentence config setting for same-sentence preference.

        Args:
            candidates: List of candidates to deduplicate

        Returns:
            Tuple of (deduplicated_candidates, duplicates_removed_count)
        """
        return deduplicate_candidates(
            candidates,
            prefer_same_sentence=self.config.prefer_same_sentence_in_dedup,
        )

    def _process_segment(
        self,
        filing_id: int,
        company_id: int,
        segment: SegmentDict,
        db: Any | None = None,
    ) -> tuple[list[ReviewCandidate], dict[str, int]]:
        """
        Process a single segment to find candidates.

        Args:
            filing_id: The filing ID
            company_id: The company ID
            segment: Segment dict from database
            db: Optional DatabaseAdapter for learned rules filtering (E2)

        Returns:
            Tuple of (candidates, segment_stats)
            segment_stats contains counts for numbers_found, numbers_failed,
            false_positives_filtered, filtered_by_learned_rules
        """
        segment_stats = {
            "numbers_found": 0,
            "numbers_failed": 0,
            "false_positives_filtered": 0,
            "filtered_by_learned_rules": 0,
        }

        # Validate segment dict
        if not isinstance(segment, dict):
            raise SegmentProcessingError(
                f"Segment must be a dict, got {type(segment).__name__}"
            )

        text = segment.get("raw_text", "")
        if not text:
            return [], segment_stats

        # Validate text is a string
        if not isinstance(text, str):
            raise SegmentProcessingError(
                f"raw_text must be a string, got {type(text).__name__}",
                segment_id=segment.get("source_segment_id"),
            )

        source_segment_id = segment.get("source_segment_id")

        # Skip definition segments - they explain metrics but don't contain values (EI-1)
        if segment.get("contains_definition_flag"):
            logger.debug(
                f"Skipping definition segment {source_segment_id}: "
                "contains_definition_flag is True"
            )
            return [], segment_stats

        candidates = []

        # Find all numbers in the segment
        numbers = self._find_numbers(text)
        if not numbers:
            return [], segment_stats

        segment_stats["numbers_found"] = len(numbers)

        # Pre-compute all keyword matches once for efficiency (P1.1 optimization)
        # This avoids re-searching the text for every number
        all_keywords = self._find_all_keywords(text)

        # Pre-compute word positions once for efficiency (P1.2 optimization)
        # This avoids re-parsing text for context extraction for every number
        self._current_segment_words = self._context_extractor.parse_text_into_words(text)

        # Pre-compute semantic boundaries once for efficiency (P1 enhancement)
        # This enables boundary-aware keyword matching to avoid cross-boundary false positives
        from src.review.boundary_detection import BoundaryDetector

        boundaries = None
        detector: BoundaryDetector | None = None
        if self.config.enable_boundary_detection:
            detector = BoundaryDetector()
            boundaries = detector.find_boundaries(text)
            logger.debug(f"Detected {len(boundaries)} semantic boundaries in segment")

        # Pre-compute sentence boundaries for P1.5 sentence-aware filtering
        # This enables sentence-aware keyword matching to avoid cross-sentence false positives
        sentence_boundaries = None
        if self.config.detect_sentences:
            if detector is None:  # Reuse detector if already created
                detector = BoundaryDetector()
            segment_type = segment.get("segment_type")
            # Disable sentence detection for tables (configurable)
            if segment_type == "table" and not self.config.sentence_detection_for_tables:
                # Table segments get single boundary to prevent false negatives
                pass  # sentence_boundaries stays None, fallback to no sentence filtering
            else:
                sentence_boundaries = detector.find_sentence_boundaries(text, segment_type)
                if sentence_boundaries:
                    logger.debug(
                        f"Detected {len(sentence_boundaries)} sentences in segment"
                    )

        # Pre-compute table row structure for table row filtering
        # This prevents keywords in one row from matching with numbers in another row
        table_row_parser: MarkerRowParser | TableRowParser | None = None
        raw_html = segment.get("raw_html", "")

        # Check for markers first (more reliable when present)
        if " [ROW] " in text or " [CELL] " in text:
            from src.review.marker_row_parser import MarkerRowParser
            table_row_parser = MarkerRowParser(text)
        elif raw_html and ('<table' in raw_html.lower()):
            from src.review.table_structure import TableRowParser
            table_row_parser = TableRowParser(raw_html, text)

        if table_row_parser is not None and table_row_parser.is_table():
            logger.debug(
                f"Parsed {len(table_row_parser.get_rows())} table rows for row-aware matching"
            )

        # Track (number_position, metric_id) pairs to avoid duplicates
        seen: set[tuple[int, str]] = set()

        # For each number, find nearby keywords
        for num in numbers:
            try:
                # Filter out likely false positives
                is_fp, fp_reason = self._is_likely_false_positive(text, num)
                if is_fp:
                    logger.debug(
                        f"Filtered false positive: {num.raw_text!r} ({fp_reason})"
                    )
                    segment_stats["false_positives_filtered"] += 1
                    continue

                keyword_matches = self._find_keywords_near_number(
                    num, all_keywords, boundaries, sentence_boundaries, segment, table_row_parser
                )

                # Phase 7: If no nearby keywords found, check context_prefix
                # Context prefix contains the last sentence from the previous segment,
                # which may provide relevant keyword context for list items, etc.
                context_prefix_raw = segment.get("context_prefix", "")
                context_prefix = str(context_prefix_raw) if context_prefix_raw else ""
                from_context_prefix = False
                if not keyword_matches and context_prefix:
                    # Search context_prefix for keywords
                    context_keywords = self._find_all_keywords(context_prefix)
                    if context_keywords:
                        # Use context keywords (they won't have "nearby" relationship to number)
                        # Take first keyword per metric for simplicity
                        seen_metrics: set[str] = set()
                        for ck in context_keywords:
                            if ck.metric_id not in seen_metrics:
                                keyword_matches.append(ck)
                                seen_metrics.add(ck.metric_id)
                        from_context_prefix = True
                        logger.debug(
                            f"Found {len(keyword_matches)} keywords in context_prefix "
                            f"for number {num.raw_text!r}"
                        )

                for kw in keyword_matches:
                    # Deduplicate by (number_position, metric_id)
                    key = (num.start, kw.metric_id)
                    if key in seen:
                        continue
                    seen.add(key)

                    # Early exclusion check around NUMBER position
                    # This catches FPs where number is near exclusion context
                    # (e.g., contribution margin values matched to take rate)
                    # EXT-FN-1: Pass table_row_parser to limit exclusion context to same row
                    should_exclude, reason = self._keyword_matcher.should_exclude_for_number_context(
                        metric_id=kw.metric_id,
                        text=text,
                        number_position=num.start,
                        table_row_parser=table_row_parser,
                    )
                    if should_exclude:
                        segment_stats["excluded_by_number_context"] = (
                            segment_stats.get("excluded_by_number_context", 0) + 1
                        )
                        logger.debug(f"Excluded candidate: {reason}")
                        continue

                    # Calculate distance and position
                    # For context_prefix matches, use a special "large" distance
                    if from_context_prefix:
                        distance = 500  # Indicates "from context, not nearby"
                        keyword_position = "before"  # Context is from previous segment
                    else:
                        distance = self._calculate_distance(num, kw)
                        # L3: Use direction from KeywordMatch (handle "at" edge case by mapping to "before")
                        # Rationale: When keyword and number are at same position, treat as "before" (no penalty)
                        # since there's no temporal "after" relationship in reading order
                        keyword_position = "after" if kw.direction == "after" else "before"

                    # Extract context
                    context = self._extract_context(text, num.start)

                    # Compute ML features
                    features = self._compute_features(
                        number=num,
                        keyword_distance=distance,
                        keyword_position=keyword_position,
                        context_text=context,
                        segment=segment,
                        all_numbers=numbers,
                    )

                    # L4/E1: Compute context type for multiplier optimization
                    context_type = self._keyword_matcher.get_context_type(
                        text=text,
                        number_position=num.start,
                        keyword_position=kw.start,
                        keyword_direction=kw.direction if kw.direction else keyword_position,
                        boundaries=boundaries,
                        segment_type=segment.get("segment_type"),
                    )
                    features.context_type = context_type

                    # P1.6: Track if keyword and number are in the same sentence
                    if sentence_boundaries and not from_context_prefix:
                        number_sentence = self._keyword_matcher._get_boundary_at_position(
                            num.start, sentence_boundaries
                        )
                        keyword_sentence = self._keyword_matcher._get_boundary_at_position(
                            kw.start, sentence_boundaries
                        )
                        features.is_same_sentence = (
                            number_sentence is not None
                            and keyword_sentence is not None
                            and number_sentence == keyword_sentence
                        )
                    elif from_context_prefix:
                        # Context prefix matches are never "same sentence" (different segments)
                        features.is_same_sentence = False
                    else:
                        # Without sentence detection, assume same sentence (conservative)
                        features.is_same_sentence = True

                    # Phase 7: Track if keyword came from context_prefix
                    features.from_context_prefix = from_context_prefix

                    # Compute confidence score
                    confidence = None
                    if self.compute_confidence:
                        confidence = self._confidence_scorer.compute_confidence(
                            keyword_distance=distance,
                            keyword_position=keyword_position,
                            keyword=kw.keyword,
                            metric_id=kw.metric_id,
                            features=features,
                        )

                        # Phase 7: Apply 0.8x confidence penalty for context_prefix matches
                        # These matches are less certain since keyword is in a different segment
                        if from_context_prefix and confidence is not None:
                            confidence = confidence * 0.8
                            logger.debug(
                                f"Applied 0.8x confidence penalty for context_prefix match: "
                                f"{confidence:.3f}"
                            )

                    candidate = ReviewCandidate(
                        filing_id=filing_id,
                        company_id=company_id,
                        source_segment_id=source_segment_id,
                        char_position=num.start,
                        context_text=context,
                        raw_number_text=num.raw_text,
                        parsed_value=num.value,
                        parsed_unit=num.unit,
                        triggering_keyword=kw.keyword,
                        keyword_distance=distance,
                        keyword_position=keyword_position,
                        suggested_metric_id=kw.metric_id,
                        suggestion_confidence=confidence,
                        features=features,
                    )
                    candidates.append(candidate)

            except NumberProcessingError as e:
                # Known number-level error (already defined but not yet raised internally)
                segment_stats["numbers_failed"] += 1
                logger.warning(
                    f"Number processing error for {num.raw_text!r} at position {num.start}: {e}"
                )
                # Continue processing other numbers
            except (ValueError, TypeError, AttributeError, KeyError) as e:
                # Unexpected but recoverable error in number processing
                segment_stats["numbers_failed"] += 1
                logger.warning(
                    f"Unexpected error processing number {num.raw_text!r} at position {num.start}: "
                    f"{type(e).__name__}: {e}"
                )
                # Continue processing other numbers

        # Clear cached word positions (P1.2 optimization cleanup)
        self._current_segment_words = None

        # L1: Enrich with respectively patterns (before learned rules filtering)
        candidates = self._enrich_with_respectively_patterns(
            candidates=candidates,
            segment_text=text,
        )

        # E2: Apply learned pattern filtering if enabled
        if self.apply_learned_rules and db is not None:
            applicator = self._get_rule_applicator(db)
            if applicator is not None:
                filtered_candidates = []
                for candidate in candidates:
                    should_filter, reason = applicator.should_filter(
                        candidate, candidate.features
                    )
                    if should_filter:
                        segment_stats["filtered_by_learned_rules"] += 1
                        logger.debug(
                            f"Filtered candidate by learned rule: {reason} "
                            f"(value={candidate.parsed_value}, metric={candidate.suggested_metric_id})"
                        )
                    else:
                        filtered_candidates.append(candidate)
                candidates = filtered_candidates

        # HRV Type Validation: Filter candidates with wrong format for metric type
        if self.config.filter_false_positives:  # Reuse FP filter flag
            filtered_candidates = []
            for candidate in candidates:
                metric_id = candidate.suggested_metric_id
                raw_text = candidate.raw_number_text
                unit = candidate.parsed_unit or "count"
                context_text = candidate.context_text  # FIX-A: Get context for context-aware checks

                # Check if metric has type constraints
                type_mismatch = False
                mismatch_reason = None

                if metric_id in PERCENTAGE_ONLY_METRICS:
                    # FIX-A: Use context-aware percentage detection for retention metrics
                    if not should_treat_as_percentage(metric_id, raw_text, unit, context_text):
                        type_mismatch = True
                        mismatch_reason = f"{metric_id} expects percentage, got {unit}"

                elif metric_id in DOLLAR_ONLY_METRICS:
                    if not is_dollar_format(raw_text, unit):
                        type_mismatch = True
                        mismatch_reason = f"{metric_id} expects dollar amount, got {unit}"

                elif metric_id in COUNT_ONLY_METRICS:
                    if not is_count_format(raw_text, unit):
                        type_mismatch = True
                        mismatch_reason = f"{metric_id} expects count, got {unit}"

                if type_mismatch:
                    segment_stats["filtered_by_type_validation"] = segment_stats.get("filtered_by_type_validation", 0) + 1
                    logger.debug(
                        f"Filtered by type validation: {mismatch_reason} "
                        f"(value={candidate.parsed_value}, raw={raw_text})"
                    )
                else:
                    filtered_candidates.append(candidate)

            candidates = filtered_candidates

        return candidates, segment_stats

    def _find_numbers(self, text: str) -> list[NumberMatch]:
        """
        Find all numbers in text.

        Delegates to NumberParser (P1.3 - extracted to separate module).

        Args:
            text: The text to search

        Returns:
            List of NumberMatch objects
        """
        return self._number_parser.find_numbers(text)

    # _parse_number method removed - now part of NumberParser (P1.3)

    def _is_likely_false_positive(
        self, text: str, number: NumberMatch
    ) -> tuple[bool, str | None]:
        """
        Check if a number match is likely a false positive.

        Delegates to FalsePositiveFilter (P1.3 - extracted to separate module).

        Args:
            text: The full text containing the number
            number: The NumberMatch to check

        Returns:
            Tuple of (is_false_positive, reason)
            reason is None if not a false positive
        """
        return self._false_positive_filter.is_false_positive(text, number)

    def _find_all_keywords(self, text: str) -> list[KeywordMatch]:
        """
        Find all metric keywords in text.

        Delegates to KeywordMatcher (P1.3 - extracted to separate module).

        Args:
            text: The full text to search

        Returns:
            List of all KeywordMatch objects found, sorted by position
        """
        return self._keyword_matcher.find_all_keywords(text)

    def _find_keywords_near_number(
        self,
        number: NumberMatch,
        all_keywords: list[KeywordMatch],
        boundaries: list[Any] | None = None,
        sentence_boundaries: list[Any] | None = None,
        segment: SegmentDict | None = None,
        table_row_parser: Any | None = None,
    ) -> list[KeywordMatch]:
        """
        Find metric keywords within max_keyword_distance of a number.

        Delegates to KeywordMatcher (P1.3 - extracted to separate module, P1 enhanced, P1.5 sentence-aware).

        Args:
            number: The NumberMatch to search around
            all_keywords: Pre-computed list of all keyword matches in text
            boundaries: Optional list of TextBoundary objects for boundary-aware matching (P1 enhancement)
            sentence_boundaries: Optional list of TextBoundary objects for sentence-aware matching (P1.5 enhancement)
            segment: Optional segment dict for context (L4 Option C)
            table_row_parser: Optional TableRowParser for table row filtering

        Returns:
            List of KeywordMatch objects within range (one per metric)
        """
        # Extract text and segment_type for L4 Option C context detection
        text = segment.get("raw_text", "") if segment else ""
        segment_type = segment.get("segment_type") if segment else None

        return self._keyword_matcher.find_keywords_near_number(
            number,
            all_keywords,
            boundaries,
            sentence_boundaries,
            text=text,
            segment_type=segment_type,
            table_row_parser=table_row_parser,
        )

    def _calculate_distance(self, number: NumberMatch, keyword: KeywordMatch) -> int:
        """
        Calculate character distance between number and keyword.

        Delegates to KeywordMatcher (P1.3 - extracted to separate module).

        Args:
            number: NumberMatch
            keyword: KeywordMatch

        Returns:
            Minimum distance in characters
        """
        return self._keyword_matcher.calculate_distance(number, keyword)

    def _extract_context(self, text: str, position: int) -> str:
        """
        Extract context words around a position.

        Delegates to ContextExtractor (P1.3 - extracted to separate module).
        Uses cached word positions if available (optimization P1.2).

        Args:
            text: The full text
            position: Character position to center on

        Returns:
            Context string with ~context_words words each direction
        """
        return self._context_extractor.extract_context(
            text, position, cached_words=self._current_segment_words
        )

    def _compute_features(
        self,
        number: NumberMatch,
        keyword_distance: int,
        keyword_position: str,
        context_text: str,
        segment: SegmentDict,
        all_numbers: list[NumberMatch],
    ) -> CandidateFeatures:
        """
        Compute ML features for a candidate.

        Delegates to FeatureExtractor for feature computation.

        Args:
            number: The NumberMatch for this candidate
            keyword_distance: Distance to triggering keyword
            keyword_position: 'before' or 'after'
            context_text: Extracted context around number
            segment: Segment dict with metadata
            all_numbers: All numbers found in the segment

        Returns:
            CandidateFeatures instance
        """
        # Defensive: ensure segment is a dict
        if not isinstance(segment, dict):
            segment = {}  # type: ignore[unreachable]

        # Defensive: ensure all_numbers is a list
        if not isinstance(all_numbers, list):
            all_numbers = []  # type: ignore[unreachable]

        # Delegate to feature extractor
        return self._feature_extractor.compute_features(
            number_value=number.value,
            number_unit=number.unit,
            number_raw_text=number.raw_text,
            keyword_distance=keyword_distance,
            keyword_position=keyword_position,
            context_text=context_text,
            segment_type=segment.get("segment_type"),
            section_heading=segment.get("section_heading"),
            section_path=segment.get("section_path"),
            surrounding_numbers_count=max(0, len(all_numbers) - 1),
        )

    def _enrich_with_respectively_patterns(
        self,
        candidates: list[ReviewCandidate],
        segment_text: str,
    ) -> list[ReviewCandidate]:
        """
        Enrich candidates with period associations from respectively patterns (L1).

        Detects patterns like:
            "Revenue for 2015, 2016 and 2017 was $1M, $2M and $3M, respectively."

        And enriches matching candidates with detected_period="2015" etc. in features.

        Args:
            candidates: Candidates generated from segment
            segment_text: Full segment text to search for patterns

        Returns:
            Enriched candidates with detected_period in features
        """
        # Skip if disabled
        if not self.config.detect_respectively_patterns:
            return candidates

        # L1-P1.2: Detect patterns (single or multiple depending on config)
        from src.review.respectively_parser import (
            detect_all_respectively_patterns,
            detect_respectively_pattern,
        )

        if self.config.detect_all_respectively_patterns:
            # Detect ALL patterns in segment
            patterns = detect_all_respectively_patterns(
                segment_text,
                min_confidence=self.config.respectively_min_confidence
            )
        else:
            # Backward compatible: detect only first pattern
            pattern = detect_respectively_pattern(
                segment_text,
                min_confidence=self.config.respectively_min_confidence
            )
            patterns = [pattern] if pattern else []

        # No patterns found
        if not patterns:
            return candidates

        # Build lookup: normalized value -> (period, confidence)
        # If multiple patterns have same value, use highest confidence
        value_to_period: dict[str, tuple[str, float]] = {}
        for pattern in patterns:
            for value_text, period_text in pattern.associations:
                normalized = self._normalize_value_text(value_text)

                # Keep highest confidence if duplicate
                if normalized in value_to_period:
                    existing_confidence = value_to_period[normalized][1]
                    if pattern.confidence > existing_confidence:
                        value_to_period[normalized] = (period_text, pattern.confidence)
                else:
                    value_to_period[normalized] = (period_text, pattern.confidence)

        # Enrich candidates
        enriched_count = 0
        for candidate in candidates:
            # Try to match candidate value to pattern value
            normalized_candidate = self._normalize_value_text(
                candidate.raw_number_text or ""
            )

            if normalized_candidate in value_to_period:
                period, confidence = value_to_period[normalized_candidate]

                # Update features
                if candidate.features:
                    candidate.features.detected_period = period
                    candidate.features.respectively_confidence = confidence
                    enriched_count += 1

        if enriched_count > 0:
            logger.info(
                f"Enriched {enriched_count}/{len(candidates)} candidates with "
                f"{len(patterns)} respectively pattern(s)"
            )

        return candidates

    def _normalize_value_text(self, value_text: str) -> str:
        """
        Normalize value text for matching (remove spaces, standardize units).

        L1-P1.3 Enhancement: Standardizes magnitude suffixes for consistent matching.

        Used to match candidate raw_number_text with respectively pattern values.
        Handles variations like "million" vs "M", "billion" vs "B", etc.

        Examples:
            "$1M" -> "$1m"
            "$ 1 M" -> "$1m"
            "$1 million" -> "$1m"
            "$1Million" -> "$1m"
            "33.0%" -> "33.0%"
            "1.42" -> "1.42"
            "10 thousand" -> "10k"
            "5bn" -> "5b"

        Args:
            value_text: Raw value text to normalize

        Returns:
            Normalized text for matching
        """
        # Remove spaces
        normalized = value_text.replace(" ", "")

        # Standardize magnitude suffixes (long form → short form, then lowercase)
        # Order matters: do long forms first to avoid partial replacements
        replacements = [
            ("million", "m"),
            ("Million", "m"),
            ("MILLION", "m"),
            ("billion", "b"),
            ("Billion", "b"),
            ("BILLION", "b"),
            ("thousand", "k"),
            ("Thousand", "k"),
            ("THOUSAND", "k"),
            ("mn", "m"),  # Alternate short form
            ("MN", "m"),
            ("Mn", "m"),
            ("bn", "b"),  # Alternate short form
            ("BN", "b"),
            ("Bn", "b"),
            ("M", "m"),  # Lowercase remaining
            ("B", "b"),
            ("K", "k"),
        ]

        for old, new in replacements:
            normalized = normalized.replace(old, new)

        return normalized


# =============================================================================
# Convenience Functions
# =============================================================================

# generate_candidates_for_filing() moved to src/review/helpers.py


---

## File 6: src/review/keyword_matching.py

"""
Keyword Matching - Find metric keywords in text and match them to numbers.

This module provides functionality to find metric keywords in text and
determine which keywords are near which numbers. It handles:
- Finding all keyword matches in text
- Filtering keywords by distance from numbers
- Calculating distances between text spans
- Table-aware matching with row boundary filtering (prevents cross-row matches)
- Row heading priority (prefers keywords in first cell of table rows)

Extracted from candidate_generator.py as part of P1.3 module splitting
for improved maintainability and testability.

Automatic Usage (via CandidateGenerator):
    >>> from src.review import CandidateGenerator
    >>>
    >>> # Keyword matching happens automatically
    >>> generator = CandidateGenerator()
    >>> candidates = generator.generate_for_filing(
    ...     filing_id=123, company_id=456, segments=segments
    ... )
    >>> # Each candidate has triggering_keyword field
    >>> print(candidates[0].triggering_keyword)  # e.g., "active customers"

Direct Usage (advanced):
    >>> from src.review.keyword_matching import KeywordMatcher
    >>> from src.review.number_parsing import NumberMatch
    >>> from decimal import Decimal
    >>>
    >>> # Initialize matcher
    >>> matcher = KeywordMatcher(max_keyword_distance=100)
    >>>
    >>> # Find all keywords in text
    >>> text = "We have 50,000 active customers and $100M in revenue."
    >>> keywords = matcher.find_all_keywords(text)
    >>> print(f"Found {len(keywords)} keyword matches")
    >>>
    >>> # Find keywords near a specific number
    >>> number = NumberMatch(
    ...     start=8, end=14, raw_text="50,000", value=Decimal("50000"), unit="count"
    ... )
    >>> nearby = matcher.find_keywords_near_number(number, keywords)
    >>> for kw in nearby:
    ...     print(f"{kw.keyword} (metric: {kw.metric_id}, distance: {kw.distance})")

Adjusting Proximity Threshold:
    >>> from src.review.config import CandidateGenerationConfig
    >>>
    >>> # Stricter proximity (high precision)
    >>> config = CandidateGenerationConfig(
    ...     max_keyword_distance=50,  # Only match if within 50 chars
    ... )
    >>> generator = CandidateGenerator(config=config)
    >>> candidates = generator.generate_for_filing(
    ...     filing_id=123, company_id=456, segments=segments
    ... )
    >>>
    >>> # Looser proximity (high recall)
    >>> config = CandidateGenerationConfig(
    ...     max_keyword_distance=150,  # Match within 150 chars
    ... )
    >>> generator = CandidateGenerator(config=config)

Understanding Distance Calculation:
    >>> # Distance is character distance between spans
    >>> # If keyword ends at position 50 and number starts at 60:
    >>> # distance = 60 - 50 = 10 characters
    >>> # Whitespace counts toward distance
    >>>
    >>> # Example: "active customers 50,000"
    >>> # Keyword: "active customers" (positions 0-16)
    >>> # Number: "50,000" (positions 17-23)
    >>> # Distance: 17 - 16 = 1 character

See Also:
    - candidate_generator.py: Uses KeywordMatcher internally
    - config.py: Configure max_keyword_distance
"""

import logging
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Optional, cast

from src.review.number_parsing import NumberMatch

if TYPE_CHECKING:
    from src.review.boundary_detection import TextBoundary
    from src.review.marker_row_parser import MarkerRowParser
    from src.review.table_structure import TableRowParser

logger = logging.getLogger(__name__)


# =============================================================================
# Keyword Loading Functions
# =============================================================================

def _load_metric_keywords() -> dict[str, list[str]]:
    """Load metric keywords from YAML config, excluding deprecated metrics.

    Raises:
        KeywordConfigError: If YAML config cannot be loaded.
    """
    from src.extraction.keyword_config import get_metric_keywords, is_metric_deprecated

    all_keywords = get_metric_keywords()

    # Filter out deprecated metrics
    active_keywords = {
        metric_id: patterns
        for metric_id, patterns in all_keywords.items()
        if not is_metric_deprecated(metric_id)
    }

    logger.info(
        f"Loaded {len(active_keywords)} active metrics "
        f"({len(all_keywords) - len(active_keywords)} deprecated, skipped)"
    )

    return cast(dict[str, list[str]], active_keywords)


def _load_exclusion_patterns() -> dict[str, list[str]]:
    """Load exclusion patterns from YAML config, excluding deprecated metrics.

    Raises:
        KeywordConfigError: If YAML config cannot be loaded.
    """
    from src.extraction.keyword_config import get_exclusion_patterns, is_metric_deprecated

    all_exclusions = get_exclusion_patterns()

    # Filter out deprecated metrics
    active_exclusions = {
        metric_id: patterns
        for metric_id, patterns in all_exclusions.items()
        if not is_metric_deprecated(metric_id)
    }

    return cast(dict[str, list[str]], active_exclusions)


def _load_specific_patterns() -> list[str]:
    """Load specific (multi-word) patterns from YAML config.

    Raises:
        KeywordConfigError: If YAML config cannot be loaded.
    """
    from src.extraction.keyword_config import get_specific_patterns
    return cast(list[str], get_specific_patterns())


def _load_required_context() -> dict[str, dict[str, Any]]:
    """Load required context patterns from YAML config, excluding deprecated metrics.

    Required context patterns gate which metrics generate review candidates.
    Metrics with required_context only generate candidates when at least one
    of the context patterns appears within proximity of the keyword match.

    Raises:
        KeywordConfigError: If YAML config cannot be loaded.
    """
    from src.extraction.keyword_config import get_required_context, is_metric_deprecated

    all_context = get_required_context()

    # Filter out deprecated metrics
    active_context = {
        metric_id: context
        for metric_id, context in all_context.items()
        if not is_metric_deprecated(metric_id)
    }

    return cast(dict[str, dict[str, Any]], active_context)


# =============================================================================
# Module-Level Keyword Data (loaded at import time)
# =============================================================================

# These are loaded once at module import and used throughout
METRIC_KEYWORDS: dict[str, list[str]] = _load_metric_keywords()
METRIC_EXCLUSION_PATTERNS: dict[str, list[str]] = _load_exclusion_patterns()
SPECIFIC_KEYWORD_PATTERNS: list[str] = _load_specific_patterns()
METRIC_REQUIRED_CONTEXT: dict[str, dict[str, Any]] = _load_required_context()


# =============================================================================
# Data Classes
# =============================================================================


@dataclass
class KeywordMatch:
    """A keyword match found in text."""

    start: int  # Character position
    end: int  # End position
    keyword: str  # The matched text
    metric_id: str  # Associated metric ID
    pattern: str  # The regex pattern that matched
    direction: str | None = None  # 'before' | 'after' | 'at' (relative to number, L3 enhancement)


# =============================================================================
# KeywordMatcher Class
# =============================================================================


class KeywordMatcher:
    """
    Matcher for finding metric keywords in text.

    Handles finding all keyword matches in text and filtering them by
    distance from numbers. Uses pre-compiled regex patterns for efficiency.

    P1 Enhancements:
    - Sort by distance first (closest keyword), then length (longest)
    - Boundary-aware matching (prefer keywords in same boundary as number)
    - Ambiguity logging when multiple keywords are equally close

    P1.5 Enhancements:
    - Sentence-aware matching (filter keywords from different sentences)

    L4 Enhancement:
    - Post-value distance multiplier (prefer keywords before values)
    - Context-dependent multipliers (Option C: different preferences by context)
    """

    def __init__(
        self,
        max_keyword_distance: int = 100,
        prefer_closest_keyword: bool = True,
        respect_bullet_boundaries: bool = True,
        respect_sentence_boundaries: bool = True,
        log_ambiguous_matches: bool = True,
        ambiguity_threshold: int = 10,
        post_value_distance_multiplier: float = 0.9,
        use_context_dependent_multipliers: bool = True,
        multiplier_bullet_points: float = 0.9,
        multiplier_parenthetical: float = 1.15,
        multiplier_tables: float = 0.85,
        multiplier_copula_verb: float = 0.9,
        multiplier_preposition: float = 1.1,
        multiplier_default: float = 0.9,
    ):
        """
        Initialize the keyword matcher.

        Args:
            max_keyword_distance: Maximum character distance between number
                                 and keyword for a match
            prefer_closest_keyword: Sort by distance first, then length (P1 enhancement)
            respect_bullet_boundaries: Prefer keywords in same boundary as number (P1 enhancement)
            respect_sentence_boundaries: Filter keywords from different sentences (P1.5 enhancement)
            log_ambiguous_matches: Log when multiple keywords are equally close (P1 enhancement)
            ambiguity_threshold: Characters to consider "equally close" (default: 10)
            post_value_distance_multiplier: Base multiplier for post-value keyword distances (L4 enhancement)
            use_context_dependent_multipliers: Enable context-dependent multiplier logic (L4 Option C)
            multiplier_bullet_points: Multiplier for bullet point contexts (L4 Option C)
            multiplier_parenthetical: Multiplier for parenthetical text (L4 Option C)
            multiplier_tables: Multiplier for table contexts (L4 Option C)
            multiplier_copula_verb: Multiplier for copula verb contexts (L4 Option C)
            multiplier_preposition: Multiplier for prepositional phrases (L4 Option C)
            multiplier_default: Default multiplier when no context detected (L4 Option C)
        """
        self.max_keyword_distance = max_keyword_distance
        self.prefer_closest_keyword = prefer_closest_keyword
        self.respect_bullet_boundaries = respect_bullet_boundaries
        self.respect_sentence_boundaries = respect_sentence_boundaries
        self.log_ambiguous_matches = log_ambiguous_matches
        self.ambiguity_threshold = ambiguity_threshold
        self.post_value_distance_multiplier = post_value_distance_multiplier

        # L4 Option C: Context-dependent multipliers
        self.use_context_dependent_multipliers = use_context_dependent_multipliers
        self.multiplier_bullet_points = multiplier_bullet_points
        self.multiplier_parenthetical = multiplier_parenthetical
        self.multiplier_tables = multiplier_tables
        self.multiplier_copula_verb = multiplier_copula_verb
        self.multiplier_preposition = multiplier_preposition
        self.multiplier_default = multiplier_default

        # Pre-compile all keyword patterns for reuse
        self._compiled_patterns: dict[str, list[tuple[re.Pattern[str], str]]] = {}
        for metric_id, patterns in METRIC_KEYWORDS.items():
            self._compiled_patterns[metric_id] = [
                (re.compile(pattern, re.IGNORECASE), pattern) for pattern in patterns
            ]

        # HRI-3: Pre-compile exclusion patterns for reuse
        self._compiled_exclusions: dict[str, list[re.Pattern[str]]] = {}
        for metric_id, exclusion_patterns in METRIC_EXCLUSION_PATTERNS.items():
            compiled_list: list[re.Pattern[str]] = []
            for pattern in exclusion_patterns:
                try:
                    compiled_list.append(re.compile(pattern, re.IGNORECASE))
                except re.error as e:
                    # Log and skip invalid patterns - don't crash
                    logger.warning(
                        f"Invalid exclusion pattern for {metric_id}: {pattern!r} - {e}"
                    )
            if compiled_list:
                self._compiled_exclusions[metric_id] = compiled_list

        # Pre-compile required context patterns for revenue synonym filtering
        # tuple of (compiled_patterns, proximity_chars)
        self._compiled_required_context: dict[str, tuple[list[re.Pattern[str]], int]] = {}
        for metric_id, ctx_config in METRIC_REQUIRED_CONTEXT.items():
            compiled_ctx_patterns: list[re.Pattern[str]] = []
            for pattern in ctx_config.get("patterns", []):
                try:
                    compiled_ctx_patterns.append(re.compile(pattern, re.IGNORECASE))
                except re.error as e:
                    logger.warning(
                        f"Invalid required_context pattern for {metric_id}: {pattern!r} - {e}"
                    )
            if compiled_ctx_patterns:
                proximity = ctx_config.get("proximity_chars", 1500)
                self._compiled_required_context[metric_id] = (
                    compiled_ctx_patterns,
                    proximity,
                )

    def _is_excluded(self, metric_id: str, context: str) -> bool:
        """
        Check if context contains an exclusion pattern for this metric.

        HRI-3 Enhancement: Prevents misclassifications by checking if the
        surrounding context indicates a different metric should be matched.

        Args:
            metric_id: The metric ID to check exclusions for
            context: The surrounding text context (typically ±50 chars)

        Returns:
            True if any exclusion pattern matches, False otherwise
        """
        if metric_id not in self._compiled_exclusions:
            return False

        for pattern in self._compiled_exclusions[metric_id]:
            if pattern.search(context):
                return True
        return False

    def should_exclude_for_number_context(
        self,
        metric_id: str,
        text: str,
        number_position: int,
        window_chars: int = 100,
        table_row_parser: "TableRowParser | MarkerRowParser | None" = None,
    ) -> tuple[bool, str | None]:
        """
        Check if a candidate should be excluded based on NUMBER context.

        Called by CandidateGenerator before feature extraction.
        Uses the same compiled exclusion patterns as keyword-context exclusions.

        This addresses the architecture issue where keyword-context exclusions
        (checked during find_all_keywords) use ±50 chars around the KEYWORD,
        but some false positives occur when numbers are far from keywords
        but near exclusion-worthy context.

        EXT-FN-1 Enhancement: When a table_row_parser is provided and the
        segment is a table, the exclusion context is limited to ONLY the text
        within the same table row as the number. This prevents false exclusions
        where keywords like "Net Dollar Retention Rate" in an adjacent row
        incorrectly exclude values from the "Paid Customers >$100,000" row.

        Args:
            metric_id: The metric ID to check exclusions for
            text: The full text containing the number
            number_position: Character position of the number in text
            window_chars: Characters around number position to check (default: 100)
            table_row_parser: Optional parser for table row boundaries. If provided
                and segment is a table, limits exclusion context to same row only.

        Returns:
            Tuple of (should_exclude, reason)
            reason is a string like "exclusion:number_context:<pattern>" if excluded,
            None if not excluded
        """
        if metric_id not in self._compiled_exclusions:
            return False, None

        # EXT-FN-1: If table_row_parser provided and it's a table,
        # limit exclusion context to the same row as the number
        if table_row_parser is not None and table_row_parser.is_table():
            row = table_row_parser.get_row_at_position(number_position)
            if row is not None:
                # Use row text as context instead of window-based context
                context = row.row_text
            else:
                # Position not in any row - fall back to window-based context
                # This is unexpected in normal operation, so log at debug level
                logger.debug(
                    f"EXT-FN-1: Position {number_position} not in parsed rows, "
                    f"using {window_chars}-char window fallback"
                )
                start = max(0, number_position - window_chars)
                end = min(len(text), number_position + window_chars)
                context = text[start:end]
        else:
            # No table parser or not a table - use original window-based context
            start = max(0, number_position - window_chars)
            end = min(len(text), number_position + window_chars)
            context = text[start:end]

        for pattern in self._compiled_exclusions[metric_id]:
            if pattern.search(context):
                return True, f"exclusion:number_context:{pattern.pattern}"

        return False, None

    def _has_required_context(
        self, metric_id: str, match_position: int, full_text: str
    ) -> bool:
        """
        Check if required context is present for a context-gated metric.

        For metrics with required_context configuration (e.g., cm_gmv, cm_tcv),
        this checks if at least one of the required context patterns (cohort,
        per customer, etc.) appears within the specified proximity of the
        keyword match.

        Revenue synonym metrics (GMV, TCV, ACV, Bookings, Billings) require
        cohort or per-customer context to be meaningful as customer metrics.
        Without this context, they are just aggregate revenue measures.

        Args:
            metric_id: The metric ID to check required context for
            match_position: The character position of the keyword match
            full_text: The full text to search for context

        Returns:
            True if no required context is configured for this metric, OR
            True if required context IS configured AND at least one pattern is found.
            False if required context IS configured but NO patterns are found.
        """
        if metric_id not in self._compiled_required_context:
            return True  # No required context for this metric - always matches

        patterns, proximity_chars = self._compiled_required_context[metric_id]

        # Define the search window around the match position
        context_start = max(0, match_position - proximity_chars)
        context_end = min(len(full_text), match_position + proximity_chars)
        context = full_text[context_start:context_end]

        # Check if ANY required context pattern matches
        for pattern in patterns:
            if pattern.search(context):
                logger.debug(
                    f"Required context found for {metric_id} at position {match_position}: "
                    f"pattern '{pattern.pattern}' matched within {proximity_chars} chars"
                )
                return True

        logger.debug(
            f"Required context NOT found for {metric_id} at position {match_position}: "
            f"no cohort/per-customer patterns within {proximity_chars} chars"
        )
        return False

    def find_all_keywords(self, text: str) -> list[KeywordMatch]:
        """
        Find all metric keywords in text.

        Searches text for all metric keyword patterns. Uses pre-compiled
        patterns for efficiency, but searches each pattern individually.
        This approach is faster than combining patterns due to regex engine
        behavior with large alternations.

        HRI-3 Enhancement:
        - Applies exclusion pattern filtering to prevent misclassifications
        - Checks surrounding context (±50 chars) for exclusion patterns
        - Skips matches where exclusion pattern indicates wrong metric

        Args:
            text: The full text to search

        Returns:
            List of all KeywordMatch objects found, sorted by position
        """
        all_matches = []

        # Search with each compiled pattern (faster than combined pattern due to early exits)
        for metric_id, compiled_patterns in self._compiled_patterns.items():
            for compiled_pattern, pattern_str in compiled_patterns:
                for match in compiled_pattern.finditer(text):
                    # HRI-3: Check exclusion patterns before adding match
                    # Get context around the match (±50 chars)
                    context_start = max(0, match.start() - 50)
                    context_end = min(len(text), match.end() + 50)
                    context = text[context_start:context_end]

                    # Skip if exclusion pattern matches in context
                    if self._is_excluded(metric_id, context):
                        logger.debug(
                            f"Excluded match: '{match.group()}' for {metric_id} "
                            f"due to exclusion pattern in context"
                        )
                        continue

                    all_matches.append(
                        KeywordMatch(
                            start=match.start(),
                            end=match.end(),
                            keyword=match.group(),
                            metric_id=metric_id,
                            pattern=pattern_str,
                        )
                    )

        # Sort by position
        all_matches.sort(key=lambda m: m.start)
        return all_matches

    def find_keywords_near_number(
        self,
        number: NumberMatch,
        all_keywords: list[KeywordMatch],
        boundaries: list["TextBoundary"] | None = None,
        sentence_boundaries: list["TextBoundary"] | None = None,
        text: str = "",
        segment_type: str | None = None,
        table_row_parser: Optional["TableRowParser"] = None,
        check_required_context: bool = True,
    ) -> list[KeywordMatch]:
        """
        Find metric keywords within max_keyword_distance of a number.

        Uses pre-computed keyword matches for efficiency. Returns at most
        one keyword per metric ID (the closest one). Filters out keywords
        that are substrings of other matched keywords at overlapping positions
        (e.g., if "LTV/CAC" is matched, don't also match "LTV" and "CAC").

        P1 Enhancements:
        - Sorts by distance first (closest), then length (longest)
        - Applies boundary constraints if boundaries provided
        - Logs ambiguous matches when multiple keywords are equally close

        P1.5 Enhancements:
        - Applies sentence boundary constraints if sentence_boundaries provided
        - Filters keywords from different sentences than the number

        L4 Option C Enhancement:
        - Context-dependent multipliers for post-value keywords
        - Different preferences based on textual context (tables, bullets, parentheticals)

        Table Row Filtering Enhancement:
        - Filters out keywords from different table rows than the number
        - Prevents false matches where keyword in one row associates with value from another row

        Args:
            number: The NumberMatch to search around
            all_keywords: Pre-computed list of all keyword matches in text
            boundaries: Optional list of TextBoundary objects for boundary-aware matching
            sentence_boundaries: Optional list of sentence boundaries for P1.5 filtering
            text: Optional full text for context detection (L4 Option C)
            segment_type: Optional segment type for context detection (L4 Option C)
            table_row_parser: Optional TableRowParser for table row filtering
            check_required_context: If True (default), filter out revenue synonym
                metrics (GMV, TCV, etc.) that lack cohort or per-customer context.
                Set to False to include all matches regardless of context.

        Returns:
            List of KeywordMatch objects within range (one per metric,
            prioritizing closest, then longest keywords)
        """
        # Phase 1: Collect all keywords within distance with their distances and directions
        # Store as (keyword, raw_distance, direction) for L4 multiplier application
        # Also filter by required context for revenue synonym metrics
        #
        # FIX-5: For tables with row/cell structure, skip distance filter in Phase 1
        # and rely on Phase 2.75 (table row filtering) instead. This prevents
        # missing values in wide tables where the row heading keyword is >100 chars
        # from some values in the same row. Distance is still computed for ranking.
        # Note: We check for table_row_parser presence (not just is_table()) because
        # single-row tables with [CELL] markers also need unrestricted same-row matching.
        has_table_structure = table_row_parser is not None

        candidates_with_distance: list[tuple[KeywordMatch, int]] = []
        for kw in all_keywords:
            dist = self.calculate_distance_from_positions(
                number.start, number.end, kw.start, kw.end
            )
            # Apply distance filter only if NOT in a table with row structure
            if not has_table_structure and dist > self.max_keyword_distance:
                continue

            # Check required context for context-gated metrics (GMV, TCV, etc.)
            if check_required_context and not self._has_required_context(
                kw.metric_id, kw.start, text
            ):
                logger.debug(
                    f"Filtered keyword '{kw.keyword}' ({kw.metric_id}): "
                    f"required cohort/per-customer context not present"
                )
                continue
            candidates_with_distance.append((kw, dist))

        if not candidates_with_distance:
            return []

        # Phase 2: Apply boundary constraints (P1 enhancement)
        if boundaries and self.respect_bullet_boundaries:
            # Find the boundary containing the number
            number_boundary = self._get_boundary_at_position(number.start, boundaries)

            if number_boundary is not None:
                # Separate candidates into same-boundary vs cross-boundary
                same_boundary = [
                    (kw, dist)
                    for kw, dist in candidates_with_distance
                    if self._is_in_same_boundary(kw.start, number_boundary, boundaries)
                ]

                # Prefer same-boundary candidates if any exist
                if same_boundary:
                    logger.debug(
                        f"Boundary filtering: {len(same_boundary)}/{len(candidates_with_distance)} "
                        f"keywords in same boundary as number at position {number.start}"
                    )
                    candidates_with_distance = same_boundary

        # Phase 2.5: Apply sentence boundary constraints (P1.5 enhancement)
        if sentence_boundaries and self.respect_sentence_boundaries:
            # Find the sentence containing the number
            number_sentence = self._get_boundary_at_position(
                number.start, sentence_boundaries
            )

            if number_sentence is not None:
                # Filter to keywords in the same sentence as the number
                same_sentence = [
                    (kw, dist)
                    for kw, dist in candidates_with_distance
                    if self._is_in_same_boundary(
                        kw.start, number_sentence, sentence_boundaries
                    )
                ]

                # Only filter if we have same-sentence candidates
                # (fallback: if no same-sentence keywords, keep all)
                if same_sentence:
                    if len(same_sentence) < len(candidates_with_distance):
                        logger.debug(
                            f"Sentence filtering: {len(same_sentence)}/{len(candidates_with_distance)} "
                            f"keywords in same sentence as number '{number.raw_text}'"
                        )
                    candidates_with_distance = same_sentence
                else:
                    # No same-sentence keywords found - keep all candidates (fallback)
                    logger.debug(
                        f"Sentence filtering fallback: no keywords in same sentence "
                        f"as number '{number.raw_text}'; keeping all {len(candidates_with_distance)} candidates"
                    )

        # Phase 2.75: Apply table row constraints (Table Row Filtering Enhancement)
        if table_row_parser is not None and table_row_parser.is_table():
            # Filter to keywords in the same table row as the number
            same_row = [
                (kw, dist)
                for kw, dist in candidates_with_distance
                if table_row_parser.are_in_same_row(kw.start, number.start)
            ]

            # Strict row filtering: only keep same-row keywords
            # Numbers without same-row keywords are not valid metric candidates
            if len(same_row) < len(candidates_with_distance):
                filtered_count = len(candidates_with_distance) - len(same_row)
                logger.debug(
                    f"Table row filtering: kept {len(same_row)}/{len(candidates_with_distance)} "
                    f"keywords in same row as '{number.raw_text}' (filtered {filtered_count} cross-row)"
                )
            candidates_with_distance = same_row

        # Phase 3: Sort by distance first, then length (P1 enhancement + L4 multiplier + L4 Option C)
        if self.prefer_closest_keyword:
            # L4 Option C: Compute effective distance using context-dependent multipliers
            candidates_with_effective_distance: list[tuple[KeywordMatch, int, float]] = []

            for kw, raw_distance in candidates_with_distance:
                # Compute direction to determine if multiplier applies
                direction = self.calculate_keyword_direction(kw.start, number.start)

                # Get context-appropriate multiplier (L4 Option C)
                multiplier = self.get_context_multiplier(
                    text=text,
                    number_position=number.start,
                    keyword_position=kw.start,
                    keyword_direction=direction,
                    boundaries=boundaries,
                    segment_type=segment_type,
                )

                # Apply multiplier to post-value keywords by dividing
                # Example: distance=100, multiplier=0.9 → effective=111.11 (less favorable)
                # Example: distance=100, multiplier=1.15 → effective=86.96 (more favorable)
                effective_distance = (
                    raw_distance / multiplier if direction == "after" else float(raw_distance)
                )

                # Row Heading Priority: Keywords in table row headings (first cell) get strong preference
                # This ensures we match "Gross profit" (row heading) over "Gross profit margin"
                # (different row) when a value appears in the "Gross profit" row
                if table_row_parser is not None and table_row_parser.is_table():
                    if table_row_parser.is_row_heading(kw.start):
                        # Apply 0.25x multiplier (75% reduction) to effective distance
                        # This makes row headings strongly preferred over other keywords
                        effective_distance *= 0.25
                        logger.debug(
                            f"Row heading priority: '{kw.keyword}' effective distance "
                            f"reduced {raw_distance:.1f} → {effective_distance:.1f}"
                        )

                candidates_with_effective_distance.append(
                    (kw, raw_distance, effective_distance)
                )

            # Sort by (effective_distance, -length): closest first, then longest
            candidates_with_effective_distance.sort(
                key=lambda x: (x[2], -len(x[0].keyword))
            )
        else:
            # Original behavior: sort by length only (longest first)
            # Still need to create tuples with effective distance for consistency
            candidates_with_effective_distance = [
                (kw, dist, float(dist)) for kw, dist in candidates_with_distance
            ]
            candidates_with_effective_distance.sort(key=lambda x: -len(x[0].keyword))

        # Phase 4: Detect and log ambiguous matches (P1 enhancement, B1 fix)
        # B1 Fix: Use EFFECTIVE distance for ambiguity detection, not raw distance
        if self.log_ambiguous_matches and len(candidates_with_effective_distance) > 1:
            min_effective_distance = candidates_with_effective_distance[0][2]
            ambiguous_keywords = [
                kw.keyword
                for kw, raw_dist, eff_dist in candidates_with_effective_distance
                if abs(eff_dist - min_effective_distance) <= self.ambiguity_threshold
            ]

            if len(ambiguous_keywords) > 1:
                logger.info(
                    f"Ambiguous match: {len(ambiguous_keywords)} keywords equally close "
                    f"(effective distance) to number '{number.raw_text}' "
                    f"at ~{min_effective_distance:.1f} chars: "
                    f"{', '.join(repr(k) for k in ambiguous_keywords[:5])}"
                )

        # Phase 5: Filter substring duplicates, deduplicate by metric, and add direction (L3)
        # Cross-metric substring suppression: when keywords from different metrics
        # overlap positionally AND one is a substring of the other, keep the longer match.
        matches: list[KeywordMatch] = []
        seen_metrics: set[str] = set()

        for kw, _raw_dist, _eff_dist in candidates_with_effective_distance:
            # Skip if we already have a match for this metric
            if kw.metric_id in seen_metrics:
                continue

            # Check if this keyword overlaps with any already-accepted keyword
            # and one is a substring of the other (cross-metric deduplication)
            is_substring_duplicate = False
            replace_index: int | None = None

            for i, accepted in enumerate(matches):
                if self._keywords_overlap(kw, accepted) and self._is_substring_match(
                    kw, accepted
                ):
                    # Overlapping substring match found - compare lengths
                    if len(kw.keyword) > len(accepted.keyword):
                        # New keyword is longer (more specific) - replace accepted
                        # Log at INFO for monitoring cross-metric suppression in production
                        logger.info(
                            f"CMS-1 cross-metric replacement: '{accepted.keyword}' "
                            f"({accepted.metric_id}) replaced by longer "
                            f"'{kw.keyword}' ({kw.metric_id})"
                        )
                        replace_index = i
                        # Remove old metric from seen so we can add new one
                        seen_metrics.discard(accepted.metric_id)
                    else:
                        # Accepted keyword is longer or equal - skip new one
                        # Log at INFO for monitoring cross-metric suppression in production
                        logger.info(
                            f"CMS-1 cross-metric suppression: '{kw.keyword}' "
                            f"({kw.metric_id}) suppressed by longer '{accepted.keyword}' "
                            f"({accepted.metric_id})"
                        )
                        is_substring_duplicate = True
                    break

            if not is_substring_duplicate:
                # L3: Compute direction relative to number
                direction = self.calculate_keyword_direction(kw.start, number.start)

                # Create new KeywordMatch with direction set
                match_with_direction = KeywordMatch(
                    start=kw.start,
                    end=kw.end,
                    keyword=kw.keyword,
                    metric_id=kw.metric_id,
                    pattern=kw.pattern,
                    direction=direction,
                )

                if replace_index is not None:
                    # Replace shorter keyword with longer one (cross-metric)
                    matches[replace_index] = match_with_direction
                else:
                    matches.append(match_with_direction)
                seen_metrics.add(kw.metric_id)

        return matches

    def _keywords_overlap(self, kw1: KeywordMatch, kw2: KeywordMatch) -> bool:
        """
        Check if two keyword matches overlap in position.

        Args:
            kw1: First keyword match
            kw2: Second keyword match

        Returns:
            True if keywords overlap, False otherwise
        """
        return not (kw1.end <= kw2.start or kw2.end <= kw1.start)

    def _is_substring_match(self, kw1: KeywordMatch, kw2: KeywordMatch) -> bool:
        """
        Check if kw1's keyword is a substring of kw2's keyword.

        Args:
            kw1: First keyword match
            kw2: Second keyword match

        Returns:
            True if kw1.keyword is a substring of kw2.keyword (case-insensitive)
        """
        kw1_lower = kw1.keyword.lower()
        kw2_lower = kw2.keyword.lower()
        return kw1_lower in kw2_lower or kw2_lower in kw1_lower

    def calculate_distance(self, number: NumberMatch, keyword: KeywordMatch) -> int:
        """
        Calculate character distance between number and keyword.

        Args:
            number: NumberMatch
            keyword: KeywordMatch

        Returns:
            Minimum distance in characters
        """
        return self.calculate_distance_from_positions(
            number.start, number.end, keyword.start, keyword.end
        )

    def calculate_distance_from_positions(
        self, n_start: int, n_end: int, k_start: int, k_end: int
    ) -> int:
        """
        Calculate distance between two spans.

        If spans overlap, distance is 0.
        Otherwise, distance is the gap between them.

        Args:
            n_start: Number start position
            n_end: Number end position
            k_start: Keyword start position
            k_end: Keyword end position

        Returns:
            Distance in characters
        """
        if n_end <= k_start:
            # Number is before keyword
            return k_start - n_end
        elif k_end <= n_start:
            # Keyword is before number
            return n_start - k_end
        else:
            # Overlapping
            return 0

    def calculate_keyword_direction(
        self, keyword_start: int, number_start: int
    ) -> str:
        """
        Calculate whether keyword appears before or after the number.

        Args:
            keyword_start: Keyword start position
            number_start: Number start position

        Returns:
            'before' if keyword appears before number,
            'after' if keyword appears after number,
            'at' if they start at the same position (edge case)
        """
        if keyword_start < number_start:
            return "before"
        elif keyword_start > number_start:
            return "after"
        else:
            return "at"

    def get_context_type(
        self,
        text: str,
        number_position: int,
        keyword_position: int,
        keyword_direction: str,
        boundaries: list["TextBoundary"] | None = None,
        segment_type: str | None = None,
    ) -> str:
        """
        Determine which context type applies to this keyword-number pair.

        This is used for E1 multiplier optimization to track which context
        triggered the multiplier selection.

        Args:
            text: Full text containing both keyword and number
            number_position: Character position of the number
            keyword_position: Character position of the keyword
            keyword_direction: 'before' or 'after' (from calculate_keyword_direction)
            boundaries: Optional list of TextBoundary objects
            segment_type: Optional segment type ('table', 'paragraph', etc.)

        Returns:
            Context type: 'table', 'parenthetical', 'bullet', 'copula', 'preposition', or 'default'
        """
        # For pre-value keywords, context doesn't affect multiplier (always 1.0)
        # But still track context for analysis

        # Priority 1: Table context (strongest signal)
        if segment_type == "table" or self._is_in_table(number_position, boundaries):
            return 'table'

        # Priority 2: Parenthetical text (strong signal for clarifications)
        if self._is_in_parentheses(number_position, text):
            return 'parenthetical'

        # Priority 3: Bullet points (strong signal for structured lists)
        if self._is_in_bullet_point(number_position, boundaries):
            return 'bullet'

        # Priority 4: Copula verb pattern (moderate signal)
        if self._has_copula_verb_between(
            text, min(keyword_position, number_position), max(keyword_position, number_position)
        ):
            return 'copula'

        # Priority 5: Prepositional phrase (moderate signal)
        if keyword_direction == "after" and self._has_preposition_after(text, number_position, keyword_position):
            return 'preposition'

        # Default: no special context
        return 'default'

    def get_context_multiplier(
        self,
        text: str,
        number_position: int,
        keyword_position: int,
        keyword_direction: str,
        boundaries: list["TextBoundary"] | None = None,
        segment_type: str | None = None,
    ) -> float:
        """
        Determine the appropriate multiplier based on textual context.

        This implements L4 Option C: context-dependent multipliers for post-value keywords.
        Different contexts have different patterns for where metrics appear relative to values.

        Args:
            text: Full text containing both keyword and number
            number_position: Character position of the number
            keyword_position: Character position of the keyword
            keyword_direction: 'before' or 'after' (from calculate_keyword_direction)
            boundaries: Optional list of TextBoundary objects
            segment_type: Optional segment type ('table', 'paragraph', etc.)

        Returns:
            Multiplier to apply to the effective distance (only for 'after' direction)
            - < 1.0: Penalize post-value keywords (prefer pre-value)
            - 1.0: No preference
            - > 1.0: Boost post-value keywords (prefer post-value)
        """
        # If context-dependent multipliers disabled, use base multiplier
        if not self.use_context_dependent_multipliers:
            return self.post_value_distance_multiplier

        # Only apply multiplier for post-value keywords
        if keyword_direction != "after":
            return 1.0  # No adjustment for pre-value keywords

        # Get context type and map to multiplier
        context_type = self.get_context_type(
            text, number_position, keyword_position, keyword_direction, boundaries, segment_type
        )

        # Map context type to multiplier
        context_multipliers = {
            'table': self.multiplier_tables,
            'parenthetical': self.multiplier_parenthetical,
            'bullet': self.multiplier_bullet_points,
            'copula': self.multiplier_copula_verb,
            'preposition': self.multiplier_preposition,
            'default': self.multiplier_default,
        }

        return context_multipliers.get(context_type, self.multiplier_default)

    def _is_in_parentheses(self, position: int, text: str) -> bool:
        """
        Check if a position is inside parentheses.

        Args:
            position: Character position to check
            text: Full text

        Returns:
            True if position is inside (...), False otherwise
        """
        # Count open parentheses before position
        text_before = text[:position]
        open_count = text_before.count("(") - text_before.count(")")

        # If more open than close, we're inside parentheses
        return open_count > 0

    def _is_in_table(
        self, position: int, boundaries: list["TextBoundary"] | None
    ) -> bool:
        """
        Check if a position is in a table boundary.

        Args:
            position: Character position to check
            boundaries: Optional list of boundaries

        Returns:
            True if position is in a table boundary, False otherwise
        """
        if boundaries is None:
            return False

        boundary = self._get_boundary_at_position(position, boundaries)
        if boundary is None:
            return False

        # Check if boundary type indicates table
        # Note: boundary_type might be "table" or have other indicators
        return getattr(boundary, "boundary_type", None) == "table"

    def _is_in_bullet_point(
        self, position: int, boundaries: list["TextBoundary"] | None
    ) -> bool:
        """
        Check if a position is in a bullet point boundary.

        Args:
            position: Character position to check
            boundaries: Optional list of boundaries

        Returns:
            True if position is in a bullet boundary, False otherwise
        """
        if boundaries is None:
            return False

        boundary = self._get_boundary_at_position(position, boundaries)
        if boundary is None:
            return False

        # Check if boundary type indicates bullet/list
        boundary_type = getattr(boundary, "boundary_type", None)
        return boundary_type in ("bullet", "numbered_list", "lettered_list")

    def _has_copula_verb_between(self, text: str, start: int, end: int) -> bool:
        """
        Check if there's a copula verb (is/was/were/are) between two positions.

        Copula verbs suggest subject-verb structure: "Gross margin was 33%"

        Args:
            text: Full text
            start: Start position
            end: End position

        Returns:
            True if copula verb found between positions, False otherwise
        """
        snippet = text[start:end].lower()
        # Match copula verbs with word boundaries
        copula_pattern = r"\b(is|was|were|are)\b"
        return bool(re.search(copula_pattern, snippet))

    def _has_preposition_after(
        self, text: str, number_position: int, keyword_position: int
    ) -> bool:
        """
        Check if there's a preposition (of/for/in) between number and keyword.

        Prepositions suggest the keyword is the object: "33% of revenue", "33% for margin"

        Args:
            text: Full text
            number_position: Number start position
            keyword_position: Keyword start position (must be after number)

        Returns:
            True if preposition found between number and keyword, False otherwise
        """
        if keyword_position <= number_position:
            return False

        # Check the gap between number and keyword (up to 50 chars)
        gap_start = number_position
        gap_end = min(number_position + 50, keyword_position + 10)
        snippet = text[gap_start:gap_end].lower()

        # Match common prepositions with word boundaries
        preposition_pattern = r"\b(of|for|in|from)\b"
        return bool(re.search(preposition_pattern, snippet))

    def _get_boundary_at_position(
        self, pos: int, boundaries: list["TextBoundary"]
    ) -> Optional["TextBoundary"]:
        """
        Find the boundary containing a position.

        Args:
            pos: Character position
            boundaries: List of TextBoundary objects

        Returns:
            The boundary containing the position, or None if not found
        """
        for boundary in boundaries:
            if boundary.contains_position(pos):
                return boundary
        return None

    def _is_in_same_boundary(
        self, pos: int, target_boundary: "TextBoundary", boundaries: list["TextBoundary"]
    ) -> bool:
        """
        Check if a position is in the same boundary as a target boundary.

        Args:
            pos: Character position to check
            target_boundary: The target boundary
            boundaries: List of all boundaries

        Returns:
            True if position is in the same boundary, False otherwise
        """
        boundary = self._get_boundary_at_position(pos, boundaries)
        return boundary is not None and boundary == target_boundary


---

## File 7: src/extraction/value_extractor.py

"""
Value Extractor - Extract numeric metric values from segments.

This module extracts quantitative metric values from classified segments,
particularly focusing on table data with cohort breakdowns.
"""

import difflib
import html
import logging
import re
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import TYPE_CHECKING, Optional

from bs4 import BeautifulSoup

from ..review.false_positive_filter import FalsePositiveFilter
from ..review.number_parsing import NumberMatch
from ..review.table_structure import TableRowParser
from .models import MetricValue, SourceSegment

if TYPE_CHECKING:
    from ..llm.openai_client import OpenAIClient

logger = logging.getLogger(__name__)

# Quote verification constants
DEFAULT_SIMILARITY_THRESHOLD = 0.7  # Minimum similarity ratio for fuzzy matching
WINDOW_SIZE_MULTIPLIER = 1.3  # Window size = quote length * this multiplier
STRIDE_DIVISOR = 10  # Sample every quote_len / this value positions


# Mapping from LLM-returned metric names to canonical metric IDs
# The LLM returns free-form names; we need to map them to our taxonomy
METRIC_NAME_MAPPING = {
    # Core metrics
    "new_customers_acquired": "cm_new_customers_acquired",
    "new_customers": "cm_new_customers_acquired",
    "customer_acquisition": "cm_new_customers_acquired",
    "customers_acquired": "cm_new_customers_acquired",
    "new_customer_additions": "cm_new_customers_acquired",

    "customers_by_tenure": "cm_customers_period_end_by_tenure",
    "customer_count_by_tenure": "cm_customers_period_end_by_tenure",
    "customer_cohort_count": "cm_customers_period_end_by_tenure",

    "revenue_by_cohort": "cm_revenue_by_cohort",
    "cohort_revenue": "cm_revenue_by_cohort",
    "revenue_by_customer_cohort": "cm_revenue_by_cohort",

    "transactions_by_cohort": "cm_transactions_by_cohort",
    "purchases_by_cohort": "cm_transactions_by_cohort",
    "orders_by_cohort": "cm_transactions_by_cohort",

    # Extended metrics - customer counts
    "active_customers": "cm_active_customers_total",
    "active_customers_total": "cm_active_customers_total",
    "total_active_customers": "cm_active_customers_total",
    "active_users": "cm_active_customers_total",
    "customer_count": "cm_active_customers_total",
    "total_customers": "cm_active_customers_total",

    # Extended metrics - engagement
    "monthly_active_users": "cm_monthly_active_users",
    "mau": "cm_monthly_active_users",
    "monthly_active": "cm_monthly_active_users",

    "daily_active_users": "cm_daily_active_users",
    "dau": "cm_daily_active_users",
    "daily_active": "cm_daily_active_users",

    # Extended metrics - unit economics
    "revenue_per_customer": "cm_revenue_per_customer",
    "arpu": "cm_revenue_per_customer",
    "average_revenue_per_user": "cm_revenue_per_customer",
    "revenue_per_user": "cm_revenue_per_customer",

    "customer_acquisition_cost": "cm_customer_acquisition_cost",
    "cac": "cm_customer_acquisition_cost",
    "acquisition_cost": "cm_customer_acquisition_cost",

    "cac_payback_period": "cm_cac_payback_period",
    "cac_payback": "cm_cac_payback_period",
    "payback_period": "cm_cac_payback_period",

    "customer_lifetime_value": "cm_lifetime_value_per_customer",
    "lifetime_value": "cm_lifetime_value_per_customer",
    "ltv": "cm_lifetime_value_per_customer",
    "clv": "cm_lifetime_value_per_customer",

    "ltv_to_cac_ratio": "cm_ltv_to_cac_ratio",
    "ltv_cac": "cm_ltv_to_cac_ratio",
    "ltv_cac_ratio": "cm_ltv_to_cac_ratio",

    "ltv_to_cac_ratio_by_cohort": "cm_ltv_to_cac_ratio_by_cohort",
    "ltv_cac_by_cohort": "cm_ltv_to_cac_ratio_by_cohort",
    "cohort_ltv_cac": "cm_ltv_to_cac_ratio_by_cohort",

    # Extended metrics - retention
    "customer_retention_rate": "cm_customer_retention_rate",
    "retention_rate": "cm_customer_retention_rate",
    "customer_retention": "cm_customer_retention_rate",

    "customer_churn_rate": "cm_customer_churn_rate",
    "churn_rate": "cm_customer_churn_rate",
    "churn": "cm_customer_churn_rate",
    "attrition_rate": "cm_customer_churn_rate",

    "net_revenue_retention": "cm_net_revenue_retention",
    "nrr": "cm_net_revenue_retention",
    "net_dollar_retention": "cm_net_revenue_retention",
    "net_dollar_retention_rate": "cm_net_revenue_retention",
    "ndr": "cm_net_revenue_retention",
    "revenue_retention": "cm_net_revenue_retention",

    "gross_revenue_retention": "cm_gross_revenue_retention",
    "grr": "cm_gross_revenue_retention",

    # Extended metrics - customer counts specific (period-end stock count)
    "paid_customers": "cm_customers_period_end",
    "total_paid_customers": "cm_customers_period_end",
    "paid_customer_count": "cm_customers_period_end",
    "customers_period_end": "cm_customers_period_end",
    "period_end_customers": "cm_customers_period_end",
    "customer_base": "cm_customers_period_end",
    "total_customer_count": "cm_customers_period_end",
    "customers_at_period_end": "cm_customers_period_end",

    "paid_customers_100k": "cm_large_customers_period_end",
    "paid_customers_100k+": "cm_large_customers_period_end",
    "customers_over_100k": "cm_large_customers_period_end",
    "large_customers": "cm_large_customers_period_end",
    "enterprise_customers": "cm_large_customers_period_end",

    # Extended metrics - recurring revenue
    "arr": "cm_arr",
    "annual_recurring_revenue": "cm_arr",
    "annualized_recurring_revenue": "cm_arr",

    "mrr": "cm_mrr",
    "monthly_recurring_revenue": "cm_mrr",

    # Extended metrics - transactions
    "purchase_transactions": "cm_purchase_transactions_overall",
    "total_transactions": "cm_purchase_transactions_overall",
    "transaction_count": "cm_purchase_transactions_overall",
    "order_count": "cm_purchase_transactions_overall",
    "total_orders": "cm_purchase_transactions_overall",

    # Extended metrics - cohort economics
    "gross_margin_by_cohort": "cm_gross_margin_by_cohort",
    "cohort_gross_margin": "cm_gross_margin_by_cohort",
    "cohort_margin": "cm_gross_margin_by_cohort",

    # Extended metrics - expansion and concentration
    "expansion_revenue": "cm_expansion_revenue",
    "upsell_revenue": "cm_expansion_revenue",
    "cross_sell_revenue": "cm_expansion_revenue",

    "revenue_concentration": "cm_revenue_concentration",
    "customer_concentration": "cm_revenue_concentration",
    "top_customers": "cm_revenue_concentration",

    # Extended metrics - e-commerce
    "average_order_value": "cm_average_order_value",
    "aov": "cm_average_order_value",
    "avg_order_value": "cm_average_order_value",

    "repeat_purchase_rate": "cm_repeat_purchase_rate",
    "repeat_purchases": "cm_repeat_purchase_rate",
    "purchase_frequency": "cm_repeat_purchase_rate",
}

# Create reverse mapping for validation
VALID_METRIC_IDS = set(METRIC_NAME_MAPPING.values())


def map_llm_name_to_metric_id(
    llm_name: str,
    candidate_metric_ids: list[str] | None = None
) -> str | None:
    """
    Map an LLM-returned metric name to a canonical metric ID.

    Args:
        llm_name: The metric name returned by the LLM (e.g., "monthly_active_users")
        candidate_metric_ids: Optional list of candidate metric IDs to prefer

    Returns:
        Canonical metric ID (e.g., "cm_monthly_active_users") or None if no match
    """
    if not llm_name:
        return None

    # Normalize the LLM name: lowercase, replace spaces with underscores
    normalized = llm_name.lower().strip().replace(" ", "_").replace("-", "_")

    # 1. Check if it's already a valid metric ID
    if normalized in VALID_METRIC_IDS:
        return normalized

    # 2. Check if it's a valid metric ID with cm_ prefix
    if normalized.startswith("cm_") and normalized in VALID_METRIC_IDS:
        return normalized

    # 3. Try adding cm_ prefix
    with_prefix = f"cm_{normalized}"
    if with_prefix in VALID_METRIC_IDS:
        return with_prefix

    # 4. Check the mapping table
    if normalized in METRIC_NAME_MAPPING:
        mapped_id = METRIC_NAME_MAPPING[normalized]
        # If we have candidates, prefer the mapped ID if it's in candidates
        if candidate_metric_ids and mapped_id in candidate_metric_ids:
            return mapped_id
        return mapped_id

    # 5. Try partial matching with candidates
    if candidate_metric_ids:
        for candidate in candidate_metric_ids:
            # Check if the LLM name is a substring of the candidate (after removing cm_)
            candidate_base = candidate.replace("cm_", "")
            if normalized in candidate_base or candidate_base in normalized:
                return candidate

    # 6. No match found
    logger.debug(f"No metric ID mapping found for LLM name: {llm_name}")
    return None


def _normalize_text(text: str | None) -> str:
    """
    Normalize text for comparison.

    - Decode HTML entities (&amp; -> &, &nbsp; -> space, etc.)
    - Normalize whitespace (collapse multiple spaces, strip)
    - Normalize quote characters (" " -> ")
    """
    if not text:
        return ""

    # Decode HTML entities
    normalized = html.unescape(text)

    # Normalize quote characters (curly to straight)
    normalized = normalized.replace("\u201c", '"').replace("\u201d", '"')  # " and "
    normalized = normalized.replace("\u2018", "'").replace("\u2019", "'")  # ' and '

    # Aggressive normalization:
    # Keep alphanumerics (a-z, 0-9)
    # Keep critical context cues: . % $ € £
    # Replace everything else with space
    # This ensures "Net-Dollar Retention" matches "Net Dollar Retention"
    # while keeping "1.5" distinct from "15"
    normalized = re.sub(r'[^a-zA-Z0-9\.\%\$\€\£\s]', ' ', normalized)

    # Normalize whitespace (including newlines)
    normalized = " ".join(normalized.split())

    return normalized


def verify_quote_in_source(
    quote: str,
    source_text: str,
    threshold: float = DEFAULT_SIMILARITY_THRESHOLD,
) -> bool:
    """
    Verify that an LLM-extracted quote exists in the source text.

    Uses a sliding window approach with difflib.SequenceMatcher to find
    the best matching substring in the source and checks if similarity
    meets the threshold.

    Args:
        quote: The quote extracted by the LLM
        source_text: The original source text to verify against
        threshold: Minimum similarity ratio (default 0.8 = 80%)

    Returns:
        True if quote is verified, False otherwise
    """
    if not quote or not source_text:
        return False

    # Normalize both texts
    quote_normalized = _normalize_text(quote)
    source_normalized = _normalize_text(source_text)

    if not quote_normalized or not source_normalized:
        return False

    # Fast path: exact substring match
    if quote_normalized.lower() in source_normalized.lower():
        return True

    # Fuzzy matching: find best matching window in source
    # Use a window slightly larger than the quote to allow for minor differences
    quote_len = len(quote_normalized)
    window_size = int(quote_len * WINDOW_SIZE_MULTIPLIER)

    best_ratio = 0.0
    source_lower = source_normalized.lower()
    quote_lower = quote_normalized.lower()

    # Use stride to reduce iterations for large documents (O(n/stride) instead of O(n))
    stride = max(1, quote_len // STRIDE_DIVISOR)

    # Slide window across source to find best match
    for i in range(0, max(1, len(source_lower) - quote_len + 1), stride):
        window = source_lower[i : i + window_size]
        matcher = difflib.SequenceMatcher(None, quote_lower, window, autojunk=False)
        ratio = matcher.ratio()
        if ratio > best_ratio:
            best_ratio = ratio
            if best_ratio >= threshold:
                return True  # Early exit on good match

    return best_ratio >= threshold


class ValueExtractor:
    """
    Extract metric values from source segments.

    Focuses on:
    1. Table extraction (most reliable for cohort breakdowns)
    2. Text extraction (fallback for simple disclosures)
    3. Period parsing (fiscal quarters, years)
    4. Cohort label normalization
    """

    # Number patterns
    NUMBER_PATTERN = (
        r"[-]?\$?\s*(\d{1,3}(?:,\d{3})*(?:\.\d+)?)\s*(?:million|billion|thousand|%)?"
    )

    # Period patterns
    QUARTER_PATTERN = r"[qQ]([1-4])\s+(\d{4})"
    YEAR_PATTERN = r"(?:FY|fy)?\s*(\d{4})"

    # Cohort patterns
    ACQUISITION_COHORT_PATTERN = r"(\d{4})\s+[Cc]ohort"
    TENURE_COHORT_PATTERNS = [
        (r"(\d+)\s*-\s*(\d+)\s+(?:months?|mos?)", "months"),
        (r"(\d+)\s*-\s*(\d+)\s+years?", "years"),
        (r"(\d+)\+\s+years?", "years_plus"),
        (r"<\s*(\d+)\s+(?:months?|years?)", "less_than"),
    ]

    def __init__(self, llm_client: Optional["OpenAIClient"] = None):
        """
        Initialize the value extractor.

        Args:
            llm_client: Optional OpenAI client for LLM-enhanced extraction.
                       If provided, LLM extraction will be tried first before
                       falling back to rule-based extraction.
        """
        self._number_regex = re.compile(self.NUMBER_PATTERN, re.IGNORECASE)
        self._quarter_regex = re.compile(self.QUARTER_PATTERN)
        self._year_regex = re.compile(self.YEAR_PATTERN)
        self._acquisition_cohort_regex = re.compile(self.ACQUISITION_COHORT_PATTERN)
        self.llm_client = llm_client

        # Initialize false positive filter (EI-3: prevent extracting page numbers, years, dates)
        try:
            self._fp_filter = FalsePositiveFilter()
            logger.debug("False positive filter initialized successfully")
        except Exception as e:
            logger.warning(f"Failed to initialize false positive filter: {e}. Extraction will continue without filtering.")
            self._fp_filter = None

    def _is_false_positive_value(
        self,
        value_str: str,
        position: int | None,
        context_text: str,
        unit: str | None = None
    ) -> tuple[bool, str | None]:
        """
        Check if an extracted value is a false positive.

        Args:
            value_str: The raw value string (e.g., "2019", "45")
            position: Character position in context_text (None if unknown)
            context_text: The full text containing the value
            unit: Optional unit type ('count', 'currency', 'percentage')

        Returns:
            Tuple of (is_false_positive, reason_string)
        """
        # If filter not available, don't filter (fail open)
        if self._fp_filter is None:
            return False, None

        # If position not available, try to find it in context
        if position is None:
            try:
                position = context_text.find(value_str)
                if position == -1:
                    logger.debug(f"Could not find value '{value_str}' in context for false positive check")
                    return False, None  # Can't filter without position
            except Exception as e:
                logger.debug(f"Error finding position for value '{value_str}': {e}")
                return False, None

        # Create NumberMatch for the filter
        try:
            # Parse the numeric value to get a Decimal
            parsed_value = self._parse_number(value_str)

            # Determine unit if not provided
            if unit is None:
                if "$" in value_str or "usd" in value_str.lower():
                    unit = "currency"
                elif "%" in value_str or "percent" in value_str.lower():
                    unit = "percentage"
                else:
                    unit = "count"

            # Create NumberMatch
            number_match = NumberMatch(
                start=position,
                end=position + len(value_str),
                raw_text=value_str,
                value=parsed_value,
                unit=unit
            )

            # Check if it's a false positive
            is_fp, reason = self._fp_filter.is_false_positive(context_text, number_match)

            if is_fp:
                logger.debug(
                    f"False positive detected: value='{value_str}' reason={reason} "
                    f"context={context_text[max(0, position-30):min(len(context_text), position+30)]!r}"
                )

            return is_fp, reason

        except Exception as e:
            logger.warning(
                f"Error checking false positive for value '{value_str}': {e}. "
                "Proceeding without filtering."
            )
            return False, None  # Don't block extraction on filter errors

    def extract_from_segment(
        self, segment: SourceSegment, company_id: int
    ) -> list[MetricValue]:
        """
        Extract all metric values from a segment.

        Uses hybrid extraction strategy:
        1. Try LLM extraction if LLM client is available
        2. Fall back to rule-based extraction if LLM fails or not available

        Args:
            segment: Classified source segment
            company_id: Company ID for the filing

        Returns:
            List of MetricValue objects (may be multiple per segment)
        """
        # Only extract from segments with numeric disclosure flag
        if not segment.contains_numeric_disclosure_flag:
            return []

        # Try LLM extraction first if available
        if self.llm_client:
            try:
                logger.info(
                    f"Attempting LLM extraction for segment {segment.source_segment_id or segment.sequence_index}"
                )
                if segment.segment_type == "table":
                    values = self.extract_from_table_with_llm(segment, company_id)
                else:
                    values = self.extract_from_text_with_llm(segment, company_id)

                if values:  # LLM extraction succeeded
                    logger.info(
                        f"LLM extraction succeeded: {len(values)} values extracted"
                    )
                    return values
                else:
                    logger.info(
                        "LLM extraction returned no values, falling back to rules"
                    )

            except Exception as e:
                logger.warning(
                    f"LLM extraction failed for segment {segment.source_segment_id or segment.sequence_index}: {e}"
                )
                logger.info("Falling back to rule-based extraction")

        # Fall back to rule-based extraction
        logger.debug("Using rule-based extraction")
        if segment.segment_type == "table":
            return self.extract_from_table(segment, company_id)
        else:
            return self.extract_from_text(segment, company_id)

    def extract_from_table(
        self, segment: SourceSegment, company_id: int
    ) -> list[MetricValue]:
        """
        Extract structured data from table segments.

        Args:
            segment: Table segment
            company_id: Company ID

        Returns:
            List of MetricValue objects extracted from the table
        """
        if not segment.raw_html:
            logger.warning(f"No raw HTML for table segment {segment.source_segment_id}")
            return []

        # Parse table with BeautifulSoup
        soup = BeautifulSoup(segment.raw_html, "html.parser")
        table = soup.find("table")
        if not table:
            logger.warning(f"No table found in segment {segment.source_segment_id}")
            return []

        # Extract table structure
        rows = table.find_all("tr")
        if len(rows) < 2:  # Need at least header + 1 data row
            return []

        # EI-4: Create TableRowParser for row boundary validation
        row_parser: TableRowParser | None = None
        if segment.raw_html and segment.raw_text:
            try:
                row_parser = TableRowParser(segment.raw_html, segment.raw_text)
                logger.debug(f"TableRowParser created for segment {segment.source_segment_id}")
            except Exception as e:
                logger.warning(
                    f"Failed to create TableRowParser for segment {segment.source_segment_id}: {e}. "
                    "Proceeding without row validation."
                )

        # Parse header row to identify columns
        header_row = rows[0]
        headers = [
            self._clean_text(cell.get_text())
            for cell in header_row.find_all(["th", "td"])
        ]

        # Identify column types
        column_info = self._identify_columns(headers)

        # Parse data rows
        values = []
        for row in rows[1:]:
            cells = row.find_all(["td", "th"])
            if len(cells) != len(headers):
                continue  # Skip malformed rows

            row_values = self._parse_table_row(
                cells, headers, column_info, segment, company_id, row_parser
            )
            values.extend(row_values)

        logger.info(
            f"Extracted {len(values)} values from table segment {segment.source_segment_id}"
        )
        return values

    def extract_from_text(
        self, segment: SourceSegment, company_id: int
    ) -> list[MetricValue]:
        """
        Extract values from text segments using pattern matching with smart scoring.

        Args:
            segment: Text segment
            company_id: Company ID

        Returns:
            List of MetricValue objects
        """
        if not segment.raw_text:
            return []

        values = []
        candidate_metrics = segment.candidate_metric_ids or []
        filtered_count = 0

        # Regex patterns for exclusion
        # Matches "January 31, 2019" or "Jan 31 2019"
        # We want to ignore the day (31) and year (2019)
        date_pattern = re.compile(
            r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+(\d{1,2})(?:st|nd|rd|th)?(?:,)?\s+(\d{4})",
            re.IGNORECASE
        )

        # Matches standalone page numbers/TOC entries at start of line
        # e.g., "73 Table of Contents"
        toc_pattern = re.compile(r"^\s*(\d+)\s+(?:Table of Contents|Page)", re.IGNORECASE)

        # Helper to check if a match range overlaps with an exclusion range
        def is_excluded(start: int, end: int, exclusions: list[tuple[int, int]]) -> bool:
            for ex_start, ex_end in exclusions:
                # If overlap
                if start < ex_end and end > ex_start:
                    return True
            return False

        # Scoring function for candidates
        def score_candidate(val_str: str, full_match_str: str, context: str) -> float:
            score = 0.0

            # 1. Currency boost (High)
            if "$" in full_match_str or "USD" in full_match_str.upper():
                score += 5.0
            elif "€" in full_match_str or "£" in full_match_str:
                score += 5.0

            # 2. Magnitude boost (High)
            if "million" in full_match_str.lower():
                score += 4.0
            elif "billion" in full_match_str.lower():
                score += 4.0
            elif "thousand" in full_match_str.lower():
                score += 2.0

            # 3. Percentage boost (Medium - if relevant)
            if "%" in full_match_str:
                score += 3.0

            # 4. Precision boost (Small)
            if "." in val_str:
                score += 1.0

            # 5. Penalties
            # Penalty for "Day of month" lookalikes (1-31 integers)
            if re.match(r"^[1-3][0-9]$|^[1-9]$", val_str):
                score -= 2.0

            # Penalty for "Year" lookalikes (1990-2030) without currency
            if re.match(r"^(?:19|20)\d{2}$", val_str) and "$" not in full_match_str:
                score -= 3.0

            return score

        # Split text into sentences
        sentences = re.split(r'[.\n]+', segment.raw_text)

        # Import metric classifier to access patterns
        from .metric_classifier import MetricClassifier
        classifier = MetricClassifier()

        for sentence in sentences:
            sentence = sentence.strip()
            if not sentence:
                continue

            # 1. Identify Exclusion Ranges in this sentence
            exclusions = []

            # Find dates
            for m in date_pattern.finditer(sentence):
                # Exclude the day group (group 1) and year group (group 2)
                # Group 1 (Day)
                g1_start, g1_end = m.span(1)
                exclusions.append((g1_start, g1_end))
                # Group 2 (Year)
                g2_start, g2_end = m.span(2)
                exclusions.append((g2_start, g2_end))

            # Find TOC/Page numbers
            for m in toc_pattern.finditer(sentence):
                exclusions.append(m.span(1))

            # 2. Find all potential numbers
            # finditer gives us match objects with positions
            number_matches = list(self._number_regex.finditer(sentence))
            if not number_matches:
                continue

            # 3. Process By Metric
            for metric_id in candidate_metrics:
                # Check keywords exist in sentence
                patterns = classifier._metric_patterns.get(metric_id, [])
                has_keyword = False
                for pattern in patterns:
                    if pattern.search(sentence):
                        has_keyword = True
                        break

                if not has_keyword:
                    continue

                # Collect valid candidates and score them
                candidates = []

                for match in number_matches:
                    val_str = match.group(1) # The numeric part
                    full_str = match.group(0) # The full match including $ million etc.
                    start, end = match.span(1) # Span of the numeric part

                    # Skip if in excluded range (Date/Page)
                    if is_excluded(start, end, exclusions):
                        continue

                    # Skip if false positive (using existing filter)
                    position_in_full_text = segment.raw_text.find(sentence) + sentence.find(val_str)
                    is_fp, reason = self._is_false_positive_value(
                        value_str=val_str,
                        position=position_in_full_text,
                        context_text=segment.raw_text,
                        unit=None
                    )
                    if is_fp:
                        filtered_count += 1
                        continue

                    # Score it
                    score = score_candidate(val_str, full_str, sentence)
                    candidates.append({
                        "val_str": val_str,
                        "numeric_value": self._parse_number(val_str),
                        "unit": self._infer_unit(val_str, metric_id),
                        "score": score,
                        "full_match": full_str
                    })

                if not candidates:
                    continue

                # Pick the best candidate
                # Sort by score descending
                candidates.sort(key=lambda x: x["score"], reverse=True)
                best = candidates[0]

                # If best score is very low/negative, maybe skip?
                # For now, we trust the ranking. If it's a tie, first one wins.

                # Create value
                value = MetricValue(
                    filing_id=segment.filing_id,
                    company_id=company_id,
                    metric_id=metric_id,
                    source_segment_id=segment.sequence_index,
                    source_type="text",
                    extraction_method="rule_text_smart",
                    value_numeric=best["numeric_value"],
                    value_text=best["val_str"],
                    unit=best["unit"],
                    period_end=self._extract_period_from_text(sentence),
                    qa_status="unreviewed",
                )
                values.append(value)

                # Move to next metric (we only extract one value per metric per sentence)

        if filtered_count > 0:
            logger.debug(f"Filtered {filtered_count} false positive(s) from smart text extraction")

        return values

    def extract_from_text_with_llm(
        self, segment: SourceSegment, company_id: int
    ) -> list[MetricValue]:
        """
        Extract values from text segments using LLM.

        Args:
            segment: Text segment
            company_id: Company ID

        Returns:
            List of MetricValue objects
        """
        if not self.llm_client:
            raise ValueError("LLM client not available")

        # Import here to avoid circular imports
        from ..llm.prompts import PromptTemplates

        # Get metric names to look for
        metric_names = ", ".join(segment.candidate_metric_ids or [])
        if not metric_names:
            metric_names = "active_users, customer_count, revenue_retention, churn_rate"

        # Create prompt
        prompt = PromptTemplates.value_extraction_from_text(
            segment_text=segment.raw_text[:8000],  # Limit to 8000 chars
            metric_names=metric_names,
            context_text=segment.context_prefix,
        )

        # Get LLM response
        response = self.llm_client.complete(
            prompt, system_message=PromptTemplates.SYSTEM_VALUE_EXTRACTION
        )

        # Parse response
        try:
            data = PromptTemplates.parse_json_response(response.content)

            if not PromptTemplates.validate_value_extraction_response(data):
                logger.warning("LLM response failed validation")
                return []

            # Convert LLM response to MetricValue objects
            values = []
            filtered_count = 0
            for item in data:
                # Parse the numeric value
                numeric_value = self._parse_number(item["value"])
                if numeric_value is None:
                    continue

                # EI-3: Check if value is a false positive before further processing
                value_str = item["value"]
                position = segment.raw_text.find(value_str) if value_str else None
                is_fp, fp_reason = self._is_false_positive_value(
                    value_str=value_str,
                    position=position,
                    context_text=segment.raw_text,
                    unit=item.get("units")
                )

                if is_fp:
                    logger.debug(
                        f"Skipping false positive in LLM text extraction: "
                        f"value='{value_str}' reason={fp_reason}"
                    )
                    filtered_count += 1
                    continue  # Skip this value

                # Parse period if available
                period_end = None
                if item.get("period"):
                    period_end = self._extract_period_from_text(item["period"])

                # Determine metric_id using the mapping function
                llm_metric_name = item.get("metric_name")
                metric_id = map_llm_name_to_metric_id(
                    llm_metric_name,
                    segment.candidate_metric_ids
                )
                if not metric_id:
                    # Log unmapped metric names for debugging
                    logger.warning(
                        f"Could not map LLM metric name '{llm_metric_name}' to canonical ID. "
                        f"Candidates: {segment.candidate_metric_ids}"
                    )
                    continue  # Skip if we can't determine the metric type

                # Verify quote exists in source text
                quote = item.get("quote")
                qa_status = "unreviewed"

                if quote:
                    if verify_quote_in_source(quote, segment.raw_text):
                        qa_status = "pass"  # Quote verified
                    else:
                        # Log with details for debugging (truncate long quotes)
                        truncated_quote = (
                            quote[:100] + "..." if len(quote) > 100 else quote
                        )
                        logger.warning(
                            f"Quote verification failed for {metric_id}. "
                            f"Rejecting extraction. Quote: '{truncated_quote}'"
                        )
                        continue  # Skip this extraction - reject unverified quotes
                else:
                    # CRITICAL FIX: Reject empty quotes instead of accepting
                    logger.warning(
                        f"LLM returned empty quote for {metric_id} - "
                        "rejecting extraction (quote required for verification)"
                    )
                    continue  # Skip this extraction - require quotes

                # CRITICAL: Validate quote contains metric keyword AND value
                # This prevents extracting unrelated nearby numbers
                from .extraction_validation import (
                    ValidationResult,
                    get_rejection_reason,
                    should_reject_extraction,
                    validate_extraction,
                    validate_quote_contains_metric_keyword,
                )
                quote_keyword_result, reason = validate_quote_contains_metric_keyword(
                    metric_id=metric_id,
                    quote=quote,
                    value=float(numeric_value),
                )
                if quote_keyword_result == ValidationResult.FAIL_KEYWORD:
                    truncated_quote = quote[:100] + "..." if len(quote) > 100 else quote
                    logger.warning(
                        f"Quote-keyword validation failed for {metric_id}={numeric_value}: "
                        f"{reason}. Quote: '{truncated_quote}'"
                    )
                    continue  # Reject - quote doesn't prove metric-value association

                # Run additional post-extraction validation
                validation_issues = validate_extraction(
                    metric_id=metric_id,
                    value=numeric_value,
                    unit=item.get("units"),
                    quote=quote,
                    source_text=segment.raw_text,
                )
                if should_reject_extraction(validation_issues):
                    reason = get_rejection_reason(validation_issues)
                    logger.warning(
                        f"Validation failed for {metric_id}={numeric_value}: {reason}"
                    )
                    continue  # Skip this extraction - validation failed

                value = MetricValue(
                    filing_id=segment.filing_id,
                    company_id=company_id,
                    metric_id=metric_id,
                    source_segment_id=segment.source_segment_id
                    or segment.sequence_index,
                    source_type="text",
                    extraction_method="llm_text",
                    value_numeric=numeric_value,
                    value_text=item["value"],
                    unit=item.get("units"),
                    period_end=period_end,
                    cohort_bucket_raw=item.get("cohort_label"),
                    qa_status=qa_status,
                    qa_notes=quote,
                )
                values.append(value)

            if filtered_count > 0:
                logger.debug(f"Filtered {filtered_count} false positive(s) from LLM text extraction")

            logger.info(f"LLM extracted {len(values)} values from text segment")
            return values

        except Exception as e:
            logger.error(f"Failed to parse LLM response: {e}")
            return []

    def extract_from_table_with_llm(
        self, segment: SourceSegment, company_id: int
    ) -> list[MetricValue]:
        """
        Extract values from table segments using LLM.

        Args:
            segment: Table segment
            company_id: Company ID

        Returns:
            List of MetricValue objects
        """
        if not self.llm_client:
            raise ValueError("LLM client not available")

        if not segment.raw_html:
            logger.warning(f"No raw HTML for table segment {segment.source_segment_id}")
            return []

        # Import here to avoid circular imports
        from ..llm.prompts import PromptTemplates

        # Get metric names to look for
        metric_names = ", ".join(segment.candidate_metric_ids or [])
        if not metric_names:
            metric_names = "revenue_by_cohort, customers_by_tenure, retention_rate"

        # Create prompt with both text and HTML
        table_text = segment.raw_text[:4000]  # Limit text
        table_html = segment.raw_html[:4000]  # Limit HTML

        prompt = PromptTemplates.value_extraction_from_table(
            table_text=table_text,
            table_html=table_html,
            metric_names=metric_names,
            context_text=segment.context_prefix,
        )

        # Get LLM response
        response = self.llm_client.complete(
            prompt, system_message=PromptTemplates.SYSTEM_VALUE_EXTRACTION
        )

        # Parse response
        try:
            data = PromptTemplates.parse_json_response(response.content)

            if not PromptTemplates.validate_value_extraction_response(data):
                logger.warning("LLM response failed validation")
                return []

            # Convert LLM response to MetricValue objects
            values = []
            filtered_count = 0
            for item in data:
                # Parse the numeric value
                numeric_value = self._parse_number(item["value"])
                if numeric_value is None:
                    continue

                # EI-3: Check if value is a false positive before further processing
                value_str = item["value"]
                source_for_filtering = segment.raw_text or table_text
                position = source_for_filtering.find(value_str) if value_str else None
                is_fp, fp_reason = self._is_false_positive_value(
                    value_str=value_str,
                    position=position,
                    context_text=source_for_filtering,
                    unit=item.get("units")
                )

                if is_fp:
                    logger.debug(
                        f"Skipping false positive in LLM table extraction: "
                        f"value='{value_str}' reason={fp_reason}"
                    )
                    filtered_count += 1
                    continue  # Skip this value

                # Parse period if available
                period_end = None
                if item.get("period"):
                    period_end = self._extract_period_from_text(item["period"])

                # Parse cohort if available
                cohort_type = None
                cohort_normalized = None
                cohort_label = item.get("cohort_label") or item.get("row_label")
                if cohort_label:
                    cohort_type, cohort_normalized = self.parse_cohort_label(
                        cohort_label
                    )

                # Determine metric_id using the mapping function
                llm_metric_name = item.get("metric_name")
                metric_id = map_llm_name_to_metric_id(
                    llm_metric_name,
                    segment.candidate_metric_ids
                )
                if not metric_id:
                    # Log unmapped metric names for debugging
                    logger.warning(
                        f"Could not map LLM metric name '{llm_metric_name}' to canonical ID. "
                        f"Candidates: {segment.candidate_metric_ids}"
                    )
                    continue  # Skip if we can't determine the metric type

                # Verify quote exists in source text
                quote = item.get("quote")
                qa_status = "unreviewed"

                if quote:
                    # For tables, check against both raw_text and table_text
                    source_for_verification = segment.raw_text or table_text
                    if verify_quote_in_source(quote, source_for_verification):
                        qa_status = "pass"  # Quote verified
                    else:
                        truncated_quote = (
                            quote[:100] + "..." if len(quote) > 100 else quote
                        )
                        logger.warning(
                            f"Quote verification failed for table extraction: {metric_id}. "
                            f"Rejecting extraction. Quote: '{truncated_quote}'"
                        )
                        continue  # Reject unverified
                else:
                    # CRITICAL FIX: Reject empty quotes instead of accepting
                    logger.warning(
                        f"LLM returned empty quote for table extraction: {metric_id} - "
                        "rejecting extraction (quote required for verification)"
                    )
                    continue  # Skip this extraction - require quotes

                # CRITICAL: Validate quote contains metric keyword AND value
                # This prevents extracting unrelated nearby numbers
                from .extraction_validation import (
                    ValidationResult,
                    get_rejection_reason,
                    should_reject_extraction,
                    validate_extraction,
                    validate_quote_contains_metric_keyword,
                )
                quote_keyword_result, reason = validate_quote_contains_metric_keyword(
                    metric_id=metric_id,
                    quote=quote,
                    value=float(numeric_value),
                )
                if quote_keyword_result == ValidationResult.FAIL_KEYWORD:
                    truncated_quote = quote[:100] + "..." if len(quote) > 100 else quote
                    logger.warning(
                        f"Quote-keyword validation failed for table {metric_id}={numeric_value}: "
                        f"{reason}. Quote: '{truncated_quote}'"
                    )
                    continue  # Reject - quote doesn't prove metric-value association

                # Run additional post-extraction validation
                source_for_validation = segment.raw_text or table_text
                validation_issues = validate_extraction(
                    metric_id=metric_id,
                    value=numeric_value,
                    unit=item.get("units"),
                    quote=quote,
                    source_text=source_for_validation,
                )
                if should_reject_extraction(validation_issues):
                    reason = get_rejection_reason(validation_issues)
                    logger.warning(
                        f"Validation failed for table {metric_id}={numeric_value}: {reason}"
                    )
                    continue  # Skip this extraction - validation failed

                value = MetricValue(
                    filing_id=segment.filing_id,
                    company_id=company_id,
                    metric_id=metric_id,
                    source_segment_id=segment.source_segment_id
                    or segment.sequence_index,
                    source_type="table",
                    extraction_method="llm_table",
                    value_numeric=numeric_value,
                    value_text=item["value"],
                    unit=item.get("units"),
                    period_end=period_end,
                    cohort_type=cohort_type,
                    cohort_bucket_raw=cohort_label,
                    cohort_bucket_normalized=cohort_normalized,
                    qa_status=qa_status,
                    qa_notes=quote,
                )
                values.append(value)

            if filtered_count > 0:
                logger.debug(f"Filtered {filtered_count} false positive(s) from LLM table extraction")

            logger.info(f"LLM extracted {len(values)} values from table segment")
            return values

        except Exception as e:
            logger.error(f"Failed to parse LLM response: {e}")
            return []

    def _identify_columns(self, headers: list[str]) -> dict:
        """
        Identify the type of each column based on header text.

        Returns:
            Dictionary mapping column index to column type:
            - 'cohort': Column contains cohort labels
            - 'period': Column contains period labels
            - 'value': Column contains numeric values
        """
        column_info = {}

        for i, header in enumerate(headers):
            header_lower = header.lower()

            # Cohort column indicators
            if any(kw in header_lower for kw in ["cohort", "vintage", "year acquired"]):
                column_info[i] = {"type": "cohort"}

            # Period column indicators (Q1 2024, FY 2023, etc.)
            elif re.search(r"[qQ]\d|FY|20\d{2}", header):
                period_end = self._extract_period_from_text(header)
                column_info[i] = {"type": "value", "period_end": period_end}

            # Default to value column
            else:
                column_info[i] = {"type": "value", "period_end": None}

        return column_info

    def _parse_table_row(
        self,
        cells: list,
        headers: list[str],
        column_info: dict,
        segment: SourceSegment,
        company_id: int,
        row_parser: TableRowParser | None = None,
    ) -> list[MetricValue]:
        """
        Parse a single table row to extract metric values.

        Args:
            cells: List of table cells
            headers: List of header labels
            column_info: Column type information
            segment: Source segment
            company_id: Company ID
            row_parser: Optional TableRowParser for row boundary validation (EI-4)

        Returns:
            List of MetricValue objects from this row
        """
        values = []

        # Extract cohort label from first column if it's a cohort column
        cohort_label = None
        cohort_type = None
        cohort_normalized = None
        cohort_position = None  # EI-4: Track cohort position for row validation

        for i, info in column_info.items():
            if info["type"] == "cohort" and i < len(cells):
                cohort_label = self._clean_text(cells[i].get_text())
                cohort_type, cohort_normalized = self.parse_cohort_label(cohort_label)
                # EI-4: Find position of cohort label for row validation
                if cohort_label and segment.raw_text:
                    cohort_position = segment.raw_text.find(cohort_label)
                break

        # Extract values from value columns
        filtered_count = 0
        row_boundary_filtered_count = 0  # EI-4: Track cross-row rejections
        for i, info in column_info.items():
            if info["type"] != "value" or i >= len(cells):
                continue

            cell_text = self._clean_text(cells[i].get_text())
            numeric_value = self._parse_number(cell_text)

            if numeric_value is None:
                continue  # Skip non-numeric cells

            # EI-3: Check if value is a false positive before creating MetricValue
            # Use segment.raw_text as context for table filtering
            position = segment.raw_text.find(cell_text) if cell_text and segment.raw_text else None
            is_fp, reason = self._is_false_positive_value(
                value_str=cell_text,
                position=position,
                context_text=segment.raw_text or "",
                unit=None  # Will be inferred
            )

            if is_fp:
                logger.debug(
                    f"Skipping false positive in table extraction: "
                    f"value='{cell_text}' reason={reason}"
                )
                filtered_count += 1
                continue  # Skip this value

            # EI-4: Validate row boundary - check if cohort/label and value are in same row
            if row_parser is not None and cohort_position is not None and cohort_position != -1:
                value_position = position  # Already calculated above
                if value_position is not None and value_position != -1:
                    try:
                        if not row_parser.are_in_same_row(cohort_position, value_position):
                            logger.debug(
                                f"Cross-row match rejected: cohort='{cohort_label}' at pos {cohort_position}, "
                                f"value='{cell_text}' at pos {value_position}"
                            )
                            row_boundary_filtered_count += 1
                            continue  # Skip this value - cross-row match
                    except Exception as e:
                        # Fallback: if row validation fails, proceed with extraction
                        logger.debug(
                            f"Row boundary validation failed for value '{cell_text}': {e}. "
                            "Proceeding with extraction."
                        )

            # Determine which metric this value belongs to
            # STRICT: Check row label for metric keywords
            row_metric_id = None

            # Find the row label (first text cell usually)
            row_label_text = ""
            for cell in cells:
                txt = self._clean_text(cell.get_text())
                # Skip if it looks like a number
                if self._parse_number(txt) is None and txt:
                    row_label_text = txt
                    break

            # Check if row label matches any candidate metric
            if segment.candidate_metric_ids:
                from .metric_classifier import MetricClassifier
                classifier = MetricClassifier()
                for cid in segment.candidate_metric_ids:
                    patterns = classifier._metric_patterns.get(cid, [])
                    for pattern in patterns:
                        if pattern.search(row_label_text):
                            row_metric_id = cid
                            break
                    if row_metric_id:
                        break

            # Also check if column header implies metric (e.g. "Revenue")
            col_metric_id = self._infer_metric_from_context(segment, headers, i)

            # Combine: Row label match takes precedence, then Column header match
            metric_id = row_metric_id or col_metric_id

            if not metric_id:
                continue

            # Create MetricValue
            value = MetricValue(
                filing_id=segment.filing_id,
                company_id=company_id,
                metric_id=metric_id,
                source_segment_id=segment.source_segment_id or 0,
                source_type="table",
                extraction_method="rule_table",
                value_numeric=numeric_value,
                value_text=cell_text,
                unit=self._infer_unit(cell_text, metric_id),
                period_end=info.get("period_end"),
                cohort_type=cohort_type,
                cohort_bucket_raw=cohort_label,
                cohort_bucket_normalized=cohort_normalized,
                qa_status="unreviewed",
            )

            values.append(value)

        if filtered_count > 0:
            logger.debug(f"Filtered {filtered_count} false positive(s) from table row")
        if row_boundary_filtered_count > 0:
            logger.debug(f"Filtered {row_boundary_filtered_count} cross-row match(es) from table row")

        return values

    def _infer_metric_from_context(self, segment: SourceSegment, headers: list[str], column_index: int) -> str | None:
        """
        Infer metric ID from column context (header).
        """
        # Strict Row-Only Logic:
        # A value belongs to a metric IF AND ONLY IF:
        # 1. The column header explicity names it (e.g. "Revenue")
        # 2. OR The row label explicitily matches the metric keywords

        # 1. Check Column Header
        if column_index < len(headers):
            header = headers[column_index].lower()

            # Direct header matches
            if "revenue" in header and "cohort" in header:
                return "cm_revenue_by_cohort"
            if "transaction" in header and "cohort" in header:
                return "cm_transactions_by_cohort"
            if "customer" in header and "tenure" in header:
                return "cm_customers_period_end_by_tenure"

            # If the segment has candidates, check if header matches one of them
            if segment.candidate_metric_ids:
                from .metric_classifier import MetricClassifier
                classifier = MetricClassifier()

                for metric_id in segment.candidate_metric_ids:
                    patterns = classifier._metric_patterns.get(metric_id, [])
                    for pattern in patterns:
                         if pattern.search(header):
                             return metric_id

        return None

        # Current fallback (RESTRICTED):
        # We DO NOT fallback to "candidate_metrics[0]" blindly anymore.
        # If we can't find a match in the header, we return None (unless the table is VERY simple).

        return None

    def _infer_unit(self, value_text: str, metric_id: str) -> str | None:
        """Infer the unit from value text and metric type."""
        value_lower = value_text.lower()

        # Currency
        if "$" in value_text or "usd" in value_lower:
            return "usd"

        # Percentage
        if "%" in value_text or "percent" in value_lower:
            return "%"

        # From metric type
        if "revenue" in metric_id or "cost" in metric_id or "value" in metric_id:
            return "usd"

        if "rate" in metric_id:
            return "%"

        # Default to count for customer/user metrics
        if "customer" in metric_id or "user" in metric_id or "transaction" in metric_id:
            return "count"

        return None

    def parse_cohort_label(self, raw_label: str) -> tuple[str | None, str | None]:
        """
        Parse cohort label into type and normalized bucket.

        Args:
            raw_label: Raw cohort label from filing

        Returns:
            (cohort_type, cohort_bucket_normalized)

        Examples:
            "2021 Cohort" -> ("acquisition", "2021")
            "0-12 months" -> ("tenure", "0-1y")
            "2+ years" -> ("tenure", "2y+")
        """
        if not raw_label:
            return None, None

        # Check for acquisition cohort (year-based)
        match = self._acquisition_cohort_regex.search(raw_label)
        if match:
            year = match.group(1)
            return "acquisition", year

        # Check for tenure cohorts
        for pattern, cohort_subtype in self.TENURE_COHORT_PATTERNS:
            match = re.search(pattern, raw_label, re.IGNORECASE)
            if match:
                if cohort_subtype == "months":
                    start, end = match.groups()
                    # Convert to year buckets
                    start_years = int(start) // 12
                    end_years = int(end) // 12
                    return "tenure", f"{start_years}-{end_years}y"

                elif cohort_subtype == "years":
                    start, end = match.groups()
                    return "tenure", f"{start}-{end}y"

                elif cohort_subtype == "years_plus":
                    years = match.group(1)
                    return "tenure", f"{years}y+"

                elif cohort_subtype == "less_than":
                    value = match.group(1)
                    if "month" in raw_label.lower():
                        years = int(value) // 12
                        return "tenure", f"<{years}y"
                    else:
                        return "tenure", f"<{value}y"

        # Could not parse
        return "other", raw_label

    def _parse_number(self, text: str) -> Decimal | None:
        """
        Parse numeric value from text.

        Handles:
        - Comma separators: 1,234,567
        - Currency symbols: $1.2M
        - Negative numbers: -123
        - Scale indicators: million, billion

        Returns:
            Decimal value or None if unparseable
        """
        # Remove currency symbols and whitespace
        cleaned = text.replace("$", "").replace(",", "").strip()

        # Check for scale indicators
        scale = 1
        if "billion" in cleaned.lower():
            scale = 1_000_000_000
            cleaned = re.sub(r"billion", "", cleaned, flags=re.IGNORECASE).strip()
        elif "million" in cleaned.lower():
            scale = 1_000_000
            cleaned = re.sub(r"million", "", cleaned, flags=re.IGNORECASE).strip()
        elif "thousand" in cleaned.lower():
            scale = 1_000
            cleaned = re.sub(r"thousand", "", cleaned, flags=re.IGNORECASE).strip()

        # Remove percentage signs
        cleaned = cleaned.replace("%", "").strip()

        # Try to convert to Decimal
        try:
            value = Decimal(cleaned) * scale
            return value
        except (InvalidOperation, ValueError):
            return None

    def _extract_period_from_text(self, text: str) -> date | None:
        """
        Extract period end date from text.

        Looks for patterns like:
        - Q1 2024 -> 2024-03-31
        - Q4 2023 -> 2023-12-31
        - FY 2023 -> 2023-12-31
        """
        # Try quarter pattern first
        match = self._quarter_regex.search(text)
        if match:
            quarter = int(match.group(1))
            year = int(match.group(2))

            # Map quarter to month
            quarter_end_months = {1: 3, 2: 6, 3: 9, 4: 12}
            month = quarter_end_months.get(quarter, 12)

            # Last day of quarter
            if month in [3, 6, 9]:
                day = 30 if month == 6 or month == 9 else 31
            else:
                day = 31

            try:
                return date(year, month, day)
            except ValueError:
                return None

        # Try year pattern
        match = self._year_regex.search(text)
        if match:
            year = int(match.group(1))
            try:
                return date(year, 12, 31)
            except ValueError:
                return None

        return None

    def _clean_text(self, text: str) -> str:
        """Clean text content."""
        return re.sub(r"\s+", " ", text).strip()


# Convenience function
def extract_values(segment: SourceSegment, company_id: int) -> list[MetricValue]:
    """
    Convenience function to extract values from a segment.

    Args:
        segment: Source segment
        company_id: Company ID

    Returns:
        List of MetricValue objects
    """
    extractor = ValueExtractor()
    return extractor.extract_from_segment(segment, company_id)


---

## File 8: src/review/false_positive_filter.py

"""
False Positive Filter - Identify and filter out false positive number matches.

This module provides functionality to identify numbers that are unlikely to be
metrics, such as dates, years, page numbers, and other reference numbers.

Enhanced with temporal context patterns (2025-12-17) to improve date detection
in SEC filings by recognizing common temporal phrases like "as of", "ended",
"for the period ended", etc.

Extracted from candidate_generator.py as part of P1.3 module splitting
for improved maintainability and testability.

Automatic Usage (via CandidateGenerator):
    >>> from src.review import CandidateGenerator
    >>>
    >>> # False positive filtering enabled by default
    >>> generator = CandidateGenerator()
    >>> candidates = generator.generate_for_filing(
    ...     filing_id=123, company_id=456, segments=segments
    ... )
    >>> # Years (1990-2100), dates, page refs automatically filtered

Direct Usage (advanced):
    >>> from src.review.false_positive_filter import FalsePositiveFilter
    >>> from src.review.number_parsing import NumberMatch
    >>> from decimal import Decimal
    >>>
    >>> # Initialize filter
    >>> fp_filter = FalsePositiveFilter(
    ...     min_metric_value=10,
    ...     filter_years=True,
    ...     year_min=1990,
    ...     year_max=2100,
    ... )
    >>>
    >>> # Check if a number is a false positive
    >>> number = NumberMatch(
    ...     start=10, end=14, raw_text="2023", value=Decimal("2023"), unit="count"
    ... )
    >>> text = "In 2023, we had 50,000 customers"
    >>> is_fp, reason = fp_filter.is_false_positive(number, text)
    >>> print(f"False positive: {is_fp}, Reason: {reason}")

Configuring Filter Behavior:
    >>> from src.review.config import CandidateGenerationConfig
    >>>
    >>> # Adjust filtering thresholds
    >>> config = CandidateGenerationConfig(
    ...     min_metric_value=100,    # Only keep numbers >= 100
    ...     filter_years=False,      # Don't filter year-like numbers
    ...     filter_false_positives=True,  # Keep other FP filtering
    ... )
    >>> generator = CandidateGenerator(config=config)
    >>> candidates = generator.generate_for_filing(
    ...     filing_id=123, company_id=456, segments=segments
    ... )

Disabling False Positive Filtering (high recall):
    >>> from src.review.config import get_high_recall_config
    >>>
    >>> # Disable all false positive filtering
    >>> config = get_high_recall_config()
    >>> generator = CandidateGenerator(config=config)
    >>> candidates = generator.generate_for_filing(
    ...     filing_id=123, company_id=456, segments=segments
    ... )
    >>> # Will include years, dates, page refs, small numbers

Understanding Filter Reasons:
    >>> # Filter returns tuple (is_false_positive: bool, reason: str)
    >>> # Possible reasons:
    >>> # - "likely_year": Number in year range (1990-2100) and 4-digit format
    >>> # - "below_min_value": Number below min_metric_value threshold
    >>> # - "part_of_date": Part of a date (e.g., "31" from "January 31, 2019")
    >>> # - "toc_proximity": Number near "Table of Contents" header
    >>> # - "toc_page_reference": Dot leader pattern (section name ... page number)
    >>> # - "reference_number": Matches FALSE_POSITIVE_CONTEXT_PATTERNS (page/note/section refs, TOC links)
    >>> # - None: Not a false positive
    >>> #
    >>> # Temporal phrases recognized (enhanced 2025-12-17):
    >>> # - "as of January 31, 2019"
    >>> # - "ended January 31, 2019"
    >>> # - "Year Ended January 31, 2019"
    >>> # - "Three Months Ended April 30, 2018"
    >>> # - "beginning January 31, 2019"

See Also:
    - candidate_generator.py: Uses FalsePositiveFilter internally
    - config.py: Configure filtering parameters
    - number_parsing.py: NumberMatch data structure
"""

import logging
import re
from re import Pattern

from src.review.config import DEFAULT_CONFIG, MIN_METRIC_VALUE, YEAR_MAX, YEAR_MIN
from src.review.number_parsing import NumberMatch

logger = logging.getLogger(__name__)


# =============================================================================
# False Positive Detection Patterns
# =============================================================================

# Date patterns - to detect if a number is part of a date
DATE_CONTEXT_PATTERNS: list[Pattern[str]] = [
    # MM/DD/YYYY or DD/MM/YYYY
    re.compile(r"\d{1,2}/\d{1,2}/\d{2,4}"),
    # Month DD, YYYY
    re.compile(
        r"(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|"
        r"Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\.?,?\s+\d{1,2},?\s+\d{4}",
        re.IGNORECASE,
    ),
    # DD Month YYYY
    re.compile(
        r"\d{1,2}\s+(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|"
        r"Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\.?,?\s+\d{4}",
        re.IGNORECASE,
    ),
    # Temporal phrases with dates - "as of January 31, 2019"
    re.compile(
        r"\bas\s+of\s+(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|"
        r"Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\.?,?\s+\d{1,2},?\s+\d{4}",
        re.IGNORECASE,
    ),
    # "ended January 31, 2019"
    re.compile(
        r"\bended\s+(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|"
        r"Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\.?,?\s+\d{1,2},?\s+\d{4}",
        re.IGNORECASE,
    ),
    # "beginning January 31, 2019" or "beginning of period"
    re.compile(
        r"\bbeginning\s+(?:of\s+)?(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|"
        r"Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\.?,?\s+\d{1,2},?\s+\d{4}",
        re.IGNORECASE,
    ),
    # Fiscal year references - "Year Ended January 31, 2019"
    re.compile(
        r"\byear\s+ended\s+(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|"
        r"Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\.?,?\s+\d{1,2},?\s+\d{4}",
        re.IGNORECASE,
    ),
    # Quarter references - "Three Months Ended April 30, 2018"
    re.compile(
        r"\b(?:three|six|nine|twelve)\s+months\s+ended\s+(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|"
        r"Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\.?,?\s+\d{1,2},?\s+\d{4}",
        re.IGNORECASE,
    ),
    # DFP-1: Month DD without year - "January 31," in table headers
    # Matches: "January 31,", "June 30,", "Jul 31", "September 30" (with or without comma)
    # This catches day numbers from fiscal period headers that don't include a year
    re.compile(
        r"(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|"
        r"Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\.?,?\s+\d{1,2}\b",
        re.IGNORECASE,
    ),
]

# Patterns that indicate a number is NOT a metric (contextual false positives)
FALSE_POSITIVE_CONTEXT_PATTERNS: list[Pattern[str]] = [
    # Page references: "page 123", "pages 10-20"
    re.compile(r"\bpages?\s+\d+", re.IGNORECASE),
    # Note references: "Note 5", "Notes 1-3"
    re.compile(r"\bnotes?\s+\d+", re.IGNORECASE),
    # Section references: "Section 5.1"
    re.compile(r"\bsections?\s+\d+", re.IGNORECASE),
    # Item references: "Item 1A"
    re.compile(r"\bitems?\s+\d+", re.IGNORECASE),
    # Version numbers: "Version 2.0", "v2.1"
    re.compile(r"\b(?:version|v)\s*\d+(?:\.\d+)*", re.IGNORECASE),
    # Exhibit references: "Exhibit 10.1"
    re.compile(r"\bexhibits?\s+\d+", re.IGNORECASE),
    # Table references: "Table 1"
    re.compile(r"\btables?\s+\d+", re.IGNORECASE),
    # Figure references: "Figure 3"
    re.compile(r"\bfigures?\s+\d+", re.IGNORECASE),
    # Footnote references: "[1]", "(1)"
    re.compile(r"[\[\(]\d+[\]\)]"),
    # Chapter references: "Chapter 5"
    re.compile(r"\bchapters?\s+\d+", re.IGNORECASE),
    # Part references: "Part II"
    re.compile(r"\bparts?\s+(?:I{1,3}|IV|V|VI{0,3}|\d+)", re.IGNORECASE),
    # Table of Contents references: "73 Table of Contents" (Issue 4 - standalone pattern)
    re.compile(r"\d+\s+(?:table\s+of\s+contents|toc)\b", re.IGNORECASE),
    # Measurement unit patterns (EI-2) - numbers within time units are not metrics
    # Matches: "24-hour", "30-day", "7 days", "12-month", "90-second"
    # These describe measurement timeframes, not actual metric values
    re.compile(r"\b\d+[-\s]?(?:hour|day|week|month|year|period|quarter)s?\b", re.IGNORECASE),
    re.compile(r"\b\d+[-\s]?(?:minute|second)s?\b", re.IGNORECASE),
]

# Label-embedded value pattern (CMS-2)
# Detects numbers that are part of metric label thresholds, not actual values.
# Example: "Paid Customers > $100,000" - the $100,000 is part of the label, not a value.
# Matches patterns like:
#   - "> $100,000" or ">= $50M" (comparison + currency + number)
#   - "< 1000" or "<= 500" (comparison + number without currency)
#   - "≥ $100K" or "≤ $1 million" (unicode operators)
LABEL_EMBEDDED_VALUE_PATTERN: Pattern[str] = re.compile(
    r"(?:>=?|<=?|≥|≤)\s*"  # Comparison operator (>, >=, <, <=, ≥, ≤)
    r"\$?\s*"  # Optional currency symbol
    r"\d[\d,]*"  # Number (with optional commas)
    r"(?:\.\d+)?"  # Optional decimal
    r"(?:\s*(?:thousand|million|billion|mn|bn|[KMB]))?"  # Optional magnitude suffix
    r"\b",
    re.IGNORECASE,
)

# Year range - numbers in this range are likely years, not metrics
# (imported from config.py for centralized configuration)
YEAR_MIN = YEAR_MIN
YEAR_MAX = YEAR_MAX

# Minimum value threshold - very small numbers are rarely metrics
# (imported from config.py for centralized configuration)
MIN_METRIC_VALUE = MIN_METRIC_VALUE  # Filter out single-digit numbers by default

# Table of Contents proximity threshold - distance to look for TOC header
# (L2 enhancement - configurable via CandidateGenerationConfig)
TOC_PROXIMITY_CHARS = 300  # Characters before number to search for TOC header

# Dot leader window - distance to search for dot leader pattern
# (L2 enhancement - configurable via CandidateGenerationConfig)
TOC_DOT_LEADER_WINDOW = 50  # Characters before number to search for dot leaders

# Table of Contents header variations to recognize
# (L2 enhancement - handles multiple TOC formats in real filings)
TOC_HEADERS = [
    "table of contents",
    "contents",
    "index",
    "index to financial statements",
    "index to consolidated financial statements",
]

# Dot leader pattern - indicates page number in table of contents
# Matches patterns like "... 12" or "........ 23" (3+ dots followed by optional whitespace)
# Updated to handle whitespace before number more flexibly
TOC_DOT_LEADER_PATTERN = re.compile(r'\.{3,}\s*$')


# =============================================================================
# HRV-10: Financial Statement Context Detection (2025-12-26)
# =============================================================================

# Financial statement header patterns
FINANCIAL_STATEMENT_HEADERS: list[Pattern[str]] = [
    # Income statement / P&L variations
    re.compile(r'\bconsolidated\s+statements?\s+of\s+(?:operations|income)', re.IGNORECASE),
    re.compile(r'\bincome\s+statements?', re.IGNORECASE),
    re.compile(r'\bstatements?\s+of\s+(?:operations|earnings|income)', re.IGNORECASE),
    re.compile(r'\bconsolidated\s+results?\s+of\s+operations', re.IGNORECASE),

    # Balance sheet variations
    re.compile(r'\bconsolidated\s+balance\s+sheets?', re.IGNORECASE),
    re.compile(r'\bstatements?\s+of\s+financial\s+position', re.IGNORECASE),
    re.compile(r'\bbalance\s+sheet\s+data', re.IGNORECASE),

    # Cash flow statement variations
    re.compile(r'\bconsolidated\s+statements?\s+of\s+cash\s+flows?', re.IGNORECASE),
    re.compile(r'\bstatements?\s+of\s+cash\s+flows?', re.IGNORECASE),

    # Summary financial data tables
    re.compile(r'\bsummary\s+(?:consolidated\s+)?(?:financial|operating)\s+data', re.IGNORECASE),
    re.compile(r'\bselected\s+financial\s+data', re.IGNORECASE),
]

# Financial statement line item keywords that should NOT be treated as customer metrics
FINANCIAL_LINE_ITEM_KEYWORDS: list[str] = [
    # Income statement line items
    'revenue', 'total revenue', 'net revenue', 'revenues',
    'cost of revenue', 'cost of sales', 'cost of goods sold', 'cogs',
    'gross profit', 'gross income',
    'operating expenses', 'operating income', 'operating loss',
    'research and development', 'r&d expenses',
    'sales and marketing', 'general and administrative',
    'net income', 'net loss', 'net earnings',
    'income from operations', 'loss from operations',
    'earnings per share', 'eps', 'diluted eps', 'basic eps',

    # Balance sheet line items
    'total assets', 'current assets', 'non-current assets',
    'cash and cash equivalents', 'cash equivalents', 'marketable securities',
    'accounts receivable', 'inventory', 'prepaid expenses',
    'property and equipment', 'intangible assets', 'goodwill',
    'total liabilities', 'current liabilities', 'long-term liabilities',
    'accounts payable', 'accrued expenses', 'accrued liabilities',
    'deferred revenue', 'unearned revenue',
    'working capital',
    'stockholders equity', 'shareholders equity', 'total equity',

    # Cash flow line items
    'cash flows from operating activities',
    'cash flows from investing activities',
    'cash flows from financing activities',
    'free cash flow', 'operating cash flow',

    # Common financial ratios and changes
    '$ change', '% change', 'percent change',
    'increase', 'decrease',
]

# Proximity threshold for financial statement context (characters)
FINANCIAL_STATEMENT_PROXIMITY_CHARS = 500


# =============================================================================
# Metric Type Validation (HRV Type Validation Enhancement - 2025-12-26)
# =============================================================================

# Metrics that should ONLY be percentages (not raw counts or dollar amounts)
PERCENTAGE_ONLY_METRICS: set[str] = {
    'cm_net_revenue_retention',  # NDR should be 143%, not 143 or $143
    'cm_gross_retention_rate',
    'cm_customer_retention_rate',
    'cm_customer_churn_rate',
    'cm_ltv_cac_ratio',  # Ratio, expect decimal or %
}

# Metrics that should ONLY be dollar amounts (not percentages or plain counts)
DOLLAR_ONLY_METRICS: set[str] = {
    'cm_arr',  # ARR should be $X million, not 40% or 100
    'cm_mrr',  # MRR should be $X million, not 40% or 100
    'cm_tcv',  # Total contract value
    'cm_acv',  # Annual contract value
    'cm_ltv',  # Lifetime value
    'cm_cac',  # Customer acquisition cost
    'cm_arpu',  # Average revenue per user
}

# Metrics that should ONLY be counts (not percentages or dollars)
COUNT_ONLY_METRICS: set[str] = {
    'cm_customer',  # Customer count
    'cm_daily_active_users',  # DAU count
    'cm_weekly_active_users',  # WAU count
    'cm_monthly_active_users',  # MAU count
    'cm_paid_users',
    'cm_subscribers',
    # Customer count metrics (added 2026-01-07 - were missing, causing % false matches)
    'cm_customers_period_end',
    'cm_active_customers_total',
    'cm_large_customers_period_end',
    'cm_new_customers_acquired',
}


def is_spelled_out_number(raw_text: str) -> bool:
    """
    Check if a number text is spelled out rather than numeric.

    Spelled-out numbers (e.g., "six", "twenty-one", "five million") are
    intentionally written and unlikely to be page numbers or false positives.

    Args:
        raw_text: The raw text of the number match

    Returns:
        True if the number contains no digits (is spelled out)

    Examples:
        >>> is_spelled_out_number("six")
        True
        >>> is_spelled_out_number("twenty-one")
        True
        >>> is_spelled_out_number("123")
        False
        >>> is_spelled_out_number("$50,000")
        False
    """
    return not any(c.isdigit() for c in raw_text)


def is_percentage_format(raw_text: str, unit: str) -> bool:
    """Check if a number is in percentage format.

    Also accepts decimal ratios (0.5 to 2.5 range) as valid percentage representations,
    since metrics like NRR are often expressed as decimals (e.g., 1.25 = 125%).
    """
    # Explicit percentage format
    if '%' in raw_text or unit == 'percentage':
        return True

    # Decimal ratio format (common for retention rates like 1.25 = 125%)
    # Accept values in 0.5 to 2.5 range with decimal point
    if '.' in raw_text and unit == 'count':
        try:
            # Remove any non-numeric chars except decimal point
            cleaned = ''.join(c for c in raw_text if c.isdigit() or c == '.')
            val = float(cleaned)
            # Retention rates typically 0.5 (50%) to 2.0 (200%)
            if 0.5 <= val <= 2.5:
                return True
        except (ValueError, TypeError):
            pass

    return False


def should_treat_as_percentage(metric_id: str, raw_text: str, unit: str, context_text: str | None = None) -> bool:
    """
    Context-based percentage detection for retention metrics.

    FIX-A: Handles cases where retention percentages are extracted as plain numbers
    (e.g., "138" instead of "138%"). When a retention metric has retention context,
    treat the value as a percentage even without the % symbol.

    Args:
        metric_id: The metric identifier (e.g., 'cm_net_revenue_retention')
        raw_text: The raw text of the number match
        unit: The parsed unit (e.g., 'count', 'percentage', 'currency')
        context_text: Optional context text around the number

    Returns:
        True if the value should be treated as a percentage

    Examples:
        >>> # Explicit percentage
        >>> should_treat_as_percentage('cm_net_revenue_retention', '138%', 'percentage')
        True

        >>> # Plain number with retention context
        >>> should_treat_as_percentage('cm_net_revenue_retention', '138', 'count', 'net revenue retention of 138')
        True

        >>> # Plain number without retention context
        >>> should_treat_as_percentage('cm_net_revenue_retention', '138', 'count', 'customers of 138')
        False
    """
    # First check explicit percentage format
    if is_percentage_format(raw_text, unit):
        return True

    # FIX-A: Retention metrics with retention context are percentages
    # This handles values like "138" that should be "138%" in retention contexts
    if metric_id in {'cm_net_revenue_retention', 'cm_gross_revenue_retention', 'cm_gross_retention_rate'}:
        if context_text:
            context_lower = context_text.lower()
            # Check for retention-related keywords in context
            retention_keywords = [
                'retention', 'retained', 'churn', 'renewal', 'renewals',
                'net dollar retention', 'ndr', 'net revenue retention', 'nrr',
                'gross retention', 'grr', 'dollar-based net expansion'
            ]
            if any(keyword in context_lower for keyword in retention_keywords):
                return True

    return False


def is_dollar_format(raw_text: str, unit: str) -> bool:
    """Check if a number is in dollar format."""
    return '$' in raw_text or unit in ('currency', 'usd')


def is_count_format(raw_text: str, unit: str) -> bool:
    """Check if a number is a plain count (not percentage or dollar)."""
    return unit == 'count' and '%' not in raw_text and '$' not in raw_text


# =============================================================================
# Helper Functions for Financial Statement Detection (HRV-10)
# =============================================================================


def is_in_financial_statement_context(
    text: str,
    number_position: int,
    proximity_chars: int = FINANCIAL_STATEMENT_PROXIMITY_CHARS
) -> bool:
    """
    Check if a number appears within a financial statement context.

    Financial statements (income statement, balance sheet, cash flow statement)
    contain many numbers that are financial accounting line items, not customer
    metrics. This function detects financial statement headers to identify
    such contexts.

    Recognizes multiple financial statement variations:
    - "Consolidated Statements of Operations"
    - "Income Statement"
    - "Consolidated Balance Sheets"
    - "Statements of Cash Flows"
    - "Summary Financial Data"

    Args:
        text: The full text containing the number
        number_position: Starting position of the number in the text
        proximity_chars: Character distance to search backwards (default: 500)

    Returns:
        True if any financial statement header found within proximity_chars before number

    Examples:
        >>> text = "CONSOLIDATED STATEMENTS OF OPERATIONS\\nRevenue $400,552"
        >>> is_in_financial_statement_context(text, text.find("400,552"))
        True

        >>> text = "We had 400,552 daily active users"
        >>> is_in_financial_statement_context(text, text.find("400,552"))
        False
    """
    # Look backwards from number position
    search_start = max(0, number_position - proximity_chars)
    search_text = text[search_start:number_position]

    # Check for any financial statement header pattern
    return any(pattern.search(search_text) for pattern in FINANCIAL_STATEMENT_HEADERS)


def contains_financial_line_item_keyword(text: str) -> str | None:
    """
    Check if text contains financial statement line item keywords.

    These keywords indicate financial accounting line items (Revenue, Cost of
    Revenue, Total Assets, etc.) which should not be treated as customer metrics,
    even though terms like "revenue" might appear in customer metric keyword lists.

    Args:
        text: Text to search (typically context text around a number)

    Returns:
        The matching keyword if found (lowercase), None otherwise

    Examples:
        >>> contains_financial_line_item_keyword("Revenue [CELL] $400,552")
        'revenue'

        >>> contains_financial_line_item_keyword("Total assets $1,198,956")
        'total assets'

        >>> contains_financial_line_item_keyword("Daily active users: 10 million")
        None
    """
    text_lower = text.lower()

    # Check for line item keywords (longest first to match "total revenue" before "revenue")
    # Sort by length descending
    sorted_keywords = sorted(FINANCIAL_LINE_ITEM_KEYWORDS, key=len, reverse=True)

    for keyword in sorted_keywords:
        if keyword in text_lower:
            return keyword

    return None


# =============================================================================
# Helper Functions for Table of Contents Detection
# =============================================================================


def is_near_table_of_contents(
    text: str,
    number_position: int,
    proximity_chars: int = TOC_PROXIMITY_CHARS
) -> bool:
    """
    Check if a number appears near a "Table of Contents" header.

    Numbers near TOC headers are almost always page numbers, not customer metrics.
    Searches backwards from the number position for TOC indicators.

    Recognizes multiple TOC header variations:
    - "Table of Contents"
    - "Contents"
    - "Index"
    - "Index to Financial Statements"
    - "Index to Consolidated Financial Statements"

    Args:
        text: The full text containing the number
        number_position: Starting position of the number in the text
        proximity_chars: Character distance to search backwards (default: TOC_PROXIMITY_CHARS)

    Returns:
        True if any TOC header found within proximity_chars before number

    Examples:
        >>> text = "TABLE OF CONTENTS\\nRisk Factors ... 12"
        >>> is_near_table_of_contents(text, text.find("12"))
        True

        >>> text = "INDEX\\nBusiness Overview ... 5"
        >>> is_near_table_of_contents(text, text.find("5"))
        True

        >>> text = "We had 12 million customers in the quarter"
        >>> is_near_table_of_contents(text, text.find("12"))
        False
    """
    # Look backwards from number position
    search_start = max(0, number_position - proximity_chars)
    search_text = text[search_start:number_position].lower()

    # Check for any TOC header variation (case-insensitive)
    return any(header in search_text for header in TOC_HEADERS)


def is_toc_page_reference(
    text: str,
    number_position: int,
    window_chars: int = TOC_DOT_LEADER_WINDOW
) -> bool:
    """
    Check if a number is part of a TOC page reference with dot leaders.

    Detects patterns like:
    - "Business Overview.........1"
    - "Risk Factors ... 12"
    - "Item 1A. Risk Factors....23"

    L2-P1.1 Enhancement: Context-aware detection to prevent false positives
    from narrative ellipsis (e.g., "We expect...12 million customers").

    Now requires BOTH dot leaders AND TOC context (either header proximity
    or section heading pattern) to avoid filtering valid metrics.

    Args:
        text: The full text containing the number
        number_position: Starting position of the number in the text
        window_chars: Character distance to search backwards (default: TOC_DOT_LEADER_WINDOW)

    Returns:
        True if dot leader pattern found AND TOC context detected

    Examples:
        >>> text = "Risk Factors.........12"
        >>> is_toc_page_reference(text, text.find("12"))
        True

        >>> text = "We had 12 million customers"
        >>> is_toc_page_reference(text, text.find("12"))
        False

        >>> text = "We expect...12 million customers"  # Narrative ellipsis
        >>> is_toc_page_reference(text, text.find("12"))
        False  # No TOC context, not filtered
    """
    # Look backwards from number position for dot leader pattern
    search_start = max(0, number_position - window_chars)
    preceding_text = text[search_start:number_position]

    # First check: Must have dot leader pattern (3+ dots)
    if not TOC_DOT_LEADER_PATTERN.search(preceding_text):
        return False

    # L2-P1.1: Require TOC context to avoid narrative ellipsis false positives

    # Context check 1: TOC header within 200 chars (tighter than default 300)
    # This catches most genuine TOC entries
    if is_near_table_of_contents(text, number_position, proximity_chars=200):
        return True

    # Context check 2: TOC-like section heading pattern
    # Matches: "Item 1A.", "Part II", "Section 3", "Chapter 5"
    # Look for these patterns anywhere in the preceding text (not just at end)
    section_heading_pattern = re.compile(
        r'(?:Item|Part|Section|Chapter)\s+[IVX0-9]+[A-Z]?\b',
        re.IGNORECASE
    )
    if section_heading_pattern.search(preceding_text):
        return True

    # Has dot leaders but no TOC context - likely narrative ellipsis
    return False


# =============================================================================
# FalsePositiveFilter Class
# =============================================================================


class FalsePositiveFilter:
    """
    Filter for identifying false positive number matches.

    Handles filtering of numbers that are unlikely to be metrics:
    - Numbers below minimum threshold
    - Year values (1990-2100)
    - Numbers that are part of dates
    - Reference numbers (page, note, section, etc.)
    - Numbers near Table of Contents sections (L2 enhancement)
    - TOC page references with dot leaders (L2 enhancement)
    - Numbers near "Table of Contents" links (Issue 4 enhancement)
    """

    def __init__(
        self,
        filter_enabled: bool = DEFAULT_CONFIG.filter_false_positives,
        min_value: float = DEFAULT_CONFIG.min_metric_value,
        filter_years: bool = DEFAULT_CONFIG.filter_years,
        toc_proximity_chars: int = DEFAULT_CONFIG.toc_proximity_chars,
        toc_dot_leader_window: int = DEFAULT_CONFIG.toc_dot_leader_window,
        filter_financial_statements: bool = True,  # HRV-10/HRV-11
        financial_statement_proximity_chars: int = FINANCIAL_STATEMENT_PROXIMITY_CHARS,
    ):
        """
        Initialize the false positive filter.

        Args:
            filter_enabled: Whether to apply filtering (default from config)
            min_value: Minimum value threshold for count units (default from config)
            filter_years: Whether to filter year-like values (default from config)
            toc_proximity_chars: TOC header proximity threshold (default from config, L2)
            toc_dot_leader_window: Dot leader search window (default from config, L2)
            filter_financial_statements: Whether to filter financial statement line items (HRV-10/11)
            financial_statement_proximity_chars: Financial statement header proximity threshold (HRV-10)
        """
        self.filter_enabled = filter_enabled
        self.min_value = min_value
        self.filter_years = filter_years
        self.toc_proximity_chars = toc_proximity_chars
        self.toc_dot_leader_window = toc_dot_leader_window
        self.filter_financial_statements = filter_financial_statements
        self.financial_statement_proximity_chars = financial_statement_proximity_chars

    def is_false_positive(
        self, text: str, number: NumberMatch
    ) -> tuple[bool, str | None]:
        """
        Check if a number match is likely a false positive.

        Filters out:
        - Numbers that are part of dates (12/31/2023)
        - Numbers that look like years (1990-2100)
        - Numbers near "Table of Contents" headers
        - TOC page references with dot leaders (e.g., "Risk Factors...12")
        - Page/note/section/exhibit references
        - Version numbers
        - Numbers below minimum threshold

        Args:
            text: The full text containing the number
            number: The NumberMatch to check

        Returns:
            Tuple of (is_false_positive, reason)
            reason is None if not a false positive
        """
        if not self.filter_enabled:
            return False, None

        value = number.value
        start = number.start
        end = number.end

        # Check minimum value threshold (skip for percentages, currency, decimals, and spelled-out)
        # Decimals like 1.25 could be ratios (e.g., NRR of 125%)
        # Spelled-out numbers like "six" are intentionally written - likely meaningful
        if number.unit == "count" and value is not None:
            is_decimal = "." in number.raw_text
            if not is_decimal and not is_spelled_out_number(number.raw_text) and abs(float(value)) < self.min_value:
                return True, "below_min_value"

        # Check if number looks like a year (only for plain integers)
        if self.filter_years and number.unit == "count":
            if value is not None and YEAR_MIN <= float(value) <= YEAR_MAX:
                # Additional check: is it a 4-digit integer without decimal?
                if "." not in number.raw_text and len(number.raw_text.replace(",", "")) == 4:
                    return True, "likely_year"

        # Check if number appears near "Table of Contents" header
        # Only filter if it looks like a page number (small integer, no currency/decimals)
        # Real metrics (e.g. "31.0 million") often appear on pages with TOC headers
        # Spelled-out numbers (e.g., "six", "twenty") are unlikely to be page numbers
        is_plain_count = number.unit == "count"
        is_integer_format = "." not in number.raw_text
        is_small_value = value is not None and abs(float(value)) < 1000

        if is_plain_count and is_integer_format and is_small_value and not is_spelled_out_number(number.raw_text):
            if is_near_table_of_contents(text, start, self.toc_proximity_chars):
                logger.debug(
                    f"TOC proximity filter: number={number.raw_text} "
                    f"context={text[max(0, start-30):min(len(text), end+30)]!r}"
                )
                return True, "toc_proximity"

        # Check if number is part of a TOC page reference with dot leaders
        if is_toc_page_reference(text, start, self.toc_dot_leader_window):
            logger.debug(
                f"TOC dot leader filter: number={number.raw_text} "
                f"context={text[max(0, start-30):min(len(text), end+30)]!r}"
            )
            return True, "toc_page_reference"

        # Check if number is part of a date pattern
        # Look at surrounding context (100 chars each side to catch longer phrases)
        context_start = max(0, start - 100)
        context_end = min(len(text), end + 100)
        local_context = text[context_start:context_end]

        # Calculate the number's position relative to the local context
        num_rel_start = start - context_start
        num_rel_end = end - context_start

        for pattern in DATE_CONTEXT_PATTERNS:
            # FIX: Use finditer to check ALL matches in the context, not just the first one
            for match in pattern.finditer(local_context):
                # Check if our number overlaps with the date match (in local coords)
                if num_rel_start >= match.start() and num_rel_end <= match.end():
                    return True, "part_of_date"

        # Check for false positive context patterns (page refs, notes, etc.)
        for pattern in FALSE_POSITIVE_CONTEXT_PATTERNS:
            # FIX: Use finditer to check ALL matches inside the context
            for match in pattern.finditer(local_context):
                # Check if our number overlaps with the reference pattern
                if num_rel_start >= match.start() and num_rel_end <= match.end():
                    return True, "reference_number"

        # CMS-2: Check if number is part of a metric label threshold
        # Example: "Paid Customers > $100,000" - the $100,000 is label-embedded
        # Look for comparison operator immediately before the number
        if self._is_label_embedded_value(text, number):
            logger.debug(
                f"Label-embedded value filter: number={number.raw_text} "
                f"context={text[max(0, start-30):min(len(text), end+10)]!r}"
            )
            return True, "label_embedded_value"

        # HRV-11: Check if number appears in financial statement context
        if self.filter_financial_statements:
            # First check: Is this within a financial statement section?
            in_fin_statement = is_in_financial_statement_context(
                text, start, self.financial_statement_proximity_chars
            )

            if in_fin_statement:
                # Second check: Does the local context contain financial line item keywords?
                financial_keyword = contains_financial_line_item_keyword(local_context)

                if financial_keyword:
                    logger.debug(
                        f"Financial statement filter: number={number.raw_text} "
                        f"keyword={financial_keyword!r} "
                        f"context={text[max(0, start-50):min(len(text), end+50)]!r}"
                    )
                    return True, f"financial_line_item:{financial_keyword}"

        return False, None

    def _is_label_embedded_value(
        self, text: str, number: NumberMatch, window_chars: int = 20
    ) -> bool:
        """
        Check if a number is part of a metric label threshold pattern.

        Detects patterns like:
        - "Customers > $100,000" - the $100,000 is label-embedded
        - "ARR >= $50M" - the $50M is label-embedded
        - "Paid Customers > $100K" - part of a threshold label

        Args:
            text: Full text containing the number
            number: The NumberMatch to check
            window_chars: Characters before number to search for operator

        Returns:
            True if number appears to be part of a comparison pattern
        """
        # Look at text before the number (with some buffer)
        search_start = max(0, number.start - window_chars)

        # Include the number itself since pattern needs to match both operator and number
        search_text = text[search_start : number.end]

        # Check if pattern matches and includes our number
        match = LABEL_EMBEDDED_VALUE_PATTERN.search(search_text)
        if match:
            # Verify the pattern ends at or after our number position
            # (relative to search_text)
            num_rel_end = number.end - search_start
            if match.end() >= num_rel_end - 2:  # Allow small tolerance
                return True

        return False


---

## File 9: src/web/app.py

"""
Flask application factory for the human review interface.

Creates and configures the Flask application with:
- Database connection management
- Blueprint registration for routes
- Template and static file configuration
"""

import atexit
import logging
import os
from typing import Any

from flask import Flask, current_app, g, jsonify, render_template, request

from src.infra.db import DatabaseAdapter

logger = logging.getLogger(__name__)


class Config:
    """Base configuration."""

    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-secret-key-not-for-production")
    DATABASE_URL = os.environ.get("DATABASE_URL", "")

    # Session configuration
    SESSION_COOKIE_SECURE = False  # Set True in production with HTTPS
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"

    # Connection pool configuration
    DB_POOL_ENABLED = os.environ.get("DB_POOL_ENABLED", "true").lower() == "true"
    DB_POOL_MIN_SIZE = int(os.environ.get("DB_POOL_MIN_SIZE", "2"))
    DB_POOL_MAX_SIZE = int(os.environ.get("DB_POOL_MAX_SIZE", "10"))


class DevelopmentConfig(Config):
    """Development configuration."""

    DEBUG = True
    TESTING = False


class TestingConfig(Config):
    """Testing configuration."""

    DEBUG = True
    TESTING = True
    SECRET_KEY = "test-secret-key-for-testing-only"
    DATABASE_URL = os.environ.get("TEST_DATABASE_URL", "")


class ProductionConfig(Config):
    """Production configuration - SECRET_KEY validated at app creation."""

    DEBUG = False
    TESTING = False
    SESSION_COOKIE_SECURE = True


# Configuration mapping
config_by_name: dict[str, type] = {
    "development": DevelopmentConfig,
    "testing": TestingConfig,
    "production": ProductionConfig,
}


def get_db() -> DatabaseAdapter:
    """
    Get database adapter for the current request.

    Returns cached adapter from Flask g object, creating if needed.
    If connection pooling is enabled, the adapter uses the app-level pool.
    Must be called within a Flask request context.
    """
    if "db" not in g:
        database_url = current_app.config.get("DATABASE_URL", "")
        if not database_url:
            raise RuntimeError(
                "DATABASE_URL not configured. "
                "Set DATABASE_URL in app config or environment."
            )
        # Get pool from app config (may be None if pooling disabled)
        pool = current_app.config.get("_db_pool")
        g.db = DatabaseAdapter(database_url, pool=pool)
    return g.db


def close_db(e: Exception | None = None) -> None:
    """
    Clean up database adapter at end of request.

    Called automatically via teardown_appcontext. Removes the adapter
    from Flask's g object. When connection pooling is enabled, pooled
    connections are automatically returned to the pool by the adapter's
    context manager.

    Args:
        e: Optional exception that occurred during request handling.
    """
    db = g.pop("db", None)
    if db is not None:
        logger.debug("Database adapter removed from request context")


def init_pool(app: Flask) -> None:
    """
    Initialize the connection pool for the Flask application.

    Creates a connection pool and stores it in app.config["_db_pool"].
    The pool is used by get_db() to provide pooled connections to
    DatabaseAdapter instances.

    If pool creation fails, logs the error and continues without pooling
    (graceful degradation to per-request connections).

    Args:
        app: Flask application instance.
    """
    if not app.config.get("DB_POOL_ENABLED", True):
        logger.info("Connection pooling disabled via DB_POOL_ENABLED=false")
        return

    database_url = app.config.get("DATABASE_URL", "")
    if not database_url:
        logger.warning("DATABASE_URL not configured, skipping pool initialization")
        return

    from src.infra.pool import create_pool

    try:
        pool = create_pool(
            database_url,
            min_size=app.config.get("DB_POOL_MIN_SIZE", 2),
            max_size=app.config.get("DB_POOL_MAX_SIZE", 10),
        )
        app.config["_db_pool"] = pool
        logger.info(
            f"Connection pool initialized: min_size={app.config.get('DB_POOL_MIN_SIZE', 2)}, "
            f"max_size={app.config.get('DB_POOL_MAX_SIZE', 10)}"
        )
    except Exception as e:
        logger.error(
            f"Failed to initialize connection pool: {e}. "
            "Falling back to per-request connections."
        )
        app.config["_db_pool"] = None


def close_pool(app: Flask) -> None:
    """
    Close the connection pool for the Flask application.

    Should be called when the application is shutting down to properly
    release database connections.

    Args:
        app: Flask application instance.
    """
    pool = app.config.get("_db_pool")
    if pool is not None:
        try:
            pool.close()
            logger.info("Connection pool closed")
        except Exception as e:
            logger.warning(f"Error closing connection pool: {e}")
        finally:
            app.config["_db_pool"] = None


def create_app(config_name: str | None = None, config_override: dict[str, Any] | None = None) -> Flask:
    """
    Create and configure the Flask application.

    Args:
        config_name: Configuration environment name ('development', 'testing', 'production').
                    Defaults to APP_ENV environment variable or 'development'.
        config_override: Optional dictionary of configuration values to override.

    Returns:
        Configured Flask application instance.

    Example:
        # Development server
        app = create_app()
        app.run(debug=True)

        # Testing
        app = create_app('testing')

        # Custom configuration
        app = create_app(config_override={'DATABASE_URL': 'postgresql://...'})
    """
    # Determine configuration
    if config_name is None:
        config_name = os.environ.get("APP_ENV", "development")

    config_class = config_by_name.get(config_name, DevelopmentConfig)

    # Create Flask app
    app = Flask(
        __name__,
        template_folder="templates",
        static_folder="static",
    )

    # Load configuration
    app.config.from_object(config_class)

    # Apply any overrides
    if config_override:
        app.config.update(config_override)

    # Validate production configuration
    if config_name == "production":
        # Check environment directly since config class may have been loaded at import time
        env_secret = os.environ.get("SECRET_KEY", "")
        if not env_secret:
            raise ValueError(
                "SECRET_KEY environment variable is required in production. "
                "Generate one with: python -c \"import secrets; print(secrets.token_hex(32))\""
            )
        # Update config with the actual secret key from environment
        app.config["SECRET_KEY"] = env_secret

    # Register database teardown handler
    app.teardown_appcontext(close_db)

    # Initialize connection pool
    init_pool(app)

    # Register pool cleanup on process exit
    atexit.register(close_pool, app)

    # Register health check endpoint
    _register_health_check(app)

    # Register blueprints (routes will be added in later tasks)
    _register_blueprints(app)

    # Register error handlers
    _register_error_handlers(app)

    # Register template context processors
    _register_context_processors(app)

    # Register template filters
    _register_template_filters(app)

    logger.info(f"Flask app created with config: {config_name}")

    return app


def _register_health_check(app: Flask) -> None:
    """
    Register /health endpoint for load balancers and monitoring.

    Returns 200 OK if app and database are healthy, 503 otherwise.
    Does not require authentication.
    """
    @app.route("/health")
    def health_check():
        """
        Health check endpoint for monitoring and load balancing.

        Returns:
            JSON response with health status and optional pool stats.
            - 200 OK: Application and database are healthy
            - 503 Service Unavailable: Database connection failed
        """
        try:
            pool = current_app.config.get("_db_pool")

            if pool is not None:
                from src.infra.pool import check_pool_health

                health = check_pool_health(pool)
                if health.is_healthy:
                    return jsonify({
                        "status": "healthy",
                        "database": "connected",
                        "pool_stats": {
                            "total_connections": health.total_connections,
                            "idle_connections": health.idle_connections,
                            "active_connections": health.active_connections,
                            "test_query_elapsed": health.test_query_elapsed,
                        },
                    }), 200
                else:
                    return jsonify({
                        "status": "unhealthy",
                        "database": "error",
                        "message": health.error,
                    }), 503
            else:
                # No pool, try direct connection
                db = DatabaseAdapter(current_app.config["DATABASE_URL"])
                with db.get_connection() as conn:
                    conn.execute("SELECT 1")

                return jsonify({
                    "status": "healthy",
                    "database": "connected",
                    "pool_stats": None,
                }), 200

        except Exception as e:
            logger.error(f"Health check failed: {e}")
            return jsonify({
                "status": "unhealthy",
                "database": "error",
                "message": str(e),
            }), 503


def _register_blueprints(app: Flask) -> None:
    """
    Register route blueprints with the application.

    Blueprints are added in tasks D1 (review.py) and D2 (api.py).
    """
    # Register review blueprint (D1)
    from src.web.routes.review import review_bp

    app.register_blueprint(review_bp)

    # API blueprint (D2)
    from src.web.routes.api import api_bp

    app.register_blueprint(api_bp, url_prefix="/api")

    # Image review API blueprint (IMG-1-5)
    from src.web.routes.api_images import api_images_bp

    app.register_blueprint(api_images_bp)

    # Image review page routes (IMG-1-4)
    from src.web.routes.review_images import review_images_bp

    app.register_blueprint(review_images_bp)


def _wants_json_response() -> bool:
    """Check if the client prefers JSON over HTML."""
    best = request.accept_mimetypes.best_match(["application/json", "text/html"])
    return (
        best == "application/json"
        and request.accept_mimetypes[best] > request.accept_mimetypes["text/html"]
    )


def _register_error_handlers(app: Flask) -> None:
    """Register custom error handlers that return JSON for API requests, HTML otherwise."""

    @app.errorhandler(404)
    def not_found_error(error):
        if _wants_json_response():
            return jsonify(error="Not found"), 404
        return render_template("errors/404.html"), 404

    @app.errorhandler(500)
    def internal_error(error):
        logger.error(f"Internal server error: {error}")
        if _wants_json_response():
            return jsonify(error="Internal server error"), 500
        return render_template("errors/500.html"), 500


def _register_context_processors(app: Flask) -> None:
    """Register template context processors."""

    @app.context_processor
    def utility_processor():
        """Add utility functions to template context."""
        return {
            "app_name": "Filings Review",
            "app_version": "0.1.0",
        }


def _register_template_filters(app: Flask) -> None:
    """Register custom Jinja2 template filters."""

    @app.template_filter("highlight_context")
    def highlight_context_filter(context_text, raw_number_text, triggering_keyword):
        """
        Jinja2 filter to highlight number and keyword in context text.

        Usage in template:
            {{ candidate.context_text|highlight_context(
                 candidate.raw_number_text,
                 candidate.triggering_keyword
               )|safe }}

        Args:
            context_text: The surrounding text context
            raw_number_text: Exact number text to highlight
            triggering_keyword: Metric keyword to underline

        Returns:
            Markup: HTML-safe string with highlighted number and keyword
        """
        from src.web.routes.review import _highlight_context

        return _highlight_context(context_text, raw_number_text, triggering_keyword)

    @app.template_filter("highlight_html")
    def highlight_html_filter(html_content, raw_number_text, triggering_keyword):
        """
        Jinja2 filter to highlight number and keyword in HTML content (tables).

        Usage in template:
            {{ candidate.segment_html|highlight_html(
                 candidate.raw_number_text,
                 candidate.triggering_keyword
               )|safe }}

        Args:
            html_content: HTML content (e.g., table markup)
            raw_number_text: Exact number text to highlight
            triggering_keyword: Metric keyword to underline

        Returns:
            Markup: HTML string with highlighted number and keyword
        """
        from src.web.routes.review import _highlight_html

        return _highlight_html(html_content, raw_number_text, triggering_keyword)


# Convenience function for running directly
def run_dev_server(host: str = "127.0.0.1", port: int = 5002) -> None:
    """
    Run the development server.

    Args:
        host: Host to bind to (default: 127.0.0.1)
        port: Port to bind to (default: 5002)
    """
    from dotenv import load_dotenv

    load_dotenv()

    app = create_app("development")
    app.run(host=host, port=port, debug=True)


if __name__ == "__main__":
    run_dev_server()


---

## File 10: src/extraction/extraction_pipeline.py

"""
Extraction Pipeline - End-to-end metric extraction orchestration.

This module orchestrates the complete extraction pipeline:
1. HTML Segmentation
2. Metric Classification
3. Value Extraction
4. Definition Extraction
5. Quality Scoring
6. Database Storage
"""

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Optional

from src.infra.db import DatabaseAdapter

from .definition_extractor import DefinitionExtractor
from .html_segmenter import HTMLSegmenter
from .metric_classifier import MetricClassifier
from .models import (
    FilingMetricIncidence,
    MetricDefinition,
    MetricValue,
    SourceSegment,
)
from .quality_scorer import QualityScorer
from .segment_enricher import SegmentEnricher, cluster_goldmine_segments
from .value_extractor import ValueExtractor

if TYPE_CHECKING:
    from ..llm.openai_client import OpenAIClient

logger = logging.getLogger(__name__)


@dataclass
class ExtractionResult:
    """Result of processing a single filing."""

    filing_id: int
    success: bool
    error: str | None = None
    num_segments: int = 0
    num_values: int = 0
    num_definitions: int = 0
    num_incidences: int = 0


class ExtractionPipeline:
    """
    Orchestrate the complete metric extraction pipeline.

    Pipeline stages:
    1. Segment HTML into source_segments
    2. Classify segments for metric content
    3. Extract numeric values from segments
    4. Extract definitions and methodologies
    5. Compute quality scores and incidence
    6. Write all results to database
    """

    def __init__(
        self, db: DatabaseAdapter, llm_client: Optional["OpenAIClient"] = None
    ):
        """
        Initialize the extraction pipeline.

        Args:
            db: Database adapter
            llm_client: Optional OpenAI client for LLM-enhanced extraction.
                       If provided, extractors will use LLM with rule-based fallback.
                       If not provided, only rule-based extraction will be used.
        """
        self.db = db
        self.llm_client = llm_client
        self.segmenter = HTMLSegmenter()
        self.classifier = MetricClassifier()
        self.enricher = SegmentEnricher()
        self.value_extractor = ValueExtractor(llm_client=llm_client)
        self.definition_extractor = DefinitionExtractor(llm_client=llm_client)
        self.quality_scorer = QualityScorer()

        if llm_client:
            logger.info("✓ Pipeline initialized with LLM-enhanced extraction and enrichment")
        else:
            logger.info("✓ Pipeline initialized with rule-based extraction and enrichment")

    def process_filing(self, filing_id: int) -> ExtractionResult:
        """
        Run full extraction pipeline for a single filing.

        Steps:
            1. Fetch filing metadata from database
            2. Segment HTML
            3. Classify segments
            4. Extract values
            5. Extract definitions
            6. Compute quality scores
            7. Write all to database in a transaction

        Args:
            filing_id: Database filing ID

        Returns:
            ExtractionResult with processing summary
        """
        logger.info(f"Processing filing {filing_id}")

        try:
            # Step 0: Fetch filing metadata
            filing = self._get_filing_metadata(filing_id)
            if not filing:
                return ExtractionResult(
                    filing_id=filing_id,
                    success=False,
                    error="Filing not found in database",
                )

            # Step 1: Segment HTML
            logger.info("  Stage 1: Segmenting HTML")
            segments = self.segmenter.segment_filing(
                filing_id=filing_id, html_path=filing["html_storage_path"]
            )

            if not segments:
                return ExtractionResult(
                    filing_id=filing_id,
                    success=False,
                    error="No segments extracted from HTML",
                )

            # Step 2: Classify segments
            logger.info(f"  Stage 2: Classifying {len(segments)} segments")
            classified_segments = self.classifier.classify_batch(segments)

            # Step 2b: Enrich segments with richness metadata
            logger.info(f"  Stage 2b: Enriching {len(classified_segments)} segments")
            self.enricher.enrich_batch(classified_segments)  # mutates in place

            # Step 2c: Tiered segment selection
            logger.info("  Stage 2c: Selecting segments via tiered prioritization")
            selected_segments = self._select_segments_tiered(classified_segments)

            # Log goldmine statistics
            goldmines = [s for s in selected_segments if (s.richness_score or 0) >= 6.0]
            clusters = cluster_goldmine_segments(goldmines) if goldmines else []
            logger.info(f"  Identified {len(goldmines)} goldmine segments in {len(clusters)} clusters")

            # Step 3: Extract values (from selected segments)
            logger.info(f"  Stage 3: Extracting values from {len(selected_segments)} segments")
            all_values = []
            for seg in selected_segments:
                values = self.value_extractor.extract_from_segment(
                    seg, company_id=filing["company_id"]
                )
                all_values.extend(values)

            # Step 4: Extract definitions (from selected segments)
            logger.info(f"  Stage 4: Extracting definitions from {len(selected_segments)} segments")
            definitions = self.definition_extractor.extract_definitions(
                selected_segments, company_id=filing["company_id"]
            )

            # Step 5: Compute quality scores (based on selected segments)
            logger.info("  Stage 5: Computing quality scores")
            incidences = self.quality_scorer.score_filing(
                filing_id=filing_id,
                company_id=filing["company_id"],
                segments=selected_segments,
                values=all_values,
                definitions=definitions,
            )

            # Step 6: Write to database
            logger.info("  Stage 6: Writing to database")
            self._write_results(
                filing_id, selected_segments, all_values, definitions, incidences
            )

            logger.info(f"✓ Successfully processed filing {filing_id}")
            logger.info(
                f"    Total segments: {len(classified_segments)}, Selected: {len(selected_segments)}, "
                + f"Goldmines: {len(goldmines)}, Values: {len(all_values)}, "
                + f"Definitions: {len(definitions)}, Incidences: {len(incidences)}"
            )

            return ExtractionResult(
                filing_id=filing_id,
                success=True,
                num_segments=len(selected_segments),
                num_values=len(all_values),
                num_definitions=len(definitions),
                num_incidences=len(incidences),
            )

        except (ValueError, KeyError) as e:
            # Data/validation errors - filing data is invalid or missing expected fields
            logger.error(
                f"✗ Data error processing filing {filing_id}: {e}", exc_info=True
            )
            return ExtractionResult(filing_id=filing_id, success=False, error=str(e))

        except OSError as e:
            # File system errors - HTML file not found or unreadable
            logger.error(
                f"✗ File error processing filing {filing_id}: {e}", exc_info=True
            )
            return ExtractionResult(filing_id=filing_id, success=False, error=str(e))

        except Exception as e:
            # Unexpected errors - log with full details for debugging
            logger.critical(
                f"✗ Unexpected error processing filing {filing_id}: "
                f"{type(e).__name__}: {e}",
                exc_info=True,
            )
            return ExtractionResult(filing_id=filing_id, success=False, error=str(e))

    def process_batch(self, filing_ids: list[int]) -> dict[str, int]:
        """
        Process multiple filings.

        Args:
            filing_ids: List of filing IDs to process

        Returns:
            Statistics dictionary with counts
        """
        logger.info(f"Processing batch of {len(filing_ids)} filings")

        stats = {
            "total": len(filing_ids),
            "success": 0,
            "failed": 0,
            "total_segments": 0,
            "total_values": 0,
            "total_definitions": 0,
            "total_incidences": 0,
        }

        for i, filing_id in enumerate(filing_ids):
            logger.info(f"[{i+1}/{len(filing_ids)}] Processing filing {filing_id}")

            result = self.process_filing(filing_id)

            if result.success:
                stats["success"] += 1
                stats["total_segments"] += result.num_segments
                stats["total_values"] += result.num_values
                stats["total_definitions"] += result.num_definitions
                stats["total_incidences"] += result.num_incidences
            else:
                stats["failed"] += 1
                logger.error(f"  Failed: {result.error}")

        logger.info("")
        logger.info("=" * 80)
        logger.info("Batch Processing Summary")
        logger.info("=" * 80)
        logger.info(f"Total filings: {stats['total']}")
        logger.info(f"Successful: {stats['success']}")
        logger.info(f"Failed: {stats['failed']}")
        logger.info(f"Total segments: {stats['total_segments']}")
        logger.info(f"Total values: {stats['total_values']}")
        logger.info(f"Total definitions: {stats['total_definitions']}")
        logger.info(f"Total incidences: {stats['total_incidences']}")
        logger.info("=" * 80)

        return stats

    def _get_filing_metadata(self, filing_id: int) -> dict | None:
        """Fetch filing metadata from database."""
        result = self.db.query(
            """
            SELECT filing_id, company_id, cik, accession_number, html_storage_path
            FROM filings
            WHERE filing_id = %(filing_id)s
        """,
            {"filing_id": filing_id},
        )

        if not result:
            return None

        filing = result[0]

        # Check if HTML file exists
        if (
            not filing["html_storage_path"]
            or not Path(filing["html_storage_path"]).exists()
        ):
            logger.error(f"HTML file not found: {filing['html_storage_path']}")
            return None

        return filing

    def _select_segments_tiered(
        self, segments: list[SourceSegment]
    ) -> list[SourceSegment]:
        """
        Select segments using tiered prioritization.

        Tiers (processed in order, deduplicated):
        1. High richness (>= 6.0) - up to 30 segments
        2. Medium richness (4.0-6.0) - up to 40 segments
        3. Critical flags (definitions/methodologies) - remainder up to 80 total

        Args:
            segments: Enriched segments with richness_score populated

        Returns:
            Selected segments, deduplicated and sorted by richness
        """
        RICHNESS_THRESHOLD = 6.0
        MEDIUM_THRESHOLD = 4.0
        MAX_HIGH_RICHNESS = 30
        MAX_MEDIUM_RICHNESS = 40
        MAX_TOTAL = 80

        selected_ids: set[int] = set()  # Use object id for deduplication
        result: list[SourceSegment] = []

        # Tier 1: High richness (goldmines)
        high_richness = sorted(
            [s for s in segments if (s.richness_score or 0) >= RICHNESS_THRESHOLD],
            key=lambda s: s.richness_score or 0,
            reverse=True,
        )[:MAX_HIGH_RICHNESS]

        for seg in high_richness:
            if id(seg) not in selected_ids:
                result.append(seg)
                selected_ids.add(id(seg))

        high_count = len(result)

        # Tier 2: Medium richness (supporting context)
        medium_richness = sorted(
            [
                s
                for s in segments
                if MEDIUM_THRESHOLD <= (s.richness_score or 0) < RICHNESS_THRESHOLD
            ],
            key=lambda s: s.richness_score or 0,
            reverse=True,
        )[:MAX_MEDIUM_RICHNESS]

        for seg in medium_richness:
            if id(seg) not in selected_ids:
                result.append(seg)
                selected_ids.add(id(seg))

        # NEW: Direct Hit Tier (Specific matches with lower richness)
        # Allows short segments that are highly specific (e.g. "Churn rate was 5%")
        # Threshold: 3.0 (Lower than medium)
        DIRECT_HIT_THRESHOLD = 3.0
        direct_hits = [
            s for s in segments
            if (s.richness_score or 0) >= DIRECT_HIT_THRESHOLD
            and (s.richness_score or 0) < MEDIUM_THRESHOLD
            and s.candidate_metric_ids
            and len(s.candidate_metric_ids) == 1 # Very specific
            and s.contains_numeric_disclosure_flag # Must have numbers
        ]

        for seg in direct_hits:
            if len(result) >= MAX_TOTAL:
                break
            if id(seg) not in selected_ids:
                result.append(seg)
                selected_ids.add(id(seg))

        medium_count = len(result) - high_count

        # Tier 3: Critical flags (definitions/methodologies)
        critical = [
            s
            for s in segments
            if (s.contains_definition_flag or s.contains_methodology_flag)
            and id(s) not in selected_ids
        ]

        critical_count = 0
        for seg in critical:
            if len(result) >= MAX_TOTAL:
                break
            result.append(seg)
            selected_ids.add(id(seg))
            critical_count += 1

        logger.info(
            f"  Selected: {high_count} high-richness, {medium_count} medium-richness, "
            f"{critical_count} critical (total: {len(result)})"
        )

        return result

    def _write_results(
        self,
        filing_id: int,
        segments: list[SourceSegment],
        values: list[MetricValue],
        definitions: list[MetricDefinition],
        incidences: list[FilingMetricIncidence],
    ):
        """
        Write all extraction results to database in a transaction.

        Args:
            filing_id: Filing ID
            segments: Source segments
            values: Metric values
            definitions: Metric definitions
            incidences: Filing-metric incidences
        """
        # Use database transaction for atomicity
        # If any insert fails, everything rolls back

        cleanup_sql = [
            "DELETE FROM filing_metric_incidence WHERE filing_id = %(filing_id)s",
            "DELETE FROM metric_definitions WHERE filing_id = %(filing_id)s",
            "DELETE FROM metric_values WHERE filing_id = %(filing_id)s",
            "DELETE FROM source_segments WHERE filing_id = %(filing_id)s",
        ]

        with self.db.get_connection() as conn:
            with conn.cursor() as cur:
                # Remove any prior extraction artifacts for this filing so re-runs are idempotent.
                for statement in cleanup_sql:
                    cur.execute(statement, {"filing_id": filing_id})

                # Insert source segments
                segment_id_map: dict[int, int] = {}
                for seg in segments:
                    cur.execute(
                        """
                        INSERT INTO source_segments (
                            filing_id, segment_type, section_path, section_heading,
                            sequence_index, raw_text, raw_html,
                            candidate_metric_ids,
                            contains_definition_flag,
                            contains_methodology_flag,
                            contains_numeric_disclosure_flag,
                            classifier_confidence,
                            metric_density,
                            distinct_metric_count,
                            contains_temporal_trend,
                            contains_cohort_breakdown,
                            image_count,
                            richness_score
                        ) VALUES (
                            %(filing_id)s, %(segment_type)s, %(section_path)s, %(section_heading)s,
                            %(sequence_index)s, %(raw_text)s, %(raw_html)s,
                            %(candidate_metric_ids)s,
                            %(contains_definition_flag)s,
                            %(contains_methodology_flag)s,
                            %(contains_numeric_disclosure_flag)s,
                            %(classifier_confidence)s,
                            %(metric_density)s,
                            %(distinct_metric_count)s,
                            %(contains_temporal_trend)s,
                            %(contains_cohort_breakdown)s,
                            %(image_count)s,
                            %(richness_score)s
                        )
                        RETURNING source_segment_id
                        """,
                        seg.to_dict(),
                    )
                    result = cur.fetchone()
                    if result:
                        db_id = result["source_segment_id"]
                        segment_id_map[seg.sequence_index] = db_id
                        seg.source_segment_id = db_id

                # Update values with actual segment IDs
                valid_values: list[MetricValue] = []
                for val in values:
                    if val.source_segment_id in segment_id_map:
                        val.source_segment_id = segment_id_map[val.source_segment_id]
                        valid_values.append(val)
                    else:
                        logger.warning(
                            "Skipping metric value for filing %s because segment %s was not persisted",
                            filing_id,
                            val.source_segment_id,
                        )

                # Insert metric values
                for val in valid_values:
                    cur.execute(
                        """
                        INSERT INTO metric_values (
                            filing_id, company_id, metric_id, source_segment_id,
                            source_type, extraction_method,
                            value_numeric, value_text, unit, currency,
                            period_start, period_end, period_type,
                            cohort_type, cohort_bucket_raw, cohort_bucket_normalized,
                            segment_dimension, segment_value,
                            qa_status, qa_notes, alignment_flag
                        ) VALUES (
                            %(filing_id)s, %(company_id)s, %(metric_id)s, %(source_segment_id)s,
                            %(source_type)s, %(extraction_method)s,
                            %(value_numeric)s, %(value_text)s, %(unit)s, %(currency)s,
                            %(period_start)s, %(period_end)s, %(period_type)s,
                            %(cohort_type)s, %(cohort_bucket_raw)s, %(cohort_bucket_normalized)s,
                            %(segment_dimension)s, %(segment_value)s,
                            %(qa_status)s, %(qa_notes)s, %(alignment_flag)s
                        )
                        """,
                        val.to_dict(),
                    )

                # Update definitions with actual segment IDs
                valid_definitions: list[MetricDefinition] = []
                for defn in definitions:
                    if (
                        defn.definition_segment_id is not None
                        and defn.definition_segment_id in segment_id_map
                    ):
                        defn.definition_segment_id = segment_id_map[
                            defn.definition_segment_id
                        ]

                    if (
                        defn.methodology_segment_id is not None
                        and defn.methodology_segment_id in segment_id_map
                    ):
                        defn.methodology_segment_id = segment_id_map[
                            defn.methodology_segment_id
                        ]
                    valid_definitions.append(defn)

                # Insert metric definitions
                for defn in valid_definitions:
                    cur.execute(
                        """
                        INSERT INTO metric_definitions (
                            filing_id, company_id, metric_id,
                            definition_version_in_filing,
                            definition_text_normalized, methodology_text_normalized,
                            definition_raw_text, methodology_raw_text,
                            definition_segment_id, methodology_segment_id,
                            alignment_flag, alignment_notes
                        ) VALUES (
                            %(filing_id)s, %(company_id)s, %(metric_id)s,
                            %(definition_version_in_filing)s,
                            %(definition_text_normalized)s, %(methodology_text_normalized)s,
                            %(definition_raw_text)s, %(methodology_raw_text)s,
                            %(definition_segment_id)s, %(methodology_segment_id)s,
                            %(alignment_flag)s, %(alignment_notes)s
                        )
                        """,
                        defn.to_dict(),
                    )

                # Update incidences with actual segment IDs
                for inc in incidences:
                    if (
                        inc.primary_definition_segment_id is not None
                        and inc.primary_definition_segment_id in segment_id_map
                    ):
                        inc.primary_definition_segment_id = segment_id_map[
                            inc.primary_definition_segment_id
                        ]
                    elif inc.primary_definition_segment_id is not None:
                        # Segment not in map, set to None to avoid FK violation
                        inc.primary_definition_segment_id = None

                    if (
                        inc.primary_methodology_segment_id is not None
                        and inc.primary_methodology_segment_id in segment_id_map
                    ):
                        inc.primary_methodology_segment_id = segment_id_map[
                            inc.primary_methodology_segment_id
                        ]
                    elif inc.primary_methodology_segment_id is not None:
                        # Segment not in map, set to None to avoid FK violation
                        inc.primary_methodology_segment_id = None

                # Insert filing-metric incidences
                for inc in incidences:
                    cur.execute(
                        """
                        INSERT INTO filing_metric_incidence (
                            filing_id, company_id, metric_id,
                            metric_disclosed_flag,
                            num_numeric_segments, num_definition_segments, num_methodology_segments,
                            primary_definition_segment_id, primary_methodology_segment_id,
                            quality_overall_score, quality_definition_score,
                            quality_methodology_score, quality_completeness_score,
                            quality_comparability_score,
                            alignment_flag, quality_notes,
                            has_cohort_breakdown_flag, has_tenure_breakdown_flag,
                            has_acquisition_cohort_flag
                        ) VALUES (
                            %(filing_id)s, %(company_id)s, %(metric_id)s,
                            %(metric_disclosed_flag)s,
                            %(num_numeric_segments)s, %(num_definition_segments)s, %(num_methodology_segments)s,
                            %(primary_definition_segment_id)s, %(primary_methodology_segment_id)s,
                            %(quality_overall_score)s, %(quality_definition_score)s,
                            %(quality_methodology_score)s, %(quality_completeness_score)s,
                            %(quality_comparability_score)s,
                            %(alignment_flag)s, %(quality_notes)s,
                            %(has_cohort_breakdown_flag)s, %(has_tenure_breakdown_flag)s,
                            %(has_acquisition_cohort_flag)s
                        )
                        """,
                        inc.to_dict(),
                    )

        logger.info(f"    Inserted {len(segments)} source segments")
        logger.info(f"    Inserted {len(valid_values)} metric values")
        logger.info(f"    Inserted {len(valid_definitions)} metric definitions")
        logger.info(f"    Inserted {len(incidences)} filing-metric incidences")


---

## File 11: src/llm/openai_client.py

"""
OpenAI API Client with error handling, retry logic, and cost tracking.

This module provides a robust wrapper around the OpenAI API with:
- Automatic retry with exponential backoff
- Token counting and cost tracking
- Rate limiting
- Comprehensive error handling
"""

import logging
import os
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Any

try:
    import tiktoken
except ImportError:
    tiktoken = None

try:
    from openai import APIConnectionError, APIError, OpenAI, RateLimitError
except ImportError as e:
    raise ImportError("OpenAI package not installed. Run: pip install openai tiktoken") from e

logger = logging.getLogger(__name__)


@dataclass
class LLMResponse:
    """Response from LLM with metadata."""

    content: str
    model: str
    input_tokens: int
    output_tokens: int
    total_tokens: int
    cost: float
    latency_ms: int
    timestamp: datetime


@dataclass
class CostTracker:
    """Track cumulative LLM API costs."""

    total_requests: int = 0
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    total_cost: float = 0.0
    failed_requests: int = 0

    def add_request(self, response: LLMResponse):
        """Add a successful request to tracking."""
        self.total_requests += 1
        self.total_input_tokens += response.input_tokens
        self.total_output_tokens += response.output_tokens
        self.total_cost += response.cost

    def add_failure(self):
        """Record a failed request."""
        self.failed_requests += 1

    def summary(self) -> dict[str, Any]:
        """Get summary statistics."""
        return {
            "total_requests": self.total_requests,
            "successful_requests": self.total_requests,
            "failed_requests": self.failed_requests,
            "total_input_tokens": self.total_input_tokens,
            "total_output_tokens": self.total_output_tokens,
            "total_tokens": self.total_input_tokens + self.total_output_tokens,
            "total_cost_usd": round(self.total_cost, 4),
            "avg_cost_per_request": (
                round(self.total_cost / self.total_requests, 4)
                if self.total_requests > 0
                else 0
            ),
        }


class OpenAIClient:
    """
    OpenAI API client with robust error handling and cost tracking.

    Features:
    - Automatic retry with exponential backoff
    - Token counting using tiktoken
    - Cost tracking per request and cumulative
    - Rate limiting
    - Comprehensive error handling
    """

    # Pricing per 1M tokens (as of 2025-01)
    PRICING = {
        "gpt-4o": {"input": 2.50, "output": 10.00},
        "gpt-4o-mini": {"input": 0.15, "output": 0.60},
        "gpt-4o-2024-08-06": {"input": 2.50, "output": 10.00},
        "gpt-4o-mini-2024-07-18": {"input": 0.15, "output": 0.60},
    }

    def __init__(
        self,
        api_key: str | None = None,
        model: str = "gpt-4o-mini",
        temperature: float = 0.1,
        max_tokens: int = 4096,
        max_retries: int = 3,
        retry_delay: float = 1.0,
    ):
        """
        Initialize OpenAI client.

        Args:
            api_key: OpenAI API key (defaults to OPENAI_API_KEY env var)
            model: Model to use (default: gpt-4o-mini)
            temperature: Sampling temperature (0.0-2.0, default: 0.1 for deterministic)
            max_tokens: Maximum tokens in response
            max_retries: Number of retries on failure
            retry_delay: Initial delay between retries (exponential backoff)
        """
        self.api_key = api_key or os.getenv("OPENAI_API_KEY")
        if not self.api_key:
            raise ValueError(
                "OpenAI API key required. Set OPENAI_API_KEY env var or pass api_key parameter."
            )

        self.client = OpenAI(api_key=self.api_key)
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.max_retries = max_retries
        self.retry_delay = retry_delay

        # Initialize tokenizer for counting
        if tiktoken:
            try:
                self.tokenizer = tiktoken.encoding_for_model(model)
            except KeyError:
                # Fallback to cl100k_base for newer models
                self.tokenizer = tiktoken.get_encoding("cl100k_base")
                logger.warning(
                    f"No tokenizer for {model}, using cl100k_base as fallback"
                )
        else:
            self.tokenizer = None
            logger.warning("tiktoken not installed, token counting will be estimated")

        # Cost tracking
        self.cost_tracker = CostTracker()

        logger.info(f"OpenAI client initialized with model: {model}")

    def count_tokens(self, text: str) -> int:
        """
        Count tokens in text.

        Args:
            text: Input text

        Returns:
            Token count
        """
        if self.tokenizer:
            return len(self.tokenizer.encode(text))
        else:
            # Rough estimate: 1 token ≈ 4 characters
            return len(text) // 4

    def calculate_cost(self, input_tokens: int, output_tokens: int) -> float:
        """
        Calculate cost for a request.

        Args:
            input_tokens: Number of input tokens
            output_tokens: Number of output tokens

        Returns:
            Cost in USD
        """
        pricing = self.PRICING.get(self.model, self.PRICING["gpt-4o-mini"])

        input_cost = (input_tokens / 1_000_000) * pricing["input"]
        output_cost = (output_tokens / 1_000_000) * pricing["output"]

        return input_cost + output_cost

    def complete(
        self,
        prompt: str,
        system_message: str | None = None,
        **kwargs,
    ) -> LLMResponse:
        """
        Send completion request to OpenAI API with retry logic.

        Args:
            prompt: User prompt
            system_message: Optional system message
            **kwargs: Additional arguments to pass to API

        Returns:
            LLMResponse with content and metadata

        Raises:
            APIError: If all retries fail
        """
        # Build messages
        messages = []
        if system_message:
            messages.append({"role": "system", "content": system_message})
        messages.append({"role": "user", "content": prompt})

        # Count input tokens
        input_text = (system_message or "") + prompt
        input_tokens = self.count_tokens(input_text)

        # Retry loop with exponential backoff
        last_error = None
        for attempt in range(self.max_retries):
            try:
                start_time = time.time()

                # Make API call
                response = self.client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    temperature=self.temperature,
                    max_tokens=self.max_tokens,
                    **kwargs,
                )

                latency_ms = int((time.time() - start_time) * 1000)

                # Extract response
                content = response.choices[0].message.content
                output_tokens = response.usage.completion_tokens
                total_tokens = response.usage.total_tokens

                # Calculate cost
                cost = self.calculate_cost(input_tokens, output_tokens)

                # Create response object
                llm_response = LLMResponse(
                    content=content,
                    model=self.model,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    total_tokens=total_tokens,
                    cost=cost,
                    latency_ms=latency_ms,
                    timestamp=datetime.now(),
                )

                # Track cost
                self.cost_tracker.add_request(llm_response)

                logger.debug(
                    f"LLM request successful: {output_tokens} tokens, ${cost:.4f}, {latency_ms}ms"
                )

                return llm_response

            except RateLimitError as e:
                last_error = e
                delay = self.retry_delay * (2**attempt)
                logger.warning(
                    f"Rate limit hit, retrying in {delay}s (attempt {attempt + 1}/{self.max_retries})"
                )
                time.sleep(delay)

            except APIConnectionError as e:
                last_error = e
                delay = self.retry_delay * (2**attempt)
                logger.warning(
                    f"Connection error, retrying in {delay}s (attempt {attempt + 1}/{self.max_retries})"
                )
                time.sleep(delay)

            except APIError as e:
                last_error = e
                # Don't retry on 4xx errors (except rate limit)
                if hasattr(e, "status_code") and 400 <= e.status_code < 500:
                    logger.error(f"API error (non-retryable): {e}")
                    self.cost_tracker.add_failure()
                    raise
                else:
                    delay = self.retry_delay * (2**attempt)
                    logger.warning(
                        f"API error, retrying in {delay}s (attempt {attempt + 1}/{self.max_retries})"
                    )
                    time.sleep(delay)

        # All retries exhausted
        self.cost_tracker.add_failure()
        logger.error(f"All {self.max_retries} retries exhausted")
        raise last_error

    def complete_batch(
        self,
        prompts: list[str],
        system_message: str | None = None,
        delay_between_requests: float = 0.1,
    ) -> list[LLMResponse]:
        """
        Send multiple completion requests with rate limiting.

        Args:
            prompts: List of user prompts
            system_message: Optional system message for all prompts
            delay_between_requests: Delay between requests (seconds)

        Returns:
            List of LLMResponse objects
        """
        responses = []

        for i, prompt in enumerate(prompts):
            logger.info(f"Processing prompt {i + 1}/{len(prompts)}")

            try:
                response = self.complete(prompt, system_message=system_message)
                responses.append(response)
            except Exception as e:
                logger.error(f"Failed to process prompt {i + 1}: {e}")
                # Continue with next prompt
                continue

            # Rate limiting delay
            if i < len(prompts) - 1:
                time.sleep(delay_between_requests)

        return responses

    def get_cost_summary(self) -> dict[str, Any]:
        """Get cumulative cost tracking summary."""
        return self.cost_tracker.summary()

    def reset_cost_tracker(self):
        """Reset cost tracking to zero."""
        self.cost_tracker = CostTracker()
        logger.info("Cost tracker reset")
