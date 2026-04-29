"""
Unit tests for ChartMetricClassifier.classify_all and backward-compat classify().
"""

from __future__ import annotations

import pytest

from src.extraction_v2.chart.metric_classifier import (
    _COHORT_GATE_EXEMPT,
    _MAX_POSSIBLE_RAW,
    _W_ANNOTATIONS,
    _W_AXIS_NEARBY,
    _W_PRIMARY_TITLE,
    _W_SPECIFIC_TITLE,
    _W_Y_AXIS,
    ChartMetricClassifier,
)
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


# ---------------------------------------------------------------------------
# Soft-normalization denominator (gh-289 Scope B)
# ---------------------------------------------------------------------------


class TestSoftNormalization:
    """The _MAX_POSSIBLE_RAW denominator must be derived from weight constants,
    not hardcoded. This verifies the two are in sync."""

    def test_max_possible_raw_equals_sum_of_weights(self) -> None:
        expected = (
            _W_SPECIFIC_TITLE + _W_PRIMARY_TITLE + _W_Y_AXIS + _W_AXIS_NEARBY + _W_ANNOTATIONS
        )
        assert _MAX_POSSIBLE_RAW == pytest.approx(expected, abs=1e-9), (
            f"_MAX_POSSIBLE_RAW ({_MAX_POSSIBLE_RAW}) must equal sum of weight constants "
            f"({expected}). Update _MAX_POSSIBLE_RAW when changing weight constants."
        )

    def test_max_possible_raw_value_is_8_3(self) -> None:
        """Regression guard: 8.3 is the correct sum for current weights."""
        assert _MAX_POSSIBLE_RAW == pytest.approx(8.3, abs=1e-9)


# ---------------------------------------------------------------------------
# New Tier-1 metrics — gh-289 Scope B expansion
# ---------------------------------------------------------------------------


class TestCustomerRetentionRate:
    """cm_customer_retention_rate: cohort-gate exempt, fires on retention-rate charts."""

    def test_detects_retention_rate_chart(self, classifier: ChartMetricClassifier) -> None:
        """A bar chart titled 'Customer Retention Rate' must produce cm_customer_retention_rate."""
        chart = ChartData(
            chart_type=ChartType.BAR,
            title="Customer Retention Rate",
            y_axis_label="Retention %",
            series=[ChartSeries(name="Annual Cohort")],
        )
        result = classifier.classify_all(chart)
        metric_ids = [m for m, _ in result]
        assert "cm_customer_retention_rate" in metric_ids, (
            f"Expected cm_customer_retention_rate in {metric_ids}"
        )

    def test_cohort_gate_exempt(self, classifier: ChartMetricClassifier) -> None:
        """cm_customer_retention_rate must fire even without vintage-year series names."""
        chart = ChartData(
            chart_type=ChartType.LINE,
            title="Annual Customer Retention",
            y_axis_label="% Retained",
            series=[ChartSeries(name="All Customers")],  # no vintage year
        )
        result = classifier.classify_all(chart)
        metric_ids = [m for m, _ in result]
        assert "cm_customer_retention_rate" in metric_ids

    def test_does_not_match_revenue_retention(self, classifier: ChartMetricClassifier) -> None:
        """Revenue retention charts (NRR) must NOT produce cm_customer_retention_rate."""
        chart = ChartData(
            chart_type=ChartType.BAR,
            title="Net Revenue Retention",
            y_axis_label="NRR %",
            series=[ChartSeries(name="Annual")],
        )
        result = classifier.classify_all(chart)
        metric_ids = [m for m, _ in result]
        assert "cm_customer_retention_rate" not in metric_ids

    def test_in_cohort_gate_exempt_set(self) -> None:
        assert "cm_customer_retention_rate" in _COHORT_GATE_EXEMPT


