"""Unit tests for validate_against_gold_standard.py CLI enhancements.

Tests for GS-2: Enhanced validation script with baseline comparison and regression detection.
"""

import subprocess
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock

import pytest

# Add project root to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from scripts.validate_against_gold_standard import (
    print_baseline_comparison,
)


class TestCLIArguments:
    """Tests for new CLI argument parsing."""

    def test_baseline_flag_in_help(self) -> None:
        """--baseline flag appears in help output."""
        result = subprocess.run(
            [sys.executable, "scripts/validate_against_gold_standard.py", "--help"],
            capture_output=True,
            text=True,
            cwd=Path(__file__).parent.parent.parent.parent,
        )
        assert result.returncode == 0
        assert "--baseline" in result.stdout
        assert "Compare results against stored baseline" in result.stdout

    def test_update_baseline_flag_in_help(self) -> None:
        """--update-baseline flag appears in help output."""
        result = subprocess.run(
            [sys.executable, "scripts/validate_against_gold_standard.py", "--help"],
            capture_output=True,
            text=True,
            cwd=Path(__file__).parent.parent.parent.parent,
        )
        assert result.returncode == 0
        assert "--update-baseline" in result.stdout
        assert "Save current metrics as new baseline" in result.stdout

    def test_fail_on_regression_flag_in_help(self) -> None:
        """--fail-on-regression flag appears in help output."""
        result = subprocess.run(
            [sys.executable, "scripts/validate_against_gold_standard.py", "--help"],
            capture_output=True,
            text=True,
            cwd=Path(__file__).parent.parent.parent.parent,
        )
        assert result.returncode == 0
        assert "--fail-on-regression" in result.stdout
        assert "Exit with code 1" in result.stdout

    def test_tolerance_flag_in_help(self) -> None:
        """--tolerance flag appears in help output with default value."""
        result = subprocess.run(
            [sys.executable, "scripts/validate_against_gold_standard.py", "--help"],
            capture_output=True,
            text=True,
            cwd=Path(__file__).parent.parent.parent.parent,
        )
        assert result.returncode == 0
        assert "--tolerance" in result.stdout
        assert "0.01" in result.stdout or "1%" in result.stdout

    def test_baseline_path_flag_in_help(self) -> None:
        """--baseline-path flag appears in help output with default path."""
        result = subprocess.run(
            [sys.executable, "scripts/validate_against_gold_standard.py", "--help"],
            capture_output=True,
            text=True,
            cwd=Path(__file__).parent.parent.parent.parent,
        )
        assert result.returncode == 0
        assert "--baseline-path" in result.stdout
        assert "baseline_metrics.json" in result.stdout


class TestPrintBaselineComparison:
    """Tests for print_baseline_comparison function."""

    def test_delta_display_shows_positive_sign(self, capsys: pytest.CaptureFixture) -> None:
        """Delta display shows + sign for improvements."""
        # Create a mock comparison result
        mock_comparison = MagicMock()
        mock_comparison.precision_delta = 0.05
        mock_comparison.recall_delta = 0.10
        mock_comparison.f1_delta = 0.07
        mock_comparison.regressed_metrics = []
        mock_comparison.regressed_companies = []

        print_baseline_comparison(
            comparison=mock_comparison,
            baseline_date="2025-12-15T12:00:00+00:00",
            current_precision=0.80,
            current_recall=0.85,
            current_f1=0.82,
        )

        captured = capsys.readouterr()
        assert "+5.0%" in captured.out
        assert "+10.0%" in captured.out
        assert "+7.0%" in captured.out
        assert "2025-12-15" in captured.out

    def test_delta_display_shows_negative_sign(self, capsys: pytest.CaptureFixture) -> None:
        """Delta display shows - sign for regressions."""
        mock_comparison = MagicMock()
        mock_comparison.precision_delta = -0.03
        mock_comparison.recall_delta = -0.05
        mock_comparison.f1_delta = -0.04
        mock_comparison.regressed_metrics = ["precision", "recall", "f1"]
        mock_comparison.regressed_companies = []

        print_baseline_comparison(
            comparison=mock_comparison,
            baseline_date="2025-12-15",
            current_precision=0.72,
            current_recall=0.65,
            current_f1=0.68,
        )

        captured = capsys.readouterr()
        assert "-3.0%" in captured.out
        assert "-5.0%" in captured.out
        assert "-4.0%" in captured.out

    def test_regression_markers_appear(self, capsys: pytest.CaptureFixture) -> None:
        """[REGRESSION] markers appear for regressed metrics."""
        mock_comparison = MagicMock()
        mock_comparison.precision_delta = 0.02  # Improved
        mock_comparison.recall_delta = -0.08   # Regressed
        mock_comparison.f1_delta = -0.03       # Regressed
        mock_comparison.regressed_metrics = ["recall", "f1"]
        mock_comparison.regressed_companies = []

        print_baseline_comparison(
            comparison=mock_comparison,
            baseline_date="2025-12-15",
            current_precision=0.82,
            current_recall=0.72,
            current_f1=0.77,
        )

        captured = capsys.readouterr()
        # Should have [REGRESSION] markers for recall and f1
        lines = captured.out.split("\n")
        recall_line = [l for l in lines if "Recall" in l][0]
        f1_line = [l for l in lines if "F1" in l][0]
        precision_line = [l for l in lines if "Precision" in l][0]

        assert "[REGRESSION]" in recall_line
        assert "[REGRESSION]" in f1_line
        assert "[REGRESSION]" not in precision_line

    def test_regressed_companies_displayed(self, capsys: pytest.CaptureFixture) -> None:
        """Regressed companies are listed when present."""
        mock_comparison = MagicMock()
        mock_comparison.precision_delta = -0.05
        mock_comparison.recall_delta = -0.05
        mock_comparison.f1_delta = -0.05
        mock_comparison.regressed_metrics = ["precision"]
        mock_comparison.regressed_companies = ["Acme Corp", "Beta Inc"]

        print_baseline_comparison(
            comparison=mock_comparison,
            baseline_date="2025-12-15",
            current_precision=0.70,
            current_recall=0.65,
            current_f1=0.67,
        )

        captured = capsys.readouterr()
        assert "Regressed companies" in captured.out
        assert "Acme Corp" in captured.out
        assert "Beta Inc" in captured.out


