"""
Stage 5: OCR & Chart Extraction.

Processes high-relevance images to extract structured data:
- TABLE_IMAGE: Run OCR to extract text, then reconstruct into Table object
- CHART: Use vision model to extract labeled data values (never interpolate)

Design principle: "Charts only when labeled" - extract ONLY explicit data labels
shown on charts, never interpolate values from axis positions.

Key responsibilities:
- Process images with relevance_score >= MIN_RELEVANCE_FOR_PROCESSING
- Extract table structures via OCR API
- Extract chart data via vision model (labeled values only)
- Set confidence scores and manual capture flags
- Track API costs and respect limits
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import TYPE_CHECKING

from src.extraction_v2.models import (
    Cell,
    ImageAsset,
    ImageClassification,
    Table,
)

if TYPE_CHECKING:
    from src.extraction_v2 import pipeline

logger = logging.getLogger(__name__)


class OCRExtractionStage:
    """
    Stage 5: OCR & Chart Extraction - process high-relevance images.

    Pipeline responsibilities:
    - Process images with relevance_score >= threshold
    - Extract table structures from TABLE_IMAGE via OCR
    - Extract chart data from CHART via vision model
    - Set processed=True and confidence after extraction
    - Mark low-confidence results for manual capture
    - Track API costs and respect limits
    """

    # Processing thresholds
    MIN_RELEVANCE_FOR_PROCESSING: float = 0.3  # Must match ImageTriageStage
    OCR_CONFIDENCE_THRESHOLD: float = 0.5  # Below this, mark for manual

    # Cost control limits (per document)
    MAX_OCR_CALLS_PER_DOCUMENT: int = 20
    MAX_CHART_CALLS_PER_DOCUMENT: int = 10

    def __init__(self, vision_client: object | None = None) -> None:
        """
        Initialize the OCR extraction stage.

        Args:
            vision_client: Optional vision API client (OpenAI Vision).
                          If None, will be created on first use.
        """
        self._vision_client = vision_client
        self._api_call_count = 0
        self._ocr_call_count = 0
        self._chart_call_count = 0

    @property
    def vision_client(self) -> object:
        """Lazy-load vision client to avoid import errors in tests."""
        if self._vision_client is None:
            # Import here to avoid circular dependency
            from src.extraction_v2.vision_client import OpenAIVisionClient

            self._vision_client = OpenAIVisionClient()
        return self._vision_client

    def _should_process(self, asset: ImageAsset) -> bool:
        """
        Determine if image should be processed.

        Args:
            asset: Image to check

        Returns:
            True if should be processed
        """
        # Skip if already processed
        if asset.processed:
            return False

        # Skip if below relevance threshold
        if asset.relevance_score < self.MIN_RELEVANCE_FOR_PROCESSING:
            return False

        # Skip decorative/logo/signature
        if asset.classification in {
            ImageClassification.DECORATIVE,
            ImageClassification.LOGO,
            ImageClassification.SIGNATURE,
        }:
            return False

        # Skip if no file path
        if not asset.file_path:
            logger.warning(f"Image {asset.img_id} has no file_path, skipping")
            return False

        return True

    def process_table_image(self, asset: ImageAsset) -> None:
        """
        Extract table from image using OCR.

        Steps:
        1. Load image file as bytes
        2. Call Vision API with table extraction prompt
        3. Parse OCR response into cells
        4. Use TableReconstructor to build Table object
        5. Compute confidence from OCR quality signals
        6. Set requires_manual_capture if confidence is low

        Args:
            asset: Image asset to process (modified in place)

        Raises:
            FileNotFoundError: If image file doesn't exist
            ValueError: If API returns invalid response
        """
        import json
        from pathlib import Path

        from src.llm.vision_client import VisionClient

        # Validate file path
        if not asset.file_path:
            raise ValueError(f"Image {asset.img_id} has no file_path")

        image_path = Path(asset.file_path)
        if not image_path.exists():
            raise FileNotFoundError(f"Image file not found: {asset.file_path}")

        # Load image bytes
        image_bytes = image_path.read_bytes()

        # Call Vision API with table extraction prompt
        vision_client = self.vision_client
        if not isinstance(vision_client, VisionClient):
            # Create VisionClient if mock was provided
            vision_client = VisionClient()

        try:
            response = vision_client.analyze_image(
                image_bytes=image_bytes,
                prompt=self._get_table_extraction_prompt(),
                detail="high",  # High detail for accurate OCR
                max_tokens=2000,
            )

            # Parse JSON response
            try:
                ocr_data = json.loads(response.content)
            except json.JSONDecodeError as e:
                logger.error(f"Failed to parse OCR response as JSON: {e}")
                logger.debug(f"Response content: {response.content[:500]}")
                # Fallback: store raw text but mark for manual capture
                asset.ocr_text = response.content
                asset.processed = True
                asset.confidence = 0.0
                asset.requires_manual_capture = True
                return

            # Store raw OCR text
            asset.ocr_text = ocr_data.get("raw_text", "")

            # Reconstruct table from cells
            cells_data = ocr_data.get("cells", [])
            if not cells_data:
                logger.warning(f"No cells found in OCR response for {asset.img_id}")
                asset.processed = True
                asset.confidence = 0.0
                asset.requires_manual_capture = True
                return

            # Build table from OCR cells
            table = self._reconstruct_table_from_ocr(cells_data)
            asset.ocr_table = table

            # Compute confidence from OCR quality signals
            confidence = ocr_data.get("confidence", 0.5)
            asset.confidence = float(confidence)

            # Mark for manual capture if confidence is low
            if asset.confidence < self.OCR_CONFIDENCE_THRESHOLD:
                asset.requires_manual_capture = True
                logger.info(
                    f"Table {asset.img_id} marked for manual capture (confidence={asset.confidence:.2f})"
                )

            asset.processed = True
            logger.info(
                f"Processed table image {asset.img_id}: {table.row_count}x{table.col_count} cells, "
                f"confidence={asset.confidence:.2f}"
            )

        except Exception as e:
            logger.error(f"Error during OCR for {asset.img_id}: {e}", exc_info=True)
            asset.processed = True
            asset.confidence = 0.0
            asset.requires_manual_capture = True
            raise

    def _get_table_extraction_prompt(self) -> str:
        """
        Get the prompt for table extraction via OCR.

        Returns:
            Prompt string for Vision API
        """
        return """Analyze this table image and extract all cell contents.

