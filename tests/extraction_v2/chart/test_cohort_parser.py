from datetime import date

from src.extraction_v2.chart.cohort_parser import CohortParser
from src.extraction_v2.models import (
    ChartAnnotation,
    ChartData,
    ChartSeries,
    ChartType,
    DataPoint,
)


def _parser() -> CohortParser:
    return CohortParser()


def _chart(
    series: list[ChartSeries] | None = None, annotations: list[ChartAnnotation] | None = None
) -> ChartData:
    return ChartData(
        chart_type=ChartType.STACKED_BAR,
        series=series or [],
        annotations=annotations or [],
    )


def test_parses_year_cohort_from_series_name() -> None:
    series = ChartSeries(name="2017 cohort", points=[DataPoint(x="2020", y=100.0)])
    chart = _chart(series=[series])
    result = _parser().parse(chart, series, series.points[0], date(2021, 6, 30))
    assert result is not None
    assert result.cohort_def == "2017"
    assert result.period_start == date(2017, 1, 1)


def test_parses_measurement_year_from_xaxis() -> None:
    series = ChartSeries(name="2016", points=[DataPoint(x="2021", y=50.0)])
    chart = _chart(series=[series])
    result = _parser().parse(chart, series, series.points[0], date(2022, 1, 1))
    assert result is not None
    assert result.period_end == date(2021, 12, 31)


def test_falls_back_to_annotations_when_series_empty() -> None:
    ann = ChartAnnotation(
        text="2019 cohort data", value=None, unit="", category="Cohort 2019", period="2019"
    )
    chart = _chart(series=[], annotations=[ann])
    result = _parser().parse(chart, None, None, date(2021, 1, 1))
    assert result is not None
    assert result.requires_review is True
    assert result.confidence == 0.55


def test_stacked_bar_vintages() -> None:
    s2015 = ChartSeries(
        name="2015", points=[DataPoint(x="2020", y=30.0), DataPoint(x="2021", y=28.0)]
    )
    s2016 = ChartSeries(name="2016", points=[DataPoint(x="2020", y=40.0)])
    s2017 = ChartSeries(name="2017", points=[DataPoint(x="2020", y=55.0)])
    chart = _chart(series=[s2015, s2016, s2017])
    result = _parser().parse(chart, s2016, s2016.points[0], date(2021, 6, 1))
    assert result is not None
    assert result.cohort_def == "2016"
    assert result.period_start == date(2016, 1, 1)
    assert result.period_end == date(2020, 12, 31)
    assert result.confidence == 0.85
    assert result.requires_review is False


def test_rejects_unparseable_cohort() -> None:
    series = ChartSeries(name="Revenue", points=[DataPoint(x="Q1", y=100.0)])
    chart = _chart(series=[series], annotations=[])
    result = _parser().parse(chart, series, series.points[0], date(2021, 1, 1))
    assert result is None


def test_simple_bar_uses_filing_date_when_no_time_axis() -> None:
    series = ChartSeries(name="Total Revenue", points=[DataPoint(x="FY2020", y=500.0)])
    chart = _chart(series=[series])
    result = _parser().parse(chart, series, series.points[0], date(2021, 3, 15))
    assert result is None


def test_elapsed_period_regime_year_n() -> None:
    series = ChartSeries(name="2019", points=[DataPoint(x="Year 2", y=75.0)])
    chart = _chart(series=[series])
    result = _parser().parse(chart, series, series.points[0], date(2022, 1, 1))
    assert result is not None
    assert "2019" in result.cohort_def
    assert "Year 2" in result.cohort_def
    assert result.period_end == date(2021, 1, 1)
    assert result.confidence == 0.80
    assert result.requires_review is False


def test_elapsed_period_regime_month_n() -> None:
    series = ChartSeries(name="2020 Cohort", points=[DataPoint(x="Month 6", y=60.0)])
    chart = _chart(series=[series])
    result = _parser().parse(chart, series, series.points[0], date(2022, 1, 1))
    assert result is not None
    assert result.period_end == date(2020, 7, 1)
    assert result.confidence == 0.80
    assert result.requires_review is False


def test_elapsed_period_rejects_when_series_name_has_no_year() -> None:
    series = ChartSeries(name="New Customers", points=[DataPoint(x="Year 1", y=50.0)])
    chart = _chart(series=[series])
    parser = _parser()
    result = parser._parse_elapsed_period_regime(chart, series, series.points[0], date(2022, 1, 1))
    assert result is None


def test_regime_dispatch_order_prefers_series_year_over_elapsed() -> None:
    series = ChartSeries(name="2019", points=[DataPoint(x="2021", y=80.0)])
    chart = _chart(series=[series])
    result = _parser().parse(chart, series, series.points[0], date(2022, 1, 1))
    assert result is not None
    assert result.period_end == date(2021, 12, 31)
    assert result.confidence == 0.85
