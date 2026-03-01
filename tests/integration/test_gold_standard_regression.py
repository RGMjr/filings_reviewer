"""
Gold Standard Regression Tests (GS-4).

pytest integration tests that validate metrics against the gold standard baseline
and fail CI when regressions occur.

Usage:
    # Run gold standard tests only
    pytest -m gold_standard -v

    # Run with custom tolerance (default: 1%)
    pytest -m gold_standard --gold-standard-tolerance=0.02 -v

    # Skip gold standard tests
    pytest -m "not gold_standard"

These tests compare current extraction performance against a saved baseline.
When precision, recall, or F1 drops below the baseline threshold, tests fail
with clear diagnostic messages.

Prerequisites:
    - Gold standard data must exist in data/gold_standard/
    - Baseline file must exist at data/gold_standard/baseline.json
      (create with: python scripts/validate_against_gold_standard.py --all --update-baseline)
    - Database must contain gold standard filings
"""

import logging
from pathlib import Path
from typing import Any

import pytest

from src.gold_standard.baseline import (
    BaselineMetrics,
    ComparisonResult,
    MetricScores,
    compare_to_baseline,
    create_baseline_from_results,
    load_baseline,
)

logger = logging.getLogger(__name__)


# =============================================================================
# Paths
# =============================================================================

GOLD_STANDARD_CSV_PATH = Path("data/gold_standard/golden_set_251218.csv")
BASELINE_PATH = Path("data/gold_standard/baseline.json")


# =============================================================================
# Helper Functions
# =============================================================================


def run_validation(db, gold_standard_path: Path) -> list[dict[str, Any]]:
    """
    Run gold standard validation and return results.

    This mirrors the logic in scripts/validate_against_gold_standard.py
    but returns structured data for test assertions.
    """
    import sys

    sys.path.insert(0, str(Path(__file__).parent.parent.parent))

    from scripts.validate_against_gold_standard import (
        get_entries_for_company,
        load_gold_standard,
        validate_filing,
    )

    # Load gold standard entries
    gold_entries = load_gold_standard(gold_standard_path)

    # Get unique companies
    companies = sorted(set(e.company for e in gold_entries))

    results = []
    for company in companies:
        company_entries = get_entries_for_company(gold_entries, company)

        # Find filing in database
        query = """
            SELECT f.filing_id, c.company_name
            FROM filings f
            JOIN companies c ON f.company_id = c.company_id
            WHERE LOWER(c.company_name) = LOWER(%(company)s)
            LIMIT 1
        """
        filing_rows = db.query(query, {"company": company})
        filing_id = filing_rows[0]["filing_id"] if filing_rows else None

        result = validate_filing(db, filing_id, company, company_entries)

        results.append(
            {
                "company_name": result.company_name,
                "filing_id": result.filing_id,
                "gold_standard_count": result.gold_standard_count,
                "candidate_count": result.candidate_count,
                "true_positives": result.true_positives,
                "false_positives": result.false_positives,
                "false_negatives": result.false_negatives,
                "precision": result.precision,
                "recall": result.recall,
                "f1_score": result.f1_score,
            }
        )

    return results


def results_to_baseline_metrics(results: list[dict[str, Any]]) -> BaselineMetrics:
    """Convert validation results to BaselineMetrics for comparison."""
    return create_baseline_from_results(results)


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture(scope="module")
def gold_standard_csv_path():
    """Return path to gold standard CSV file."""
    return GOLD_STANDARD_CSV_PATH


@pytest.fixture(scope="module")
def validation_results(test_db_adapter, gold_standard_csv_path):
    """
    Run validation and cache results for the module.

    This is module-scoped to avoid running validation multiple times.
    """
    if not gold_standard_csv_path.exists():
        pytest.skip(f"Gold standard CSV not found: {gold_standard_csv_path}")

    return run_validation(test_db_adapter, gold_standard_csv_path)


@pytest.fixture(scope="module")
def current_metrics(validation_results) -> BaselineMetrics:
    """Convert validation results to BaselineMetrics."""
    if not validation_results:
        pytest.skip("No validation results available")

    return results_to_baseline_metrics(validation_results)


@pytest.fixture(scope="module")
def comparison_result(
    current_metrics, baseline_metrics, gold_standard_tolerance
) -> ComparisonResult | None:
    """
    Compare current metrics to baseline.

    Returns None if baseline doesn't exist.
    """
    if baseline_metrics is None:
        return None

    return compare_to_baseline(
        current=current_metrics,
        baseline=baseline_metrics,
        tolerance=gold_standard_tolerance,
    )


# =============================================================================
# Test Classes
# =============================================================================


