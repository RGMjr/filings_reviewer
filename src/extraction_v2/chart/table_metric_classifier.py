"""Table-image metric presence scorer.

Scores an OCR-reconstructed Table against the same metrics supported by
ChartMetricClassifier, using header_path / stub_path keyword matching rather
than chart-axis / series structure.

_SUPPORTED_METRICS must stay in sync with ChartMetricClassifier._SUPPORTED_METRICS
in src/extraction_v2/chart/metric_classifier.py (expanded in gh-289 Scope B).

Intended call site: ChartFactBridgeStage (after the chart-data branch),
when image.ocr_table is not None.

Scoring surfaces and weights
-----------------------------
  title / nearby_text[:200]   1.0   (caption / surrounding text)
  column header_path          2.0   (highest: headers often name the metric)
  row stub_path               1.5   (medium: row labels carry cohort context)
  cell text (capped)          0.5   (low: only counted when header or stub matched)

Soft denominator: sum of max possible per-surface weights, derived from the
weight table itself.  This keeps the [0, 1] clip honest without magic constants.

Usage
-----
    from src.extraction_v2.chart.table_metric_classifier import score_ocr_table

    candidates = score_ocr_table(table, nearby_text="Cohort Revenue by Year")
    # → [("cm_revenue_by_cohort", 0.72), ...]

No keyword-config changes required — reuses get_metric_keywords /
get_specific_patterns_by_metric / get_exclusion_patterns from
src.shared.keyword_config.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from src.extraction_v2.models import Table
from src.shared.keyword_config import (
    get_exclusion_patterns,
    get_metric_keywords,
    get_specific_patterns_by_metric,
)

if TYPE_CHECKING:
    from src.extraction_v2.pipeline import KeywordPatchOverride

# Must stay in sync with ChartMetricClassifier._SUPPORTED_METRICS
# (src/extraction_v2/chart/metric_classifier.py).
# No metric_gate equivalent here — keyword patterns + the 0.5 score threshold
# applied by ChartFactBridgeStage act as the implicit discriminator.
_SUPPORTED_METRICS: tuple[str, ...] = (
    # Original 5 cohort metrics
    "cm_balance_by_cohort",
    "cm_gross_margin_by_cohort",
    "cm_revenue_by_cohort",
    "cm_transactions_by_cohort",
    "cm_ltv_to_cac_ratio",
    # Tier-1 expansion (gh-289 Scope B): retention + concentration + tenure
    "cm_customer_retention_rate",
    "cm_net_revenue_retention",
    "cm_customers_period_end_by_tenure",
    "cm_revenue_concentration",
)

# Surface weights — used both for scoring and for computing the soft denominator.
_W_TITLE = 1.0
_W_HEADER = 2.0
_W_STUB = 1.5
_W_CELL = 0.5  # applied per-column (capped at 1 column's worth)

# Soft denominator: max possible score if every surface matched.
# title + best header + best stub + capped cell contribution.
_SOFT_DENOM: float = _W_TITLE + _W_HEADER + _W_STUB + _W_CELL


def _any_match(patterns: list[str], text: str) -> bool:
    return any(re.search(p, text, re.IGNORECASE) for p in patterns)


def _score_metric_on_table(
    metric_id: str,
    table: Table,
    nearby_text: str,
    all_keywords: dict[str, list[str]],
    specific_by_metric: dict[str, list[str]],
    exclusions: dict[str, list[str]],
) -> float:
    """Compute a [0, 1] presence score for one metric against a reconstructed Table.

    Args:
        metric_id: One of _SUPPORTED_METRICS.
        table: OCR-reconstructed Table with cell header_path / stub_path set.
        nearby_text: Caption or surrounding text for the image (used as title proxy).
        all_keywords: Primary keyword patterns keyed by metric_id.
        specific_by_metric: Specific (high-confidence) patterns keyed by metric_id.
        exclusions: Exclusion patterns keyed by metric_id.

    Returns:
        Score in [0.0, 1.0].
    """
    patterns = all_keywords.get(metric_id, [])
    specific = specific_by_metric.get(metric_id, [])
    excl = exclusions.get(metric_id, [])

    if not patterns:
        return 0.0

    # ----------------------------------------------------------------
    # Title surface: caption / nearby text (first 200 chars)
    # ----------------------------------------------------------------
    title_text = nearby_text[:200]
    raw = 0.0

    # Specific patterns (multi-word, high confidence) match title
    if specific and _any_match(specific, title_text):
        raw += _W_TITLE + 0.5  # small bonus for specific match
    elif patterns and _any_match(patterns, title_text):
        raw += _W_TITLE

    # ----------------------------------------------------------------
    # Header surface: column header_path of every non-stub, non-header cell
    # ----------------------------------------------------------------
    header_hit = False
    header_texts: set[str] = set()
    for cell in table.cells:
        if cell.is_header:
            text = cell.text.strip()
            if text:
                header_texts.add(text)
    # Also collect from header_path on data cells
    for cell in table.cells:
        if not cell.is_header and not cell.is_stub:
            for h in cell.header_path:
                if h.strip():
                    header_texts.add(h.strip())

    combined_headers = " | ".join(header_texts)
    if combined_headers and _any_match(patterns, combined_headers):
        raw += _W_HEADER
        header_hit = True

    # ----------------------------------------------------------------
    # Stub surface: row stub_path of data cells
    # ----------------------------------------------------------------
    stub_hit = False
    stub_texts: set[str] = set()
    for cell in table.cells:
        if cell.is_stub:
            text = cell.text.strip()
            if text:
                stub_texts.add(text)
    for cell in table.cells:
        if not cell.is_header and not cell.is_stub:
            for s in cell.stub_path:
                if s.strip():
                    stub_texts.add(s.strip())

    combined_stubs = " | ".join(stub_texts)
    if combined_stubs and _any_match(patterns, combined_stubs):
        raw += _W_STUB
        stub_hit = True

    # ----------------------------------------------------------------
    # Cell surface: value-cells where header or stub already matched
    # (capped to avoid inflating score from large tables)
    # ----------------------------------------------------------------
    if header_hit or stub_hit:
        cell_hits = 0
        for cell in table.cells:
            if cell.is_header or cell.is_stub:
                continue
            if _any_match(patterns, cell.text):
                cell_hits += 1
                if cell_hits >= 1:  # cap: count at most one column's worth
                    break
        if cell_hits:
            raw += _W_CELL

    # ----------------------------------------------------------------
    # Exclusion penalty
    # ----------------------------------------------------------------
    all_text = f"{title_text} {combined_headers} {combined_stubs}"
    if excl and _any_match(excl, all_text):
        raw -= 5.0

    return min(1.0, max(0.0, raw) / _SOFT_DENOM)


def score_ocr_table(
    table: Table,
    nearby_text: str = "",
    *,
    keyword_override: KeywordPatchOverride | None = None,
) -> list[tuple[str, float]]:
    """Score an OCR-reconstructed table for per-metric presence.

    Returns a list of (metric_id, score) pairs, sorted by score descending,
    for all metrics in _SUPPORTED_METRICS.  The caller (ChartFactBridgeStage)
    applies the chart_presence_min_score gate before emitting DetectedMetric rows.

    Args:
        table: Reconstructed Table from OCR (header_path / stub_path populated).
        nearby_text: Caption or nearby paragraph text used as a title proxy.
        keyword_override: Optional per-metric pattern overrides
            (simulate-and-ship flow). When None, YAML defaults are used.

    Returns:
        List of (metric_id, score) tuples sorted score-descending.
        All supported metrics are always included (score may be 0.0).
    """
    override = keyword_override or {}
    keywords = get_metric_keywords(override=override.get("metric_keywords"))
    specific = get_specific_patterns_by_metric(override=override.get("specific_patterns"))
    exclusions = get_exclusion_patterns(override=override.get("exclusion_patterns"))

    results: list[tuple[str, float]] = []
    for metric_id in _SUPPORTED_METRICS:
        score = _score_metric_on_table(
            metric_id=metric_id,
            table=table,
            nearby_text=nearby_text,
            all_keywords=keywords,
            specific_by_metric=specific,
            exclusions=exclusions,
        )
        results.append((metric_id, score))

    return sorted(results, key=lambda x: x[1], reverse=True)
