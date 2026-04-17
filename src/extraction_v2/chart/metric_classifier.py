from __future__ import annotations

import re

from src.extraction_v2.models import ChartData, ChartType
from src.shared.keyword_config import (
    get_exclusion_patterns,
    get_metric_keywords,
    get_specific_patterns_by_metric,
)

_PHASE_1_METRICS = ("cm_balance_by_cohort", "cm_gross_margin_by_cohort")
_MAX_POSSIBLE_RAW = 8.3
_COHORT_YEAR_RE = re.compile(r"(?:19|20)\d{2}")


def _any_match(patterns: list[str], text: str) -> bool:
    return any(re.search(p, text, re.IGNORECASE) for p in patterns)


def _cohort_gate(chart: ChartData) -> bool:
    if any(_COHORT_YEAR_RE.search(s.name) for s in chart.series):
        return True
    for field in (chart.title, chart.x_axis_label, chart.y_axis_label):
        if re.search(r"\b(?:cohort|vintage)\b", field, re.IGNORECASE):
            return True
    return False


def _metric_gate(metric_id: str, chart: ChartData) -> bool:
    if metric_id == "cm_balance_by_cohort":
        has_deposit_or_balance = re.search(
            r"\b(?:deposits?|balance)\b",
            chart.title + " " + chart.y_axis_label,
            re.IGNORECASE,
        )
        has_chart_type = chart.chart_type in (ChartType.BAR, ChartType.STACKED_BAR)
        return bool(has_deposit_or_balance and has_chart_type)
    if metric_id == "cm_gross_margin_by_cohort":
        return bool(re.search(r"%|margin|contribution\s+margin", chart.y_axis_label, re.IGNORECASE))
    return False


def _score_metric(
    metric_id: str,
    chart: ChartData,
    nearby_text: str,
    all_keywords: dict[str, list[str]],
    specific_by_metric: dict[str, list[str]],
    exclusions: dict[str, list[str]],
) -> float:
    patterns = all_keywords.get(metric_id, [])
    specific = specific_by_metric.get(metric_id, [])
    excl = exclusions.get(metric_id, [])

    raw = 0.0
    if specific and _any_match(specific, chart.title):
        raw += 3.0
    if patterns and _any_match(patterns, chart.title):
        raw += 2.0
    if patterns and _any_match(patterns, chart.y_axis_label):
        raw += 1.5
    if patterns and _any_match(patterns, chart.x_axis_label + " " + nearby_text[:1500]):
        raw += 1.0
    if patterns:
        raw += 0.8 * sum(1 for ann in chart.annotations if _any_match(patterns, ann.text))
    if excl and _any_match(excl, chart.title + " " + chart.y_axis_label):
        raw -= 5.0

    return min(1.0, max(0.0, raw) / _MAX_POSSIBLE_RAW)


class ChartMetricClassifier:
    def __init__(self) -> None:
        self._keywords = get_metric_keywords()
        self._specific = get_specific_patterns_by_metric()
        self._exclusions = get_exclusion_patterns()

    def classify(self, chart: ChartData, nearby_text: str = "") -> tuple[str | None, float]:
        scores = {
            mid: _score_metric(
                mid,
                chart,
                nearby_text,
                self._keywords,
                self._specific,
                self._exclusions,
            )
            for mid in _PHASE_1_METRICS
        }

        # Pick best-scoring metric that satisfies all gates.
        # Return (None, best_raw_score) when any gate blocks.
        if not _cohort_gate(chart):
            best_raw = max(scores.values()) if scores else 0.0
            return (None, best_raw)

        candidates = [(mid, scores[mid]) for mid in _PHASE_1_METRICS if _metric_gate(mid, chart)]
        if not candidates:
            best_raw = max(scores.values()) if scores else 0.0
            return (None, best_raw)

        best_id, best_score = max(candidates, key=lambda x: x[1])
        return (best_id, best_score)
