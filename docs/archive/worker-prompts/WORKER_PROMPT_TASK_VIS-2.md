# WORKER PROMPT: Task VIS-2 - LLM Vision Chart Value Extraction Pipeline

```
═══════════════════════════════════════════════════════════════════════════════
TASK ID:       VIS-2
TASK NAME:     Implement LLM Vision-based chart value extraction pipeline
WORKSTREAM:    Visual Interpretation
SOURCE:        VIS-1/VIS-1a research recommendations
STATUS:        🟡 PENDING
COMPLETION:    N/A
TIME ESTIMATE: 4-6 hours (image fetcher: 1hr, vision extractor: 2hr, integration: 1hr, tests: 1.5hr)
TIME ACTUAL:   N/A
RISK LEVEL:    Low - additive feature, no existing behavior changed
TASK SIZE:     L
DEPENDS ON:    VIS-1 ✅, VIS-1a ✅ (research confirming LLM Vision is the only viable approach)
UNLOCKS:       VIS-3 (review UI integration for chart metrics)
BLOCKS:        None
PARALLEL WITH: None - foundational infrastructure task
═══════════════════════════════════════════════════════════════════════════════
```

## Objective

Build an automated pipeline that downloads chart images from SEC filings and extracts structured metric data using LLM Vision (OpenAI GPT-4o).

**Business Rationale**: High-value cohort metrics in SEC filings (ARR by cohort, GMV by vintage, retention curves) exist ONLY in chart images. VIS-1/VIS-1a research confirmed that:
- DePlot/MatCha (academic chart-to-table models) fail catastrophically on stacked area charts (0% accuracy)
- LLM Vision (Claude/GPT-4o) achieves ~80% accuracy with zero hallucinations

Without this pipeline, we cannot extract metrics that companies deliberately present visually rather than textually.

**Current Behavior**: `CohortChartDetector` identifies WHERE charts are but cannot extract WHAT values they contain.

**Desired Behavior**: Pipeline fetches chart images, sends to LLM Vision, and returns structured `ExtractedChartValue` objects with cohort labels, values, periods, and confidence scores.

## Prerequisites

- VIS-1 research complete (confirms DePlot fails, Claude works)
- VIS-1a research complete (confirms MatCha fails, recommendation is LLM Vision)
- OpenAI API key configured in `.env` (OPENAI_API_KEY)
- Existing infrastructure: `CohortChartDetector`, `OpenAIClient`, `SECClient`

## Files to Create

1. **`src/llm/vision_client.py`** - VisionClient class wrapping OpenAI GPT-4o Vision API
2. **`src/extraction/chart_value_extractor.py`** - Uses VisionClient for extraction with structured output parsing
3. **`tests/unit/llm/test_vision_client.py`** - Unit tests for VisionClient
4. **`tests/unit/extraction/test_chart_value_extractor.py`** - Unit tests with mocked LLM responses

## Files to Modify

1. **`src/infra/sec_client.py`** - Add `fetch_image(cik, accession, filename) -> bytes | None` method
2. **`tests/unit/infra/test_sec_client.py`** - Tests for image fetching

## Files to Read (Context Only)

- `src/extraction/cohort_chart_detector.py` - Understand `CohortChartCandidate` structure
- `src/llm/openai_client.py` - Understand existing LLM infrastructure (VisionClient is NEW, not a modification)
- `docs/research/VIS-1-chart-extraction-results.md` - Reference extraction prompts
- `docs/research/VIS-1a-extended-evaluation-results.md` - Failure mode documentation
- `docs/research/VIS-GPT4O-VALIDATION.md` - GPT-4o validation test results (GO decision confirmed)

## Implementation Requirements

### 1. SEC Image Fetcher (`sec_client.py`)

Add method to download images from SEC EDGAR:

```python
def fetch_image(
    self,
    cik: str,
    accession_number: str,
    filename: str,
    *,
    max_size_bytes: int = 10 * 1024 * 1024,  # 10MB default limit
) -> bytes | None:
    """
    Fetch an image file from SEC EDGAR.

    Args:
        cik: SEC Central Index Key (will be zero-padded)
        accession_number: SEC accession number (with dashes, e.g., "0001234567-24-000001")
        filename: Image filename from the filing (e.g., "chart1.jpg")
        max_size_bytes: Maximum allowed image size (default 10MB)

    Returns:
        Raw image bytes, or None if fetch failed (404, network error, too large)

    Note:
        - Respects existing rate limiting (100ms minimum between requests)
        - Validates Content-Type is an image type
        - Logs warnings for failures (does not raise exceptions)
    """
```

**URL Construction**: `https://www.sec.gov/Archives/edgar/data/{CIK}/{accession_no_dashes}/{filename}`
- CIK should NOT be zero-padded in the URL (SEC uses raw CIK)
- Accession number should have dashes removed

**Implementation Requirements**:
- Use `self._http_client.get()` for consistency with existing code
- Call `self._rate_limit()` before the request
- Validate `Content-Type` header starts with `image/`
- Check `Content-Length` against `max_size_bytes` before downloading
- Return `None` on any error (404, network, validation failure)
- Log at WARNING level for failures

### 2. Chart Value Extractor (`chart_value_extractor.py`)

#### Core Data Structures

```python
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ExtractedChartValue:
    """Single extracted value from a chart."""

    metric_type: str          # e.g., "ARR", "GMV", "retention"
    cohort_label: str         # e.g., "FY2015", "2010 cohort"
    period: str               # e.g., "FY2019", "2017"
    value: float | None       # Numeric value if extractable
    unit: str                 # e.g., "USD millions", "percent"
    confidence: float         # 0.0-1.0
    source_image: str         # Image filename for provenance


@dataclass
class ChartExtractionResult:
    """Complete extraction result for one chart."""

    chart_title: str | None
    metric_type: str
    values: list[ExtractedChartValue] = field(default_factory=list)
    has_y_axis_scale: bool = False    # Critical for value accuracy
    extraction_confidence: float = 0.0
    raw_llm_response: str = ""        # Preserve for debugging
    cost_usd: float = 0.0
    latency_ms: int = 0
    error: str | None = None          # Error message if extraction failed
```

#### Extraction Prompt

Use the prompt validated in VIS-1 research:

```
Extract all data series from this cohort chart as a structured table. Include:
- Chart title/description (if visible)
- Metric type (ARR, GMV, retention, etc.)
- For each data series:
  - Cohort label (e.g., "FY2015 cohort")
  - Values by time period with years
  - Units (dollars, millions, percent)

If the Y-axis has no numeric scale, note this and do NOT estimate values.
Return structured JSON with this schema:
{
  "chart_title": "...",
  "metric_type": "ARR|GMV|retention|other",
  "has_y_axis_scale": true/false,
  "cohorts": [
    {
      "label": "FY2015",
      "values": [{"period": "FY2019", "value": 100, "unit": "USD millions"}]
    }
  ],
  "annotations": ["44.4% New Consumers", ...]
}
```

### 3. VisionClient (`src/llm/vision_client.py`)

Create a new `VisionClient` class (separate from `OpenAIClient`) for vision-specific operations:

```python
"""LLM Vision API client for chart image analysis."""
from __future__ import annotations

import base64
import logging
import time
from dataclasses import dataclass

from openai import OpenAI

logger = logging.getLogger(__name__)


# Supported image formats with their magic bytes
IMAGE_SIGNATURES: dict[bytes, str] = {
    b"\xff\xd8\xff": "image/jpeg",
    b"\x89PNG\r\n\x1a\n": "image/png",
    b"GIF87a": "image/gif",
    b"GIF89a": "image/gif",
}


def detect_mime_type(image_bytes: bytes) -> str:
    """Detect MIME type from image magic bytes.

    Args:
        image_bytes: Raw image bytes

    Returns:
        MIME type string (defaults to "image/png" if unknown)
    """
    for signature, mime_type in IMAGE_SIGNATURES.items():
        if image_bytes.startswith(signature):
            return mime_type
    # Default to PNG for unknown formats (OpenAI will reject if invalid)
    return "image/png"


@dataclass
class VisionResponse:
    """Response from Vision LLM."""

    content: str
    model: str
    prompt_tokens: int
    completion_tokens: int
    cost_usd: float
    latency_ms: int


class VisionClient:
    """Client for OpenAI GPT-4o Vision API.

    Design: OpenAI-only for now. Can be extended to support Claude Vision
    in the future via subclassing or protocol pattern.
    """

    # GPT-4o pricing per 1M tokens (as of 2025-01)
    # Source: https://openai.com/pricing
    COST_PER_1M_INPUT_TOKENS: float = 2.50   # $2.50/1M input
    COST_PER_1M_OUTPUT_TOKENS: float = 10.00  # $10.00/1M output

    def __init__(self, model: str = "gpt-4o") -> None:
        """Initialize VisionClient.

        Args:
            model: OpenAI model to use (default: gpt-4o)
        """
        self.model = model
        self._client = OpenAI()  # Uses OPENAI_API_KEY from env

    def analyze_image(
        self,
        image_bytes: bytes,
        prompt: str,
        *,
        detail: str = "high",
        max_tokens: int = 2000,
    ) -> VisionResponse:
        """Send image to Vision LLM for analysis.

        Args:
            image_bytes: Raw image bytes (JPEG, PNG, or GIF)
            prompt: Text prompt describing what to extract
            detail: Image detail level ("high" for accuracy, "low" for speed/cost)
            max_tokens: Maximum response tokens

        Returns:
            VisionResponse with content and metadata

        Raises:
            openai.APIError: On API failures (after retries exhausted)
        """
        # Encode image as base64
        b64_image = base64.standard_b64encode(image_bytes).decode("utf-8")

        # Detect MIME type from magic bytes
        mime_type = detect_mime_type(image_bytes)

        start_ms = int(time.time() * 1000)

        response = self._client.chat.completions.create(
            model=self.model,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:{mime_type};base64,{b64_image}",
                                "detail": detail,
                            },
                        },
                    ],
                }
            ],
            max_tokens=max_tokens,
        )

        latency_ms = int(time.time() * 1000) - start_ms

        # Extract usage stats
        usage = response.usage
        prompt_tokens = usage.prompt_tokens if usage else 0
        completion_tokens = usage.completion_tokens if usage else 0

        # Calculate cost (per 1M tokens)
        cost_usd = (
            (prompt_tokens / 1_000_000) * self.COST_PER_1M_INPUT_TOKENS
            + (completion_tokens / 1_000_000) * self.COST_PER_1M_OUTPUT_TOKENS
        )

        return VisionResponse(
            content=response.choices[0].message.content or "",
            model=response.model,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            cost_usd=cost_usd,
            latency_ms=latency_ms,
        )
```

### 4. Integration Pattern

The pipeline connects `CohortChartDetector` → `SECClient` → `VisionClient` → `ChartValueExtractor`:

```python
# Pipeline: Detection → Fetch → Extract
import logging

from src.extraction.cohort_chart_detector import CohortChartDetector
from src.extraction.chart_value_extractor import ChartValueExtractor, ChartExtractionResult
from src.infra.sec_client import SECClient

logger = logging.getLogger(__name__)


def extract_chart_metrics(
    html_content: str,
    cik: str,
    accession_number: str,
) -> list[ChartExtractionResult]:
    """Extract metrics from cohort charts in a filing.

    This is the integration pattern showing how components connect.
    Actual implementation may vary.

    Args:
        html_content: Raw HTML content of the filing
        cik: SEC Central Index Key
        accession_number: SEC accession number (with dashes)

    Returns:
        List of extraction results (one per chart)
    """
    # Step 1: Detect chart candidates
    detector = CohortChartDetector()
    candidates = detector.detect_from_html(html_content)

    if not candidates:
        logger.info("No cohort chart candidates detected")
        return []

    # Step 2: Fetch and extract from each candidate
    sec_client = SECClient()
    extractor = ChartValueExtractor()  # Uses VisionClient internally

    results: list[ChartExtractionResult] = []
    for candidate in candidates:
        # Fetch image bytes from SEC EDGAR
        image_bytes = sec_client.fetch_image(
            cik=cik,
            accession_number=accession_number,
            filename=candidate.image_src,
        )

        if image_bytes is None:
            logger.warning(f"Failed to fetch image: {candidate.image_src}")
            continue  # 404 or network error

        # Extract values via Vision LLM
        result = extractor.extract(
            image_bytes=image_bytes,
            context=candidate.preceding_text,  # Helps LLM understand chart
            source_image=candidate.image_src,
        )
        results.append(result)

    logger.info(f"Extracted {len(results)} chart results from {len(candidates)} candidates")
    return results
```

