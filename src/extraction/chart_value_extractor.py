"""Chart Value Extractor using LLM Vision.

Extracts structured metric data from chart images using GPT-4o Vision API.
Designed to work with cohort charts detected by CohortChartDetector.

Usage:
    extractor = ChartValueExtractor()
    result = extractor.extract(image_bytes, context="ARR by cohort chart")
    for value in result.values:
        print(f"{value.cohort_label}: {value.value} {value.unit}")
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any

from src.llm.vision_client import VisionClient, VisionResponse

logger = logging.getLogger(__name__)


# Default extraction prompt validated in VIS-GPT4O-VALIDATION.md
DEFAULT_EXTRACTION_PROMPT = """Extract all data series from this cohort chart as a structured table. Include:
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
}"""


@dataclass
class ExtractedChartValue:
    """Single extracted value from a chart.

    Attributes:
        metric_type: Type of metric (e.g., "ARR", "GMV", "retention")
        cohort_label: Cohort identifier (e.g., "FY2015", "2010 cohort")
        period: Time period for this value (e.g., "FY2019", "2017")
        value: Numeric value if extractable, None if no scale
        unit: Unit description (e.g., "USD millions", "percent")
        confidence: Confidence score 0.0-1.0
        source_image: Image filename for provenance tracking
    """

    metric_type: str
    cohort_label: str
    period: str
    value: float | None
    unit: str
    confidence: float
    source_image: str


@dataclass
class ChartExtractionResult:
    """Complete extraction result for one chart.

    Attributes:
        chart_title: Title of the chart if visible
        metric_type: Type of metric extracted
        values: List of extracted values
        has_y_axis_scale: Whether chart has readable Y-axis scale
        extraction_confidence: Overall confidence for this extraction
        raw_llm_response: Raw LLM response for debugging
        cost_usd: Cost of this extraction in USD
        latency_ms: Latency in milliseconds
        error: Error message if extraction failed
    """

    chart_title: str | None
    metric_type: str
    values: list[ExtractedChartValue] = field(default_factory=list)
    has_y_axis_scale: bool = False
    extraction_confidence: float = 0.0
    raw_llm_response: str = ""
    cost_usd: float = 0.0
    latency_ms: int = 0
    error: str | None = None


class ChartValueExtractor:
    """Extracts structured values from chart images using Vision LLM.

    Uses GPT-4o Vision to analyze chart images and extract cohort-based
    metrics. Handles JSON parsing, confidence calculation, and error recovery.

    Example:
        extractor = ChartValueExtractor()
        result = extractor.extract(
            image_bytes=open("chart.jpg", "rb").read(),
            source_image="chart.jpg",
        )
        if result.error:
            print(f"Extraction failed: {result.error}")
        else:
            for value in result.values:
                print(f"{value.cohort_label} @ {value.period}: {value.value}")
    """

    def __init__(
        self,
        vision_client: VisionClient | None = None,
        prompt: str = DEFAULT_EXTRACTION_PROMPT,
    ) -> None:
        """Initialize ChartValueExtractor.

        Args:
            vision_client: Optional VisionClient instance. If None, creates default.
            prompt: Extraction prompt to use. Defaults to validated prompt.
        """
        self._vision_client = vision_client
        self._prompt = prompt

    @property
    def vision_client(self) -> VisionClient:
        """Lazy-initialize vision client on first use."""
        if self._vision_client is None:
            self._vision_client = VisionClient()
        return self._vision_client

    def extract(
        self,
        image_bytes: bytes,
        source_image: str,
        context: str | None = None,
    ) -> ChartExtractionResult:
        """Extract metric values from a chart image.

        Args:
            image_bytes: Raw image bytes (JPEG, PNG, or GIF)
            source_image: Image filename for provenance tracking
            context: Optional context text (e.g., preceding text from HTML)

        Returns:
            ChartExtractionResult with extracted values and metadata
        """
        # Build prompt with optional context
        prompt = self._prompt
        if context:
            prompt = f"Context from document: {context}\n\n{prompt}"

        try:
            # Call Vision API
            response = self.vision_client.analyze_image(
                image_bytes=image_bytes,
                prompt=prompt,
            )

            # Parse response
            result = self._parse_response(response, source_image)
            return result

        except Exception as e:
            logger.warning(f"Vision API error for {source_image}: {e}")
            return ChartExtractionResult(
                chart_title=None,
                metric_type="unknown",
                values=[],
                has_y_axis_scale=False,
                extraction_confidence=0.0,
                raw_llm_response="",
                cost_usd=0.0,
                latency_ms=0,
                error=str(e),
            )

    def _parse_response(
        self,
        response: VisionResponse,
        source_image: str,
    ) -> ChartExtractionResult:
        """Parse Vision API response into ChartExtractionResult.

        Args:
            response: VisionResponse from Vision API
            source_image: Image filename for provenance

        Returns:
            Parsed ChartExtractionResult
        """
        raw_content = response.content

        # Try to extract JSON from response
        json_data = self._extract_json(raw_content)

        if json_data is None:
            logger.warning(f"Failed to parse JSON from response for {source_image}")
            return ChartExtractionResult(
                chart_title=None,
                metric_type="unknown",
                values=[],
                has_y_axis_scale=False,
                extraction_confidence=0.0,
                raw_llm_response=raw_content,
                cost_usd=response.cost_usd,
                latency_ms=response.latency_ms,
                error="Failed to parse JSON from LLM response",
            )

        # Extract fields from parsed JSON
        chart_title = json_data.get("chart_title")
        metric_type = json_data.get("metric_type", "unknown")
        has_y_axis_scale = json_data.get("has_y_axis_scale", False)
        cohorts = json_data.get("cohorts", [])

        # Convert cohorts to ExtractedChartValue objects
        values = self._extract_values(
            cohorts=cohorts,
            metric_type=metric_type,
            has_y_axis_scale=has_y_axis_scale,
            source_image=source_image,
        )

        # Calculate confidence
        confidence = self._calculate_confidence(
            has_y_axis_scale=has_y_axis_scale,
            values=values,
            json_parsed=True,
        )

        return ChartExtractionResult(
            chart_title=chart_title,
            metric_type=metric_type,
            values=values,
            has_y_axis_scale=has_y_axis_scale,
            extraction_confidence=confidence,
            raw_llm_response=raw_content,
            cost_usd=response.cost_usd,
            latency_ms=response.latency_ms,
            error=None,
        )

    def _extract_json(self, content: str) -> dict[str, Any] | None:
        """Extract JSON from LLM response content.

        Handles JSON wrapped in markdown code blocks.

        Args:
            content: Raw LLM response content

        Returns:
            Parsed JSON dict, or None if parsing failed
        """
        # Try to find JSON in markdown code blocks first
        # Pattern: ```json ... ``` or ``` ... ```
        code_block_pattern = r"```(?:json)?\s*([\s\S]*?)```"
        match = re.search(code_block_pattern, content)
        if match:
            json_str = match.group(1).strip()
            try:
                result: dict[str, Any] = json.loads(json_str)
                return result
            except json.JSONDecodeError:
                pass  # Try other methods

        # Try parsing the entire content as JSON
        try:
            parsed: dict[str, Any] = json.loads(content)
            return parsed
        except json.JSONDecodeError:
            pass

        # Try to find JSON object in content
        # Look for first { and last }
        start = content.find("{")
        end = content.rfind("}")
        if start != -1 and end != -1 and end > start:
            json_str = content[start : end + 1]
            try:
                parsed = json.loads(json_str)
                return parsed
            except json.JSONDecodeError:
                pass

        return None

    def _extract_values(
        self,
        cohorts: list[dict[str, Any]],
        metric_type: str,
        has_y_axis_scale: bool,
        source_image: str,
    ) -> list[ExtractedChartValue]:
        """Convert cohort data to ExtractedChartValue objects.

        Args:
            cohorts: List of cohort dicts from JSON
            metric_type: Metric type string
            has_y_axis_scale: Whether Y-axis scale was visible
            source_image: Image filename for provenance

        Returns:
            List of ExtractedChartValue objects
        """
        values: list[ExtractedChartValue] = []

        # Base confidence for individual values
        base_confidence = 0.8 if has_y_axis_scale else 0.4

        for cohort in cohorts:
            cohort_label = cohort.get("label", "unknown")
            cohort_values = cohort.get("values", [])

            for val_data in cohort_values:
                period = val_data.get("period", "unknown")
                raw_value = val_data.get("value")
                unit = val_data.get("unit", "unknown")

                # Convert value to float or None
                numeric_value: float | None = None
                if raw_value is not None:
                    try:
                        numeric_value = float(raw_value)
                    except (ValueError, TypeError):
                        # Value is not numeric (e.g., "N/A", null)
                        numeric_value = None

                # Adjust confidence based on value presence
                confidence = base_confidence
                if numeric_value is None and has_y_axis_scale:
                    # Had scale but couldn't extract value - lower confidence
                    confidence = 0.5
                elif numeric_value is not None and not has_y_axis_scale:
                    # Extracted value without scale - warn, very low confidence
                    confidence = 0.3
                    logger.warning(
                        f"Value extracted without Y-axis scale: "
                        f"{cohort_label}@{period}={numeric_value} (may be estimate)"
                    )

                values.append(
                    ExtractedChartValue(
                        metric_type=metric_type,
                        cohort_label=cohort_label,
                        period=period,
                        value=numeric_value,
                        unit=unit,
                        confidence=confidence,
                        source_image=source_image,
                    )
                )

        return values

    def _calculate_confidence(
        self,
        has_y_axis_scale: bool,
        values: list[ExtractedChartValue],
        json_parsed: bool,
    ) -> float:
        """Calculate overall extraction confidence.

        Based on VIS-1 research findings:
        - Y-axis visible, values extracted: 0.8
        - Y-axis visible, only labels extracted: 0.5
        - No Y-axis, values reported: 0.3 (warn: may be estimates)
        - No Y-axis, only labels: 0.4
        - Parse failure: 0.0

        Args:
            has_y_axis_scale: Whether Y-axis scale was visible
            values: List of extracted values
            json_parsed: Whether JSON was successfully parsed

        Returns:
            Confidence score 0.0-1.0
        """
        if not json_parsed:
            return 0.0

        # Check if any values were actually extracted (not None)
        has_numeric_values = any(v.value is not None for v in values)

        if has_y_axis_scale:
            if has_numeric_values:
                confidence = 0.8
            else:
                confidence = 0.5
        else:
            if has_numeric_values:
                # Values without scale are likely estimates
                confidence = 0.3
            else:
                # Labels only, no values - reasonable for no-scale charts
                confidence = 0.4

        # Bonus for multiple cohorts (up to 0.1)
        unique_cohorts = len(set(v.cohort_label for v in values))
        if unique_cohorts >= 3:
            confidence += 0.1
        elif unique_cohorts >= 2:
            confidence += 0.05

        # Bonus for successful JSON parse
        confidence += 0.05

        return min(1.0, max(0.0, confidence))
