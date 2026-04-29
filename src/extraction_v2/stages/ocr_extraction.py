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

import json
import logging
import os
import re
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from src.extraction_v2.exceptions import V2FatalError
from src.extraction_v2.models import (
    Cell,
    ChartAnnotation,
    ImageAsset,
    ImageClassification,
    SectionType,
    Segment,
    SegmentSourceType,
    SegmentType,
    Table,
)
from src.shared.keyword_config import get_tier1_keywords_re

if TYPE_CHECKING:
    from src.extraction_v2 import pipeline

logger = logging.getLogger(__name__)


def _synthesize_ocr_segment(
    *,
    image: ImageAsset,
    context: pipeline.PipelineContext,
    ocr_text: str,
) -> Segment:
    """Build a ``Segment`` from OCR'd image text.

    Shared by Path A (full-page-scan) and Path B (keyword pre-scan
    promotion). The resulting segment flows through the normal text
    candidate-generation pipeline, so facts derived from it are
    indistinguishable from HTML-sourced facts except via the segment's
    ``source_type='image_ocr'`` + ``source_img_id`` provenance fields.

    - ``section_type`` is set to ``PRESENTATION_SLIDE`` (valid under the
      live schema's CHECK constraint) so downstream FP rules gated on
      section context do not mis-fire on UNKNOWN.
    - ``dom_locator`` uses a synthetic ``image:<img_id>`` form because
      the image has no HTML DOM position.
    - ``sequence`` is assigned after the current max so downstream
      ordering stays monotonic even when multiple OCR'd segments are
      appended to a filing with existing HTML segments.
    """
    next_sequence = max((s.sequence for s in context.segments), default=-1) + 1
    return Segment(
        filing_id=str(context.filing_id) if context.filing_id else "",
        segment_type=SegmentType.PARAGRAPH,
        text=ocr_text,
        dom_locator=f"image:{image.img_id}",
        section_path=list(image.section_path or []),
        section_type=SectionType.PRESENTATION_SLIDE,
        sequence=next_sequence,
        source_type=SegmentSourceType.IMAGE_OCR,
        source_img_id=image.img_id,
    )


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
    # Full-page-scan (Path A) cap. Longest known PayPal deck is ~16 pages;
    # 30 gives headroom. Exceeding this halts processing with a warning.
    MAX_FULL_PAGE_OCR_CALLS_PER_DOCUMENT: int = 30
    # Keyword pre-scan (Path B) cap. Pre-scan runs on ambiguous UNKNOWN
    # images only; 10/filing bounds worst-case cost at ~$1 (10 pre-scans +
    # up to 10 follow-on chart/table calls, shared chart budget).
    MAX_PRESCAN_CALLS_PER_DOCUMENT: int = 10

    # A3: chart cost control. Per-filing cumulative-spend ceiling in USD
    # replaces the prior MAX_CHART_CALLS_PER_DOCUMENT=10 count cap. Charts
    # are processed in descending relevance_score order; when running-total
    # vision spend hits CHART_BUDGET_PER_FILING_USD, remaining charts are
    # skipped EXCEPT when they carry Tier-1 keywords in nearby_text (these
    # process regardless of budget — CMASB's priority metrics).
    # Dollar-based (not count-based) so the ceiling adapts when cheaper
    # providers land in Wave B4.
    DEFAULT_CHART_BUDGET_PER_FILING_USD: float = 0.25

    # Tier-1 keyword regex used by Path B to decide whether an OCR'd
    # ambiguous image should escalate to the chart/table extraction path.
    # Built automatically from ``config/metric_keywords.yaml`` (tier == 1
    # entries' ``patterns`` + ``specific_patterns``) via ``_build_tier1_re()``.
    # False negatives are tolerable (the image just stays UNKNOWN), but false
    # positives spend an extra vision call.
    TIER1_KEYWORDS_RE: re.Pattern[str] = get_tier1_keywords_re()

    def __init__(
        self,
        vision_client: object | None = None,
        sec_client: object | None = None,
    ) -> None:
        """
        Initialize the OCR extraction stage.

        Args:
            vision_client: Optional vision API client (OpenAI Vision).
                          If None, will be created on first use.
            sec_client: Optional SECClient instance for image downloading.
                       If None, will be created on first use when needed.
        """
        self._vision_client = vision_client
        self._sec_client = sec_client
        self._api_call_count = 0
        self._ocr_call_count = 0
        self._chart_call_count = 0
        self._full_page_ocr_call_count = 0
        self._prescan_call_count = 0
        # A2 observability counters — reset per-document in process().
        self._parse_failed_count = 0
        # A3: per-filing cumulative chart vision spend (USD).
        self._chart_vision_spend: float = 0.0
        # Per-site vision spend (USD), keyed by call-site name. Sites are
        # disjoint: chart_read_premium and chart_ocr_fast both fire inside
        # process_chart but bucketed separately for cost-experiment analysis.
        self._vision_spend_by_site: dict[str, float] = self._zero_spend_by_site()

    @staticmethod
    def _zero_spend_by_site() -> dict[str, float]:
        return {
            "table_ocr": 0.0,
            "chart_ocr_fast": 0.0,
            "chart_read_premium": 0.0,
            "full_page_ocr": 0.0,
            "prescan": 0.0,
        }

    @property
    def vision_client(self) -> Any:
        """Lazy-load vision client to avoid import errors in tests."""
        if self._vision_client is None:
            if not os.environ.get("OPENAI_API_KEY", "").strip():
                raise V2FatalError(
                    "OPENAI_API_KEY is not set. Cannot initialize VisionClient for OCR/chart extraction.",
                    stage_name="ocr_chart_extraction",
                )
            # Import here to avoid circular dependency
            from src.llm.vision_client import VisionClient

            self._vision_client = VisionClient()
        return self._vision_client

    @staticmethod
    def _strip_code_fences(text: str) -> str:
        """Strip markdown code fences from LLM response."""
        return (
            re.sub(r"^```(?:json)?\s*\n?", "", text.strip(), flags=re.MULTILINE).rstrip("`").strip()
        )

    @classmethod
    def _parse_chart_json(cls, content: str) -> dict[str, Any] | None:
        """Parse vision response JSON, attempting a light-touch repair on failure.

        JSON mode should prevent this, but cached responses from before JSON mode
        was enabled — or a truncated response hitting max_tokens mid-array — can
        still produce invalid JSON. Trim to the last balanced brace before giving up.
        """
        import json

        stripped = cls._strip_code_fences(content)
        try:
            return json.loads(stripped)
        except json.JSONDecodeError:
            pass

        repaired = cls._repair_truncated_json(stripped)
        if repaired is None:
            return None
        try:
            return json.loads(repaired)
        except json.JSONDecodeError:
            return None

    @staticmethod
    def _repair_truncated_json(text: str) -> str | None:
        """Attempt to recover a valid JSON object from a truncated response.

        Walks the string tracking brace/bracket depth outside of strings and
        returns the shortest prefix that forms a balanced top-level object.
        Returns None if no balanced object is found.
        """
        if not text or not text.lstrip().startswith("{"):
            return None
        depth = 0
        in_string = False
        escape = False
        last_balanced = -1
        start = text.find("{")
        for i in range(start, len(text)):
            ch = text[i]
            if in_string:
                if escape:
                    escape = False
                elif ch == "\\":
                    escape = True
                elif ch == '"':
                    in_string = False
                continue
            if ch == '"':
                in_string = True
            elif ch == "{" or ch == "[":
                depth += 1
            elif ch == "}" or ch == "]":
                depth -= 1
                if depth == 0 and text[start] == "{" and ch == "}":
                    last_balanced = i
        if last_balanced == -1:
            return None
        return text[start : last_balanced + 1]

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
        from src.infra.image_storage import (
            InvalidStorageKeyError,
            get_image_storage,
            validate_key,
        )
        from src.infra.paths import image_cache_dir

        if not context.cik or not context.accession_number:
            return 0

        # Lazy-load SECClient with image_cache_dir set so fetch_image writes bytes
        # to the shared cache root; storage keys are derived as relative paths
        # from that root.  We then explicitly upload via storage.put_bytes so
        # downstream readers can dereference asset.file_path uniformly across
        # backends — the disk write alone is only sufficient when the storage
        # backend is LocalFilesystemStorage rooted at image_cache_dir() (dev);
        # for R2 (prod), without put_bytes the bytes never leave the local
        # disk and downstream get_bytes calls fail with FileNotFoundError.
        if self._sec_client is None:
            from src.infra.sec_client import SECClient

            self._sec_client = SECClient(image_cache_dir=image_cache_dir())

        cache_root = image_cache_dir()
        downloaded = 0

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
                    cache_path = self._sec_client.get_image_cache_path(
                        context.cik, context.accession_number, asset.filename
                    )
                    key = str(cache_path.relative_to(cache_root))
                    try:
                        validate_key(key)
                    except InvalidStorageKeyError as err:
                        raise InvalidStorageKeyError(
                            f"Derived storage key {key!r} failed validation — "
                            f"cache path {cache_path!r} is not under cache root {cache_root!r}"
                        ) from err
                    get_image_storage().put_bytes(
                        key,
                        image_bytes,
                        content_type="image/jpeg",
                    )
                    asset.file_path = key
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
        from src.infra.image_storage import get_image_storage

        # Validate file path
        if not asset.file_path:
            raise ValueError(f"Image {asset.img_id} has no file_path")

        storage = get_image_storage()
        try:
            image_bytes = storage.get_bytes(asset.file_path)
        except FileNotFoundError:
            raise FileNotFoundError(f"Image file not found: {asset.file_path}") from None

        # Call Vision API with table extraction prompt.
        # Wave B4: in two_stage mode this routes to the fast provider;
        # in legacy mode it falls through to self.analyze_image (identical
        # behavior).
        try:
            response = self.vision_client.analyze_image_targeted(
                image_bytes=image_bytes,
                prompt=self._get_table_extraction_prompt(),
                task_type="table_ocr",
                detail="high",  # High detail for accurate OCR
                max_tokens=2000,
                response_format={"type": "json_object"},
            )
            self._vision_spend_by_site["table_ocr"] += float(getattr(response, "cost_usd", 0.0))

            # Parse JSON response; attempt a best-effort repair before giving up
            ocr_data = self._parse_chart_json(response.content)
            if ocr_data is None:
                logger.error(f"Failed to parse OCR response as JSON for {asset.img_id}")
                logger.debug(f"Response content: {response.content[:500]}")
                self._parse_failed_count += 1
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

    def _get_chart_ocr_prompt(self) -> str:
        """Fast OCR prompt used by Wave B4 two-stage routing.

        Purpose: extract every visible text element from a chart — axis
        labels, tick labels, legend entries, annotation strings, title —
        as a grounding blob for the premium chart reader. Does NOT
        interpret data or extract numeric values as "data points" — that
        is the premium reader's job under the project's "labeled values
        only, no interpolation" rule.

        Returns a JSON object so the response can be parsed deterministically.
        """
        return """Read every visible text element on this chart.
Include: chart title, axis labels, axis tick labels, legend entries,
annotation / callout text, and any labels printed directly on bars / lines / slices.

Do NOT interpret the chart. Do NOT extract numeric values as "data". Just read
the text exactly as it appears.

Return a JSON object with:
- text: All visible text joined with newlines (string)
- labels: Array of individual label strings (array of strings)
"""

    def _get_chart_extraction_prompt(self, nearby_text: str = "", ocr_text: str = "") -> str:
        """
        Get the prompt for chart extraction via Vision API.

        Args:
            nearby_text: Surrounding HTML paragraph text for context
            ocr_text: Optional text extracted from a prior fast-OCR pass
                (Wave B4 two-stage routing). Used as grounding for axis
                labels, legend entries, and annotation strings — never
                as a source of extracted numeric values.

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
When the chart shows cohorts over elapsed time (e.g., a "cohort parfait" or retention-by-vintage chart), put the COHORT VINTAGE in `series.name` (e.g., "Q1 FY2022", "2019 Cohort") and put the ELAPSED MEASUREMENT PERIOD in `point.x` (e.g., "Year 1", "Year 2", "Month 12"). Do not merge them into a single field.
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

Example for elapsed-period cohort chart:
{"series": [{"name": "Q1 FY2022", "points": [{"x": "Year 1", "y": 1.00, "label": "1.00x"}, {"x": "Year 2", "y": 1.40, "label": "1.40x"}]}]}
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

        # Wave B4: append text extracted from a prior fast-OCR pass as grounding.
        # Rule: use this to ground axis labels, legend entries, and annotation
        # text. DO NOT use it as a source of numeric data — any number surfaced
        # only in this blob (and not as a labeled point on the chart) MUST be
        # rejected per the extraction contract.
        if ocr_text:
            ocr_truncated = ocr_text[:2000]
            prompt += f"""