@pytest.mark.gold_standard
class TestGoldStandardRegression:
    """
    Regression tests comparing current metrics against baseline.

    These tests fail if precision, recall, or F1 drops below the baseline
    threshold (with configurable tolerance via --gold-standard-tolerance).
    """

    def test_baseline_exists(self, baseline_metrics, baseline_path):
        """Verify baseline file exists and can be loaded."""
        if baseline_metrics is None:
            pytest.skip(
                f"Baseline file not found: {baseline_path}. "
                f"Create with: python3 scripts/validate_against_gold_standard.py --all --update-baseline"
            )

        assert baseline_metrics is not None, "Baseline should be loaded"
        assert baseline_metrics.overall is not None, "Baseline should have overall metrics"
        assert len(baseline_metrics.by_company) > 0, "Baseline should have per-company metrics"

    def test_overall_precision_above_baseline(
        self,
        current_metrics,
        baseline_metrics,
        gold_standard_tolerance,
        baseline_path,
    ):
        """Fail if precision drops below baseline threshold."""
        if baseline_metrics is None:
            pytest.skip(
                f"Baseline file not found: {baseline_path}. "
                f"Create with: python3 scripts/validate_against_gold_standard.py --all --update-baseline"
            )

        delta = current_metrics.overall.precision - baseline_metrics.overall.precision
        threshold = -gold_standard_tolerance

        assert delta >= threshold, (
            f"PRECISION REGRESSED: {current_metrics.overall.precision:.1%} "
            f"(baseline: {baseline_metrics.overall.precision:.1%}, "
            f"delta: {delta:+.1%}, allowed: {threshold:+.1%})"
        )

        if delta > 0:
            logger.info(
                f"Precision improved: {current_metrics.overall.precision:.1%} "
                f"(+{delta:.1%} vs baseline)"
            )

    def test_overall_recall_above_baseline(
        self,
        current_metrics,
        baseline_metrics,
        gold_standard_tolerance,
        baseline_path,
    ):
        """Fail if recall drops below baseline threshold."""
        if baseline_metrics is None:
            pytest.skip(
                f"Baseline file not found: {baseline_path}. "
                f"Create with: python3 scripts/validate_against_gold_standard.py --all --update-baseline"
            )

        delta = current_metrics.overall.recall - baseline_metrics.overall.recall
        threshold = -gold_standard_tolerance

        assert delta >= threshold, (
            f"RECALL REGRESSED: {current_metrics.overall.recall:.1%} "
            f"(baseline: {baseline_metrics.overall.recall:.1%}, "
            f"delta: {delta:+.1%}, allowed: {threshold:+.1%})"
        )

        if delta > 0:
            logger.info(
                f"Recall improved: {current_metrics.overall.recall:.1%} (+{delta:.1%} vs baseline)"
            )

    def test_overall_f1_above_baseline(
        self,
        current_metrics,
        baseline_metrics,
        gold_standard_tolerance,
        baseline_path,
    ):
        """Fail if F1 drops below baseline threshold."""
        if baseline_metrics is None:
            pytest.skip(
                f"Baseline file not found: {baseline_path}. "
                f"Create with: python3 scripts/validate_against_gold_standard.py --all --update-baseline"
            )

        delta = current_metrics.overall.f1 - baseline_metrics.overall.f1
        threshold = -gold_standard_tolerance

        assert delta >= threshold, (
            f"F1 REGRESSED: {current_metrics.overall.f1:.1%} "
            f"(baseline: {baseline_metrics.overall.f1:.1%}, "
            f"delta: {delta:+.1%}, allowed: {threshold:+.1%})"
        )

        if delta > 0:
            logger.info(f"F1 improved: {current_metrics.overall.f1:.1%} (+{delta:.1%} vs baseline)")

    def test_no_company_recall_regressions(
        self,
        current_metrics,
        baseline_metrics,
        gold_standard_tolerance,
        baseline_path,
    ):
        """Fail if any company's recall dropped significantly."""
        if baseline_metrics is None:
            pytest.skip(
                f"Baseline file not found: {baseline_path}. "
                f"Create with: python3 scripts/validate_against_gold_standard.py --all --update-baseline"
            )

        regressed_companies = []

        for company, baseline_scores in baseline_metrics.by_company.items():
            if company not in current_metrics.by_company:
                # Company missing in current run - might be data change
                logger.warning(f"Company '{company}' in baseline but not in current run")
                continue

            current_scores = current_metrics.by_company[company]
            recall_delta = current_scores.recall - baseline_scores.recall

            if recall_delta < -gold_standard_tolerance:
                regressed_companies.append(
                    {
                        "company": company,
                        "current": current_scores.recall,
                        "baseline": baseline_scores.recall,
                        "delta": recall_delta,
                    }
                )

        if regressed_companies:
            details = "\n".join(
                f"  - {r['company']}: {r['current']:.1%} "
                f"(was {r['baseline']:.1%}, delta: {r['delta']:+.1%})"
                for r in regressed_companies
            )
            pytest.fail(f"RECALL REGRESSIONS in {len(regressed_companies)} companies:\n{details}")

    def test_aggregate_company_metrics(
        self,
        current_metrics,
        baseline_metrics,
        comparison_result,
        baseline_path,
    ):
        """Verify aggregate comparison result reports no regressions."""
        if baseline_metrics is None:
            pytest.skip(
                f"Baseline file not found: {baseline_path}. "
                f"Create with: python3 scripts/validate_against_gold_standard.py --all --update-baseline"
            )

        if comparison_result is None:
            pytest.skip("No comparison result available")

        assert not comparison_result.has_regression, (
            f"REGRESSION DETECTED:\n"
            f"  {comparison_result.summary()}\n"
            f"  Regressed metrics: {comparison_result.regressed_metrics}\n"
            f"  Regressed companies: {comparison_result.regressed_companies}"
        )


