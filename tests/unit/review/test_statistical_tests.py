"""
Unit tests for statistical_tests module.

Tests pure Python implementations of chi-squared, t-test, and performance metrics.
Target coverage: 90-95%
"""

import pytest

from src.review.statistical_tests import (
    _approximate_chi_squared_p_value,
    _approximate_t_test_p_value,
    _normal_cdf,
    chi_squared_test,
    compute_performance_metrics,
    interpret_significance,
    t_test_independent,
)

# =============================================================================
# TestChiSquaredTest
# =============================================================================


class TestChiSquaredTest:
    """Tests for chi_squared_test function."""

    def test_chi_squared_basic_2x2(self):
        """Should compute chi-squared for 2x2 contingency table."""
        feature_values = ["before", "before", "after", "after"]
        decision_values = ["accept", "reject", "accept", "reject"]
        result = chi_squared_test(feature_values, decision_values)

        assert "chi_squared" in result
        assert "degrees_of_freedom" in result
        assert result["degrees_of_freedom"] == 1  # (2-1) * (2-1)
        assert result["chi_squared"] == 0.0  # Perfect independence

    def test_chi_squared_independence(self):
        """Should detect independence (low chi-squared)."""
        # Feature uniformly distributed across decisions (larger sample for validity)
        feature_values = ["A"] * 20 + ["B"] * 20  # 20 A, 20 B
        decision_values = (
            ["accept"] * 10
            + ["reject"] * 10  # 10 accept, 10 reject for A
            + ["accept"] * 10
            + ["reject"] * 10  # 10 accept, 10 reject for B
        )
        result = chi_squared_test(feature_values, decision_values)

        # Should be very low chi-squared (near 0) for uniform distribution
        assert result["chi_squared"] < 0.1
        assert result["is_valid"] is True

    def test_chi_squared_strong_association(self):
        """Should detect strong association (high chi-squared)."""
        # Feature strongly correlated with decision
        feature_values = ["risk_factors"] * 10 + ["not_risk"] * 10  # 10 risk, 10 not_risk
        decision_values = (
            ["reject"] * 9
            + ["accept"] * 1  # 9 reject, 1 accept in risk_factors
            + ["accept"] * 9
            + ["reject"] * 1  # 9 accept, 1 reject in not_risk
        )
        result = chi_squared_test(feature_values, decision_values)

        # Should have high chi-squared (strong association)
        assert result["chi_squared"] > 10.0
        assert result["is_valid"] is True

    def test_chi_squared_low_expected_frequency_warning(self):
        """Should warn when expected frequencies < 5."""
        # Very small sample with rare category
        feature_values = ["A", "B"]  # Only 2 samples
        decision_values = ["accept", "reject"]
        result = chi_squared_test(feature_values, decision_values, min_expected_frequency=5.0)

        assert result["is_valid"] is False
        assert result["warning"] is not None
        assert "Low expected frequency" in result["warning"]
        assert result["min_expected"] < 5.0

    def test_chi_squared_empty_input_error(self):
        """Should raise ValueError for empty inputs."""
        with pytest.raises(ValueError, match="cannot be empty"):
            chi_squared_test([], [])

    def test_chi_squared_mismatched_length_error(self):
        """Should raise ValueError for mismatched lengths."""
        with pytest.raises(ValueError, match="must have same length"):
            chi_squared_test(["A", "B"], ["accept"])

    def test_chi_squared_multiple_categories(self):
        """Should handle multiple feature values and decisions."""
        # Create 3x3 contingency table with uniform distribution
        # Each combination appears exactly 10 times
        feature_values = []
        decision_values = []
        for feat in ["A", "B", "C"]:
            for dec in ["accept", "reject", "reclassify"]:
                feature_values.extend([feat] * 10)
                decision_values.extend([dec] * 10)

        result = chi_squared_test(feature_values, decision_values)

        assert result["degrees_of_freedom"] == (3 - 1) * (3 - 1)  # 4
        assert result["chi_squared"] == pytest.approx(0.0, abs=0.01)  # Perfect independence

    def test_chi_squared_computes_pvalue_large_df(self):
        """Should compute p-value for large degrees of freedom (df > 5)."""
        # Create contingency table with df > 5: 4 features × 3 decisions = df = 6
        feature_values = []
        decision_values = []
        for feat in ["A", "B", "C", "D"]:  # 4 categories
            for dec in ["accept", "reject", "reclassify"]:  # 3 decisions
                feature_values.extend([feat] * 10)
                decision_values.extend([dec] * 10)

        result = chi_squared_test(feature_values, decision_values)

        assert result["degrees_of_freedom"] == 6  # (4-1) * (3-1)
        assert result["p_value"] is not None  # Should compute for df > 5
        assert 0.0 <= result["p_value"] <= 1.0  # Valid p-value range

    def test_chi_squared_returns_none_pvalue_small_df(self):
        """Should return p_value=None for small degrees of freedom (df <= 5)."""
        # Small contingency table: df = (2-1) * (2-1) = 1 < 5
        feature_values = ["A", "B", "C"]
        decision_values = ["accept", "reject", "accept"]
        result = chi_squared_test(feature_values, decision_values)

        assert result["degrees_of_freedom"] <= 5
        assert result["p_value"] is None  # Approximation not reliable for small df


