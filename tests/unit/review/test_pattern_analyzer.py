"""
Unit tests for pattern_analyzer module.

Tests PatternAnalyzer class for analyzing review decisions and computing feature importance.
Target coverage: 85-90%
"""

from unittest.mock import Mock

import pytest

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

    def test_analyze_decisions_not_implemented_without_filing_id(self, mock_db):
        """Should raise NotImplementedError when filing_id is None (MVP)."""
        analyzer = PatternAnalyzer(mock_db)

        with pytest.raises(NotImplementedError, match="not yet implemented"):
            analyzer.analyze_decisions(filing_id=None)

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
                {"feature": "is_in_risk_factors", "operator": "eq", "value": "False"}
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
                {"feature": "keyword_distance", "operator": "gte", "value": 100.0}
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
                {"feature": "keyword_distance", "operator": "gte", "value": 100.0},
                {"feature": "is_in_risk_factors", "operator": "eq", "value": "True"},
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
                    {"feature": "keyword_distance", "operator": op_code, "value": 50}
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
        pattern_features = [p["conditions"][0]["feature"] for p in patterns]
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
            if p["conditions"][0]["feature"] == "keyword_distance"
        ]

        # Should have 6 patterns: 3 quartiles × 2 operators (lte, gte)
        assert len(distance_patterns) == 6

        # Check operators
        operators = [p["conditions"][0]["operator"] for p in distance_patterns]
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
        pattern_features = [p["conditions"][0]["feature"] for p in patterns]
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
            if p["conditions"][0]["feature"] == "is_in_risk_factors"
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
                {"feature": "is_in_risk_factors", "operator": "eq", "value": True}
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
                {"feature": "is_in_risk_factors", "operator": "eq", "value": True}
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
                {"feature": "keyword_distance", "operator": "gte", "value": 100}
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
                pattern_id=0,
                pattern_name="Reject: is_in_risk_factors = True",
                pattern_type="reject_rule",
                pattern_definition={
                    "pattern_type": "reject_rule",
                    "conditions": [
                        {"feature": "is_in_risk_factors", "operator": "eq", "value": True}
                    ],
                },
                metric_id=None,
                precision_score=0.85,
                recall_score=0.75,
                f1_score=0.80,
                sample_count=10,
                status="candidate",
                created_at=None,
                approved_at=None,
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
                pattern_id=0,
                pattern_name="Reject: is_in_risk_factors = True",
                pattern_type="reject_rule",
                pattern_definition={
                    "pattern_type": "reject_rule",
                    "conditions": [
                        {"feature": "is_in_risk_factors", "operator": "eq", "value": True}
                    ],
                },
                metric_id=None,
                precision_score=0.95,  # Above threshold
                recall_score=0.85,
                f1_score=0.90,
                sample_count=20,
                status="candidate",
                created_at=None,
                approved_at=None,
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
                pattern_id=0,
                pattern_name="Reject: is_in_risk_factors = True",
                pattern_type="reject_rule",
                pattern_definition={
                    "pattern_type": "reject_rule",
                    "conditions": [
                        {"feature": "is_in_risk_factors", "operator": "eq", "value": True}
                    ],
                },
                metric_id=None,
                precision_score=0.85,
                recall_score=0.75,
                f1_score=0.80,
                sample_count=10,
                status="candidate",
                created_at=None,
                approved_at=None,
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
                pattern_id=0,
                pattern_name=f"Pattern {i}",
                pattern_type="reject_rule",
                pattern_definition={"pattern_type": "reject_rule", "conditions": []},
                metric_id=None,
                precision_score=0.85 if i == 0 else 0.95,  # First low, second high
                recall_score=0.75,
                f1_score=0.80,
                sample_count=10,
                status="candidate",
                created_at=None,
                approved_at=None,
            )
            for i in range(2)
        ]

        mock_db.insert_learned_pattern.return_value = True

        analyzer = PatternAnalyzer(mock_db)
        results = analyzer.save_patterns(patterns, auto_approve_threshold=0.90)

        assert results["saved_count"] == 2
        assert results["approved_count"] == 1  # Only the second one
        assert results["candidate_count"] == 1  # Only the first one
