from __future__ import annotations

import re

from src.extraction_v2.chart.unit_inference import infer_unit_and_currency
from src.extraction_v2.models import ChartData, ChartType, Unit
from src.shared.keyword_config import (
    get_exclusion_patterns,
    get_metric_keywords,
    get_specific_patterns_by_metric,
)

_SUPPORTED_METRICS = (
    "cm_balance_by_cohort",
    "cm_gross_margin_by_cohort",
    "cm_revenue_by_cohort",
    "cm_transactions_by_cohort",
    "cm_ltv_to_cac_ratio",
)
_MAX_POSSIBLE_RAW = 8.3
_COHORT_YEAR_RE = re.compile(r"(?:19|20)\d{2}")
_COHORT_GATE_EXEMPT = frozenset({"cm_ltv_to_cac_ratio"})


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
    if metric_id == "cm_revenue_by_cohort":
        combined = chart.title + " " + chart.y_axis_label
        has_revenue_signal = bool(
            re.search(r"\brevenue\b", combined, re.IGNORECASE)
            or re.search(r"\bGMV\b", combined, re.IGNORECASE)
            or "$" in combined
        )
        if not has_revenue_signal:
            return False
        orders_dominant = bool(
            re.search(r"\b(orders|transactions|trades|purchases)\b", combined, re.IGNORECASE)
            and not re.search(r"\brevenue\b|\bGMV\b|\$", combined, re.IGNORECASE)
        )
        return not orders_dominant
    if metric_id == "cm_transactions_by_cohort":
        combined = chart.title + " " + chart.y_axis_label
        has_transactions = bool(
            re.search(r"\b(orders|transactions|purchases|trades)\b", combined, re.IGNORECASE)
        )
        if not has_transactions:
            return False
        dollar_dominant = "$" in chart.y_axis_label and not re.search(
            r"\b(orders|transactions|purchases|trades)\b", chart.y_axis_label, re.IGNORECASE
        )
        return not dollar_dominant
    if metric_id == "cm_ltv_to_cac_ratio":
        combined = chart.title + " " + chart.y_axis_label
        return bool(
            re.search(r"ltv\s*[:/ to]+\s*cac", combined, re.IGNORECASE)
            or re.search(r"lifetime\s+value.*acquisition\s+cost", combined, re.IGNORECASE)
        )
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
            for mid in _SUPPORTED_METRICS
        }

        cohort_passed = _cohort_gate(chart)

        candidates: list[tuple[str, float]] = []
        for mid in _SUPPORTED_METRICS:
            if mid in _COHORT_GATE_EXEMPT:
                if _metric_gate(mid, chart):
                    candidates.append((mid, scores[mid]))
            else:
                if cohort_passed and _metric_gate(mid, chart):
                    candidates.append((mid, scores[mid]))

        if not candidates:
            best_raw = max(scores.values()) if scores else 0.0
            return (None, best_raw)

        rev_id = "cm_revenue_by_cohort"
        txn_id = "cm_transactions_by_cohort"
        candidate_ids = {mid for mid, _ in candidates}
        if rev_id in candidate_ids and txn_id in candidate_ids:
            unit, _currency = infer_unit_and_currency(chart.y_axis_label)
            if unit == Unit.CURRENCY:
                candidates = [(mid, s) for mid, s in candidates if mid != txn_id]
            elif unit == Unit.COUNT:
                candidates = [(mid, s) for mid, s in candidates if mid != rev_id]

        best_id, best_score = max(candidates, key=lambda x: x[1])
        return (best_id, best_score)
