"""Unit tests for ChartValueExtractor.

Tests for chart value extraction using Vision LLM, including:
- JSON parsing from LLM responses
- Response handling with various formats
- Confidence calculation
- Value extraction from cohort data
- Error handling
"""

from unittest.mock import MagicMock, patch

import pytest

from src.extraction.chart_value_extractor import (
    DEFAULT_EXTRACTION_PROMPT,
    ChartExtractionResult,
    ChartValueExtractor,
    ExtractedChartValue,
)
from src.llm.vision_client import VisionResponse

# Mock responses from VIS-GPT4O-VALIDATION.md
MOCK_SLACK_RESPONSE = """{
  "chart_title": "Annual Recurring Revenue (ARR) by Annual Cohort through January 31, 2019",
  "metric_type": "ARR",
  "has_y_axis_scale": false,
  "cohorts": [
    {
      "label": "FY2015",
      "values": [
        { "period": "FY2015", "value": null, "unit": "USD (no scale)" },
        { "period": "FY2016", "value": null, "unit": "USD (no scale)" },
        { "period": "FY2019", "value": null, "unit": "USD (no scale)" }
      ]
    },
    {
      "label": "FY2016",
      "values": [
        { "period": "FY2016", "value": null, "unit": "USD (no scale)" },
        { "period": "FY2019", "value": null, "unit": "USD (no scale)" }
      ]
    }
  ],
  "annotations": []
}"""

MOCK_FARFETCH_RESPONSE = """{
  "chart_title": null,
  "metric_type": "GMV",
  "has_y_axis_scale": true,
  "cohorts": [
    {
      "label": "2008",
      "values": [
        {"period": "2015", "value": 15, "unit": "USD millions"},
        {"period": "2016", "value": 15, "unit": "USD millions"},
        {"period": "2017", "value": 15, "unit": "USD millions"}
      ]
    },
    {
      "label": "New in 2017",
      "values": [
        {"period": "2017", "value": 400, "unit": "USD millions"}
      ]
    }
  ],
  "annotations": ["44.4% New Consumers in 2017", "55.6% Existing Consumers in 2017"]
}"""


class TestExtractedChartValue:
    """Test suite for ExtractedChartValue dataclass."""

    def test_create_extracted_value(self):
        """Test creating an ExtractedChartValue instance."""
        value = ExtractedChartValue(
            metric_type="ARR",
            cohort_label="FY2015",
            period="FY2019",
            value=100.5,
            unit="USD millions",
            confidence=0.8,
            source_image="chart.jpg",
        )

        assert value.metric_type == "ARR"
        assert value.cohort_label == "FY2015"
        assert value.period == "FY2019"
        assert value.value == 100.5
        assert value.unit == "USD millions"
        assert value.confidence == 0.8
        assert value.source_image == "chart.jpg"

    def test_extracted_value_with_none_value(self):
        """Test creating ExtractedChartValue with None numeric value."""
        value = ExtractedChartValue(
            metric_type="ARR",
            cohort_label="FY2015",
            period="FY2019",
            value=None,
            unit="USD (no scale)",
            confidence=0.4,
            source_image="chart.jpg",
        )

        assert value.value is None


class TestChartExtractionResult:
    """Test suite for ChartExtractionResult dataclass."""

    def test_create_extraction_result(self):
        """Test creating a ChartExtractionResult instance."""
        result = ChartExtractionResult(
            chart_title="Test Chart",
            metric_type="ARR",
            values=[],
            has_y_axis_scale=True,
            extraction_confidence=0.8,
            raw_llm_response="{}",
            cost_usd=0.01,
            latency_ms=2000,
            error=None,
        )

        assert result.chart_title == "Test Chart"
        assert result.metric_type == "ARR"
        assert result.values == []
        assert result.has_y_axis_scale is True
        assert result.extraction_confidence == 0.8
        assert result.error is None

    def test_extraction_result_with_error(self):
        """Test creating ChartExtractionResult with error."""
        result = ChartExtractionResult(
            chart_title=None,
            metric_type="unknown",
            values=[],
            has_y_axis_scale=False,
            extraction_confidence=0.0,
            raw_llm_response="",
            cost_usd=0.0,
            latency_ms=0,
            error="API connection failed",
        )

        assert result.error == "API connection failed"


