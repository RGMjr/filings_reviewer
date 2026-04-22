"""
Unit tests for A2 stage-level observability counters.

Validates that:
- image_triage StageResult.metadata contains per-classification counters that
  reconcile with images_seen (sum of all classified_* == images_seen).
- ocr_extraction StageResult.metadata contains A2 counters (skipped_for_missing_bytes,
  skipped_by_budget_cap, parse_failed, chart_data_none_after_processing).
- Counter reconciliation: skipped + processed + parse-failed accounts for all
  processable chart/table images.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.extraction_v2.models import (
    ImageAsset,
    ImageClassification,
)
from src.extraction_v2.pipeline import PipelineConfig, PipelineContext
from src.extraction_v2.stages.image_triage import ImageTriageStage
from src.extraction_v2.stages.ocr_extraction import OCRExtractionStage
from src.llm.vision_client import VisionResponse

# ---------------------------------------------------------------------------
# Shared fixture: route image storage to tmp_path (mirrors test_ocr_extraction)
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _route_image_cache_to_tmp(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from src.infra.image_storage import get_image_storage
    from src.infra.paths import image_cache_dir

    monkeypatch.setenv("IMAGE_CACHE_DIR", str(tmp_path))
    monkeypatch.delenv("R2_BUCKET", raising=False)
    image_cache_dir.cache_clear()
    get_image_storage.cache_clear()
    yield  # type: ignore[misc]
    image_cache_dir.cache_clear()
    get_image_storage.cache_clear()


# ---------------------------------------------------------------------------
# Minimal mock vision client (same shape as test_ocr_extraction.MockVisionClient)
# ---------------------------------------------------------------------------


class _MockVisionClient:
    def __init__(self, responses: list[VisionResponse]) -> None:
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
        if self.call_count >= len(self.responses):
            raise IndexError(f"No more mock responses (call_count={self.call_count})")
        response = self.responses[self.call_count]
        self.call_count += 1
        return response


def _make_context(tmp_path: Path, images: list[ImageAsset]) -> PipelineContext:
    return PipelineContext(
        html_path=tmp_path / "test.html",
        filing_id=1,
        config=PipelineConfig(),
        images=images,
    )


def _write_dummy_png(path: Path) -> None:
    """Write a minimal valid PNG to *path*."""
    path.write_bytes(
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
        b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01"
        b"\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
    )


# ===========================================================================
# image_triage counters
# ===========================================================================


class TestImageTriageCounters:
    """Per-classification counters in ImageTriageStage.process() metadata."""

    @pytest.fixture
    def stage(self) -> ImageTriageStage:
        return ImageTriageStage()

    def _make_triage_context(self, tmp_path: Path, images: list[ImageAsset]) -> PipelineContext:
        return PipelineContext(
            html_path=tmp_path / "test.html",
            filing_id=1,
            config=None,  # type: ignore[arg-type]
            images=images,
        )

    def test_images_seen_present(self, stage: ImageTriageStage, tmp_path: Path) -> None:
        """images_seen key must exist in metadata and equal len(context.images)."""
        images = [
            ImageAsset(img_id="1", filename="chart.png", width=800, height=600),
            ImageAsset(img_id="2", filename="logo.png", width=100, height=50),
        ]
        ctx = self._make_triage_context(tmp_path, images)
        result = stage.process(ctx)

        assert "images_seen" in result.metadata
        assert result.metadata["images_seen"] == 2

    def test_per_classification_keys_present(self, stage: ImageTriageStage, tmp_path: Path) -> None:
        """All expected per-classification keys must be present in metadata."""
        expected_keys = {
            "classified_chart",
            "classified_table",
            "classified_decorative",
            "classified_logo",
            "classified_signature",
            "classified_unknown",
            "classified_full_page_scan",
        }
        ctx = self._make_triage_context(
            tmp_path,
            [ImageAsset(img_id="1", filename="chart.png", width=800, height=600)],
        )
        result = stage.process(ctx)

        for key in expected_keys:
            assert key in result.metadata, f"Missing counter key: {key}"

    def test_classification_sum_equals_images_seen(
        self, stage: ImageTriageStage, tmp_path: Path
    ) -> None:
        """Sum of all classified_* counters must equal images_seen."""
        images = [
            ImageAsset(img_id="1", filename="revenue_chart.png", width=900, height=700),
            ImageAsset(img_id="2", filename="logo.png", width=80, height=60),
            ImageAsset(img_id="3", filename="ceo_signature.png", width=400, height=100),
            ImageAsset(img_id="4", filename="spacer.png", width=20, height=20),
            ImageAsset(
                img_id="5",
                filename="unknown.png",
                width=500,
                height=400,
                nearby_text="",
            ),
        ]
        ctx = self._make_triage_context(tmp_path, images)
        result = stage.process(ctx)

        classified_sum = (
            result.metadata["classified_chart"]
            + result.metadata["classified_table"]
            + result.metadata["classified_decorative"]
            + result.metadata["classified_logo"]
            + result.metadata["classified_signature"]
            + result.metadata["classified_unknown"]
            + result.metadata["classified_full_page_scan"]
        )
        assert classified_sum == result.metadata["images_seen"], (
            f"classified_sum={classified_sum} != images_seen={result.metadata['images_seen']}; "
            f"classification_counts={result.metadata['classification_counts']}"
        )

    def test_counters_consistent_with_classification_counts(
        self, stage: ImageTriageStage, tmp_path: Path
    ) -> None:
        """classified_chart must equal classification_counts['chart'] when present."""
        images = [
            ImageAsset(img_id="1", filename="revenue_chart.png", width=900, height=700),
            ImageAsset(img_id="2", filename="cohort_chart.png", width=900, height=700),
            ImageAsset(img_id="3", filename="logo.png", width=80, height=60),
        ]
        ctx = self._make_triage_context(tmp_path, images)
        result = stage.process(ctx)

        counts = result.metadata["classification_counts"]
        assert result.metadata["classified_chart"] == counts.get("chart", 0)
        assert result.metadata["classified_logo"] == counts.get("logo", 0)
        assert result.metadata["classified_decorative"] == counts.get("decorative", 0)

    def test_empty_images_returns_zero_counters(
        self, stage: ImageTriageStage, tmp_path: Path
    ) -> None:
        """Empty image list should produce metadata with message, not error."""
        ctx = self._make_triage_context(tmp_path, [])
        result = stage.process(ctx)
        assert result.success is True
        # Empty path returns early with a message key; no classification counters needed.
        assert "message" in result.metadata


# ===========================================================================
# ocr_extraction counters
# ===========================================================================


class TestOCRExtractionCounters:
    """A2 observability counters in OCRExtractionStage.process() metadata."""

    def _make_valid_table_response(self) -> VisionResponse:
        data = {
            "raw_text": "Year Revenue\n2021 $1B\n2022 $2B",
            "confidence": 0.95,
            "cells": [
                {"row": 0, "col": 0, "text": "Year", "is_header": True},
                {"row": 0, "col": 1, "text": "Revenue", "is_header": True},
                {"row": 1, "col": 0, "text": "2021", "is_header": False},
                {"row": 1, "col": 1, "text": "$1B", "is_header": False},
            ],
        }
        return VisionResponse(
            content=json.dumps(data),
            model="gpt-4o-mock",
            prompt_tokens=100,
            completion_tokens=50,
            cost_usd=0.01,
            latency_ms=200,
        )

    def _make_valid_chart_response(self) -> VisionResponse:
        data = {
            "chart_type": "bar",
            "title": "Revenue by Year",
            "x_axis_label": "Year",
            "y_axis_label": "Revenue",
            "confidence": 0.9,
            "series": [
                {
                    "name": "Revenue",
                    "points": [{"x": "2021", "y": 100.0, "label": "100"}],
                }
            ],
            "annotations": [],
        }
        return VisionResponse(
            content=json.dumps(data),
            model="gpt-4o-mock",
            prompt_tokens=100,
            completion_tokens=50,
            cost_usd=0.01,
            latency_ms=200,
        )

    def _make_invalid_json_response(self) -> VisionResponse:
        return VisionResponse(
            content="this is not json {{{broken",
            model="gpt-4o-mock",
            prompt_tokens=100,
            completion_tokens=50,
            cost_usd=0.01,
            latency_ms=200,
        )

    def test_new_counter_keys_present_on_normal_run(self, tmp_path: Path) -> None:
        """All A2 counter keys must be present in metadata even when counts are 0."""
        png = tmp_path / "chart.png"
        _write_dummy_png(png)

        mock_client = _MockVisionClient(responses=[self._make_valid_chart_response()])
        stage = OCRExtractionStage(vision_client=mock_client)

        images = [
            ImageAsset(
                img_id="c1",
                filename="chart.png",
                nearby_text="Revenue",
                width=800,
                height=600,
                classification=ImageClassification.CHART,
                relevance_score=0.9,
                processed=False,
                file_path=png.name,
            )
        ]
        ctx = _make_context(tmp_path, images)
        result = stage.process(ctx)

        for key in (
            "skipped_for_missing_bytes",
            "skipped_by_budget_cap",
            "parse_failed",
            "chart_data_none_after_processing",
        ):
            assert key in result.metadata, f"Missing A2 counter key: {key}"

    def test_skipped_by_budget_cap_increments_at_chart_limit(self, tmp_path: Path) -> None:
        """skipped_by_budget_cap must equal number of charts over the cap."""
        limit = OCRExtractionStage.MAX_CHART_CALLS_PER_DOCUMENT
        png = tmp_path / "chart.png"
        _write_dummy_png(png)

        # Provide exactly `limit` valid responses; remaining images will be skipped.
        mock_client = _MockVisionClient(
            responses=[self._make_valid_chart_response() for _ in range(limit)]
        )
        stage = OCRExtractionStage(vision_client=mock_client)

        over_limit = 3
        images = [
            ImageAsset(
                img_id=f"c{i}",
                filename="chart.png",
                nearby_text="Revenue",
                width=800,
                height=600,
                classification=ImageClassification.CHART,
                relevance_score=0.9,
                processed=False,
                file_path=png.name,
            )
            for i in range(limit + over_limit)
        ]
        ctx = _make_context(tmp_path, images)
        result = stage.process(ctx)

        assert result.metadata["skipped_by_budget_cap"] == over_limit
        assert result.metadata["chart_calls"] == limit

    def test_skipped_by_budget_cap_increments_at_ocr_limit(self, tmp_path: Path) -> None:
        """skipped_by_budget_cap must equal number of tables over the OCR cap."""
        limit = OCRExtractionStage.MAX_OCR_CALLS_PER_DOCUMENT
        png = tmp_path / "table.png"
        _write_dummy_png(png)

        mock_client = _MockVisionClient(
            responses=[self._make_valid_table_response() for _ in range(limit)]
        )
        stage = OCRExtractionStage(vision_client=mock_client)

        over_limit = 2
        images = [
            ImageAsset(
                img_id=f"t{i}",
                filename="table.png",
                nearby_text="Table",
                width=800,
                height=600,
                classification=ImageClassification.TABLE_IMAGE,
                relevance_score=0.9,
                processed=False,
                file_path=png.name,
            )
            for i in range(limit + over_limit)
        ]
        ctx = _make_context(tmp_path, images)
        result = stage.process(ctx)

        assert result.metadata["skipped_by_budget_cap"] == over_limit
        assert result.metadata["ocr_calls"] == limit

    def test_parse_failed_increments_on_bad_json_chart(self, tmp_path: Path) -> None:
        """parse_failed must be 1 when the vision API returns invalid JSON for a chart."""
        png = tmp_path / "chart.png"
        _write_dummy_png(png)

        mock_client = _MockVisionClient(responses=[self._make_invalid_json_response()])
        stage = OCRExtractionStage(vision_client=mock_client)

        images = [
            ImageAsset(
                img_id="c1",
                filename="chart.png",
                nearby_text="Revenue",
                width=800,
                height=600,
                classification=ImageClassification.CHART,
                relevance_score=0.9,
                processed=False,
                file_path=png.name,
            )
        ]
        ctx = _make_context(tmp_path, images)
        result = stage.process(ctx)

        assert result.metadata["parse_failed"] == 1

    def test_parse_failed_increments_on_bad_json_table(self, tmp_path: Path) -> None:
        """parse_failed must be 1 when the vision API returns invalid JSON for a table."""
        png = tmp_path / "table.png"
        _write_dummy_png(png)

        mock_client = _MockVisionClient(responses=[self._make_invalid_json_response()])
        stage = OCRExtractionStage(vision_client=mock_client)

        images = [
            ImageAsset(
                img_id="t1",
                filename="table.png",
                nearby_text="Revenue table",
                width=800,
                height=600,
                classification=ImageClassification.TABLE_IMAGE,
                relevance_score=0.9,
                processed=False,
                file_path=png.name,
            )
        ]
        ctx = _make_context(tmp_path, images)
        result = stage.process(ctx)

        assert result.metadata["parse_failed"] == 1

    def test_skipped_for_missing_bytes_on_missing_file(self, tmp_path: Path) -> None:
        """skipped_for_missing_bytes must increment when storage cannot find the file."""
        # file_path points to a key that was never written to storage
        stage = OCRExtractionStage(vision_client=_MockVisionClient(responses=[]))

        images = [
            ImageAsset(
                img_id="c1",
                filename="missing.png",
                nearby_text="Revenue",
                width=800,
                height=600,
                classification=ImageClassification.CHART,
                relevance_score=0.9,
                processed=False,
                file_path="missing.png",  # key exists on asset but bytes absent from storage
            )
        ]
        ctx = _make_context(tmp_path, images)
        result = stage.process(ctx)

        assert result.metadata["skipped_for_missing_bytes"] == 1
        # The image should be marked for manual capture
        assert images[0].requires_manual_capture is True

    def test_chart_data_none_after_processing_when_no_labeled_values(self, tmp_path: Path) -> None:
        """chart_data_none_after_processing must be 1 when chart yields no data/annotations."""
        png = tmp_path / "chart.png"
        _write_dummy_png(png)

        # Return a chart response with empty series and no annotations
        no_data = {
            "chart_type": "bar",
            "title": "Empty Chart",
            "x_axis_label": "",
            "y_axis_label": "",
            "confidence": 0.5,
            "series": [],
            "annotations": [],
        }
        response = VisionResponse(
            content=json.dumps(no_data),
            model="gpt-4o-mock",
            prompt_tokens=100,
            completion_tokens=30,
            cost_usd=0.005,
            latency_ms=150,
        )
        mock_client = _MockVisionClient(responses=[response])
        stage = OCRExtractionStage(vision_client=mock_client)

        images = [
            ImageAsset(
                img_id="c1",
                filename="chart.png",
                nearby_text="Revenue",
                width=800,
                height=600,
                classification=ImageClassification.CHART,
                relevance_score=0.9,
                processed=False,
                file_path=png.name,
            )
        ]
        ctx = _make_context(tmp_path, images)
        result = stage.process(ctx)

        assert result.metadata["chart_data_none_after_processing"] == 1
        assert images[0].chart_data is None

    def test_all_counters_zero_on_clean_run(self, tmp_path: Path) -> None:
        """On a successful run with no skips, all A2 failure counters are 0."""
        png = tmp_path / "chart.png"
        _write_dummy_png(png)

        mock_client = _MockVisionClient(responses=[self._make_valid_chart_response()])
        stage = OCRExtractionStage(vision_client=mock_client)

        images = [
            ImageAsset(
                img_id="c1",
                filename="chart.png",
                nearby_text="Revenue",
                width=800,
                height=600,
                classification=ImageClassification.CHART,
                relevance_score=0.9,
                processed=False,
                file_path=png.name,
            )
        ]
        ctx = _make_context(tmp_path, images)
        result = stage.process(ctx)

        assert result.metadata["skipped_for_missing_bytes"] == 0
        assert result.metadata["skipped_by_budget_cap"] == 0
        assert result.metadata["parse_failed"] == 0
        assert result.metadata["chart_data_none_after_processing"] == 0


# ===========================================================================
# Reconciliation invariants
# ===========================================================================


class TestCounterReconciliation:
    """Counter totals must account for all processable images."""

    def test_triage_total_reconciles(self, tmp_path: Path) -> None:
        """In image_triage: sum of classified_* == items_processed == images_seen."""
        stage = ImageTriageStage()
        images = [
            ImageAsset(img_id="1", filename="chart.png", width=900, height=700),
            ImageAsset(img_id="2", filename="logo.png", width=80, height=60),
            ImageAsset(img_id="3", filename="table.png", nearby_text="table summary"),
            ImageAsset(img_id="4", filename="banner.png", width=1200, height=100),
        ]
        ctx = PipelineContext(
            html_path=tmp_path / "test.html",
            filing_id=1,
            config=None,  # type: ignore[arg-type]
            images=images,
        )
        result = stage.process(ctx)

        classified_sum = (
            result.metadata["classified_chart"]
            + result.metadata["classified_table"]
            + result.metadata["classified_decorative"]
            + result.metadata["classified_logo"]
            + result.metadata["classified_signature"]
            + result.metadata["classified_unknown"]
            + result.metadata["classified_full_page_scan"]
        )
        assert classified_sum == result.metadata["images_seen"]
        assert result.metadata["images_seen"] == result.items_processed

    def test_ocr_budget_cap_accounts_for_over_limit_charts(self, tmp_path: Path) -> None:
        """processed_count + skipped_by_budget_cap must equal total chart images
        when every chart has bytes available (no other skip reason)."""
        png = tmp_path / "chart.png"
        _write_dummy_png(png)

        limit = OCRExtractionStage.MAX_CHART_CALLS_PER_DOCUMENT
        over_limit = 2
        total = limit + over_limit

        chart_resp = VisionResponse(
            content=json.dumps(
                {
                    "chart_type": "bar",
                    "title": "T",
                    "x_axis_label": "",
                    "y_axis_label": "",
                    "confidence": 0.9,
                    "series": [{"name": "S", "points": [{"x": "A", "y": 1.0, "label": "1"}]}],
                    "annotations": [],
                }
            ),
            model="gpt-4o-mock",
            prompt_tokens=100,
            completion_tokens=50,
            cost_usd=0.01,
            latency_ms=200,
        )
        stage = OCRExtractionStage(vision_client=_MockVisionClient(responses=[chart_resp] * limit))

        images = [
            ImageAsset(
                img_id=f"c{i}",
                filename="chart.png",
                nearby_text="Revenue",
                width=800,
                height=600,
                classification=ImageClassification.CHART,
                relevance_score=0.9,
                processed=False,
                file_path=png.name,
            )
            for i in range(total)
        ]
        ctx = _make_context(tmp_path, images)
        result = stage.process(ctx)

        assert result.items_processed == limit
        assert result.metadata["skipped_by_budget_cap"] == over_limit
        assert result.items_processed + result.metadata["skipped_by_budget_cap"] == total