# =============================================================================
# TestTTestIndependent
# =============================================================================


class TestTTestIndependent:
    """Tests for t_test_independent function."""

    def test_t_test_equal_variance_students(self):
        """Should compute Student's t-test correctly."""
        group1 = [10.0, 12.0, 14.0, 16.0, 18.0]  # mean=14
        group2 = [20.0, 22.0, 24.0, 26.0, 28.0]  # mean=24
        result = t_test_independent(group1, group2, equal_variance=True)

        assert "t_statistic" in result
        assert "effect_size" in result
        assert "mean_difference" in result
        assert result["mean_difference"] == -10.0  # 14 - 24
        assert result["degrees_of_freedom"] == 8  # 5 + 5 - 2
        assert result["t_statistic"] < 0  # Negative (group1 < group2)
        assert result["effect_size"] < 0  # Negative effect size
        assert result["is_valid"] is True

    def test_t_test_unequal_variance_welch(self):
        """Should compute Welch's t-test correctly."""
        group1 = [10.0, 12.0, 14.0]  # Small variance
        group2 = [20.0, 30.0, 40.0]  # Large variance
        result = t_test_independent(group1, group2, equal_variance=False)

        assert "t_statistic" in result
        assert result["degrees_of_freedom"] > 0  # Welch's df
        assert result["mean_difference"] < 0  # group1 < group2
        assert result["is_valid"] is True

    def test_t_test_effect_size_cohens_d(self):
        """Should compute Cohen's d effect size."""
        group1 = [10.0, 12.0, 14.0, 16.0, 18.0]
        group2 = [20.0, 22.0, 24.0, 26.0, 28.0]
        result = t_test_independent(group1, group2)

        # Large effect (mean_diff = 10, std ≈ 3.16)
        # Cohen's d ≈ 10 / 3.16 ≈ 3.16
        assert abs(result["effect_size"]) > 2.0  # Large effect
        assert result["effect_size"] < 0  # Negative (group1 < group2)

    def test_t_test_no_difference(self):
        """Should detect no significant difference (t~0)."""
        group1 = [10.0, 12.0, 14.0, 16.0, 18.0]
        group2 = [10.0, 12.0, 14.0, 16.0, 18.0]  # Same as group1
        result = t_test_independent(group1, group2)

        assert result["t_statistic"] == 0.0  # No difference
        assert result["mean_difference"] == 0.0
        assert result["effect_size"] == 0.0

    def test_t_test_empty_input_error(self):
        """Should raise ValueError for empty inputs."""
        with pytest.raises(ValueError, match="cannot be empty"):
            t_test_independent([], [10.0, 20.0])

        with pytest.raises(ValueError, match="cannot be empty"):
            t_test_independent([10.0, 20.0], [])

    def test_t_test_small_sample_warning(self):
        """Should warn when sample size < 2."""
        group1 = [10.0]  # n=1
        group2 = [20.0]  # n=1
        result = t_test_independent(group1, group2)

        assert result["is_valid"] is False
        assert result["warning"] is not None
        assert "Small sample size" in result["warning"]

    def test_t_test_minimum_sample_size(self):
        """Should handle minimum valid sample size (n=2)."""
        group1 = [10.0, 12.0]  # n=2
        group2 = [20.0, 22.0]  # n=2
        result = t_test_independent(group1, group2)

        assert result["is_valid"] is True
        assert result["mean_difference"] == -10.0  # 11 - 21

    def test_t_test_zero_variance(self):
        """Should handle zero variance (all values identical)."""
        group1 = [10.0, 10.0, 10.0]  # No variance
        group2 = [20.0, 20.0, 20.0]  # No variance
        result = t_test_independent(group1, group2)

        # Should have warning about zero variance
        assert result["warning"] is not None
        assert "Zero variance" in result["warning"]
        assert result["t_statistic"] == 0.0

    def test_t_test_computes_pvalue_large_sample(self):
        """Should compute p-value for large samples (df > 30)."""
        # Create large samples: n1=50, n2=50, df = 98 > 30
        import random

        random.seed(42)
        group1 = [random.gauss(10, 2) for _ in range(50)]  # mean~10, std~2
        group2 = [random.gauss(15, 2) for _ in range(50)]  # mean~15, std~2
        result = t_test_independent(group1, group2)

        assert result["degrees_of_freedom"] > 30  # Large sample
        assert result["p_value"] is not None  # Should compute for large samples
        assert 0.0 <= result["p_value"] <= 1.0  # Valid p-value range
        assert result["p_value"] < 0.001  # Should be highly significant (groups different)

    def test_t_test_returns_none_pvalue_small_sample(self):
        """Should return p_value=None for small samples (df <= 30)."""
        group1 = [10.0, 12.0, 14.0]  # n=3
        group2 = [20.0, 22.0, 24.0]  # n=3
        result = t_test_independent(group1, group2)

        assert result["degrees_of_freedom"] <= 30  # Small sample: df = 4
        assert result["p_value"] is None  # Approximation not reliable for small df

    def test_t_test_positive_difference(self):
        """Should handle positive mean difference."""
        group1 = [20.0, 22.0, 24.0]  # mean=22
        group2 = [10.0, 12.0, 14.0]  # mean=12
        result = t_test_independent(group1, group2)

        assert result["mean_difference"] > 0  # group1 > group2
        assert result["t_statistic"] > 0  # Positive t-stat
        assert result["effect_size"] > 0  # Positive effect


