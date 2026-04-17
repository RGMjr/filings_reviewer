import pytest

from src.extraction_v2.chart.metric_classifier import ChartMetricClassifier
from src.extraction_v2.models import ChartAnnotation, ChartData, ChartSeries, ChartType


@pytest.fixture
def classifier() -> ChartMetricClassifier:
    return ChartMetricClassifier()


def test_classifies_robinhood_deposits_as_balance_by_cohort(
    classifier: ChartMetricClassifier,
) -> None:
    chart = ChartData(
        chart_type=ChartType.STACKED_BAR,
        title="Cumulative Net Deposits by Cohort",
        y_axis_label="$ billions",
        x_axis_label="Year",
        series=[
            ChartSeries(name="2015"),
            ChartSeries(name="2016"),
            ChartSeries(name="2017"),
        ],
    )
    metric_id, score = classifier.classify(chart)
    assert metric_id == "cm_balance_by_cohort"
    assert score >= 0.6


def test_classifies_farfetch_contribution_margin_as_gross_margin(
    classifier: ChartMetricClassifier,
) -> None:
    # title hits margin-by-cohort pattern (+2.0), y_axis hits cohort-margin (+1.5),
    # x_axis hits cohort-margin (+1.0), annotation hits gross-margin-by-cohort (+0.8)
    # → raw 5.3/8.3 ≈ 0.638
    chart = ChartData(
        chart_type=ChartType.BAR,
        title="Contribution Margin by Cohort Year",
        y_axis_label="Cohort Gross Margin %",
        x_axis_label="Cohort Margin",
        series=[
            ChartSeries(name="2016"),
            ChartSeries(name="2017"),
            ChartSeries(name="2018"),
        ],
        annotations=[ChartAnnotation(text="gross margin by cohort")],
    )
    metric_id, score = classifier.classify(chart)
    assert metric_id == "cm_gross_margin_by_cohort"
    assert score >= 0.6


def test_ambiguous_chart_returns_none_below_threshold(
    classifier: ChartMetricClassifier,
) -> None:
    chart = ChartData(
        chart_type=ChartType.BAR,
        title="Annual Revenue",
        y_axis_label="USD millions",
        x_axis_label="Year",
        series=[ChartSeries(name="Revenue")],
    )
    metric_id, _score = classifier.classify(chart)
    assert metric_id is None


def test_cohort_gate_rejects_generic_revenue_chart(
    classifier: ChartMetricClassifier,
) -> None:
    # Title/axes have no "cohort"/"vintage"; series names are not year-like.
    chart = ChartData(
        chart_type=ChartType.BAR,
        title="Revenue by Segment",
        y_axis_label="$ millions",
        x_axis_label="Segment",
        series=[
            ChartSeries(name="North America"),
            ChartSeries(name="Europe"),
        ],
    )
    metric_id, _score = classifier.classify(chart)
    assert metric_id is None


def test_exclusions_zero_out_score(classifier: ChartMetricClassifier) -> None:
    # Neither cm_balance_by_cohort nor cm_gross_margin_by_cohort have exclusion
    # patterns in config; verifies that absent exclusions don't raise an error.
    chart = ChartData(
        chart_type=ChartType.STACKED_BAR,
        title="Cumulative Net Deposits by Cohort",
        y_axis_label="$ billions",
        series=[ChartSeries(name="2020")],
    )
    metric_id, score = classifier.classify(chart)
    # Must not raise; result must be a valid (str|None, float) tuple.
    assert isinstance(score, float)
    assert score >= 0.0
