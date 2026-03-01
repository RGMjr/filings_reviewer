# Worker Prompt: V2-04 - Implement Image Triage Stage (Phase 4)

## Context
- **Branch**: `main`
- **Dependencies**: V2-01 (Ingestion stage) - COMPLETE
- **PRD Reference**: V2_IMPLEMENTATION_ROADMAP.md - Phase 4: Image Triage
- **Size**: M (2-4 hours)

## Background

The V2 extraction pipeline ingestion stage (Phase 1) extracts `ImageAsset` objects from SEC filings with basic decorative filtering. Phase 4 (Image Triage) adds sophisticated classification and relevance scoring to prioritize images for expensive OCR/Vision processing in Phase 5.

Current state:
- `src/extraction_v2/stages/ingestion.py` extracts `ImageAsset` objects with:
  - Basic decorative filtering (logo, icon, bullet patterns)
  - Initial relevance score based on nearby text keywords
  - Nearby text extraction (caption + context)

Phase 4 needs to:
- Classify images into more granular categories (chart vs table image vs decorative)
- Score relevance based on section context (MD&A > Cover)
- Identify chart types (bar, line, pie) for appropriate extraction strategy
- Queue high-relevance images for OCR/Vision processing

## Acceptance Criteria

- [ ] AC-1: Create `src/extraction_v2/stages/image_triage.py` with `ImageTriageStage` class
- [ ] AC-2: Implement `classify_image()` method using filename patterns, nearby text, and dimensions
- [ ] AC-3: Classify images into: CHART, TABLE_IMAGE, DECORATIVE, LOGO, SIGNATURE, UNKNOWN
- [ ] AC-4: For CHART images, detect chart type (BAR, LINE, PIE, STACKED_BAR, AREA)
- [ ] AC-5: Implement `score_relevance()` with section-aware scoring (MD&A +0.2, Risk Factors +0.1)
- [ ] AC-6: Implement `triage_images()` batch method that processes all images in context
- [ ] AC-7: Filter decorative images more aggressively (aspect ratio, repeated patterns)
- [ ] AC-8: Set `requires_manual_capture=True` for ambiguous images
- [ ] AC-9: Implement `process()` method conforming to pipeline stage interface
- [ ] AC-10: Unit tests achieve ≥85% coverage on new code
- [ ] AC-11: Integration test with real SEC filing images (from test fixtures)

## Technical Approach

### Image Classification Algorithm

```python
def classify_image(self, asset: ImageAsset) -> ImageClassification:
    """
    Classify image based on multiple signals.

    Priority order:
    1. Filename patterns (most reliable)
    2. Nearby text patterns (caption analysis)
    3. Dimensions and aspect ratio
    4. Section context
    """
    filename_lower = asset.filename.lower()
    text_lower = asset.nearby_text.lower()

    # 1. Logo detection (filename + dimensions)
    if self._is_logo(asset):
        return ImageClassification.LOGO

    # 2. Signature detection
    if 'signature' in filename_lower or 'sign' in filename_lower:
        return ImageClassification.SIGNATURE

    # 3. Chart detection (filename + text patterns)
    if self._is_chart(asset):
        return ImageClassification.CHART

    # 4. Table image detection
    if self._is_table_image(asset):
        return ImageClassification.TABLE_IMAGE

    # 5. Decorative detection (fallback)
    if self._is_decorative(asset):
        return ImageClassification.DECORATIVE

    return ImageClassification.UNKNOWN
```

### Chart Type Detection

```python
def detect_chart_type(self, asset: ImageAsset) -> ChartType:
    """Detect chart type from filename and caption."""
    text = (asset.filename + ' ' + asset.nearby_text).lower()

    if any(kw in text for kw in ['bar chart', 'bar graph', 'histogram']):
        return ChartType.BAR
    if any(kw in text for kw in ['stacked bar', 'stacked chart']):
        return ChartType.STACKED_BAR
    if any(kw in text for kw in ['line chart', 'line graph', 'trend']):
        return ChartType.LINE
    if any(kw in text for kw in ['pie chart', 'pie graph', 'distribution']):
        return ChartType.PIE
    if any(kw in text for kw in ['area chart', 'area graph']):
        return ChartType.AREA

    return ChartType.UNKNOWN
```

### Relevance Scoring