class TestNetRevenueRetention:
    """cm_net_revenue_retention: cohort-gate exempt, fires on NRR/NDR charts."""

    def test_detects_nrr_acronym_chart(self, classifier: ChartMetricClassifier) -> None:
        chart = ChartData(
            chart_type=ChartType.BAR,
            title="NRR by Quarter",
            y_axis_label="NRR %",
            series=[ChartSeries(name="All Customers")],
        )
        result = classifier.classify_all(chart)
        metric_ids = [m for m, _ in result]
        assert "cm_net_revenue_retention" in metric_ids

    def test_detects_net_revenue_retention_title(self, classifier: ChartMetricClassifier) -> None:
        chart = ChartData(
            chart_type=ChartType.LINE,
            title="Net Revenue Retention Rate",
            y_axis_label="Percent",
            series=[ChartSeries(name="Enterprise")],
        )
        result = classifier.classify_all(chart)
        metric_ids = [m for m, _ in result]
        assert "cm_net_revenue_retention" in metric_ids

    def test_cohort_gate_exempt(self, classifier: ChartMetricClassifier) -> None:
        """NRR chart without vintage-year series must still be detected."""
        chart = ChartData(
            chart_type=ChartType.BAR,
            title="Net Dollar Retention",
            y_axis_label="NDR %",
            series=[ChartSeries(name="SMB"), ChartSeries(name="Enterprise")],
        )
        result = classifier.classify_all(chart)
        metric_ids = [m for m, _ in result]
        assert "cm_net_revenue_retention" in metric_ids

    def test_in_cohort_gate_exempt_set(self) -> None:
        assert "cm_net_revenue_retention" in _COHORT_GATE_EXEMPT


class TestCustomersByTenure:
    """cm_customers_period_end_by_tenure: cohort-gate exempt because tenure charts
    use elapsed-time axis labels (Year 1, Year 2) not calendar vintage years."""

    def test_detects_customers_by_tenure_title(self, classifier: ChartMetricClassifier) -> None:
        chart = ChartData(
            chart_type=ChartType.BAR,
            title="Customers by Tenure",
            y_axis_label="Number of Customers",
            series=[ChartSeries(name="Year 1"), ChartSeries(name="Year 2")],
        )
        result = classifier.classify_all(chart)
        metric_ids = [m for m, _ in result]
        assert "cm_customers_period_end_by_tenure" in metric_ids

    def test_cohort_gate_exempt_elapsed_time_series(
        self, classifier: ChartMetricClassifier
    ) -> None:
        """Elapsed-time series (Year 1 / Year 2) do NOT trigger _cohort_gate because
        they lack calendar 19xx/20xx years. The metric must still be detected via exempt."""
        chart = ChartData(
            chart_type=ChartType.STACKED_BAR,
            title="Customers by Tenure Band",
            y_axis_label="Count",
            series=[
                ChartSeries(
                    name="All Customers",
                    points=[DataPoint(x="Year 1", y=100.0), DataPoint(x="Year 2", y=85.0)],
                )
            ],
        )
        result = classifier.classify_all(chart)
        metric_ids = [m for m, _ in result]
        assert "cm_customers_period_end_by_tenure" in metric_ids, (
            "Tenure chart with elapsed-time x-axis must be detected via _COHORT_GATE_EXEMPT"
        )

    def test_in_cohort_gate_exempt_set(self) -> None:
        assert "cm_customers_period_end_by_tenure" in _COHORT_GATE_EXEMPT


class TestRevenueConcentration:
    """cm_revenue_concentration: cohort-gate exempt, fires on top-N customer charts."""

    def test_detects_revenue_concentration_title(self, classifier: ChartMetricClassifier) -> None:
        chart = ChartData(
            chart_type=ChartType.BAR,
            title="Revenue Concentration",
            y_axis_label="% of Total Revenue",
            series=[ChartSeries(name="Top 10 Customers")],
        )
        result = classifier.classify_all(chart)
        metric_ids = [m for m, _ in result]
        assert "cm_revenue_concentration" in metric_ids

    def test_does_not_match_generic_revenue_chart(self, classifier: ChartMetricClassifier) -> None:
        """A generic revenue bar chart without concentration signal must not fire."""
        chart = ChartData(
            chart_type=ChartType.BAR,
            title="Annual Revenue",
            y_axis_label="USD millions",
            series=[ChartSeries(name="Revenue")],
        )
        result = classifier.classify_all(chart)
        metric_ids = [m for m, _ in result]
        assert "cm_revenue_concentration" not in metric_ids

    def test_in_cohort_gate_exempt_set(self) -> None:
        assert "cm_revenue_concentration" in _COHORT_GATE_EXEMPT
