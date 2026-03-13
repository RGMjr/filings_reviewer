"""
Unit tests for pattern_analyzer module.

Tests PatternAnalyzer class for analyzing review decisions and computing feature importance.
Target coverage: 85-90%
"""

from unittest.mock import Mock

import pytest

from src.review.models import LearnedPattern
from src.review.pattern_analyzer import PatternAnalyzer

# =============================================================================
# Test Fixtures
# =============================================================================


@pytest.fixture
def mock_db():
    """Mock database adapter."""
    return Mock()


@pytest.fixture
def sample_decisions_data():
    """Sample decisions with features for testing."""
    return [
        {
            "candidate_id": 1,
            "filing_id": 100,
            "decision": "accept",
            "assigned_metric_id": "cm_active_customers_total",
            "rejection_category": None,
            "features": {
                "keyword_distance": 15,
                "keyword_position": "before",
                "is_in_table": False,
                "is_in_risk_factors": False,
                "contains_definition_language": True,
                "has_period_mention": True,
                "number_format": "integer",
                "value_magnitude": 4.5,  # log10(31623) ≈ 4.5
                "surrounding_numbers_count": 2,
                "context_word_count": 50,
                "section_name": "Key Metrics",
            },
        },
        {
            "candidate_id": 2,
            "filing_id": 100,
            "decision": "reject",
            "assigned_metric_id": None,
            "rejection_category": "not_a_metric",
            "features": {
                "keyword_distance": 120,
                "keyword_position": "after",
                "is_in_table": False,
                "is_in_risk_factors": True,
                "contains_definition_language": False,
                "has_period_mention": False,
                "number_format": "integer",
                "value_magnitude": 3.0,  # log10(1000) = 3.0
                "surrounding_numbers_count": 8,
                "context_word_count": 45,
                "section_name": "Risk Factors",
            },
        },
        {
            "candidate_id": 3,
            "filing_id": 100,
            "decision": "accept",
            "assigned_metric_id": "cm_arr",
            "rejection_category": None,
            "features": {
                "keyword_distance": 20,
                "keyword_position": "before",
                "is_in_table": True,
                "is_in_risk_factors": False,
                "contains_definition_language": True,
                "has_period_mention": True,
                "number_format": "currency",
                "value_magnitude": 6.0,  # log10(1000000) = 6.0
                "surrounding_numbers_count": 5,
                "context_word_count": 60,
                "section_name": "Revenue Metrics",
            },
        },
        {
            "candidate_id": 4,
            "filing_id": 100,
            "decision": "reject",
            "assigned_metric_id": None,
            "rejection_category": "wrong_value",
            "features": {
                "keyword_distance": 95,
                "keyword_position": "after",
                "is_in_table": False,
                "is_in_risk_factors": True,
                "contains_definition_language": False,
                "has_period_mention": False,
                "number_format": "integer",
                "value_magnitude": 2.0,  # log10(100) = 2.0
                "surrounding_numbers_count": 10,
                "context_word_count": 40,
                "section_name": "Risk Factors",
            },
        },
        {
            "candidate_id": 5,
            "filing_id": 100,
            "decision": "reclassify",
            "assigned_metric_id": "cm_total_customers",
            "rejection_category": None,
            "features": {
                "keyword_distance": 30,
                "keyword_position": "before",
                "is_in_table": True,
                "is_in_risk_factors": False,
                "contains_definition_language": False,
                "has_period_mention": True,
                "number_format": "decimal",
                "value_magnitude": 5.2,  # log10(158489) ≈ 5.2
                "surrounding_numbers_count": 3,
                "context_word_count": 55,
                "section_name": "Customer Base",
            },
        },
    ]


# =============================================================================
# TestPatternAnalyzer - Initialization
# =============================================================================


class TestPatternAnalyzerInit:
    """Tests for PatternAnalyzer initialization."""

    def test_init_default_parameters(self, mock_db):
        """Should initialize with default parameters."""
        analyzer = PatternAnalyzer(mock_db)

        assert analyzer.db is mock_db
        assert analyzer.min_pattern_precision == 0.75
        assert analyzer.min_pattern_support == 5
        assert analyzer.min_sample_size == 30
        assert analyzer.significance_threshold == 0.05

    def test_init_custom_parameters(self, mock_db):
        """Should initialize with custom parameters."""
        analyzer = PatternAnalyzer(
            mock_db,
            min_pattern_precision=0.85,
            min_pattern_support=10,
            min_sample_size=50,
            significance_threshold=0.01,
        )

        assert analyzer.min_pattern_precision == 0.85
        assert analyzer.min_pattern_support == 10
        assert analyzer.min_sample_size == 50
        assert analyzer.significance_threshold == 0.01

    def test_class_constants(self):
        """Should have correct feature constants."""
        assert len(PatternAnalyzer.CATEGORICAL_FEATURES) == 6
        assert "keyword_position" in PatternAnalyzer.CATEGORICAL_FEATURES
        assert "is_in_risk_factors" in PatternAnalyzer.CATEGORICAL_FEATURES

        assert len(PatternAnalyzer.NUMERIC_FEATURES) == 4
        assert "keyword_distance" in PatternAnalyzer.NUMERIC_FEATURES
        assert "value_magnitude" in PatternAnalyzer.NUMERIC_FEATURES


# =============================================================================
# TestComputeCategoricalImportance
# =============================================================================


class TestComputeCategoricalImportance:
    """Tests for _compute_categorical_importance method."""

    def test_categorical_importance_basic(self, mock_db, sample_decisions_data):
        """Should compute categorical importance correctly."""
        analyzer = PatternAnalyzer(mock_db)
        result = analyzer._compute_categorical_importance(
            "is_in_risk_factors", sample_decisions_data
        )

        assert result is not None
        assert result["feature_name"] == "is_in_risk_factors"
        assert "chi_squared" in result
        assert "value_distribution" in result
        assert result["is_significant"] is False  # MVP: always False

        # Check value distribution
        assert "True" in result["value_distribution"]
        assert "False" in result["value_distribution"]

    def test_categorical_importance_with_boolean_conversion(
        self, mock_db, sample_decisions_data
    ):
        """Should convert boolean values to strings."""
        analyzer = PatternAnalyzer(mock_db)
        result = analyzer._compute_categorical_importance(
            "is_in_table", sample_decisions_data
        )

        assert result is not None
        # Booleans should be converted to strings
        assert "True" in result["value_distribution"]
        assert "False" in result["value_distribution"]

    def test_categorical_importance_all_none_values(self, mock_db):
        """Should return None for feature with all None values."""
        decisions_data = [
            {
                "decision": "accept",
                "features": {"keyword_position": None},
            },
            {
                "decision": "reject",
                "features": {"keyword_position": None},
            },
        ]

        analyzer = PatternAnalyzer(mock_db)
        result = analyzer._compute_categorical_importance(
            "keyword_position", decisions_data
        )

        assert result is None

    def test_categorical_importance_invalid_test(self, mock_db):
        """Should handle chi-squared test failures gracefully."""
        # Single decision - chi-squared will fail
        decisions_data = [
            {
                "decision": "accept",
                "features": {"keyword_position": "before"},
            },
        ]

        analyzer = PatternAnalyzer(mock_db)
        result = analyzer._compute_categorical_importance(
            "keyword_position", decisions_data
        )

        # Should return None or handle gracefully
        # (actual behavior depends on chi_squared_test implementation)
        assert result is None or result["is_valid"] is False


# =============================================================================
# TestComputeNumericImportance
# =============================================================================


class TestComputeNumericImportance:
    """Tests for _compute_numeric_importance method."""

    def test_numeric_importance_basic(self, mock_db, sample_decisions_data):
        """Should compute numeric importance correctly."""
        analyzer = PatternAnalyzer(mock_db)
        result = analyzer._compute_numeric_importance(
            "keyword_distance", sample_decisions_data
        )

        assert result is not None
        assert result["feature_name"] == "keyword_distance"
        assert "t_statistic" in result
        assert "effect_size" in result
        assert "mean_by_decision" in result
        assert result["is_significant"] is False  # MVP: always False

        # Should have means for accept and reject
        assert "accept" in result["mean_by_decision"]
        assert "reject" in result["mean_by_decision"]

        # Accept values: [15, 20], mean = 17.5
        # Reject values: [120, 95], mean = 107.5
        assert result["mean_by_decision"]["accept"] == pytest.approx(17.5)
        assert result["mean_by_decision"]["reject"] == pytest.approx(107.5)

    def test_numeric_importance_includes_reclassify_in_means(
        self, mock_db, sample_decisions_data
    ):
        """Should include reclassify in mean computation but not in t-test."""
        analyzer = PatternAnalyzer(mock_db)
        result = analyzer._compute_numeric_importance(
            "keyword_distance", sample_decisions_data
        )

        # Should have mean for reclassify (not in t-test comparison)
        assert "reclassify" in result["mean_by_decision"]
        assert result["mean_by_decision"]["reclassify"] == 30.0

    def test_numeric_importance_insufficient_data(self, mock_db):
        """Should return None when insufficient data for t-test."""
        # Only accept decisions, no reject
        decisions_data = [
            {
                "decision": "accept",
                "features": {"keyword_distance": 15},
            },
            {
                "decision": "accept",
                "features": {"keyword_distance": 20},
            },
        ]

        analyzer = PatternAnalyzer(mock_db)
        result = analyzer._compute_numeric_importance("keyword_distance", decisions_data)

        assert result is None  # No reject values for t-test

    def test_numeric_importance_none_values_filtered(self, mock_db):
        """Should filter out None values before t-test."""
        decisions_data = [
            {
                "decision": "accept",
                "features": {"value_magnitude": 4.5},
            },
            {
                "decision": "accept",
                "features": {"value_magnitude": None},  # Should be filtered out
            },
            {
                "decision": "reject",
                "features": {"value_magnitude": 2.0},
            },
            {
                "decision": "reject",
                "features": {"value_magnitude": None},  # Should be filtered out
            },
        ]

        analyzer = PatternAnalyzer(mock_db)
        result = analyzer._compute_numeric_importance("value_magnitude", decisions_data)

        # Should still work with filtered data
        assert result is not None
        assert result["mean_by_decision"]["accept"] == 4.5
        assert result["mean_by_decision"]["reject"] == 2.0

    def test_numeric_importance_non_numeric_filtered(self, mock_db):
        """Should filter out non-numeric values."""
        decisions_data = [
            {
                "decision": "accept",
                "features": {"keyword_distance": 15},
            },
            {
                "decision": "accept",
                "features": {"keyword_distance": "invalid"},  # Non-numeric
            },
            {
                "decision": "reject",
                "features": {"keyword_distance": 120},
            },
        ]

        analyzer = PatternAnalyzer(mock_db)
        result = analyzer._compute_numeric_importance("keyword_distance", decisions_data)

        assert result is not None
        # "invalid" should be filtered out
        assert result["mean_by_decision"]["accept"] == 15.0