class TestChartValueExtractorInit:
    """Test suite for ChartValueExtractor initialization."""

    def test_default_init(self):
        """Test default initialization."""
        extractor = ChartValueExtractor()
        assert extractor._vision_client is None
        assert extractor._prompt == DEFAULT_EXTRACTION_PROMPT

    def test_custom_prompt(self):
        """Test initialization with custom prompt."""
        custom_prompt = "Extract chart data"
        extractor = ChartValueExtractor(prompt=custom_prompt)
        assert extractor._prompt == custom_prompt

    @patch("src.extraction.chart_value_extractor.VisionClient")
    def test_custom_vision_client(self, mock_vision_client):
        """Test initialization with custom VisionClient."""
        mock_client = MagicMock()
        extractor = ChartValueExtractor(vision_client=mock_client)
        assert extractor._vision_client is mock_client

    @patch("src.extraction.chart_value_extractor.VisionClient")
    def test_lazy_vision_client_creation(self, mock_vision_client):
        """Test that vision_client is lazy-initialized."""
        extractor = ChartValueExtractor()

        # Client should not be created yet
        mock_vision_client.assert_not_called()

        # Access the property
        _ = extractor.vision_client

        # Now client should be created
        mock_vision_client.assert_called_once()


class TestJsonParsing:
    """Test suite for JSON parsing from LLM responses."""

    def test_parse_plain_json(self):
        """Test parsing plain JSON response."""
        extractor = ChartValueExtractor()
        json_str = '{"chart_title": "Test", "metric_type": "ARR", "has_y_axis_scale": true, "cohorts": []}'

        result = extractor._extract_json(json_str)

        assert result is not None
        assert result["chart_title"] == "Test"
        assert result["metric_type"] == "ARR"

    def test_parse_json_in_code_block(self):
        """Test parsing JSON wrapped in markdown code block."""
        extractor = ChartValueExtractor()
        json_str = """Here is the data:

```json
{"chart_title": "Test", "metric_type": "GMV", "has_y_axis_scale": false, "cohorts": []}
```

Hope this helps!"""

        result = extractor._extract_json(json_str)

        assert result is not None
        assert result["metric_type"] == "GMV"

    def test_parse_json_in_generic_code_block(self):
        """Test parsing JSON wrapped in generic code block (no json marker)."""
        extractor = ChartValueExtractor()
        json_str = """```
{"chart_title": "Test", "metric_type": "retention", "has_y_axis_scale": true, "cohorts": []}
```"""

        result = extractor._extract_json(json_str)

        assert result is not None
        assert result["metric_type"] == "retention"

    def test_parse_json_with_surrounding_text(self):
        """Test parsing JSON with text before and after."""
        extractor = ChartValueExtractor()
        json_str = """Based on the chart, I extracted:
{"chart_title": "Revenue", "metric_type": "ARR", "has_y_axis_scale": true, "cohorts": []}
This shows the annual revenue."""

        result = extractor._extract_json(json_str)

        assert result is not None
        assert result["chart_title"] == "Revenue"

    def test_parse_invalid_json_returns_none(self):
        """Test that invalid JSON returns None."""
        extractor = ChartValueExtractor()

        result = extractor._extract_json("not valid json at all")

        assert result is None

    def test_parse_partial_json_returns_none(self):
        """Test that partial JSON returns None."""
        extractor = ChartValueExtractor()

        result = extractor._extract_json('{"chart_title": "Test"')

        assert result is None

    def test_parse_empty_string_returns_none(self):
        """Test that empty string returns None."""
        extractor = ChartValueExtractor()

        result = extractor._extract_json("")

        assert result is None

    def test_parse_nested_json(self):
        """Test parsing nested JSON structure."""
        extractor = ChartValueExtractor()

        result = extractor._extract_json(MOCK_SLACK_RESPONSE)

        assert result is not None
        assert result["metric_type"] == "ARR"
        assert len(result["cohorts"]) == 2
        assert result["cohorts"][0]["label"] == "FY2015"

    def test_parse_json_with_unicode(self):
        """Test parsing JSON with unicode characters."""
        extractor = ChartValueExtractor()
        json_str = '{"chart_title": "Réservation par Cohorte", "metric_type": "GMV", "has_y_axis_scale": true, "cohorts": []}'

        result = extractor._extract_json(json_str)

        assert result is not None
        assert result["chart_title"] == "Réservation par Cohorte"


