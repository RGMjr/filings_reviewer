# Worker Prompt: V2-05 - Implement OCR & Chart Extraction Stage (Phase 5)

## Context
- **Branch**: `main`
- **Dependencies**: V2-04 (Image Triage stage) - COMPLETE
- **PRD Reference**: V2 extraction pipeline - Phase 5: OCR & Chart Extraction
- **Size**: L (4-8 hours)

## Background

The V2 extraction pipeline Image Triage stage (V2-04) classifies images and computes relevance scores. Phase 5 (OCR & Chart Extraction) processes high-relevance images to extract structured data:

- **TABLE_IMAGE**: Run OCR to extract text, then reconstruct into `Table` object
- **CHART**: Use vision model to extract labeled data values (never interpolate from axes)

V2 design principle: "Charts only when labeled" - extract ONLY explicit data labels shown on charts, never interpolate values from axis positions.

Current state:
- `src/extraction_v2/stages/image_triage.py` classifies images and sets `relevance_score`
- `src/extraction_v2/models.py` defines `ImageAsset`, `ChartData`, `ChartSeries`, `DataPoint`, `Table`
- Images with `relevance_score >= 0.3` are queued for processing

## Acceptance Criteria

- [ ] AC-1: Create `src/extraction_v2/stages/ocr_extraction.py` with `OCRExtractionStage` class
- [ ] AC-2: Implement `process_table_image()` method that:
  - Calls OCR API (OpenAI Vision or Tesseract fallback)
  - Stores raw OCR text in `ImageAsset.ocr_text`
  - Reconstructs table structure into `ImageAsset.ocr_table` using `TableReconstructor`
- [ ] AC-3: Implement `process_chart()` method that:
  - Calls vision model (OpenAI GPT-4o) with structured extraction prompt
  - Extracts ONLY labeled data values (never interpolate from axes)
  - Populates `ImageAsset.chart_data` with `ChartData`, `ChartSeries`, `DataPoint`
- [ ] AC-4: Implement `process()` method conforming to pipeline stage interface
  - Only process images with `relevance_score >= MIN_RELEVANCE_FOR_PROCESSING`
  - Skip images already marked `processed=True`
- [ ] AC-5: Set `ImageAsset.processed = True` and `ImageAsset.confidence` after extraction
- [ ] AC-6: Set `requires_manual_capture=True` when:
  - OCR confidence is low (< 0.5)
  - Chart has no labeled values
  - Vision model returns ambiguous results
- [ ] AC-7: Implement cost-aware batching (track API calls, respect config limits)
- [ ] AC-8: Handle extraction errors gracefully (log, mark for manual, continue)
- [ ] AC-9: Unit tests achieve >= 85% coverage on new code
- [ ] AC-10: Integration test with mocked vision API responses

## Technical Approach

### Table Image OCR

```python
async def process_table_image(self, asset: ImageAsset) -> None:
    """
    Extract table from image using OCR.

    Steps:
    1. Call vision API with table extraction prompt
    2. Parse OCR response into cells
    3. Use TableReconstructor to build Table object
    4. Compute confidence from OCR quality signals
    """
    # Use OpenAI Vision API with structured output
    response = await self.vision_client.analyze_image(
        image_path=asset.file_path,
        prompt=TABLE_EXTRACTION_PROMPT,
        response_format={"type": "json_schema", "schema": TABLE_SCHEMA}
    )

    asset.ocr_text = response.raw_text
    asset.ocr_table = self._reconstruct_table(response.cells)
    asset.confidence = response.confidence
    asset.processed = True
```

### Chart Data Extraction

```python
async def process_chart(self, asset: ImageAsset) -> None:
    """
    Extract labeled values from chart.

    CRITICAL: Only extract values that are EXPLICITLY labeled on the chart.
    Never interpolate values from axis positions.
    """
    response = await self.vision_client.analyze_image(
        image_path=asset.file_path,
        prompt=CHART_EXTRACTION_PROMPT,  # Emphasizes "labeled values only"
        response_format={"type": "json_schema", "schema": CHART_SCHEMA}
    )

    if not response.data_points:
        # No labeled values found - mark for manual capture
        asset.requires_manual_capture = True
        asset.confidence = 0.0
    else:
        asset.chart_data = self._build_chart_data(response)
        asset.confidence = response.confidence

    asset.processed = True
```

### Vision API Prompts

```python
TABLE_EXTRACTION_PROMPT = """
Analyze this table image and extract all cell contents.

Return a JSON array of cells, each with:
- row: 0-indexed row number
- col: 0-indexed column number
- text: cell content as string
- is_header: true if this appears to be a header cell

Focus on accuracy over completeness. If text is unclear, mark confidence as low.
"""

CHART_EXTRACTION_PROMPT = """
Analyze this chart and extract ONLY explicitly labeled data values.

CRITICAL RULES:
1. ONLY extract values that are explicitly shown as data labels on the chart
2. Do NOT interpolate or estimate values from axis positions
3. If a bar/line/point has no label, do NOT include it
4. Include the exact text of labels as shown

Return JSON with:
- chart_type: "bar", "line", "pie", "stacked_bar", "area", "unknown"
- title: chart title if visible
- x_axis_label: x-axis label if visible
- y_axis_label: y-axis label if visible
- series: array of {name, points: [{x, y, label}]}

If NO labeled values are found, return empty series array.
"""
```

