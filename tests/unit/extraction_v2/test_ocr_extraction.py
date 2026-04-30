"""
Unit tests for V2 OCR & Chart Extraction Stage.

Tests:
- Table image OCR extraction
- Chart extraction with labeled values
- Chart extraction without labels (manual capture)
- Low confidence handling
- Relevance filtering
- Already processed filtering
- API error handling
- API call limits
- Empty batch handling
- Pipeline stage integration
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


@pytest.fixture(autouse=True)
def _route_image_cache_to_tmp(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Route LocalFilesystemStorage under tmp_path for all tests in this module.

    Tests that write bytes to ``tmp_path / filename`` can then pass
    ``file_path=filename`` (the storage key) to ImageAsset; downstream
    ``storage.get_bytes(key)`` reads the correct file.
    """
    from src.infra.image_storage import get_image_storage
    from src.infra.paths import image_cache_dir

    monkeypatch.setenv("IMAGE_CACHE_DIR", str(tmp_path))
    monkeypatch.delenv("R2_BUCKET", raising=False)
    image_cache_dir.cache_clear()
    get_image_storage.cache_clear()
    yield
    image_cache_dir.cache_clear()
    get_image_storage.cache_clear()


@pytest.fixture(autouse=True)
def _route_triage_ocr_through_injected_client(monkeypatch: pytest.MonkeyPatch) -> None:
    """PR 2 compatibility: route triage OCR calls through the injected vision_client.

    PR 2 sends full_page_ocr and prescan calls through _build_cheap_ocr_client,
    which builds a real Gemini VisionClient. Tests in this module inject a mock
    via OCRExtractionStage(vision_client=mock); this fixture bridges the gap by
    making _get_full_page_ocr_client / _get_prescan_client return the injected
    client so all unit tests remain hermetic.
    """

    def _get_full_page_ocr_client(self, context):  # type: ignore[override]
        return self._vision_client

    def _get_prescan_client(self, context):  # type: ignore[override]
        return self._vision_client

    monkeypatch.setattr(OCRExtractionStage, "_get_full_page_ocr_client", _get_full_page_ocr_client)
    monkeypatch.setattr(OCRExtractionStage, "_get_prescan_client", _get_prescan_client)


class MockVisionClient:
    """Mock vision client for testing that inherits from VisionClient."""

    def __init__(self, responses: list[VisionResponse]) -> None:
        """Initialize mock with responses list."""
        # Don't call super().__init__() to avoid OpenAI client creation
        self.responses = responses
        self.call_count = 0
        self.model = "gpt-4o-mock"

    def analyze_image(
        self,
        image_bytes: bytes,
        prompt: str,
        detail: str = "high",
        max_tokens: int = 2000,
        response_format: dict[str, str] | None = None,
    ) -> VisionResponse:
        """Return next mocked response."""
        if self.call_count >= len(self.responses):
            raise IndexError(f"No more mock responses available (call_count={self.call_count})")
        self.last_response_format = response_format
        response = self.responses[self.call_count]
        self.call_count += 1
        return response

    def analyze_image_targeted(
        self,
        image_bytes: bytes,
        prompt: str,
        *,
        task_type: str,
        detail: str = "high",
        max_tokens: int = 2000,
        response_format: dict[str, str] | None = None,
        max_retries: int | None = None,
    ) -> VisionResponse:
        """Delegate to analyze_image — mock does not inspect task_type."""
        return self.analyze_image(
            image_bytes=image_bytes,
            prompt=prompt,
            detail=detail,
            max_tokens=max_tokens,
            response_format=response_format,
        )


class TestOCRExtractionBasics:
    """Tests for basic OCR extraction functionality."""

    @pytest.fixture
    def stage(self) -> OCRExtractionStage:
        """Create a fresh stage instance for each test."""
        return OCRExtractionStage()

    @pytest.fixture
    def temp_image_file(self, tmp_path: Path) -> Path:
        """Create a temporary image file for testing."""
        image_path = tmp_path / "test_image.png"
        # Write a minimal PNG file
        image_path.write_bytes(
            b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
            b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01"
            b"\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
        )
        return image_path

    def test_should_process_high_relevance(self, stage: OCRExtractionStage) -> None:
        """Images with high relevance should be processed."""
        asset = ImageAsset(
            img_id="test_1",
            filename="table.png",
            nearby_text="Revenue table",
            width=800,
            height=600,
            classification=ImageClassification.TABLE_IMAGE,
            relevance_score=0.8,
            processed=False,
            file_path="/path/to/image.png",
        )
        assert stage._should_process(asset) is True

    def test_should_not_process_low_relevance(self, stage: OCRExtractionStage) -> None:
        """Images with low relevance should be skipped."""
        asset = ImageAsset(
            img_id="test_2",
            filename="image.png",
            nearby_text="",
            width=800,
            height=600,
            classification=ImageClassification.TABLE_IMAGE,
            relevance_score=0.2,  # Below MIN_RELEVANCE_FOR_PROCESSING (0.3)
            processed=False,
            file_path="/path/to/image.png",
        )
        assert stage._should_process(asset) is False

    def test_should_not_process_already_processed(self, stage: OCRExtractionStage) -> None:
        """Already processed images should be skipped."""
        asset = ImageAsset(
            img_id="test_3",
            filename="table.png",
            nearby_text="Revenue table",
            width=800,
            height=600,
            classification=ImageClassification.TABLE_IMAGE,
            relevance_score=0.8,
            processed=True,  # Already processed
            file_path="/path/to/image.png",
        )
        assert stage._should_process(asset) is False

    def test_should_not_process_decorative(self, stage: OCRExtractionStage) -> None:
        """Decorative images should be skipped."""
        asset = ImageAsset(
            img_id="test_4",
            filename="logo.png",
            nearby_text="",
            width=800,
            height=600,
            classification=ImageClassification.DECORATIVE,
            relevance_score=0.8,
            processed=False,
            file_path="/path/to/image.png",
        )
        assert stage._should_process(asset) is False

    def test_should_not_process_logo(self, stage: OCRExtractionStage) -> None:
        """Logo images should be skipped."""
        asset = ImageAsset(
            img_id="test_5",
            filename="logo.png",
            nearby_text="",
            width=800,
            height=600,
            classification=ImageClassification.LOGO,
            relevance_score=0.8,
            processed=False,
            file_path="/path/to/image.png",
        )
        assert stage._should_process(asset) is False

    def test_should_not_process_no_file_path(self, stage: OCRExtractionStage) -> None:
        """Images without file path should be skipped."""
        asset = ImageAsset(
            img_id="test_6",
            filename="table.png",
            nearby_text="Revenue table",
            width=800,
            height=600,
            classification=ImageClassification.TABLE_IMAGE,
            relevance_score=0.8,
            processed=False,
            file_path=None,  # No file path
        )
        assert stage._should_process(asset) is False