class TestValueExtraction:
    """Test suite for extracting values from cohort data."""

    def test_extract_values_with_y_axis(self):
        """Test extracting values when Y-axis scale is present."""
        extractor = ChartValueExtractor()

        cohorts = [
            {
                "label": "2008",
                "values": [
                    {"period": "2017", "value": 15, "unit": "USD millions"},
                ],
            },
            {
                "label": "New in 2017",
                "values": [
                    {"period": "2017", "value": 400, "unit": "USD millions"},
                ],
            },
        ]

        values = extractor._extract_values(
            cohorts=cohorts,
            metric_type="GMV",
            has_y_axis_scale=True,
            source_image="chart.jpg",
        )

        assert len(values) == 2
        assert values[0].value == 15.0
        assert values[0].confidence == 0.8  # High confidence with Y-axis
        assert values[1].value == 400.0

    def test_extract_values_without_y_axis(self):
        """Test extracting values when Y-axis scale is absent."""
        extractor = ChartValueExtractor()

        cohorts = [
            {
                "label": "FY2015",
                "values": [
                    {"period": "FY2019", "value": None, "unit": "USD (no scale)"},
                ],
            },
        ]

        values = extractor._extract_values(
            cohorts=cohorts,
            metric_type="ARR",
            has_y_axis_scale=False,
            source_image="chart.jpg",
        )

        assert len(values) == 1
        assert values[0].value is None
        assert values[0].confidence == 0.4  # Lower confidence without Y-axis

    def test_extract_values_numeric_conversion(self):
        """Test that numeric values are converted to float."""
        extractor = ChartValueExtractor()

        cohorts = [
            {
                "label": "Test",
                "values": [
                    {"period": "2024", "value": 100, "unit": "dollars"},  # int
                    {"period": "2023", "value": "50.5", "unit": "dollars"},  # string
                ],
            },
        ]

        values = extractor._extract_values(
            cohorts=cohorts,
            metric_type="revenue",
            has_y_axis_scale=True,
            source_image="chart.jpg",
        )

        assert len(values) == 2
        assert values[0].value == 100.0
        assert isinstance(values[0].value, float)
        # Note: "50.5" as string will be converted to float

    def test_extract_values_non_numeric_handled(self):
        """Test that non-numeric values are handled gracefully."""
        extractor = ChartValueExtractor()

        cohorts = [
            {
                "label": "Test",
                "values": [
                    {"period": "2024", "value": "N/A", "unit": "unknown"},
                ],
            },
        ]

        values = extractor._extract_values(
            cohorts=cohorts,
            metric_type="revenue",
            has_y_axis_scale=True,
            source_image="chart.jpg",
        )

        assert len(values) == 1
        assert values[0].value is None
        assert values[0].confidence == 0.5  # Had scale but couldn't extract

    def test_extract_values_preserves_metadata(self):
        """Test that metadata is preserved in extracted values."""
        extractor = ChartValueExtractor()

        cohorts = [
            {
                "label": "FY2015",
                "values": [
                    {"period": "FY2019", "value": 100, "unit": "USD millions"},
                ],
            },
        ]

        values = extractor._extract_values(
            cohorts=cohorts,
            metric_type="ARR",
            has_y_axis_scale=True,
            source_image="test_chart.jpg",
        )

        assert values[0].metric_type == "ARR"
        assert values[0].cohort_label == "FY2015"
        assert values[0].period == "FY2019"
        assert values[0].unit == "USD millions"
        assert values[0].source_image == "test_chart.jpg"

    def test_extract_values_empty_cohorts(self):
        """Test extraction with empty cohorts list."""
        extractor = ChartValueExtractor()

        values = extractor._extract_values(
            cohorts=[],
            metric_type="ARR",
            has_y_axis_scale=True,
            source_image="chart.jpg",
        )

        assert values == []

    def test_extract_values_warns_on_estimate(self):
        """Test that extracting values without scale logs warning."""
        extractor = ChartValueExtractor()

        cohorts = [
            {
                "label": "Test",
                "values": [
                    {"period": "2024", "value": 100, "unit": "USD"},  # Value without scale
                ],
            },
        ]

        values = extractor._extract_values(
            cohorts=cohorts,
            metric_type="revenue",
            has_y_axis_scale=False,  # No scale
            source_image="chart.jpg",
        )

        # Value extracted but low confidence
        assert values[0].value == 100.0
        assert values[0].confidence == 0.3  # Very low confidence


