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

    def __init__(self) -> None:
        """Initialize the ingestion stage."""
        self.min_paragraph_chars = 50  # Port from V1
        self.max_paragraph_chars = 10000  # Port from V1

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

            # TODO (AC-4): Generate stable XPath locators
            # TODO (AC-5): Port paragraph detection from V1
            # TODO (AC-6): Port table detection with div-wrapper deduplication
            # TODO (AC-7): Add [CELL] and [ROW] markers
            # TODO (AC-8): Port definition/methodology block detection
            # TODO (AC-9): Extract ImageAsset objects with context
            # TODO (AC-10): Create Segment objects
            # TODO (AC-11): Create Document object

            # Placeholder implementation
            doc = Document(
                doc_id=str(context.filing_id),
                html_path=str(context.html_path),
            )
            context.document = doc

            # Placeholder: empty segments list
            context.segments = []

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