# =============================================================================
# TestAnalyzeDecisions
# =============================================================================


class TestAnalyzeDecisions:
    """Tests for analyze_decisions method."""

    def test_analyze_decisions_without_filing_id_uses_all_reviewed(
        self, mock_db, sample_decisions_data
    ):
        """Should load all reviewed candidates when filing_id is None (Phase 4)."""
        # Mock database to return sample decisions
        mock_db.get_all_reviewed_candidates_with_decisions.return_value = [
            {
                "candidate_id": d["candidate_id"],
                "filing_id": d["filing_id"],
                "decision": d["decision"],
                "assigned_metric_id": d.get("assigned_metric_id"),
                "rejection_category": d.get("rejection_category"),
                "suggested_metric_id": d.get("suggested_metric_id"),
                "features": d["features"],
            }
            for d in sample_decisions_data
        ]

        analyzer = PatternAnalyzer(mock_db)
        result = analyzer.analyze_decisions(filing_id=None)

        # Should call get_all_reviewed_candidates_with_decisions, not get_review_candidates_with_decisions
        mock_db.get_all_reviewed_candidates_with_decisions.assert_called_once_with(
            metric_id=None
        )
        mock_db.get_review_candidates_with_decisions.assert_not_called()

        # Should return valid analysis
        assert result["total_decisions"] == 5  # sample_decisions_data has 5 items
        assert "categorical_features" in result
        assert "numeric_features" in result

    def test_analyze_decisions_with_filing_id(self, mock_db, sample_decisions_data):
        """Should analyze decisions for specific filing."""
        # Mock database to return sample decisions
        mock_db.get_review_candidates_with_decisions.return_value = [
            {
                "candidate_id": d["candidate_id"],
                "filing_id": d["filing_id"],
                "decision": d["decision"],
                "assigned_metric_id": d.get("assigned_metric_id"),
                "rejection_category": d.get("rejection_category"),
                "features": d["features"],
            }
            for d in sample_decisions_data
        ]

        analyzer = PatternAnalyzer(mock_db, min_sample_size=3)
        result = analyzer.analyze_decisions(filing_id=100)

        assert result["total_decisions"] == 5
        assert result["decision_counts"]["accept"] == 2
        assert result["decision_counts"]["reject"] == 2
        assert result["decision_counts"]["reclassify"] == 1
        assert len(result["categorical_features"]) > 0
        assert len(result["numeric_features"]) > 0
        assert len(result["warnings"]) == 0  # 5 >= min_sample_size (3)

    def test_analyze_decisions_small_sample_warning(self, mock_db, sample_decisions_data):
        """Should warn when sample size < minimum."""
        mock_db.get_review_candidates_with_decisions.return_value = [
            {
                "candidate_id": d["candidate_id"],
                "filing_id": d["filing_id"],
                "decision": d["decision"],
                "assigned_metric_id": d.get("assigned_metric_id"),
                "rejection_category": d.get("rejection_category"),
                "features": d["features"],
            }
            for d in sample_decisions_data[:2]  # Only 2 decisions
        ]

        analyzer = PatternAnalyzer(mock_db, min_sample_size=30)
        result = analyzer.analyze_decisions(filing_id=100)

        assert len(result["warnings"]) > 0
        assert "Small sample size" in result["warnings"][0]

    def test_analyze_decisions_skips_candidates_without_decisions(self, mock_db):
        """Should skip candidates without decisions (NULL decision field)."""
        candidates = [
            {
                "candidate_id": 1,
                "filing_id": 100,
                "decision": "accept",  # Has decision
                "features": {
                    "keyword_distance": 15,
                    "keyword_position": "before",
                    "is_in_table": False,
                    "is_in_risk_factors": False,
                    "contains_definition_language": True,
                    "has_period_mention": True,
                    "number_format": "integer",
                    "value_magnitude": 4.5,
                    "surrounding_numbers_count": 2,
                    "context_word_count": 50,
                },
            },
            {
                "candidate_id": 2,
                "filing_id": 100,
                "decision": None,  # No decision (should be skipped)
                "features": {
                    "keyword_distance": 120,
                    "keyword_position": "after",
                },
            },
        ]

        mock_db.get_review_candidates_with_decisions.return_value = candidates

        analyzer = PatternAnalyzer(mock_db, min_sample_size=1)
        result = analyzer.analyze_decisions(filing_id=100)

        # Should only count the one with decision
        assert result["total_decisions"] == 1

    def test_analyze_decisions_sorts_categorical_by_chi_squared(
        self, mock_db, sample_decisions_data
    ):
        """Should sort categorical features by chi-squared descending."""
        mock_db.get_review_candidates_with_decisions.return_value = [
            {
                "candidate_id": d["candidate_id"],
                "filing_id": d["filing_id"],
                "decision": d["decision"],
                "assigned_metric_id": d.get("assigned_metric_id"),
                "features": d["features"],
            }
            for d in sample_decisions_data
        ]

        analyzer = PatternAnalyzer(mock_db, min_sample_size=1)
        result = analyzer.analyze_decisions(filing_id=100)

        # Should be sorted by chi_squared descending
        chi_squared_values = [f["chi_squared"] for f in result["categorical_features"]]
        assert chi_squared_values == sorted(chi_squared_values, reverse=True)

    def test_analyze_decisions_sorts_numeric_by_effect_size(
        self, mock_db, sample_decisions_data
    ):
        """Should sort numeric features by absolute effect size descending."""
        mock_db.get_review_candidates_with_decisions.return_value = [
            {
                "candidate_id": d["candidate_id"],
                "filing_id": d["filing_id"],
                "decision": d["decision"],
                "assigned_metric_id": d.get("assigned_metric_id"),
                "features": d["features"],
            }
            for d in sample_decisions_data
        ]

        analyzer = PatternAnalyzer(mock_db, min_sample_size=1)
        result = analyzer.analyze_decisions(filing_id=100)

        # Should be sorted by absolute effect size descending
        effect_sizes = [abs(f["effect_size"]) for f in result["numeric_features"]]
        assert effect_sizes == sorted(effect_sizes, reverse=True)


# =============================================================================
# TestEdgeCases
# =============================================================================


class TestEdgeCases:
    """Tests for edge cases."""

    def test_load_decisions_filters_by_metric_id(self, mock_db, sample_decisions_data):
        """Should filter decisions by metric_id when provided."""
        mock_db.get_review_candidates_with_decisions.return_value = [
            {
                "candidate_id": d["candidate_id"],
                "filing_id": d["filing_id"],
                "decision": d["decision"],
                "assigned_metric_id": d.get("assigned_metric_id"),
                "suggested_metric_id": d.get("assigned_metric_id"),  # Use assigned as suggested
                "features": d["features"],
            }
            for d in sample_decisions_data
        ]

        analyzer = PatternAnalyzer(mock_db, min_sample_size=1)
        result = analyzer.analyze_decisions(filing_id=100, metric_id="cm_arr")

        # Should only include decisions for cm_arr
        assert result["total_decisions"] == 1
        assert result["decision_counts"]["accept"] == 1

    def test_load_decisions_skips_candidates_without_features(self, mock_db, caplog):
        """Should skip and warn about candidates without features."""
        candidates = [
            {
                "candidate_id": 1,
                "filing_id": 100,
                "decision": "accept",
                "features": None,  # No features
            },
            {
                "candidate_id": 2,
                "filing_id": 100,
                "decision": "reject",
                "features": {
                    "keyword_distance": 120,
                    "keyword_position": "after",
                    "is_in_table": False,
                    "is_in_risk_factors": True,
                    "contains_definition_language": False,
                    "has_period_mention": False,
                    "number_format": "integer",
                    "value_magnitude": 3.0,
                    "surrounding_numbers_count": 8,
                    "context_word_count": 45,
                },
            },
        ]

        mock_db.get_review_candidates_with_decisions.return_value = candidates

        analyzer = PatternAnalyzer(mock_db, min_sample_size=1)
        result = analyzer.analyze_decisions(filing_id=100)

        # Should only count the one with features
        assert result["total_decisions"] == 1
        # Should have logged a warning
        assert "has no features" in caplog.text


# =============================================================================
# TestGeneratePatternName
# =============================================================================


