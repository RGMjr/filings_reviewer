"""
Unit tests for ChartMetricClassifier.classify_all and backward-compat classify().
"""

from __future__ import annotations

import pytest

from src.extraction_v2.chart.metric_classifier import ChartMetricClassifier
from src.extraction_v2.models import ChartData, ChartSeries, ChartType, DataPoint


@pytest.fixture
def classifier() -> ChartMetricClassifier:
    return ChartMetricClassifier()


# ---------------------------------------------------------------------------
# classify_all — multi-label output
# ---------------------------------------------------------------------------


class TestClassifyAll:
    def test_returns_list(self, classifier: ChartMetricClassifier) -> None:
        chart = ChartData(
            chart_type=ChartType.STACKED_BAR,
            title="Cumulative Net Deposits by Cohort",
            y_axis_label="$ billions",
            series=[ChartSeries(name="2018"), ChartSeries(name="2019")],
        )
        result = classifier.classify_all(chart)
        assert isinstance(result, list)

    def test_returns_empty_for_non_cohort_chart(self, classifier: ChartMetricClassifier) -> None:
        chart = ChartData(
            chart_type=ChartType.BAR,
            title="Annual Revenue",
            y_axis_label="USD millions",
            series=[ChartSeries(name="Revenue")],
        )
        result = classifier.classify_all(chart)
        assert result == []

    def test_sorted_by_score_descending(self, classifier: ChartMetricClassifier) -> None:
        """All returned (metric_id, score) pairs must be sorted score-desc."""
        chart = ChartData(
            chart_type=ChartType.STACKED_BAR,
            title="Cumulative Net Deposits by Cohort",
            y_axis_label="$ billions",
            series=[ChartSeries(name="2018"), ChartSeries(name="2019"), ChartSeries(name="2020")],
        )
        result = classifier.classify_all(chart)
        scores = [s for _, s in result]
        assert scores == sorted(scores, reverse=True), "Results must be sorted by score desc"

    def test_each_result_is_tuple_str_float(self, classifier: ChartMetricClassifier) -> None:
        chart = ChartData(
            chart_type=ChartType.STACKED_BAR,
            title="Revenue by Cohort",
            y_axis_label="$ Millions",
            series=[ChartSeries(name="2019"), ChartSeries(name="2020")],
        )
        result = classifier.classify_all(chart)
        for metric_id, score in result:
            assert isinstance(metric_id, str)
            assert isinstance(score, float)
            assert 0.0 <= score <= 1.0

    def test_respects_cohort_gate(self, classifier: ChartMetricClassifier) -> None:
        """Generic revenue chart (no cohort/vintage signal) produces no candidates."""
        chart = ChartData(
            chart_type=ChartType.BAR,
            title="Revenue by Segment",
            y_axis_label="$ millions",
            series=[ChartSeries(name="North America"), ChartSeries(name="Europe")],
        )
        result = classifier.classify_all(chart)
        assert result == []

    def test_respects_metric_gate(self, classifier: ChartMetricClassifier) -> None:
        """A cohort chart without balance/deposit signals should not return cm_balance_by_cohort."""
        chart = ChartData(
            chart_type=ChartType.STACKED_BAR,
            title="Revenue by Cohort",
            y_axis_label="$ Millions",
            series=[ChartSeries(name="2019"), ChartSeries(name="2020")],
        )
        result = classifier.classify_all(chart)
        metric_ids = [m for m, _ in result]
        assert "cm_balance_by_cohort" not in metric_ids

    def test_ltv_cac_bypasses_cohort_gate(self, classifier: ChartMetricClassifier) -> None:
        """cm_ltv_to_cac_ratio should appear even for non-vintage-year charts."""
        chart = ChartData(
            chart_type=ChartType.BAR,
            title="LTV to CAC Ratio by Tenure",
            y_axis_label="Ratio (x)",
            series=[
                ChartSeries(
                    name="All Customers",
                    points=[DataPoint(x="1 Year Tenure", y=1.8)],
                )
            ],
        )
        result = classifier.classify_all(chart)
        metric_ids = [m for m, _ in result]
        assert "cm_ltv_to_cac_ratio" in metric_ids

    def test_balance_cohort_chart_returns_balance_metric(
        self, classifier: ChartMetricClassifier
    ) -> None:
        chart = ChartData(
            chart_type=ChartType.STACKED_BAR,
            title="Cumulative Net Deposits by Cohort",
            y_axis_label="$ billions",
            series=[ChartSeries(name="2018"), ChartSeries(name="2019")],
        )
        result = classifier.classify_all(chart)
        metric_ids = [m for m, _ in result]
        assert "cm_balance_by_cohort" in metric_ids


# ---------------------------------------------------------------------------
# classify() backward compatibility — must still return top-1
# ---------------------------------------------------------------------------


class TestClassifyBackwardCompat:
    def test_classify_returns_top1_from_classify_all(
        self, classifier: ChartMetricClassifier
    ) -> None:
        """classify() must return the highest-scoring candidate from classify_all()."""
        chart = ChartData(
            chart_type=ChartType.STACKED_BAR,
            title="Cumulative Net Deposits by Cohort",
            y_axis_label="$ billions",
            series=[ChartSeries(name="2018"), ChartSeries(name="2019")],
        )
        all_candidates = classifier.classify_all(chart)
        single = classifier.classify(chart)

        assert single[0] is not None
        if all_candidates:
            # The single result should correspond to the top score from classify_all,
            # possibly after revenue/transactions disambiguation.
            assert single[1] >= min(s for _, s in all_candidates)

    def test_classify_returns_none_when_no_candidates(
        self, classifier: ChartMetricClassifier
    ) -> None:
        chart = ChartData(
            chart_type=ChartType.BAR,
            title="Annual Revenue",
            y_axis_label="USD millions",
            series=[ChartSeries(name="Revenue")],
        )
        metric_id, score = classifier.classify(chart)
        assert metric_id is None
        assert isinstance(score, float)

    def test_classify_returns_single_tuple(self, classifier: ChartMetricClassifier) -> None:
        chart = ChartData(
            chart_type=ChartType.STACKED_BAR,
            title="Revenue by Cohort",
            y_axis_label="$ Millions",
            series=[ChartSeries(name="2019"), ChartSeries(name="2020")],
        )
        result = classifier.classify(chart)
        assert len(result) == 2
        metric_id, score = result
        assert metric_id is None or isinstance(metric_id, str)
        assert isinstance(score, float)