# =============================================================================
# TestPerformanceMetrics
# =============================================================================


class TestPerformanceMetrics:
    """Tests for compute_performance_metrics function."""

    def test_precision_recall_f1_basic(self):
        """Should compute correct precision, recall, F1."""
        true_labels = ["accept", "accept", "reject", "reject", "accept"]
        predicted_labels = ["accept", "reject", "reject", "reject", "accept"]
        result = compute_performance_metrics(true_labels, predicted_labels, "accept")

        # TP=2 (positions 0, 4), FP=0, FN=1 (position 1), TN=2 (positions 2, 3)
        assert result["true_positives"] == 2
        assert result["false_positives"] == 0
        assert result["false_negatives"] == 1
        assert result["true_negatives"] == 2
        assert result["precision"] == 1.0  # 2/(2+0)
        assert result["recall"] == pytest.approx(2 / 3)  # 2/(2+1)
        assert result["f1_score"] == pytest.approx(2 * 1.0 * (2 / 3) / (1.0 + 2 / 3))
        assert result["support"] == 3  # 3 actual accepts

    def test_perfect_precision(self):
        """Should handle perfect precision case."""
        true_labels = ["accept", "reject", "accept", "reject"]
        predicted_labels = ["accept", "reject", "accept", "reject"]
        result = compute_performance_metrics(true_labels, predicted_labels, "accept")

        assert result["precision"] == 1.0  # 2/(2+0)
        assert result["recall"] == 1.0  # 2/(2+0)
        assert result["f1_score"] == 1.0

    def test_perfect_recall(self):
        """Should handle perfect recall case."""
        true_labels = ["accept", "accept", "reject"]
        predicted_labels = ["accept", "accept", "accept"]  # All predicted as accept
        result = compute_performance_metrics(true_labels, predicted_labels, "accept")

        assert result["recall"] == 1.0  # 2/(2+0) - found all accepts
        assert result["precision"] == pytest.approx(2 / 3)  # 2/(2+1) - some false positives
        assert result["true_positives"] == 2
        assert result["false_positives"] == 1  # Predicted reject as accept

    def test_zero_division_precision(self):
        """Should return 0.0 for precision when TP+FP=0."""
        true_labels = ["reject", "reject", "reject"]
        predicted_labels = ["reject", "reject", "reject"]
        result = compute_performance_metrics(true_labels, predicted_labels, "accept")

        # No predictions as "accept"
        assert result["precision"] == 0.0
        assert result["true_positives"] == 0
        assert result["false_positives"] == 0

    def test_zero_division_recall(self):
        """Should return 0.0 for recall when TP+FN=0."""
        true_labels = ["reject", "reject", "reject"]
        predicted_labels = ["accept", "accept", "accept"]
        result = compute_performance_metrics(true_labels, predicted_labels, "accept")

        # No actual "accept" labels
        assert result["recall"] == 0.0
        assert result["true_positives"] == 0
        assert result["false_negatives"] == 0
        assert result["support"] == 0

    def test_zero_division_f1(self):
        """Should return 0.0 for F1 when precision+recall=0."""
        true_labels = ["reject", "reject"]
        predicted_labels = ["reject", "reject"]
        result = compute_performance_metrics(true_labels, predicted_labels, "accept")

        assert result["f1_score"] == 0.0
        assert result["precision"] == 0.0
        assert result["recall"] == 0.0

    def test_mismatched_length_error(self):
        """Should raise ValueError for mismatched lengths."""
        true_labels = ["accept", "reject"]
        predicted_labels = ["accept"]

        with pytest.raises(ValueError, match="must have same length"):
            compute_performance_metrics(true_labels, predicted_labels)

    def test_different_positive_label(self):
        """Should compute metrics for different positive label."""
        true_labels = ["accept", "reject", "reject", "accept"]
        predicted_labels = ["accept", "reject", "accept", "accept"]
        result = compute_performance_metrics(true_labels, predicted_labels, "reject")

        # For "reject" as positive:
        # TP=1 (position 1), FP=0, FN=1 (position 2), TN=2 (positions 0, 3)
        assert result["true_positives"] == 1
        assert result["false_positives"] == 0
        assert result["false_negatives"] == 1
        assert result["true_negatives"] == 2
        assert result["precision"] == 1.0  # 1/(1+0)
        assert result["recall"] == 0.5  # 1/(1+1)

    def test_support_count(self):
        """Should count support correctly."""
        true_labels = ["accept", "accept", "accept", "reject", "reject"]
        predicted_labels = ["accept", "reject", "accept", "reject", "reject"]
        result = compute_performance_metrics(true_labels, predicted_labels, "accept")

        assert result["support"] == 3  # 3 actual "accept" in true_labels

    def test_all_correct_predictions(self):
        """Should handle all correct predictions."""
        true_labels = ["accept", "reject", "accept", "reject"]
        predicted_labels = ["accept", "reject", "accept", "reject"]
        result = compute_performance_metrics(true_labels, predicted_labels, "accept")

        assert result["precision"] == 1.0
        assert result["recall"] == 1.0
        assert result["f1_score"] == 1.0
        assert result["false_positives"] == 0
        assert result["false_negatives"] == 0

    def test_all_wrong_predictions(self):
        """Should handle all wrong predictions."""
        true_labels = ["accept", "accept", "reject", "reject"]
        predicted_labels = ["reject", "reject", "accept", "accept"]
        result = compute_performance_metrics(true_labels, predicted_labels, "accept")

        # All accepts predicted as reject, all rejects predicted as accept
        assert result["true_positives"] == 0
        assert result["false_positives"] == 2  # 2 rejects predicted as accept
        assert result["false_negatives"] == 2  # 2 accepts predicted as reject
        assert result["true_negatives"] == 0
        assert result["precision"] == 0.0
        assert result["recall"] == 0.0
        assert result["f1_score"] == 0.0


