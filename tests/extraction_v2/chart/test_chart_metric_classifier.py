import pytest

from src.extraction_v2.chart.metric_classifier import _COHORT_GATE_EXEMPT, ChartMetricClassifier
from src.extraction_v2.models import ChartAnnotation, ChartData, ChartSeries, ChartType, DataPoint


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


def test_classifies_revenue_by_cohort_with_dollar_y_axis(
    classifier: ChartMetricClassifier,
) -> None:
    chart = ChartData(
        chart_type=ChartType.STACKED_BAR,
        title="Revenue by Cohort",
        y_axis_label="$ Millions",
        x_axis_label="Year",
        series=[
            ChartSeries(name="2019"),
            ChartSeries(name="2020"),
        ],
    )
    metric_id, _score = classifier.classify(chart)
    assert metric_id == "cm_revenue_by_cohort"


def test_classifies_revenue_by_cohort_with_gmv_title(
    classifier: ChartMetricClassifier,
) -> None:
    chart = ChartData(
        chart_type=ChartType.BAR,
        title="Gross Merchandise Value by Cohort",
        y_axis_label="GMV (USD)",
        x_axis_label="Year",
        series=[ChartSeries(name="2020")],
    )
    metric_id, _score = classifier.classify(chart)
    assert metric_id == "cm_revenue_by_cohort"


def test_classifies_ltv_to_cac_bypasses_cohort_gate(
    classifier: ChartMetricClassifier,
) -> None:
    chart = ChartData(
        chart_type=ChartType.BAR,
        title="LTV to CAC Ratio by Tenure",
        y_axis_label="Ratio (x)",
        x_axis_label="Tenure",
        series=[
            ChartSeries(
                name="All Customers",
                points=[DataPoint(x="1 Year Tenure", y=1.8)],
            )
        ],
    )
    metric_id, _score = classifier.classify(chart)
    assert metric_id == "cm_ltv_to_cac_ratio"


def test_transactions_chart_rejected_when_dollar_y_axis(
    classifier: ChartMetricClassifier,
) -> None:
    chart = ChartData(
        chart_type=ChartType.STACKED_BAR,
        title="Orders by Cohort",
        y_axis_label="$ Revenue",
        x_axis_label="Year",
        series=[ChartSeries(name="2020")],
    )
    result = classifier.classify(chart)
    assert result[0] != "cm_transactions_by_cohort"


def test_revenue_chart_rejected_when_orders_dominates_title(
    classifier: ChartMetricClassifier,
) -> None:
    chart = ChartData(
        chart_type=ChartType.STACKED_BAR,
        title="Number of Orders by Cohort",
        y_axis_label="Order Count",
        x_axis_label="Year",
        series=[ChartSeries(name="2020")],
    )
    result = classifier.classify(chart)
    assert result[0] != "cm_revenue_by_cohort"


def test_cohort_gate_exempt_set_applies_only_to_ltv_to_cac() -> None:
    assert "cm_ltv_to_cac_ratio" in _COHORT_GATE_EXEMPT
    assert "cm_revenue_by_cohort" not in _COHORT_GATE_EXEMPT


def test_annotation_scoring_capped_at_08(classifier: ChartMetricClassifier) -> None:
    # Must keep raw score below _MAX_POSSIBLE_RAW (8.3) in BOTH n=1 and n=5 cases,
    # otherwise normalization clamp at 1.0 masks the cap. Use a minimal chart with
    # only y_axis + cohort-gate signal, so raw stays small:
    #   with cap: raw = 1.5 (y_axis "margin") + 0.8 (cap) = 2.3  → score ≈ 0.277
    #   no cap n=5: raw = 1.5 + 5*0.8 = 5.5 → score ≈ 0.663 (distinct from 0.277)
    def _chart_with_n_anns(n: int) -> ChartData:
        return ChartData(
            chart_type=ChartType.STACKED_BAR,
            title="",
            y_axis_label="margin",
            x_axis_label="",
            series=[ChartSeries(name="2020")],
            annotations=[ChartAnnotation(text="gross margin by cohort") for _ in range(n)],
        )

    _, score_1 = classifier.classify(_chart_with_n_anns(1))
    _, score_5 = classifier.classify(_chart_with_n_anns(5))
    assert score_5 == score_1
    assert score_1 < 0.5


def test_ltv_cac_gate_accepts_common_phrasings() -> None:
    from src.extraction_v2.chart.metric_classifier import _metric_gate

    def _chart_with_title(title: str) -> ChartData:
        return ChartData(
            chart_type=ChartType.BAR,
            title=title,
            y_axis_label="Ratio (x)",
            x_axis_label="Tenure",
            series=[ChartSeries(name="All Customers", points=[DataPoint(x="1 Year", y=1.8)])],
        )

    positives = [
        "LTV to CAC Ratio by Tenure",
        "LTV:CAC Over Time",
        "LTV/CAC by Cohort",
        "LTV vs CAC Analysis",
    ]
    for title in positives:
        assert _metric_gate("cm_ltv_to_cac_ratio", _chart_with_title(title)), (
            f"expected gate to accept: {title!r}"
        )

    assert not _metric_gate(
        "cm_ltv_to_cac_ratio", _chart_with_title("LTV and CAC Analysis")
    )
