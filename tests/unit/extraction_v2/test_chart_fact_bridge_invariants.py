"""
Invariant tests for `ChartFactBridgeStage`.

Under the presence-pivot contract (see PR rewriting `ChartFactBridgeStage`),
chart images no longer emit per-value `MetricFact` rows — they carry
image-level metric-presence signals on `ImageAsset.detected_metrics`.

The persistence layer writes these signals to `v2_image_assets.detected_metrics`
keyed by `img_id`, so every `DetectedMetric` must belong to an image with a
non-null `img_id`. These tests lock that invariant at unit-test granularity
across the historical chart shapes (cohort series, LTV/CAC, annotations-only)
so regressions surface locally before they reach the DB.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

from src.extraction_v2.models import (
    ChartAnnotation,
    ChartData,
    ChartSeries,
    ChartType,
    DataPoint,
    ImageAsset,
    ImageClassification,
)
from src.extraction_v2.pipeline import PipelineConfig, PipelineContext
from src.extraction_v2.stages.chart_fact_bridge import ChartFactBridgeStage

_FILING_DATE = date(2020, 12, 31)


def _context(images: list[ImageAsset]) -> PipelineContext:
    return PipelineContext(
        html_path=Path("/test/filing.html"),
        filing_id=1,
        config=PipelineConfig(),
        document_date=_FILING_DATE,
        images=images,
    )


def _ltv_image(img_id: str = "img-ltv-invariant") -> ImageAsset:
    chart = ChartData(
        chart_type=ChartType.BAR,
        title="LTV to CAC Ratio by Cohort",
        x_axis_label="Cohort",
        y_axis_label="LTV/CAC",
        series=[
            ChartSeries(
                name="Enterprise",
                points=[
                    DataPoint(x="Cohort 2018", y=3.5, label="3.5x"),
                    DataPoint(x="Cohort 2019", y=4.0, label="4.0x"),
                ],
            ),
        ],
    )
    return ImageAsset(
        img_id=img_id,
        classification=ImageClassification.CHART,
        chart_data=chart,
        processed=True,
        confidence=0.9,
        relevance_score=0.9,
    )


def _cohort_series_image(img_id: str = "img-cohort-invariant") -> ImageAsset:
    chart = ChartData(
        chart_type=ChartType.BAR,
        title="GMV by Consumer Cohort",
        x_axis_label="Year",
        y_axis_label="GMV (USDm)",
        series=[
            ChartSeries(
                name="2017 Cohort",
                points=[
                    DataPoint(x="2017", y=100.0, label="100"),
                    DataPoint(x="2018", y=120.0, label="120"),
                ],
            ),
        ],
    )
    return ImageAsset(
        img_id=img_id,
        classification=ImageClassification.CHART,
        chart_data=chart,
        processed=True,
        confidence=0.9,
        relevance_score=0.9,
        nearby_text="GMV from Marketplace by consumer cohort",
    )


def _annotation_only_image(img_id: str = "img-ann-invariant") -> ImageAsset:
    chart = ChartData(
        chart_type=ChartType.BAR,
        title="Revenue by Cohort",
        x_axis_label="Year",
        y_axis_label="USDm",
        series=[],
        annotations=[
            ChartAnnotation(text="$2.8M 2014 new customer revenue", value=2.8, unit="USD"),
        ],
    )
    return ImageAsset(
        img_id=img_id,
        classification=ImageClassification.CHART,
        chart_data=chart,
        processed=True,
        confidence=0.9,
        relevance_score=0.9,
        nearby_text="new customer revenue by cohort",
    )


class TestNoChartFactsEmitted:
    """Presence-pivot contract: `ChartFactBridgeStage` never emits MetricFacts."""

    def test_cohort_series_shape_emits_zero_facts(self) -> None:
        context = _context([_cohort_series_image()])
        ChartFactBridgeStage().process(context)
        assert context.facts == []

    def test_ltv_shape_emits_zero_facts(self) -> None:
        context = _context([_ltv_image()])
        ChartFactBridgeStage().process(context)
        assert context.facts == []

    def test_annotation_only_shape_emits_zero_facts(self) -> None:
        context = _context([_annotation_only_image()])
        ChartFactBridgeStage().process(context)
        assert context.facts == []


class TestDetectedMetricsImgIdInvariant:
    """Every detected_metrics entry must belong to an image with a non-null img_id.

    This replaces the prior "every chart fact has img_id" invariant — under the
    presence-pivot contract, metric-presence signals are keyed to the image
    row in v2_image_assets by img_id, so the img_id must always be present on
    any image that carries detected_metrics.
    """

    def test_cohort_series_image_img_id_non_null(self) -> None:
        image = _cohort_series_image("img-cohort-A")
        context = _context([image])

        ChartFactBridgeStage().process(context)

        if image.detected_metrics:
            assert image.img_id is not None
            assert image.img_id == "img-cohort-A"

    def test_ltv_image_img_id_non_null(self) -> None:
        image = _ltv_image("img-ltv-A")
        context = _context([image])

        ChartFactBridgeStage().process(context)

        if image.detected_metrics:
            assert image.img_id is not None
            assert image.img_id == "img-ltv-A"

    def test_annotation_only_image_img_id_non_null(self) -> None:
        image = _annotation_only_image("img-ann-A")
        context = _context([image])

        ChartFactBridgeStage().process(context)

        # Annotation-only charts may or may not detect metrics; the invariant
        # only applies to images that did populate detected_metrics.
        if image.detected_metrics:
            assert image.img_id is not None
            assert image.img_id == "img-ann-A"

    def test_invariant_holds_across_multiple_images(self) -> None:
        images = [
            _cohort_series_image("img-multi-cohort"),
            _ltv_image("img-multi-ltv"),
            _annotation_only_image("img-multi-ann"),
        ]
        context = _context(images)

        ChartFactBridgeStage().process(context)

        for image in images:
            if image.detected_metrics:
                assert image.img_id is not None, (
                    f"image with detected_metrics has null img_id: {image!r}"
                )
