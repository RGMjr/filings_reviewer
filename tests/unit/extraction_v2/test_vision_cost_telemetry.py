"""
Per-call-site vision cost telemetry (PR 1 of vision cost experiments).

Validates that each of the six vision call sites attributes its
``VisionResponse.cost_usd`` (or ``PageTextExtraction.cost_usd``) into the
correct bucket of ``StageResult.metadata['vision_spend_usd_by_site']``,
and that ``PipelineResult.vision_spend_usd_by_site`` aggregates these
buckets across all stages.

Sites covered:
- table_ocr (OCRExtractionStage.process_table_image)
- chart_read_premium (OCRExtractionStage.process_chart, legacy + two-stage)
- chart_ocr_fast (OCRExtractionStage.process_chart, two-stage only)
- full_page_ocr (OCRExtractionStage.process_full_page_scan)
- prescan (OCRExtractionStage._prescan_ambiguous_images)
- metric_classify (ImageClassifyStage.process)
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from src.extraction_v2.models import (
    Document,
    ImageAsset,
    ImageClassification,
)
from src.extraction_v2.pipeline import (
    PipelineConfig,
    PipelineContext,
    PipelineResult,
    PipelineStage,
    StageResult,
)
from src.extraction_v2.stages.image_classify import ImageClassifyStage
from src.extraction_v2.stages.ocr_extraction import OCRExtractionStage
from src.llm.vision_client import PageTextExtraction, VisionResponse

# ---------------------------------------------------------------------------
# Fixtures shared with other ocr_extraction unit tests — route image storage
# at the worker tmp_path so get_bytes() resolves the on-disk file.
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


def _write_dummy_png(path: Path) -> None:
    path.write_bytes(
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
        b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01"
        b"\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
    )


def _make_context(tmp_path: Path, images: list[ImageAsset]) -> PipelineContext:
    return PipelineContext(
        html_path=tmp_path / "test.html",
        filing_id=1,
        config=PipelineConfig(),
        images=images,
    )


def _vision_response(content: str | dict[str, Any], *, cost: float) -> VisionResponse:
    if isinstance(content, dict):
        content = json.dumps(content)
    return VisionResponse(
        content=content,
        model="mock",
        prompt_tokens=10,
        completion_tokens=10,
        cost_usd=cost,
        latency_ms=1,
    )


def _valid_chart_payload() -> dict[str, Any]:
    return {
        "chart_type": "bar",
        "title": "Revenue",
        "x_axis_label": "Year",
        "y_axis_label": "USD",
        "confidence": 0.9,
        "series": [{"name": "Revenue", "points": [{"x": "2021", "y": 100.0, "label": "100"}]}],
        "annotations": [],
    }


def _valid_table_payload() -> dict[str, Any]:
    return {
        "raw_text": "Year Revenue\n2021 $1B",
        "confidence": 0.9,
        "cells": [
            {"row": 0, "col": 0, "text": "Year", "is_header": True},
            {"row": 0, "col": 1, "text": "Revenue", "is_header": True},
            {"row": 1, "col": 0, "text": "2021", "is_header": False},
            {"row": 1, "col": 1, "text": "$1B", "is_header": False},
        ],
    }


def _valid_chart_ocr_payload() -> dict[str, Any]:
    """Fast-OCR pass response — used by two-stage chart routing."""
    return {"text": "Revenue\n2021\n100", "labels": ["Revenue", "2021", "100"]}


# ---------------------------------------------------------------------------
# Mocks — kept tiny because each test cares about per-call cost, not content
# ---------------------------------------------------------------------------


class _SequencedVisionClient:
    """Vision client that hands out pre-built VisionResponses in order.

    Each call to ``analyze_image`` / ``analyze_image_targeted`` consumes
    one response from ``responses``; ``analyze_image_for_text`` consumes
    one from ``text_responses``. Useful when a single test stresses one
    site at a time.
    """

    def __init__(
        self,
        responses: list[VisionResponse] | None = None,
        text_responses: list[PageTextExtraction] | None = None,
    ) -> None:
        self.responses = responses or []
        self.text_responses = text_responses or []
        self.call_count = 0
        self.text_call_count = 0
        self.model = "mock"

    def analyze_image(self, image_bytes: bytes, prompt: str, **_: Any) -> VisionResponse:
        if self.call_count >= len(self.responses):
            raise IndexError(f"no more vision responses (call_count={self.call_count})")
        resp = self.responses[self.call_count]
        self.call_count += 1
        return resp

    def analyze_image_targeted(
        self, image_bytes: bytes, prompt: str, *, task_type: str, **_: Any
    ) -> VisionResponse:
        return self.analyze_image(image_bytes=image_bytes, prompt=prompt)

    def analyze_image_for_text(
        self, *, image_bytes: bytes, max_tokens: int = 3000
    ) -> PageTextExtraction:
        if self.text_call_count >= len(self.text_responses):
            raise IndexError(f"no more text responses (text_call_count={self.text_call_count})")
        resp = self.text_responses[self.text_call_count]
        self.text_call_count += 1
        return resp


# ---------------------------------------------------------------------------
# Per-site bucket attribution
# ---------------------------------------------------------------------------


class TestPerSiteBuckets:
    def test_metadata_includes_vision_spend_usd_by_site_keys(self, tmp_path: Path) -> None:
        """All five OCR-stage site keys must be present even when only one fires."""
        png = tmp_path / "chart.png"
        _write_dummy_png(png)
        client = _SequencedVisionClient(
            responses=[_vision_response(_valid_chart_payload(), cost=0.02)]
        )
        stage = OCRExtractionStage(vision_client=client)
        images = [
            ImageAsset(
                img_id="c1",
                filename="chart.png",
                nearby_text="Revenue",
                width=800,
                height=600,
                classification=ImageClassification.CHART,
                relevance_score=0.9,
                file_path=png.name,
            )
        ]
        result = stage.process(_make_context(tmp_path, images))

        spend = result.metadata["vision_spend_usd_by_site"]
        for site in (
            "table_ocr",
            "chart_ocr_fast",
            "chart_read_premium",
            "full_page_ocr",
            "prescan",
        ):
            assert site in spend, f"missing site key {site!r}"

    def test_table_ocr_cost_attributed_to_table_ocr_bucket(self, tmp_path: Path) -> None:
        png = tmp_path / "table.png"
        _write_dummy_png(png)
        client = _SequencedVisionClient(
            responses=[_vision_response(_valid_table_payload(), cost=0.03)]
        )
        stage = OCRExtractionStage(vision_client=client)
        images = [
            ImageAsset(
                img_id="t1",
                filename="table.png",
                nearby_text="Revenue table",
                width=800,
                height=600,
                classification=ImageClassification.TABLE_IMAGE,
                relevance_score=0.9,
                file_path=png.name,
            )
        ]
        result = stage.process(_make_context(tmp_path, images))

        spend = result.metadata["vision_spend_usd_by_site"]
        assert spend["table_ocr"] == pytest.approx(0.03)
        assert spend["chart_read_premium"] == 0.0
        assert spend["chart_ocr_fast"] == 0.0

    def test_chart_legacy_mode_attributes_to_chart_read_premium(self, tmp_path: Path) -> None:
        """In legacy mode (no VISION_ROUTING_MODE), chart_read_premium gets the full cost."""
        png = tmp_path / "chart.png"
        _write_dummy_png(png)
        client = _SequencedVisionClient(
            responses=[_vision_response(_valid_chart_payload(), cost=0.05)]
        )
        stage = OCRExtractionStage(vision_client=client)
        images = [
            ImageAsset(
                img_id="c1",
                filename="chart.png",
                nearby_text="Revenue",
                width=800,
                height=600,
                classification=ImageClassification.CHART,
                relevance_score=0.9,
                file_path=png.name,
            )
        ]
        result = stage.process(_make_context(tmp_path, images))

        spend = result.metadata["vision_spend_usd_by_site"]
        assert spend["chart_read_premium"] == pytest.approx(0.05)
        assert spend["chart_ocr_fast"] == 0.0

    def test_chart_two_stage_mode_attributes_both_chart_buckets(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Two-stage mode runs the fast OCR pass first; both costs bucket separately."""
        monkeypatch.setenv("VISION_ROUTING_MODE", "two_stage")

        png = tmp_path / "chart.png"
        _write_dummy_png(png)
        client = _SequencedVisionClient(
            responses=[
                _vision_response(_valid_chart_ocr_payload(), cost=0.001),
                _vision_response(_valid_chart_payload(), cost=0.04),
            ]
        )
        stage = OCRExtractionStage(vision_client=client)
        images = [
            ImageAsset(
                img_id="c1",
                filename="chart.png",
                nearby_text="Revenue",
                width=800,
                height=600,
                classification=ImageClassification.CHART,
                relevance_score=0.9,
                file_path=png.name,
            )
        ]
        result = stage.process(_make_context(tmp_path, images))

        spend = result.metadata["vision_spend_usd_by_site"]
        assert spend["chart_ocr_fast"] == pytest.approx(0.001)
        assert spend["chart_read_premium"] == pytest.approx(0.04)

    def test_full_page_ocr_attributes_to_full_page_ocr_bucket(self, tmp_path: Path) -> None:
        jpg = tmp_path / "page.jpg"
        jpg.write_bytes(b"\xff\xd8\xff\xe0fake-jpeg-bytes")

        client = _SequencedVisionClient(
            text_responses=[
                PageTextExtraction(
                    text="Q3 revenue $100M",
                    contains_chart=False,
                    contains_table=False,
                    chart_hint="none",
                    cost_usd=0.02,
                    raw_response="",
                )
            ]
        )
        stage = OCRExtractionStage(vision_client=client)
        images = [
            ImageAsset(
                img_id="p1",
                filename="page.jpg",
                file_path=jpg.name,
                width=1055,
                height=1365,
                classification=ImageClassification.FULL_PAGE_SCAN,
                relevance_score=0.6,
            )
        ]
        ctx = PipelineContext(
            html_path=tmp_path / "test.html",
            filing_id=1,
            config=PipelineConfig(enable_full_page_ocr=True),
            images=images,
        )
        result = stage.process(ctx)

        spend = result.metadata["vision_spend_usd_by_site"]
        assert spend["full_page_ocr"] == pytest.approx(0.02)
        assert spend["chart_read_premium"] == 0.0

    def test_prescan_attributes_to_prescan_bucket(self, tmp_path: Path) -> None:
        """Pre-scan promotes UNKNOWN images that hit a Tier-1 keyword in OCR text."""
        png = tmp_path / "ambig.png"
        _write_dummy_png(png)

        client = _SequencedVisionClient(
            text_responses=[
                PageTextExtraction(
                    text="Customer retention rate by cohort 95%",
                    contains_chart=False,
                    contains_table=True,
                    chart_hint="none",
                    cost_usd=0.004,
                    raw_response="",
                )
            ],
            responses=[_vision_response(_valid_table_payload(), cost=0.03)],
        )
        stage = OCRExtractionStage(vision_client=client)
        images = [
            ImageAsset(
                img_id="u1",
                filename="ambig.png",
                file_path=png.name,
                nearby_text="",
                width=800,
                height=600,
                classification=ImageClassification.UNKNOWN,
                relevance_score=0.25,
            )
        ]
        ctx = PipelineContext(
            html_path=tmp_path / "test.html",
            filing_id=1,
            config=PipelineConfig(enable_image_keyword_prescan=True),
            images=images,
        )
        result = stage.process(ctx)

        spend = result.metadata["vision_spend_usd_by_site"]
        assert spend["prescan"] == pytest.approx(0.004)
        # Promoted to TABLE_IMAGE then table OCR ran on it — confirms no
        # double-attribution of the prescan cost into table_ocr.
        assert spend["table_ocr"] == pytest.approx(0.03)