class TestGeneratePatternName:
    """Tests for generate_pattern_name method."""

    def test_generate_pattern_name_accept_rule(self, mock_db):
        """Should generate name for accept rule."""
        analyzer = PatternAnalyzer(mock_db)

        pattern_def = {
            "pattern_type": "accept_rule",
            "conditions": [
                {"field": "is_in_risk_factors", "op": "eq", "value": "False"}
            ],
        }

        name = analyzer.generate_pattern_name(pattern_def, "accept_rule")
        assert name == "Accept: is_in_risk_factors = False"

    def test_generate_pattern_name_reject_rule(self, mock_db):
        """Should generate name for reject rule."""
        analyzer = PatternAnalyzer(mock_db)

        pattern_def = {
            "pattern_type": "reject_rule",
            "conditions": [
                {"field": "keyword_distance", "op": "gte", "value": 100.0}
            ],
        }

        name = analyzer.generate_pattern_name(pattern_def, "reject_rule")
        assert name == "Reject: keyword_distance >= 100.00"

    def test_generate_pattern_name_multiple_conditions(self, mock_db):
        """Should join multiple conditions with AND."""
        analyzer = PatternAnalyzer(mock_db)

        pattern_def = {
            "pattern_type": "reject_rule",
            "conditions": [
                {"field": "keyword_distance", "op": "gte", "value": 100.0},
                {"field": "is_in_risk_factors", "op": "eq", "value": "True"},
            ],
        }

        name = analyzer.generate_pattern_name(pattern_def, "reject_rule")
        assert "keyword_distance >= 100.00" in name
        assert "is_in_risk_factors = True" in name
        assert " AND " in name

    def test_generate_pattern_name_all_operators(self, mock_db):
        """Should handle all operator types."""
        analyzer = PatternAnalyzer(mock_db)

        operators_to_test = [
            ("eq", "="),
            ("ne", "!="),
            ("lt", "<"),
            ("gt", ">"),
            ("lte", "<="),
            ("gte", ">="),
        ]

        for op_code, op_symbol in operators_to_test:
            pattern_def = {
                "pattern_type": "reject_rule",
                "conditions": [
                    {"field": "keyword_distance", "op": op_code, "value": 50}
                ],
            }

            name = analyzer.generate_pattern_name(pattern_def, "reject_rule")
            assert f"keyword_distance {op_symbol} 50" in name


# =============================================================================
# TestGenerateSingleFeaturePatterns
# =============================================================================


class TestGenerateSingleFeaturePatterns:
    """Tests for _generate_single_feature_patterns method."""

    def test_generate_categorical_patterns(self, mock_db, sample_decisions_data):
        """Should generate patterns for categorical features."""
        analyzer = PatternAnalyzer(mock_db)

        patterns = analyzer._generate_single_feature_patterns(
            sample_decisions_data, target_decision="reject"
        )

        # Should have patterns for each unique categorical value
        pattern_features = [p["conditions"][0]["field"] for p in patterns]
        assert "keyword_position" in pattern_features
        assert "is_in_risk_factors" in pattern_features
        assert "number_format" in pattern_features

        # All should be reject_rule type
        assert all(p["pattern_type"] == "reject_rule" for p in patterns)

    def test_generate_numeric_patterns_at_quartiles(self, mock_db):
        """Should generate patterns at quartile thresholds for numeric features."""
        # Create data with known quartiles
        decisions_data = []
        for i in range(20):
            decisions_data.append(
                {
                    "decision": "accept" if i % 2 == 0 else "reject",
                    "features": {
                        "keyword_distance": i * 10,  # 0, 10, 20, ..., 190
                    },
                }
            )

        analyzer = PatternAnalyzer(mock_db)
        patterns = analyzer._generate_single_feature_patterns(
            decisions_data, target_decision="reject"
        )

        # Should have patterns for keyword_distance at quartiles
        distance_patterns = [
            p
            for p in patterns
            if p["conditions"][0]["field"] == "keyword_distance"
        ]

        # Should have 6 patterns: 3 quartiles × 2 operators (lte, gte)
        assert len(distance_patterns) == 6

        # Check operators
        operators = [p["conditions"][0]["op"] for p in distance_patterns]
        assert operators.count("lte") == 3
        assert operators.count("gte") == 3

    def test_generate_patterns_skips_features_with_insufficient_data(self, mock_db):
        """Should skip numeric features with < 4 values."""
        decisions_data = [
            {"decision": "accept", "features": {"keyword_distance": 10}},
            {"decision": "reject", "features": {"keyword_distance": 20}},
            {"decision": "accept", "features": {"keyword_distance": 30}},
            # Only 3 values - should be skipped
        ]

        analyzer = PatternAnalyzer(mock_db)
        patterns = analyzer._generate_single_feature_patterns(
            decisions_data, target_decision="reject"
        )

        # Should not have keyword_distance patterns
        pattern_features = [p["conditions"][0]["field"] for p in patterns]
        assert "keyword_distance" not in pattern_features

    def test_generate_patterns_converts_booleans_to_strings(
        self, mock_db, sample_decisions_data
    ):
        """Should convert boolean values to strings for categorical patterns."""
        analyzer = PatternAnalyzer(mock_db)

        patterns = analyzer._generate_single_feature_patterns(
            sample_decisions_data, target_decision="reject"
        )

        # Find patterns for boolean feature
        bool_patterns = [
            p
            for p in patterns
            if p["conditions"][0]["field"] == "is_in_risk_factors"
        ]

        # Values should be strings "True" and "False"
        values = [p["conditions"][0]["value"] for p in bool_patterns]
        assert "True" in values or "False" in values


# =============================================================================
# TestEvaluatePattern
# =============================================================================


class TestEvaluatePattern:
    """Tests for _evaluate_pattern method."""

    def test_evaluate_pattern_basic(self, mock_db):
        """Should evaluate pattern and compute metrics."""
        decisions_data = [
            {
                "decision": "reject",
                "features": {
                    "is_in_risk_factors": True,
                    "keyword_distance": 120,
                    "keyword_position": "after",
                    "number_format": "integer",
                    "value_magnitude": 3.0,
                    "surrounding_numbers_count": 8,
                    "context_word_count": 45,
                    "is_in_table": False,
                    "contains_definition_language": False,
                    "has_period_mention": False,
                },
            },
            {
                "decision": "reject",
                "features": {
                    "is_in_risk_factors": True,
                    "keyword_distance": 95,
                    "keyword_position": "after",
                    "number_format": "integer",
                    "value_magnitude": 2.0,
                    "surrounding_numbers_count": 10,
                    "context_word_count": 40,
                    "is_in_table": False,
                    "contains_definition_language": False,
                    "has_period_mention": False,
                },
            },
            {
                "decision": "accept",
                "features": {
                    "is_in_risk_factors": False,
                    "keyword_distance": 15,
                    "keyword_position": "before",
                    "number_format": "integer",
                    "value_magnitude": 4.5,
                    "surrounding_numbers_count": 2,
                    "context_word_count": 50,
                    "is_in_table": False,
                    "contains_definition_language": True,
                    "has_period_mention": True,
                },
            },
        ]

        pattern_def = {
            "pattern_type": "reject_rule",
            "conditions": [
                {"field": "is_in_risk_factors", "op": "eq", "value": True}
            ],
            "metric_id": None,
        }

        analyzer = PatternAnalyzer(mock_db)
        learned_pattern = analyzer._evaluate_pattern(
            pattern_def, decisions_data, target_decision="reject"
        )

        assert learned_pattern is not None
        assert learned_pattern.pattern_type == "reject_rule"
        assert learned_pattern.precision_score == 1.0  # 2 TP, 0 FP
        assert learned_pattern.recall_score == 1.0  # 2 TP, 0 FN
        assert learned_pattern.f1_score == 1.0
        assert learned_pattern.sample_count == 2
        assert learned_pattern.status == "candidate"

    def test_evaluate_pattern_returns_none_for_zero_support(self, mock_db):
        """Should return None when pattern has no support."""
        decisions_data = [
            {
                "decision": "accept",
                "features": {
                    "is_in_risk_factors": False,
                    "keyword_distance": 15,
                    "keyword_position": "before",
                    "number_format": "integer",
                    "value_magnitude": 4.5,
                    "surrounding_numbers_count": 2,
                    "context_word_count": 50,
                    "is_in_table": False,
                    "contains_definition_language": True,
                    "has_period_mention": True,
                },
            },
        ]

        pattern_def = {
            "pattern_type": "reject_rule",
            "conditions": [
                {"field": "is_in_risk_factors", "op": "eq", "value": True}
            ],
            "metric_id": None,
        }

        analyzer = PatternAnalyzer(mock_db)
        learned_pattern = analyzer._evaluate_pattern(
            pattern_def, decisions_data, target_decision="reject"
        )

        # No reject decisions, so support = 0
        assert learned_pattern is None

    def test_evaluate_pattern_handles_numeric_conditions(self, mock_db):
        """Should evaluate numeric threshold patterns."""
        decisions_data = [
            {
                "decision": "reject",
                "features": {
                    "keyword_distance": 120,
                    "is_in_risk_factors": True,
                    "keyword_position": "after",
                    "number_format": "integer",
                    "value_magnitude": 3.0,
                    "surrounding_numbers_count": 8,
                    "context_word_count": 45,
                    "is_in_table": False,
                    "contains_definition_language": False,
                    "has_period_mention": False,
                },
            },
            {
                "decision": "accept",
                "features": {
                    "keyword_distance": 15,
                    "is_in_risk_factors": False,
                    "keyword_position": "before",
                    "number_format": "integer",
                    "value_magnitude": 4.5,
                    "surrounding_numbers_count": 2,
                    "context_word_count": 50,
                    "is_in_table": False,
                    "contains_definition_language": True,
                    "has_period_mention": True,
                },
            },
        ]

        pattern_def = {
            "pattern_type": "reject_rule",
            "conditions": [
                {"field": "keyword_distance", "op": "gte", "value": 100}
            ],
            "metric_id": None,
        }

        analyzer = PatternAnalyzer(mock_db)
        learned_pattern = analyzer._evaluate_pattern(
            pattern_def, decisions_data, target_decision="reject"
        )

        assert learned_pattern is not None
        assert learned_pattern.precision_score == 1.0  # 1 TP, 0 FP
        assert learned_pattern.recall_score == 1.0  # 1 TP, 0 FN