class TestConfidenceCalculation:
    """Test suite for confidence calculation."""

    def test_confidence_y_axis_with_values(self):
        """Test confidence when Y-axis present and values extracted."""
        extractor = ChartValueExtractor()

        values = [
            ExtractedChartValue(
                metric_type="ARR", cohort_label="FY2015", period="FY2019",
                value=100.0, unit="USD", confidence=0.8, source_image="chart.jpg"
            ),
        ]

        confidence = extractor._calculate_confidence(
            has_y_axis_scale=True,
            values=values,
            json_parsed=True,
        )

        # Base 0.8 + parse bonus 0.05
        assert confidence == pytest.approx(0.85, rel=0.01)

    def test_confidence_y_axis_no_values(self):
        """Test confidence when Y-axis present but no values extracted."""
        extractor = ChartValueExtractor()

        values = [
            ExtractedChartValue(
                metric_type="ARR", cohort_label="FY2015", period="FY2019",
                value=None, unit="USD", confidence=0.5, source_image="chart.jpg"
            ),
        ]

        confidence = extractor._calculate_confidence(
            has_y_axis_scale=True,
            values=values,
            json_parsed=True,
        )

        # Base 0.5 + parse bonus 0.05
        assert confidence == pytest.approx(0.55, rel=0.01)

    def test_confidence_no_y_axis_with_values(self):
        """Test confidence when no Y-axis but values reported (estimates)."""
        extractor = ChartValueExtractor()

        values = [
            ExtractedChartValue(
                metric_type="ARR", cohort_label="FY2015", period="FY2019",
                value=100.0, unit="USD", confidence=0.3, source_image="chart.jpg"
            ),
        ]

        confidence = extractor._calculate_confidence(
            has_y_axis_scale=False,
            values=values,
            json_parsed=True,
        )

        # Base 0.3 + parse bonus 0.05
        assert confidence == pytest.approx(0.35, rel=0.01)

    def test_confidence_no_y_axis_no_values(self):
        """Test confidence when no Y-axis and no values (labels only)."""
        extractor = ChartValueExtractor()

        values = [
            ExtractedChartValue(
                metric_type="ARR", cohort_label="FY2015", period="FY2019",
                value=None, unit="USD (no scale)", confidence=0.4, source_image="chart.jpg"
            ),
        ]

        confidence = extractor._calculate_confidence(
            has_y_axis_scale=False,
            values=values,
            json_parsed=True,
        )

        # Base 0.4 + parse bonus 0.05
        assert confidence == pytest.approx(0.45, rel=0.01)

    def test_confidence_json_parse_failure(self):
        """Test confidence is 0 when JSON parsing fails."""
        extractor = ChartValueExtractor()

        confidence = extractor._calculate_confidence(
            has_y_axis_scale=True,
            values=[],
            json_parsed=False,
        )

        assert confidence == 0.0

    def test_confidence_bonus_for_multiple_cohorts(self):
        """Test confidence bonus for multiple cohorts."""
        extractor = ChartValueExtractor()

        values = [
            ExtractedChartValue(
                metric_type="ARR", cohort_label="FY2015", period="FY2019",
                value=100.0, unit="USD", confidence=0.8, source_image="chart.jpg"
            ),
            ExtractedChartValue(
                metric_type="ARR", cohort_label="FY2016", period="FY2019",
                value=150.0, unit="USD", confidence=0.8, source_image="chart.jpg"
            ),
            ExtractedChartValue(
                metric_type="ARR", cohort_label="FY2017", period="FY2019",
                value=200.0, unit="USD", confidence=0.8, source_image="chart.jpg"
            ),
        ]

        confidence = extractor._calculate_confidence(
            has_y_axis_scale=True,
            values=values,
            json_parsed=True,
        )

        # Base 0.8 + parse 0.05 + 3 cohorts bonus 0.1 = 0.95
        assert confidence == pytest.approx(0.95, rel=0.01)

    def test_confidence_capped_at_1(self):
        """Test confidence is capped at 1.0."""
        extractor = ChartValueExtractor()

        values = [
            ExtractedChartValue(
                metric_type="ARR", cohort_label=f"FY{year}", period="FY2019",
                value=100.0, unit="USD", confidence=0.8, source_image="chart.jpg"
            )
            for year in range(2015, 2025)  # 10 unique cohorts
        ]

        confidence = extractor._calculate_confidence(
            has_y_axis_scale=True,
            values=values,
            json_parsed=True,
        )

        # Base 0.8 + parse 0.05 + cohort bonus 0.1 (max) = 0.95
        # The max cap ensures we don't exceed 1.0
        assert confidence <= 1.0
        assert confidence == pytest.approx(0.95, rel=0.01)


