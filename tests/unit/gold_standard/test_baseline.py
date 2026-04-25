"""Unit tests for baseline metrics module."""

import json
import tempfile
from pathlib import Path

import pytest

from src.gold_standard.baseline import (
    BaselineMetrics,
    ComparisonResult,
    MetricScores,
    compare_to_baseline,
    create_baseline_from_results,
    load_baseline,
    save_baseline,
)


class TestMetricScores:
    """Tests for MetricScores dataclass."""

    def test_valid_scores(self) -> None:
        """MetricScores accepts valid 0.0-1.0 values."""
        scores = MetricScores(precision=0.85, recall=0.92, f1=0.88)
        assert scores.precision == 0.85
        assert scores.recall == 0.92
        assert scores.f1 == 0.88

    def test_perfect_scores(self) -> None:
        """MetricScores accepts 1.0 (perfect) values."""
        scores = MetricScores(precision=1.0, recall=1.0, f1=1.0)
        assert scores.precision == 1.0
        assert scores.recall == 1.0
        assert scores.f1 == 1.0

    def test_zero_scores(self) -> None:
        """MetricScores accepts 0.0 values."""
        scores = MetricScores(precision=0.0, recall=0.0, f1=0.0)
        assert scores.precision == 0.0
        assert scores.recall == 0.0
        assert scores.f1 == 0.0

    def test_integer_scores(self) -> None:
        """MetricScores accepts integer 0 and 1."""
        scores = MetricScores(precision=0, recall=1, f1=0)
        assert scores.precision == 0
        assert scores.recall == 1

    def test_invalid_range_raises_error(self) -> None:
        """MetricScores raises ValueError for out-of-range values."""
        with pytest.raises(ValueError, match="precision must be between 0.0 and 1.0"):
            MetricScores(precision=1.5, recall=0.5, f1=0.5)

    def test_negative_value_raises_error(self) -> None:
        """MetricScores raises ValueError for negative values."""
        with pytest.raises(ValueError, match="recall must be between 0.0 and 1.0"):
            MetricScores(precision=0.5, recall=-0.1, f1=0.5)

    def test_non_numeric_raises_error(self) -> None:
        """MetricScores raises TypeError for non-numeric values."""
        with pytest.raises(TypeError, match="precision must be a number"):
            MetricScores(precision="high", recall=0.5, f1=0.5)  # type: ignore[arg-type]