# =============================================================================
# TestDiscoverPatterns
# =============================================================================


class TestDiscoverPatterns:
    """Tests for discover_patterns method."""

    def test_discover_patterns_no_decisions(self, mock_db):
        """Should return empty list when no decisions available."""
        mock_db.get_review_candidates_with_decisions.return_value = []

        analyzer = PatternAnalyzer(mock_db)
        patterns = analyzer.discover_patterns(filing_id=100)

        assert patterns == []

    def test_discover_patterns_reject_rules(self, mock_db, sample_decisions_data):
        """Should discover rejection patterns."""
        mock_db.get_review_candidates_with_decisions.return_value = [
            {
                "candidate_id": d["candidate_id"],
                "filing_id": d["filing_id"],
                "decision": d["decision"],
                "suggested_metric_id": d.get("assigned_metric_id"),
                "features": d["features"],
            }
            for d in sample_decisions_data
        ]

        analyzer = PatternAnalyzer(mock_db, min_pattern_precision=0.5, min_pattern_support=1)
        patterns = analyzer.discover_patterns(filing_id=100, pattern_type="reject_rule")

        # Should find some rejection patterns
        assert len(patterns) > 0
        assert all(p.pattern_type == "reject_rule" for p in patterns)
        assert all(p.precision_score >= 0.5 for p in patterns)
        assert all(p.sample_count >= 1 for p in patterns)

    def test_discover_patterns_accept_rules(self, mock_db, sample_decisions_data):
        """Should discover acceptance patterns."""
        mock_db.get_review_candidates_with_decisions.return_value = [
            {
                "candidate_id": d["candidate_id"],
                "filing_id": d["filing_id"],
                "decision": d["decision"],
                "suggested_metric_id": d.get("assigned_metric_id"),
                "features": d["features"],
            }
            for d in sample_decisions_data
        ]

        analyzer = PatternAnalyzer(mock_db, min_pattern_precision=0.5, min_pattern_support=1)
        patterns = analyzer.discover_patterns(filing_id=100, pattern_type="accept_rule")

        # Should find some acceptance patterns
        assert len(patterns) > 0
        assert all(p.pattern_type == "accept_rule" for p in patterns)

    def test_discover_patterns_both_types(self, mock_db, sample_decisions_data):
        """Should discover both accept and reject patterns when pattern_type is None."""
        mock_db.get_review_candidates_with_decisions.return_value = [
            {
                "candidate_id": d["candidate_id"],
                "filing_id": d["filing_id"],
                "decision": d["decision"],
                "suggested_metric_id": d.get("assigned_metric_id"),
                "features": d["features"],
            }
            for d in sample_decisions_data
        ]

        analyzer = PatternAnalyzer(mock_db, min_pattern_precision=0.5, min_pattern_support=1)
        patterns = analyzer.discover_patterns(filing_id=100, pattern_type=None)

        # Should have both types
        pattern_types = {p.pattern_type for p in patterns}
        assert "reject_rule" in pattern_types or "accept_rule" in pattern_types

    def test_discover_patterns_sorts_by_f1_score(self, mock_db, sample_decisions_data):
        """Should sort patterns by F1 score descending."""
        mock_db.get_review_candidates_with_decisions.return_value = [
            {
                "candidate_id": d["candidate_id"],
                "filing_id": d["filing_id"],
                "decision": d["decision"],
                "suggested_metric_id": d.get("assigned_metric_id"),
                "features": d["features"],
            }
            for d in sample_decisions_data
        ]

        analyzer = PatternAnalyzer(mock_db, min_pattern_precision=0.5, min_pattern_support=1)
        patterns = analyzer.discover_patterns(filing_id=100)

        if len(patterns) > 1:
            # Should be sorted by F1 descending
            f1_scores = [p.f1_score for p in patterns]
            assert f1_scores == sorted(f1_scores, reverse=True)

    def test_discover_patterns_filters_by_precision_and_support(
        self, mock_db, sample_decisions_data
    ):
        """Should filter patterns by minimum precision and support."""
        mock_db.get_review_candidates_with_decisions.return_value = [
            {
                "candidate_id": d["candidate_id"],
                "filing_id": d["filing_id"],
                "decision": d["decision"],
                "suggested_metric_id": d.get("assigned_metric_id"),
                "features": d["features"],
            }
            for d in sample_decisions_data
        ]

        analyzer = PatternAnalyzer(
            mock_db, min_pattern_precision=0.95, min_pattern_support=2
        )
        patterns = analyzer.discover_patterns(filing_id=100)

        # All patterns should meet criteria
        for p in patterns:
            assert p.precision_score >= 0.95
            assert p.sample_count >= 2


# =============================================================================
# TestSavePatterns
# =============================================================================


class TestSavePatterns:
    """Tests for save_patterns method."""

    def test_save_patterns_basic(self, mock_db):
        """Should save patterns to database."""
        from src.review.models import LearnedPattern

        patterns = [
            LearnedPattern(
                pattern_type="reject_rule",
                pattern_name="Reject: is_in_risk_factors = True",
                pattern_definition={
                    "pattern_type": "reject_rule",
                    "conditions": [
                        {"field": "is_in_risk_factors", "op": "eq", "value": True}
                    ],
                },
                metric_id=None,
                precision_score=0.85,
                recall_score=0.75,
                f1_score=0.80,
                sample_count=10,
                status="candidate",
            ),
        ]

        mock_db.insert_learned_pattern.return_value = True

        analyzer = PatternAnalyzer(mock_db)
        results = analyzer.save_patterns(patterns)

        assert results["saved_count"] == 1
        assert results["candidate_count"] == 1
        assert results["approved_count"] == 0
        assert mock_db.insert_learned_pattern.called

    def test_save_patterns_auto_approve_high_precision(self, mock_db):
        """Should auto-approve patterns above threshold."""
        from src.review.models import LearnedPattern

        patterns = [
            LearnedPattern(
                pattern_type="reject_rule",
                pattern_name="Reject: is_in_risk_factors = True",
                pattern_definition={
                    "pattern_type": "reject_rule",
                    "conditions": [
                        {"field": "is_in_risk_factors", "op": "eq", "value": True}
                    ],
                },
                metric_id=None,
                precision_score=0.95,  # Above threshold
                recall_score=0.85,
                f1_score=0.90,
                sample_count=20,
                status="candidate",
            ),
        ]

        mock_db.insert_learned_pattern.return_value = True

        analyzer = PatternAnalyzer(mock_db)
        results = analyzer.save_patterns(patterns, auto_approve_threshold=0.90)

        assert results["saved_count"] == 1
        assert results["approved_count"] == 1
        assert results["candidate_count"] == 0

        # Pattern should have been modified to approved status
        assert patterns[0].status == "approved"
        assert patterns[0].approved_at is not None

    def test_save_patterns_handles_database_failure(self, mock_db, caplog):
        """Should handle database insertion failures gracefully."""
        from src.review.models import LearnedPattern

        patterns = [
            LearnedPattern(
                pattern_type="reject_rule",
                pattern_name="Reject: is_in_risk_factors = True",
                pattern_definition={
                    "pattern_type": "reject_rule",
                    "conditions": [
                        {"field": "is_in_risk_factors", "op": "eq", "value": True}
                    ],
                },
                metric_id=None,
                precision_score=0.85,
                recall_score=0.75,
                f1_score=0.80,
                sample_count=10,
                status="candidate",
            ),
        ]

        mock_db.insert_learned_pattern.return_value = False  # Simulate failure

        analyzer = PatternAnalyzer(mock_db)
        results = analyzer.save_patterns(patterns)

        assert results["saved_count"] == 0
        assert "Failed to save pattern" in caplog.text

    def test_save_patterns_multiple_patterns(self, mock_db):
        """Should save multiple patterns with mixed approval status."""
        from src.review.models import LearnedPattern

        patterns = [
            LearnedPattern(
                pattern_type="reject_rule",
                pattern_name=f"Pattern {i}",
                pattern_definition={"pattern_type": "reject_rule", "conditions": []},
                metric_id=None,
                precision_score=0.85 if i == 0 else 0.95,  # First low, second high
                recall_score=0.75,
                f1_score=0.80,
                sample_count=10,
                status="candidate",
            )
            for i in range(2)
        ]

        mock_db.insert_learned_pattern.return_value = True

        analyzer = PatternAnalyzer(mock_db)
        results = analyzer.save_patterns(patterns, auto_approve_threshold=0.90)

        assert results["saved_count"] == 2
        assert results["approved_count"] == 1  # Only the second one
        assert results["candidate_count"] == 1  # Only the first one

# =============================================================================
# TestCrossValidation
# =============================================================================


