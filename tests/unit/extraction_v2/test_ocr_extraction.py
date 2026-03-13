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
    ImageExtractionMeta,
)
from src.extraction_v2.pipeline import PipelineConfig, PipelineContext, PipelineStage
from src.extraction_v2.stages.ocr_extraction import OCRExtractionStage
from src.llm.vision_client import VisionResponse


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
    ) -> VisionResponse:
        """Return next mocked response."""
        if self.call_count >= len(self.responses):
            raise IndexError(f"No more mock responses available (call_count={self.call_count})")
        response = self.responses[self.call_count]
        self.call_count += 1
        return response


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
            file_path=str(temp_image_file),
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

        # Verify extraction_meta telemetry
        assert asset.extraction_meta is not None
        assert isinstance(asset.extraction_meta, ImageExtractionMeta)
        assert asset.extraction_meta.parse_success is True
        assert asset.extraction_meta.vision_model == "gpt-4o"
        assert asset.extraction_meta.prompt_tokens == 1000
        assert asset.extraction_meta.completion_tokens == 200
        assert asset.extraction_meta.extraction_mode == "exact"
        assert asset.extraction_meta.skip_reason == ""

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
            file_path=str(temp_image_file),
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
            file_path=str(temp_image_file),
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
            file_path=str(temp_image_file),
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
            file_path="/nonexistent/path/image.png",
        )

        with pytest.raises(FileNotFoundError):
            stage.process_table_image(asset)


def _make_pass1_response(chart_type: str = "bar") -> VisionResponse:
    """Return a standard Pass 1 classification response for two-pass tests."""
    return VisionResponse(
        content=json.dumps(
            {
                "chart_type": chart_type,
                "has_data_labels": True,
                "x_label": "X",
                "y_label": "Y",
                "y_min": 0,
                "y_max": 2000,
                "y_ticks": [0, 500, 1000, 1500, 2000],
                "x_categories": [],
                "legend_entries": [],
                "estimated_series_count": 1,
                "confidence": 0.88,
            }
        ),
        model="gpt-4o",
        prompt_tokens=100,
        completion_tokens=80,
        cost_usd=0.005,
        latency_ms=300,
    )


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

        pass2_response = VisionResponse(
            content=json.dumps(chart_data),
            model="gpt-4o",
            prompt_tokens=1500,
            completion_tokens=300,
            cost_usd=0.08,
            latency_ms=600,
        )

        # Two-pass: Pass 1 classification response followed by Pass 2 extraction response
        pass1_response = _make_pass1_response("bar")
        mock_client = MockVisionClient(responses=[pass1_response, pass2_response])
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
            file_path=str(temp_image_file),
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

        # Verify extraction_meta telemetry (summed across both passes)
        assert asset.extraction_meta is not None
        assert isinstance(asset.extraction_meta, ImageExtractionMeta)
        assert asset.extraction_meta.parse_success is True
        assert asset.extraction_meta.vision_model == "gpt-4o"
        assert asset.extraction_meta.prompt_tokens == pass1_response.prompt_tokens + 1500
        assert asset.extraction_meta.completion_tokens == pass1_response.completion_tokens + 300
        assert asset.extraction_meta.extraction_mode == "exact"
        assert asset.extraction_meta.skip_reason == ""

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

        pass2_response = VisionResponse(
            content=json.dumps(chart_data),
            model="gpt-4o",
            prompt_tokens=1500,
            completion_tokens=200,
            cost_usd=0.06,
            latency_ms=500,
        )

        mock_client = MockVisionClient(responses=[_make_pass1_response("line"), pass2_response])
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
            file_path=str(temp_image_file),
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
            file_path=str(temp_image_file),
        )

        stage.process_chart(asset)

        assert asset.processed is True
        assert asset.confidence == 0.0
        assert asset.requires_manual_capture is True

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

        pass2_response = VisionResponse(
            content=json.dumps(chart_data),
            model="gpt-4o",
            prompt_tokens=1500,
            completion_tokens=200,
            cost_usd=0.05,
            latency_ms=450,
        )

        mock_client = MockVisionClient(responses=[_make_pass1_response("bar"), pass2_response])
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
            file_path=str(temp_image_file),
        )

        stage.process_chart(asset)

        assert asset.processed is True
        assert asset.confidence == 0.0
        assert asset.requires_manual_capture is True


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
            # OCR table response (single call)
            VisionResponse(
                content=json.dumps(table_data),
                model="gpt-4o",
                prompt_tokens=1000,
                completion_tokens=200,
                cost_usd=0.05,
                latency_ms=500,
            ),
            # Chart Pass 1: classification
            _make_pass1_response("bar"),
            # Chart Pass 2: extraction
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
                file_path=str(temp_image_file),
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
                file_path=str(temp_image_file),
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
        assert result.metadata["chart_calls"] == 2  # two-pass: Pass 1 + Pass 2
        assert result.metadata["total_api_calls"] == 2  # 2 images processed (1 OCR + 1 chart)

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
                file_path=str(temp_image_file),
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
                file_path=str(temp_image_file),
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
        """vision_client property raises when OPENAI_API_KEY is missing.

        After the factory refactor, the error comes from the OpenAI SDK itself
        (openai.OpenAIError) rather than a V2FatalError, since key validation
        is now handled inside OpenAIVisionProvider.__init__.
        """
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        stage = OCRExtractionStage()  # No pre-set vision_client
        with pytest.raises(Exception):  # noqa: B017
            _ = stage.vision_client

    def test_vision_client_does_not_raise_when_key_set(self, monkeypatch: pytest.MonkeyPatch) -> None:
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

    def test_vision_client_not_checked_when_already_set(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Pre-set vision_client should bypass the API key check."""

        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        mock_client = object()
        stage = OCRExtractionStage(vision_client=mock_client)
        # Should return the pre-set client without raising
        result = stage.vision_client
        assert result is mock_client