class TestSerializationRoundTrip:
    """Tests for save/load operations."""

    def test_round_trip_preserves_data(self) -> None:
        """Save then load preserves all data exactly."""
        original = BaselineMetrics(
            baseline_date="2024-12-31T12:00:00+00:00",
            description="Test baseline",
            overall=MetricScores(precision=0.85, recall=0.92, f1=0.88),
            by_company={
                "Acme Corp": MetricScores(precision=0.90, recall=0.85, f1=0.87),
                "Beta Inc": MetricScores(precision=0.80, recall=0.95, f1=0.87),
            },
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "baseline.json"
            save_baseline(original, path)
            loaded = load_baseline(path)

        assert loaded.baseline_date == original.baseline_date
        assert loaded.description == original.description
        assert loaded.overall.precision == original.overall.precision
        assert loaded.overall.recall == original.overall.recall
        assert loaded.overall.f1 == original.overall.f1
        assert len(loaded.by_company) == len(original.by_company)
        assert "Acme Corp" in loaded.by_company
        assert loaded.by_company["Acme Corp"].precision == 0.90

    def test_json_format_human_readable(self) -> None:
        """Saved JSON is properly formatted for human readability."""
        metrics = BaselineMetrics(
            baseline_date="2024-12-31T12:00:00+00:00",
            description="Readable test",
            overall=MetricScores(precision=0.5, recall=0.5, f1=0.5),
            by_company={},
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "baseline.json"
            save_baseline(metrics, path)

            # Read raw JSON to check formatting
            content = path.read_text()
            data = json.loads(content)

            # Should have proper structure
            assert "baseline_date" in data
            assert "description" in data
            assert "overall" in data
            assert "by_company" in data

            # Should be indented (human-readable)
            assert "\n" in content
            assert "  " in content  # Indentation

    def test_special_characters_in_company_names(self) -> None:
        """Company names with special characters are preserved."""
        metrics = BaselineMetrics(
            baseline_date="2024-12-31T12:00:00+00:00",
            description=None,
            overall=MetricScores(precision=0.5, recall=0.5, f1=0.5),
            by_company={
                "O'Brien & Associates, Inc.": MetricScores(precision=0.75, recall=0.80, f1=0.77),
                'Company with "Quotes"': MetricScores(precision=0.65, recall=0.70, f1=0.67),
                "Société Générale": MetricScores(precision=0.85, recall=0.90, f1=0.87),
            },
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "baseline.json"
            save_baseline(metrics, path)
            loaded = load_baseline(path)

        assert "O'Brien & Associates, Inc." in loaded.by_company
        assert 'Company with "Quotes"' in loaded.by_company
        assert "Société Générale" in loaded.by_company
        assert loaded.by_company["Société Générale"].precision == 0.85

    def test_none_description_preserved(self) -> None:
        """None description is preserved through round-trip."""
        metrics = BaselineMetrics(
            baseline_date="2024-12-31T12:00:00+00:00",
            description=None,
            overall=MetricScores(precision=0.5, recall=0.5, f1=0.5),
            by_company={},
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "baseline.json"
            save_baseline(metrics, path)
            loaded = load_baseline(path)

        assert loaded.description is None

    def test_creates_parent_directories(self) -> None:
        """save_baseline creates parent directories if needed."""
        metrics = BaselineMetrics(
            baseline_date="2024-12-31T12:00:00+00:00",
            description="Test",
            overall=MetricScores(precision=0.5, recall=0.5, f1=0.5),
            by_company={},
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "nested" / "deeply" / "baseline.json"
            save_baseline(metrics, path)
            assert path.exists()


class TestComparisonLogic:
    """Tests for compare_to_baseline function."""

    def test_improvement_detected(self) -> None:
        """Positive deltas when current metrics are better."""
        baseline = BaselineMetrics(
            baseline_date="2024-12-01",
            description=None,
            overall=MetricScores(precision=0.70, recall=0.60, f1=0.65),
            by_company={},
        )
        current = BaselineMetrics(
            baseline_date="2024-12-31",
            description=None,
            overall=MetricScores(precision=0.80, recall=0.70, f1=0.75),
            by_company={},
        )

        result = compare_to_baseline(current, baseline)

        assert result.precision_delta == pytest.approx(0.10)
        assert result.recall_delta == pytest.approx(0.10)
        assert result.f1_delta == pytest.approx(0.10)
        assert not result.has_regression
        assert result.regressed_metrics == []

    def test_regression_detected(self) -> None:
        """Fact-level deltas are reported but informational under PR2 (no longer gate)."""
        baseline = BaselineMetrics(
            baseline_date="2024-12-01",
            description=None,
            overall=MetricScores(precision=0.80, recall=0.70, f1=0.75),
            by_company={},
        )
        current = BaselineMetrics(
            baseline_date="2024-12-31",
            description=None,
            overall=MetricScores(precision=0.70, recall=0.60, f1=0.65),
            by_company={},
        )

        result = compare_to_baseline(current, baseline)

        assert result.precision_delta == pytest.approx(-0.10)
        assert result.recall_delta == pytest.approx(-0.10)
        assert result.f1_delta == pytest.approx(-0.10)
        # PR2: fact-level drops are reported as informational, do NOT gate.
        assert not result.has_regression
        assert any("precision" in m for m in result.regressed_metrics)
        assert any("recall" in m for m in result.regressed_metrics)
        assert any("f1" in m for m in result.regressed_metrics)
        # All entries should carry the [informational] label since no Tier-1 fields set.
        assert all("[informational]" in m for m in result.regressed_metrics)

    def test_no_change_zero_delta(self) -> None:
        """Zero deltas when metrics are unchanged."""
        metrics = MetricScores(precision=0.75, recall=0.65, f1=0.70)
        baseline = BaselineMetrics(
            baseline_date="2024-12-01",
            description=None,
            overall=metrics,
            by_company={},
        )
        current = BaselineMetrics(
            baseline_date="2024-12-31",
            description=None,
            overall=MetricScores(precision=0.75, recall=0.65, f1=0.70),
            by_company={},
        )

        result = compare_to_baseline(current, baseline)

        assert result.precision_delta == 0.0
        assert result.recall_delta == 0.0
        assert result.f1_delta == 0.0
        assert not result.has_regression

    def test_tolerance_threshold_respected(self) -> None:
        """Small regression within tolerance doesn't flag as regression."""
        baseline = BaselineMetrics(
            baseline_date="2024-12-01",
            description=None,
            overall=MetricScores(precision=0.80, recall=0.70, f1=0.75),
            by_company={},
        )
        current = BaselineMetrics(
            baseline_date="2024-12-31",
            description=None,
            overall=MetricScores(precision=0.795, recall=0.695, f1=0.745),
            by_company={},
        )

        # With 1% tolerance, 0.5% regression should not flag
        result = compare_to_baseline(current, baseline, tolerance=0.01)

        assert not result.has_regression
        assert result.regressed_metrics == []

    def test_very_small_deltas(self) -> None:
        """Very small deltas (0.001) are detected correctly (informational under PR2)."""
        baseline = BaselineMetrics(
            baseline_date="2024-12-01",
            description=None,
            overall=MetricScores(precision=0.800, recall=0.700, f1=0.750),
            by_company={},
        )
        current = BaselineMetrics(
            baseline_date="2024-12-31",
            description=None,
            overall=MetricScores(precision=0.801, recall=0.701, f1=0.749),
            by_company={},
        )

        result = compare_to_baseline(current, baseline)

        assert result.precision_delta == pytest.approx(0.001)
        assert result.recall_delta == pytest.approx(0.001)
        assert result.f1_delta == pytest.approx(-0.001)
        # F1 dropped — reported as informational, does NOT gate under PR2.
        assert not result.has_regression
        assert any("f1" in m and "[informational]" in m for m in result.regressed_metrics)

    def test_company_regression_detected(self) -> None:
        """Per-company regression is reported but informational under PR2."""
        baseline = BaselineMetrics(
            baseline_date="2024-12-01",
            description=None,
            overall=MetricScores(precision=0.80, recall=0.70, f1=0.75),
            by_company={
                "Good Corp": MetricScores(precision=0.90, recall=0.85, f1=0.87),
                "Bad Corp": MetricScores(precision=0.70, recall=0.60, f1=0.65),
            },
        )
        current = BaselineMetrics(
            baseline_date="2024-12-31",
            description=None,
            overall=MetricScores(precision=0.80, recall=0.70, f1=0.75),  # Same overall
            by_company={
                "Good Corp": MetricScores(precision=0.90, recall=0.85, f1=0.87),  # Same
                "Bad Corp": MetricScores(precision=0.50, recall=0.40, f1=0.45),  # Regressed
            },
        )

        result = compare_to_baseline(current, baseline)

        # Per-company drops are tracked but no longer gate under PR2.
        assert not result.has_regression
        assert "Bad Corp" in result.regressed_companies
        assert "Good Corp" not in result.regressed_companies

    def test_partial_metric_regression(self) -> None:
        """Only some metrics regressing — reported informational under PR2."""
        baseline = BaselineMetrics(
            baseline_date="2024-12-01",
            description=None,
            overall=MetricScores(precision=0.80, recall=0.70, f1=0.75),
            by_company={},
        )
        current = BaselineMetrics(
            baseline_date="2024-12-31",
            description=None,
            overall=MetricScores(precision=0.85, recall=0.60, f1=0.70),  # precision up, recall down
            by_company={},
        )

        result = compare_to_baseline(current, baseline)

        assert result.precision_delta == pytest.approx(0.05)
        assert result.recall_delta == pytest.approx(-0.10)
        assert not result.has_regression
        assert any("recall" in m for m in result.regressed_metrics)
        assert not any("precision" in m for m in result.regressed_metrics)


class TestErrorHandling:
    """Tests for error conditions."""

    def test_missing_file_raises_filenotfounderror(self) -> None:
        """load_baseline raises FileNotFoundError for missing file."""
        with pytest.raises(FileNotFoundError, match="Baseline file not found"):
            load_baseline("/nonexistent/path/baseline.json")

    def test_invalid_json_raises_valueerror(self) -> None:
        """load_baseline raises ValueError for invalid JSON."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "bad.json"
            path.write_text("not valid json {{{")

            with pytest.raises(ValueError, match="Invalid JSON"):
                load_baseline(path)

    def test_missing_required_field_raises_valueerror(self) -> None:
        """load_baseline raises ValueError for missing required fields."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "incomplete.json"
            path.write_text(json.dumps({"baseline_date": "2024-12-31"}))

            with pytest.raises(ValueError, match="Missing required field: overall"):
                load_baseline(path)

    def test_missing_metric_field_raises_valueerror(self) -> None:
        """load_baseline raises ValueError when metric fields are missing."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "bad_metrics.json"
            path.write_text(
                json.dumps(
                    {
                        "baseline_date": "2024-12-31",
                        "overall": {"precision": 0.5},  # Missing recall and f1
                        "by_company": {},
                    }
                )
            )

            with pytest.raises(ValueError, match="Missing field in 'overall'"):
                load_baseline(path)

    def test_non_object_json_raises_valueerror(self) -> None:
        """load_baseline raises ValueError for non-object JSON."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "array.json"
            path.write_text("[1, 2, 3]")

            with pytest.raises(ValueError, match="must contain a JSON object"):
                load_baseline(path)


class TestCreateBaselineFromResults:
    """Tests for create_baseline_from_results helper."""

    def test_creates_baseline_from_results(self) -> None:
        """Creates valid baseline from validation results."""
        results = [
            {
                "company_name": "Acme Corp",
                "true_positives": 10,
                "false_positives": 2,
                "false_negatives": 3,
                "precision": 0.833,
                "recall": 0.769,
                "f1_score": 0.8,
            },
            {
                "company_name": "Beta Inc",
                "true_positives": 8,
                "false_positives": 4,
                "false_negatives": 2,
                "precision": 0.667,
                "recall": 0.8,
                "f1_score": 0.727,
            },
        ]

        baseline = create_baseline_from_results(results, description="Test run")

        assert baseline.description == "Test run"
        assert baseline.baseline_date  # Should be set
        assert len(baseline.by_company) == 2
        assert "Acme Corp" in baseline.by_company
        assert baseline.by_company["Acme Corp"].precision == 0.833

        # Overall: 18 TP, 6 FP, 5 FN
        # Precision: 18/24 = 0.75
        # Recall: 18/23 = 0.7826
        assert baseline.overall.precision == pytest.approx(0.75)

    def test_empty_results_raises_valueerror(self) -> None:
        """Empty results list raises ValueError."""
        with pytest.raises(ValueError, match="Cannot create baseline from empty"):
            create_baseline_from_results([])


class TestComparisonResultSummary:
    """Tests for ComparisonResult.summary() method."""

    def test_summary_format_improvement(self) -> None:
        """Summary shows positive deltas for improvements."""
        result = ComparisonResult(
            precision_delta=0.05,
            recall_delta=0.10,
            f1_delta=0.07,
            has_regression=False,
            regressed_companies=[],
            regressed_metrics=[],
        )

        summary = result.summary()

        assert "+5.0%" in summary
        assert "+10.0%" in summary
        assert "REGRESSION" not in summary

    def test_summary_format_regression(self) -> None:
        """Summary shows regression warning."""
        result = ComparisonResult(
            precision_delta=-0.05,
            recall_delta=-0.10,
            f1_delta=-0.07,
            has_regression=True,
            regressed_companies=["Bad Corp"],
            regressed_metrics=["precision", "recall", "f1"],
        )

        summary = result.summary()

        assert "-5.0%" in summary
        assert "REGRESSION DETECTED" in summary
        assert "precision" in summary
        assert "Bad Corp" in summary


class TestTier1PresenceGate:
    """PR2 — Tier-1 presence-recall regression gate.

    Replaces the pre-PR2 fact-level gate. Only Tier-1 presence-recall drops
    set ``has_regression=True``; everything else (overall fact P/R/F1, per-
    company fact deltas, presence_f1, Tier-2 presence-recall) is informational.
    """

    @staticmethod
    def _baseline(
        tier1: float | None = None,
        tier2: float | None = None,
        presence_f1: float | None = None,
        precision: float = 0.6,
        recall: float = 0.6,
        f1: float = 0.6,
    ) -> BaselineMetrics:
        return BaselineMetrics(
            baseline_date="2026-04-25T00:00:00+00:00",
            description=None,
            overall=MetricScores(precision=precision, recall=recall, f1=f1),
            by_company={},
            tier1_presence_recall=tier1,
            tier2_presence_recall=tier2,
            presence_f1=presence_f1,
        )

    def test_tier1_drop_blocks(self) -> None:
        """Tier-1 presence-recall drop is the only thing that gates."""
        result = compare_to_baseline(
            self._baseline(tier1=0.70, tier2=0.50),
            self._baseline(tier1=0.75, tier2=0.50),
        )
        assert result.has_regression
        assert result.tier1_presence_recall_delta == pytest.approx(-0.05)
        assert any("[GATE]" in m and "tier1_presence_recall" in m for m in result.regressed_metrics)

    def test_tier2_drop_does_not_block(self) -> None:
        """Tier-2 drops are reported as informational, never gate."""
        result = compare_to_baseline(
            self._baseline(tier1=0.70, tier2=0.40),
            self._baseline(tier1=0.70, tier2=0.50),
        )
        assert not result.has_regression
        assert result.tier2_presence_recall_delta == pytest.approx(-0.10)
        assert any(
            "[informational]" in m and "tier2_presence_recall" in m
            for m in result.regressed_metrics
        )

    def test_fact_level_drop_does_not_block(self) -> None:
        """Pre-PR2 gate metrics (overall P/R/F1) are now informational."""
        result = compare_to_baseline(
            self._baseline(tier1=0.70, precision=0.4, recall=0.4, f1=0.4),
            self._baseline(tier1=0.70, precision=0.6, recall=0.6, f1=0.6),
        )
        assert not result.has_regression
        # Fact-level deltas still reported.
        assert all("[informational]" in m for m in result.regressed_metrics)

    def test_presence_f1_drop_does_not_block(self) -> None:
        """Chart-presence F1 drop is informational under PR2."""
        result = compare_to_baseline(
            self._baseline(tier1=0.70, presence_f1=0.40),
            self._baseline(tier1=0.70, presence_f1=0.60),
        )
        assert not result.has_regression
        assert result.presence_f1_delta == pytest.approx(-0.20)

    def test_pre_pr2_baseline_skips_gate(self, caplog: pytest.LogCaptureFixture) -> None:
        """Loading a baseline without tier1 field skips the gate + warns."""
        result = compare_to_baseline(
            self._baseline(tier1=0.70),
            self._baseline(tier1=None),  # pre-PR2 baseline
        )
        assert not result.has_regression
        assert result.tier1_presence_recall_delta is None
        assert any(
            "Tier-1 presence-recall not present" in record.message for record in caplog.records
        )

    def test_tier1_unchanged_with_other_drops_no_block(self) -> None:
        """When Tier-1 holds, drops elsewhere are informational only."""
        result = compare_to_baseline(
            self._baseline(tier1=0.70, tier2=0.40, presence_f1=0.30, precision=0.4),
            self._baseline(tier1=0.70, tier2=0.50, presence_f1=0.50, precision=0.6),
        )
        assert not result.has_regression
        assert any("tier2_presence_recall" in m for m in result.regressed_metrics)
        assert any("presence_f1" in m for m in result.regressed_metrics)
        assert any("precision" in m for m in result.regressed_metrics)

    def test_tier1_drop_with_other_metrics_still_blocks(self) -> None:
        """Tier-1 drop blocks even if everything else also dropped (mixed regression)."""
        result = compare_to_baseline(
            self._baseline(tier1=0.50, tier2=0.30, precision=0.4),
            self._baseline(tier1=0.70, tier2=0.50, precision=0.6),
        )
        assert result.has_regression
        # Tier-1 entry should appear first in regressed_metrics (gate marker).
        assert result.regressed_metrics[0].startswith("[GATE]")
        assert "tier1_presence_recall" in result.regressed_metrics[0]


class TestBaselineMetricsTier1Fields:
    """PR2 — Tier-1/2 presence-recall round-trip + backwards compat."""

    def test_round_trip_with_tier_fields(self) -> None:
        b = BaselineMetrics(
            baseline_date="2026-04-25T00:00:00+00:00",
            description="PR2 test",
            overall=MetricScores(precision=0.5, recall=0.5, f1=0.5),
            by_company={},
            tier1_presence_recall=0.72,
            tier2_presence_recall=0.41,
        )
        d = b.to_dict()
        assert d["tier1_presence_recall"] == 0.72
        assert d["tier2_presence_recall"] == 0.41
        b2 = BaselineMetrics.from_dict(d)
        assert b2.tier1_presence_recall == 0.72
        assert b2.tier2_presence_recall == 0.41

    def test_none_tier_fields_omitted_from_dict(self) -> None:
        """Pre-PR2 baselines should not gain a serialized null field."""
        b = BaselineMetrics(
            baseline_date="2026-04-25T00:00:00+00:00",
            description=None,
            overall=MetricScores(precision=0.5, recall=0.5, f1=0.5),
            by_company={},
        )
        d = b.to_dict()
        assert "tier1_presence_recall" not in d
        assert "tier2_presence_recall" not in d

    def test_load_pre_pr2_baseline_json(self) -> None:
        """A baseline JSON predating PR2 must load cleanly with None tier fields."""
        legacy_json = {
            "baseline_date": "2026-04-20T00:00:00+00:00",
            "description": "pre-PR2",
            "overall": {"precision": 0.65, "recall": 0.55, "f1": 0.60},
            "by_company": {
                "Acme, Inc.": {"precision": 0.7, "recall": 0.5, "f1": 0.58},
            },
        }
        b = BaselineMetrics.from_dict(legacy_json)
        assert b.tier1_presence_recall is None
        assert b.tier2_presence_recall is None

    def test_save_load_round_trip_via_disk(self) -> None:
        """to_dict / from_dict via JSON file."""
        b = BaselineMetrics(
            baseline_date="2026-04-25T00:00:00+00:00",
            description="disk round-trip",
            overall=MetricScores(precision=0.6, recall=0.7, f1=0.65),
            by_company={"Foo Co.": MetricScores(precision=0.5, recall=0.5, f1=0.5)},
            tier1_presence_recall=0.81,
            tier2_presence_recall=0.62,
        )
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "baseline.json"
            save_baseline(b, p)
            loaded = load_baseline(p)
            assert loaded.tier1_presence_recall == 0.81
            assert loaded.tier2_presence_recall == 0.62
            # Verify JSON shape too
            d = json.loads(p.read_text())
            assert d["tier1_presence_recall"] == 0.81