class TestTableImageOCR:
    """Tests for table image OCR extraction."""

    @pytest.fixture
    def temp_image_file(self, tmp_path: Path) -> Path:
        """Create a temporary image file for testing."""
        image_path = tmp_path / "test_table.png"
        image_path.write_bytes(
            b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
            b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01"
            b"\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
        )
        return image_path

    def test_table_ocr_success(self, temp_image_file: Path) -> None:
        """Successfully extract table from image."""
        # Mock vision response with table data
        ocr_data = {
            "raw_text": "Year Revenue\n2021 $1.2B\n2022 $1.5B",
            "confidence": 0.95,
            "cells": [
                {"row": 0, "col": 0, "text": "Year", "is_header": True},
                {"row": 0, "col": 1, "text": "Revenue", "is_header": True},
                {"row": 1, "col": 0, "text": "2021", "is_header": False},
                {"row": 1, "col": 1, "text": "$1.2B", "is_header": False},
                {"row": 2, "col": 0, "text": "2022", "is_header": False},
                {"row": 2, "col": 1, "text": "$1.5B", "is_header": False},
            ],
        }

        mock_response = VisionResponse(
            content=json.dumps(ocr_data),
            model="gpt-4o",
            prompt_tokens=1000,
            completion_tokens=200,
            cost_usd=0.05,
            latency_ms=500,
        )

        mock_client = MockVisionClient(responses=[mock_response])
        stage = OCRExtractionStage(vision_client=mock_client)

        asset = ImageAsset(
            img_id="test_table_1",
            filename="revenue_table.png",
            nearby_text="Annual revenue",
            width=800,
            height=600,
            classification=ImageClassification.TABLE_IMAGE,
            relevance_score=0.9,
            processed=False,
            file_path=temp_image_file.name,
        )

        stage.process_table_image(asset)

        # Verify results
        assert asset.processed is True
        assert asset.confidence == 0.95
        assert asset.requires_manual_capture is False
        assert asset.ocr_text == "Year Revenue\n2021 $1.2B\n2022 $1.5B"
        assert asset.ocr_table is not None
        assert asset.ocr_table.row_count == 3
        assert asset.ocr_table.col_count == 2
        assert len(asset.ocr_table.cells) == 6

    def test_table_ocr_low_confidence(self, temp_image_file: Path) -> None:
        """Low confidence OCR should mark for manual capture."""
        ocr_data = {
            "raw_text": "Unclear text",
            "confidence": 0.3,  # Below OCR_CONFIDENCE_THRESHOLD (0.5)
            "cells": [
                {"row": 0, "col": 0, "text": "unclear", "is_header": True},
            ],
        }

        mock_response = VisionResponse(
            content=json.dumps(ocr_data),
            model="gpt-4o",
            prompt_tokens=1000,
            completion_tokens=100,
            cost_usd=0.02,
            latency_ms=400,
        )

        mock_client = MockVisionClient(responses=[mock_response])
        stage = OCRExtractionStage(vision_client=mock_client)

        asset = ImageAsset(
            img_id="test_table_2",
            filename="blurry_table.png",
            nearby_text="",
            width=800,
            height=600,
            classification=ImageClassification.TABLE_IMAGE,
            relevance_score=0.8,
            processed=False,
            file_path=temp_image_file.name,
        )

        stage.process_table_image(asset)

        assert asset.processed is True
        assert asset.confidence == 0.3
        assert asset.requires_manual_capture is True

    def test_table_ocr_no_cells(self, temp_image_file: Path) -> None:
        """OCR with no cells should mark for manual capture."""
        ocr_data = {
            "raw_text": "Some text",
            "confidence": 0.8,
            "cells": [],  # No cells found
        }

        mock_response = VisionResponse(
            content=json.dumps(ocr_data),
            model="gpt-4o",
            prompt_tokens=1000,
            completion_tokens=50,
            cost_usd=0.01,
            latency_ms=300,
        )

        mock_client = MockVisionClient(responses=[mock_response])
        stage = OCRExtractionStage(vision_client=mock_client)

        asset = ImageAsset(
            img_id="test_table_3",
            filename="empty_table.png",
            nearby_text="",
            width=800,
            height=600,
            classification=ImageClassification.TABLE_IMAGE,
            relevance_score=0.7,
            processed=False,
            file_path=temp_image_file.name,
        )

        stage.process_table_image(asset)

        assert asset.processed is True
        assert asset.confidence == 0.0
        assert asset.requires_manual_capture is True

    def test_table_ocr_invalid_json(self, temp_image_file: Path) -> None:
        """Invalid JSON response should mark for manual capture."""
        mock_response = VisionResponse(
            content="Not valid JSON",
            model="gpt-4o",
            prompt_tokens=1000,
            completion_tokens=50,
            cost_usd=0.01,
            latency_ms=300,
        )

        mock_client = MockVisionClient(responses=[mock_response])
        stage = OCRExtractionStage(vision_client=mock_client)

        asset = ImageAsset(
            img_id="test_table_4",
            filename="table.png",
            nearby_text="",
            width=800,
            height=600,
            classification=ImageClassification.TABLE_IMAGE,
            relevance_score=0.8,
            processed=False,
            file_path=temp_image_file.name,
        )

        stage.process_table_image(asset)

        assert asset.processed is True
        assert asset.confidence == 0.0
        assert asset.requires_manual_capture is True
        assert asset.ocr_text == "Not valid JSON"

    def test_table_ocr_file_not_found(self) -> None:
        """Missing file should raise FileNotFoundError."""
        mock_client = MockVisionClient(responses=[])
        stage = OCRExtractionStage(vision_client=mock_client)

        asset = ImageAsset(
            img_id="test_table_5",
            filename="missing.png",
            nearby_text="",
            width=800,
            height=600,
            classification=ImageClassification.TABLE_IMAGE,
            relevance_score=0.8,
            processed=False,
            file_path="nonexistent-path/image.png",
        )

        with pytest.raises(FileNotFoundError):
            stage.process_table_image(asset)


