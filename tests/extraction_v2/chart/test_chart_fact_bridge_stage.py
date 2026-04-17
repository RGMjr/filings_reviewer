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
    SourceType,
)
from src.extraction_v2.pipeline import PipelineConfig, PipelineContext
from src.extraction_v2.stages.chart_fact_bridge import ChartFactBridgeStage


def _make_context(
    images: list[ImageAsset],
    enable_bridge: bool = True,
    min_score: float = 0.6,
    document_date: date | None = None,
) -> PipelineContext:
    config = PipelineConfig(
        enable_chart_fact_bridge=enable_bridge,
        chart_metric_classification_min_score=min_score,
    )
    ctx = PipelineContext(
        html_path=Path("/dev/null"),
        filing_id=42,
        config=config,
        document_date=document_date or date(2021, 10, 8),
    )
    ctx.images = images
    return ctx


def _cohort_stacked_bar_image() -> ImageAsset:
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
                points=[
                    DataPoint(x="2020", y=9.0, label="9.0"),
                ],
            ),
        ],
    )
    img = ImageAsset(img_id="img-001", nearby_text="")
    img.chart_data = chart
    return img


def test_emits_facts_for_classified_chart() -> None:
    image = _cohort_stacked_bar_image()
    ctx = _make_context([image])
    ChartFactBridgeStage().process(ctx)
    assert len(ctx.facts) >= 1


def test_skips_chart_below_classification_threshold() -> None:
    chart = ChartData(
        chart_type=ChartType.BAR,
        title="Annual Revenue",
        y_axis_label="USD millions",
        x_axis_label="Year",
        series=[ChartSeries(name="Revenue", points=[DataPoint(x="2020", y=100.0)])],
    )
    img = ImageAsset(img_id="img-low", nearby_text="")
    img.chart_data = chart
    ctx = _make_context([img])
    ChartFactBridgeStage().process(ctx)
    assert ctx.facts == []


def test_sets_source_type_chart_and_img_id_locator() -> None:
    image = _cohort_stacked_bar_image()
    ctx = _make_context([image])
    ChartFactBridgeStage().process(ctx)
    assert len(ctx.facts) >= 1
    fact = ctx.facts[0]
    assert fact.source_type == SourceType.CHART
    assert fact.source_locator.img_id == "img-001"


def test_marks_requires_review_for_annotations_only_facts() -> None:
    ann = ChartAnnotation(
        text="2019 cohort data",
        value=44.4,
        unit="billions",
        category="2019 Cohort",
        period="2019",
    )
    chart = ChartData(
        chart_type=ChartType.STACKED_BAR,
        title="Cumulative Net Deposits by Cohort",
        y_axis_label="Cumulative Net Deposits ($ Billions)",
        x_axis_label="Year",
        series=[],
        annotations=[ann],
    )
    img = ImageAsset(img_id="img-ann", nearby_text="")
    img.chart_data = chart
    ctx = _make_context([img])
    ChartFactBridgeStage().process(ctx)
    assert len(ctx.facts) >= 1
    fact = ctx.facts[0]
    assert fact.requires_review is True
    assert fact.confidence == 0.55


def test_populates_cohort_def_and_period_end() -> None:
    image = _cohort_stacked_bar_image()
    ctx = _make_context([image])
    ChartFactBridgeStage().process(ctx)
    assert len(ctx.facts) >= 1
    fact = ctx.facts[0]
    assert fact.cohort_def is not None
    assert fact.period_end is not None


def test_bridge_noop_when_enable_chart_fact_bridge_false() -> None:
    image = _cohort_stacked_bar_image()
    ctx = _make_context([image], enable_bridge=False)
    result = ChartFactBridgeStage().process(ctx)
    assert result.items_output == 0
    assert ctx.facts == []