# =============================================================================
# TestPValueCalculations
# =============================================================================


class TestPValueCalculations:
    """Tests for p-value approximation functions."""

    def test_normal_cdf_standard_values(self):
        """Should compute standard normal CDF correctly for known values."""
        # Test known values (approximately)
        assert _normal_cdf(0.0) == pytest.approx(0.5, abs=1e-4)  # Φ(0) = 0.5
        assert _normal_cdf(1.0) == pytest.approx(0.8413, abs=1e-3)  # Φ(1) ≈ 0.8413
        assert _normal_cdf(-1.0) == pytest.approx(0.1587, abs=1e-3)  # Φ(-1) ≈ 0.1587
        assert _normal_cdf(2.0) == pytest.approx(0.9772, abs=1e-3)  # Φ(2) ≈ 0.9772
        assert _normal_cdf(-2.0) == pytest.approx(0.0228, abs=1e-3)  # Φ(-2) ≈ 0.0228

    def test_normal_cdf_extreme_values(self):
        """Should handle extreme z-scores."""
        assert _normal_cdf(5.0) == pytest.approx(1.0, abs=1e-6)  # Very high z
        assert _normal_cdf(-5.0) == pytest.approx(0.0, abs=1e-6)  # Very low z

    def test_chi_squared_pvalue_none_small_df(self):
        """Should return None for df <= 5."""
        assert _approximate_chi_squared_p_value(10.0, df=1) is None
        assert _approximate_chi_squared_p_value(10.0, df=5) is None

    def test_chi_squared_pvalue_computed_large_df(self):
        """Should compute p-value for df > 5."""
        # Chi-squared = 12.0, df = 6
        # Should return valid p-value in (0, 1)
        p_value = _approximate_chi_squared_p_value(12.0, df=6)
        assert p_value is not None
        assert 0.0 < p_value < 1.0

    def test_chi_squared_pvalue_zero_statistic(self):
        """Should handle chi-squared = 0 (perfect fit)."""
        p_value = _approximate_chi_squared_p_value(0.0, df=10)
        assert p_value is not None
        assert p_value == pytest.approx(1.0, abs=0.01)  # p ≈ 1 for χ² = 0

    def test_chi_squared_pvalue_large_statistic(self):
        """Should handle large chi-squared values (strong association)."""
        p_value = _approximate_chi_squared_p_value(50.0, df=10)
        assert p_value is not None
        assert p_value < 0.001  # Very small p-value for large χ²

    def test_chi_squared_pvalue_negative_statistic(self):
        """Should return None for negative chi-squared (invalid)."""
        assert _approximate_chi_squared_p_value(-5.0, df=10) is None

    def test_t_test_pvalue_none_small_df(self):
        """Should return None for df <= 30."""
        assert _approximate_t_test_p_value(2.0, df=10) is None
        assert _approximate_t_test_p_value(2.0, df=30) is None

    def test_t_test_pvalue_computed_large_df(self):
        """Should compute p-value for df > 30."""
        # t = 2.0, df = 50 (large sample)
        p_value = _approximate_t_test_p_value(2.0, df=50)
        assert p_value is not None
        assert 0.0 < p_value < 1.0

    def test_t_test_pvalue_zero_statistic(self):
        """Should handle t = 0 (no difference)."""
        p_value = _approximate_t_test_p_value(0.0, df=100)
        assert p_value is not None
        assert p_value == pytest.approx(1.0, abs=0.01)  # p ≈ 1 for t = 0

    def test_t_test_pvalue_large_statistic(self):
        """Should handle large t-values (strong difference)."""
        p_value = _approximate_t_test_p_value(5.0, df=100)
        assert p_value is not None
        assert p_value < 0.001  # Very small p-value for large |t|

    def test_t_test_pvalue_negative_statistic(self):
        """Should handle negative t-values (symmetric)."""
        # Two-tailed test: p(-t) = p(t)
        p_positive = _approximate_t_test_p_value(2.5, df=50)
        p_negative = _approximate_t_test_p_value(-2.5, df=50)
        assert p_positive == pytest.approx(p_negative, abs=1e-6)