Return a JSON object with:
- raw_text: Full OCR text of the table (string)
- confidence: Overall OCR confidence 0.0-1.0 (float)
- cells: Array of cell objects, each with:
  - row: 0-indexed row number (int)
  - col: 0-indexed column number (int)
  - text: cell content as string
  - is_header: true if this appears to be a header cell (boolean)

CRITICAL RULES:
1. Focus on accuracy over completeness. If text is unclear, mark confidence as low.
2. Maintain table structure: ensure row/col indices are consistent.
3. Empty cells should have empty string text ("").
4. Numbers should be preserved exactly as shown (with commas, decimals, etc).
5. Header cells are typically in the first row(s) or use bold/different styling.

Example JSON:
{
  "raw_text": "Year Revenue\\n2021 $1.2B\\n2022 $1.5B",
  "confidence": 0.95,
  "cells": [
    {"row": 0, "col": 0, "text": "Year", "is_header": true},
    {"row": 0, "col": 1, "text": "Revenue", "is_header": true},
    {"row": 1, "col": 0, "text": "2021", "is_header": false},
    {"row": 1, "col": 1, "text": "$1.2B", "is_header": false}
  ]
}
"""

    def _reconstruct_table_from_ocr(self, cells_data: list[dict[str, object]]) -> Table:
        """
        Reconstruct Table object from OCR cell data.

        Args:
            cells_data: List of cell dicts with row, col, text, is_header

        Returns:
            Table object with normalized structure
        """

        from src.extraction_v2.models import Cell, Table

        # Determine grid dimensions
        if not cells_data:
            return Table(
                row_count=0,
                col_count=0,
                header_rows=0,
                stub_cols=0,
                cells=[],
                _grid=[],
            )

        # Helper to safely extract int from cell data
        def get_int(data: dict[str, object], key: str, default: int = 0) -> int:
            val = data.get(key, default)
            if isinstance(val, int):
                return val
            if isinstance(val, (float, str)):
                try:
                    return int(val)
                except (ValueError, TypeError):
                    return default
            return default

        # Find max row/col
        max_row = max(get_int(cell, "row") for cell in cells_data)
        max_col = max(get_int(cell, "col") for cell in cells_data)
        row_count = max_row + 1
        col_count = max_col + 1

        # Initialize grid
        grid: list[list[Cell | None]] = [[None] * col_count for _ in range(row_count)]

        # Create Cell objects and populate grid
        cells: list[Cell] = []
        for cell_data in cells_data:
            row = get_int(cell_data, "row")
            col = get_int(cell_data, "col")
            text = str(cell_data.get("text", ""))
            is_header = bool(cell_data.get("is_header", False))

            cell = Cell(
                row=row,
                col=col,
                text=text,
                is_header=is_header,
                rowspan=1,  # OCR doesn't detect spans
                colspan=1,
            )
            cells.append(cell)
            grid[cell.row][cell.col] = cell

        # Detect header rows (first N rows where majority are marked is_header)
        header_rows = 0
        for grid_row in grid:
            unique_cells = [c for c in grid_row if c is not None]
            if not unique_cells:
                break
            header_count = sum(1 for c in unique_cells if c.is_header)
            if header_count > len(unique_cells) * 0.5:
                header_rows += 1
            else:
                break
        header_rows = max(1, header_rows)  # At least 1

        # Detect stub cols (first N cols where majority are text, not numbers)
        stub_cols = 1  # Default to 1 for OCR tables

        # Mark cells as header/stub based on detected regions
        seen_cells: set[int] = set()
        for row_idx, grid_row2 in enumerate(grid):
            for col_idx, cell_maybe in enumerate(grid_row2):
                if cell_maybe and id(cell_maybe) not in seen_cells:
                    if row_idx < header_rows:
                        cell_maybe.is_header = True
                    if col_idx < stub_cols:
                        cell_maybe.is_stub = True
                    seen_cells.add(id(cell_maybe))

        # Compute header_path and stub_path for each cell
        for cell in cells:
            # Header path: column headers
            header_path: list[str] = []
            for h_row in range(header_rows):
                h_cell = grid[h_row][cell.col]
                if h_cell and h_cell.text.strip():
                    if not header_path or header_path[-1] != h_cell.text.strip():
                        header_path.append(h_cell.text.strip())
            cell.header_path = header_path

            # Stub path: row stubs
            stub_path: list[str] = []
            for s_col in range(stub_cols):
                s_cell = grid[cell.row][s_col]
                if s_cell and s_cell.text.strip():
                    if not stub_path or stub_path[-1] != s_cell.text.strip():
                        stub_path.append(s_cell.text.strip())
            cell.stub_path = stub_path

        return Table(
            row_count=row_count,
            col_count=col_count,
            header_rows=header_rows,
            stub_cols=stub_cols,
            cells=cells,
            _grid=grid,
        )

    def process_chart(self, asset: ImageAsset) -> None:
        """
        Extract labeled values from chart.

        CRITICAL: Only extract values that are EXPLICITLY labeled on the chart.
        Never interpolate values from axis positions.

        Placeholder for AC-3 implementation.

        Args:
            asset: Image asset to process (modified in place)
        """
        # TODO: AC-3 - Implement chart extraction
        logger.info(f"Processing chart {asset.img_id} (not implemented)")
        asset.processed = True
        asset.confidence = 0.0
        asset.requires_manual_capture = True

    def process(self, context: pipeline.PipelineContext) -> pipeline.StageResult:
        """
        Process high-relevance images with OCR/Vision.

        Modifies context.images in place, setting:
        - ocr_text/ocr_table for TABLE_IMAGE
        - chart_data for CHART
        - processed=True
        - confidence scores
        - requires_manual_capture flags

        Args:
            context: Pipeline context with images list

        Returns:
            StageResult with extraction counts and metadata
        """
        # Import here to avoid circular import
        from src.extraction_v2.pipeline import PipelineStage, StageResult

        start_time = datetime.utcnow()
        errors: list[str] = []
        warnings: list[str] = []

        # Reset API call counters for this document
        self._api_call_count = 0
        self._ocr_call_count = 0
        self._chart_call_count = 0

        processed_count = 0
        skipped_count = 0
        manual_capture_count = 0

        try:
            # Handle empty images list
            if not context.images:
                logger.info("No images to process")
                duration_ms = int((datetime.utcnow() - start_time).total_seconds() * 1000)
                return StageResult(
                    stage=PipelineStage.OCR_CHART_EXTRACTION,
                    success=True,
                    duration_ms=duration_ms,
                    items_processed=0,
                    items_output=0,
                    errors=errors,
                    warnings=warnings,
                    metadata={"message": "No images to process"},
                )

            # Process each relevant image
            for asset in context.images:
                # Check if should process
                if not self._should_process(asset):
                    skipped_count += 1
                    continue

                # Check API call limits
                if asset.classification == ImageClassification.TABLE_IMAGE:
                    if self._ocr_call_count >= self.MAX_OCR_CALLS_PER_DOCUMENT:
                        msg = f"OCR call limit ({self.MAX_OCR_CALLS_PER_DOCUMENT}) reached"
                        warnings.append(msg)
                        logger.warning(msg)
                        break
                elif asset.classification == ImageClassification.CHART:
                    if self._chart_call_count >= self.MAX_CHART_CALLS_PER_DOCUMENT:
                        msg = f"Chart call limit ({self.MAX_CHART_CALLS_PER_DOCUMENT}) reached"
                        warnings.append(msg)
                        logger.warning(msg)
                        break

                # Process based on classification
                try:
                    if asset.classification == ImageClassification.TABLE_IMAGE:
                        self.process_table_image(asset)
                        self._ocr_call_count += 1
                    elif asset.classification == ImageClassification.CHART:
                        self.process_chart(asset)
                        self._chart_call_count += 1
                    else:
                        # Unknown type - skip
                        logger.debug(f"Skipping image {asset.img_id} with classification {asset.classification}")
                        skipped_count += 1
                        continue

                    self._api_call_count += 1
                    processed_count += 1

                    if asset.requires_manual_capture:
                        manual_capture_count += 1

                except Exception as e:
                    # Log error but continue processing other images
                    error_msg = f"Error processing {asset.img_id}: {str(e)}"
                    errors.append(error_msg)
                    logger.error(error_msg, exc_info=True)

                    # Mark for manual capture
                    asset.requires_manual_capture = True
                    asset.processed = True
                    asset.confidence = 0.0
                    manual_capture_count += 1

            duration_ms = int((datetime.utcnow() - start_time).total_seconds() * 1000)

            return StageResult(
                stage=PipelineStage.OCR_CHART_EXTRACTION,
                success=len(errors) == 0,
                duration_ms=duration_ms,
                items_processed=processed_count,
                items_output=processed_count,
                errors=errors,
                warnings=warnings,
                metadata={
                    "ocr_calls": self._ocr_call_count,
                    "chart_calls": self._chart_call_count,
                    "total_api_calls": self._api_call_count,
                    "manual_capture_count": manual_capture_count,
                    "skipped_count": skipped_count,
                },
            )

        except Exception as e:
            # Catastrophic error - fail the stage
            error_msg = f"OCR extraction stage failed: {str(e)}"
            errors.append(error_msg)
            logger.error(error_msg, exc_info=True)

            duration_ms = int((datetime.utcnow() - start_time).total_seconds() * 1000)

            return StageResult(
                stage=PipelineStage.OCR_CHART_EXTRACTION,
                success=False,
                duration_ms=duration_ms,
                items_processed=processed_count,
                items_output=processed_count,
                errors=errors,
                warnings=warnings,
                metadata={
                    "ocr_calls": self._ocr_call_count,
                    "chart_calls": self._chart_call_count,
                    "total_api_calls": self._api_call_count,
                    "manual_capture_count": manual_capture_count,
                    "skipped_count": skipped_count,
                },
            )
