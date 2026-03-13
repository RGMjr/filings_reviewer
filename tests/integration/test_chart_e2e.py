"""
Integration test for the chart extraction end-to-end path.

Tests the Stage 4 → 5 → 6 → 7 → 9 path with a MockVisionClient
returning a realistic chart JSON response.

This test does NOT require OPENAI_API_KEY because it uses a mock client.
It also does NOT require TEST_DATABASE_URL as it doesn't hit a database.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.extraction_v2.models import (
    ChartType,
    ImageAsset,
    ImageClassification,
)
from src.extraction_v2.pipeline import PipelineConfig, PipelineContext, PipelineStage
from src.extraction_v2.stages.ocr_extraction import OCRExtractionStage
from src.llm.vision_client import VisionResponse


class MockVisionClient:
    """Mock vision client returning a realistic chart extraction response."""

    def __init__(self) -> None:
        self.call_count = 0
        self.model = "gpt-4o-mock"

    def analyze_image(
        self,
        image_bytes: bytes,
        prompt: str,
        detail: str = "high",
        max_tokens: int = 2000,
    ) -> VisionResponse:
        """Return a realistic chart JSON response."""
        self.call_count += 1
        response_data = {
            "chart_type": "bar",
            "title": "Monthly Active Users (millions)",
            "x_axis_label": "Quarter",
            "y_axis_label": "MAU (M)",
            "confidence": 0.88,
            "series": [
                {
                    "name": "MAU",
                    "points": [
                        {"x": "Q1 2023", "y": 42.1, "label": "42.1M"},
                        {"x": "Q2 2023", "y": 45.3, "label": "45.3M"},
                        {"x": "Q3 2023", "y": 48.7, "label": "48.7M"},
                        {"x": "Q4 2023", "y": 52.0, "label": "52.0M"},
                    ],
                }
            ],
            "annotations": [],
        }
        return VisionResponse(
            content=json.dumps(response_data),
            model="gpt-4o-mock",
            prompt_tokens=500,
            completion_tokens=200,
            cost_usd=0.01,
            latency_ms=250,
        )


@pytest.fixture
def tmp_chart_image(tmp_path: Path) -> Path:
    """Create a minimal PNG file for testing."""
    img = tmp_path / "mau_chart.png"
    img.write_bytes(
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
        b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01"
        b"\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
    )
    return img


class TestChartExtractionE2E:
    """End-to-end tests for chart OCR extraction through the pipeline stage."""

    def test_chart_extraction_produces_chart_data(
        self, tmp_chart_image: Path
    ) -> None:
        """OCRExtractionStage should extract chart data from a CHART image."""
        mock_client = MockVisionClient()
        stage = OCRExtractionStage(vision_client=mock_client)

        asset = ImageAsset(
            img_id="chart_mau_001",
            filename="mau_chart.png",
            file_path=str(tmp_chart_image),
            classification=ImageClassification.CHART,
            relevance_score=0.85,
            nearby_text="The following chart shows our Monthly Active Users over 2023.",
        )

        config = PipelineConfig(
            enable_chart_extraction=True,
            save_evidence_screenshots=False,
        )
        context = PipelineContext(
            html_path=tmp_chart_image.parent / "filing.html",
            filing_id=9999,
            config=config,
            images=[asset],
        )
        # Manually set html_path to a dummy (not needed for this stage)
        context.html_path = tmp_chart_image

        result = stage.process(context)

        assert result.success is True
        assert mock_client.call_count >= 1  # two-pass extraction makes 2 calls
        assert asset.processed is True
        assert asset.chart_data is not None
        assert asset.chart_data.chart_type == ChartType.BAR
        assert asset.chart_data.title == "Monthly Active Users (millions)"
        assert len(asset.chart_data.series) == 1
        assert len(asset.chart_data.series[0].points) == 4
        assert asset.confidence == pytest.approx(0.88)

    def test_chart_stage_result_metadata(
        self, tmp_chart_image: Path
    ) -> None:
        """StageResult should track chart API call counts."""
        mock_client = MockVisionClient()
        stage = OCRExtractionStage(vision_client=mock_client)

        asset = ImageAsset(
            img_id="chart_002",
            filename="chart.png",
            file_path=str(tmp_chart_image),
            classification=ImageClassification.CHART,
            relevance_score=0.90,
        )

        config = PipelineConfig(enable_chart_extraction=True)
        context = PipelineContext(
            html_path=tmp_chart_image,
            filing_id=1001,
            config=config,
            images=[asset],
        )

        result = stage.process(context)

        assert result.stage == PipelineStage.OCR_CHART_EXTRACTION
        assert result.metadata["chart_calls"] >= 1  # two-pass extraction counts each pass
        assert result.metadata["total_api_calls"] >= 1
        assert result.items_processed == 1

    def test_chart_not_processed_when_relevance_below_threshold(
        self, tmp_chart_image: Path
    ) -> None:
        """Charts below relevance threshold should be skipped."""
        mock_client = MockVisionClient()
        stage = OCRExtractionStage(vision_client=mock_client)

        asset = ImageAsset(
            img_id="chart_low_rel",
            filename="chart.png",
            file_path=str(tmp_chart_image),
            classification=ImageClassification.CHART,
            relevance_score=0.10,  # Below MIN_RELEVANCE_FOR_PROCESSING (0.3)
        )

        config = PipelineConfig()
        context = PipelineContext(
            html_path=tmp_chart_image,
            filing_id=1002,
            config=config,
            images=[asset],
        )

        stage.process(context)

        assert mock_client.call_count == 0
        assert asset.processed is False

    def test_fact_construction_chart_evidence(
        self, tmp_chart_image: Path
    ) -> None:
        """FactConstructionStage should generate chart evidence with screenshot_path."""
        from src.extraction_v2.models import (
            BoundValue,
            ChartData,
            ChartType,
            ImageAsset,
            ImageClassification,
            SourceLocator,
            Unit,
        )
        from src.extraction_v2.pipeline import PipelineConfig
        from src.extraction_v2.stages.fact_construction import FactConstructionStage

        evidence_dir = tmp_chart_image.parent / "evidence"

        asset = ImageAsset(
            img_id="chart_fc_001",
            filename="chart.png",
            file_path=str(tmp_chart_image),
            classification=ImageClassification.CHART,
            nearby_text="Monthly active users reached 52 million in Q4 2023.",
            chart_data=ChartData(
                chart_type=ChartType.BAR,
                title="Monthly Active Users",
                series=[],
            ),
        )

        config = PipelineConfig(
            save_evidence_screenshots=True,
            evidence_screenshot_dir=str(evidence_dir),
        )

        bv = BoundValue(
            candidate_id="cand_001",
            value=52.0,
            value_raw="52",
            unit=Unit.COUNT,
            binding_confidence=0.85,
            source_locator=SourceLocator(img_id="chart_fc_001"),
        )

        stage = FactConstructionStage()
        evidence = stage._generate_evidence(bv, {}, {}, {asset.img_id: asset}, config)

        # Screenshot should be copied
        assert evidence.screenshot_path is not None
        assert Path(evidence.screenshot_path).exists()

        # Snippet should include title
        assert "Monthly Active Users" in evidence.snippet_html

        # Context before from nearby text
        assert "52 million" in evidence.context_before