# =============================================================================
# TestSignificanceInterpretation
# =============================================================================


class TestSignificanceInterpretation:
    """Tests for interpret_significance function."""

    def test_extremely_significant(self):
        """Should interpret p < 0.001 as extremely significant."""
        result = interpret_significance(0.0005)
        assert result["is_significant"] is True
        assert result["significance_level"] == "***"
        assert "Extremely significant" in result["interpretation"]

    def test_highly_significant(self):
        """Should interpret 0.001 <= p < 0.01 as highly significant."""
        result = interpret_significance(0.005)
        assert result["is_significant"] is True
        assert result["significance_level"] == "**"
        assert "Highly significant" in result["interpretation"]

    def test_significant(self):
        """Should interpret 0.01 <= p < 0.05 as significant."""
        result = interpret_significance(0.03)
        assert result["is_significant"] is True
        assert result["significance_level"] == "*"
        assert "Significant" in result["interpretation"]

    def test_not_significant(self):
        """Should interpret p >= 0.05 as not significant."""
        result = interpret_significance(0.15)
        assert result["is_significant"] is False
        assert result["significance_level"] is None
        assert "Not significant" in result["interpretation"]

    def test_none_pvalue(self):
        """Should handle None p-value (not computed)."""
        result = interpret_significance(None)
        assert result["is_significant"] is None
        assert result["significance_level"] is None
        assert "not computed" in result["interpretation"]

    def test_custom_alpha_levels(self):
        """Should support custom alpha levels."""
        # Use stricter thresholds: [0.0001, 0.001, 0.01]
        # For p=0.005: 0.005 is not < 0.001, so not highly significant (**)
        # But 0.005 < 0.01, so it is significant (*)
        result = interpret_significance(0.005, alpha_levels=[0.0001, 0.001, 0.01])
        assert result["is_significant"] is True
        assert result["significance_level"] == "*"  # 0.001 < 0.005 < 0.01

        # Test a value that IS highly significant
        result2 = interpret_significance(0.0005, alpha_levels=[0.0001, 0.001, 0.01])
        assert result2["is_significant"] is True
        assert result2["significance_level"] == "**"  # 0.0001 < 0.0005 < 0.001

    def test_boundary_values(self):
        """Should handle exact boundary values correctly."""
        # Exactly at threshold
        result_boundary = interpret_significance(0.05)
        assert result_boundary["is_significant"] is False  # p >= 0.05 is not significant

        # Just below threshold
        result_below = interpret_significance(0.049)
        assert result_below["is_significant"] is True

    def test_zero_pvalue(self):
        """Should handle p-value = 0 (extremely significant)."""
        result = interpret_significance(0.0)
        assert result["is_significant"] is True
        assert result["significance_level"] == "***"

    def test_pvalue_one(self):
        """Should handle p-value = 1.0 (no significance)."""
        result = interpret_significance(1.0)
        assert result["is_significant"] is False
        assert result["significance_level"] is None