@pytest.mark.gold_standard
class TestGoldStandardEdgeCases:
    """Edge case tests for gold standard validation."""

    def test_handles_missing_baseline_gracefully(self, baseline_path):
        """Verify graceful handling when baseline doesn't exist."""
        nonexistent_path = Path("/nonexistent/baseline.json")

        with pytest.raises(FileNotFoundError) as exc_info:
            load_baseline(nonexistent_path)

        assert "Baseline file not found" in str(exc_info.value)
        assert "Run validation with --update-baseline" in str(exc_info.value)

    def test_handles_empty_validation_results(self):
        """Verify graceful handling of empty validation results."""
        # Empty results should raise ValueError
        with pytest.raises(ValueError) as exc_info:
            create_baseline_from_results([])

        assert "Cannot create baseline from empty results" in str(exc_info.value)

    def test_tolerance_applied_correctly(self):
        """Verify tolerance is applied correctly in comparisons."""
        # Create test metrics
        baseline = BaselineMetrics(
            baseline_date="2024-01-01T00:00:00Z",
            description="test baseline",
            overall=MetricScores(precision=0.80, recall=0.70, f1=0.747),
            by_company={},
        )

        # Current metrics slightly below baseline
        current = BaselineMetrics(
            baseline_date="2024-01-02T00:00:00Z",
            description="test current",
            overall=MetricScores(precision=0.795, recall=0.695, f1=0.742),
            by_company={},
        )

        # With 1% tolerance, small drops should not count as regressions
        result = compare_to_baseline(current, baseline, tolerance=0.01)
        assert not result.has_regression, (
            f"0.5% drop should not trigger regression with 1% tolerance. "
            f"Regressed metrics: {result.regressed_metrics}"
        )

        # With 0.1% tolerance, same drops should be flagged
        result_strict = compare_to_baseline(current, baseline, tolerance=0.001)
        assert result_strict.has_regression, (
            "0.5% drop should trigger regression with 0.1% tolerance"
        )


@pytest.mark.gold_standard
class TestGoldStandardMetrics:
    """Tests for gold standard metrics reporting."""

    def test_current_metrics_structure(self, current_metrics):
        """Verify current metrics have expected structure."""
        assert current_metrics is not None, "Current metrics should exist"
        assert current_metrics.overall is not None, "Should have overall metrics"

        # Verify overall metrics are valid
        assert 0.0 <= current_metrics.overall.precision <= 1.0
        assert 0.0 <= current_metrics.overall.recall <= 1.0
        assert 0.0 <= current_metrics.overall.f1 <= 1.0

    def test_per_company_breakdown(self, current_metrics):
        """Verify per-company metrics are available."""
        if not current_metrics.by_company:
            pytest.skip("No per-company metrics available")

        for company, scores in current_metrics.by_company.items():
            assert 0.0 <= scores.precision <= 1.0, f"Invalid precision for {company}"
            assert 0.0 <= scores.recall <= 1.0, f"Invalid recall for {company}"
            assert 0.0 <= scores.f1 <= 1.0, f"Invalid F1 for {company}"

    def test_validation_covers_all_gold_standard_companies(
        self, validation_results, gold_standard_csv_path
    ):
        """Verify all gold standard companies are validated."""
        if not gold_standard_csv_path.exists():
            pytest.skip(f"Gold standard CSV not found: {gold_standard_csv_path}")

        from scripts.validate_against_gold_standard import load_gold_standard

        gold_entries = load_gold_standard(gold_standard_csv_path)
        expected_companies = set(e.company for e in gold_entries)
        validated_companies = set(r["company_name"] for r in validation_results)

        missing = expected_companies - validated_companies
        assert not missing, (
            f"Missing validation for companies: {missing}. "
            f"Ensure these companies exist in the database."
        )
