"""
Stage 1: Ingestion & Parsing.

Parses SEC filing HTML to create Document and Segment objects with stable XPath locators.

Key responsibilities:
- Parse HTML using lxml for 10x faster processing vs BeautifulSoup
- Generate stable XPath locators for every DOM element
- Detect and extract paragraphs, tables, images
- Apply V1 patterns: div-wrapper deduplication, table markers
- Extract ImageAsset objects with nearby text context
"""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from lxml import etree, html

from src.extraction_v2.models import (
    Document,
    ImageAsset,
    Segment,
    SegmentType,
    SectionType,
)

if TYPE_CHECKING:
    from src.extraction_v2 import pipeline

logger = logging.getLogger(__name__)


class IngestionStage:
    """
    Stage 1: Ingestion & Parsing.

    Parses HTML into Document and Segment objects with XPath locators.

    Pipeline responsibilities:
    - Read HTML from context.html_path
    - Create Document object with filing metadata
    - Extract segments (paragraphs, tables, images) with XPath locators
    - Populate context.document and context.segments
    """

    # V1 compatibility constants
    MIN_PARAGRAPH_CHARS = 50  # Minimum text length for paragraphs
    MAX_PARAGRAPH_CHARS = 10000  # Maximum text length for paragraphs

    def __init__(self) -> None:
        """Initialize the ingestion stage."""
        pass

    def _parse_html(self, html_path: Path) -> etree._Element | None:
        """
        Parse HTML file using lxml.

        Uses lxml for 10x faster parsing compared to BeautifulSoup.
        Handles malformed HTML gracefully using the HTML parser.

        Args:
            html_path: Path to HTML file

        Returns:
            Parsed lxml Element tree, or None if parsing fails
        """
        try:
            with open(html_path, "rb") as f:
                content = f.read()

            # Handle empty files
            if not content or len(content.strip()) == 0:
                logger.warning(f"Empty HTML file: {html_path}")
                # Return minimal valid HTML element
                return html.fromstring(b"<html><body></body></html>")

            # Use lxml.html.parse for better HTML handling (auto-fixes malformed HTML)
            try:
                root = html.fromstring(content)
                logger.debug(f"Successfully parsed HTML from {html_path}")
                return root
            except etree.ParseError as e:
                logger.error(f"lxml parse error for {html_path}: {e}")
                return None

        except FileNotFoundError:
            logger.error(f"HTML file not found: {html_path}")
            return None

        except Exception as e:
            logger.error(f"Unexpected error parsing HTML {html_path}: {e}")
            return None

    def _generate_xpath(self, element: etree._Element) -> str:
        """
        Generate a stable XPath locator for an element.

        Creates an absolute XPath using element positions within parent.
        Format: /html[1]/body[1]/div[2]/p[3]

        This XPath is stable across re-parsing of the same HTML document.

        Args:
            element: lxml Element to generate XPath for

        Returns:
            Absolute XPath string
        """
        # Build path from root to element
        path_parts: list[str] = []

        current = element
        while current is not None:
            # Get parent to calculate position
            parent = current.getparent()

            if parent is None:
                # Root element - just use tag name
                path_parts.insert(0, current.tag)
            else:
                # Count siblings of same type before this element
                tag = current.tag
                siblings_before = 0

                for sibling in parent:
                    if sibling is current:
                        break
                    if sibling.tag == tag:
                        siblings_before += 1

                # XPath positions are 1-indexed
                position = siblings_before + 1
                path_parts.insert(0, f"{tag}[{position}]")

            current = parent

        # Prepend / for absolute path
        return "/" + "/".join(path_parts)

    def _normalize_text(self, text: str) -> str:
        """
        Normalize text by collapsing whitespace.

        Args:
            text: Raw text content

        Returns:
            Normalized text with collapsed whitespace
        """
        # Replace multiple whitespace (including newlines) with single space
        import re
        normalized = re.sub(r'\s+', ' ', text)
        return normalized.strip()

    def _is_paragraph_element(self, element: etree._Element) -> bool:
        """
        Check if element should be treated as a paragraph.

        Paragraph elements: p, div, blockquote, pre, figure
        Skip elements nested in tables (handled separately).
        Skip divs that contain paragraph elements (extract children instead).

        Args:
            element: lxml Element to check

        Returns:
            True if element should be extracted as paragraph
        """
        # Check tag type
        if element.tag not in ('p', 'div', 'blockquote', 'pre', 'figure'):
            return False

        # Skip if nested inside a table
        parent = element.getparent()
        while parent is not None:
            if parent.tag == 'table':
                return False
            parent = parent.getparent()

        # Skip divs that contain paragraph elements (we'll extract the <p> tags instead)
        if element.tag == 'div':
            # Check if div contains any paragraph-like children
            for child in element:
                if child.tag in ('p', 'blockquote', 'pre', 'figure'):
                    return False

        return True

    def _should_skip_div_wrapper(self, div_element: etree._Element) -> bool:
        """
        Check if a div should be skipped because it only wraps a table.

        This implements V1 div-wrapper deduplication (Design Decision #16).
        Prevents duplicate extraction when a div contains ONLY a table with no additional text.
        The table will be extracted separately with correct type and markers.

        Args:
            div_element: A div element to check

        Returns:
            True if div should be skipped (contains only a table)
        """
        if div_element.tag != 'div':
            return False

        # Find all table children
        tables = div_element.xpath('.//table')
        if not tables:
            return False

        # Get text from div and from first table
        div_text = self._normalize_text(div_element.text_content() if hasattr(div_element, 'text_content') else '')
        table_text = self._normalize_text(tables[0].text_content() if hasattr(tables[0], 'text_content') else '')

        # If div text equals table text, the div adds nothing beyond the table
        return div_text == table_text

    def _extract_table_segments(
        self, tree: etree._Element, filing_id: int
    ) -> list[Segment]:
        """
        Extract table segments from HTML tree.

        Ports table detection logic from V1 html_segmenter.py:
        - Find <table> elements
        - Skip tables nested in divs that will be handled by div processing
        - Extract table text (markers will be added in AC-7)
        - Generate XPath locators

        Args:
            tree: Parsed lxml HTML tree
            filing_id: Filing ID for segment metadata

        Returns:
            List of table Segment objects
        """
        segments: list[Segment] = []
        sequence = 0

        # Find all table elements
        for element in tree.iter():
            if element.tag != 'table':
                continue

            # Skip if parent is a div that only wraps this table
            # The div wrapper will be skipped, so we extract the table directly
            parent = element.getparent()
            if parent is not None and parent.tag == 'div':
                if self._should_skip_div_wrapper(parent):
                    # This table is in a div-wrapper that will be skipped
                    # Extract the table directly
                    pass  # Continue to extract this table
                else:
                    # Parent div has additional content
                    # Check if this is a composite div (has both text and tables)
                    # For now, extract the table; composite handling is for AC-7
                    pass

            # Extract table text content (without markers for now)
            text_content = element.text_content() if hasattr(element, 'text_content') else ''
            normalized_text = self._normalize_text(text_content)

            # Skip empty tables
            if len(normalized_text) < self.MIN_PARAGRAPH_CHARS:
                continue

            # Generate XPath locator
            xpath = self._generate_xpath(element)

            # Create segment
            segment = Segment(
                segment_id=f"{filing_id}_tbl_{sequence}",
                segment_type=SegmentType.TABLE,
                sequence=sequence,
                text=normalized_text,  # AC-7 will add [ROW]/[CELL] markers
                dom_locator=xpath,
                section_type=SectionType.UNKNOWN,  # Will be classified in Stage 2
            )

            segments.append(segment)
            sequence += 1

        logger.info(f"Extracted {len(segments)} table segments from filing {filing_id}")
        return segments

    def _extract_paragraph_segments(
        self, tree: etree._Element, filing_id: int
    ) -> list[Segment]:
        """
        Extract paragraph segments from HTML tree.

        Ports paragraph detection logic from V1 html_segmenter.py:
        - Find text elements (p, div, blockquote, pre, figure)
        - Extract and normalize text content
        - Filter by min/max length (50-10000 chars)
        - Skip elements nested in tables
        - Skip div-wrappers (AC-6 deduplication)

        Args:
            tree: Parsed lxml HTML tree
            filing_id: Filing ID for segment metadata

        Returns:
            List of paragraph Segment objects
        """
        segments: list[Segment] = []
        sequence = 0

        # Find all potential paragraph elements
        # Using tree.iter() to traverse all elements in document order
        for element in tree.iter():
            if not self._is_paragraph_element(element):
                continue

            # AC-6: Skip div that only wraps a table (deduplication)
            if element.tag == 'div' and self._should_skip_div_wrapper(element):
                continue

            # Extract text content
            text_content = element.text_content() if hasattr(element, 'text_content') else ''
            normalized_text = self._normalize_text(text_content)

            # Apply length filters
            if len(normalized_text) < self.MIN_PARAGRAPH_CHARS:
                continue
            if len(normalized_text) > self.MAX_PARAGRAPH_CHARS:
                normalized_text = normalized_text[:self.MAX_PARAGRAPH_CHARS]

            # Generate XPath locator
            xpath = self._generate_xpath(element)

            # Create segment
            segment = Segment(
                segment_id=f"{filing_id}_seg_{sequence}",
                segment_type=SegmentType.PARAGRAPH,
                sequence=sequence,
                text=normalized_text,
                dom_locator=xpath,
                section_type=SectionType.UNKNOWN,  # Will be classified in Stage 2
            )

            segments.append(segment)
            sequence += 1

        logger.info(f"Extracted {len(segments)} paragraph segments from filing {filing_id}")
        return segments

    def process(self, context: pipeline.PipelineContext) -> pipeline.StageResult:
        """
        Parse HTML and generate segments with XPath locators.

        Args:
            context: Pipeline context with html_path and filing_id

        Returns:
            StageResult with processing metrics
        """
        # Import here to avoid circular import
        from src.extraction_v2.pipeline import PipelineStage, StageResult

        start_time = datetime.utcnow()
        errors: list[str] = []
        warnings: list[str] = []

        try:
            # Validate input
            if not context.html_path.exists():
                raise FileNotFoundError(f"HTML file not found: {context.html_path}")

            # AC-3: Parse HTML using lxml
            logger.info(f"Parsing HTML file: {context.html_path}")
            tree = self._parse_html(context.html_path)

            if tree is None:
                raise ValueError(f"Failed to parse HTML from {context.html_path}")

            # AC-5: Port paragraph detection from V1
            logger.info(f"Extracting paragraph segments from filing {context.filing_id}")
            paragraph_segments = self._extract_paragraph_segments(tree, context.filing_id)

            # AC-6: Port table detection with div-wrapper deduplication
            logger.info(f"Extracting table segments from filing {context.filing_id}")
            table_segments = self._extract_table_segments(tree, context.filing_id)

            # TODO (AC-7): Add [CELL] and [ROW] markers
            # TODO (AC-8): Port definition/methodology block detection
            # TODO (AC-9): Extract ImageAsset objects with context
            # TODO (AC-10): Create Segment objects (combine all segment types)

            # AC-11: Create Document object
            doc = Document(
                doc_id=str(context.filing_id),
                html_path=str(context.html_path),
            )
            context.document = doc

            # AC-10: Combine all segment types
            all_segments = paragraph_segments + table_segments
            # Sort by sequence to maintain document order
            # Note: Currently using separate sequences per type; will need unified sequencing
            context.segments = all_segments

            duration_ms = int((datetime.utcnow() - start_time).total_seconds() * 1000)

            return StageResult(
                stage=PipelineStage.INGESTION,
                success=True,
                duration_ms=duration_ms,
                items_processed=1,  # 1 HTML file
                items_output=len(context.segments),
                errors=errors,
                warnings=warnings,
                metadata={
                    "html_path": str(context.html_path),
                    "segment_count": len(context.segments),
                    "image_count": len(context.images),
                },
            )

        except Exception as e:
            logger.exception(f"Ingestion stage failed: {e}")
            duration_ms = int((datetime.utcnow() - start_time).total_seconds() * 1000)
            return StageResult(
                stage=PipelineStage.INGESTION,
                success=False,
                duration_ms=duration_ms,
                items_processed=0,
                items_output=0,
                errors=[str(e)],
                warnings=warnings,
            )
