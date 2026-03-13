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
import os
import re
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from src.extraction_v2.chart_prompts import get_classification_prompt, get_pass2_prompt
from src.extraction_v2.exceptions import V2FatalError
from src.extraction_v2.models import (
    Cell,
    ChartAnnotation,
    ChartClassificationResult,
    ImageAsset,
    ImageClassification,
    ImageExtractionMeta,
    Table,
)

if TYPE_CHECKING:
    from src.extraction_v2 import pipeline

logger = logging.getLogger(__name__)

_DEFAULT_IMAGE_CACHE_DIR = "data/image_cache"


def _image_cache_base_dir() -> Path:
    """Return the base directory for caching downloaded filing images.

    Defaults to data/image_cache/ relative to the working directory.
    Override with FILINGS_IMAGE_CACHE_DIR environment variable.
    """
    env_val = os.environ.get("FILINGS_IMAGE_CACHE_DIR", "").strip()
    return Path(env_val) if env_val else Path(_DEFAULT_IMAGE_CACHE_DIR)


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
    MAX_CHART_CALLS_PER_DOCUMENT: int = 20  # 10 charts x 2 passes (Pass 1 + Pass 2)

    def __init__(
        self,
        vision_client: object | None = None,
        sec_client: object | None = None,
        config: Any | None = None,
    ) -> None:
        """
        Initialize the OCR extraction stage.

        Args:
            vision_client: Optional vision API client (injected for testing).
                          If None, will be created on first use via factory.
            sec_client: Optional SECClient instance for image downloading.
                       If None, will be created on first use when needed.
            config: Optional PipelineConfig for provider selection.
                   If None, defaults to OpenAI provider.
        """
        self._vision_client = vision_client
        self._sec_client = sec_client
        self._config = config
        self._api_call_count = 0
        self._ocr_call_count = 0
        self._chart_call_count = 0

    @property
    def vision_client(self) -> Any:
        """Lazy-load vision client via factory using config provider settings."""
        if self._vision_client is None:
            from src.llm.vision_factory import create_vision_provider

            provider = "openai"
            model: str | None = None
            if self._config is not None:
                provider = getattr(self._config, "vision_provider", "openai")
                model = getattr(self._config, "vision_model", None)

            self._vision_client = create_vision_provider(provider, model)
        return self._vision_client

    @staticmethod
    def _strip_code_fences(text: str) -> str:
        """Strip markdown code fences from LLM response."""
        return (
            re.sub(r"^```(?:json)?\s*\n?", "", text.strip(), flags=re.MULTILINE).rstrip("`").strip()
        )

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

    def _download_missing_images(self, context: pipeline.PipelineContext) -> int:
        """
        Download image files for triaged images that lack file_path.

        Uses SECClient.fetch_image() with caching, rate limiting, and
        content validation.

        Args:
            context: Pipeline context with images list, cik, accession_number

        Returns:
            Number of images successfully downloaded
        """
        if not context.cik or not context.accession_number:
            return 0

        # Lazy-load SECClient
        if self._sec_client is None:
            from src.infra.sec_client import SECClient

            self._sec_client = SECClient(
                image_cache_dir=_image_cache_base_dir()
            )

        downloaded = 0
        cache_dir = _image_cache_base_dir() / "pipeline"
        cache_dir.mkdir(parents=True, exist_ok=True)

        for asset in context.images:
            # Only download for images that would be processed but lack file_path
            if asset.processed:
                continue
            if asset.relevance_score < self.MIN_RELEVANCE_FOR_PROCESSING:
                continue
            if asset.classification in {
                ImageClassification.DECORATIVE,
                ImageClassification.LOGO,
                ImageClassification.SIGNATURE,
            }:
                continue
            if asset.file_path:
                continue  # Already have file
            if not asset.filename:
                continue

            try:
                image_bytes = self._sec_client.fetch_image(
                    cik=context.cik,
                    accession_number=context.accession_number,
                    filename=asset.filename,
                )
                if image_bytes:
                    image_path = cache_dir / asset.filename
                    image_path.write_bytes(image_bytes)
                    asset.file_path = str(image_path)
                    downloaded += 1
                    logger.info(f"Downloaded image {asset.filename}: {len(image_bytes)} bytes")
                else:
                    logger.warning(f"Failed to download image {asset.filename}")
            except Exception as e:
                logger.warning(f"Error downloading image {asset.filename}: {e}")

        if downloaded:
            logger.info(f"Downloaded {downloaded} images for pipeline processing")
        return downloaded

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

        # Validate file path
        if not asset.file_path:
            raise ValueError(f"Image {asset.img_id} has no file_path")

        image_path = Path(asset.file_path)
        if not image_path.exists():
            raise FileNotFoundError(f"Image file not found: {asset.file_path}")

        # Load image bytes
        image_bytes = image_path.read_bytes()

        # Call Vision API with table extraction prompt
        try:
            _t0 = time.monotonic()
            response = self.vision_client.analyze_image(
                image_bytes=image_bytes,
                prompt=self._get_table_extraction_prompt(),
                detail="high",  # High detail for accurate OCR
                max_tokens=2000,
            )
            _latency_ms = (time.monotonic() - _t0) * 1000.0

            # Parse JSON response
            try:
                ocr_data = json.loads(self._strip_code_fences(response.content))
            except json.JSONDecodeError as e:
                logger.error(f"Failed to parse OCR response as JSON: {e}")
                logger.debug(f"Response content: {response.content[:500]}")
                # Fallback: store raw text but mark for manual capture
                asset.ocr_text = response.content
                asset.processed = True
                asset.confidence = 0.0
                asset.requires_manual_capture = True
                asset.extraction_meta = ImageExtractionMeta(
                    vision_model=response.model,
                    prompt_tokens=response.prompt_tokens,
                    completion_tokens=response.completion_tokens,
                    cost_usd=response.cost_usd,
                    latency_ms=_latency_ms,
                    parse_success=False,
                    manual_capture_reason="json_parse_error",
                )
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
                asset.extraction_meta = ImageExtractionMeta(
                    vision_model=response.model,
                    prompt_tokens=response.prompt_tokens,
                    completion_tokens=response.completion_tokens,
                    cost_usd=response.cost_usd,
                    latency_ms=_latency_ms,
                    parse_success=False,
                    manual_capture_reason="no_cells_in_response",
                )
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
            asset.extraction_meta = ImageExtractionMeta(
                vision_model=response.model,
                prompt_tokens=response.prompt_tokens,
                completion_tokens=response.completion_tokens,
                cost_usd=response.cost_usd,
                latency_ms=_latency_ms,
                parse_success=True,
                manual_capture_reason="low_ocr_confidence" if asset.requires_manual_capture else "",
                extraction_mode="exact",
            )
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

    def _get_chart_extraction_prompt(self, nearby_text: str = "") -> str:
        """
        Get the prompt for chart extraction via Vision API.

        Args:
            nearby_text: Surrounding HTML paragraph text for context

        Returns:
            Prompt string for Vision API
        """
        prompt = """Analyze this chart and extract ONLY explicitly labeled data values.

DEFINITIONS:
- "data labels" = numeric values printed directly on data points (bars, lines, pie slices)
- "annotations" = floating text overlays, callouts, or percentage breakdowns visible on the chart but NOT attached to specific data points

CRITICAL RULES:
1. ONLY extract values that are explicitly shown as data labels on the chart
2. Do NOT interpolate or estimate values from axis positions
3. If a bar/line/point has no label, do NOT include it
4. Include the exact text of labels as shown
5. For unlabeled charts, return empty series array
6. Always capture annotations — floating text overlays with numbers, even if series is empty

Return a JSON object with:
- chart_type: One of "bar", "line", "pie", "stacked_bar", "area", "unknown" (string)
- title: Chart title if visible (string, empty if not visible)
- x_axis_label: X-axis label if visible (string, empty if not visible)
- y_axis_label: Y-axis label if visible (string, empty if not visible)
- confidence: Extraction confidence 0.0-1.0 (float)
- series: Array of series objects, each with:
  - name: Series name from legend (string)
  - points: Array of data point objects, each with:
    - x: Category or date label (string)
    - y: Numeric value (number)
    - label: The explicit label text shown on chart (string or null)
- annotations: Array of text annotations/callouts visible on the chart, each with:
  - text: Full annotation text as shown (string, e.g. "44.4% New Consumers in 2017")
  - value: Parsed numeric value if present (number or null, e.g. 44.4)
  - unit: Unit type — "percent", "currency", "count", or "" if unknown (string)
  - category: Category/segment the annotation refers to (string, e.g. "New Consumers")
  - period: Time period if mentioned (string, e.g. "2017")

If NO labeled values are found, return empty series array (but still populate annotations if any text overlays are visible).

Example JSON:
{
  "chart_type": "area",
  "title": "Marketplace GMV (USDm) by Consumer Cohort",
  "x_axis_label": "Year",
  "y_axis_label": "GMV (USDm)",
  "confidence": 0.85,
  "series": [],
  "annotations": [
    {"text": "44.4% New Consumers in 2017", "value": 44.4, "unit": "percent", "category": "New Consumers", "period": "2017"},
    {"text": "55.6% Existing Consumers in 2017", "value": 55.6, "unit": "percent", "category": "Existing Consumers", "period": "2017"}
  ]
}
"""
        # Append bounded surrounding context if available
        if nearby_text:
            truncated = nearby_text[:1500]
            prompt += f"""
SURROUNDING CONTEXT (from the HTML near this chart):
\"\"\"{truncated}\"\"\"

Use this context to understand what the chart represents. It may contain metric names,
time periods, or definitions that help interpret the chart's data.
"""
        return prompt

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

    def _parse_chart_response(
        self,
        chart_response: dict,
        classification: ChartClassificationResult,
    ) -> tuple[list, list, str, str, str, float]:
        """
        Parse a Pass 2 chart extraction response into structured objects.

        Returns:
            Tuple of (series_list, annotations, title, x_axis_label, y_axis_label, confidence)
        """
        from src.extraction_v2.models import ChartAnnotation, ChartSeries, DataPoint

        title = chart_response.get("title", "")
        x_axis_label = chart_response.get("x_axis_label", "")
        y_axis_label = chart_response.get("y_axis_label", "")
        confidence = float(chart_response.get("confidence", 0.8))

        # Parse axis range from classification for validation
        y_min = classification.axis_info.get("y_min")
        y_max = classification.axis_info.get("y_max")

        # Parse annotations
        annotations_data = chart_response.get("annotations", [])
        chart_annotations: list[ChartAnnotation] = []
        for ann_item in annotations_data:
            ann_text = str(ann_item.get("text", ""))
            if not ann_text:
                continue
            ann_value = ann_item.get("value")
            if ann_value is not None:
                try:
                    ann_value = float(ann_value)
                except (ValueError, TypeError):
                    ann_value = None
            chart_annotations.append(
                ChartAnnotation(
                    text=ann_text,
                    value=ann_value,
                    unit=str(ann_item.get("unit", "")),
                    category=str(ann_item.get("category", "")),
                    period=str(ann_item.get("period", "")),
                )
            )

        # Parse series data
        series_data = chart_response.get("series", [])
        chart_series_list: list[ChartSeries] = []

        for series_item in series_data:
            series_name = series_item.get("name", "")
            points_data = series_item.get("points", [])

            data_points: list[DataPoint] = []
            for point_item in points_data:
                x_val = str(point_item.get("x", ""))
                y_val = point_item.get("y", 0.0)
                label_val = point_item.get("label")
                interpolated = bool(point_item.get("interpolated", False))
                point_conf_raw = point_item.get("confidence")
                point_confidence = float(point_conf_raw) if point_conf_raw is not None else None

                # Convert y to float
                try:
                    if isinstance(y_val, str):
                        y_cleaned = y_val.replace("$", "").replace("%", "").replace(",", "").strip()
                        y_val = float(y_cleaned)
                    else:
                        y_val = float(y_val)
                except (ValueError, TypeError):
                    logger.warning(f"Failed to parse y value: {point_item.get('y')}, skipping point")
                    continue

                # Axis range check: flag out-of-range points
                if y_min is not None and y_max is not None and y_max > y_min:
                    lower_bound = float(y_min) * 0.8
                    upper_bound = float(y_max) * 1.2
                    if y_val < lower_bound or y_val > upper_bound:
                        logger.warning(
                            f"DataPoint y={y_val} is out of axis range [{y_min}, {y_max}] "
                            f"for chart series '{series_name}' — applying 0.5x confidence penalty"
                        )
                        # Apply confidence penalty: set point_confidence if not set
                        if point_confidence is None:
                            point_confidence = 0.5
                        else:
                            point_confidence = point_confidence * 0.5
                        interpolated = True  # Treat out-of-range as unreliable

                # Negative percentage check
                if y_val < 0 and (
                    "percent" in (y_axis_label or "").lower() or "%" in (y_axis_label or "")
                ):
                    logger.warning(
                        f"Negative percentage value {y_val} — applying 0.7x confidence penalty"
                    )
                    if point_confidence is None:
                        point_confidence = 0.7
                    else:
                        point_confidence = point_confidence * 0.7

                data_point = DataPoint(
                    x=x_val,
                    y=y_val,
                    label=label_val,
                    interpolated=interpolated,
                    point_confidence=point_confidence,
                )
                data_points.append(data_point)

            if data_points:
                chart_series_list.append(ChartSeries(name=series_name, points=data_points))

        return chart_series_list, chart_annotations, title, x_axis_label, y_axis_label, confidence

    def _parse_classification_response(self, response_dict: dict) -> ChartClassificationResult:
        """Parse Pass 1 classification JSON into a ChartClassificationResult."""
        from src.extraction_v2.models import ChartType

        chart_type_str = response_dict.get("chart_type", "unknown")
        try:
            chart_type = ChartType(chart_type_str)
        except ValueError:
            chart_type = ChartType.UNKNOWN

        axis_info = {
            "x_label": response_dict.get("x_label", ""),
            "y_label": response_dict.get("y_label", ""),
            "y_min": response_dict.get("y_min"),
            "y_max": response_dict.get("y_max"),
            "y_ticks": response_dict.get("y_ticks", []),
            "x_categories": response_dict.get("x_categories", []),
        }

        return ChartClassificationResult(
            chart_type=chart_type,
            has_data_labels=bool(response_dict.get("has_data_labels", False)),
            axis_info=axis_info,
            legend_entries=list(response_dict.get("legend_entries", [])),
            estimated_series_count=int(response_dict.get("estimated_series_count", 0)),
            confidence=float(response_dict.get("confidence", 0.0)),
        )

    def process_chart(self, asset: ImageAsset, config: Any = None) -> None:
        """
        Extract labeled values from chart using a two-pass Vision API approach.

        Pass 1: Classify chart type, axis scales, legend entries (no value extraction).
        Pass 2: Type-specific extraction using Pass 1 context as structured priors.

        If Pass 1 confidence < 0.3, skip Pass 2 and mark for manual capture.

        Args:
            asset: Image asset to process (modified in place)
            config: Optional PipelineConfig (for interpolation flag)

        Raises:
            FileNotFoundError: If image file doesn't exist
            ValueError: If API returns invalid response
        """
        import json
        from pathlib import Path

        from src.extraction_v2.models import ChartData

        # Validate file path
        if not asset.file_path:
            raise ValueError(f"Image {asset.img_id} has no file_path")

        image_path = Path(asset.file_path)
        if not image_path.exists():
            raise FileNotFoundError(f"Image file not found: {asset.file_path}")

        # Determine if interpolation is enabled from config
        interpolation_enabled = bool(
            config is not None and getattr(config, "enable_chart_interpolation", False)
        )

        # Load image bytes
        image_bytes = image_path.read_bytes()

        try:
            # ----------------------------------------------------------------
            # Pass 1: Classification
            # ----------------------------------------------------------------
            _t1 = time.monotonic()
            pass1_response = self.vision_client.analyze_image(
                image_bytes=image_bytes,
                prompt=get_classification_prompt(),
                detail="high",
                max_tokens=1000,
            )
            _latency_pass1_ms = (time.monotonic() - _t1) * 1000.0
            self._chart_call_count += 1

            # Parse Pass 1 response
            try:
                pass1_data = json.loads(self._strip_code_fences(pass1_response.content))
            except json.JSONDecodeError as e:
                logger.error(f"Failed to parse Pass 1 classification response: {e}")
                asset.processed = True
                asset.confidence = 0.0
                asset.requires_manual_capture = True
                asset.extraction_meta = ImageExtractionMeta(
                    vision_model=pass1_response.model,
                    prompt_tokens=pass1_response.prompt_tokens,
                    completion_tokens=pass1_response.completion_tokens,
                    cost_usd=pass1_response.cost_usd,
                    latency_ms=_latency_pass1_ms,
                    parse_success=False,
                    manual_capture_reason="pass1_json_parse_error",
                )
                return

            classification = self._parse_classification_response(pass1_data)
            asset.classification_result = classification

            # Skip Pass 2 if classification confidence is too low
            if classification.confidence < 0.3:
                logger.info(
                    f"Chart {asset.img_id} Pass 1 confidence={classification.confidence:.2f} < 0.3, "
                    f"skipping Pass 2"
                )
                asset.processed = True
                asset.confidence = classification.confidence
                asset.requires_manual_capture = True
                asset.extraction_meta = ImageExtractionMeta(
                    vision_model=pass1_response.model,
                    prompt_tokens=pass1_response.prompt_tokens,
                    completion_tokens=pass1_response.completion_tokens,
                    cost_usd=pass1_response.cost_usd,
                    latency_ms=_latency_pass1_ms,
                    parse_success=True,
                    skip_reason="low_classification_confidence",
                    manual_capture_reason="low_classification_confidence",
                )
                return

            # ----------------------------------------------------------------
            # Pass 2: Type-specific extraction with Pass 1 priors
            # ----------------------------------------------------------------

            # Build pass1_context dict for prompt construction
            pass1_context = {
                "chart_type": classification.chart_type.value,
                "has_data_labels": classification.has_data_labels,
                "legend_entries": classification.legend_entries,
                **classification.axis_info,
            }

            pass2_prompt = get_pass2_prompt(
                chart_type=classification.chart_type.value,
                pass1_context=pass1_context,
                interpolation_enabled=interpolation_enabled,
            )
            # Append nearby context if available
            if asset.nearby_text:
                truncated = asset.nearby_text[:1500]
                pass2_prompt += (
                    f"\n\nSURROUNDING CONTEXT (from the HTML near this chart):\n"
                    f'"""{truncated}"""\n\n'
                    f"Use this context to understand what the chart represents.\n"
                )

            _t2 = time.monotonic()
            pass2_response = self.vision_client.analyze_image(
                image_bytes=image_bytes,
                prompt=pass2_prompt,
                detail="high",
                max_tokens=2000,
            )
            _latency_pass2_ms = (time.monotonic() - _t2) * 1000.0
            self._chart_call_count += 1

            # Sum telemetry across both passes
            total_prompt_tokens = pass1_response.prompt_tokens + pass2_response.prompt_tokens
            total_completion_tokens = pass1_response.completion_tokens + pass2_response.completion_tokens
            total_cost_usd = pass1_response.cost_usd + pass2_response.cost_usd
            total_latency_ms = _latency_pass1_ms + _latency_pass2_ms

            # Parse Pass 2 response
            try:
                chart_response = json.loads(self._strip_code_fences(pass2_response.content))
            except json.JSONDecodeError as e:
                logger.error(f"Failed to parse Pass 2 chart extraction response: {e}")
                asset.processed = True
                asset.confidence = 0.0
                asset.requires_manual_capture = True
                asset.extraction_meta = ImageExtractionMeta(
                    vision_model=pass2_response.model,
                    prompt_tokens=total_prompt_tokens,
                    completion_tokens=total_completion_tokens,
                    cost_usd=total_cost_usd,
                    latency_ms=total_latency_ms,
                    parse_success=False,
                    manual_capture_reason="pass2_json_parse_error",
                )
                return

            # Parse chart response
            chart_series_list, chart_annotations, title, x_axis_label, y_axis_label, confidence = (
                self._parse_chart_response(chart_response, classification)
            )
            total_points = sum(len(s.points) for s in chart_series_list)

            # Pie chart sum check
            if classification.chart_type.value == "pie" and chart_series_list:
                pie_sum = sum(p.y for s in chart_series_list for p in s.points)
                if abs(pie_sum - 100) > 5:
                    logger.warning(
                        f"Pie chart {asset.img_id}: sum of slice values = {pie_sum:.1f} "
                        f"(expected ~100)"
                    )

            # No data at all — mark for manual capture
            if total_points == 0 and not chart_annotations:
                logger.info(
                    f"Chart {asset.img_id} has no valid data points or annotations, marking for manual capture"
                )
                asset.processed = True
                asset.confidence = 0.0
                asset.requires_manual_capture = True
                asset.extraction_meta = ImageExtractionMeta(
                    vision_model=pass2_response.model,
                    prompt_tokens=total_prompt_tokens,
                    completion_tokens=total_completion_tokens,
                    cost_usd=total_cost_usd,
                    latency_ms=total_latency_ms,
                    parse_success=True,
                    manual_capture_reason="no_labeled_values",
                )
                return

            # Determine extraction mode
            has_interpolated = any(p.interpolated for s in chart_series_list for p in s.points)
            extraction_mode = "interpolated" if has_interpolated else "exact"

            # Build ChartData
            asset.chart_data = ChartData(
                chart_type=classification.chart_type,
                title=title,
                x_axis_label=x_axis_label,
                y_axis_label=y_axis_label,
                series=chart_series_list,
                annotations=chart_annotations,
            )
            asset.confidence = confidence
            asset.requires_manual_capture = False
            asset.processed = True
            asset.extraction_meta = ImageExtractionMeta(
                vision_model=pass2_response.model,
                prompt_tokens=total_prompt_tokens,
                completion_tokens=total_completion_tokens,
                cost_usd=total_cost_usd,
                latency_ms=total_latency_ms,
                parse_success=True,
                extraction_mode=extraction_mode,
            )

            logger.info(
                f"Processed chart {asset.img_id} (two-pass): type={classification.chart_type.value}, "
                f"series={len(chart_series_list)}, points={total_points}, "
                f"confidence={confidence:.2f}, mode={extraction_mode}"
            )

        except Exception as e:
            logger.error(f"Error during chart extraction for {asset.img_id}: {e}", exc_info=True)
            asset.processed = True
            asset.confidence = 0.0
            asset.requires_manual_capture = True
            raise

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

        # Sync config from context so vision_client property picks up provider settings.
        # Only update if not already injected (injected clients take precedence in tests).
        if self._vision_client is None and context.config is not None:
            self._config = context.config

        start_time = datetime.now(UTC)
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
            # Download missing images before processing
            if context.cik and context.accession_number:
                downloaded = self._download_missing_images(context)
                if downloaded:
                    warnings.append(f"Downloaded {downloaded} images from SEC EDGAR")

            # Handle empty images list
            if not context.images:
                logger.info("No images to process")
                duration_ms = int((datetime.now(UTC) - start_time).total_seconds() * 1000)
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

                # Check API call limits per type — use continue so other types
                # still get processed (break would skip all remaining images).
                if asset.classification == ImageClassification.TABLE_IMAGE:
                    if self._ocr_call_count >= self.MAX_OCR_CALLS_PER_DOCUMENT:
                        msg = f"OCR call limit ({self.MAX_OCR_CALLS_PER_DOCUMENT}) reached"
                        if msg not in warnings:
                            warnings.append(msg)
                            logger.warning(msg)
                        asset.extraction_meta = ImageExtractionMeta(skip_reason="api_limit")
                        skipped_count += 1
                        continue
                elif asset.classification == ImageClassification.CHART:
                    if self._chart_call_count >= self.MAX_CHART_CALLS_PER_DOCUMENT:
                        msg = f"Chart call limit ({self.MAX_CHART_CALLS_PER_DOCUMENT}) reached"
                        if msg not in warnings:
                            warnings.append(msg)
                            logger.warning(msg)
                        asset.extraction_meta = ImageExtractionMeta(skip_reason="api_limit")
                        skipped_count += 1
                        continue

                # Process based on classification
                try:
                    if asset.classification == ImageClassification.TABLE_IMAGE:
                        self.process_table_image(asset)
                        self._ocr_call_count += 1
                        # Feed OCR table into pipeline for candidate generation
                        if asset.ocr_table is not None:
                            context.tables.append(asset.ocr_table)
                    elif asset.classification == ImageClassification.CHART:
                        self.process_chart(asset, config=context.config)
                        # _chart_call_count is incremented inside process_chart (once per pass)
                    else:
                        # Unknown type - skip
                        logger.debug(
                            f"Skipping image {asset.img_id} with classification {asset.classification}"
                        )
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

            duration_ms = int((datetime.now(UTC) - start_time).total_seconds() * 1000)

            context.ocr_calls += self._ocr_call_count
            context.vision_calls += self._chart_call_count

            # Aggregate telemetry from all processed images
            total_cost_usd = sum(
                img.extraction_meta.cost_usd
                for img in context.images
                if img.extraction_meta is not None
            )
            skip_reasons: dict[str, int] = {}
            for img in context.images:
                if img.extraction_meta and img.extraction_meta.skip_reason:
                    reason = img.extraction_meta.skip_reason
                    skip_reasons[reason] = skip_reasons.get(reason, 0) + 1

            images_processed = sum(1 for img in context.images if img.processed)
            images_skipped = sum(
                1
                for img in context.images
                if img.extraction_meta and img.extraction_meta.skip_reason
            )

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
                    "images_processed": images_processed,
                    "images_skipped": images_skipped,
                    "skip_reasons": skip_reasons,
                    "total_cost_usd": total_cost_usd,
                },
            )

        except V2FatalError:
            raise
        except Exception as e:
            raise V2FatalError(str(e), stage_name="ocr_chart_extraction") from e