class TestExtractMethod:
    """Test suite for the main extract() method."""

    def test_extract_success(self):
        """Test successful extraction."""
        mock_vision_client = MagicMock()
        mock_vision_client.analyze_image.return_value = VisionResponse(
            content=MOCK_FARFETCH_RESPONSE,
            model="gpt-4o",
            prompt_tokens=1000,
            completion_tokens=500,
            cost_usd=0.0075,
            latency_ms=2500,
        )

        extractor = ChartValueExtractor(vision_client=mock_vision_client)
        result = extractor.extract(
            image_bytes=b"\xff\xd8\xff\xe0test",
            source_image="farfetch_gmv.jpg",
        )

        assert result.error is None
        assert result.metric_type == "GMV"
        assert result.has_y_axis_scale is True
        assert len(result.values) == 4  # 3 values for 2008 + 1 for New in 2017
        assert result.cost_usd == 0.0075
        assert result.latency_ms == 2500

    def test_extract_with_context(self):
        """Test extraction with context text."""
        mock_vision_client = MagicMock()
        mock_vision_client.analyze_image.return_value = VisionResponse(
            content=MOCK_SLACK_RESPONSE,
            model="gpt-4o",
            prompt_tokens=1000,
            completion_tokens=500,
            cost_usd=0.0075,
            latency_ms=2500,
        )

        extractor = ChartValueExtractor(vision_client=mock_vision_client)
        extractor.extract(
            image_bytes=b"\xff\xd8\xff\xe0test",
            source_image="slack_arr.jpg",
            context="This shows ARR by cohort through FY2019",
        )

        # Verify context was included in the prompt
        call_args = mock_vision_client.analyze_image.call_args
        prompt = call_args.kwargs["prompt"]
        assert "This shows ARR by cohort through FY2019" in prompt

    def test_extract_api_error_returns_error_result(self):
        """Test that API errors return result with error field."""
        mock_vision_client = MagicMock()
        mock_vision_client.analyze_image.side_effect = Exception("API connection failed")

        extractor = ChartValueExtractor(vision_client=mock_vision_client)
        result = extractor.extract(
            image_bytes=b"\xff\xd8\xff\xe0test",
            source_image="chart.jpg",
        )

        assert result.error == "API connection failed"
        assert result.metric_type == "unknown"
        assert result.values == []
        assert result.extraction_confidence == 0.0

    def test_extract_json_parse_error_returns_error_result(self):
        """Test that JSON parse errors return result with error field."""
        mock_vision_client = MagicMock()
        mock_vision_client.analyze_image.return_value = VisionResponse(
            content="This is not valid JSON",
            model="gpt-4o",
            prompt_tokens=1000,
            completion_tokens=100,
            cost_usd=0.003,
            latency_ms=1500,
        )

        extractor = ChartValueExtractor(vision_client=mock_vision_client)
        result = extractor.extract(
            image_bytes=b"\xff\xd8\xff\xe0test",
            source_image="chart.jpg",
        )

        assert result.error == "Failed to parse JSON from LLM response"
        assert result.raw_llm_response == "This is not valid JSON"
        assert result.cost_usd == 0.003  # Cost still tracked

    def test_extract_no_y_axis_chart(self):
        """Test extraction from chart without Y-axis scale."""
        mock_vision_client = MagicMock()
        mock_vision_client.analyze_image.return_value = VisionResponse(
            content=MOCK_SLACK_RESPONSE,
            model="gpt-4o",
            prompt_tokens=1000,
            completion_tokens=500,
            cost_usd=0.0075,
            latency_ms=2500,
        )

        extractor = ChartValueExtractor(vision_client=mock_vision_client)
        result = extractor.extract(
            image_bytes=b"\xff\xd8\xff\xe0test",
            source_image="slack_arr.jpg",
        )

        assert result.has_y_axis_scale is False
        assert result.chart_title == "Annual Recurring Revenue (ARR) by Annual Cohort through January 31, 2019"
        # All values should be None
        for value in result.values:
            assert value.value is None

    def test_extract_preserves_raw_response(self):
        """Test that raw LLM response is preserved."""
        mock_vision_client = MagicMock()
        mock_vision_client.analyze_image.return_value = VisionResponse(
            content=MOCK_FARFETCH_RESPONSE,
            model="gpt-4o",
            prompt_tokens=1000,
            completion_tokens=500,
            cost_usd=0.0075,
            latency_ms=2500,
        )

        extractor = ChartValueExtractor(vision_client=mock_vision_client)
        result = extractor.extract(
            image_bytes=b"\xff\xd8\xff\xe0test",
            source_image="chart.jpg",
        )

        assert result.raw_llm_response == MOCK_FARFETCH_RESPONSE