### 5. GPT-4o Vision API Reference

For implementation reference, here's the validated API pattern:

```python
from openai import OpenAI
import base64

client = OpenAI()

def encode_image(image_bytes: bytes) -> str:
    return base64.standard_b64encode(image_bytes).decode("utf-8")

response = client.chat.completions.create(
    model="gpt-4o",
    messages=[
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "Extract data from this chart..."},
                {
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:image/jpeg;base64,{encode_image(image_bytes)}",
                        "detail": "high"  # "high" for accuracy, "low" for speed
                    }
                }
            ]
        }
    ],
    max_tokens=2000
)
```

**Cost**: ~$0.01-0.03 per image at "high" detail
**Latency**: ~2-5 seconds per image

### 6. Response Parsing

- Parse JSON from LLM response (handle markdown code blocks: ```json...```)
- Validate structure matches expected schema
- Handle missing fields gracefully (None/default values)
- Calculate confidence based on:
  - `has_y_axis_scale`: True = 0.8, False = 0.4 (values are estimates)
  - `len(cohorts)`: More cohorts extracted = higher confidence
  - Parse success: Valid JSON = +0.1

### 7. Error Handling

- **Image fetch failure**: Log warning, skip image (don't fail entire extraction)
- **LLM API error**: Let OpenAI client handle retries; on exhaustion, return result with error field set
- **JSON parse failure**: Log warning with raw response, return partial result with `error` field
- **No values extracted**: Return result with empty values list, confidence 0.0

### 8. Confidence Calibration

Based on VIS-1 research findings:

| Condition | Base Confidence |
|-----------|-----------------|
| Y-axis visible, values extracted | 0.8 |
| Y-axis visible, only labels extracted | 0.5 |
| No Y-axis, values reported | 0.3 (warn: may be estimates) |
| No Y-axis, only labels | 0.4 |
| Parse failure | 0.0 |

## Test Requirements

### Coverage Target: **≥ 85%** for `chart_value_extractor.py`, **≥ 90%** for `vision_client.py`

### Test Categories (25+ tests recommended)

1. **Image Fetcher Tests** (`test_sec_client.py`) (5-7 tests)
   - Successful image download (mock response)
   - 404 handling (return None)
   - Network error handling (return None)
   - Rate limiting respected
   - URL construction with edge cases (accession formats)
   - Content-Type validation (reject non-images)
   - Size limit enforcement (reject oversized images)

2. **VisionClient Tests** (`test_vision_client.py`) (6-8 tests)
   - MIME type detection for JPEG, PNG, GIF
   - Unknown format defaults to PNG
   - Base64 encoding correctness
   - Cost calculation accuracy (verify math)
   - Latency tracking
   - API error propagation

3. **Response Parsing Tests** (`test_chart_value_extractor.py`) (8-10 tests)
   - Valid JSON parsing with all fields
   - JSON wrapped in markdown code blocks
   - Missing optional fields handled
   - Invalid JSON returns error result
   - Empty cohorts list handled
   - Malformed values handled
   - Unicode in chart titles handled

4. **Confidence Calculation Tests** (5-7 tests)
   - Y-axis present vs absent
   - Multiple cohorts vs single cohort
   - Parse success vs failure impact
   - Edge case: confidence capped at 1.0
   - Edge case: confidence floored at 0.0

5. **Integration Tests** (3-4 tests)
   - End-to-end mock: fetch → extract → result
   - `CohortChartCandidate` input integration
   - Cost tracking accumulation

### Test Fixtures

Include realistic mock GPT-4o responses based on VIS-GPT4O-VALIDATION.md:

```python
# Mock response for Slack ARR chart (NO Y-axis scale)
MOCK_SLACK_RESPONSE = '''{
  "chart_title": "Annual Recurring Revenue (ARR) by Annual Cohort through January 31, 2019",
  "metric_type": "ARR",
  "has_y_axis_scale": false,
  "cohorts": [
    {"label": "FY2015", "values": [{"period": "FY2019", "value": null, "unit": "USD (no scale)"}]},
    {"label": "FY2016", "values": [{"period": "FY2019", "value": null, "unit": "USD (no scale)"}]},
    {"label": "FY2017", "values": [{"period": "FY2019", "value": null, "unit": "USD (no scale)"}]},
    {"label": "FY2018", "values": [{"period": "FY2019", "value": null, "unit": "USD (no scale)"}]},
    {"label": "FY2019", "values": [{"period": "FY2019", "value": null, "unit": "USD (no scale)"}]}
  ],
  "annotations": []
}'''

# Mock response for Farfetch GMV chart (HAS Y-axis scale)
MOCK_FARFETCH_RESPONSE = '''{
  "chart_title": null,
  "metric_type": "GMV",
  "has_y_axis_scale": true,
  "cohorts": [
    {"label": "2008", "values": [{"period": "2017", "value": 15, "unit": "USD millions"}]},
    {"label": "New in 2017", "values": [{"period": "2017", "value": 400, "unit": "USD millions"}]}
  ],
  "annotations": ["44.4% New Consumers in 2017", "55.6% Existing Consumers in 2017"]
}'''
```

### Known Edge Cases to Test

- Image with no Y-axis (Slack ARR chart behavior)
- Image with Y-axis but low resolution
- Chart with percentage annotations (Farfetch 44.4%/55.6%)
- Non-cohort chart fed to extractor (should return low confidence)
- Very large image (>10MB, should be rejected by fetch_image)
- Unsupported image format (e.g., TIFF, BMP)
- LLM returns malformed JSON
- LLM returns JSON wrapped in ```json code blocks

## Acceptance Criteria

- [ ] `sec_client.fetch_image()` downloads images from SEC EDGAR
- [ ] `fetch_image()` validates Content-Type and enforces size limits
- [ ] `VisionClient` correctly detects MIME types for JPEG, PNG, GIF
- [ ] `VisionClient` cost calculation uses per-1M-token pricing (not per-1K)
- [ ] `ChartValueExtractor` sends images to GPT-4o Vision and parses responses
- [ ] Structured `ExtractedChartValue` objects returned with all required fields
- [ ] Confidence scores reflect Y-axis visibility and extraction completeness
- [ ] Cost tracking integrated (per-image and cumulative)
- [ ] **25+ unit tests** covering all categories
- [ ] **Test coverage ≥ 85%** for `chart_value_extractor.py`
- [ ] **Test coverage ≥ 90%** for `vision_client.py`
- [ ] All tests pass
- [ ] `mypy src/llm/vision_client.py src/extraction/chart_value_extractor.py --strict` passes
- [ ] NO changes to existing extraction logic (additive only)
- [ ] Images without Y-axis scales flagged with lower confidence

## Do NOT

- Modify `cohort_chart_detector.py` (detection is separate from extraction)
- Add new LLM models - use existing GPT-4o configuration
- Implement caching in this task (deferred to VIS-2a)
- Create database schema for chart values (that's VIS-3)
- Build UI components (that's VIS-3)
- Process real filings - only test with mocked responses

## Verification Commands

```bash
# Run new tests
TEST_DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis_test" \
  python3 -m pytest tests/unit/llm/test_vision_client.py \
  tests/unit/extraction/test_chart_value_extractor.py \
  tests/unit/infra/test_sec_client.py -v --tb=short

# Check coverage for vision_client
TEST_DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis_test" \
  python3 -m pytest tests/unit/llm/test_vision_client.py \
  --cov=src.llm.vision_client --cov-report=term-missing --cov-fail-under=90

# Check coverage for chart_value_extractor
TEST_DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis_test" \
  python3 -m pytest tests/unit/extraction/test_chart_value_extractor.py \
  --cov=src.extraction.chart_value_extractor --cov-report=term-missing --cov-fail-under=85

# Type safety check
mypy src/llm/vision_client.py src/extraction/chart_value_extractor.py --strict

# Verify no changes to existing extraction
git diff src/extraction/cohort_chart_detector.py  # Should be empty
```

## Critical Evaluation Phase

**Task Size: L - Thorough evaluation**

After verification passes but BEFORE committing:

### 1. Code Quality Review
- [ ] No linting issues or type errors
- [ ] DRY principle followed
- [ ] Error handling appropriate (not over/under-engineered)
- [ ] Logging at appropriate levels (INFO for operations, WARNING for recoverable errors)
- [ ] All imports at top of file (no inline imports)

### 2. Test Coverage Assessment
- [ ] All edge cases from VIS-1 research covered
- [ ] Negative tests for API failures
- [ ] Mock responses match real GPT-4o Vision format (from VIS-GPT4O-VALIDATION.md)

### 3. Architecture Alignment
- [ ] Follows patterns in CLAUDE.md
- [ ] Uses existing infrastructure (no reinventing OpenAIClient)
- [ ] Provenance tracking maintained (source_image field)

### 4. Identify Improvements
Document potential improvements discovered:
- Performance optimizations (batching?)
- Additional metrics that could be extracted
- Better confidence calibration based on real data

### 5. User Approval (REQUIRED)
**STOP and present findings before committing.**

## Follow-Up Tasks (Out of Scope for VIS-2)

1. **VIS-2a: Image Caching** ✅ COMPLETE (2026-01-13) - Cache downloaded images to `data/images/{cik}/{accession}/` to avoid repeated SEC requests
2. **VIS-2b: Claude Vision Support** ~~DROPPED~~ (2026-01-13) - Research showed GPT-4o and Claude Vision perform equivalently; adding provider abstraction adds complexity with no benefit (YAGNI)
3. **VIS-2c: Batch Processing** ⏸️ DEFERRED (2026-01-13) - Premature optimization; no demonstrated bottleneck exists; revisit after IMG-1-8 complete with real usage data

## Expected Impact

**Before VIS-2**:
- Chart-based metrics (Slack ARR cohorts, Farfetch GMV cohorts) marked as `value_numeric = "chart"` in gold standard but NOT extractable
- These metrics cannot be processed by the automated pipeline

**After VIS-2**:
- Extraction pipeline can process chart images and return structured values
- Foundation for VIS-3 (review UI integration) and VIS-4 (database storage)
- Estimated coverage improvement: +2-5% on gold standard filings with chart metrics

## Reference

- **Research**: `docs/research/VIS-1-chart-extraction-results.md`, `docs/research/VIS-1a-extended-evaluation-results.md`
- **Validation**: `docs/research/VIS-GPT4O-VALIDATION.md` (GPT-4o test results)
- **Dependencies**: VIS-1 ✅, VIS-1a ✅
- **Related**: `src/extraction/cohort_chart_detector.py`, `src/llm/openai_client.py`

---

**Last Updated**: 2026-01-13
**Format Version**: 2.7
**Branch**: `feature/visual-exploration`
**Revision Notes**:
- Fixed VisionClient cost calculation (per-1M, not per-1K tokens)
- Added MIME type detection for JPEG/PNG/GIF (not just JPEG)
- Added `fetch_image()` size limit and Content-Type validation
- Added test fixtures from VIS-GPT4O-VALIDATION.md
- Added coverage targets per module (90% vision_client, 85% chart_value_extractor)
- Added `error` field to ChartExtractionResult
- Defined follow-up tasks (VIS-2a/b/c)
- Moved `import time` to top of file in code examples
