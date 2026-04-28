"""
Unit tests for score_ocr_table in
src/extraction_v2/chart/table_metric_classifier.py.

Mirrors test_chart_metric_classifier.py style and conventions.
"""

from __future__ import annotations

from src.extraction_v2.chart.table_metric_classifier import (
    _SUPPORTED_METRICS,
    score_ocr_table,
)
from src.extraction_v2.models import Cell, Table

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_cohort_revenue_table() -> Table:
    """Synthetic cohort-revenue table whose headers match cm_revenue_by_cohort patterns.

    Layout (2 cols x 3 rows):
        Cohort Year | Revenue by Cohort
        2022        | $1.2B
        2023        | $1.5B

    Column header "Revenue by Cohort" matches the primary pattern
    ``\\brevenue\\s+by\\s+cohort\\b``.  The nearby_text caption "Cohort Revenue
    by Year" additionally matches ``\\bcohort\\s+revenue\\b`` for the title
    surface bonus.
    """
    cells = [
        # Header row
        Cell(row=0, col=0, text="Cohort Year", is_header=True),
        Cell(row=0, col=1, text="Revenue by Cohort", is_header=True),
        # Data row 1
        Cell(row=1, col=0, text="2022", is_stub=True),
        Cell(
            row=1,
            col=1,
            text="$1.2B",
            header_path=["Revenue by Cohort"],
            stub_path=["2022"],
        ),
        # Data row 2
        Cell(row=2, col=0, text="2023", is_stub=True),
        Cell(
            row=2,
            col=1,
            text="$1.5B",
            header_path=["Revenue by Cohort"],
            stub_path=["2023"],
        ),
    ]
    return Table(
        row_count=3,
        col_count=2,
        header_rows=1,
        stub_cols=1,
        cells=cells,
    )


def _make_cohort_balance_table() -> Table:
    """Synthetic cohort-balance table whose header matches cm_balance_by_cohort patterns.

    Layout:
        Cohort Year | Cumulative Net Deposits by Cohort
        2021        | $500M
        2022        | $700M

    Column header "Cumulative Net Deposits by Cohort" matches the primary
    pattern ``\\bcumulative\\s+net\\s+deposits?\\s+by\\s+(?:annual\\s+)?cohort\\b``.
    The nearby_text "Cumulative Net Deposits by Annual Cohort" additionally
    contributes the title-surface score.
    """
    cells = [
        Cell(row=0, col=0, text="Cohort Year", is_header=True),
        Cell(row=0, col=1, text="Cumulative Net Deposits by Cohort", is_header=True),
        Cell(row=1, col=0, text="2021", is_stub=True),
        Cell(
            row=1,
            col=1,
            text="$500M",
            header_path=["Cumulative Net Deposits by Cohort"],
            stub_path=["2021"],
        ),
        Cell(row=2, col=0, text="2022", is_stub=True),
        Cell(
            row=2,
            col=1,
            text="$700M",
            header_path=["Cumulative Net Deposits by Cohort"],
            stub_path=["2022"],
        ),
    ]
    return Table(
        row_count=3,
        col_count=2,
        header_rows=1,
        stub_cols=1,
        cells=cells,
    )


def _make_generic_pl_table() -> Table:
    """Generic quarterly P&L summary — no cohort signals at all.

    Layout:
        Quarter | Net Income | Operating Expense
        Q1 2024 | $10M       | $8M
        Q2 2024 | $12M       | $9M
    """
    cells = [
        Cell(row=0, col=0, text="Quarter", is_header=True),
        Cell(row=0, col=1, text="Net Income", is_header=True),
        Cell(row=0, col=2, text="Operating Expense", is_header=True),
        Cell(row=1, col=0, text="Q1 2024", is_stub=True),
        Cell(
            row=1,
            col=1,
            text="$10M",
            header_path=["Net Income"],
            stub_path=["Q1 2024"],
        ),
        Cell(
            row=1,
            col=2,
            text="$8M",
            header_path=["Operating Expense"],
            stub_path=["Q1 2024"],
        ),
        Cell(row=2, col=0, text="Q2 2024", is_stub=True),
        Cell(
            row=2,
            col=1,
            text="$12M",
            header_path=["Net Income"],
            stub_path=["Q2 2024"],
        ),
        Cell(
            row=2,
            col=2,
            text="$9M",
            header_path=["Operating Expense"],
            stub_path=["Q2 2024"],
        ),
    ]
    return Table(row_count=3, col_count=3, header_rows=1, stub_cols=1, cells=cells)


# ---------------------------------------------------------------------------
# Positive cases
# ---------------------------------------------------------------------------


class TestPositiveCohortRevenue:
    """score_ocr_table must detect cm_revenue_by_cohort on a cohort revenue table."""

    def test_cm_revenue_by_cohort_scores_above_threshold(self) -> None:
        """Cohort revenue table: cm_revenue_by_cohort must score >= 0.5."""
        table = _make_cohort_revenue_table()
        results = score_ocr_table(table, nearby_text="Cohort Revenue by Year")

        result_map = dict(results)
        assert "cm_revenue_by_cohort" in result_map, (
            f"cm_revenue_by_cohort not in results. Candidates: {results}"
        )
        score = result_map["cm_revenue_by_cohort"]
        assert score >= 0.5, f"Expected cm_revenue_by_cohort score >= 0.5, got {score:.3f}"

    def test_nearby_text_boosts_score(self) -> None:
        """Adding a cohort-revenue caption in nearby_text should not lower the score."""
        table = _make_cohort_revenue_table()
        results_with_caption = score_ocr_table(
            table, nearby_text="Cohort Revenue by Acquisition Year"
        )
        results_no_caption = score_ocr_table(table, nearby_text="")

        score_with = dict(results_with_caption).get("cm_revenue_by_cohort", 0.0)
        score_without = dict(results_no_caption).get("cm_revenue_by_cohort", 0.0)
        assert score_with >= score_without, (
            f"Caption should not lower score: with={score_with:.3f} without={score_without:.3f}"
        )