class TestDefaultExtractionPrompt:
    """Test suite for the default extraction prompt."""

    def test_prompt_contains_key_instructions(self):
        """Test that default prompt contains key extraction instructions."""
        assert "chart title" in DEFAULT_EXTRACTION_PROMPT.lower()
        assert "metric type" in DEFAULT_EXTRACTION_PROMPT.lower()
        assert "cohort" in DEFAULT_EXTRACTION_PROMPT.lower()
        assert "y-axis" in DEFAULT_EXTRACTION_PROMPT.lower()
        assert "json" in DEFAULT_EXTRACTION_PROMPT.lower()

    def test_prompt_warns_about_no_scale(self):
        """Test that prompt warns not to estimate without scale."""
        assert "no numeric scale" in DEFAULT_EXTRACTION_PROMPT.lower()
        assert "do not estimate" in DEFAULT_EXTRACTION_PROMPT.lower()


class TestMissingFields:
    """Test suite for handling missing or malformed JSON fields."""

    def test_missing_chart_title(self):
        """Test handling of missing chart_title field."""
        mock_vision_client = MagicMock()
        mock_vision_client.analyze_image.return_value = VisionResponse(
            content='{"metric_type": "ARR", "has_y_axis_scale": true, "cohorts": []}',
            model="gpt-4o",
            prompt_tokens=100,
            completion_tokens=50,
            cost_usd=0.001,
            latency_ms=1000,
        )

        extractor = ChartValueExtractor(vision_client=mock_vision_client)
        result = extractor.extract(
            image_bytes=b"\xff\xd8\xff\xe0test",
            source_image="chart.jpg",
        )

        assert result.chart_title is None
        assert result.error is None

    def test_missing_metric_type(self):
        """Test handling of missing metric_type field."""
        mock_vision_client = MagicMock()
        mock_vision_client.analyze_image.return_value = VisionResponse(
            content='{"chart_title": "Test", "has_y_axis_scale": true, "cohorts": []}',
            model="gpt-4o",
            prompt_tokens=100,
            completion_tokens=50,
            cost_usd=0.001,
            latency_ms=1000,
        )

        extractor = ChartValueExtractor(vision_client=mock_vision_client)
        result = extractor.extract(
            image_bytes=b"\xff\xd8\xff\xe0test",
            source_image="chart.jpg",
        )

        assert result.metric_type == "unknown"

    def test_missing_has_y_axis_scale(self):
        """Test handling of missing has_y_axis_scale field."""
        mock_vision_client = MagicMock()
        mock_vision_client.analyze_image.return_value = VisionResponse(
            content='{"chart_title": "Test", "metric_type": "ARR", "cohorts": []}',
            model="gpt-4o",
            prompt_tokens=100,
            completion_tokens=50,
            cost_usd=0.001,
            latency_ms=1000,
        )

        extractor = ChartValueExtractor(vision_client=mock_vision_client)
        result = extractor.extract(
            image_bytes=b"\xff\xd8\xff\xe0test",
            source_image="chart.jpg",
        )

        assert result.has_y_axis_scale is False  # Defaults to False

    def test_missing_cohorts(self):
        """Test handling of missing cohorts field."""
        mock_vision_client = MagicMock()
        mock_vision_client.analyze_image.return_value = VisionResponse(
            content='{"chart_title": "Test", "metric_type": "ARR", "has_y_axis_scale": true}',
            model="gpt-4o",
            prompt_tokens=100,
            completion_tokens=50,
            cost_usd=0.001,
            latency_ms=1000,
        )

        extractor = ChartValueExtractor(vision_client=mock_vision_client)
        result = extractor.extract(
            image_bytes=b"\xff\xd8\xff\xe0test",
            source_image="chart.jpg",
        )

        assert result.values == []

    def test_malformed_cohort_values(self):
        """Test handling of malformed cohort value entries."""
        mock_vision_client = MagicMock()
        mock_vision_client.analyze_image.return_value = VisionResponse(
            content='{"chart_title": "Test", "metric_type": "ARR", "has_y_axis_scale": true, "cohorts": [{"label": "FY2015", "values": [{"period": "FY2019"}]}]}',
            model="gpt-4o",
            prompt_tokens=100,
            completion_tokens=50,
            cost_usd=0.001,
            latency_ms=1000,
        )

        extractor = ChartValueExtractor(vision_client=mock_vision_client)
        result = extractor.extract(
            image_bytes=b"\xff\xd8\xff\xe0test",
            source_image="chart.jpg",
        )

        # Should handle gracefully
        assert len(result.values) == 1
        assert result.values[0].value is None  # Missing value defaults to None
        assert result.values[0].unit == "unknown"  # Missing unit defaults to unknown
