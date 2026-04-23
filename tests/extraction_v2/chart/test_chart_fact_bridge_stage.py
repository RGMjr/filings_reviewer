"""Presence-pivot contract smoke tests for ChartFactBridgeStage.

The detailed behavioural assertions live in
``tests/unit/extraction_v2/test_chart_fact_bridge_stage.py``. This file keeps
a narrower set of scope-guard cases to prevent silent regressions on the
"charts no longer emit facts" invariant from the `chart/` test package.
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
)
from src.extraction_v2.pipeline import PipelineConfig, PipelineContext
from src.extraction_v2.stages.chart_fact_bridge import ChartFactBridgeStage


def _make_context(images: list[ImageAsset]) -> PipelineContext:
    return PipelineContext(
        html_path=Path("/dev/null"),
        filing_id=42,
        config=PipelineConfig(),
        document_date=date(2021, 10, 8),
        images=images,
    )


def _cohort_series_image() -> ImageAsset:
    chart = ChartData(
        chart_type=ChartType.STACKED_BAR,
        title="Cumulative Net Deposits by Cohort",
        y_axis_label="Cumulative Net Deposits ($ Billions)",
        x_axis_label="Year",
        series=[
            ChartSeries(
                name="2018",
                points=[
                    DataPoint(x="2019", y=4.5, label="4.5"),
                    DataPoint(x="2020", y=8.3, label="8.3"),
                ],
            ),
            ChartSeries(
                name="2019",
                points=[DataPoint(x="2020", y=9.0, label="9.0")],
            ),
        ],
    )
    img = ImageAsset(img_id="img-cohort", nearby_text="")
    img.chart_data = chart
    img.confidence = 0.8
    return img


def _ltv_cac_image() -> ImageAsset:
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
    img = ImageAsset(img_id="img-ltv", nearby_text="")
    img.chart_data = chart
    img.confidence = 0.9
    return img


def _annotation_only_image() -> ImageAsset:
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
    img = ImageAsset(img_id="img-ann", nearby_text="new customer revenue by cohort")
    img.chart_data = chart
    img.confidence = 0.9
    return img


def test_cohort_series_shape_emits_zero_facts() -> None:
    ctx = _make_context([_cohort_series_image()])
    ChartFactBridgeStage().process(ctx)
    assert ctx.facts == []


def test_ltv_cac_shape_emits_zero_facts() -> None:
    ctx = _make_context([_ltv_cac_image()])
    ChartFactBridgeStage().process(ctx)
    assert ctx.facts == []


def test_annotation_only_shape_emits_zero_facts() -> None:
    ctx = _make_context([_annotation_only_image()])
    ChartFactBridgeStage().process(ctx)
    assert ctx.facts == []


def test_cohort_series_shape_populates_detected_metrics() -> None:
    image = _cohort_series_image()
    ctx = _make_context([image])
    ChartFactBridgeStage().process(ctx)
    assert len(image.detected_metrics) >= 1
    for detected in image.detected_metrics:
        assert isinstance(detected.metric_id, str) and detected.metric_id
        assert 0.0 <= detected.score <= 1.0


def test_ltv_cac_shape_populates_detected_metrics() -> None:
    image = _ltv_cac_image()
    ctx = _make_context([image])
    ChartFactBridgeStage().process(ctx)
    assert len(image.detected_metrics) >= 1
