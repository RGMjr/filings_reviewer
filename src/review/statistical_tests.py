"""
Statistical Tests - Pure Python implementations for pattern analysis.

This module provides statistical functions without external dependencies
(scipy/numpy) for analyzing review decisions and computing feature importance.

Functions:
- chi_squared_test(): Test association between categorical features and decisions
- t_test_independent(): Test difference in numeric features between groups
- compute_performance_metrics(): Compute precision, recall, F1 for patterns
"""

import logging
import math
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# =============================================================================
# Chi-Squared Test for Categorical Features
# =============================================================================


def chi_squared_test(
    feature_values: List[Any],
    decision_values: List[str],
    min_expected_frequency: float = 5.0,
) -> Dict[str, Any]:
    """
    Compute chi-squared test for categorical feature vs decision.

    Tests whether a categorical feature is associated with review decisions
    using Pearson's chi-squared test of independence.

    Args:
        feature_values: Categorical feature values (e.g., ['before', 'after', 'before'])
        decision_values: Decision values ('accept', 'reject', 'reclassify')
        min_expected_frequency: Minimum expected frequency for valid test (default: 5.0)

    Returns:
        Dict with:
            - chi_squared: float - Chi-squared test statistic
            - p_value: Optional[float] - P-value (None in MVP, add later)
            - degrees_of_freedom: int - df = (rows - 1) * (cols - 1)
            - is_valid: bool - True if expected frequencies >= min threshold
            - warning: Optional[str] - Warning message if invalid
            - min_expected: float - Minimum expected frequency in contingency table

    Raises:
        ValueError: If inputs have different lengths or are empty

    Example:
        >>> feature_values = ['before', 'before', 'after', 'after']
        >>> decision_values = ['accept', 'reject', 'accept', 'reject']
        >>> result = chi_squared_test(feature_values, decision_values)
        >>> print(result['chi_squared'])
        0.0  # No association - uniform distribution
    """
    if not feature_values or not decision_values:
        raise ValueError("feature_values and decision_values cannot be empty")

    if len(feature_values) != len(decision_values):
        raise ValueError(
            f"Inputs must have same length: "
            f"feature_values={len(feature_values)}, "
            f"decision_values={len(decision_values)}"
        )

    # Build contingency table: feature_value × decision
    contingency: Dict[Any, Dict[str, int]] = {}
    for fval, dval in zip(feature_values, decision_values):
        if fval not in contingency:
            contingency[fval] = {}
        contingency[fval][dval] = contingency[fval].get(dval, 0) + 1

    # Compute row and column totals
    row_totals: Dict[Any, int] = {}
    col_totals: Dict[str, int] = {}

    for fval, decisions_dict in contingency.items():
        row_totals[fval] = sum(decisions_dict.values())
        for dval, count in decisions_dict.items():
            col_totals[dval] = col_totals.get(dval, 0) + count

    total = sum(row_totals.values())

    # Compute chi-squared statistic and track minimum expected frequency
    chi_squared = 0.0
    min_expected = float("inf")

    for fval in contingency.keys():
        for dval in col_totals.keys():
            observed = contingency[fval].get(dval, 0)
            expected = (row_totals[fval] * col_totals[dval]) / total

            min_expected = min(min_expected, expected)

            if expected > 0:
                chi_squared += (observed - expected) ** 2 / expected

    # Compute degrees of freedom
    df = (len(row_totals) - 1) * (len(col_totals) - 1)

    # Check validity based on expected frequencies
    is_valid = min_expected >= min_expected_frequency
    warning = None
    if not is_valid:
        warning = (
            f"Low expected frequency: {min_expected:.2f} < {min_expected_frequency}. "
            f"Chi-squared test may not be reliable."
        )

    return {
        "chi_squared": chi_squared,
        "p_value": None,  # MVP: return None, add approximation later
        "degrees_of_freedom": df,
        "is_valid": is_valid,
        "warning": warning,
        "min_expected": min_expected,
    }


# =============================================================================
# T-Test for Numeric Features
# =============================================================================


