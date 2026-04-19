"""
Invariant tests for `ChartFactBridgeStage`.

The review UI's "Chart Evidence" block depends on every chart-sourced fact
carrying a non-null `source_locator.img_id` — the CI integrity gate treats a
null img_id on a `source_type='chart'` fact as a blocking violation (see
`scripts/check_image_referential_integrity.py`). These tests lock that
invariant in at unit-test granularity so regressions surface locally before
they reach the DB.
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
    """LTV/CAC ratio chart that exercises the cm_ltv_to_cac_ratio branch."""
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
    """Cohort revenue chart that exercises the default series branch."""
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
    """Annotation-only chart that exercises the annotations-only branch."""
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


def _assert_img_id_on_every_fact(facts: list, expected_img_id: str) -> None:
    assert facts, "expected at least one chart fact to be emitted"
    for fact in facts:
        assert fact.source_locator is not None, f"fact {fact.fact_id} has no source_locator"
        assert fact.source_locator.img_id == expected_img_id, (
            f"fact {fact.fact_id} img_id={fact.source_locator.img_id!r} "
            f"expected {expected_img_id!r}"
        )


class TestChartFactBridgeImgIdInvariant:
    def test_series_branch_always_sets_img_id(self) -> None:
        image = _cohort_series_image("img-cohort-A")
        context = _context([image])

        ChartFactBridgeStage().process(context)

        _assert_img_id_on_every_fact(context.facts, "img-cohort-A")

    def test_ltv_branch_always_sets_img_id(self) -> None:
        image = _ltv_image("img-ltv-A")
        context = _context([image])

        ChartFactBridgeStage().process(context)

        _assert_img_id_on_every_fact(context.facts, "img-ltv-A")

    def test_annotation_only_branch_always_sets_img_id(self) -> None:
        image = _annotation_only_image("img-ann-A")
        context = _context([image])

        ChartFactBridgeStage().process(context)

        # Annotation-only branch may be filtered by classifier; the invariant
        # only applies to facts that were emitted.
        for fact in context.facts:
            assert fact.source_locator is not None
            assert fact.source_locator.img_id == "img-ann-A"