class TestCrossValidation:
    """Tests for cross-validation functionality."""

    def test_stratified_k_fold_split_basic(self):
        """Should create k folds with stratified sampling."""
        # Create decisions with 60% reject, 40% accept
        decisions_data = [
            {"decision": "reject", "features": {"keyword_distance": i}}
            for i in range(30)
        ] + [
            {"decision": "accept", "features": {"keyword_distance": i}}
            for i in range(20)
        ]

        mock_db = Mock()
        analyzer = PatternAnalyzer(mock_db)

        splits = analyzer._stratified_k_fold_split(decisions_data, k=5)

        # Should create 5 splits
        assert len(splits) == 5

        # Each split should have train and test
        for train, test in splits:
            assert len(train) + len(test) == 50
            assert len(test) > 0
            assert len(train) > 0

            # Test set should preserve approximate 60/40 ratio
            test_rejects = sum(1 for d in test if d["decision"] == "reject")
            test_accepts = sum(1 for d in test if d["decision"] == "accept")

            # With k=5, each fold has ~10 items
            # 60% reject = 6, 40% accept = 4 (approximately)
            assert test_rejects >= 4  # Some variance expected
            assert test_accepts >= 2

    def test_stratified_k_fold_split_preserves_all_data(self):
        """Should include all decisions across folds."""
        decisions_data = [
            {"decision": "reject", "features": {}, "id": i} for i in range(10)
        ] + [{"decision": "accept", "features": {}, "id": i} for i in range(10, 15)]

        mock_db = Mock()
        analyzer = PatternAnalyzer(mock_db)

        splits = analyzer._stratified_k_fold_split(decisions_data, k=3)

        # Collect all test items across folds
        all_test_ids = set()
        for _, test in splits:
            for item in test:
                all_test_ids.add(item["id"])

        # Should cover all 15 items
        assert len(all_test_ids) == 15

    def test_discover_patterns_with_cv_insufficient_data(self):
        """Should raise ValueError if sample size too small."""
        # Create only 20 decisions (below minimum of 30)
        decisions_data = [
            {
                "candidate_id": i,
                "filing_id": 1,
                "decision": "reject" if i % 2 == 0 else "accept",
                "features": {"keyword_distance": i * 10},
            }
            for i in range(20)
        ]

        mock_db = Mock()
        mock_db.get_all_reviewed_candidates_with_decisions.return_value = (
            decisions_data
        )

        analyzer = PatternAnalyzer(mock_db)

        with pytest.raises(ValueError, match="Insufficient data"):
            analyzer.discover_patterns_with_cross_validation()

    def test_discover_patterns_with_cv_basic(self):
        """Should discover patterns with CV metrics."""
        # Create 50 decisions with clear pattern
        # Pattern: keyword_distance < 50 → reject (high precision)
        decisions_data = []
        for i in range(50):
            decision = "reject" if i < 25 else "accept"
            keyword_dist = i * 2  # 0, 2, 4, ..., 98

            decisions_data.append(
                {
                    "candidate_id": i,
                    "filing_id": 1,
                    "decision": decision,
                    "features": {
                        "keyword_distance": keyword_dist,
                        "keyword_position": "before",
                        "number_format": "integer",
                        "is_in_table": False,
                        "is_in_risk_factors": False,
                        "contains_definition_language": False,
                        "has_period_mention": False,
                        "value_magnitude": None,
                        "surrounding_numbers_count": 0,
                        "context_word_count": 50,
                    },
                }
            )

        mock_db = Mock()
        mock_db.get_all_reviewed_candidates_with_decisions.return_value = (
            decisions_data
        )

        analyzer = PatternAnalyzer(mock_db, min_pattern_precision=0.5)

        results = analyzer.discover_patterns_with_cross_validation(k=5)

        # Should find patterns
        assert len(results) > 0

        # Each result should have CV metrics
        for result in results:
            assert "pattern" in result
            assert "cv_precision_mean" in result
            assert "cv_precision_std" in result
            assert "cv_recall_mean" in result
            assert "cv_recall_std" in result
            assert "cv_f1_mean" in result
            assert "cv_f1_std" in result
            assert "is_stable" in result
            assert "fold_count" in result

            # Metrics should be valid
            assert 0.0 <= result["cv_precision_mean"] <= 1.0
            assert result["cv_precision_std"] >= 0.0
            assert result["fold_count"] >= 1

    def test_discover_patterns_with_cv_filters_unstable(self):
        """Should mark patterns with high variance as unstable."""
        # Create data that would produce unstable patterns
        # (This is tested implicitly by checking is_stable flag)
        decisions_data = []
        for i in range(60):
            decision = "reject" if i % 3 == 0 else "accept"

            decisions_data.append(
                {
                    "candidate_id": i,
                    "filing_id": 1,
                    "decision": decision,
                    "features": {
                        "keyword_distance": i * 5,
                        "keyword_position": "before",
                        "number_format": "integer",
                        "is_in_table": False,
                        "is_in_risk_factors": False,
                        "contains_definition_language": False,
                        "has_period_mention": False,
                        "value_magnitude": None,
                        "surrounding_numbers_count": 0,
                        "context_word_count": 50,
                    },
                }
            )

        mock_db = Mock()
        mock_db.get_all_reviewed_candidates_with_decisions.return_value = (
            decisions_data
        )

        analyzer = PatternAnalyzer(mock_db, min_pattern_precision=0.5)

        results = analyzer.discover_patterns_with_cross_validation(
            k=5, max_variance=0.1
        )

        # Should have is_stable flags
        # Note: Whether we actually get unstable patterns depends on the data
        # but the flag should be present
        assert all("is_stable" in r for r in results)

    def test_discover_patterns_with_cv_respects_min_precision(self):
        """Should filter patterns by minimum CV precision."""
        # Create 40 decisions
        decisions_data = []
        for i in range(40):
            decision = "reject" if i < 20 else "accept"

            decisions_data.append(
                {
                    "candidate_id": i,
                    "filing_id": 1,
                    "decision": decision,
                    "features": {
                        "keyword_distance": i * 10,
                        "keyword_position": "before",
                        "number_format": "integer",
                        "is_in_table": False,
                        "is_in_risk_factors": False,
                        "contains_definition_language": False,
                        "has_period_mention": False,
                        "value_magnitude": None,
                        "surrounding_numbers_count": 0,
                        "context_word_count": 50,
                    },
                }
            )

        mock_db = Mock()
        mock_db.get_all_reviewed_candidates_with_decisions.return_value = (
            decisions_data
        )

        # Set very high minimum precision
        analyzer = PatternAnalyzer(mock_db, min_pattern_precision=0.99)

        results = analyzer.discover_patterns_with_cross_validation(k=3)

        # Should filter most/all patterns
        # All returned patterns should meet minimum precision
        for result in results:
            assert result["cv_precision_mean"] >= 0.99

    def test_discover_patterns_with_cv_requires_min_fold_coverage(self):
        """Should skip patterns that don't appear in enough folds."""
        # Create small dataset where some patterns may not appear in all folds
        decisions_data = []
        for i in range(35):  # Just above minimum
            decision = "reject" if i < 18 else "accept"

            decisions_data.append(
                {
                    "candidate_id": i,
                    "filing_id": 1,
                    "decision": decision,
                    "features": {
                        "keyword_distance": i * 10,
                        "keyword_position": "before",
                        "number_format": "integer",
                        "is_in_table": False,
                        "is_in_risk_factors": False,
                        "contains_definition_language": False,
                        "has_period_mention": False,
                        "value_magnitude": None,
                        "surrounding_numbers_count": 0,
                        "context_word_count": 50,
                    },
                }
            )

        mock_db = Mock()
        mock_db.get_all_reviewed_candidates_with_decisions.return_value = (
            decisions_data
        )

        analyzer = PatternAnalyzer(mock_db, min_pattern_precision=0.5)

        results = analyzer.discover_patterns_with_cross_validation(k=5)

        # All returned patterns should appear in at least k//2 folds
        for result in results:
            assert result["fold_count"] >= 5 // 2  # At least 2 folds

    def test_discover_patterns_with_cv_sorts_by_f1(self):
        """Should sort results by F1 mean descending."""
        decisions_data = []
        for i in range(50):
            decision = "reject" if i < 25 else "accept"

            decisions_data.append(
                {
                    "candidate_id": i,
                    "filing_id": 1,
                    "decision": decision,
                    "features": {
                        "keyword_distance": i * 5,
                        "keyword_position": "before",
                        "number_format": "integer",
                        "is_in_table": False,
                        "is_in_risk_factors": False,
                        "contains_definition_language": False,
                        "has_period_mention": False,
                        "value_magnitude": None,
                        "surrounding_numbers_count": 0,
                        "context_word_count": 50,
                    },
                }
            )

        mock_db = Mock()
        mock_db.get_all_reviewed_candidates_with_decisions.return_value = (
            decisions_data
        )

        analyzer = PatternAnalyzer(mock_db, min_pattern_precision=0.5)

        results = analyzer.discover_patterns_with_cross_validation(k=5)

        # Should be sorted by F1 descending
        if len(results) > 1:
            for i in range(len(results) - 1):
                assert results[i]["cv_f1_mean"] >= results[i + 1]["cv_f1_mean"]


