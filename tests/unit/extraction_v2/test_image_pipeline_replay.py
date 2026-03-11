"""
Unit tests for the image pipeline replay:
OCRExtractionStage (chart) -> ValueBindingStage -> BoundValues with period_hint.

Uses a mocked VisionClient to avoid real API calls.
"""

from __future__ import annotations

import json
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

from src.extraction_v2.models import (
    ChartAnnotation,
    ChartType,
    ImageAsset,
    ImageClassification,
    MetricCandidate,
    SourceLocator,
    SourceType,
)
from src.extraction_v2.stages.ocr_extraction import OCRExtractionStage
from src.extraction_v2.stages.value_binding import ValueBindingStage
from src.llm.vision_client import VisionResponse


# ============================================================================
# Fixtures and helpers
# ============================================================================


@dataclass
class MockPipelineConfig:
    min_confidence_auto_accept: float = 0.90
    min_confidence_no_review: float = 0.85
    max_confidence_auto_reject: float = 0.15


@dataclass
class MockPipelineContext:
    html_path: Path = field(default_factory=lambda: Path("/test/file.html"))
    filing_id: int = 1
    config: MockPipelineConfig = field(default_factory=MockPipelineConfig)
    segments: list[Any] = field(default_factory=list)
    tables: list[Any] = field(default_factory=list)
    images: list[Any] = field(default_factory=list)
    candidates: list[Any] = field(default_factory=list)
    bound_values: list[Any] = field(default_factory=list)
    cik: str = ""
    accession_number: str = ""
    ocr_calls: int = 0
    vision_calls: int = 0


def _valid_chart_json(
    series_points: list[dict[str, Any]] | None = None,
    annotations: list[dict[str, Any]] | None = None,
) -> str:
    """Return a JSON string matching the chart extraction prompt format."""
    payload: dict[str, Any] = {
        "chart_type": "bar",
        "title": "ARR by Year",
        "x_axis_label": "Year",
        "y_axis_label": "ARR ($M)",
        "confidence": 0.88,
        "series": [
            {
                "name": "ARR",
                "points": series_points
                if series_points is not None
                else [
                    {"x": "2020", "y": 100.0, "label": "100M"},
                    {"x": "2021", "y": 200.0, "label": "200M"},
                ],
            }
        ],
        "annotations": annotations if annotations is not None else [],
    }
    return json.dumps(payload)


def _make_vision_response(content: str) -> VisionResponse:
    return VisionResponse(
        content=content,
        model="gpt-4o",
        prompt_tokens=100,
        completion_tokens=50,
        cost_usd=0.001,
        latency_ms=200,
    )


def _make_chart_asset(img_id: str, tmp_path: Path) -> ImageAsset:
    """Create an ImageAsset with a real (minimal) JPEG file for OCR stage."""
    # Minimal 1x1 white JPEG
    jpeg_bytes = bytes(
        [
            0xFF, 0xD8, 0xFF, 0xE0, 0x00, 0x10, 0x4A, 0x46, 0x49, 0x46, 0x00, 0x01,
            0x01, 0x00, 0x00, 0x01, 0x00, 0x01, 0x00, 0x00,
            0xFF, 0xDB, 0x00, 0x43, 0x00,
        ] + [0x08] * 64 + [
            0xFF, 0xC0, 0x00, 0x0B, 0x08, 0x00, 0x01, 0x00, 0x01, 0x01, 0x01, 0x11, 0x00,
            0xFF, 0xC4, 0x00, 0x1F, 0x00,
        ] + [0x00] * 29 + [
            0xFF, 0xC4, 0x00, 0x1F, 0x10,
        ] + [0x00] * 29 + [
            0xFF, 0xDA, 0x00, 0x08, 0x01, 0x01, 0x00, 0x00, 0x3F, 0x00,
            0x7F, 0xFF, 0xD9,
        ]
    )
    img_file = tmp_path / f"{img_id}.jpg"
    img_file.write_bytes(jpeg_bytes)

    return ImageAsset(
        img_id=img_id,
        filename=f"{img_id}.jpg",
        file_path=str(img_file),
        classification=ImageClassification.CHART,
        relevance_score=0.7,
        nearby_text="annual recurring revenue growth",
    )


# ============================================================================
# Tests
# ============================================================================


class TestImagePipelineReplay:
    """Integration-style tests: OCRExtractionStage -> ValueBindingStage."""

    def test_chart_data_populated_after_ocr(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """VisionClient.analyze_image mock -> OCRExtractionStage -> chart_data populated."""
        img_id = "replay-chart-1"
        asset = _make_chart_asset(img_id, tmp_path)

        mock_response = _make_vision_response(_valid_chart_json())

        # Patch analyze_image on the class
        monkeypatch.setattr(
            "src.llm.vision_client.VisionClient.analyze_image",
            lambda self, **kwargs: mock_response,
        )

        # Build stage with a real VisionClient (analyze_image is patched)
        from src.llm.vision_client import VisionClient

        stage = OCRExtractionStage(vision_client=VisionClient.__new__(VisionClient))

        context = MockPipelineContext(images=[asset])
        result = stage.process(context)  # type: ignore

        assert result.success, result.errors
        assert asset.chart_data is not None
        assert asset.chart_data.chart_type == ChartType.BAR
        assert len(asset.chart_data.series) == 1
        assert len(asset.chart_data.series[0].points) == 2

    def test_bound_values_have_period_hint_after_full_replay(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """End-to-end: OCRExtractionStage + ValueBindingStage -> BoundValues with period_hint."""
        img_id = "replay-chart-2"
        asset = _make_chart_asset(img_id, tmp_path)

        mock_response = _make_vision_response(_valid_chart_json())
        monkeypatch.setattr(
            "src.llm.vision_client.VisionClient.analyze_image",
            lambda self, **kwargs: mock_response,
        )

        from src.llm.vision_client import VisionClient

        ocr_stage = OCRExtractionStage(vision_client=VisionClient.__new__(VisionClient))
        binding_stage = ValueBindingStage()

        candidate = MetricCandidate(
            candidate_id="cand-replay-2",
            metric_id="cm_arr",
            match_text="ARR",
            source_type=SourceType.CHART,
            source_locator=SourceLocator(img_id=img_id),
        )

        context = MockPipelineContext(images=[asset], candidates=[candidate])

        # Run Stage 5 then Stage 7
        ocr_result = ocr_stage.process(context)  # type: ignore
        assert ocr_result.success, ocr_result.errors

        binding_result = binding_stage.process(context)  # type: ignore
        assert binding_result.success, binding_result.errors

        chart_label_bvs = [
            bv for bv in context.bound_values if bv.binding_type == "chart_label"
        ]
        assert len(chart_label_bvs) == 2

        period_hints = {bv.period_hint for bv in chart_label_bvs}
        assert "2020" in period_hints
        assert "2021" in period_hints

    def test_context_vision_calls_incremented(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """After OCRExtractionStage, context.vision_calls is incremented."""
        img_id = "replay-chart-3"
        asset = _make_chart_asset(img_id, tmp_path)

        mock_response = _make_vision_response(_valid_chart_json())
        monkeypatch.setattr(
            "src.llm.vision_client.VisionClient.analyze_image",
            lambda self, **kwargs: mock_response,
        )

        from src.llm.vision_client import VisionClient

        stage = OCRExtractionStage(vision_client=VisionClient.__new__(VisionClient))
        context = MockPipelineContext(images=[asset])

        assert context.vision_calls == 0
        stage.process(context)  # type: ignore
        assert context.vision_calls == 2  # two-pass: Pass 1 (classify) + Pass 2 (extract)
