"""
Unit tests for ChartFactBridgeStage hallucination guards (Cluster A).

Tests Guard 1–5 and config override behaviour.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

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


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

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


def _make_ltv_image(
    confidence: float = 0.9,
    series_data: list[tuple[str, list[tuple[str, float, str | None]]]] | None = None,
) -> ImageAsset:
    """Build a minimal LTV/CAC chart asset that the classifier will route to cm_ltv_to_cac_ratio."""
    if series_data is None:
        series_data = [
            ("Enterprise", [("Cohort 2018", 3.5, "3.5x"), ("Cohort 2019", 4.0, "4.0x")]),
        ]
    series = []
    for name, pts in series_data:
        points = [DataPoint(x=x, y=y, label=label) for x, y, label in pts]
        series.append(ChartSeries(name=name, points=points))

    chart = ChartData(
        chart_type=ChartType.BAR,
        title="LTV to CAC Ratio by Cohort",
        x_axis_label="Cohort",
        y_axis_label="LTV/CAC",
        series=series,
    )
    return ImageAsset(
        img_id="img-ltv-1",
        classification=ImageClassification.CHART,
        chart_data=chart,
        processed=True,
        confidence=confidence,
        relevance_score=0.9,
    )


def _make_cohort_image(
    confidence: float = 0.9,
    series_data: list[tuple[str, list[tuple[str, float, str | None]]]] | None = None,
) -> ImageAsset:
    """Build a cohort revenue chart asset routed to a non-LTV metric."""
    if series_data is None:
        series_data = [
            ("2017 Cohort", [("2017", 100.0, "100"), ("2018", 120.0, "120")]),
        ]
    series = []
    for name, pts in series_data:
        points = [DataPoint(x=x, y=y, label=label) for x, y, label in pts]
        series.append(ChartSeries(name=name, points=points))

    chart = ChartData(
        chart_type=ChartType.BAR,
        title="GMV by Consumer Cohort",
        x_axis_label="Year",
        y_axis_label="GMV (USDm)",
        series=series,
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


# ---------------------------------------------------------------------------
# Guard 1: image confidence gate
# ---------------------------------------------------------------------------


class TestGuard1ImageConfidence:
    def test_guard_skips_chart_when_image_confidence_below_threshold(self) -> None:
        """Images with confidence below chart_image_min_confidence (default 0.6) are skipped."""
        image = _make_ltv_image(confidence=0.3)
        context = _make_context([image])
        stage = ChartFactBridgeStage()

        result = stage.process(context)

        assert result.success
        assert len(context.facts) == 0
        assert result.metadata["guard_skipped_low_image_confidence"] == 1

    def test_image_without_confidence_is_not_skipped(self) -> None:
        """Images where confidence is None pass the gate regardless of threshold."""
        image = _make_cohort_image(confidence=0.9)
        image.confidence = None  # type: ignore[assignment]
        context = _make_context([image])
        stage = ChartFactBridgeStage()

        result = stage.process(context)

        assert result.success
        assert result.metadata["guard_skipped_low_image_confidence"] == 0


# ---------------------------------------------------------------------------
# Guard 2: label-required gate
# ---------------------------------------------------------------------------


class TestGuard2LabelRequired:
    def test_guard_skips_point_when_label_missing(self) -> None:
        """Points with label=None are skipped; labeled points contribute facts."""
        image = _make_ltv_image(
            series_data=[
                (
                    "Enterprise",
                    [
                        ("Cohort 2018", 3.5, "3.5x"),   # labeled — should emit
                        ("Cohort 2019", 4.0, None),     # no label — should skip
                    ],
                )
            ]
        )
        context = _make_context([image])
        stage = ChartFactBridgeStage()

        result = stage.process(context)

        assert result.success
        # Only the labeled point should produce a fact
        assert len(context.facts) == 1
        assert result.metadata["guard_skipped_missing_label"] == 1


# ---------------------------------------------------------------------------
# Guard 3: axis-range sanity
# ---------------------------------------------------------------------------


class TestGuard3AxisRange:
    def test_guard_skips_point_out_of_axis_range(self) -> None:
        """An unlabeled point whose abs(y) > 10× the labeled-max is skipped before label gate."""
        # labeled_max = max(abs(3.5), abs(4.0)) = 4.0
        # 4.0 * 10 = 40.0 — unlabeled point with y=1000 should be filtered by axis-range guard
        # (axis-range guard runs before the label-required guard, so unlabeled outliers are caught)
        image = _make_ltv_image(
            series_data=[
                (
                    "Enterprise",
                    [
                        ("Cohort 2018", 3.5, "3.5x"),   # labeled, in-range → emits fact
                        ("Cohort 2019", 4.0, "4.0x"),   # labeled, in-range → emits fact
                        ("Noise", 1000.0, None),         # unlabeled, out-of-range → skipped by G3
                    ],
                )
            ]
        )
        context = _make_context([image])
        stage = ChartFactBridgeStage()

        result = stage.process(context)

        assert result.success
        assert len(context.facts) == 2  # Only the two labeled in-range points
        assert result.metadata["guard_skipped_out_of_range"] == 1
        # Guard 2 counter should be 0 because axis-range guard fired first
        assert result.metadata["guard_skipped_missing_label"] == 0

    def test_guard_skips_nothing_when_labeled_max_is_zero(self) -> None:
        """When all labeled y-values are 0, the axis-range guard is skipped (no division risk)."""
        image = _make_ltv_image(
            series_data=[
                (
                    "Enterprise",
                    [
                        ("Cohort 2018", 0.0, "0"),
                        ("Cohort 2019", 0.0, "0"),
                    ],
                )
            ]
        )
        context = _make_context([image])
        stage = ChartFactBridgeStage()

        result = stage.process(context)

        assert result.metadata["guard_skipped_out_of_range"] == 0


# ---------------------------------------------------------------------------
# Guard 4: cohort-year sanity
# ---------------------------------------------------------------------------


class TestGuard4CohortYear:
    def test_guard_skips_cohort_year_beyond_filing_year_plus_one(self) -> None:
        """Cohort points whose resolved period_end.year > filing_date.year + 1 are rejected."""
        # filing_date = 2020-12-31, so max allowed year = 2021
        # series name "2023 Cohort" → cohort_year=2023 → period_end.year=2023 > 2021 → skip
        image = _make_cohort_image(
            series_data=[
                (
                    "2023 Cohort",
                    [("2023", 150.0, "150")],
                ),
            ]
        )
        context = _make_context([image], filing_date=date(2020, 12, 31))
        stage = ChartFactBridgeStage()

        result = stage.process(context)

        assert result.success
        assert result.metadata["guard_skipped_future_cohort"] >= 1

    def test_cohort_within_allowed_window_passes(self) -> None:
        """A cohort year at filing_date.year + 1 (boundary) is allowed through."""
        # filing_date = 2020, so year 2021 should NOT be blocked
        image = _make_cohort_image(
            series_data=[
                (
                    "2017 Cohort",
                    [("2017", 100.0, "100"), ("2018", 120.0, "120")],
                ),
            ]
        )
        context = _make_context([image], filing_date=date(2020, 12, 31))
        stage = ChartFactBridgeStage()

        result = stage.process(context)

        assert result.metadata["guard_skipped_future_cohort"] == 0


# ---------------------------------------------------------------------------
# Guard 5: fact review threshold
# ---------------------------------------------------------------------------


class TestGuard5FactReviewThreshold:
    def test_ltv_cac_branch_respects_fact_review_threshold(self) -> None:
        """LTV/CAC facts with confidence < 0.80 get requires_review=True."""
        # The LTV/CAC branch sets confidence=0.80; default threshold is also 0.80.
        # Override threshold to 0.85 to force requires_review=True on those facts.
        config = PipelineConfig(chart_fact_review_threshold=0.85)
        image = _make_ltv_image(
            series_data=[
                ("Enterprise", [("Cohort 2018", 3.5, "3.5x")]),
            ]
        )
        context = _make_context([image], config=config)
        stage = ChartFactBridgeStage()

        result = stage.process(context)

        assert result.success
        assert len(context.facts) == 1
        assert context.facts[0].requires_review is True

    def test_high_confidence_fact_does_not_force_review(self) -> None:
        """A fact with confidence >= threshold retains the branch-set requires_review value."""
        # LTV/CAC branch sets confidence=0.80, requires_review=False; threshold=0.70
        config = PipelineConfig(chart_fact_review_threshold=0.70)
        image = _make_ltv_image(
            series_data=[
                ("Enterprise", [("Cohort 2018", 3.5, "3.5x")]),
            ]
        )
        context = _make_context([image], config=config)
        stage = ChartFactBridgeStage()

        result = stage.process(context)

        assert result.success
        assert len(context.facts) == 1
        assert context.facts[0].requires_review is False


# ---------------------------------------------------------------------------
# Config override test
# ---------------------------------------------------------------------------


class TestConfigOverrides:
    def test_guards_respect_config_overrides(self) -> None:
        """Setting chart_image_min_confidence=0.0 passes images that would normally be skipped."""
        config = PipelineConfig(chart_image_min_confidence=0.0)
        image = _make_ltv_image(confidence=0.1)  # Would be skipped at default 0.6
        context = _make_context([image], config=config)
        stage = ChartFactBridgeStage()

        result = stage.process(context)

        assert result.success
        assert result.metadata["guard_skipped_low_image_confidence"] == 0
        # Should have emitted facts (image passes through)
        assert len(context.facts) > 0