class TestChartExtraction:
    """Tests for chart extraction with labeled values."""

    @pytest.fixture
    def temp_image_file(self, tmp_path: Path) -> Path:
        """Create a temporary image file for testing."""
        image_path = tmp_path / "test_chart.png"
        image_path.write_bytes(
            b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
            b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01"
            b"\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
        )
        return image_path

    def test_chart_extraction_with_labels(self, temp_image_file: Path) -> None:
        """Successfully extract chart with labeled values."""
        chart_data = {
            "chart_type": "bar",
            "title": "Annual Revenue",
            "x_axis_label": "Year",
            "y_axis_label": "Revenue ($M)",
            "confidence": 0.95,
            "series": [
                {
                    "name": "Revenue",
                    "points": [
                        {"x": "2021", "y": 1200.0, "label": "$1,200M"},
                        {"x": "2022", "y": 1500.0, "label": "$1,500M"},
                    ],
                }
            ],
        }

        mock_response = VisionResponse(
            content=json.dumps(chart_data),
            model="gpt-4o",
            prompt_tokens=1500,
            completion_tokens=300,
            cost_usd=0.08,
            latency_ms=600,
        )

        mock_client = MockVisionClient(responses=[mock_response])
        stage = OCRExtractionStage(vision_client=mock_client)

        asset = ImageAsset(
            img_id="test_chart_1",
            filename="revenue_chart.png",
            nearby_text="Revenue growth",
            width=1000,
            height=700,
            classification=ImageClassification.CHART,
            relevance_score=0.9,
            processed=False,
            file_path=temp_image_file.name,
        )

        stage.process_chart(asset)

        # Verify results
        assert asset.processed is True
        assert asset.confidence == 0.95
        assert asset.requires_manual_capture is False
        assert asset.chart_data is not None
        assert asset.chart_data.chart_type == ChartType.BAR
        assert asset.chart_data.title == "Annual Revenue"
        assert len(asset.chart_data.series) == 1
        assert len(asset.chart_data.series[0].points) == 2

    def test_chart_extraction_no_labels(self, temp_image_file: Path) -> None:
        """Chart with no labeled values should mark for manual capture."""
        chart_data = {
            "chart_type": "line",
            "title": "Growth Trend",
            "x_axis_label": "Quarter",
            "y_axis_label": "Growth %",
            "confidence": 0.8,
            "series": [],  # No labeled values
        }

        mock_response = VisionResponse(
            content=json.dumps(chart_data),
            model="gpt-4o",
            prompt_tokens=1500,
            completion_tokens=200,
            cost_usd=0.06,
            latency_ms=500,
        )

        mock_client = MockVisionClient(responses=[mock_response])
        stage = OCRExtractionStage(vision_client=mock_client)

        asset = ImageAsset(
            img_id="test_chart_2",
            filename="unlabeled_chart.png",
            nearby_text="Growth trend",
            width=1000,
            height=700,
            classification=ImageClassification.CHART,
            relevance_score=0.8,
            processed=False,
            file_path=temp_image_file.name,
        )

        stage.process_chart(asset)

        assert asset.processed is True
        assert asset.confidence == 0.0
        assert asset.requires_manual_capture is True
        assert asset.chart_data is None

    def test_chart_extraction_invalid_json(self, temp_image_file: Path) -> None:
        """Invalid JSON response should mark for manual capture."""
        mock_response = VisionResponse(
            content="Invalid JSON response",
            model="gpt-4o",
            prompt_tokens=1500,
            completion_tokens=100,
            cost_usd=0.03,
            latency_ms=400,
        )

        mock_client = MockVisionClient(responses=[mock_response])
        stage = OCRExtractionStage(vision_client=mock_client)

        asset = ImageAsset(
            img_id="test_chart_3",
            filename="chart.png",
            nearby_text="",
            width=1000,
            height=700,
            classification=ImageClassification.CHART,
            relevance_score=0.8,
            processed=False,
            file_path=temp_image_file.name,
        )

        stage.process_chart(asset)

        assert asset.processed is True
        assert asset.confidence == 0.0
        assert asset.requires_manual_capture is True

    def test_chart_extraction_repairs_truncated_json(self, temp_image_file: Path) -> None:
        """Truncated JSON (e.g., hit max_tokens mid-annotation) should be repaired.

        Vision mode should prevent this, but cached pre-JSON-mode responses can
        still be truncated. The repair trims back to the last balanced brace so
        we recover metadata + any fully-closed sections rather than dropping the
        whole chart.
        """
        truncated = (
            '{"chart_type": "bar", "title": "Marketplace Order Contribution Margin", '
            '"x_axis_label": "Year", "y_axis_label": "%", "confidence": 0.85, '
            '"series": [], "annotations": [{"text": "44.4% New Consumers in 2017", '
            '"value": 44.4, "unit": "percent", "category": "New Consumers", '
            '"period": "2017"}]}'
            ' extra garbage after the object, followed by {"broken": '  # unterminated tail
        )
        mock_response = VisionResponse(
            content=truncated,
            model="gpt-4o",
            prompt_tokens=1500,
            completion_tokens=200,
            cost_usd=0.05,
            latency_ms=400,
        )
        mock_client = MockVisionClient(responses=[mock_response])
        stage = OCRExtractionStage(vision_client=mock_client)
        asset = ImageAsset(
            img_id="test_chart_repair",
            filename="ftch_margin.png",
            nearby_text="",
            width=1000,
            height=700,
            classification=ImageClassification.CHART,
            relevance_score=0.9,
            processed=False,
            file_path=temp_image_file.name,
        )

        stage.process_chart(asset)

        assert asset.processed is True
        assert asset.requires_manual_capture is False
        assert asset.chart_data is not None
        assert asset.chart_data.title == "Marketplace Order Contribution Margin"
        assert len(asset.chart_data.annotations) == 1
        assert asset.chart_data.annotations[0].value == 44.4

    def test_chart_extraction_passes_json_mode(self, temp_image_file: Path) -> None:
        """Chart extraction should request JSON mode from the vision client."""
        mock_response = VisionResponse(
            content='{"chart_type": "bar", "title": "t", "x_axis_label": "", '
            '"y_axis_label": "", "confidence": 0.8, "series": [], '
            '"annotations": [{"text": "x", "value": 1.0, "unit": "count", '
            '"category": "", "period": ""}]}',
            model="gpt-4o",
            prompt_tokens=100,
            completion_tokens=50,
            cost_usd=0.01,
            latency_ms=100,
        )
        mock_client = MockVisionClient(responses=[mock_response])
        stage = OCRExtractionStage(vision_client=mock_client)
        asset = ImageAsset(
            img_id="test_chart_json_mode",
            filename="chart.png",
            nearby_text="",
            width=800,
            height=600,
            classification=ImageClassification.CHART,
            relevance_score=0.9,
            processed=False,
            file_path=temp_image_file.name,
        )

        stage.process_chart(asset)

        assert mock_client.last_response_format == {"type": "json_object"}

    def test_chart_extraction_no_valid_points(self, temp_image_file: Path) -> None:
        """Chart with unparseable data points should mark for manual capture."""
        chart_data = {
            "chart_type": "bar",
            "title": "Test Chart",
            "x_axis_label": "X",
            "y_axis_label": "Y",
            "confidence": 0.9,
            "series": [
                {
                    "name": "Series 1",
                    "points": [
                        {"x": "A", "y": "invalid", "label": "bad"},  # Invalid y value
                    ],
                }
            ],
        }

        mock_response = VisionResponse(
            content=json.dumps(chart_data),
            model="gpt-4o",
            prompt_tokens=1500,
            completion_tokens=200,
            cost_usd=0.05,
            latency_ms=450,
        )

        mock_client = MockVisionClient(responses=[mock_response])
        stage = OCRExtractionStage(vision_client=mock_client)

        asset = ImageAsset(
            img_id="test_chart_4",
            filename="bad_data_chart.png",
            nearby_text="",
            width=1000,
            height=700,
            classification=ImageClassification.CHART,
            relevance_score=0.8,
            processed=False,
            file_path=temp_image_file.name,
        )

        stage.process_chart(asset)

        assert asset.processed is True
        assert asset.confidence == 0.0
        assert asset.requires_manual_capture is True