# =============================================================================
# TestEdgeCases
# =============================================================================


class TestEdgeCases:
    """Tests for edge cases across all functions."""

    def test_chi_squared_single_category(self):
        """Should handle single feature category."""
        feature_values = ["A", "A", "A"]
        decision_values = ["accept", "reject", "accept"]
        result = chi_squared_test(feature_values, decision_values)

        # df = (1-1) * (2-1) = 0
        assert result["degrees_of_freedom"] == 0
        assert result["chi_squared"] == 0.0

    def test_t_test_large_effect_size(self):
        """Should compute large effect size correctly."""
        group1 = [10.0] * 100  # mean=10, no variance
        group2 = [100.0] * 100  # mean=100, no variance
        result = t_test_independent(group1, group2)

        # Should have warning about zero variance
        assert result["warning"] is not None
        assert result["mean_difference"] == -90.0

    def test_performance_metrics_reclassify_labels(self):
        """Should handle 'reclassify' decision labels."""
        true_labels = ["accept", "reject", "reclassify", "accept"]
        predicted_labels = ["accept", "reject", "reclassify", "reject"]
        result = compute_performance_metrics(true_labels, predicted_labels, "accept")

        # TP=1 (position 0), FP=0, FN=1 (position 3), TN=2 (positions 1, 2)
        assert result["true_positives"] == 1
        assert result["false_negatives"] == 1
        assert result["true_negatives"] == 2