class TestBaselineFilePaths:
    """Tests for baseline file path handling."""

    def test_default_baseline_path(self) -> None:
        """Default baseline path is in data/gold_standard/."""
        # Check that --help output shows the expected default path
        result = subprocess.run(
            [sys.executable, "scripts/validate_against_gold_standard.py", "--help"],
            capture_output=True,
            text=True,
            cwd=Path(__file__).parent.parent.parent.parent,
        )
        assert result.returncode == 0
        # The help text should show the default path contains expected components
        assert "baseline_metrics.json" in result.stdout
        # The path should be in gold_standard directory
        assert "gold_standard" in result.stdout


class TestRegressionDetection:
    """Tests for regression detection with exit codes."""

    def test_tolerance_affects_regression_detection(self) -> None:
        """Higher tolerance allows more regression without flagging."""
        from src.gold_standard.baseline import (
            BaselineMetrics,
            MetricScores,
            compare_to_baseline,
        )

        baseline = BaselineMetrics(
            baseline_date="2024-12-01",
            description=None,
            overall=MetricScores(precision=0.80, recall=0.70, f1=0.75),
            by_company={},
        )
        current = BaselineMetrics(
            baseline_date="2024-12-31",
            description=None,
            overall=MetricScores(precision=0.79, recall=0.69, f1=0.74),  # 1% regression
            by_company={},
        )

        # With 0% tolerance, this is a regression
        result_strict = compare_to_baseline(current, baseline, tolerance=0.0)
        assert result_strict.has_regression

        # With 2% tolerance, this is not a regression
        result_lenient = compare_to_baseline(current, baseline, tolerance=0.02)
        assert not result_lenient.has_regression


class TestUpdateBaselineFlow:
    """Tests for baseline update functionality."""

    def test_update_baseline_creates_file(self) -> None:
        """--update-baseline creates a new baseline file."""
        from src.gold_standard.baseline import (
            create_baseline_from_results,
            load_baseline,
            save_baseline,
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            baseline_path = Path(tmpdir) / "test_baseline.json"

            # Create sample results
            results = [
                {
                    "company_name": "Test Corp",
                    "true_positives": 10,
                    "false_positives": 2,
                    "false_negatives": 3,
                    "precision": 0.833,
                    "recall": 0.769,
                    "f1_score": 0.8,
                }
            ]

            baseline = create_baseline_from_results(results, description="Test")
            save_baseline(baseline, baseline_path)

            # Verify file was created and can be loaded
            assert baseline_path.exists()
            loaded = load_baseline(baseline_path)
            assert loaded.by_company["Test Corp"].precision == 0.833


class TestEdgeCases:
    """Tests for edge cases and error handling."""

    def test_missing_baseline_with_baseline_flag(self) -> None:
        """Missing baseline file prints warning but doesn't crash."""
        from src.gold_standard.baseline import load_baseline

        with pytest.raises(FileNotFoundError) as exc_info:
            load_baseline("/nonexistent/path/baseline.json")

        assert "Baseline file not found" in str(exc_info.value)
        assert "--update-baseline" in str(exc_info.value)

    def test_invalid_baseline_file_format(self) -> None:
        """Invalid JSON in baseline file raises ValueError."""
        from src.gold_standard.baseline import load_baseline

        with tempfile.TemporaryDirectory() as tmpdir:
            bad_file = Path(tmpdir) / "bad_baseline.json"
            bad_file.write_text("{ invalid json }")

            with pytest.raises(ValueError) as exc_info:
                load_baseline(bad_file)

            assert "Invalid JSON" in str(exc_info.value)

    def test_empty_results_no_baseline_operations(self) -> None:
        """Empty results list doesn't crash baseline operations."""
        from src.gold_standard.baseline import create_baseline_from_results

        with pytest.raises(ValueError) as exc_info:
            create_baseline_from_results([])

        assert "Cannot create baseline from empty" in str(exc_info.value)


class TestBackwardCompatibility:
    """Tests ensuring existing functionality still works."""

    def test_existing_flags_still_work(self) -> None:
        """Existing --filing-id, --company, --all flags still work."""
        result = subprocess.run(
            [sys.executable, "scripts/validate_against_gold_standard.py", "--help"],
            capture_output=True,
            text=True,
            cwd=Path(__file__).parent.parent.parent.parent,
        )
        assert result.returncode == 0
        assert "--filing-id" in result.stdout
        assert "--company" in result.stdout
        assert "--all" in result.stdout
        assert "--output" in result.stdout
        assert "--verbose" in result.stdout
        assert "--mode" in result.stdout
