"""
Unit tests for ChartFactBridgeStage — presence-pivot contract.

After the chart-presence pivot (PR 1), ChartFactBridgeStage no longer emits
MetricFact rows. Instead it populates image.detected_metrics with
DetectedMetric records. All three historical chart shapes (annotations-only,
LTV/CAC, default-series) must produce zero facts and non-empty detected_metrics
when the classifier finds a match.
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
    DetectedMetric,
    ImageAsset,
    ImageClassification,
)
from src.extraction_v2.pipeline import PipelineConfig, PipelineContext
from src.extraction_v2.stages.chart_fact_bridge import ChartFactBridgeStage

_FILING_DATE = date(2020, 12, 31)


def _make_context(
    images: list[ImageAsset],
    filing_date: date = _FILING_DATE,
    config: PipelineConfig | None = None,
) -> PipelineContext:
    return PipelineContext(
        html_path=Path("/test/filing.html"),
        filing_id=1,
        config=config or PipelineConfig(),
        document_date=filing_date,
        images=images,
    )


def _make_ltv_image(confidence: float = 0.9) -> ImageAsset:
    """LTV/CAC chart — previously exercised the cm_ltv_to_cac_ratio branch."""
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
        img_id="img-ltv-1",
        classification=ImageClassification.CHART,
        chart_data=chart,
        processed=True,
        confidence=confidence,
        relevance_score=0.9,
    )


def _make_cohort_series_image(confidence: float = 0.9) -> ImageAsset:
    """Cohort revenue chart — previously exercised the default-series branch."""
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
        img_id="img-cohort-1",
        classification=ImageClassification.CHART,
        chart_data=chart,
        processed=True,
        confidence=confidence,
        relevance_score=0.9,
        nearby_text="GMV from Marketplace by consumer cohort",
    )


def _make_annotations_only_image(confidence: float = 0.9) -> ImageAsset:
    """Annotation-only chart — previously exercised the annotations-only branch."""
    chart = ChartData(
        chart_type=ChartType.BAR,
        title="Revenue by Cohort",
        x_axis_label="Year",
        y_axis_label="USDm",
        series=[],
        annotations=[
            ChartAnnotation(
                text="$2.8M 2014 new customer revenue",
                value=2.8,
                unit="USD",
            ),
        ],
    )
    return ImageAsset(
        img_id="img-ann-1",
        classification=ImageClassification.CHART,
        chart_data=chart,
        processed=True,
        confidence=confidence,
        relevance_score=0.9,
        nearby_text="new customer revenue by cohort",
    )


# ---------------------------------------------------------------------------
# Core contract: zero facts, populated detected_metrics
# ---------------------------------------------------------------------------


class TestPresencePivotContract:
    def test_emits_zero_facts_for_ltv_shape(self) -> None:
        image = _make_ltv_image()
        context = _make_context([image])
        ChartFactBridgeStage().process(context)
        assert context.facts == []

    def test_emits_zero_facts_for_default_series_shape(self) -> None:
        image = _make_cohort_series_image()
        context = _make_context([image])
        ChartFactBridgeStage().process(context)
        assert context.facts == []

    def test_emits_zero_facts_for_annotations_only_shape(self) -> None:
        image = _make_annotations_only_image()
        context = _make_context([image])
        ChartFactBridgeStage().process(context)
        assert context.facts == []

    def test_populates_detected_metrics_for_ltv_shape(self) -> None:
        image = _make_ltv_image()
        context = _make_context([image])
        ChartFactBridgeStage().process(context)
        assert len(image.detected_metrics) >= 1
        assert all(isinstance(d, DetectedMetric) for d in image.detected_metrics)

    def test_populates_detected_metrics_for_cohort_series_shape(self) -> None:
        image = _make_cohort_series_image()
        context = _make_context([image])
        ChartFactBridgeStage().process(context)
        assert len(image.detected_metrics) >= 1

    def test_detected_metric_has_valid_score(self) -> None:
        image = _make_ltv_image()
        context = _make_context([image])
        ChartFactBridgeStage().process(context)
        for dm in image.detected_metrics:
            assert 0.0 <= dm.score <= 1.0
            assert isinstance(dm.metric_id, str)
            assert len(dm.metric_id) > 0

    def test_detected_metrics_score_above_presence_min(self) -> None:
        """All detected_metrics entries must have score >= chart_presence_min_score."""
        config = PipelineConfig(chart_presence_min_score=0.5)
        image = _make_ltv_image()
        context = _make_context([image], config=config)
        ChartFactBridgeStage().process(context)
        for dm in image.detected_metrics:
            assert dm.score >= 0.5


# ---------------------------------------------------------------------------
# Stage metadata: new counter keys
# ---------------------------------------------------------------------------


class TestStageMetadata:
    def test_metadata_has_new_counter_keys(self) -> None:
        image = _make_ltv_image()
        context = _make_context([image])
        result = ChartFactBridgeStage().process(context)
        assert "images_scanned" in result.metadata
        assert "metrics_detected" in result.metadata
        assert "images_below_confidence" in result.metadata

    def test_images_scanned_counts_processed_chart_images(self) -> None:
        images = [_make_ltv_image(), _make_cohort_series_image()]
        context = _make_context(images)
        result = ChartFactBridgeStage().process(context)
        assert result.metadata["images_scanned"] == 2

    def test_images_below_confidence_counts_skipped(self) -> None:
        low_conf = _make_ltv_image(confidence=0.1)
        context = _make_context([low_conf])
        result = ChartFactBridgeStage().process(context)
        assert result.metadata["images_below_confidence"] == 1
        assert result.metadata["images_scanned"] == 0

    def test_metrics_detected_reflects_total_detected_metrics(self) -> None:
        image = _make_ltv_image()
        context = _make_context([image])
        result = ChartFactBridgeStage().process(context)
        total = sum(len(img.detected_metrics) for img in context.images)
        assert result.metadata["metrics_detected"] == total


# ---------------------------------------------------------------------------
# Guard 1: image confidence gate
# ---------------------------------------------------------------------------


class TestGuard1ImageConfidence:
    def test_skips_image_below_confidence_threshold(self) -> None:
        image = _make_ltv_image(confidence=0.3)
        context = _make_context([image])
        result = ChartFactBridgeStage().process(context)
        assert result.success
        assert context.facts == []
        assert result.metadata["images_below_confidence"] == 1
        assert image.detected_metrics == []

    def test_image_without_confidence_is_not_skipped(self) -> None:
        image = _make_ltv_image()
        image.confidence = None  # type: ignore[assignment]
        context = _make_context([image])
        result = ChartFactBridgeStage().process(context)
        assert result.metadata["images_below_confidence"] == 0
        assert result.metadata["images_scanned"] == 1

    def test_config_override_zero_threshold_passes_all(self) -> None:
        config = PipelineConfig(chart_image_min_confidence=0.0)
        image = _make_ltv_image(confidence=0.1)
        context = _make_context([image], config=config)
        result = ChartFactBridgeStage().process(context)
        assert result.metadata["images_below_confidence"] == 0
        assert result.metadata["images_scanned"] == 1


# ---------------------------------------------------------------------------
# Presence min-score gate
# ---------------------------------------------------------------------------


class TestPresenceMinScore:
    def test_candidates_below_min_score_excluded(self) -> None:
        """With chart_presence_min_score=1.0, no candidate passes."""
        config = PipelineConfig(chart_presence_min_score=1.0)
        image = _make_ltv_image()
        context = _make_context([image], config=config)
        ChartFactBridgeStage().process(context)
        assert image.detected_metrics == []
        assert context.facts == []

    def test_candidates_at_min_score_included(self) -> None:
        """With chart_presence_min_score=0.0, all gated candidates are included."""
        config = PipelineConfig(chart_presence_min_score=0.0)
        image = _make_ltv_image()
        context = _make_context([image], config=config)
        ChartFactBridgeStage().process(context)
        assert len(image.detected_metrics) >= 1


# ---------------------------------------------------------------------------
# Bridge disabled
# ---------------------------------------------------------------------------


class TestBridgeDisabled:
    def test_bridge_noop_when_disabled(self) -> None:
        config = PipelineConfig(enable_chart_fact_bridge=False)
        image = _make_ltv_image()
        context = _make_context([image], config=config)
        result = ChartFactBridgeStage().process(context)
        assert result.items_processed == 0
        assert result.items_output == 0
        assert context.facts == []
        assert image.detected_metrics == []


# ---------------------------------------------------------------------------
# Image without chart_data is skipped
# ---------------------------------------------------------------------------


class TestNonChartImages:
    def test_image_without_chart_data_is_skipped(self) -> None:
        image = ImageAsset(img_id="img-no-chart")
        image.chart_data = None
        context = _make_context([image])
        result = ChartFactBridgeStage().process(context)
        assert result.metadata["images_scanned"] == 0
        assert image.detected_metrics == []