def t_test_independent(
    group1_values: List[float],
    group2_values: List[float],
    equal_variance: bool = True,
) -> Dict[str, Any]:
    """
    Compute independent samples t-test (Student's or Welch's).

    Tests whether two groups (e.g., accepted vs rejected candidates) have
    significantly different means for a numeric feature.

    Args:
        group1_values: Numeric values for group 1 (e.g., accepted candidates)
        group2_values: Numeric values for group 2 (e.g., rejected candidates)
        equal_variance: If True, use Student's t-test; if False, use Welch's

    Returns:
        Dict with:
            - t_statistic: float - T-test statistic
            - p_value: Optional[float] - Two-tailed p-value (None in MVP)
            - degrees_of_freedom: float - Degrees of freedom
            - mean_difference: float - mean(group1) - mean(group2)
            - effect_size: float - Cohen's d (standardized mean difference)
            - is_valid: bool - True if sample sizes >= minimum (both >= 2)
            - warning: Optional[str] - Warning message if invalid

    Raises:
        ValueError: If either group is empty

    Algorithm:
        Student's t-test (equal_variance=True):
            pooled_std = sqrt(((n1-1)*s1^2 + (n2-1)*s2^2) / (n1 + n2 - 2))
            t = (mean1 - mean2) / (pooled_std * sqrt(1/n1 + 1/n2))
            df = n1 + n2 - 2

        Welch's t-test (equal_variance=False):
            t = (mean1 - mean2) / sqrt(s1^2/n1 + s2^2/n2)
            df = (s1^2/n1 + s2^2/n2)^2 / ((s1^2/n1)^2/(n1-1) + (s2^2/n2)^2/(n2-1))

        Cohen's d: (mean1 - mean2) / pooled_std

    Example:
        >>> group1 = [10.0, 12.0, 14.0, 16.0, 18.0]  # accepted
        >>> group2 = [20.0, 22.0, 24.0, 26.0, 28.0]  # rejected
        >>> result = t_test_independent(group1, group2)
        >>> print(result['mean_difference'])
        -10.0  # Group 1 mean is 10 units lower
        >>> print(result['effect_size'] < -2.0)
        True  # Large negative effect (group 1 < group 2)
    """
    if not group1_values or not group2_values:
        raise ValueError("group1_values and group2_values cannot be empty")

    n1 = len(group1_values)
    n2 = len(group2_values)

    # Check minimum sample size
    is_valid = n1 >= 2 and n2 >= 2
    warning = None
    if not is_valid:
        warning = f"Small sample size: n1={n1}, n2={n2}. Both groups need >= 2 samples."

    # Compute means
    mean1 = sum(group1_values) / n1
    mean2 = sum(group2_values) / n2
    mean_difference = mean1 - mean2

    # Handle edge case: all values identical (no variance)
    if n1 == 1 or n2 == 1:
        # Cannot compute variance with n=1
        return {
            "t_statistic": 0.0,
            "p_value": None,
            "degrees_of_freedom": 0.0,
            "mean_difference": mean_difference,
            "effect_size": 0.0,
            "is_valid": False,
            "warning": warning or "Sample size too small (n=1)",
        }

    # Compute variances
    var1 = sum((x - mean1) ** 2 for x in group1_values) / (n1 - 1)
    var2 = sum((x - mean2) ** 2 for x in group2_values) / (n2 - 1)

    if equal_variance:
        # Student's t-test (pooled variance)
        pooled_var = ((n1 - 1) * var1 + (n2 - 1) * var2) / (n1 + n2 - 2)
        pooled_std = math.sqrt(pooled_var)

        # Handle zero variance case
        if pooled_std == 0:
            return {
                "t_statistic": 0.0,
                "p_value": None,
                "degrees_of_freedom": n1 + n2 - 2,
                "mean_difference": mean_difference,
                "effect_size": 0.0,
                "is_valid": is_valid,
                "warning": warning or "Zero variance - all values identical",
            }

        se = pooled_std * math.sqrt(1 / n1 + 1 / n2)
        t_stat = mean_difference / se
        df = n1 + n2 - 2
        cohens_d = mean_difference / pooled_std
    else:
        # Welch's t-test (unequal variance)
        se_squared = var1 / n1 + var2 / n2
        se = math.sqrt(se_squared)

        # Handle zero variance case
        if se == 0:
            return {
                "t_statistic": 0.0,
                "p_value": None,
                "degrees_of_freedom": 0.0,
                "mean_difference": mean_difference,
                "effect_size": 0.0,
                "is_valid": is_valid,
                "warning": warning or "Zero variance - all values identical",
            }

        t_stat = mean_difference / se

        # Welch-Satterthwaite degrees of freedom
        numerator = se_squared**2
        denominator = (var1 / n1) ** 2 / (n1 - 1) + (var2 / n2) ** 2 / (n2 - 1)
        df = numerator / denominator if denominator > 0 else 0.0

        # Cohen's d with pooled standard deviation
        pooled_std = math.sqrt((var1 + var2) / 2)
        cohens_d = mean_difference / pooled_std if pooled_std > 0 else 0.0

    return {
        "t_statistic": t_stat,
        "p_value": None,  # MVP: return None, add approximation later
        "degrees_of_freedom": df,
        "mean_difference": mean_difference,
        "effect_size": cohens_d,
        "is_valid": is_valid,
        "warning": warning,
    }


