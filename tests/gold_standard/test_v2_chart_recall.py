from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from src.extraction_v2.chart.cohort_parser import CohortParser
from src.extraction_v2.chart.metric_classifier import ChartMetricClassifier
from src.extraction_v2.models import (
    ChartAnnotation,
    ChartData,
    ChartSeries,
    ChartType,
    DataPoint,
)

FIXTURES = Path("tests/fixtures/charts")


def load_chart_data(name: str) -> ChartData:
    raw = json.loads((FIXTURES / name).read_text())

    chart_type_map = {v.value: v for v in ChartType}
    chart_type = chart_type_map.get(raw.get("chart_type", ""), ChartType.UNKNOWN)

    series = [
        ChartSeries(
            name=s["name"],
            points=[
                DataPoint(
                    x=p["x"],
                    y=p["y"],
                    label=p.get("label"),
                )
                for p in s.get("points", [])
            ],
        )
        for s in raw.get("series", [])
    ]

    annotations = [
        ChartAnnotation(
            text=a.get("text", ""),
            value=a.get("value"),
            unit=a.get("unit", ""),
            category=a.get("category", ""),
            period=a.get("period", ""),
        )
        for a in raw.get("annotations", [])
    ]

    return ChartData(
        chart_type=chart_type,
        title=raw.get("title", ""),
        x_axis_label=raw.get("x_axis_label", ""),
        y_axis_label=raw.get("y_axis_label", ""),
        series=series,
        annotations=annotations,
    )


class TestChartFactBridgeRecall:
    def test_hood_classified_as_balance_by_cohort(self) -> None:
        chart = load_chart_data("HOOD_cumulative_net_deposits.chart_data.json")
        classifier = ChartMetricClassifier()
        metric_id, score = classifier.classify(chart, "")
        assert metric_id == "cm_balance_by_cohort"
        assert score >= 0.6

    def test_ftch_classified_as_gross_margin_by_cohort(self) -> None:
        chart = load_chart_data("FTCH_g607688g09d00.chart_data.json")
        classifier = ChartMetricClassifier()
        metric_id, score = classifier.classify(chart, "")
        assert metric_id == "cm_gross_margin_by_cohort"
        assert score >= 0.6

    def test_hood_cohort_parser_produces_facts(self) -> None:
        chart = load_chart_data("HOOD_cumulative_net_deposits.chart_data.json")
        parser = CohortParser()
        filing_date = date(2021, 10, 8)
        facts_count = 0
        for series in chart.series:
            for point in series.points:
                cp = parser.parse(chart, series, point, filing_date)
                if cp is not None:
                    facts_count += 1
        assert facts_count >= 5, f"Expected >=5 parseable points, got {facts_count}"

    def test_ftch_cohort_parser_produces_facts(self) -> None:
        chart = load_chart_data("FTCH_g607688g09d00.chart_data.json")
        parser = CohortParser()
        filing_date = date(2018, 9, 24)
        facts_count = 0
        for series in chart.series:
            for point in series.points:
                cp = parser.parse(chart, series, point, filing_date)
                if cp is not None:
                    facts_count += 1
        assert facts_count >= 3, f"Expected >=3 parseable points, got {facts_count}"
