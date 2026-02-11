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
import re
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from lxml import etree, html

from src.extraction_v2.models import (
    Document,
    ImageAsset,
    ImageClassification,
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

    # Image detection constants (ported from V1)
    IMAGE_CONTEXT_CHARS = 500  # Characters to extract before/after image
    MIN_IMAGE_WIDTH = 100  # Minimum width for non-decorative images
    MIN_IMAGE_HEIGHT = 100  # Minimum height for non-decorative images

    # Definition/methodology detection patterns (ported from V1)
    DEFINITION_PATTERNS = [
        r"\b(we\s+define|defined\s+as|definition\s+of|refers\s+to)\b",
        r"\b(means|meaning|metric\s+definitions)\b",
    ]

    METHODOLOGY_PATTERNS = [
        r"\b(calculated\s+as|calculated\s+by|calculation|computed\s+as)\b",
        r"\b(determined\s+by|formula|methodology)\b",
    ]

    # Decorative image patterns (ported from V1)
    DECORATIVE_IMAGE_PATTERNS = [
        r'\blogo\b',
        r'\bicon\b',
        r'\bbullet\b',
        r'\bbanner\b',
        r'\bheader\b',
        r'\bfooter\b',
    ]

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
        normalized = re.sub(r'\s+', ' ', text)
        return normalized.strip()

    def _get_element_position(self, tree: etree._Element, element: etree._Element) -> int:
        """
        Get position of element in document order.

        Args:
            tree: Root tree element
            element: Element to find position for

        Returns:
            Position index in document order (0-based)
        """
        # Build a list of all elements in tree order
        all_elements = list(tree.iter())
        try:
            return all_elements.index(element)
        except ValueError:
            # Element not found in tree - should not happen
            logger.warning(f"Element not found in tree: {element.tag}")
            return 0

    def _matches_patterns(self, text: str, patterns: list[str]) -> bool:
        """
        Check if text matches any of the given regex patterns.

        Args:
            text: Text to check
            patterns: List of regex patterns to match

        Returns:
            True if text matches any pattern
        """
        if not text:
            return False

        text_lower = text.lower()
        for pattern in patterns:
            if re.search(pattern, text_lower, re.IGNORECASE):
                return True
        return False

    def _classify_segment_type(self, text: str, element_tag: str) -> SegmentType:
        """
        Classify segment type based on text content.

        Detects definition blocks and methodology blocks based on V1 patterns.

        Args:
            text: Normalized text content
            element_tag: HTML tag name (for context)

        Returns:
            SegmentType enum value
        """
        # Check for definition blocks
        if self._matches_patterns(text, self.DEFINITION_PATTERNS):
            return SegmentType.DEFINITION

        # Check for methodology blocks
        if self._matches_patterns(text, self.METHODOLOGY_PATTERNS):
            return SegmentType.METHODOLOGY

        # Default based on element tag
        if element_tag == 'table':
            return SegmentType.TABLE
        else:
            return SegmentType.PARAGRAPH

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

    def _extract_table_text_with_markers(self, table_element: etree._Element) -> str:
        """
        Extract table text with cell/row boundary markers.

        Preserves table cell boundaries by adding [CELL] and [ROW] markers
        during HTML-to-text conversion. This prevents adjacent numeric values
        from merging together when table structure is lost.

        Args:
            table_element: lxml Element (table or element containing table)

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
            table = table_element if table_element.tag == 'table' else table_element.xpath('.//table')[0] if table_element.xpath('.//table') else None

            if table is None:
                # No table found - fall back to standard normalization
                logger.debug("No table found in element, using standard normalization")
                return self._normalize_text(table_element.text_content() if hasattr(table_element, 'text_content') else '')

            # Extract rows and cells
            row_texts: list[str] = []

            # Find all rows (tr elements)
            rows = table.xpath('.//tr')

            for row in rows:
                # Find all cells in this row (both td and th)
                cells = row.xpath('./td | ./th')

                if not cells:
                    # Empty row - skip
                    continue

                # Extract and normalize text from each cell
                cell_texts = []
                for cell in cells:
                    cell_text = self._normalize_text(cell.text_content() if hasattr(cell, 'text_content') else '')
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
            return self._normalize_text(table_element.text_content() if hasattr(table_element, 'text_content') else '')

    def _extract_table_segments_with_elements(
        self, tree: etree._Element, filing_id: int
    ) -> list[tuple[Segment, etree._Element]]:
        """
        Extract table segments from HTML tree (internal method with elements).

        Ports table detection logic from V1 html_segmenter.py:
        - Find <table> elements
        - Skip tables nested in divs that will be handled by div processing
        - Extract table text (markers will be added in AC-7)
        - Generate XPath locators

        Args:
            tree: Parsed lxml HTML tree
            filing_id: Filing ID for segment metadata

        Returns:
            List of (Segment, Element) tuples for document-order sorting
        """
        segments: list[tuple[Segment, etree._Element]] = []

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

            # AC-7: Extract table text with [CELL] and [ROW] markers
            normalized_text = self._extract_table_text_with_markers(element)

            # Skip empty tables
            if len(normalized_text) < self.MIN_PARAGRAPH_CHARS:
                continue

            # Generate XPath locator
            xpath = self._generate_xpath(element)

            # Convert element to HTML string for table reconstruction
            raw_html = etree.tostring(element, encoding='unicode', method='html')

            # Create segment (sequence will be assigned after sorting)
            segment = Segment(
                segment_type=SegmentType.TABLE,
                sequence=0,  # Will be updated after sorting
                text=normalized_text,  # Has [ROW]/[CELL] markers for row-aware matching
                raw_html=raw_html,  # Original HTML for table reconstruction
                dom_locator=xpath,
                section_type=SectionType.UNKNOWN,  # Will be classified in Stage 2
            )

            segments.append((segment, element))

        logger.info(f"Extracted {len(segments)} table segments from filing {filing_id}")
        return segments

    def _extract_table_segments(
        self, tree: etree._Element, filing_id: int
    ) -> list[Segment]:
        """
        Extract table segments from HTML tree.

        Public method for testing. Returns segments with sequential numbering.

        Args:
            tree: Parsed lxml HTML tree
            filing_id: Filing ID for segment metadata

        Returns:
            List of Segment objects
        """
        segments_with_elements = self._extract_table_segments_with_elements(tree, filing_id)
        # Assign sequence numbers and extract just segments
        for idx, (segment, _) in enumerate(segments_with_elements):
            segment.sequence = idx
        return [seg for seg, _ in segments_with_elements]

    def _extract_paragraph_segments_with_elements(
        self, tree: etree._Element, filing_id: int
    ) -> list[tuple[Segment, etree._Element]]:
        """
        Extract paragraph segments from HTML tree (internal method with elements).

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
            List of (Segment, Element) tuples for document-order sorting
        """
        segments: list[tuple[Segment, etree._Element]] = []

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

            # Convert element to HTML string
            raw_html = etree.tostring(element, encoding='unicode', method='html')

            # AC-8: Classify segment type (detects definition/methodology blocks)
            segment_type = self._classify_segment_type(normalized_text, element.tag)

            # Create segment (sequence will be assigned after sorting)
            segment = Segment(
                segment_type=segment_type,
                sequence=0,  # Will be updated after sorting
                text=normalized_text,
                raw_html=raw_html,  # Original HTML
                dom_locator=xpath,
                section_type=SectionType.UNKNOWN,  # Will be classified in Stage 2
            )

            segments.append((segment, element))

        logger.info(f"Extracted {len(segments)} paragraph segments from filing {filing_id}")
        return segments

    def _extract_paragraph_segments(
        self, tree: etree._Element, filing_id: int
    ) -> list[Segment]:
        """
        Extract paragraph segments from HTML tree.

        Public method for testing. Returns segments with sequential numbering.

        Args:
            tree: Parsed lxml HTML tree
            filing_id: Filing ID for segment metadata

        Returns:
            List of Segment objects
        """
        segments_with_elements = self._extract_paragraph_segments_with_elements(tree, filing_id)
        # Assign sequence numbers and extract just segments
        for idx, (segment, _) in enumerate(segments_with_elements):
            segment.sequence = idx
        return [seg for seg, _ in segments_with_elements]

    def _is_decorative_image(self, img_element: etree._Element) -> bool:
        """
        Check if image is likely decorative (logo, icon, bullet, etc.).

        Uses size and naming patterns to filter out non-content images.

        Args:
            img_element: Image element to check

        Returns:
            True if image is likely decorative
        """
        # Check src attribute for decorative patterns
        src = img_element.get('src', '').lower()
        for pattern_str in self.DECORATIVE_IMAGE_PATTERNS:
            pattern = re.compile(pattern_str, re.IGNORECASE)
            if pattern.search(src):
                return True

        # Check width/height attributes
        try:
            width_str = img_element.get('width', '')
            height_str = img_element.get('height', '')

            if width_str and width_str.isdigit():
                width = int(width_str)
                if width < self.MIN_IMAGE_WIDTH:
                    return True

            if height_str and height_str.isdigit():
                height = int(height_str)
                if height < self.MIN_IMAGE_HEIGHT:
                    return True
        except (ValueError, TypeError):
            pass

        return False

    def _get_nearby_text(self, img_element: etree._Element, tree: etree._Element) -> str:
        """
        Extract text near an image element.

        Collects text from:
        - Caption (figcaption, nearby spans/divs)
        - Surrounding paragraphs (previous and next siblings)

        Args:
            img_element: Image element to get context for
            tree: Full HTML tree

        Returns:
            Nearby text (caption + context)
        """
        nearby_parts: list[str] = []

        # 1. Look for caption in parent figure element
        parent = img_element.getparent()
        if parent is not None and parent.tag == 'figure':
            # Find figcaption
            captions = parent.xpath('.//figcaption')
            for caption in captions:
                text = caption.text_content() if hasattr(caption, 'text_content') else ''
                text = self._normalize_text(text)
                if text:
                    nearby_parts.append(text)

        # 2. Get context from nearby siblings
        # Get parent element (or use tree root if img is at top level)
        context_root = parent if parent is not None else tree

        # Get previous siblings (up to 2)
        if parent is not None:
            prev_siblings: list[str] = []
            current = img_element.getprevious()
            count = 0
            while current is not None and count < 2:
                if current.tag in ('p', 'div', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6'):
                    text = current.text_content() if hasattr(current, 'text_content') else ''
                    text = self._normalize_text(text)
                    if text:
                        prev_siblings.insert(0, text)
                        count += 1
                current = current.getprevious()

            nearby_parts.extend(prev_siblings)

        # 3. Get next siblings (up to 2)
        if parent is not None:
            next_siblings: list[str] = []
            current = img_element.getnext()
            count = 0
            while current is not None and count < 2:
                if current.tag in ('p', 'div', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6'):
                    text = current.text_content() if hasattr(current, 'text_content') else ''
                    text = self._normalize_text(text)
                    if text:
                        next_siblings.append(text)
                        count += 1
                current = current.getnext()

            nearby_parts.extend(next_siblings)

        # 4. Fallback: if no text found and img is only child of parent (e.g. <P><IMG/></P>),
        # walk up to parent and check parent's siblings for context
        if not nearby_parts and parent is not None:
            _block_tags = ('p', 'div', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6')

            # Check parent's previous siblings (up to 2)
            parent_prev: list[str] = []
            current = parent.getprevious()
            count = 0
            while current is not None and count < 2:
                if current.tag in _block_tags:
                    text = current.text_content() if hasattr(current, 'text_content') else ''
                    text = self._normalize_text(text)
                    if text:
                        parent_prev.insert(0, text)
                        count += 1
                current = current.getprevious()
            nearby_parts.extend(parent_prev)

            # Check parent's next siblings (up to 2)
            parent_next: list[str] = []
            current = parent.getnext()
            count = 0
            while current is not None and count < 2:
                if current.tag in _block_tags:
                    text = current.text_content() if hasattr(current, 'text_content') else ''
                    text = self._normalize_text(text)
                    if text:
                        parent_next.append(text)
                        count += 1
                current = current.getnext()
            nearby_parts.extend(parent_next)

        # Combine all parts
        return ' '.join(nearby_parts)

    def _compute_initial_relevance(self, nearby_text: str, filename: str) -> float:
        """
        Compute initial relevance score for an image.

        Based on:
        - Metric keyword proximity (chart, table, cohort, retention, etc.)
        - Filename indicators

        Args:
            nearby_text: Text near the image
            filename: Image filename/src

        Returns:
            Relevance score (0-1)
        """
        score = 0.0

        # Base score for having any content
        if nearby_text:
            score = 0.1

        # Check for metric-related keywords in nearby text
        text_lower = nearby_text.lower()
        filename_lower = filename.lower()

        # High-value keywords (from V1 cohort detection)
        high_value_keywords = [
            'cohort', 'retention', 'churn', 'ltv', 'cac',
            'arr', 'mrr', 'revenue', 'growth', 'customers'
        ]

        for keyword in high_value_keywords:
            if keyword in text_lower:
                score += 0.15
            if keyword in filename_lower:
                score += 0.1

        # Chart/table indicators
        chart_keywords = ['chart', 'graph', 'figure', 'table', 'exhibit']
        for keyword in chart_keywords:
            if keyword in text_lower:
                score += 0.1
                break

        # Cap at 1.0
        return min(1.0, score)

    def _extract_image_assets(
        self, tree: etree._Element, filing_id: int
    ) -> list[ImageAsset]:
        """
        Extract ImageAsset objects from HTML tree.

        Finds <img> tags and extracts:
        - Image metadata (src, dimensions)
        - Nearby text (caption + context)
        - Initial relevance score
        - XPath locator

        Filters out decorative images (logos, icons, bullets).

        Args:
            tree: Parsed lxml HTML tree
            filing_id: Filing ID for asset metadata

        Returns:
            List of ImageAsset objects
        """
        assets: list[ImageAsset] = []
        sequence = 0

        # Find all img elements
        for element in tree.iter():
            if element.tag != 'img':
                continue

            # Filter decorative images
            if self._is_decorative_image(element):
                continue

            # Get image attributes
            src = element.get('src', '')
            if not src:
                continue

            # Get dimensions (if available)
            width = 0
            height = 0
            try:
                width_str = element.get('width', '0')
                height_str = element.get('height', '0')
                if width_str.isdigit():
                    width = int(width_str)
                if height_str.isdigit():
                    height = int(height_str)
            except (ValueError, TypeError):
                pass

            # Generate XPath locator
            xpath = self._generate_xpath(element)

            # Extract nearby text
            nearby_text = self._get_nearby_text(element, tree)

            # Compute initial relevance score
            relevance = self._compute_initial_relevance(nearby_text, src)

            # Create ImageAsset
            asset = ImageAsset(
                doc_id=str(filing_id),
                filename=src,
                width=width,
                height=height,
                dom_locator=xpath,
                nearby_text=nearby_text,
                section_type=SectionType.UNKNOWN,  # Will be classified in Stage 2
                classification=ImageClassification.UNKNOWN,  # Will be classified in Stage 4
                relevance_score=relevance,
            )

            assets.append(asset)
            sequence += 1

        logger.info(f"Extracted {len(assets)} image assets from filing {filing_id}")
        return assets

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
            paragraph_segments_with_elements = self._extract_paragraph_segments_with_elements(tree, context.filing_id)

            # AC-6: Port table detection with div-wrapper deduplication
            logger.info(f"Extracting table segments from filing {context.filing_id}")
            table_segments_with_elements = self._extract_table_segments_with_elements(tree, context.filing_id)

            # AC-8: Definition/methodology detection integrated into paragraph extraction
            # AC-9: Extract ImageAsset objects with context
            logger.info(f"Extracting image assets from filing {context.filing_id}")
            image_assets = self._extract_image_assets(tree, context.filing_id)

            # AC-10: Combine all segment types and sort by document order
            all_segments_with_elements = paragraph_segments_with_elements + table_segments_with_elements

            # Sort by tree position to maintain document order
            # lxml elements can be compared for document order using < operator
            all_segments_with_elements.sort(key=lambda x: self._get_element_position(tree, x[1]))

            # Assign unified sequence numbers
            for idx, (segment, _) in enumerate(all_segments_with_elements):
                segment.sequence = idx
                segment.doc_id = str(context.filing_id)  # Ensure doc_id is set

            # Extract just the segments
            all_segments = [seg for seg, _ in all_segments_with_elements]

            context.segments = all_segments

            # AC-11: Create Document object with filing_id as doc_id
            doc = Document(
                doc_id=str(context.filing_id),
                html_path=str(context.html_path),
            )
            context.document = doc

            # Store image assets in context
            context.images = image_assets

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