class TestPatternConflictDetection:
    """Tests for pattern conflict detection."""

    def test_detect_contradictory_patterns(self):
        """Should detect patterns with same conditions but different decisions."""
        from src.review.models import LearnedPattern

        # Create two patterns with same conditions but different decision types
        pattern1 = LearnedPattern(
            pattern_type="accept_rule",
            pattern_name="Accept: keyword_distance < 30",
            pattern_definition={
                "conditions": [{"field": "keyword_distance", "op": "lt", "value": 30}],
                "logic": "and",
            },
        )

        pattern2 = LearnedPattern(
            pattern_type="reject_rule",
            pattern_name="Reject: keyword_distance < 30",
            pattern_definition={
                "conditions": [{"field": "keyword_distance", "op": "lt", "value": 30}],
                "logic": "and",
            },
        )

        mock_db = Mock()
        analyzer = PatternAnalyzer(mock_db)

        result = analyzer.detect_pattern_conflicts([pattern1, pattern2])

        assert result["has_conflicts"] is True
        assert len(result["contradictory"]) == 1
        assert len(result["redundant"]) == 0
        assert "CONTRADICTORY" in result["warnings"][0]

    def test_detect_redundant_patterns_general_specific(self):
        """Should detect when one pattern is subset of another."""
        from src.review.models import LearnedPattern

        # General pattern: single condition
        pattern_general = LearnedPattern(
            pattern_type="reject_rule",
            pattern_name="Reject: is_in_table=True",
            pattern_definition={
                "conditions": [{"field": "is_in_table", "op": "eq", "value": True}],
                "logic": "and",
            },
        )

        # Specific pattern: includes general's condition plus another
        pattern_specific = LearnedPattern(
            pattern_type="reject_rule",
            pattern_name="Reject: is_in_table=True AND keyword_distance > 50",
            pattern_definition={
                "conditions": [
                    {"field": "is_in_table", "op": "eq", "value": True},
                    {"field": "keyword_distance", "op": "gt", "value": 50},
                ],
                "logic": "and",
            },
        )

        mock_db = Mock()
        analyzer = PatternAnalyzer(mock_db)

        result = analyzer.detect_pattern_conflicts([pattern_general, pattern_specific])

        assert result["has_conflicts"] is True
        assert len(result["contradictory"]) == 0
        assert len(result["redundant"]) == 1
        assert "REDUNDANT" in result["warnings"][0]

        # Check that the redundant pair is (general, specific)
        general, specific = result["redundant"][0]
        assert len(general.pattern_definition["conditions"]) == 1
        assert len(specific.pattern_definition["conditions"]) == 2

    def test_no_conflicts_when_patterns_independent(self):
        """Should not detect conflicts when patterns are independent."""
        from src.review.models import LearnedPattern

        pattern1 = LearnedPattern(
            pattern_type="reject_rule",
            pattern_name="Reject: is_in_risk_factors=True",
            pattern_definition={
                "conditions": [
                    {"field": "is_in_risk_factors", "op": "eq", "value": True}
                ],
                "logic": "and",
            },
        )

        pattern2 = LearnedPattern(
            pattern_type="reject_rule",
            pattern_name="Reject: keyword_distance > 100",
            pattern_definition={
                "conditions": [
                    {"field": "keyword_distance", "op": "gt", "value": 100}
                ],
                "logic": "and",
            },
        )

        mock_db = Mock()
        analyzer = PatternAnalyzer(mock_db)

        result = analyzer.detect_pattern_conflicts([pattern1, pattern2])

        assert result["has_conflicts"] is False
        assert len(result["contradictory"]) == 0
        assert len(result["redundant"]) == 0
        assert len(result["warnings"]) == 0

    def test_conditions_equivalent_order_independent(self):
        """Should detect equivalent conditions regardless of order."""
        from src.review.models import LearnedPattern

        pattern1 = LearnedPattern(
            pattern_type="reject_rule",
            pattern_name="Reject: A AND B",
            pattern_definition={
                "conditions": [
                    {"field": "is_in_table", "op": "eq", "value": True},
                    {"field": "keyword_distance", "op": "gt", "value": 50},
                ],
                "logic": "and",
            },
        )

        # Same conditions, different order, different decision
        pattern2 = LearnedPattern(
            pattern_type="accept_rule",
            pattern_name="Accept: B AND A",
            pattern_definition={
                "conditions": [
                    {"field": "keyword_distance", "op": "gt", "value": 50},
                    {"field": "is_in_table", "op": "eq", "value": True},
                ],
                "logic": "and",
            },
        )

        mock_db = Mock()
        analyzer = PatternAnalyzer(mock_db)

        result = analyzer.detect_pattern_conflicts([pattern1, pattern2])

        # Should detect as contradictory (same conditions, different decisions)
        assert result["has_conflicts"] is True
        assert len(result["contradictory"]) == 1

    def test_no_redundancy_when_different_decision_types(self):
        """Should not flag redundancy for subset patterns with different decisions."""
        from src.review.models import LearnedPattern

        # General accept pattern
        pattern1 = LearnedPattern(
            pattern_type="accept_rule",
            pattern_name="Accept: has_definition=True",
            pattern_definition={
                "conditions": [
                    {"field": "contains_definition_language", "op": "eq", "value": True}
                ],
                "logic": "and",
            },
        )

        # Specific reject pattern (includes pattern1's condition)
        pattern2 = LearnedPattern(
            pattern_type="reject_rule",
            pattern_name="Reject: has_definition=True AND is_in_risk=True",
            pattern_definition={
                "conditions": [
                    {"field": "contains_definition_language", "op": "eq", "value": True},
                    {"field": "is_in_risk_factors", "op": "eq", "value": True},
                ],
                "logic": "and",
            },
        )

        mock_db = Mock()
        analyzer = PatternAnalyzer(mock_db)

        result = analyzer.detect_pattern_conflicts([pattern1, pattern2])

        # Should NOT detect redundancy (different decision types)
        assert len(result["redundant"]) == 0

    def test_multiple_conflicts_detected(self):
        """Should detect multiple conflicts in a pattern set."""
        from src.review.models import LearnedPattern

        patterns = [
            # Pair 1: Contradictory
            LearnedPattern(
                pattern_type="accept_rule",
                pattern_name="Accept: distance < 30",
                pattern_definition={
                    "conditions": [
                        {"field": "keyword_distance", "op": "lt", "value": 30}
                    ],
                    "logic": "and",
                },
            ),
            LearnedPattern(
                pattern_type="reject_rule",
                pattern_name="Reject: distance < 30",
                pattern_definition={
                    "conditions": [
                        {"field": "keyword_distance", "op": "lt", "value": 30}
                    ],
                    "logic": "and",
                },
            ),
            # Pair 2: Redundant (general)
            LearnedPattern(
                pattern_type="reject_rule",
                pattern_name="Reject: in_table=True",
                pattern_definition={
                    "conditions": [{"field": "is_in_table", "op": "eq", "value": True}],
                    "logic": "and",
                },
            ),
            # Pair 2: Redundant (specific)
            LearnedPattern(
                pattern_type="reject_rule",
                pattern_name="Reject: in_table=True AND distance > 50",
                pattern_definition={
                    "conditions": [
                        {"field": "is_in_table", "op": "eq", "value": True},
                        {"field": "keyword_distance", "op": "gt", "value": 50},
                    ],
                    "logic": "and",
                },
            ),
        ]

        mock_db = Mock()
        analyzer = PatternAnalyzer(mock_db)

        result = analyzer.detect_pattern_conflicts(patterns)

        assert result["has_conflicts"] is True
        assert len(result["contradictory"]) == 1
        assert len(result["redundant"]) == 1
        assert len(result["warnings"]) == 2

    def test_empty_pattern_list(self):
        """Should handle empty pattern list without errors."""
        mock_db = Mock()
        analyzer = PatternAnalyzer(mock_db)

        result = analyzer.detect_pattern_conflicts([])

        assert result["has_conflicts"] is False
        assert len(result["contradictory"]) == 0
        assert len(result["redundant"]) == 0
        assert len(result["warnings"]) == 0

    def test_single_pattern_no_conflicts(self):
        """Should not detect conflicts with single pattern."""
        from src.review.models import LearnedPattern

        pattern = LearnedPattern(
            pattern_type="reject_rule",
            pattern_name="Reject: distance > 100",
            pattern_definition={
                "conditions": [
                    {"field": "keyword_distance", "op": "gt", "value": 100}
                ],
                "logic": "and",
            },
        )

        mock_db = Mock()
        analyzer = PatternAnalyzer(mock_db)

        result = analyzer.detect_pattern_conflicts([pattern])

        assert result["has_conflicts"] is False
        assert len(result["contradictory"]) == 0
        assert len(result["redundant"]) == 0
        assert len(result["warnings"]) == 0


# =============================================================================
# P2.2: Database-Side Pattern Evaluation Tests
# =============================================================================