class TestPositiveCohortBalance:
    """score_ocr_table must detect cm_balance_by_cohort on a deposits/balance table."""

    def test_cm_balance_by_cohort_scores_above_threshold(self) -> None:
        """Cohort balance table with 'Cumulative Net Deposits' header: cm_balance_by_cohort >= 0.5."""
        table = _make_cohort_balance_table()
        results = score_ocr_table(table, nearby_text="Cumulative Net Deposits by Annual Cohort")

        result_map = dict(results)
        assert "cm_balance_by_cohort" in result_map, (
            f"cm_balance_by_cohort not in results. Candidates: {results}"
        )
        score = result_map["cm_balance_by_cohort"]
        assert score >= 0.5, f"Expected cm_balance_by_cohort score >= 0.5, got {score:.3f}"


# ---------------------------------------------------------------------------
# Negative case
# ---------------------------------------------------------------------------


class TestNegativeGenericPL:
    """Generic P&L table must NOT match any of the 5 supported cohort metrics."""

    def test_no_supported_metric_scores_above_threshold(self) -> None:
        """Quarterly P&L table: none of the 5 supported metrics should score >= 0.5."""
        table = _make_generic_pl_table()
        results = score_ocr_table(table, nearby_text="Quarterly P&L Summary")

        above_threshold = [(metric_id, score) for metric_id, score in results if score >= 0.5]
        assert not above_threshold, (
            f"Expected no metrics >= 0.5 for generic P&L table, got: {above_threshold}"
        )


# ---------------------------------------------------------------------------
# Output structure
# ---------------------------------------------------------------------------


class TestOutputStructure:
    """Return type and ordering invariants."""

    def test_returns_list_of_tuples(self) -> None:
        """score_ocr_table must return a list of (str, float) tuples."""
        table = _make_cohort_revenue_table()
        results = score_ocr_table(table)

        assert isinstance(results, list)
        for item in results:
            assert isinstance(item, tuple) and len(item) == 2
            metric_id, score = item
            assert isinstance(metric_id, str)
            assert isinstance(score, float)

    def test_all_supported_metrics_present(self) -> None:
        """All 5 supported metrics must appear in the output (score may be 0.0)."""
        table = _make_cohort_revenue_table()
        results = score_ocr_table(table)

        returned_ids = {metric_id for metric_id, _ in results}
        for expected in _SUPPORTED_METRICS:
            assert expected in returned_ids, (
                f"Metric {expected!r} missing from score_ocr_table output"
            )

    def test_sorted_by_score_descending(self) -> None:
        """Results must be sorted by score descending — mirrors test_chart_metric_classifier."""
        table = _make_cohort_revenue_table()
        results = score_ocr_table(table, nearby_text="Cohort Revenue by Year")

        scores = [s for _, s in results]
        assert scores == sorted(scores, reverse=True), f"Results not sorted descending: {results}"

    def test_scores_bounded_zero_to_one(self) -> None:
        """Every score must be in [0.0, 1.0]."""
        table = _make_cohort_revenue_table()
        results = score_ocr_table(table)

        for metric_id, score in results:
            assert 0.0 <= score <= 1.0, f"Score for {metric_id!r} out of [0, 1]: {score}"

    def test_empty_table_returns_all_zero(self) -> None:
        """An empty Table (no cells) should return all metrics with score 0.0."""
        table = Table()
        results = score_ocr_table(table, nearby_text="")

        for metric_id, score in results:
            assert score == 0.0, f"Expected 0.0 for empty table, got {metric_id}={score}"


# ---------------------------------------------------------------------------
# Gate behavior (chart_presence_min_score = 0.5 default)
# ---------------------------------------------------------------------------


class TestGateBehavior:
    """Verify that sub-threshold candidates are present in raw output but
    would be filtered by ChartFactBridgeStage's chart_presence_min_score gate."""

    def test_below_threshold_candidates_present_in_raw_output(self) -> None:
        """score_ocr_table returns ALL 5 metrics; the consumer applies the gate.

        This test asserts that a metric scoring below 0.5 is still present
        in the list returned by score_ocr_table, which is how the caller
        (ChartFactBridgeStage) can implement its own configurable gate.
        """
        table = _make_generic_pl_table()
        results = score_ocr_table(table)

        # All 5 supported metrics must be present regardless of score
        returned_ids = {metric_id for metric_id, _ in results}
        assert returned_ids == set(_SUPPORTED_METRICS)

        # For this table all metrics must be below 0.5 (generic P&L, no cohort signals)
        below_threshold = [(metric_id, score) for metric_id, score in results if score < 0.5]
        assert len(below_threshold) == len(_SUPPORTED_METRICS), (
            f"Expected all {len(_SUPPORTED_METRICS)} metrics below 0.5 for a generic P&L "
            f"table, but these were above: "
            f"{[(m, s) for m, s in results if s >= 0.5]}"
        )