class TestB4TwoStageRouting:
    """Tests for Wave B4 two-stage chart routing.

    Focused on behavior-preservation (legacy mode) and the two-call flow
    under VISION_ROUTING_MODE=two_stage. Actual provider selection is
    tested at the vision_client layer; here the mock delegates task_type
    to its shared response queue.
    """

    @pytest.fixture
    def temp_image_file(self, tmp_path: Path) -> Path:
        """Create a temporary image file for testing."""
        img = tmp_path / "chart.png"
        img.write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 100)
        return img

    @pytest.fixture
    def chart_ocr_response(self) -> VisionResponse:
        """First-pass fast-OCR response: a JSON blob of visible text."""
        return VisionResponse(
            content=json.dumps(
                {
                    "text": "Revenue $1,200M 2021\nRevenue $1,500M 2022",
                    "labels": ["Revenue", "$1,200M", "$1,500M", "2021", "2022"],
                }
            ),
            model="gemini-2.5-flash-lite-mock",
            prompt_tokens=800,
            completion_tokens=150,
            cost_usd=0.005,
            latency_ms=300,
        )

    @pytest.fixture
    def chart_read_response(self) -> VisionResponse:
        """Second-pass premium-reader response: structured chart data."""
        return VisionResponse(
            content=json.dumps(
                {
                    "chart_type": "bar",
                    "title": "Annual Revenue",
                    "x_axis_label": "Year",
                    "y_axis_label": "Revenue ($M)",
                    "confidence": 0.92,
                    "series": [
                        {
                            "name": "Revenue",
                            "points": [
                                {"x": "2021", "y": 1200.0, "label": "$1,200M"},
                                {"x": "2022", "y": 1500.0, "label": "$1,500M"},
                            ],
                        }
                    ],
                }
            ),
            model="claude-sonnet-4-6-mock",
            prompt_tokens=2000,
            completion_tokens=400,
            cost_usd=0.09,
            latency_ms=700,
        )

    def test_legacy_mode_makes_one_call(
        self,
        chart_read_response: VisionResponse,
        temp_image_file: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """VISION_ROUTING_MODE unset (legacy): exactly one call, unchanged behavior."""
        monkeypatch.delenv("VISION_ROUTING_MODE", raising=False)

        mock_client = MockVisionClient(responses=[chart_read_response])
        stage = OCRExtractionStage(vision_client=mock_client)

        asset = ImageAsset(
            img_id="test_legacy",
            filename="chart.png",
            nearby_text="Revenue chart",
            width=1000,
            height=700,
            classification=ImageClassification.CHART,
            relevance_score=0.9,
            processed=False,
            file_path=temp_image_file.name,
        )

        cost = stage.process_chart(asset)

        # Exactly one call; cost matches the single response.
        assert mock_client.call_count == 1
        assert cost == pytest.approx(0.09)
        assert asset.chart_data is not None
        assert asset.confidence == 0.92

    def test_two_stage_mode_makes_two_calls_and_sums_cost(
        self,
        chart_ocr_response: VisionResponse,
        chart_read_response: VisionResponse,
        temp_image_file: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """VISION_ROUTING_MODE=two_stage: OCR pass + premium read; costs sum."""
        monkeypatch.setenv("VISION_ROUTING_MODE", "two_stage")

        # Two responses, in order: chart_ocr first, then chart_read.
        mock_client = MockVisionClient(responses=[chart_ocr_response, chart_read_response])
        stage = OCRExtractionStage(vision_client=mock_client)

        asset = ImageAsset(
            img_id="test_two_stage",
            filename="chart.png",
            nearby_text="Revenue chart",
            width=1000,
            height=700,
            classification=ImageClassification.CHART,
            relevance_score=0.9,
            processed=False,
            file_path=temp_image_file.name,
        )

        cost = stage.process_chart(asset)

        assert mock_client.call_count == 2
        # Costs of both calls accumulate: 0.005 + 0.09 = 0.095.
        assert cost == pytest.approx(0.095)
        assert asset.chart_data is not None
        assert asset.confidence == 0.92

    def test_two_stage_injects_ocr_text_into_chart_prompt(
        self,
        chart_ocr_response: VisionResponse,
        chart_read_response: VisionResponse,
        temp_image_file: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Second-pass prompt must include the OCR grounding text block."""
        monkeypatch.setenv("VISION_ROUTING_MODE", "two_stage")

        captured_prompts: list[str] = []

        class _CapturingMock(MockVisionClient):
            def analyze_image_targeted(self, image_bytes, prompt, **kwargs):
                captured_prompts.append(prompt)
                return super().analyze_image_targeted(image_bytes, prompt, **kwargs)

        mock_client = _CapturingMock(responses=[chart_ocr_response, chart_read_response])
        stage = OCRExtractionStage(vision_client=mock_client)

        asset = ImageAsset(
            img_id="test_grounding",
            filename="chart.png",
            nearby_text="Revenue chart",
            width=1000,
            height=700,
            classification=ImageClassification.CHART,
            relevance_score=0.9,
            processed=False,
            file_path=temp_image_file.name,
        )

        stage.process_chart(asset)

        assert len(captured_prompts) == 2
        # First prompt is the OCR prompt — should NOT contain grounding block.
        assert "OCR GROUNDING TEXT" not in captured_prompts[0]
        # Second prompt should include the OCR text from the first response.
        assert "OCR GROUNDING TEXT" in captured_prompts[1]
        assert "Revenue $1,200M" in captured_prompts[1]

    def test_two_stage_ocr_failure_falls_through_to_single_read(
        self,
        chart_read_response: VisionResponse,
        temp_image_file: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """If the OCR pass raises, chart extraction proceeds without grounding."""
        monkeypatch.setenv("VISION_ROUTING_MODE", "two_stage")

        class _FailingOCRMock(MockVisionClient):
            def analyze_image_targeted(self, image_bytes, prompt, **kwargs):
                if kwargs.get("task_type") == "chart_ocr":
                    raise RuntimeError("simulated OCR failure")
                return super().analyze_image_targeted(image_bytes, prompt, **kwargs)

        mock_client = _FailingOCRMock(responses=[chart_read_response])
        stage = OCRExtractionStage(vision_client=mock_client)

        asset = ImageAsset(
            img_id="test_fallthrough",
            filename="chart.png",
            nearby_text="Revenue chart",
            width=1000,
            height=700,
            classification=ImageClassification.CHART,
            relevance_score=0.9,
            processed=False,
            file_path=temp_image_file.name,
        )

        cost = stage.process_chart(asset)

        # OCR failure is swallowed; one successful premium call proceeds.
        assert mock_client.call_count == 1
        assert cost == pytest.approx(0.09)
        assert asset.chart_data is not None


class TestPipelineIntegration:
    """Tests for pipeline stage integration."""

    @pytest.fixture
    def temp_image_file(self, tmp_path: Path) -> Path:
        """Create a temporary image file for testing."""
        image_path = tmp_path / "test_image.png"
        image_path.write_bytes(
            b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
            b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01"
            b"\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
        )
        return image_path

    def test_process_empty_batch(self, tmp_path: Path) -> None:
        """Process with no images should return early."""
        mock_client = MockVisionClient(responses=[])
        stage = OCRExtractionStage(vision_client=mock_client)

        context = PipelineContext(
            html_path=tmp_path / "test.html",
            filing_id=1,
            config=PipelineConfig(),
            images=[],
        )

        result = stage.process(context)

        assert result.stage == PipelineStage.OCR_CHART_EXTRACTION
        assert result.success is True
        assert result.items_processed == 0
        assert result.items_output == 0
        assert len(result.errors) == 0
        assert result.metadata["message"] == "No images to process"

    def test_process_mixed_images(self, temp_image_file: Path, tmp_path: Path) -> None:
        """Process batch with tables and charts."""
        table_data = {
            "raw_text": "Year Revenue\n2021 $1B",
            "confidence": 0.9,
            "cells": [
                {"row": 0, "col": 0, "text": "Year", "is_header": True},
                {"row": 0, "col": 1, "text": "Revenue", "is_header": True},
                {"row": 1, "col": 0, "text": "2021", "is_header": False},
                {"row": 1, "col": 1, "text": "$1B", "is_header": False},
            ],
        }

        chart_data = {
            "chart_type": "bar",
            "title": "Revenue",
            "x_axis_label": "Year",
            "y_axis_label": "$",
            "confidence": 0.85,
            "series": [
                {
                    "name": "Revenue",
                    "points": [{"x": "2021", "y": 1000.0, "label": "$1B"}],
                }
            ],
        }

        mock_responses = [
            VisionResponse(
                content=json.dumps(table_data),
                model="gpt-4o",
                prompt_tokens=1000,
                completion_tokens=200,
                cost_usd=0.05,
                latency_ms=500,
            ),
            VisionResponse(
                content=json.dumps(chart_data),
                model="gpt-4o",
                prompt_tokens=1500,
                completion_tokens=300,
                cost_usd=0.08,
                latency_ms=600,
            ),
        ]

        mock_client = MockVisionClient(responses=mock_responses)
        stage = OCRExtractionStage(vision_client=mock_client)

        images = [
            ImageAsset(
                img_id="table_1",
                filename="table.png",
                nearby_text="Revenue table",
                width=800,
                height=600,
                classification=ImageClassification.TABLE_IMAGE,
                relevance_score=0.9,
                processed=False,
                file_path=temp_image_file.name,
            ),
            ImageAsset(
                img_id="chart_1",
                filename="chart.png",
                nearby_text="Revenue chart",
                width=1000,
                height=700,
                classification=ImageClassification.CHART,
                relevance_score=0.85,
                processed=False,
                file_path=temp_image_file.name,
            ),
        ]

        context = PipelineContext(
            html_path=tmp_path / "test.html",
            filing_id=1,
            config=PipelineConfig(),
            images=images,
        )

        result = stage.process(context)

        assert result.success is True
        assert result.items_processed == 2
        assert result.items_output == 2
        assert result.metadata["ocr_calls"] == 1
        assert result.metadata["chart_calls"] == 1
        assert result.metadata["total_api_calls"] == 2

        # Verify both images were processed
        assert images[0].processed is True
        assert images[0].ocr_table is not None
        assert images[1].processed is True
        assert images[1].chart_data is not None

    def test_process_ocr_call_limit(self, temp_image_file: Path, tmp_path: Path) -> None:
        """Processing should stop when OCR call limit is reached."""
        table_data = {
            "raw_text": "test",
            "confidence": 0.9,
            "cells": [{"row": 0, "col": 0, "text": "test", "is_header": False}],
        }

        # Create enough responses for the limit
        mock_responses = [
            VisionResponse(
                content=json.dumps(table_data),
                model="gpt-4o",
                prompt_tokens=1000,
                completion_tokens=100,
                cost_usd=0.02,
                latency_ms=300,
            )
            for _ in range(OCRExtractionStage.MAX_OCR_CALLS_PER_DOCUMENT)
        ]

        mock_client = MockVisionClient(responses=mock_responses)
        stage = OCRExtractionStage(vision_client=mock_client)

        # Create more images than the limit
        images = [
            ImageAsset(
                img_id=f"table_{i}",
                filename=f"table_{i}.png",
                nearby_text="table",
                width=800,
                height=600,
                classification=ImageClassification.TABLE_IMAGE,
                relevance_score=0.9,
                processed=False,
                file_path=temp_image_file.name,
            )
            for i in range(OCRExtractionStage.MAX_OCR_CALLS_PER_DOCUMENT + 5)
        ]

        context = PipelineContext(
            html_path=tmp_path / "test.html",
            filing_id=1,
            config=PipelineConfig(),
            images=images,
        )

        result = stage.process(context)

        # Should stop at limit
        assert result.items_processed == OCRExtractionStage.MAX_OCR_CALLS_PER_DOCUMENT
        assert result.metadata["ocr_calls"] == OCRExtractionStage.MAX_OCR_CALLS_PER_DOCUMENT
        assert len(result.warnings) > 0
        assert "OCR call limit" in result.warnings[0]

    def test_process_with_errors(self, temp_image_file: Path, tmp_path: Path) -> None:
        """Errors should be logged but processing should continue."""
        # First response succeeds, second fails
        table_data = {
            "raw_text": "test",
            "confidence": 0.9,
            "cells": [{"row": 0, "col": 0, "text": "test", "is_header": False}],
        }

        mock_responses = [
            VisionResponse(
                content=json.dumps(table_data),
                model="gpt-4o",
                prompt_tokens=1000,
                completion_tokens=100,
                cost_usd=0.02,
                latency_ms=300,
            ),
        ]

        mock_client = MockVisionClient(responses=mock_responses)
        stage = OCRExtractionStage(vision_client=mock_client)

        images = [
            ImageAsset(
                img_id="table_1",
                filename="table_1.png",
                nearby_text="table",
                width=800,
                height=600,
                classification=ImageClassification.TABLE_IMAGE,
                relevance_score=0.9,
                processed=False,
                file_path=temp_image_file.name,
            ),
            ImageAsset(
                img_id="table_2",
                filename="table_2.png",
                nearby_text="table",
                width=800,
                height=600,
                classification=ImageClassification.TABLE_IMAGE,
                relevance_score=0.9,
                processed=False,
                file_path="/nonexistent/path.png",  # Will cause error
            ),
        ]

        context = PipelineContext(
            html_path=tmp_path / "test.html",
            filing_id=1,
            config=PipelineConfig(),
            images=images,
        )

        result = stage.process(context)

        # First image should succeed
        assert images[0].processed is True
        assert images[0].requires_manual_capture is False

        # Second image should be marked for manual capture
        assert images[1].processed is True
        assert images[1].requires_manual_capture is True

        # Result should have errors but continue
        assert result.success is False  # Has errors
        assert len(result.errors) == 1
        assert "Error processing table_2" in result.errors[0]


class TestTableReconstruction:
    """Tests for table reconstruction from OCR cells."""

    def test_reconstruct_simple_table(self) -> None:
        """Reconstruct a simple 2x2 table."""
        stage = OCRExtractionStage()

        cells_data = [
            {"row": 0, "col": 0, "text": "A", "is_header": True},
            {"row": 0, "col": 1, "text": "B", "is_header": True},
            {"row": 1, "col": 0, "text": "1", "is_header": False},
            {"row": 1, "col": 1, "text": "2", "is_header": False},
        ]

        table = stage._reconstruct_table_from_ocr(cells_data)

        assert table.row_count == 2
        assert table.col_count == 2
        assert len(table.cells) == 4
        assert table.header_rows >= 1

    def test_reconstruct_empty_cells(self) -> None:
        """Reconstruct table with no cells."""
        stage = OCRExtractionStage()

        table = stage._reconstruct_table_from_ocr([])

        assert table.row_count == 0
        assert table.col_count == 0
        assert len(table.cells) == 0

    def test_reconstruct_with_empty_text(self) -> None:
        """Reconstruct table with empty cell text."""
        stage = OCRExtractionStage()

        cells_data = [
            {"row": 0, "col": 0, "text": "Header", "is_header": True},
            {"row": 0, "col": 1, "text": "", "is_header": True},  # Empty
            {"row": 1, "col": 0, "text": "Value", "is_header": False},
            {"row": 1, "col": 1, "text": "123", "is_header": False},
        ]

        table = stage._reconstruct_table_from_ocr(cells_data)

        assert table.row_count == 2
        assert table.col_count == 2
        assert len(table.cells) == 4


class TestVisionClientApiKeyCheck:
    """Tests for API key validation in vision_client property."""

    def test_vision_client_raises_when_no_api_key(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """vision_client property should raise V2FatalError when OPENAI_API_KEY is missing."""
        from src.extraction_v2.exceptions import V2FatalError

        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        stage = OCRExtractionStage()  # No pre-set vision_client
        with pytest.raises(V2FatalError) as exc_info:
            _ = stage.vision_client
        assert "OPENAI_API_KEY" in str(exc_info.value)
        assert exc_info.value.stage_name == "ocr_chart_extraction"

    def test_vision_client_does_not_raise_when_key_set(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """vision_client property should not raise when OPENAI_API_KEY is present."""
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test-key")
        stage = OCRExtractionStage()
        # The import of VisionClient will succeed (even if OpenAI SDK complains about key validity)
        # We just verify no V2FatalError is raised for missing key
        from src.extraction_v2.exceptions import V2FatalError

        try:
            _ = stage.vision_client
        except V2FatalError as e:
            if "OPENAI_API_KEY" in str(e):
                pytest.fail("V2FatalError raised for missing API key even though key was set")
        except Exception:
            pass  # Other errors (e.g., OpenAI SDK init) are acceptable

    def test_vision_client_not_checked_when_already_set(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Pre-set vision_client should bypass the API key check."""

        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        mock_client = object()
        stage = OCRExtractionStage(vision_client=mock_client)
        # Should return the pre-set client without raising
        result = stage.vision_client
        assert result is mock_client


# ============================================================================
# Full-page-scan OCR (Path A, Phase 2)
# ============================================================================


class MockTextOCRVisionClient:
    """Vision client that yields PageTextExtraction responses in order.

    Mirrors MockVisionClient but for the analyze_image_for_text path used
    by the full-page-scan and keyword-pre-scan branches. Also implements
    analyze_image so the two-pass chart extraction can complete.
    """

    def __init__(
        self,
        text_responses: list,
        chart_responses: list | None = None,
    ) -> None:
        from src.llm.vision_client import VisionResponse

        self.text_responses = text_responses
        self.chart_responses = chart_responses or []
        self.text_call_count = 0
        self.chart_call_count = 0
        self.model = "gpt-4o-mock"
        self._VisionResponse = VisionResponse

    def analyze_image_for_text(self, *, image_bytes: bytes, max_tokens: int = 3000):
        if self.text_call_count >= len(self.text_responses):
            raise IndexError("No more text responses available")
        resp = self.text_responses[self.text_call_count]
        self.text_call_count += 1
        return resp

    def analyze_image(
        self,
        image_bytes: bytes,
        prompt: str,
        detail: str = "high",
        max_tokens: int = 2000,
        response_format: dict[str, str] | None = None,
    ):
        """Serve chart/table-prompt responses in chart_call order."""
        if self.chart_call_count >= len(self.chart_responses):
            raise IndexError("No more chart responses available")
        resp = self.chart_responses[self.chart_call_count]
        self.chart_call_count += 1
        return resp

    def analyze_image_targeted(
        self,
        image_bytes: bytes,
        prompt: str,
        *,
        task_type: str,
        detail: str = "high",
        max_tokens: int = 2000,
        response_format: dict[str, str] | None = None,
        max_retries: int | None = None,
    ):
        """Delegate to analyze_image — mock does not inspect task_type."""
        return self.analyze_image(
            image_bytes=image_bytes,
            prompt=prompt,
            detail=detail,
            max_tokens=max_tokens,
            response_format=response_format,
        )


def _make_page_text_extraction(
    *,
    text: str,
    contains_chart: bool = False,
    contains_table: bool = False,
    chart_hint: str = "none",
    cost: float = 0.05,
):
    from src.llm.vision_client import PageTextExtraction

    return PageTextExtraction(
        text=text,
        contains_chart=contains_chart,
        contains_table=contains_table,
        chart_hint=chart_hint,
        cost_usd=cost,
        raw_response="",
    )


def _make_page_scan_asset(img_id: str, tmp_path: Path, filename: str = "p.jpg") -> ImageAsset:
    """Write a minimal JPEG to tmp_path and return a FULL_PAGE_SCAN asset."""
    (tmp_path / filename).write_bytes(b"\xff\xd8\xff\xe0fake-jpeg-bytes")
    return ImageAsset(
        img_id=img_id,
        filename=filename,
        file_path=filename,
        width=1055,
        height=1365,
        classification=ImageClassification.FULL_PAGE_SCAN,
        relevance_score=0.6,
    )


class TestProcessFullPageScan:
    """Tests for OCRExtractionStage.process_full_page_scan (Phase 2)."""

    def test_happy_path_appends_segment(self, tmp_path: Path) -> None:
        from src.extraction_v2.models import SectionType, SegmentSourceType

        asset = _make_page_scan_asset("p1", tmp_path)
        vision = MockTextOCRVisionClient(
            text_responses=[
                _make_page_text_extraction(
                    text="Q3 revenue reached $100M; active customers grew 12%.",
                    contains_chart=False,
                )
            ]
        )
        stage = OCRExtractionStage(vision_client=vision)
        context = PipelineContext(
            filing_id=42,
            html_path=Path("/tmp/x.html"),
            config=PipelineConfig(enable_full_page_ocr=True),
        )
        context.images = [asset]

        contains_chart = stage.process_full_page_scan(asset, context)

        assert contains_chart is False
        assert asset.ocr_text.startswith("Q3 revenue reached")
        assert asset.processed is True
        assert asset.confidence == 1.0
        assert len(context.segments) == 1
        seg = context.segments[0]
        assert seg.source_type == SegmentSourceType.IMAGE_OCR
        assert seg.source_img_id == "p1"
        assert seg.section_type == SectionType.PRESENTATION_SLIDE
        assert "$100M" in seg.text

    def test_contains_chart_true_returned(self, tmp_path: Path) -> None:
        asset = _make_page_scan_asset("p1", tmp_path)
        vision = MockTextOCRVisionClient(
            text_responses=[
                _make_page_text_extraction(
                    text="Retention by cohort (see chart)", contains_chart=True, chart_hint="line"
                )
            ]
        )
        stage = OCRExtractionStage(vision_client=vision)
        context = PipelineContext(
            filing_id=1,
            html_path=Path("/tmp/x.html"),
            config=PipelineConfig(enable_full_page_ocr=True),
        )
        context.images = [asset]

        assert stage.process_full_page_scan(asset, context) is True
        assert len(context.segments) == 1

    def test_empty_text_flags_manual_capture_no_segment(self, tmp_path: Path) -> None:
        asset = _make_page_scan_asset("p1", tmp_path)
        vision = MockTextOCRVisionClient(text_responses=[_make_page_text_extraction(text="")])
        stage = OCRExtractionStage(vision_client=vision)
        context = PipelineContext(
            filing_id=1,
            html_path=Path("/tmp/x.html"),
            config=PipelineConfig(enable_full_page_ocr=True),
        )
        context.images = [asset]

        stage.process_full_page_scan(asset, context)

        assert asset.processed is True
        assert asset.requires_manual_capture is True
        assert asset.confidence == 0.0
        assert context.segments == []

    def test_vision_exception_marks_manual_capture(self, tmp_path: Path) -> None:
        asset = _make_page_scan_asset("p1", tmp_path)

        class _RaisingClient:
            def analyze_image_for_text(self, **_kwargs):
                raise RuntimeError("OpenAI 503")

        stage = OCRExtractionStage(vision_client=_RaisingClient())
        context = PipelineContext(
            filing_id=1,
            html_path=Path("/tmp/x.html"),
            config=PipelineConfig(enable_full_page_ocr=True),
        )
        context.images = [asset]

        result = stage.process_full_page_scan(asset, context)

        assert result is False
        assert asset.processed is True
        assert asset.requires_manual_capture is True

    def test_missing_file_path_raises(self, tmp_path: Path) -> None:
        asset = ImageAsset(
            img_id="no_path",
            filename="x.jpg",
            file_path="",
            classification=ImageClassification.FULL_PAGE_SCAN,
        )
        stage = OCRExtractionStage(vision_client=MockTextOCRVisionClient([]))
        context = PipelineContext(
            filing_id=1,
            html_path=Path("/tmp/x.html"),
            config=PipelineConfig(enable_full_page_ocr=True),
        )
        with pytest.raises(ValueError, match="no file_path"):
            stage.process_full_page_scan(asset, context)

    def test_segments_append_in_monotonic_sequence(self, tmp_path: Path) -> None:
        """OCR segments appended after HTML segments take next sequence idx."""
        from src.extraction_v2.models import Segment, SegmentType

        # Pre-seed context.segments with HTML-derived segments.
        existing = [
            Segment(segment_id="s0", segment_type=SegmentType.PARAGRAPH, text="a", sequence=0),
            Segment(segment_id="s1", segment_type=SegmentType.PARAGRAPH, text="b", sequence=5),
        ]
        asset = _make_page_scan_asset("p1", tmp_path)
        vision = MockTextOCRVisionClient(
            text_responses=[_make_page_text_extraction(text="OCR page one")]
        )
        stage = OCRExtractionStage(vision_client=vision)
        context = PipelineContext(
            filing_id=1,
            html_path=Path("/tmp/x.html"),
            config=PipelineConfig(enable_full_page_ocr=True),
        )
        context.segments = list(existing)
        context.images = [asset]

        stage.process_full_page_scan(asset, context)

        # New OCR segment follows the max prior sequence (5) → 6.
        assert context.segments[-1].sequence == 6


class TestOCRStageFullPageScanBranch:
    """Tests for the FULL_PAGE_SCAN dispatch inside OCRExtractionStage.process()."""

    def test_full_page_scan_branch_counts_against_its_own_cap(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Cap tightened to 2 so the test can hit it with a manageable fixture.
        monkeypatch.setattr(OCRExtractionStage, "MAX_FULL_PAGE_OCR_CALLS_PER_DOCUMENT", 2)
        assets = [_make_page_scan_asset(f"p{i}", tmp_path, filename=f"p{i}.jpg") for i in range(4)]
        vision = MockTextOCRVisionClient(
            text_responses=[_make_page_text_extraction(text=f"text {i}") for i in range(4)]
        )
        stage = OCRExtractionStage(vision_client=vision)
        context = PipelineContext(
            filing_id=1,
            html_path=Path("/tmp/x.html"),
            config=PipelineConfig(enable_full_page_ocr=True),
        )
        context.images = assets

        result = stage.process(context)

        assert result.metadata["full_page_ocr_calls"] == 2
        assert vision.text_call_count == 2
        # Two segments appended for the two processed images.
        assert len(context.segments) == 2

    def test_two_pass_chart_triggered_when_contains_chart_true(self, tmp_path: Path) -> None:
        """When the page reports a chart, the existing chart path runs a second time."""
        asset = _make_page_scan_asset("p1", tmp_path)
        text_resp = _make_page_text_extraction(
            text="Revenue retention chart", contains_chart=True, chart_hint="bar"
        )
        # A chart-extraction response the chart path will parse as "no usable data".
        chart_resp = VisionResponse(
            content=json.dumps(
                {
                    "chart_type": "bar",
                    "title": "",
                    "x_axis_label": "",
                    "y_axis_label": "",
                    "series": [],
                    "annotations": [],
                }
            ),
            model="gpt-4o-mock",
            prompt_tokens=100,
            completion_tokens=50,
            cost_usd=0.01,
            latency_ms=10,
        )
        vision = MockTextOCRVisionClient(
            text_responses=[text_resp],
            chart_responses=[chart_resp],
        )
        stage = OCRExtractionStage(vision_client=vision)
        context = PipelineContext(
            filing_id=1,
            html_path=Path("/tmp/x.html"),
            config=PipelineConfig(enable_full_page_ocr=True),
        )
        context.images = [asset]

        stage.process(context)

        assert vision.text_call_count == 1
        assert vision.chart_call_count == 1  # Two-pass fired


# ============================================================================
# Keyword pre-scan (Path B, Phase 3)
# ============================================================================


def _make_ambiguous_asset(img_id: str, tmp_path: Path, filename: str = "a.jpg") -> ImageAsset:
    """Write bytes for an UNKNOWN image with relevance 0.25 (in-band for pre-scan)."""
    (tmp_path / filename).write_bytes(b"\xff\xd8\xff\xe0fake")
    return ImageAsset(
        img_id=img_id,
        filename=filename,
        file_path=filename,
        width=800,
        height=600,
        classification=ImageClassification.UNKNOWN,
        relevance_score=0.25,
    )


class TestPrescanAmbiguousImages:
    """Tests for Path B image-level Tier-1 keyword pre-scan."""

    def test_tier1_keyword_promotes_to_table_image(self, tmp_path: Path) -> None:
        from src.extraction_v2.models import SegmentSourceType

        asset = _make_ambiguous_asset("a1", tmp_path)
        vision = MockTextOCRVisionClient(
            text_responses=[
                _make_page_text_extraction(
                    text=("Net revenue retention by cohort: 2020: 115%, 2021: 118%, 2022: 122%"),
                    contains_chart=False,
                )
            ]
        )
        stage = OCRExtractionStage(vision_client=vision)
        context = PipelineContext(
            filing_id=1,
            html_path=Path("/tmp/x.html"),
            config=PipelineConfig(enable_image_keyword_prescan=True),
        )
        context.images = [asset]

        stage._prescan_ambiguous_images(context)

        assert asset.classification == ImageClassification.TABLE_IMAGE
        assert asset.relevance_score >= 0.6
        assert len(context.segments) == 1
        assert context.segments[0].source_type == SegmentSourceType.IMAGE_OCR

    def test_tier1_keyword_with_chart_promotes_to_chart(self, tmp_path: Path) -> None:
        asset = _make_ambiguous_asset("a1", tmp_path)
        vision = MockTextOCRVisionClient(
            text_responses=[
                _make_page_text_extraction(
                    text="LTV/CAC ratio by tenure bucket",
                    contains_chart=True,
                    chart_hint="bar",
                )
            ]
        )
        stage = OCRExtractionStage(vision_client=vision)
        context = PipelineContext(
            filing_id=1,
            html_path=Path("/tmp/x.html"),
            config=PipelineConfig(enable_image_keyword_prescan=True),
        )
        context.images = [asset]

        stage._prescan_ambiguous_images(context)

        assert asset.classification == ImageClassification.CHART

    def test_no_tier1_keyword_leaves_image_unknown(self, tmp_path: Path) -> None:
        asset = _make_ambiguous_asset("a1", tmp_path)
        vision = MockTextOCRVisionClient(
            text_responses=[
                _make_page_text_extraction(
                    text="This is a generic product photo caption.",
                    contains_chart=False,
                )
            ]
        )
        stage = OCRExtractionStage(vision_client=vision)
        context = PipelineContext(
            filing_id=1,
            html_path=Path("/tmp/x.html"),
            config=PipelineConfig(enable_image_keyword_prescan=True),
        )
        context.images = [asset]

        stage._prescan_ambiguous_images(context)

        assert asset.classification == ImageClassification.UNKNOWN
        # OCR text is recorded for audit but no segment is appended.
        assert "product photo" in (asset.ocr_text or "")
        assert context.segments == []

    def test_page_scan_mode_skips_prescan(self, tmp_path: Path) -> None:
        """Path A already handled the filing — pre-scan must not double-bill."""
        asset = _make_ambiguous_asset("a1", tmp_path)
        vision = MockTextOCRVisionClient(text_responses=[])
        stage = OCRExtractionStage(vision_client=vision)
        context = PipelineContext(
            filing_id=1,
            html_path=Path("/tmp/x.html"),
            config=PipelineConfig(enable_image_keyword_prescan=True),
        )
        context.full_page_scan_mode = True  # pretend Path A fired
        context.images = [asset]

        stage._prescan_ambiguous_images(context)

        assert vision.text_call_count == 0
        assert asset.classification == ImageClassification.UNKNOWN

    def test_flag_off_skips_prescan(self, tmp_path: Path) -> None:
        asset = _make_ambiguous_asset("a1", tmp_path)
        vision = MockTextOCRVisionClient(text_responses=[])
        stage = OCRExtractionStage(vision_client=vision)
        context = PipelineContext(
            filing_id=1,
            html_path=Path("/tmp/x.html"),
            config=PipelineConfig(enable_image_keyword_prescan=False),
        )
        context.images = [asset]

        stage._prescan_ambiguous_images(context)

        assert vision.text_call_count == 0
        assert asset.classification == ImageClassification.UNKNOWN

    def test_only_ambiguous_images_processed(self, tmp_path: Path) -> None:
        """Pre-scan skips images outside the [0.2, 0.3) relevance band."""
        chart_img = _make_ambiguous_asset("chart_img", tmp_path, filename="chart.jpg")
        chart_img.classification = ImageClassification.CHART  # already classified
        chart_img.relevance_score = 0.5

        logo = _make_ambiguous_asset("logo", tmp_path, filename="logo.jpg")
        logo.classification = ImageClassification.LOGO  # already-low path
        logo.relevance_score = 0.0

        below = _make_ambiguous_asset("low", tmp_path, filename="low.jpg")
        below.relevance_score = 0.15  # below the pre-scan band

        eligible = _make_ambiguous_asset("elig", tmp_path, filename="elig.jpg")
        # default relevance 0.25 — in band

        vision = MockTextOCRVisionClient(
            text_responses=[
                _make_page_text_extraction(
                    text="Customer retention rate up 3 points year over year."
                )
            ]
        )
        stage = OCRExtractionStage(vision_client=vision)
        context = PipelineContext(
            filing_id=1,
            html_path=Path("/tmp/x.html"),
            config=PipelineConfig(enable_image_keyword_prescan=True),
        )
        context.images = [chart_img, logo, below, eligible]

        stage._prescan_ambiguous_images(context)

        # Only one image was pre-scanned (the in-band UNKNOWN one).
        assert vision.text_call_count == 1
        # That image got promoted.
        assert eligible.classification in {
            ImageClassification.CHART,
            ImageClassification.TABLE_IMAGE,
        }
        # Others untouched.
        assert chart_img.classification == ImageClassification.CHART
        assert logo.classification == ImageClassification.LOGO
        assert below.classification == ImageClassification.UNKNOWN

    def test_call_cap_enforced(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(OCRExtractionStage, "MAX_PRESCAN_CALLS_PER_DOCUMENT", 2)
        assets = [_make_ambiguous_asset(f"a{i}", tmp_path, filename=f"a{i}.jpg") for i in range(5)]
        # None match Tier-1 — pre-scan will call each image but not promote.
        vision = MockTextOCRVisionClient(
            text_responses=[_make_page_text_extraction(text="generic caption") for _ in range(5)]
        )
        stage = OCRExtractionStage(vision_client=vision)
        context = PipelineContext(
            filing_id=1,
            html_path=Path("/tmp/x.html"),
            config=PipelineConfig(enable_image_keyword_prescan=True),
        )
        context.images = assets

        stage._prescan_ambiguous_images(context)

        assert stage._prescan_call_count == 2
        assert vision.text_call_count == 2

    def test_process_end_to_end_prescan_promotes_then_extracts(self, tmp_path: Path) -> None:
        """End-to-end: process() runs pre-scan first, then the main loop
        processes the promoted image via the existing TABLE_IMAGE branch."""
        asset = _make_ambiguous_asset("a1", tmp_path)
        text_resp = _make_page_text_extraction(
            text="Retention rate: 2021 92%, 2022 94%",
            contains_chart=False,
        )
        # process_table_image will call analyze_image with a table prompt
        # and expect JSON with cells. We hand it a minimal-valid response
        # so the second-pass call completes without errors.
        table_resp = VisionResponse(
            content=json.dumps(
                {
                    "cells": [
                        {"row": 0, "col": 0, "text": "Year", "is_header": True},
                        {"row": 0, "col": 1, "text": "Retention", "is_header": True},
                        {"row": 1, "col": 0, "text": "2021", "is_header": False},
                        {"row": 1, "col": 1, "text": "92%", "is_header": False},
                    ],
                    "confidence": 0.85,
                }
            ),
            model="gpt-4o-mock",
            prompt_tokens=80,
            completion_tokens=60,
            cost_usd=0.01,
            latency_ms=10,
        )
        vision = MockTextOCRVisionClient(
            text_responses=[text_resp],
            chart_responses=[table_resp],
        )
        stage = OCRExtractionStage(vision_client=vision)
        context = PipelineContext(
            filing_id=1,
            html_path=Path("/tmp/x.html"),
            config=PipelineConfig(enable_image_keyword_prescan=True),
        )
        context.images = [asset]

        result = stage.process(context)

        # Pre-scan ran once; main loop ran the table-image path once.
        assert result.metadata["prescan_calls"] == 1
        assert vision.chart_call_count == 1  # second-pass (table)
        # Segment synthesized from the pre-scan.
        assert len(context.segments) == 1


class TestTier1KeywordsRe:
    """Tests that TIER1_KEYWORDS_RE is correctly built from metric_keywords.yaml."""

    @pytest.mark.parametrize(
        "metric_id,phrase",
        [
            ("cm_customer_retention_rate", "customer retention"),
            ("cm_net_revenue_retention", "net revenue retention"),
            ("cm_gross_revenue_retention", "gross revenue retention"),
            ("cm_revenue_by_cohort", "revenue by cohort"),
            ("cm_lifetime_value_per_customer", "lifetime value"),
            ("cm_customer_acquisition_cost", "customer acquisition cost"),
            ("cm_ltv_to_cac_ratio", "ltv to cac"),
            ("cm_revenue_concentration", "revenue concentration"),
            ("cm_large_customers_period_end", "large customers"),
            ("cm_new_customers_acquired", "new customers acquired"),
        ],
    )
    def test_known_phrases_match(self, metric_id: str, phrase: str) -> None:
        """Each Tier-1 metric phrase must be matched by the compiled regex."""
        assert OCRExtractionStage.TIER1_KEYWORDS_RE.search(phrase) is not None, (
            f"TIER1_KEYWORDS_RE did not match phrase {phrase!r} for metric {metric_id!r}"
        )

    def test_existing_example_still_matches(self) -> None:
        """Regression: phrase covering multiple Tier-1 metrics still matches."""
        assert (
            OCRExtractionStage.TIER1_KEYWORDS_RE.search("Customer retention rate by cohort")
            is not None
        )