```python
def score_relevance(self, asset: ImageAsset) -> float:
    """
    Compute relevance score (0-1) for metric extraction.

    Factors:
    - Keyword proximity (cohort, retention, revenue, etc.)
    - Section context (MD&A most valuable)
    - Caption quality (explicit metric references)
    - Image classification (charts > unknown > decorative)
    """
    score = 0.0

    # Base score by classification
    classification_scores = {
        ImageClassification.CHART: 0.5,
        ImageClassification.TABLE_IMAGE: 0.4,
        ImageClassification.UNKNOWN: 0.2,
        ImageClassification.DECORATIVE: 0.0,
        ImageClassification.LOGO: 0.0,
        ImageClassification.SIGNATURE: 0.0,
    }
    score = classification_scores.get(asset.classification, 0.1)

    # Section bonus
    section_bonuses = {
        SectionType.MDA: 0.2,
        SectionType.BUSINESS: 0.15,
        SectionType.RISK_FACTORS: 0.1,
        SectionType.FINANCIALS: 0.05,
    }
    score += section_bonuses.get(asset.section_type, 0.0)

    # Keyword bonus
    text_lower = asset.nearby_text.lower()
    high_value_keywords = [
        'cohort', 'retention', 'churn', 'ltv', 'cac',
        'arr', 'mrr', 'nrr', 'revenue', 'customers'
    ]
    for keyword in high_value_keywords:
        if keyword in text_lower:
            score += 0.1

    return min(1.0, score)
```

### Pipeline Stage Interface

```python
class ImageTriageStage:
    """Stage 4: Image Triage - classify and prioritize images."""

    # Thresholds
    MIN_RELEVANCE_FOR_PROCESSING = 0.3  # Queue for OCR/Vision
    AMBIGUOUS_RELEVANCE_THRESHOLD = 0.5  # Mark for manual capture

    def process(self, context: PipelineContext) -> StageResult:
        """
        Process all images in context, setting classification and relevance.

        Modifies context.images in place.
        Returns StageResult with counts.
        """
        ...
```

## Files to Create/Modify

### Create
- `src/extraction_v2/stages/image_triage.py` - Main implementation
- `tests/unit/extraction_v2/test_image_triage.py` - Unit tests
- `tests/fixtures/images/` - Test image fixtures (or use mock data)

### Modify
- `src/extraction_v2/stages/__init__.py` - Export ImageTriageStage
- `src/extraction_v2/pipeline.py` - Wire ImageTriageStage into pipeline

## Test Cases Required

1. **Logo detection**: Small images with "logo" in filename
2. **Signature detection**: Images with "signature" pattern
3. **Chart detection**: Images with chart keywords in caption
4. **Table image detection**: Images with tabular content indicators
5. **Section-aware scoring**: MD&A images score higher than Cover
6. **Keyword relevance**: Cohort/retention keywords boost score
7. **Ambiguous images**: Low-confidence images marked for manual capture
8. **Empty batch**: No images should return early
9. **Pipeline integration**: Full stage process() test

## Verification Commands

```bash
# Run unit tests
pytest tests/unit/extraction_v2/test_image_triage.py -v

# Check coverage
pytest tests/unit/extraction_v2/test_image_triage.py --cov=src/extraction_v2/stages/image_triage --cov-report=term-missing

# Type checking
mypy src/extraction_v2/stages/image_triage.py --strict

# Lint
ruff check src/extraction_v2/stages/image_triage.py

# Run all V2 tests
pytest tests/unit/extraction_v2/ -v
```

## Success Metrics

- All unit tests pass
- Coverage ≥85% on `image_triage.py`
- No mypy errors with `--strict`
- No ruff errors
- Pipeline integration test passes

## Edge Cases to Handle

1. **No nearby text**: Use filename and dimensions only
2. **No dimensions**: Assume relevant (can't filter by size)
3. **Mixed signals**: Chart filename but "logo" in text - prioritize filename
4. **Very large images**: May be full-page scans, mark for manual review
5. **Repeated images**: Same image referenced multiple times (dedup by filename)

## V1 Code to Reference

- `src/extraction/cohort_chart_detector.py` - Cohort chart detection patterns
- `src/extraction/segment_enricher.py` - `_detect_cohort_chart_images()` method

## Notes

- Phase 4 does NOT do OCR or vision API calls - that's Phase 5
- Classification updates `ImageAsset.classification` in place
- Relevance score updates `ImageAsset.relevance_score` in place
- High relevance images (≥0.3) will be queued for Phase 5 processing
- The existing `ImageClassification` and `ChartType` enums in `models.py` are ready to use