# ---------------------------------------------------------------------------
# ImageClassifyStage cost aggregation
# ---------------------------------------------------------------------------


class TestImageClassifyCost:
    def test_metric_classify_metadata_emits_per_site_dict(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Stage metadata must include vision_spend_usd_by_site={metric_classify: <sum>}."""
        png = tmp_path / "img.png"
        _write_dummy_png(png)

        # Patch _classify_one to return synthetic records with known cost.
        # This exercises the aggregation loop without booting a VisionClient.
        from src.extraction_v2.models import ImageClassificationRecord

        def _fake_classify_one(
            self: ImageClassifyStage, image: ImageAsset, *_: Any, **__: Any
        ) -> ImageClassificationRecord:
            return ImageClassificationRecord(
                img_id=image.img_id,
                predicted_metrics=[],
                confidence=0.5,
                rejection_reason=None,
                reasoning=None,
                provider="mock",
                model="mock",
                prompt_version=1,
                cost_usd=0.0007,
                latency_ms=10,
            )

        monkeypatch.setattr(ImageClassifyStage, "_classify_one", _fake_classify_one)

        # _build_client is reached before _classify_one — avoid touching env.
        monkeypatch.setattr(
            "src.extraction_v2.stages.image_classify._build_client",
            lambda provider, model: object(),
        )

        images = [
            ImageAsset(
                img_id=f"i{i}",
                filename="img.png",
                file_path=png.name,
                width=800,
                height=600,
                classification=ImageClassification.CHART,
                relevance_score=0.9,
            )
            for i in range(3)
        ]
        ctx = PipelineContext(
            html_path=tmp_path / "test.html",
            filing_id=1,
            config=PipelineConfig(enable_metric_classify=True),
            images=images,
        )
        result = ImageClassifyStage().process(ctx)

        spend = result.metadata["vision_spend_usd_by_site"]
        assert spend == {"metric_classify": pytest.approx(0.0021)}


# ---------------------------------------------------------------------------
# PipelineResult rollup
# ---------------------------------------------------------------------------


class TestPipelineResultRollup:
    def _make_result(self, stage_results: list[StageResult]) -> PipelineResult:
        return PipelineResult(
            document=Document(),
            facts=[],
            tables=[],
            images=[],
            segments=[],
            stage_results=stage_results,
            total_duration_ms=1,
            success=True,
        )

    def test_rollup_aggregates_across_stages(self) -> None:
        ocr_meta = {
            "vision_spend_usd_by_site": {
                "table_ocr": 0.03,
                "chart_ocr_fast": 0.001,
                "chart_read_premium": 0.05,
                "full_page_ocr": 0.0,
                "prescan": 0.004,
            }
        }
        classify_meta = {"vision_spend_usd_by_site": {"metric_classify": 0.0021}}

        result = self._make_result(
            [
                StageResult(
                    stage=PipelineStage.OCR_CHART_EXTRACTION,
                    success=True,
                    duration_ms=1,
                    items_processed=0,
                    items_output=0,
                    metadata=ocr_meta,
                ),
                StageResult(
                    stage=PipelineStage.IMAGE_CLASSIFY,
                    success=True,
                    duration_ms=1,
                    items_processed=0,
                    items_output=0,
                    metadata=classify_meta,
                ),
            ]
        )

        spend = result.vision_spend_usd_by_site
        assert spend["table_ocr"] == pytest.approx(0.03)
        assert spend["chart_ocr_fast"] == pytest.approx(0.001)
        assert spend["chart_read_premium"] == pytest.approx(0.05)
        assert spend["prescan"] == pytest.approx(0.004)
        assert spend["full_page_ocr"] == 0.0
        assert spend["metric_classify"] == pytest.approx(0.0021)

        assert result.vision_spend_usd_total == pytest.approx(0.03 + 0.001 + 0.05 + 0.004 + 0.0021)

    def test_rollup_returns_zeros_when_no_stage_emits_metadata(self) -> None:
        result = self._make_result(
            [
                StageResult(
                    stage=PipelineStage.SECTION_CLASSIFICATION,
                    success=True,
                    duration_ms=1,
                    items_processed=0,
                    items_output=0,
                )
            ]
        )

        spend = result.vision_spend_usd_by_site
        for site in (
            "table_ocr",
            "chart_ocr_fast",
            "chart_read_premium",
            "full_page_ocr",
            "prescan",
            "metric_classify",
        ):
            assert spend[site] == 0.0
        assert result.vision_spend_usd_total == 0.0
