"""
Unit tests for multiplier recommendation generation (E1 Phase 3).

Tests verify that the PatternAnalyzer can generate data-driven multiplier
recommendations based on context performance analysis.
"""

import pytest
from unittest.mock import Mock, MagicMock
from src.review.pattern_analyzer import PatternAnalyzer


class TestMultiplierRecommendations:
    """Test multiplier recommendation generation."""

    @pytest.fixture
    def mock_db(self):
        """Mock database adapter."""
        return Mock()

    @pytest.fixture
    def analyzer(self, mock_db):
        """Pattern analyzer with mocked database."""
        return PatternAnalyzer(mock_db)

    def test_generate_recommendations_structure(self, analyzer, monkeypatch):
        """Generated recommendations have expected structure."""
        # Mock analyze_context_performance to return test data
        mock_performance = {
            "total_decisions": 100,
            "decisions_with_context": 100,
            "context_stats": {
                "table": {
                    "total": 50,
                    "accepted": 45,
                    "rejected": 5,
                    "precision": 0.9,
                    "by_direction": {},
                },
            },
        }

        monkeypatch.setattr(
            analyzer,
            "analyze_context_performance",
            lambda filing_id=None, metric_id=None: mock_performance,
        )

        result = analyzer.generate_multiplier_recommendations()

        # Check top-level structure
        assert "summary" in result
        assert "current_multipliers" in result
        assert "recommendations" in result
        assert "warnings" in result

        # Check summary
        assert result["summary"]["total_decisions"] == 100
        assert result["summary"]["baseline_precision"] == 0.5
        assert result["summary"]["min_sample_size"] == 10

        # Check recommendations structure
        assert "table" in result["recommendations"]
        table_rec = result["recommendations"]["table"]
        assert "current" in table_rec
        assert "recommended" in table_rec
        assert "precision" in table_rec
        assert "sample_size" in table_rec
        assert "confidence" in table_rec
        assert "rationale" in table_rec
        assert "change" in table_rec

    def test_high_precision_recommends_lower_multiplier(self, analyzer, monkeypatch):
        """High precision contexts should get lower multipliers (prefer pre-value)."""
        mock_performance = {
            "total_decisions": 100,
            "decisions_with_context": 100,
            "context_stats": {
                "table": {
                    "total": 50,
                    "accepted": 45,
                    "rejected": 5,
                    "precision": 0.9,  # High precision
                    "by_direction": {},
                },
            },
        }

        monkeypatch.setattr(
            analyzer,
            "analyze_context_performance",
            lambda filing_id=None, metric_id=None: mock_performance,
        )

        result = analyzer.generate_multiplier_recommendations()

        table_rec = result["recommendations"]["table"]
        # High precision (0.9) should recommend lower multiplier
        # Formula: 1.0 + ((0.5 - 0.9) * 1.0 * 0.5) = 1.0 + (-0.2) = 0.8
        assert table_rec["recommended"] < 1.0
        assert table_rec["confidence"] == "high"  # 50 samples > 50 (min * 5)

    def test_low_precision_recommends_higher_multiplier(self, analyzer, monkeypatch):
        """Low precision contexts should get higher multipliers (prefer post-value)."""
        mock_performance = {
            "total_decisions": 100,
            "decisions_with_context": 100,
            "context_stats": {
                "default": {
                    "total": 50,
                    "accepted": 5,
                    "rejected": 45,
                    "precision": 0.1,  # Low precision
                    "by_direction": {},
                },
            },
        }

        monkeypatch.setattr(
            analyzer,
            "analyze_context_performance",
            lambda filing_id=None, metric_id=None: mock_performance,
        )

        result = analyzer.generate_multiplier_recommendations()

        default_rec = result["recommendations"]["default"]
        # Low precision (0.1) should recommend higher multiplier
        # Formula: 1.0 + ((0.5 - 0.1) * 1.0 * 0.5) = 1.0 + 0.2 = 1.2
        assert default_rec["recommended"] > 1.0
        assert default_rec["confidence"] == "high"

    def test_neutral_precision_recommends_1_0(self, analyzer, monkeypatch):
        """Baseline precision should recommend multiplier = 1.0."""
        mock_performance = {
            "total_decisions": 100,
            "decisions_with_context": 100,
            "context_stats": {
                "bullet": {
                    "total": 50,
                    "accepted": 25,
                    "rejected": 25,
                    "precision": 0.5,  # Baseline precision
                    "by_direction": {},
                },
            },
        }

        monkeypatch.setattr(
            analyzer,
            "analyze_context_performance",
            lambda filing_id=None, metric_id=None: mock_performance,
        )

        result = analyzer.generate_multiplier_recommendations()

        bullet_rec = result["recommendations"]["bullet"]
        # Precision = baseline should recommend 1.0
        assert abs(bullet_rec["recommended"] - 1.0) < 0.01

    def test_insufficient_samples_keeps_current(self, analyzer, monkeypatch):
        """Contexts with insufficient samples should keep current multiplier."""
        mock_performance = {
            "total_decisions": 5,
            "decisions_with_context": 5,
            "context_stats": {
                "table": {
                    "total": 5,  # Less than min_sample_size (10)
                    "accepted": 5,
                    "rejected": 0,
                    "precision": 1.0,
                    "by_direction": {},
                },
            },
        }

        monkeypatch.setattr(
            analyzer,
            "analyze_context_performance",
            lambda filing_id=None, metric_id=None: mock_performance,
        )

        result = analyzer.generate_multiplier_recommendations()

        table_rec = result["recommendations"]["table"]
        # Should keep current value
        assert table_rec["recommended"] == table_rec["current"]
        assert table_rec["confidence"] == "insufficient"
        assert len(result["warnings"]) > 0

    def test_low_confidence_conservative_adjustment(self, analyzer, monkeypatch):
        """Low sample sizes should use conservative adjustment factor."""
        mock_performance = {
            "total_decisions": 15,
            "decisions_with_context": 15,
            "context_stats": {
                "table": {
                    "total": 15,  # Between min and min*2 (10-20)
                    "accepted": 14,
                    "rejected": 1,
                    "precision": 0.933,
                    "by_direction": {},
                },
            },
        }

        monkeypatch.setattr(
            analyzer,
            "analyze_context_performance",
            lambda filing_id=None, metric_id=None: mock_performance,
        )

        result = analyzer.generate_multiplier_recommendations()

        table_rec = result["recommendations"]["table"]
        assert table_rec["confidence"] == "low"
        # Conservative adjustment (factor=0.5) should be less aggressive
        # than full adjustment

    def test_medium_confidence_moderate_adjustment(self, analyzer, monkeypatch):
        """Medium sample sizes should use moderate adjustment factor."""
        mock_performance = {
            "total_decisions": 30,
            "decisions_with_context": 30,
            "context_stats": {
                "table": {
                    "total": 30,  # Between min*2 and min*5 (20-50)
                    "accepted": 27,
                    "rejected": 3,
                    "precision": 0.9,
                    "by_direction": {},
                },
            },
        }

        monkeypatch.setattr(
            analyzer,
            "analyze_context_performance",
            lambda filing_id=None, metric_id=None: mock_performance,
        )

        result = analyzer.generate_multiplier_recommendations()

        table_rec = result["recommendations"]["table"]
        assert table_rec["confidence"] == "medium"

    def test_high_confidence_full_adjustment(self, analyzer, monkeypatch):
        """High sample sizes should use full adjustment factor."""
        mock_performance = {
            "total_decisions": 100,
            "decisions_with_context": 100,
            "context_stats": {
                "table": {
                    "total": 100,  # > min*5 (50)
                    "accepted": 90,
                    "rejected": 10,
                    "precision": 0.9,
                    "by_direction": {},
                },
            },
        }

        monkeypatch.setattr(
            analyzer,
            "analyze_context_performance",
            lambda filing_id=None, metric_id=None: mock_performance,
        )

        result = analyzer.generate_multiplier_recommendations()

        table_rec = result["recommendations"]["table"]
        assert table_rec["confidence"] == "high"

    def test_multiplier_clamping(self, analyzer):
        """Computed multipliers should be clamped to 0.7-1.3 range."""
        # Test extreme high precision
        result_high = analyzer._compute_recommended_multiplier(
            precision=1.0,
            baseline_precision=0.5,
            adjustment_factor=1.0,
        )
        # Formula: 1.0 + ((0.5 - 1.0) * 1.0 * 0.5) = 1.0 - 0.25 = 0.75
        assert 0.7 <= result_high <= 1.3

        # Test extreme low precision
        result_low = analyzer._compute_recommended_multiplier(
            precision=0.0,
            baseline_precision=0.5,
            adjustment_factor=1.0,
        )
        # Formula: 1.0 + ((0.5 - 0.0) * 1.0 * 0.5) = 1.0 + 0.25 = 1.25
        assert 0.7 <= result_low <= 1.3

    def test_change_field_computed_correctly(self, analyzer, monkeypatch):
        """Change field should be recommended - current."""
        mock_performance = {
            "total_decisions": 50,
            "decisions_with_context": 50,
            "context_stats": {
                "table": {
                    "total": 50,
                    "accepted": 45,
                    "rejected": 5,
                    "precision": 0.9,
                    "by_direction": {},
                },
            },
        }

        monkeypatch.setattr(
            analyzer,
            "analyze_context_performance",
            lambda filing_id=None, metric_id=None: mock_performance,
        )

        result = analyzer.generate_multiplier_recommendations()

        table_rec = result["recommendations"]["table"]
        expected_change = table_rec["recommended"] - table_rec["current"]
        assert abs(table_rec["change"] - expected_change) < 0.001

    def test_custom_min_sample_size(self, analyzer, monkeypatch):
        """Custom min_sample_size should affect confidence levels."""
        mock_performance = {
            "total_decisions": 15,
            "decisions_with_context": 15,
            "context_stats": {
                "table": {
                    "total": 15,
                    "accepted": 14,
                    "rejected": 1,
                    "precision": 0.933,
                    "by_direction": {},
                },
            },
        }

        monkeypatch.setattr(
            analyzer,
            "analyze_context_performance",
            lambda filing_id=None, metric_id=None: mock_performance,
        )

        # With min_sample_size=20, 15 samples should be insufficient
        result = analyzer.generate_multiplier_recommendations(min_sample_size=20)

        table_rec = result["recommendations"]["table"]
        assert table_rec["confidence"] == "insufficient"

    def test_custom_baseline_precision(self, analyzer, monkeypatch):
        """Custom baseline_precision should affect recommendations."""
        mock_performance = {
            "total_decisions": 50,
            "decisions_with_context": 50,
            "context_stats": {
                "table": {
                    "total": 50,
                    "accepted": 35,
                    "rejected": 15,
                    "precision": 0.7,
                    "by_direction": {},
                },
            },
        }

        monkeypatch.setattr(
            analyzer,
            "analyze_context_performance",
            lambda filing_id=None, metric_id=None: mock_performance,
        )

        # With baseline=0.7, precision=0.7 should recommend 1.0
        result = analyzer.generate_multiplier_recommendations(baseline_precision=0.7)

        table_rec = result["recommendations"]["table"]
        assert abs(table_rec["recommended"] - 1.0) < 0.01

    def test_multiple_contexts_processed(self, analyzer, monkeypatch):
        """All contexts in performance data should get recommendations."""
        mock_performance = {
            "total_decisions": 150,
            "decisions_with_context": 150,
            "context_stats": {
                "table": {
                    "total": 50,
                    "accepted": 45,
                    "rejected": 5,
                    "precision": 0.9,
                    "by_direction": {},
                },
                "bullet": {
                    "total": 50,
                    "accepted": 25,
                    "rejected": 25,
                    "precision": 0.5,
                    "by_direction": {},
                },
                "default": {
                    "total": 50,
                    "accepted": 10,
                    "rejected": 40,
                    "precision": 0.2,
                    "by_direction": {},
                },
            },
        }

        monkeypatch.setattr(
            analyzer,
            "analyze_context_performance",
            lambda filing_id=None, metric_id=None: mock_performance,
        )

        result = analyzer.generate_multiplier_recommendations()

        # All three contexts should have recommendations
        assert "table" in result["recommendations"]
        assert "bullet" in result["recommendations"]
        assert "default" in result["recommendations"]

    def test_current_multipliers_from_config(self, analyzer, monkeypatch):
        """Current multipliers should match CandidateGenerationConfig defaults."""
        mock_performance = {
            "total_decisions": 0,
            "decisions_with_context": 0,
            "context_stats": {},
        }

        monkeypatch.setattr(
            analyzer,
            "analyze_context_performance",
            lambda filing_id=None, metric_id=None: mock_performance,
        )

        result = analyzer.generate_multiplier_recommendations()

        # Should have all context types
        assert "table" in result["current_multipliers"]
        assert "parenthetical" in result["current_multipliers"]
        assert "bullet" in result["current_multipliers"]
        assert "copula" in result["current_multipliers"]
        assert "preposition" in result["current_multipliers"]
        assert "default" in result["current_multipliers"]

        # Values should match config defaults
        assert result["current_multipliers"]["table"] == 0.85
        assert result["current_multipliers"]["parenthetical"] == 1.15
        assert result["current_multipliers"]["default"] == 0.9