# =============================================================================
# Performance Metrics for Pattern Evaluation
# =============================================================================


def compute_performance_metrics(
    true_labels: List[str],
    predicted_labels: List[str],
    positive_label: str = "accept",
) -> Dict[str, float]:
    """
    Compute precision, recall, F1 for binary classification.

    Used to evaluate pattern performance by comparing predicted classifications
    (pattern matches) against ground truth (actual decisions).

    Args:
        true_labels: Ground truth labels (e.g., actual decisions)
        predicted_labels: Predicted labels (e.g., pattern matches)
        positive_label: Label to treat as positive class (default: "accept")

    Returns:
        Dict with:
            - precision: float - TP / (TP + FP), 0.0 if TP + FP = 0
            - recall: float - TP / (TP + FN), 0.0 if TP + FN = 0
            - f1_score: float - 2 * (precision * recall) / (precision + recall)
            - true_positives: int - Count of TP
            - false_positives: int - Count of FP
            - false_negatives: int - Count of FN
            - true_negatives: int - Count of TN
            - support: int - Count of positive_label in true_labels

    Raises:
        ValueError: If inputs have different lengths

    Example:
        >>> true_labels = ['accept', 'accept', 'reject', 'reject', 'accept']
        >>> predicted_labels = ['accept', 'reject', 'reject', 'reject', 'accept']
        >>> result = compute_performance_metrics(true_labels, predicted_labels, 'accept')
        >>> print(f"Precision: {result['precision']:.2f}")
        Precision: 1.00  # 2 TP, 0 FP
        >>> print(f"Recall: {result['recall']:.2f}")
        Recall: 0.67  # 2 TP, 1 FN (missed position 1)
        >>> print(f"F1: {result['f1_score']:.2f}")
        F1: 0.80
    """
    if len(true_labels) != len(predicted_labels):
        raise ValueError(
            f"Inputs must have same length: "
            f"true_labels={len(true_labels)}, "
            f"predicted_labels={len(predicted_labels)}"
        )

    # Count confusion matrix components
    true_positives = 0
    false_positives = 0
    false_negatives = 0
    true_negatives = 0

    for true_label, pred_label in zip(true_labels, predicted_labels):
        if true_label == positive_label and pred_label == positive_label:
            true_positives += 1
        elif true_label != positive_label and pred_label == positive_label:
            false_positives += 1
        elif true_label == positive_label and pred_label != positive_label:
            false_negatives += 1
        else:  # true_label != positive_label and pred_label != positive_label
            true_negatives += 1

    # Compute precision (handle division by zero)
    precision_denominator = true_positives + false_positives
    precision = true_positives / precision_denominator if precision_denominator > 0 else 0.0

    # Compute recall (handle division by zero)
    recall_denominator = true_positives + false_negatives
    recall = true_positives / recall_denominator if recall_denominator > 0 else 0.0

    # Compute F1 score (harmonic mean of precision and recall)
    f1_denominator = precision + recall
    f1_score = 2 * (precision * recall) / f1_denominator if f1_denominator > 0 else 0.0

    # Support is the number of positive class instances in true labels
    support = true_positives + false_negatives

    return {
        "precision": precision,
        "recall": recall,
        "f1_score": f1_score,
        "true_positives": true_positives,
        "false_positives": false_positives,
        "false_negatives": false_negatives,
        "true_negatives": true_negatives,
        "support": support,
    }