class TestDatabaseSideEvaluation:
    """Tests for database-side pattern evaluation (P2.2)."""

    def test_build_jsonb_where_clause_numeric_lt(self):
        """Should generate correct SQL for numeric less-than condition."""
        mock_db = Mock()
        analyzer = PatternAnalyzer(mock_db)

        pattern_def = {
            "conditions": [{"field": "keyword_distance", "op": "lt", "value": 30}],
            "logic": "and",
        }

        where_clause, params = analyzer._build_jsonb_where_clause(pattern_def)

        assert where_clause == "(features->>'keyword_distance')::numeric < %s"
        assert params == [30]

    def test_build_jsonb_where_clause_boolean_eq(self):
        """Should generate correct SQL for boolean equality condition."""
        mock_db = Mock()
        analyzer = PatternAnalyzer(mock_db)

        pattern_def = {
            "conditions": [
                {"field": "is_in_risk_factors", "op": "eq", "value": True}
            ],
            "logic": "and",
        }

        where_clause, params = analyzer._build_jsonb_where_clause(pattern_def)

        assert where_clause == "(features->>'is_in_risk_factors')::boolean = %s"
        assert params == [True]

    def test_build_jsonb_where_clause_string_eq(self):
        """Should generate correct SQL for string equality condition."""
        mock_db = Mock()
        analyzer = PatternAnalyzer(mock_db)

        pattern_def = {
            "conditions": [
                {"field": "keyword_position", "op": "eq", "value": "before"}
            ],
            "logic": "and",
        }

        where_clause, params = analyzer._build_jsonb_where_clause(pattern_def)

        assert where_clause == "(features->>'keyword_position') = %s"
        assert params == ["before"]

    def test_build_jsonb_where_clause_multiple_and(self):
        """Should combine multiple conditions with AND."""
        mock_db = Mock()
        analyzer = PatternAnalyzer(mock_db)

        pattern_def = {
            "conditions": [
                {"field": "keyword_distance", "op": "lt", "value": 30},
                {"field": "is_in_risk_factors", "op": "eq", "value": False},
            ],
            "logic": "and",
        }

        where_clause, params = analyzer._build_jsonb_where_clause(pattern_def)

        expected_clause = (
            "((features->>'keyword_distance')::numeric < %s AND "
            "(features->>'is_in_risk_factors')::boolean = %s)"
        )
        assert where_clause == expected_clause
        assert params == [30, False]

    def test_build_jsonb_where_clause_multiple_or(self):
        """Should combine multiple conditions with OR."""
        mock_db = Mock()
        analyzer = PatternAnalyzer(mock_db)

        pattern_def = {
            "conditions": [
                {"field": "keyword_distance", "op": "gt", "value": 100},
                {"field": "is_in_table", "op": "eq", "value": True},
            ],
            "logic": "or",
        }

        where_clause, params = analyzer._build_jsonb_where_clause(pattern_def)

        expected_clause = (
            "((features->>'keyword_distance')::numeric > %s OR "
            "(features->>'is_in_table')::boolean = %s)"
        )
        assert where_clause == expected_clause
        assert params == [100, True]

    def test_build_jsonb_where_clause_all_operators(self):
        """Should handle all comparison operators correctly."""
        mock_db = Mock()
        analyzer = PatternAnalyzer(mock_db)

        operators_tests = [
            ("eq", "="),
            ("ne", "!="),
            ("gt", ">"),
            ("lt", "<"),
            ("gte", ">="),
            ("lte", "<="),
        ]

        for op_code, op_symbol in operators_tests:
            pattern_def = {
                "conditions": [
                    {"field": "keyword_distance", "op": op_code, "value": 50}
                ],
                "logic": "and",
            }

            where_clause, params = analyzer._build_jsonb_where_clause(pattern_def)

            expected_clause = f"(features->>'keyword_distance')::numeric {op_symbol} %s"
            assert where_clause == expected_clause
            assert params == [50]

    def test_build_jsonb_where_clause_in_operator(self):
        """Should handle IN operator with array."""
        mock_db = Mock()
        analyzer = PatternAnalyzer(mock_db)

        pattern_def = {
            "conditions": [
                {
                    "field": "keyword_position",
                    "op": "in",
                    "value": ["before", "after"],
                }
            ],
            "logic": "and",
        }

        where_clause, params = analyzer._build_jsonb_where_clause(pattern_def)

        assert where_clause == "(features->>'keyword_position') = ANY(%s)"
        assert params == [["before", "after"]]

    def test_build_jsonb_where_clause_contains_operator(self):
        """Should handle CONTAINS operator with LIKE."""
        mock_db = Mock()
        analyzer = PatternAnalyzer(mock_db)

        pattern_def = {
            "conditions": [
                {"field": "section_name", "op": "contains", "value": "Risk"}
            ],
            "logic": "and",
        }

        where_clause, params = analyzer._build_jsonb_where_clause(pattern_def)

        assert where_clause == "(features->>'section_name') LIKE %s"
        assert params == ["%Risk%"]

    def test_build_jsonb_where_clause_empty_conditions(self):
        """Should handle empty conditions gracefully."""
        mock_db = Mock()
        analyzer = PatternAnalyzer(mock_db)

        pattern_def = {"conditions": [], "logic": "and"}

        where_clause, params = analyzer._build_jsonb_where_clause(pattern_def)

        assert where_clause == "TRUE"
        assert params == []

    def test_build_jsonb_where_clause_unknown_operator(self):
        """Should skip unknown operators with warning."""
        mock_db = Mock()
        analyzer = PatternAnalyzer(mock_db)

        pattern_def = {
            "conditions": [
                {"field": "keyword_distance", "op": "unknown_op", "value": 50}
            ],
            "logic": "and",
        }

        where_clause, params = analyzer._build_jsonb_where_clause(pattern_def)

        # Unknown operator should be skipped, resulting in TRUE
        assert where_clause == "TRUE"
        assert params == []


# =============================================================================
# P2.1: Two-Feature Conjunctive Pattern Tests
# =============================================================================


class TestTwoFeaturePatterns:
    """Tests for two-feature conjunctive pattern generation (P2.1)."""

    def test_generate_two_feature_patterns_basic(self, sample_decisions_data):
        """Should generate AND combinations of top features."""
        mock_db = Mock()
        analyzer = PatternAnalyzer(mock_db, min_pattern_support=1)

        patterns = analyzer._generate_two_feature_patterns(
            sample_decisions_data,
            target_decision="reject",
            max_features=3,
        )

        # Should generate patterns combining pairs of top features
        assert len(patterns) > 0

        # Each pattern should have two conditions
        for pattern in patterns:
            assert len(pattern["conditions"]) == 2
            assert pattern["logic"] == "and"
            assert pattern["pattern_type"] == "reject_rule"

    def test_generate_two_feature_patterns_insufficient_features(self):
        """Should warn and return empty list when fewer than 2 top features."""
        mock_db = Mock()
        analyzer = PatternAnalyzer(mock_db)

        # Only one decision - insufficient for two features
        decisions_data = [
            {
                "candidate_id": 1,
                "decision": "reject",
                "features": {
                    "keyword_distance": 100,
                    "is_in_risk_factors": True,
                },
            }
        ]

        patterns = analyzer._generate_two_feature_patterns(
            decisions_data,
            target_decision="reject",
        )

        # Should return empty list
        assert patterns == []

    def test_discover_patterns_with_two_feature_flag(self, sample_decisions_data):
        """Should include two-feature patterns when flag is True."""
        mock_db = Mock()
        mock_db.get_review_candidates_with_decisions.return_value = (
            sample_decisions_data
        )

        analyzer = PatternAnalyzer(mock_db, min_pattern_support=1, min_pattern_precision=0.5)

        patterns = analyzer.discover_patterns(
            filing_id=100,
            pattern_type="reject_rule",
            include_two_feature_patterns=True,
        )

        # Should have both single-feature and two-feature patterns
        single_feature_count = sum(
            1 for p in patterns if len(p.pattern_definition["conditions"]) == 1
        )
        two_feature_count = sum(
            1 for p in patterns if len(p.pattern_definition["conditions"]) == 2
        )

        assert single_feature_count > 0
        assert two_feature_count > 0

    def test_discover_patterns_without_two_feature_flag(self, sample_decisions_data):
        """Should not include two-feature patterns when flag is False (default)."""
        mock_db = Mock()
        mock_db.get_review_candidates_with_decisions.return_value = (
            sample_decisions_data
        )

        analyzer = PatternAnalyzer(mock_db, min_pattern_support=1, min_pattern_precision=0.5)

        patterns = analyzer.discover_patterns(
            filing_id=100,
            pattern_type="reject_rule",
            include_two_feature_patterns=False,
        )

        # Should have only single-feature patterns
        for pattern in patterns:
            assert len(pattern.pattern_definition["conditions"]) == 1

    def test_two_feature_pattern_names_readable(self, sample_decisions_data):
        """Should generate human-readable names for two-feature patterns."""
        mock_db = Mock()
        analyzer = PatternAnalyzer(mock_db, min_pattern_support=1)

        # Create a two-feature pattern manually
        pattern_def = {
            "pattern_type": "reject_rule",
            "conditions": [
                {"field": "keyword_distance", "op": "gte", "value": 75},
                {"field": "is_in_risk_factors", "op": "eq", "value": "True"},
            ],
            "logic": "and",
        }

        name = analyzer.generate_pattern_name(pattern_def, "reject_rule")

        # Should show both conditions with AND
        assert "keyword_distance" in name
        assert "is_in_risk_factors" in name
        assert "AND" in name or "&" in name
        assert "Reject" in name

    def test_two_feature_patterns_use_top_features(self, sample_decisions_data):
        """Should combine top features by importance, not all features."""
        mock_db = Mock()
        analyzer = PatternAnalyzer(mock_db)

        patterns = analyzer._generate_two_feature_patterns(
            sample_decisions_data,
            target_decision="reject",
            max_features=2,  # Limit to top 2
        )

        # Count unique features used in patterns
        features_used = set()
        for pattern in patterns:
            for cond in pattern["conditions"]:
                features_used.add(cond["field"])

        # Should use at most 2 features (since max_features=2)
        assert len(features_used) <= 2