OCR GROUNDING TEXT (extracted from this image in a prior fast pass):
\"\"\"{ocr_truncated}\"\"\"

Use the above strictly as grounding for axis labels, legend entries, and
annotation strings. DO NOT extract numeric values from it unless those
numbers also appear as explicit data labels on the chart itself.
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

    def process_chart(self, asset: ImageAsset) -> float:
        """
        Extract labeled values from chart.

        CRITICAL: Only extract values that are EXPLICITLY labeled on the chart.
        Never interpolate values from axis positions.

        Steps:
        1. Load image file as bytes
        2. Call Vision API with chart extraction prompt
        3. Parse response into ChartData/ChartSeries/DataPoint
        4. Set requires_manual_capture if no labeled values found
        5. Compute confidence from extraction quality

        Args:
            asset: Image asset to process (modified in place)

        Returns:
            Cost in USD of the vision API call (0.0 if result came from cache).

        Raises:
            FileNotFoundError: If image file doesn't exist
            ValueError: If API returns invalid response
        """
        from src.extraction_v2.models import ChartData, ChartSeries, ChartType, DataPoint
        from src.infra.image_storage import get_image_storage

        # Validate file path
        if not asset.file_path:
            raise ValueError(f"Image {asset.img_id} has no file_path")

        storage = get_image_storage()
        try:
            image_bytes = storage.get_bytes(asset.file_path)
        except FileNotFoundError:
            raise FileNotFoundError(f"Image file not found: {asset.file_path}") from None

        # Call Vision API with chart extraction prompt (include nearby context).
        # Wave B4: when VISION_ROUTING_MODE=two_stage, run a cheap OCR pass
        # first and inject its output into the premium chart prompt as
        # grounding for labels/legend/annotation text (NOT as a numeric
        # data source — the premium call still enforces "labeled values
        # only, no interpolation"). Both calls' costs accumulate.
        call_cost: float = 0.0
        ocr_text_blob: str = ""
        two_stage = os.environ.get("VISION_ROUTING_MODE", "legacy").strip().lower() == "two_stage"
        try:
            if two_stage:
                try:
                    ocr_response = self.vision_client.analyze_image_targeted(
                        image_bytes=image_bytes,
                        prompt=self._get_chart_ocr_prompt(),
                        task_type="chart_ocr",
                        detail="high",
                        max_tokens=1500,
                        response_format={"type": "json_object"},
                    )
                    ocr_call_cost = float(getattr(ocr_response, "cost_usd", 0.0))
                    call_cost += ocr_call_cost
                    self._vision_spend_by_site["chart_ocr_fast"] += ocr_call_cost
                    try:
                        parsed_ocr = json.loads(ocr_response.content)
                        ocr_text_blob = str(parsed_ocr.get("text", "") or "")
                    except (json.JSONDecodeError, AttributeError):
                        # OCR pass failed to parse — fall through; grounding
                        # blob stays empty and the chart_read prompt reverts
                        # to its usual (nearby_text only) behavior.
                        logger.warning(
                            f"Chart OCR pass returned unparsable JSON for {asset.img_id}"
                        )
                except Exception as ocr_exc:
                    # OCR pass failures should not abort the chart read.
                    logger.warning(f"Chart OCR pass failed for {asset.img_id}: {ocr_exc}")

            response = self.vision_client.analyze_image_targeted(
                image_bytes=image_bytes,
                prompt=self._get_chart_extraction_prompt(
                    nearby_text=asset.nearby_text,
                    ocr_text=ocr_text_blob,
                ),
                task_type="chart_read",
                detail="high",  # High detail for accurate label extraction
                max_tokens=2000,
                response_format={"type": "json_object"},
            )
            chart_read_cost = float(getattr(response, "cost_usd", 0.0))
            call_cost += chart_read_cost
            self._vision_spend_by_site["chart_read_premium"] += chart_read_cost

            # Parse JSON response; attempt a best-effort repair before giving up
            chart_response = self._parse_chart_json(response.content)
            if chart_response is None:
                logger.error(f"Failed to parse chart response as JSON for {asset.img_id}")
                logger.debug(f"Response content: {response.content[:500]}")
                self._parse_failed_count += 1
                asset.processed = True
                asset.confidence = 0.0
                asset.requires_manual_capture = True
                return call_cost

            # Extract chart metadata
            chart_type_str = chart_response.get("chart_type", "unknown")
            try:
                chart_type = ChartType(chart_type_str)
            except ValueError:
                logger.warning(f"Unknown chart type: {chart_type_str}")
                chart_type = ChartType.UNKNOWN

            title = chart_response.get("title", "")
            x_axis_label = chart_response.get("x_axis_label", "")
            y_axis_label = chart_response.get("y_axis_label", "")

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

            # Extract series data
            series_data = chart_response.get("series", [])
            if not series_data and not chart_annotations:
                # No labeled values AND no annotations - mark for manual capture
                logger.info(
                    f"Chart {asset.img_id} has no labeled values or annotations, marking for manual capture"
                )
                asset.processed = True
                asset.confidence = 0.0
                asset.requires_manual_capture = True
                return call_cost

            # Build ChartSeries and DataPoint objects
            chart_series_list: list[ChartSeries] = []
            total_points = 0

            for series_item in series_data:
                series_name = series_item.get("name", "")
                points_data = series_item.get("points", [])

                data_points: list[DataPoint] = []
                for point_item in points_data:
                    # Extract x, y, label
                    x_val = str(point_item.get("x", ""))
                    y_val = point_item.get("y", 0.0)
                    label_val = point_item.get("label")

                    # Convert y to float if it's not already
                    try:
                        if isinstance(y_val, str):
                            # Strip common non-numeric chars (%, $, commas)
                            y_cleaned = (
                                y_val.replace("$", "").replace("%", "").replace(",", "").strip()
                            )
                            y_val = float(y_cleaned)
                        else:
                            y_val = float(y_val)
                    except (ValueError, TypeError):
                        logger.warning(
                            f"Failed to parse y value: {point_item.get('y')}, skipping point"
                        )
                        continue

                    data_point = DataPoint(x=x_val, y=y_val, label=label_val)
                    data_points.append(data_point)
                    total_points += 1

                if data_points:
                    chart_series = ChartSeries(name=series_name, points=data_points)
                    chart_series_list.append(chart_series)

            # If we still have no points AND no annotations after parsing, mark for manual
            if total_points == 0 and not chart_annotations:
                logger.info(
                    f"Chart {asset.img_id} has no valid data points or annotations after parsing, marking for manual capture"
                )
                asset.processed = True
                asset.confidence = 0.0
                asset.requires_manual_capture = True
                return call_cost

            # Build ChartData object
            chart_data = ChartData(
                chart_type=chart_type,
                title=title,
                x_axis_label=x_axis_label,
                y_axis_label=y_axis_label,
                series=chart_series_list,
                annotations=chart_annotations,
            )
            asset.chart_data = chart_data

            # Compute confidence from extraction quality
            # Use confidence from response if provided, otherwise compute based on data completeness
            confidence = chart_response.get(
                "confidence", 0.8
            )  # Default to 0.8 for successful extraction
            asset.confidence = float(confidence)

            # Don't mark for manual capture if we successfully extracted labeled values
            asset.requires_manual_capture = False
            asset.processed = True

            logger.info(
                f"Processed chart {asset.img_id}: type={chart_type.value}, "
                f"series={len(chart_series_list)}, points={total_points}, "
                f"confidence={asset.confidence:.2f}"
            )
            return call_cost

        except Exception as e:
            logger.error(f"Error during chart extraction for {asset.img_id}: {e}", exc_info=True)
            asset.processed = True
            asset.confidence = 0.0
            asset.requires_manual_capture = True
            raise

    def process_full_page_scan(
        self,
        asset: ImageAsset,
        context: pipeline.PipelineContext,
    ) -> bool:
        """Text-OCR a full-page-scan image and append a synthesized segment.

        Used by Path A (full-page-scan filings) and, post-promotion, by
        Path B (image-level Tier-1 keyword pre-scan). Always writes
        ``asset.ocr_text``; synthesizes a ``Segment`` and appends it to
        ``context.segments`` when the OCR returns any text.

        Args:
            asset: Image to OCR. ``asset.file_path`` must be populated.
            context: Active pipeline context — segments list and image
                dimensions used for stable ordering.

        Returns:
            True if the vision response reported ``contains_chart=true``
            (caller may then dispatch the existing chart-extraction path
            on the same asset as a second pass). False otherwise.

        Raises:
            FileNotFoundError: If image bytes cannot be fetched.
            ValueError: If ``asset.file_path`` is empty.
        """
        from src.infra.image_storage import get_image_storage

        if not asset.file_path:
            raise ValueError(f"Image {asset.img_id} has no file_path")

        storage = get_image_storage()
        try:
            image_bytes = storage.get_bytes(asset.file_path)
        except FileNotFoundError:
            raise FileNotFoundError(f"Image file not found: {asset.file_path}") from None

        try:
            extraction = self.vision_client.analyze_image_for_text(image_bytes=image_bytes)
        except Exception as e:
            logger.error(f"Error during full-page OCR for {asset.img_id}: {e}", exc_info=True)
            asset.processed = True
            asset.confidence = 0.0
            asset.requires_manual_capture = True
            return False

        self._vision_spend_by_site["full_page_ocr"] += float(getattr(extraction, "cost_usd", 0.0))
        asset.ocr_text = extraction.text or ""
        asset.processed = True

        if extraction.text.strip():
            asset.confidence = 1.0
            asset.requires_manual_capture = False
            segment = _synthesize_ocr_segment(
                image=asset,
                context=context,
                ocr_text=extraction.text,
            )
            context.segments.append(segment)
            logger.info(
                "process_full_page_scan: %s -> %d chars, contains_chart=%s",
                asset.img_id,
                len(extraction.text),
                extraction.contains_chart,
            )
        else:
            asset.confidence = 0.0
            asset.requires_manual_capture = True
            logger.warning("process_full_page_scan: %s returned empty text", asset.img_id)

        return bool(extraction.contains_chart)

    def _prescan_ambiguous_images(self, context: pipeline.PipelineContext) -> None:
        """Run a cheap text-OCR pre-scan on ambiguous UNKNOWN images.

        Path B: for filings that did NOT trigger Path A, this escalates
        embedded image tables that the heuristic triage couldn't classify
        from filename / nearby_text. Only runs on images where the existing
        triage already indicated "maybe useful, couldn't tell" — i.e.,
        ``classification == UNKNOWN`` and ``relevance_score`` in [0.2, 0.3).

        Cost is bounded by ``MAX_PRESCAN_CALLS_PER_DOCUMENT`` (10/filing).
        """
        if not context.config or not getattr(context.config, "enable_image_keyword_prescan", False):
            return
        if getattr(context, "full_page_scan_mode", False):
            # Path A already handled the filing; pre-scan would double-bill.
            return

        for asset in context.images:
            if self._prescan_call_count >= self.MAX_PRESCAN_CALLS_PER_DOCUMENT:
                logger.warning(
                    "Pre-scan call limit (%d) reached",
                    self.MAX_PRESCAN_CALLS_PER_DOCUMENT,
                )
                break
            # Candidates for structural disambiguation:
            #   1. UNKNOWN images in the ambiguous relevance band [0.2, 0.3)
            #      (original Path B logic)
            #   2. CHART images with weak keyword signal (relevance [0.3, 0.5))
            #      — these were claimed by _is_chart's "large + metric keyword"
            #      heuristic before A1, but may actually be table-shaped images
            #      (plan A2: extend prescan to large-but-keyword-weak CHART images)
            relevance = asset.relevance_score or 0.0
            is_ambiguous_unknown = (
                asset.classification == ImageClassification.UNKNOWN and 0.2 <= relevance < 0.3
            )
            is_weak_chart = (
                asset.classification == ImageClassification.CHART and 0.3 <= relevance < 0.5
            )
            if not (is_ambiguous_unknown or is_weak_chart):
                continue
            if not asset.file_path:
                continue

            from src.infra.image_storage import get_image_storage

            storage = get_image_storage()
            try:
                image_bytes = storage.get_bytes(asset.file_path)
            except FileNotFoundError:
                logger.debug(
                    "pre-scan: image file not found for %s (%s)",
                    asset.img_id,
                    asset.file_path,
                )
                continue

            try:
                extraction = self.vision_client.analyze_image_for_text(image_bytes=image_bytes)
            except Exception as e:
                logger.warning("pre-scan: vision call failed for %s: %s", asset.img_id, e)
                continue

            self._vision_spend_by_site["prescan"] += float(getattr(extraction, "cost_usd", 0.0))
            self._prescan_call_count += 1
            self._api_call_count += 1

            text = extraction.text or ""
            # Always record ocr_text for audit, even when we don't promote.
            asset.ocr_text = text

            if not text.strip() or not self.TIER1_KEYWORDS_RE.search(text):
                logger.debug(
                    "pre-scan: no Tier-1 keyword in %s (len=%d)",
                    asset.img_id,
                    len(text),
                )
                continue

            # Tier-1 signal found: promote the image and synthesize a
            # segment so downstream candidate_generation sees the text.
            #
            # Disambiguation rule (A2, 2026-04-28):
            #   contains_table=True,  contains_chart=False → TABLE_IMAGE
            #   contains_chart=True,  contains_table=False → CHART
            #   both True → prefer TABLE_IMAGE when chart_hint=="none" (no
            #     clear chart structural signal); otherwise CHART
            #   both False → TABLE_IMAGE (keyword match was the signal;
            #     treat conservatively as table since chart didn't fire)
            if extraction.contains_table and not extraction.contains_chart:
                asset.classification = ImageClassification.TABLE_IMAGE
            elif extraction.contains_chart and not extraction.contains_table:
                asset.classification = ImageClassification.CHART
            elif extraction.contains_chart and extraction.contains_table:
                # Both set: use chart_hint as tiebreaker
                if extraction.chart_hint == "none":
                    asset.classification = ImageClassification.TABLE_IMAGE
                else:
                    asset.classification = ImageClassification.CHART
            else:
                # Neither set (both False) — keyword matched but no structural
                # signal; default to TABLE_IMAGE (conservative)
                asset.classification = ImageClassification.TABLE_IMAGE
            asset.relevance_score = max(asset.relevance_score or 0.0, 0.6)
            asset.requires_manual_capture = False

            segment = _synthesize_ocr_segment(image=asset, context=context, ocr_text=text)
            context.segments.append(segment)

            logger.info(
                "pre-scan: promoted %s to %s (Tier-1 match, %d chars)",
                asset.img_id,
                asset.classification.value,
                len(text),
            )

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

        start_time = datetime.now(UTC)
        errors: list[str] = []
        warnings: list[str] = []

        # Reset API call counters for this document
        self._api_call_count = 0
        self._ocr_call_count = 0
        self._chart_call_count = 0
        self._full_page_ocr_call_count = 0
        self._prescan_call_count = 0
        self._parse_failed_count = 0
        self._chart_vision_spend = 0.0
        self._vision_spend_by_site = self._zero_spend_by_site()

        # A3: per-filing chart-spend ceiling. Read env each call so tests
        # and operators can tune at runtime without reconstructing the stage.
        chart_budget_usd = float(
            os.environ.get(
                "CHART_BUDGET_PER_FILING_USD",
                str(self.DEFAULT_CHART_BUDGET_PER_FILING_USD),
            )
        )

        processed_count = 0
        skipped_count = 0
        manual_capture_count = 0
        # A2 observability counters — surfaced in StageResult.metadata so
        # downstream benchmark work (B1) can separate failure modes without
        # re-reading the DB.
        skipped_for_missing_bytes = 0
        skipped_by_budget_cap = 0
        chart_data_none_after_processing = 0

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

            # Path B: image-level Tier-1 keyword pre-scan. Runs BEFORE the
            # main per-image loop so promoted images are processed under
            # their new CHART / TABLE_IMAGE classification in the same
            # invocation. Skipped on Path-A filings.
            self._prescan_ambiguous_images(context)

            # A3: process charts in descending relevance_score order so
            # high-value charts land inside the per-filing dollar budget
            # before it gets exhausted. Non-chart classifications keep
            # their original order (tables/full-page have their own caps).
            # Non-charts run first so table OCR — which feeds candidate
            # generation downstream — is not starved by chart budget.
            _charts_sorted = sorted(
                (a for a in context.images if a.classification == ImageClassification.CHART),
                key=lambda a: -(a.relevance_score or 0.0),
            )
            _non_charts = [
                a for a in context.images if a.classification != ImageClassification.CHART
            ]
            images_in_order = _non_charts + _charts_sorted

            # Process each relevant image
            for asset in images_in_order:
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
                        skipped_count += 1
                        skipped_by_budget_cap += 1
                        continue
                elif asset.classification == ImageClassification.CHART:
                    # A3: per-filing dollar ceiling. Tier-1 keyword charts
                    # process regardless of budget (CMASB priority metrics);
                    # everything else respects the ceiling. Spend is rounded
                    # to 4 decimals to sidestep float precision (0.01 is not
                    # exact in binary, so cumulative sums drift).
                    has_tier1 = bool(self.TIER1_KEYWORDS_RE.search(asset.nearby_text or ""))
                    if not has_tier1 and round(self._chart_vision_spend, 4) >= chart_budget_usd:
                        msg = (
                            f"Chart budget (${chart_budget_usd:.2f}) exhausted "
                            f"after spending ${self._chart_vision_spend:.4f}"
                        )
                        if msg not in warnings:
                            warnings.append(msg)
                            logger.warning(msg)
                        skipped_count += 1
                        skipped_by_budget_cap += 1
                        continue
                elif asset.classification == ImageClassification.FULL_PAGE_SCAN:
                    if self._full_page_ocr_call_count >= self.MAX_FULL_PAGE_OCR_CALLS_PER_DOCUMENT:
                        msg = (
                            f"Full-page OCR call limit "
                            f"({self.MAX_FULL_PAGE_OCR_CALLS_PER_DOCUMENT}) reached"
                        )
                        if msg not in warnings:
                            warnings.append(msg)
                            logger.warning(msg)
                        skipped_count += 1
                        skipped_by_budget_cap += 1
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
                        chart_cost = self.process_chart(asset)
                        self._chart_call_count += 1
                        self._chart_vision_spend += chart_cost
                        # Track charts that were processed but yielded no data.
                        if asset.chart_data is None:
                            chart_data_none_after_processing += 1
                    elif asset.classification == ImageClassification.FULL_PAGE_SCAN:
                        contains_chart = self.process_full_page_scan(asset, context)
                        self._full_page_ocr_call_count += 1
                        # Two-pass: if the page contains a chart, run the
                        # existing chart extraction on the same image.
                        # Respects the shared chart dollar budget with the
                        # same Tier-1 bypass as the main chart branch.
                        if contains_chart:
                            has_tier1 = bool(self.TIER1_KEYWORDS_RE.search(asset.nearby_text or ""))
                            if has_tier1 or round(self._chart_vision_spend, 4) < chart_budget_usd:
                                chart_cost = self.process_chart(asset)
                                self._chart_call_count += 1
                                self._chart_vision_spend += chart_cost
                                self._api_call_count += 1
                                if asset.chart_data is None:
                                    chart_data_none_after_processing += 1
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

                except FileNotFoundError:
                    # Bytes missing from storage — count separately from generic errors.
                    skipped_for_missing_bytes += 1
                    skipped_count += 1
                    asset.requires_manual_capture = True
                    asset.processed = True
                    asset.confidence = 0.0
                    manual_capture_count += 1
                    logger.warning(
                        "Missing bytes for image %s (%s) — skipped_for_missing_bytes=%d",
                        asset.img_id,
                        asset.file_path,
                        skipped_for_missing_bytes,
                    )
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
                    "chart_vision_spend_usd": round(self._chart_vision_spend, 4),
                    "chart_budget_usd": chart_budget_usd,
                    "full_page_ocr_calls": self._full_page_ocr_call_count,
                    "prescan_calls": self._prescan_call_count,
                    "total_api_calls": self._api_call_count,
                    "manual_capture_count": manual_capture_count,
                    "skipped_count": skipped_count,
                    # A2 observability counters — separate failure modes for B1 benchmarking.
                    "skipped_for_missing_bytes": skipped_for_missing_bytes,
                    "skipped_by_budget_cap": skipped_by_budget_cap,
                    "parse_failed": self._parse_failed_count,
                    "chart_data_none_after_processing": chart_data_none_after_processing,
                    "vision_spend_usd_by_site": {
                        site: round(spend, 6) for site, spend in self._vision_spend_by_site.items()
                    },
                },
            )

        except V2FatalError:
            raise
        except Exception as e:
            raise V2FatalError(str(e), stage_name="ocr_chart_extraction") from e
