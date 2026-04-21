# Boundary-sensitivity guard — see KNOWN_ISSUES #64.

import pytest

from src.extraction_v2.chart.metric_classifier import ChartMetricClassifier
from src.extraction_v2.models import ChartAnnotation, ChartData, ChartSeries, ChartType, DataPoint


def _build_hood_deposits_chart() -> ChartData:
    return ChartData(
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


def _build_farfetch_contribution_margin_chart() -> ChartData:
    return ChartData(
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


def _build_ftch_empty_axes_chart() -> ChartData:
    return ChartData(
        chart_type=ChartType.LINE,
        title="",
        y_axis_label="",
        x_axis_label="",
        series=[
            ChartSeries(
                name="Existing Consumers",
                points=[
                    DataPoint(x="2015", y=45.0, label="45%"),
                    DataPoint(x="2016", y=46.0, label="46%"),
                    DataPoint(x="2017", y=54.0, label="54%"),
                ],
            ),
            ChartSeries(
                name="All Consumers - Blended",
                points=[
                    DataPoint(x="2015", y=33.0, label="33%"),
                    DataPoint(x="2016", y=36.0, label="36%"),
                    DataPoint(x="2017", y=44.0, label="44%"),
                ],
            ),
            ChartSeries(
                name="New Consumers",
                points=[
                    DataPoint(x="2015", y=23.0, label="23%"),
                    DataPoint(x="2016", y=26.0, label="26%"),
                    DataPoint(x="2017", y=31.0, label="31%"),
                ],
            ),
        ],
    )


_FTCH_EMPTY_AXES_NEARBY_TEXT = (
    "Table of Contents Marketplace Order Contribution Margin "
    "(% Adjusted Marketplace Revenue) Fulfilment To facilitate and grow "
    "our platform, we provide fulfilment services to Marketplace "
    "consumers and receive revenue from the provision of these services."
)


def _classify_ftch_empty_axes(classifier: ChartMetricClassifier) -> tuple[str | None, float]:
    return classifier.classify(_build_ftch_empty_axes_chart(), _FTCH_EMPTY_AXES_NEARBY_TEXT)


@pytest.mark.parametrize(
    "chart_builder, nearby_text, expected_metric_id, floor",
    [
        (_build_hood_deposits_chart, "", "cm_balance_by_cohort", 0.5974),
        (_build_farfetch_contribution_margin_chart, "", "cm_gross_margin_by_cohort", 0.995),
        (
            _build_ftch_empty_axes_chart,
            _FTCH_EMPTY_AXES_NEARBY_TEXT,
            "cm_gross_margin_by_cohort",
            0.6577,
        ),
    ],
)
def test_tier1_chart_score_margin_locked_in(
    chart_builder: object,
    nearby_text: str,
    expected_metric_id: str,
    floor: float,
) -> None:
    classifier = ChartMetricClassifier()
    chart = chart_builder()  # type: ignore[operator]
    metric_id, score = classifier.classify(chart, nearby_text)
    assert metric_id == expected_metric_id
    assert score >= floor, f"score {score:.4f} below locked floor {floor}"
    assert score > 0.60, f"score {score:.4f} below classification gate 0.60"