class TestPatternExplanations:
    """Tests for pattern explanation generation (P2.3)."""

    @pytest.fixture
    def sample_pattern_single_condition(self):
        """Sample pattern with single condition."""
        pattern = LearnedPattern(
            pattern_type="reject_rule",
            metric_id=None,
            pattern_name="Reject: keyword_distance > 75",
            pattern_definition={
                "conditions": [
                    {"field": "keyword_distance", "op": "gt", "value": 75}
                ],
                "logic": "and",
            },
            precision_score=0.87,
            recall_score=0.32,
            f1_score=0.47,
            sample_count=15,
        )
        # Add confusion matrix counts as instance attributes (not in __init__)
        pattern.true_positives = 13
        pattern.false_positives = 2
        pattern.false_negatives = 28
        return pattern

    @pytest.fixture
    def sample_pattern_multi_condition(self):
        """Sample pattern with multiple conditions."""
        pattern = LearnedPattern(
            pattern_type="accept_rule",
            metric_id="active_customers",
            pattern_name="Accept: keyword_distance < 30 AND contains_definition_language = True",
            pattern_definition={
                "conditions": [
                    {"field": "keyword_distance", "op": "lt", "value": 30},
                    {
                        "field": "contains_definition_language",
                        "op": "eq",
                        "value": True,
                    },
                ],
                "logic": "and",
            },
            precision_score=0.92,
            recall_score=0.65,
            f1_score=0.76,
            sample_count=25,
        )
        # Add confusion matrix counts as instance attributes (not in __init__)
        pattern.true_positives = 23
        pattern.false_positives = 2
        pattern.false_negatives = 12
        return pattern

    def test_describe_condition_numeric_gt(self, mock_db):
        """Should generate readable description for numeric greater-than condition."""
        analyzer = PatternAnalyzer(mock_db)

        condition = {"field": "keyword_distance", "op": "gt", "value": 75}
        description = analyzer._describe_condition(condition)

        assert (
            "the distance from the number to the metric keyword is greater than 75"
            in description
        )

    def test_describe_condition_boolean_eq(self, mock_db):
        """Should generate readable description for boolean equality condition."""
        analyzer = PatternAnalyzer(mock_db)

        condition = {"field": "is_in_risk_factors", "op": "eq", "value": True}
        description = analyzer._describe_condition(condition)

        assert "the candidate is in the risk factors section is True" in description

    def test_describe_condition_all_operators(self, mock_db):
        """Should handle all operator types correctly."""
        analyzer = PatternAnalyzer(mock_db)

        test_cases = [
            (
                {"field": "keyword_distance", "op": "lt", "value": 30},
                "is less than",
            ),
            (
                {"field": "keyword_distance", "op": "lte", "value": 30},
                "is at most",
            ),
            (
                {"field": "keyword_distance", "op": "gte", "value": 50},
                "is at least",
            ),
            (
                {"field": "number_format", "op": "in", "value": ["currency", "percentage"]},
                "is one of",
            ),
        ]

        for condition, expected_phrase in test_cases:
            description = analyzer._describe_condition(condition)
            assert expected_phrase in description

    def test_generate_pattern_description_single_condition(
        self, mock_db, sample_pattern_single_condition
    ):
        """Should generate description for single-condition pattern."""
        analyzer = PatternAnalyzer(mock_db)

        description = analyzer._generate_pattern_description(
            sample_pattern_single_condition
        )

        assert "This pattern rejects candidates where" in description
        assert "the distance from the number to the metric keyword" in description
        assert "is greater than 75" in description

    def test_generate_pattern_description_multi_condition_and(
        self, mock_db, sample_pattern_multi_condition
    ):
        """Should generate description for multi-condition AND pattern."""
        analyzer = PatternAnalyzer(mock_db)

        description = analyzer._generate_pattern_description(
            sample_pattern_multi_condition
        )

        assert "This pattern accepts candidates where ALL of the following are true:" in description
        assert "1." in description  # Numbered list
        assert "2." in description
        assert "the distance from the number to the metric keyword" in description
        assert "the context contains definition language" in description

    def test_generate_pattern_description_empty_conditions(self, mock_db):
        """Should handle pattern with no conditions."""
        analyzer = PatternAnalyzer(mock_db)

        pattern = LearnedPattern(
            pattern_type="accept_rule",
            metric_id=None,
            pattern_name="Accept: all",
            pattern_definition={"conditions": [], "logic": "and"},
            precision_score=0.50,
            recall_score=1.0,
            f1_score=0.67,
        )

        description = analyzer._generate_pattern_description(pattern)

        assert "no conditions" in description.lower()
        assert "matches all" in description.lower()

    def test_format_performance_metrics_with_counts(
        self, mock_db, sample_pattern_single_condition
    ):
        """Should format performance metrics with counts interpretation."""
        analyzer = PatternAnalyzer(mock_db)

        metrics_text = analyzer._format_performance_metrics(
            sample_pattern_single_condition
        )

        # Should include precision with interpretation
        assert "Precision: 87%" in metrics_text
        assert "13/15" in metrics_text  # TP/(TP+FP)

        # Should include recall with interpretation
        assert "Recall: 32%" in metrics_text
        assert "13/41" in metrics_text  # TP/(TP+FN)

        # Should include F1 score
        assert "F1 Score: 47%" in metrics_text

    def test_format_performance_metrics_without_counts(self, mock_db):
        """Should format performance metrics without count details if unavailable."""
        analyzer = PatternAnalyzer(mock_db)

        pattern = LearnedPattern(
            pattern_type="reject_rule",
            metric_id=None,
            pattern_name="Test Pattern",
            pattern_definition={"conditions": [], "logic": "and"},
            precision_score=0.75,
            recall_score=0.60,
            f1_score=0.67,
        )

        metrics_text = analyzer._format_performance_metrics(pattern)

        # Should include percentages without counts
        assert "Precision: 75%" in metrics_text
        assert "Recall: 60%" in metrics_text
        assert "F1 Score: 67%" in metrics_text

        # Should not include count interpretations
        assert "/" not in metrics_text

    def test_get_pattern_examples_basic(self, mock_db, sample_pattern_single_condition):
        """Should return formatted examples for matching candidates."""
        analyzer = PatternAnalyzer(mock_db)

        # Mock candidates data (as returned from database)
        sample_data = [
            {
                "candidate_id": 1,
                "filing_id": 1,
                "context_text": "Revenue was $5M and we saw strong growth",
                "raw_number_text": "5",
                "triggering_keyword": "customers",
                "decision": "reject",
                "suggested_metric_id": None,
                "assigned_metric_id": None,
                "rejection_category": "wrong_metric",
                "features": {"keyword_distance": 80},  # Matches: > 75
            },
            {
                "candidate_id": 2,
                "filing_id": 1,
                "context_text": "We have 500 active customers in Q4",
                "raw_number_text": "500",
                "triggering_keyword": "customers",
                "decision": "reject",
                "suggested_metric_id": None,
                "assigned_metric_id": None,
                "rejection_category": "wrong_metric",
                "features": {"keyword_distance": 90},  # Matches: > 75
            },
            {
                "candidate_id": 3,
                "filing_id": 1,
                "context_text": "Customer count increased to 1000",
                "raw_number_text": "1000",
                "triggering_keyword": "customer",
                "decision": "accept",
                "suggested_metric_id": "active_customers",
                "assigned_metric_id": "active_customers",
                "rejection_category": None,
                "features": {"keyword_distance": 20},  # Does not match
            },
        ]

        mock_db.get_review_candidates_with_decisions.return_value = sample_data

        examples = analyzer._get_pattern_examples(
            sample_pattern_single_condition,
            filing_id=1,
            metric_id=None,
            num_examples=3,
        )

        # Should return 2 matching examples
        assert len(examples) == 2

        # Examples should include context, keyword, value, and result
        assert "Revenue was $5M" in examples[0]
        assert "keyword: customers" in examples[0]
        assert "value: 5" in examples[0]
        assert "✓" in examples[0]  # Correct rejection

    def test_get_pattern_examples_limit(self, mock_db, sample_pattern_single_condition):
        """Should limit examples to num_examples parameter."""
        analyzer = PatternAnalyzer(mock_db)

        # Create 10 matching candidates
        sample_data = [
            {
                "candidate_id": i,
                "filing_id": 1,
                "context_text": f"Context {i}",
                "raw_number_text": str(i),
                "triggering_keyword": "customers",
                "decision": "reject",
                "suggested_metric_id": None,
                "assigned_metric_id": None,
                "rejection_category": "wrong_metric",
                "features": {"keyword_distance": 80 + i},  # All match > 75
            }
            for i in range(10)
        ]

        mock_db.get_review_candidates_with_decisions.return_value = sample_data

        examples = analyzer._get_pattern_examples(
            sample_pattern_single_condition,
            filing_id=1,
            metric_id=None,
            num_examples=3,
        )

        # Should limit to 3 examples
        assert len(examples) == 3

    def test_generate_pattern_explanation_full(
        self, mock_db, sample_pattern_single_condition
    ):
        """Should generate complete explanation with all sections."""
        analyzer = PatternAnalyzer(mock_db)

        # Mock candidates data (as returned from database)
        sample_data = [
            {
                "candidate_id": 1,
                "filing_id": 1,
                "context_text": "Revenue was $5M and we saw strong growth",
                "raw_number_text": "5",
                "triggering_keyword": "customers",
                "decision": "reject",
                "suggested_metric_id": None,
                "assigned_metric_id": None,
                "rejection_category": "wrong_metric",
                "features": {"keyword_distance": 80},
            }
        ]
        mock_db.get_review_candidates_with_decisions.return_value = sample_data

        explanation = analyzer.generate_pattern_explanation(
            sample_pattern_single_condition, filing_id=1
        )

        # Should include pattern name
        assert 'Pattern: "Reject: keyword_distance > 75"' in explanation

        # Should include explanation section
        assert "Explanation:" in explanation
        assert "This pattern rejects candidates where" in explanation

        # Should include examples section
        assert "Examples:" in explanation
        assert "Revenue was $5M" in explanation

        # Should include performance section
        assert "Performance:" in explanation
        assert "Precision: 87%" in explanation
        assert "Recall: 32%" in explanation

    def test_generate_pattern_explanation_no_examples(
        self, mock_db, sample_pattern_single_condition
    ):
        """Should handle case where no matching examples exist."""
        analyzer = PatternAnalyzer(mock_db)

        # Mock no matching candidates
        mock_db.get_review_candidates_with_decisions.return_value = []

        explanation = analyzer.generate_pattern_explanation(
            sample_pattern_single_condition, filing_id=1
        )

        # Should still include pattern name and explanation
        assert 'Pattern: "Reject: keyword_distance > 75"' in explanation
        assert "Explanation:" in explanation

        # Should not have examples section (or empty)
        # Performance section should still be present
        assert "Performance:" in explanation