### Pipeline Stage Interface

```python
class OCRExtractionStage:
    """Stage 5: OCR & Chart Extraction."""

    MIN_RELEVANCE_FOR_PROCESSING = 0.3
    MAX_API_CALLS_PER_BATCH = 50  # Cost control

    def __init__(self, vision_client: VisionClient | None = None):
        self.vision_client = vision_client or OpenAIVisionClient()
        self.api_call_count = 0

    async def process(self, context: PipelineContext) -> StageResult:
        """
        Process high-relevance images with OCR/Vision.

        Modifies context.images in place.
        Returns StageResult with extraction counts.
        """
        processed_count = 0
        error_count = 0
        manual_capture_count = 0

        for asset in context.images:
            if not self._should_process(asset):
                continue

            if self.api_call_count >= self.config.max_api_calls:
                logger.warning("API call limit reached")
                break

            try:
                if asset.classification == ImageClassification.TABLE_IMAGE:
                    await self.process_table_image(asset)
                elif asset.classification == ImageClassification.CHART:
                    await self.process_chart(asset)

                self.api_call_count += 1
                processed_count += 1

                if asset.requires_manual_capture:
                    manual_capture_count += 1

            except Exception as e:
                logger.error(f"Error processing {asset.img_id}: {e}")
                asset.requires_manual_capture = True
                error_count += 1

        return StageResult(
            stage_name="ocr_extraction",
            processed_count=processed_count,
            error_count=error_count,
            metadata={"manual_capture_count": manual_capture_count}
        )
```

## Files to Create/Modify

### Create
- `src/extraction_v2/stages/ocr_extraction.py` - Main implementation
- `src/extraction_v2/vision_client.py` - Vision API wrapper (OpenAI GPT-4o)
- `tests/unit/extraction_v2/test_ocr_extraction.py` - Unit tests
- `tests/fixtures/extraction_v2/vision_responses/` - Mock API responses

### Modify
- `src/extraction_v2/stages/__init__.py` - Export OCRExtractionStage
- `src/extraction_v2/pipeline.py` - Wire OCRExtractionStage into pipeline

## Test Cases Required

1. **Table image OCR**: Mock vision response, verify Table object created
2. **Chart extraction with labels**: Extract labeled values correctly
3. **Chart without labels**: Mark `requires_manual_capture=True`
4. **Low confidence OCR**: Mark for manual capture
5. **Relevance filtering**: Skip images below threshold
6. **Already processed**: Skip images with `processed=True`
7. **API error handling**: Graceful failure, mark for manual
8. **API call limit**: Stop processing when limit reached
9. **Empty batch**: No relevant images returns early
10. **Pipeline integration**: Full stage `process()` test

## Verification Commands

```bash
# Run unit tests
pytest tests/unit/extraction_v2/test_ocr_extraction.py -v

# Check coverage
pytest tests/unit/extraction_v2/test_ocr_extraction.py --cov=src/extraction_v2/stages/ocr_extraction --cov-report=term-missing

# Type checking
mypy src/extraction_v2/stages/ocr_extraction.py src/extraction_v2/vision_client.py --strict

# Lint
ruff check src/extraction_v2/stages/ocr_extraction.py src/extraction_v2/vision_client.py

# Run all V2 tests
pytest tests/unit/extraction_v2/ -v
```

## Success Metrics

- All unit tests pass
- Coverage >= 85% on `ocr_extraction.py`
- No mypy errors with `--strict`
- No ruff errors
- Pipeline integration test passes

## Edge Cases to Handle

1. **No file path**: Image exists but file not downloaded - skip
2. **Corrupted image**: Vision API error - mark for manual
3. **Very large image**: May exceed API limits - resize or skip
4. **Rotated table**: May need rotation detection
5. **Multi-page table**: Mark for manual capture
6. **Mixed chart types**: Combo charts - extract what's labeled
7. **Non-English labels**: Support UTF-8 extraction

## V1 Code to Reference

- `src/llm/openai_client.py` - Existing OpenAI integration patterns
- `src/extraction_v2/table_reconstructor.py` - Table reconstruction logic
- `src/extraction/cohort_chart_detector.py` - Chart context patterns

## Notes

- Stage 5 is the ONLY stage that calls external vision APIs (cost-sensitive)
- Never interpolate chart values - only extract explicitly labeled data
- Track API costs via call counting
- Images that can't be extracted reliably should be marked for manual capture
- Use async/await for API calls to enable future parallelization
- The existing `ChartData`, `ChartSeries`, `DataPoint` models in `models.py` are ready to use

## Configuration

Add to `PipelineConfig`:
```python
# Vision extraction settings
enable_ocr_extraction: bool = True
enable_chart_extraction: bool = True
max_ocr_calls_per_document: int = 20
max_chart_calls_per_document: int = 10
ocr_confidence_threshold: float = 0.5  # Below this, mark for manual
vision_model: str = "gpt-4o"  # OpenAI model for vision tasks
```
