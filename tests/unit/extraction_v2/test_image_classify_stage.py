"""Unit tests for ImageClassifyStage.

The stage must:
  - skip when `enable_metric_classify=False`
  - skip non-chart / non-table_image classifications (cost gate)
  - emit an ImageClassificationRecord for each classifiable image on happy path
  - record cost/latency alongside the vision output
  - return `None` (skip the image) when the Vision API errors
  - return `None` (skip the image) when the parser returns None
  - persist below-threshold confidence (threshold is a downstream signal, not a gate)
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from unittest.mock import patch

import pytest

from src.extraction_v2.models import (
    ImageAsset,
    ImageClassification,
    ImageClassificationRecord,
)
from src.extraction_v2.pipeline import PipelineConfig, PipelineContext
from src.extraction_v2.stages.image_classify import ImageClassifyStage


@pytest.fixture
def chart_image() -> ImageAsset:
    return ImageAsset(
        img_id="img-chart-1",
        classification=ImageClassification.CHART,
        file_path="pipeline/1/chart.png",
        confidence=0.95,
    )


@pytest.fixture
def table_image() -> ImageAsset:
    return ImageAsset(
        img_id="img-table-1",
        classification=ImageClassification.TABLE_IMAGE,
        file_path="pipeline/1/table.png",
        confidence=0.85,
    )


@pytest.fixture
def decorative_image() -> ImageAsset:
    return ImageAsset(
        img_id="img-dec-1",
        classification=ImageClassification.DECORATIVE,
        file_path="pipeline/1/logo.png",
    )


def _make_context(images, *, enabled: bool = True) -> PipelineContext:
    config = PipelineConfig(enable_metric_classify=enabled)
    return PipelineContext(
        html_path=Path("/test/filing.html"),
        filing_id=1,
        config=config,
        document_date=date(2024, 12, 31),
        images=list(images),
    )


def _happy_parse_return(metric_ids, confidence, *, rejection_reason=None, reasoning="ok"):
    return {
        "predicted_metrics": list(metric_ids),
        "confidence": confidence,
        "rejection_reason": rejection_reason,
        "reasoning": reasoning,
    }


class TestGate:
    def test_skipped_when_flag_off(self, chart_image):
        context = _make_context([chart_image], enabled=False)

        with patch("src.extraction_v2.stages.image_classify.VisionClient") as mock_client:
            result = ImageClassifyStage().process(context)

        assert result.items_processed == 0
        assert result.items_output == 0
        assert context.image_classifications == []
        mock_client.assert_not_called()

    def test_skips_decorative(self, decorative_image):
        context = _make_context([decorative_image])

        with patch("src.extraction_v2.stages.image_classify.VisionClient") as mock_client:
            result = ImageClassifyStage().process(context)

        assert result.items_processed == 0
        assert context.image_classifications == []
        mock_client.assert_not_called()

    def test_skips_when_file_path_missing(self, chart_image):
        chart_image.file_path = None
        context = _make_context([chart_image])

        with patch("src.extraction_v2.stages.image_classify.VisionClient") as mock_client:
            result = ImageClassifyStage().process(context)

        assert result.items_processed == 0
        mock_client.assert_not_called()


class TestClassifiablePath:
    @patch("src.extraction_v2.stages.image_classify.get_image_storage")
    @patch("src.extraction_v2.stages.image_classify.VisionClient")
    def test_emits_record_on_happy_path(self, mock_client_cls, mock_storage, chart_image):
        mock_storage.return_value.get_bytes.return_value = b"PNGBYTES"
        mock_client_cls.return_value.analyze_image_for_metric_classification.return_value = (
            _happy_parse_return(["cm_revenue_by_cohort"], 0.87, reasoning="cohort-bar shape")
        )

        context = _make_context([chart_image])
        result = ImageClassifyStage().process(context)

        assert result.items_processed == 1
        assert result.items_output == 1
        assert len(context.image_classifications) == 1
        rec = context.image_classifications[0]
        assert isinstance(rec, ImageClassificationRecord)
        assert rec.img_id == "img-chart-1"
        assert rec.predicted_metrics == [{"metric_id": "cm_revenue_by_cohort", "score": 0.87}]
        assert rec.confidence == pytest.approx(0.87)
        assert rec.rejection_reason is None
        assert rec.reasoning == "cohort-bar shape"
        assert rec.provider == "gemini"
        assert rec.model == "gemini-2.5-flash-lite"
        assert rec.prompt_version == ImageClassifyStage.PROMPT_VERSION
        assert rec.latency_ms >= 0
        assert rec.cost_usd == 0.0  # helper doesn't surface cost yet

    @patch("src.extraction_v2.stages.image_classify.get_image_storage")
    @patch("src.extraction_v2.stages.image_classify.VisionClient")
    def test_rejection_reason_threaded_through(self, mock_client_cls, mock_storage, chart_image):
        mock_storage.return_value.get_bytes.return_value = b"PNGBYTES"
        mock_client_cls.return_value.analyze_image_for_metric_classification.return_value = (
            _happy_parse_return([], 0.05, rejection_reason="not_a_chart", reasoning="photo")
        )

        context = _make_context([chart_image])
        ImageClassifyStage().process(context)

        rec = context.image_classifications[0]
        assert rec.predicted_metrics == []
        assert rec.rejection_reason == "not_a_chart"

    @patch("src.extraction_v2.stages.image_classify.get_image_storage")
    @patch("src.extraction_v2.stages.image_classify.VisionClient")
    def test_below_threshold_still_persisted(self, mock_client_cls, mock_storage, chart_image):
        # threshold=0.5 by default; confidence 0.3 is below — but the record
        # must still land (threshold is a downstream interpretation signal)
        mock_storage.return_value.get_bytes.return_value = b"PNGBYTES"
        mock_client_cls.return_value.analyze_image_for_metric_classification.return_value = (
            _happy_parse_return(["cm_revenue_concentration"], 0.30)
        )

        context = _make_context([chart_image])
        result = ImageClassifyStage().process(context)

        assert result.items_output == 1
        assert context.image_classifications[0].confidence == pytest.approx(0.30)

    @patch("src.extraction_v2.stages.image_classify.get_image_storage")
    @patch("src.extraction_v2.stages.image_classify.VisionClient")
    def test_table_image_also_classifiable(self, mock_client_cls, mock_storage, table_image):
        mock_storage.return_value.get_bytes.return_value = b"PNGBYTES"
        mock_client_cls.return_value.analyze_image_for_metric_classification.return_value = (
            _happy_parse_return(
                [], 0.0, rejection_reason="table_handled_elsewhere", reasoning="table"
            )
        )

        context = _make_context([table_image])
        result = ImageClassifyStage().process(context)

        assert result.items_processed == 1
        assert context.image_classifications[0].rejection_reason == "table_handled_elsewhere"


class TestFailureModes:
    @patch("src.extraction_v2.stages.image_classify.get_image_storage")
    @patch("src.extraction_v2.stages.image_classify.VisionClient")
    def test_api_error_skips_image(self, mock_client_cls, mock_storage, chart_image):
        mock_storage.return_value.get_bytes.return_value = b"PNGBYTES"
        mock_client_cls.return_value.analyze_image_for_metric_classification.side_effect = (
            RuntimeError("API down")
        )

        context = _make_context([chart_image])
        result = ImageClassifyStage().process(context)

        assert result.items_processed == 1
        assert result.items_output == 0
        assert result.metadata["api_errors"] == 1
        assert context.image_classifications == []

    @patch("src.extraction_v2.stages.image_classify.get_image_storage")
    @patch("src.extraction_v2.stages.image_classify.VisionClient")
    def test_unparseable_response_skips_image(self, mock_client_cls, mock_storage, chart_image):
        mock_storage.return_value.get_bytes.return_value = b"PNGBYTES"
        mock_client_cls.return_value.analyze_image_for_metric_classification.return_value = None

        context = _make_context([chart_image])
        result = ImageClassifyStage().process(context)

        assert result.items_output == 0
        assert result.metadata["api_errors"] == 1
        assert context.image_classifications == []

    @patch("src.extraction_v2.stages.image_classify.get_image_storage")
    @patch("src.extraction_v2.stages.image_classify.VisionClient")
    def test_missing_image_bytes_skips_image(self, mock_client_cls, mock_storage, chart_image):
        mock_storage.return_value.get_bytes.side_effect = FileNotFoundError("gone")

        context = _make_context([chart_image])
        result = ImageClassifyStage().process(context)

        assert result.items_output == 0
        assert context.image_classifications == []
        mock_client_cls.return_value.analyze_image_for_metric_classification.assert_not_called()


class TestConfigPlumbing:
    @patch("src.extraction_v2.stages.image_classify.get_image_storage")
    @patch("src.extraction_v2.stages.image_classify.VisionClient")
    def test_provider_and_model_recorded(self, mock_client_cls, mock_storage, chart_image):
        mock_storage.return_value.get_bytes.return_value = b"PNGBYTES"
        mock_client_cls.return_value.analyze_image_for_metric_classification.return_value = (
            _happy_parse_return(["cm_customer_retention_rate"], 0.90)
        )

        config = PipelineConfig(
            enable_metric_classify=True,
            vision_classify_provider="openai",
            vision_classify_model="gpt-4o-2024-08-06",
        )
        context = PipelineContext(
            html_path=Path("/test/filing.html"),
            filing_id=1,
            config=config,
            document_date=date(2024, 12, 31),
            images=[chart_image],
        )
        ImageClassifyStage().process(context)

        rec = context.image_classifications[0]
        assert rec.provider == "openai"
        assert rec.model == "gpt-4o-2024-08-06"
