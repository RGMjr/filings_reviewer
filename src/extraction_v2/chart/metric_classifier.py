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
_CUSTOMER_TYPE_RE = re.compile(
    r"\b(?:new|existing|returning|blended|all|acquired|prior|repeat)\b[^,.;]{0,40}"
    r"\b(?:consumer|customer|member|subscriber|user|buyer|account|client)s?\b"
    r"|\b(?:consumer|customer|member|subscriber|user|buyer|account|client)s?\s+(?:cohort|segment)\b",
    re.IGNORECASE,
)


def _any_match(patterns: list[str], text: str) -> bool:
    return any(re.search(p, text, re.IGNORECASE) for p in patterns)


def _cohort_gate(chart: ChartData) -> bool:
    if any(_COHORT_YEAR_RE.search(s.name) for s in chart.series):
        return True
    for field in (chart.title, chart.x_axis_label, chart.y_axis_label):
        if re.search(r"\b(?:cohort|vintage)\b", field, re.IGNORECASE):
            return True
    # Fallback: fiscal year lives in point.x across multiple distinct years
    # (e.g. FTCH Order Contribution Margin — customer-type series, year x-axis).
    point_years: set[str] = set()
    for s in chart.series:
        for p in s.points:
            m = _COHORT_YEAR_RE.search(str(p.x or ""))
            if m:
                point_years.add(m.group())
    if len(point_years) >= 2 and any(_CUSTOMER_TYPE_RE.search(s.name) for s in chart.series):
        return True
    return False


def _metric_gate(metric_id: str, chart: ChartData, nearby_text: str = "") -> bool:
    if metric_id == "cm_balance_by_cohort":
        has_deposit_or_balance = re.search(
            r"\b(?:deposits?|balance)\b",
            chart.title + " " + chart.y_axis_label,
            re.IGNORECASE,
        )
        has_chart_type = chart.chart_type in (ChartType.BAR, ChartType.STACKED_BAR)
        return bool(has_deposit_or_balance and has_chart_type)
    if metric_id == "cm_gross_margin_by_cohort":
        if re.search(r"%|margin|contribution\s+margin", chart.y_axis_label, re.IGNORECASE):
            return True
        # Fallback for OCR outputs with missing y_axis_label: require margin /
        # contribution keyword somewhere in chart text OR nearby_text, AND a
        # percentage signal (point labels or axis).
        text_blob = " ".join(
            [
                chart.title or "",
                chart.x_axis_label or "",
                chart.y_axis_label or "",
                " ".join(s.name or "" for s in chart.series),
                nearby_text[:1500] if nearby_text else "",
            ]
        )
        has_margin = bool(re.search(r"\b(?:margin|contribution)\b", text_blob, re.IGNORECASE))
        has_percent = "%" in (chart.y_axis_label or "") or any(
            "%" in (p.label or "") for s in chart.series for p in s.points
        )
        return has_margin and has_percent
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
            re.search(r"ltv\s*(?::|/|\s+to\s+|\s+vs\.?\s+)\s*cac", combined, re.IGNORECASE)
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

    # When OCR returns a chart with no title/y_axis_label (the FTCH Order
    # Contribution Margin case), fall back to the first ~200 chars of
    # nearby_text as a pseudo-title so pattern matches can still score.
    effective_title = chart.title if chart.title else nearby_text[:200]
    title_fallback_used = not chart.title and bool(nearby_text)

    raw = 0.0
    if specific and _any_match(specific, effective_title):
        raw += 3.0
    if patterns and _any_match(patterns, effective_title):
        raw += 2.0
    if patterns and _any_match(patterns, chart.y_axis_label):
        raw += 1.5
    # Avoid double-counting nearby_text when it's already been promoted to
    # title; compare against x_axis_label + empty when that promotion fired.
    axis_near_text = chart.x_axis_label + " " + ("" if title_fallback_used else nearby_text[:1500])
    if patterns and _any_match(patterns, axis_near_text):
        raw += 1.0
    if patterns:
        ann_hits = sum(1 for ann in chart.annotations if _any_match(patterns, ann.text))
        raw += min(0.8, 0.8 * ann_hits)
    # Structural bonus: cohort-percentage chart with customer-type series
    # (e.g. FTCH Order Contribution Margin) that lacks title/axes but is
    # structurally a gross-margin-by-cohort chart.
    if metric_id == "cm_gross_margin_by_cohort":
        has_pct_labels = any("%" in (p.label or "") for s in chart.series for p in s.points)
        point_years = {
            m.group()
            for s in chart.series
            for p in s.points
            if (m := _COHORT_YEAR_RE.search(str(p.x or "")))
        }
        has_customer_type = any(_CUSTOMER_TYPE_RE.search(s.name) for s in chart.series)
        if has_pct_labels and len(point_years) >= 2 and has_customer_type:
            # Structural signature alone must clear the 0.6 threshold
            # (≈4.98 raw), since charts of this shape often arrive with
            # empty title/axes and no nearby-text pattern match.
            raw += 5.5
    if excl and _any_match(excl, chart.title + " " + chart.y_axis_label):
        raw -= 5.0

    return min(1.0, max(0.0, raw) / _MAX_POSSIBLE_RAW)


class ChartMetricClassifier:
    def __init__(self) -> None:
        self._keywords = get_metric_keywords()
        self._specific = get_specific_patterns_by_metric()
        self._exclusions = get_exclusion_patterns()

    def _build_candidates(self, chart: ChartData, nearby_text: str) -> list[tuple[str, float]]:
        """Compute gated candidate list (shared by classify and classify_all)."""
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
                if _metric_gate(mid, chart, nearby_text):
                    candidates.append((mid, scores[mid]))
            else:
                if cohort_passed and _metric_gate(mid, chart, nearby_text):
                    candidates.append((mid, scores[mid]))

        return candidates

    def classify_all(self, chart: ChartData, nearby_text: str = "") -> list[tuple[str, float]]:
        """Return all candidates passing _cohort_gate + _metric_gate, sorted by score desc.

        Unlike ``classify()``, this does NOT apply the revenue/transactions
        unit-disambiguation filter and does NOT collapse to a single winner.
        Suitable for metric-presence detection where multiple metrics may be
        present on the same chart (e.g. a stacked-bar cohort chart covering
        both cm_revenue_by_cohort and cm_balance_by_cohort).
        """
        candidates = self._build_candidates(chart, nearby_text)
        return sorted(candidates, key=lambda x: x[1], reverse=True)

    def classify(self, chart: ChartData, nearby_text: str = "") -> tuple[str | None, float]:
        """Return the single best-matching metric, or (None, raw_best) if none pass gates."""
        candidates = self._build_candidates(chart, nearby_text)

        if not candidates:
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
