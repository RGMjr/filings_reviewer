"""
Pattern Analyzer - Analyze review decisions to discover extraction patterns.

This module analyzes human review decisions to discover high-precision patterns
that distinguish correct from incorrect metric extractions.

After human review of 5-10 filings:
1. Load decisions with features from database
2. Compute feature importance (chi-squared for categorical, t-test for numeric)
3. Discover high-precision rejection/acceptance patterns
4. Generate LearnedPattern objects with precision/recall metrics
5. Save patterns to database for future use

Usage:
    >>> from src.infra.db import DatabaseAdapter
    >>> from src.review.pattern_analyzer import PatternAnalyzer
    >>>
    >>> db = DatabaseAdapter(connection_string)
    >>> analyzer = PatternAnalyzer(db, min_pattern_precision=0.75)
    >>>
    >>> # Analyze decisions
    >>> analysis = analyzer.analyze_decisions()
    >>> print(f"Total decisions: {analysis['total_decisions']}")
    >>>
    >>> # Discover patterns
    >>> patterns = analyzer.discover_patterns(pattern_type='reject_rule')
    >>> print(f"Found {len(patterns)} rejection patterns")
"""

import logging
from typing import Any, Dict, List, Optional

from src.review.models import CandidateFeatures, LearnedPattern
from src.review.statistical_tests import (
    chi_squared_test,
    compute_performance_metrics,
    interpret_significance,
    t_test_independent,
)

logger = logging.getLogger(__name__)


# =============================================================================
# PatternAnalyzer Class
# =============================================================================


class PatternAnalyzer:
    """
    Analyze review decisions to discover extraction patterns.

    After human review of 5-10 filings, this class:
    1. Loads decisions with features from database
    2. Computes feature importance (categorical and numeric)
    3. Discovers high-precision rejection patterns
    4. Discovers high-precision acceptance patterns
    5. Generates LearnedPattern objects with performance metrics

    Example:
        >>> db = DatabaseAdapter()
        >>> analyzer = PatternAnalyzer(db, min_pattern_precision=0.75)
        >>>
        >>> # Analyze decisions
        >>> analysis = analyzer.analyze_decisions()
        >>> print(f"Top features:")
        >>> for feat in analysis['categorical_features'][:3]:
        ...     print(f"  {feat['feature_name']}: χ²={feat['chi_squared']:.2f}")
        >>>
        >>> # Discover patterns
        >>> patterns = analyzer.discover_patterns(pattern_type='reject_rule')
        >>> for pattern in patterns[:3]:
        ...     print(f"  {pattern.pattern_name}: precision={pattern.precision_score:.2f}")
    """

    # Categorical features from CandidateFeatures
    CATEGORICAL_FEATURES = [
        "keyword_position",  # 'before' | 'after'
        "number_format",  # 'integer' | 'decimal' | 'percentage' | 'currency'
        "is_in_table",  # bool
        "is_in_risk_factors",  # bool
        "contains_definition_language",  # bool
        "has_period_mention",  # bool
    ]

    # Numeric features from CandidateFeatures
    NUMERIC_FEATURES = [
        "keyword_distance",  # 0-300+ chars
        "value_magnitude",  # log10 values (may be None)
        "surrounding_numbers_count",  # 0-10+
        "context_word_count",  # 20-100 words
    ]

    def __init__(
        self,
        db_adapter,
        min_pattern_precision: float = 0.75,
        min_pattern_support: int = 5,
        min_sample_size: int = 30,
        significance_threshold: float = 0.05,
    ):
        """
        Initialize pattern analyzer.

        Args:
            db_adapter: Database adapter for loading decisions (DatabaseAdapter instance)
            min_pattern_precision: Minimum precision for pattern approval (default: 0.75)
            min_pattern_support: Minimum samples matching pattern (default: 5)
            min_sample_size: Warn if total samples < this (default: 30)
            significance_threshold: P-value threshold for statistical significance (default: 0.05)

        Note:
            Features with p-value >= significance_threshold (when computable) are filtered out
            before pattern generation to ensure discovered patterns are statistically significant.
        """
        self.db = db_adapter
        self.min_pattern_precision = min_pattern_precision
        self.min_pattern_support = min_pattern_support
        self.min_sample_size = min_sample_size
        self.significance_threshold = significance_threshold
        self.logger = logging.getLogger(__name__)

    def analyze_decisions(
        self,
        filing_id: Optional[int] = None,
        metric_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Analyze review decisions and compute feature importance.

        Args:
            filing_id: Optional filter to specific filing
            metric_id: Optional filter to specific metric

        Returns:
            Dict with:
                - total_decisions: int - Total decision count
                - decision_counts: Dict[str, int] - {decision_type: count}
                - categorical_features: List[Dict] - Sorted by chi-squared descending
                    - feature_name: str
                    - chi_squared: float
                    - p_value: Optional[float]
                    - is_significant: bool (always False in MVP since p_value=None)
                    - is_valid: bool
                    - value_distribution: Dict[value, Dict[decision, count]]
                - numeric_features: List[Dict] - Sorted by effect size descending
                    - feature_name: str
                    - t_statistic: float
                    - p_value: Optional[float]
                    - is_significant: bool (always False in MVP)
                    - mean_by_decision: Dict[decision, float]
                    - effect_size: float (Cohen's d)
                - warnings: List[str] - e.g., "Small sample size: 15 < 30"

        Process:
            1. Load decisions with features from database
            2. Check sample size, add warnings if needed
            3. For each categorical feature: run chi-squared test
            4. For each numeric feature: run t-test (accept vs reject)
            5. Sort features by importance/effect size
            6. Return analysis results
        """
        # Load decisions with features
        decisions_data = self._load_decisions_with_features(filing_id, metric_id)

        total_decisions = len(decisions_data)
        warnings = []

        # Check minimum sample size
        if total_decisions < self.min_sample_size:
            warnings.append(
                f"Small sample size: {total_decisions} < {self.min_sample_size}. "
                f"Statistical tests may not be reliable."
            )

        # Count decisions by type
        decision_counts: Dict[str, int] = {}
        for d in decisions_data:
            decision = d["decision"]
            decision_counts[decision] = decision_counts.get(decision, 0) + 1

        # Analyze categorical features
        categorical_results = []
        for feature_name in self.CATEGORICAL_FEATURES:
            result = self._compute_categorical_importance(feature_name, decisions_data)
            if result:  # Skip features with all None values
                categorical_results.append(result)

        # Sort by chi-squared descending
        categorical_results.sort(key=lambda x: x["chi_squared"], reverse=True)

        # Analyze numeric features
        numeric_results = []
        for feature_name in self.NUMERIC_FEATURES:
            result = self._compute_numeric_importance(feature_name, decisions_data)
            if result:  # Skip features with insufficient data
                numeric_results.append(result)

        # Sort by absolute effect size descending
        numeric_results.sort(key=lambda x: abs(x["effect_size"]), reverse=True)

        return {
            "total_decisions": total_decisions,
            "decision_counts": decision_counts,
            "categorical_features": categorical_results,
            "numeric_features": numeric_results,
            "warnings": warnings,
        }

    def _load_decisions_with_features(
        self,
        filing_id: Optional[int],
        metric_id: Optional[str],
    ) -> List[Dict[str, Any]]:
        """
        Load decisions with features from database.

        Args:
            filing_id: Optional filter to specific filing
            metric_id: Optional filter to specific metric

        Returns:
            List of dicts with keys:
                - candidate_id: int
                - filing_id: int
                - decision: str ('accept', 'reject', 'reclassify')
                - assigned_metric_id: Optional[str]
                - rejection_category: Optional[str]
                - features: Dict (from CandidateFeatures.to_dict())

        Note:
            Filters to only reviewed candidates (review_status='reviewed').
            Excludes candidates without decisions.
        """
        # Query database for reviewed candidates with decisions
        # For MVP, we'll load all reviewed candidates if filing_id is None

        if filing_id:
            # Load for specific filing
            candidates = self.db.get_review_candidates_with_decisions(
                filing_id=filing_id,
                status="reviewed",
            )
        else:
            # Load across all filings using new database method (Phase 4)
            candidates = self.db.get_all_reviewed_candidates_with_decisions(
                metric_id=metric_id,
            )

        # Extract decisions with features
        decisions_data = []
        for candidate in candidates:
            # Skip if no decision exists (decision field is NULL)
            if not candidate.get("decision"):
                continue

            # Skip if filtering by metric_id
            if metric_id and candidate.get("suggested_metric_id") != metric_id:
                continue

            # Parse features from JSONB
            features_dict = candidate.get("features")
            if not features_dict:
                self.logger.warning(
                    f"Candidate {candidate['candidate_id']} has no features, skipping"
                )
                continue

            # Reconstruct CandidateFeatures for type safety (optional)
            try:
                features = CandidateFeatures.from_dict(features_dict)
                features_dict = features.to_dict()
            except Exception as e:
                self.logger.warning(
                    f"Failed to parse features for candidate {candidate['candidate_id']}: {e}"
                )
                continue

            decisions_data.append(
                {
                    "candidate_id": candidate["candidate_id"],
                    "filing_id": candidate["filing_id"],
                    "decision": candidate["decision"],
                    "assigned_metric_id": candidate.get("assigned_metric_id"),
                    "rejection_category": candidate.get("rejection_category"),
                    "features": features_dict,
                }
            )

        return decisions_data

    def _compute_categorical_importance(
        self,
        feature_name: str,
        decisions_data: List[Dict[str, Any]],
    ) -> Optional[Dict[str, Any]]:
        """
        Compute importance for categorical feature using chi-squared test.

        Args:
            feature_name: Name of categorical feature
            decisions_data: List of decision dicts with features

        Returns:
            Dict with:
                - feature_name: str
                - chi_squared: float
                - p_value: Optional[float]
                - degrees_of_freedom: int
                - is_significant: bool (always False in MVP)
                - is_valid: bool
                - warning: Optional[str]
                - value_distribution: Dict[value, Dict[decision, count]]
            Or None if feature has all None values

        Process:
            1. Extract feature values and decision values
            2. Filter out None values
            3. Run chi_squared_test()
            4. Build value distribution dict
            5. Return formatted results
        """
        # Extract feature values and decisions
        feature_values = []
        decision_values = []

        for d in decisions_data:
            feature_val = d["features"].get(feature_name)
            decision = d["decision"]

            # Skip None values
            if feature_val is None:
                continue

            # Convert boolean to string for consistency
            if isinstance(feature_val, bool):
                feature_val = str(feature_val)

            feature_values.append(feature_val)
            decision_values.append(decision)

        # Check if we have any valid values
        if not feature_values:
            self.logger.debug(
                f"Feature '{feature_name}' has all None values, skipping"
            )
            return None

        # Run chi-squared test
        try:
            chi_result = chi_squared_test(feature_values, decision_values)
        except ValueError as e:
            self.logger.warning(
                f"Chi-squared test failed for '{feature_name}': {e}"
            )
            return None

        # Build value distribution
        value_distribution: Dict[Any, Dict[str, int]] = {}
        for fval, dval in zip(feature_values, decision_values):
            if fval not in value_distribution:
                value_distribution[fval] = {}
            value_distribution[fval][dval] = value_distribution[fval].get(dval, 0) + 1

        return {
            "feature_name": feature_name,
            "chi_squared": chi_result["chi_squared"],
            "p_value": chi_result["p_value"],
            "degrees_of_freedom": chi_result["degrees_of_freedom"],
            "is_significant": False,  # MVP: always False since p_value=None
            "is_valid": chi_result["is_valid"],
            "warning": chi_result["warning"],
            "value_distribution": value_distribution,
        }

    def _compute_numeric_importance(
        self,
        feature_name: str,
        decisions_data: List[Dict[str, Any]],
    ) -> Optional[Dict[str, Any]]:
        """
        Compute importance for numeric feature using t-test (accept vs reject).

        Args:
            feature_name: Name of numeric feature
            decisions_data: List of decision dicts with features

        Returns:
            Dict with:
                - feature_name: str
                - t_statistic: float
                - p_value: Optional[float]
                - degrees_of_freedom: float
                - mean_difference: float
                - effect_size: float (Cohen's d)
                - is_significant: bool (always False in MVP)
                - is_valid: bool
                - warning: Optional[str]
                - mean_by_decision: Dict[decision, float]
            Or None if insufficient data

        Process:
            1. Extract feature values for accept vs reject groups
            2. Filter out None values
            3. Run t_test_independent()
            4. Compute mean by decision type
            5. Return formatted results

        Note:
            Only compares 'accept' vs 'reject' decisions.
            'reclassify' decisions are excluded from t-test analysis.
        """
        # Extract feature values by decision type
        accept_values = []
        reject_values = []
        all_values_by_decision: Dict[str, List[float]] = {
            "accept": [],
            "reject": [],
            "reclassify": [],
        }

        for d in decisions_data:
            feature_val = d["features"].get(feature_name)
            decision = d["decision"]

            # Skip None values
            if feature_val is None:
                continue

            # Ensure numeric
            try:
                feature_val = float(feature_val)
            except (ValueError, TypeError):
                continue

            # Group by decision
            if decision == "accept":
                accept_values.append(feature_val)
                all_values_by_decision["accept"].append(feature_val)
            elif decision == "reject":
                reject_values.append(feature_val)
                all_values_by_decision["reject"].append(feature_val)
            elif decision == "reclassify":
                all_values_by_decision["reclassify"].append(feature_val)

        # Check if we have sufficient data
        if not accept_values or not reject_values:
            self.logger.debug(
                f"Feature '{feature_name}' has insufficient data for t-test "
                f"(accept: {len(accept_values)}, reject: {len(reject_values)}), skipping"
            )
            return None

        # Run t-test
        try:
            t_result = t_test_independent(accept_values, reject_values)
        except ValueError as e:
            self.logger.warning(f"T-test failed for '{feature_name}': {e}")
            return None

        # Compute mean by decision
        mean_by_decision = {}
        for decision, values in all_values_by_decision.items():
            if values:
                mean_by_decision[decision] = sum(values) / len(values)

        return {
            "feature_name": feature_name,
            "t_statistic": t_result["t_statistic"],
            "p_value": t_result["p_value"],
            "degrees_of_freedom": t_result["degrees_of_freedom"],
            "mean_difference": t_result["mean_difference"],
            "effect_size": t_result["effect_size"],
            "is_significant": False,  # MVP: always False since p_value=None
            "is_valid": t_result["is_valid"],
            "warning": t_result["warning"],
            "mean_by_decision": mean_by_decision,
        }

    def _stratified_k_fold_split(
        self,
        decisions_data: List[Dict[str, Any]],
        k: int = 5,
    ) -> List[tuple]:
        """
        Perform stratified k-fold split of decision data.

        Stratified splitting preserves the proportion of each decision type
        (accept/reject/reclassify) in each fold.

        Args:
            decisions_data: List of decision dicts with features
            k: Number of folds (default: 5)

        Returns:
            List of (train_data, test_data) tuples for each fold

        Algorithm:
            1. Group decisions by decision type
            2. Split each group into k folds
            3. Combine folds to create train/test splits
        """
        import random

        # Group by decision type
        decision_groups = {}
        for d in decisions_data:
            decision = d["decision"]
            if decision not in decision_groups:
                decision_groups[decision] = []
            decision_groups[decision].append(d)

        # Shuffle each group (for randomization)
        for decision_type, items in decision_groups.items():
            random.shuffle(items)

        # Split each group into k folds
        folds_by_decision = {}
        for decision_type, items in decision_groups.items():
            n = len(items)
            fold_size = n // k
            remainder = n % k

            folds = []
            start = 0
            for i in range(k):
                # Add 1 extra item to first 'remainder' folds
                size = fold_size + (1 if i < remainder else 0)
                folds.append(items[start : start + size])
                start += size

            folds_by_decision[decision_type] = folds

        # Create train/test splits by combining folds
        splits = []
        for test_fold_idx in range(k):
            train_data = []
            test_data = []

            for decision_type, folds in folds_by_decision.items():
                for fold_idx, fold in enumerate(folds):
                    if fold_idx == test_fold_idx:
                        test_data.extend(fold)
                    else:
                        train_data.extend(fold)

            splits.append((train_data, test_data))

        return splits

    def _get_significant_features(
        self,
        decisions_data: List[Dict[str, Any]],
    ) -> set:
        """
        Identify statistically significant features.

        Args:
            decisions_data: List of decision dicts with features

        Returns:
            Set of feature names that are statistically significant (p < threshold)

        Process:
            1. For each categorical feature: compute chi-squared test
            2. For each numeric feature: compute t-test
            3. Return set of features where p-value < significance_threshold
            4. Include features where p-value is None (insufficient df for approximation)
        """
        significant_features = set()

        # Extract decisions for statistical tests
        decisions = [d["decision"] for d in decisions_data]

        # Check categorical features
        for feature_name in self.CATEGORICAL_FEATURES:
            # Extract feature values
            feature_values = []
            for d in decisions_data:
                features = d.get("features", {})
                value = features.get(feature_name)
                if value is not None:
                    feature_values.append(value)

            # Skip if not enough data
            if len(feature_values) < 2:
                continue

            # Perform chi-squared test
            try:
                result = chi_squared_test(feature_values[:len(decisions)], decisions)
                p_value = result["p_value"]

                # Include if significant OR if p-value not computable
                if p_value is None or p_value < self.significance_threshold:
                    significant_features.add(feature_name)
                else:
                    self.logger.debug(
                        f"Feature '{feature_name}' not significant (p={p_value:.4f})"
                    )
            except Exception as e:
                self.logger.warning(f"Error testing feature '{feature_name}': {e}")
                # Include feature if test fails (conservative approach)
                significant_features.add(feature_name)

        # Check numeric features
        for feature_name in self.NUMERIC_FEATURES:
            # Split by decision
            accept_values = []
            reject_values = []

            for d in decisions_data:
                features = d.get("features", {})
                value = features.get(feature_name)
                if value is not None:
                    if d["decision"] == "accept":
                        accept_values.append(float(value))
                    elif d["decision"] == "reject":
                        reject_values.append(float(value))

            # Skip if not enough data in either group
            if len(accept_values) < 2 or len(reject_values) < 2:
                continue

            # Perform t-test
            try:
                result = t_test_independent(accept_values, reject_values)
                p_value = result["p_value"]

                # Include if significant OR if p-value not computable
                if p_value is None or p_value < self.significance_threshold:
                    significant_features.add(feature_name)
                else:
                    self.logger.debug(
                        f"Feature '{feature_name}' not significant (p={p_value:.4f})"
                    )
            except Exception as e:
                self.logger.warning(f"Error testing feature '{feature_name}': {e}")
                # Include feature if test fails (conservative approach)
                significant_features.add(feature_name)

        self.logger.info(
            f"Identified {len(significant_features)} statistically significant features "
            f"(p < {self.significance_threshold} or p=None)"
        )

        return significant_features

    def discover_patterns(
        self,
        filing_id: Optional[int] = None,
        metric_id: Optional[str] = None,
        pattern_type: Optional[str] = None,
        use_db_evaluation: bool = False,
        include_two_feature_patterns: bool = False,
    ) -> List[LearnedPattern]:
        """
        Discover high-precision patterns from review decisions.

        Args:
            filing_id: Optional filter to specific filing
            metric_id: Optional filter to specific metric
            pattern_type: Optional filter by pattern type ('accept_rule' or 'reject_rule')
            use_db_evaluation: If True, use database-side pattern evaluation (10-100x faster).
                               If False, use Python-side evaluation (default: False for testing compatibility).
                               Production code should set use_db_evaluation=True for better performance.
            include_two_feature_patterns: If True, also generate two-feature conjunctive patterns (P2.1).
                                           These combine top features with AND logic for higher precision.
                                           Recommend min_pattern_support >= 10 to avoid overfitting.
                                           (default: False)

        Returns:
            List of LearnedPattern objects sorted by F1 score descending

        Process:
            1. Load decisions with features (for significance testing only if use_db_evaluation=True)
            2. Identify statistically significant features (p < 0.05)
            3. Generate candidate patterns (single-feature for MVP, only from significant features)
            4. For each candidate: evaluate precision/recall/F1
               - If use_db_evaluation=True: Use SQL queries with JSONB operators (fast)
               - If use_db_evaluation=False: Use Python pattern matching (slower)
            5. Filter by min_pattern_precision and min_pattern_support
            6. Return patterns sorted by F1 descending

        Performance:
            - Database-side evaluation (use_db_evaluation=True):
              * 1000 decisions: ~10-50ms per pattern
              * Recommended for production use
            - Python-side evaluation (use_db_evaluation=False):
              * 1000 decisions: ~500-1000ms per pattern
              * Useful for debugging or when SQL generation is problematic

        Note:
            MVP implementation generates single-feature patterns only.
            Future enhancement: multi-feature conjunction patterns.
        """
        # Load decisions with features (always needed for significance testing)
        decisions_data = self._load_decisions_with_features(filing_id, metric_id)

        if not decisions_data:
            self.logger.warning("No decisions found, cannot discover patterns")
            return []

        # Identify statistically significant features
        significant_features = self._get_significant_features(decisions_data)

        if not significant_features:
            self.logger.warning(
                "No statistically significant features found, cannot discover patterns"
            )
            return []

        # Generate candidate patterns (only from significant features)
        patterns = []

        # Generate rejection patterns if requested
        if pattern_type is None or pattern_type == "reject_rule":
            reject_patterns = self._generate_single_feature_patterns(
                decisions_data,
                target_decision="reject",
                significant_features=significant_features,
            )
            for pattern_def in reject_patterns:
                if use_db_evaluation:
                    evaluated = self._evaluate_pattern_db_side(
                        pattern_def,
                        filing_id=filing_id,
                        metric_id=metric_id,
                        target_decision="reject",
                    )
                else:
                    evaluated = self._evaluate_pattern(
                        pattern_def, decisions_data, target_decision="reject"
                    )
                if evaluated:
                    patterns.append(evaluated)

        # Generate acceptance patterns if requested
        if pattern_type is None or pattern_type == "accept_rule":
            accept_patterns = self._generate_single_feature_patterns(
                decisions_data,
                target_decision="accept",
                significant_features=significant_features,
            )
            for pattern_def in accept_patterns:
                if use_db_evaluation:
                    evaluated = self._evaluate_pattern_db_side(
                        pattern_def,
                        filing_id=filing_id,
                        metric_id=metric_id,
                        target_decision="accept",
                    )
                else:
                    evaluated = self._evaluate_pattern(
                        pattern_def, decisions_data, target_decision="accept"
                    )
                if evaluated:
                    patterns.append(evaluated)

        # Generate two-feature patterns if requested (P2.1)
        if include_two_feature_patterns:
            self.logger.info("Generating two-feature conjunctive patterns (P2.1)...")

            # Generate rejection two-feature patterns if requested
            if pattern_type is None or pattern_type == "reject_rule":
                two_feature_reject_patterns = self._generate_two_feature_patterns(
                    decisions_data,
                    target_decision="reject",
                    significant_features=significant_features,
                )
                for pattern_def in two_feature_reject_patterns:
                    if use_db_evaluation:
                        evaluated = self._evaluate_pattern_db_side(
                            pattern_def,
                            filing_id=filing_id,
                            metric_id=metric_id,
                            target_decision="reject",
                        )
                    else:
                        evaluated = self._evaluate_pattern(
                            pattern_def, decisions_data, target_decision="reject"
                        )
                    if evaluated:
                        patterns.append(evaluated)

            # Generate acceptance two-feature patterns if requested
            if pattern_type is None or pattern_type == "accept_rule":
                two_feature_accept_patterns = self._generate_two_feature_patterns(
                    decisions_data,
                    target_decision="accept",
                    significant_features=significant_features,
                )
                for pattern_def in two_feature_accept_patterns:
                    if use_db_evaluation:
                        evaluated = self._evaluate_pattern_db_side(
                            pattern_def,
                            filing_id=filing_id,
                            metric_id=metric_id,
                            target_decision="accept",
                        )
                    else:
                        evaluated = self._evaluate_pattern(
                            pattern_def, decisions_data, target_decision="accept"
                        )
                    if evaluated:
                        patterns.append(evaluated)

        # Filter by minimum precision and support
        filtered_patterns = []
        for pattern in patterns:
            if (
                pattern.precision_score >= self.min_pattern_precision
                and pattern.sample_count >= self.min_pattern_support
            ):
                filtered_patterns.append(pattern)

        # Sort by F1 score descending
        filtered_patterns.sort(key=lambda p: p.f1_score, reverse=True)

        evaluation_method = "database-side" if use_db_evaluation else "Python-side"
        self.logger.info(
            f"Discovered {len(filtered_patterns)} patterns using {evaluation_method} evaluation "
            f"(precision >= {self.min_pattern_precision}, "
            f"support >= {self.min_pattern_support})"
        )

        return filtered_patterns

    def discover_patterns_with_cross_validation(
        self,
        filing_id: Optional[int] = None,
        metric_id: Optional[str] = None,
        pattern_type: Optional[str] = None,
        k: int = 5,
        max_variance: float = 0.1,
        min_cv_sample_size: int = 30,
    ) -> List[Dict[str, Any]]:
        """
        Discover patterns using k-fold cross-validation for stability assessment.

        This method evaluates patterns on held-out validation folds to detect overfitting
        and filter unstable patterns.

        Args:
            filing_id: Optional filter to specific filing
            metric_id: Optional filter to specific metric
            pattern_type: Optional filter by pattern type ('accept_rule' or 'reject_rule')
            k: Number of cross-validation folds (default: 5)
            max_variance: Maximum allowed std/mean for precision (default: 0.1)
            min_cv_sample_size: Minimum sample size required for CV (default: 30)

        Returns:
            List of dicts with pattern and cross-validation metrics:
                - pattern: LearnedPattern object
                - cv_precision_mean: float - Mean precision across folds
                - cv_precision_std: float - Std deviation of precision
                - cv_recall_mean: float - Mean recall across folds
                - cv_recall_std: float - Std deviation of recall
                - cv_f1_mean: float - Mean F1 score across folds
                - cv_f1_std: float - Std deviation of F1
                - is_stable: bool - True if variance is acceptable
                - fold_count: int - Number of folds evaluated

        Raises:
            ValueError: If sample size < min_cv_sample_size

        Process:
            1. Check minimum sample size (30+ decisions recommended)
            2. Perform stratified k-fold split (preserves decision distribution)
            3. For each fold: discover patterns on train data, evaluate on test data
            4. Aggregate metrics (mean ± std) across folds
            5. Filter unstable patterns (coefficient of variation > max_variance)
            6. Return stable patterns with CV metrics

        Example:
            >>> analyzer = PatternAnalyzer(db, min_pattern_precision=0.75)
            >>> cv_results = analyzer.discover_patterns_with_cross_validation(k=5)
            >>> for result in cv_results:
            ...     pattern = result['pattern']
            ...     print(f"{pattern.pattern_name}: "
            ...           f"precision={result['cv_precision_mean']:.2f}±{result['cv_precision_std']:.2f}")
        """
        # Load decisions with features
        decisions_data = self._load_decisions_with_features(filing_id, metric_id)

        if not decisions_data:
            self.logger.warning("No decisions found, cannot perform cross-validation")
            return []

        # Check minimum sample size
        if len(decisions_data) < min_cv_sample_size:
            raise ValueError(
                f"Insufficient data for cross-validation: {len(decisions_data)} decisions "
                f"(minimum {min_cv_sample_size} required for meaningful CV)"
            )

        self.logger.info(
            f"Starting {k}-fold cross-validation with {len(decisions_data)} decisions"
        )

        # Perform stratified k-fold split
        splits = self._stratified_k_fold_split(decisions_data, k=k)

        # Store metrics for each pattern across folds
        # Key: pattern_name -> List[Dict] with metrics for each fold
        pattern_fold_metrics = {}

        # Evaluate each fold
        for fold_idx, (train_data, test_data) in enumerate(splits):
            self.logger.debug(
                f"Fold {fold_idx + 1}/{k}: train={len(train_data)}, test={len(test_data)}"
            )

            # Discover patterns on training data
            # Note: We bypass discover_patterns() to avoid significance filtering here
            # because we want to evaluate all patterns consistently across folds

            # Get significant features from training data
            significant_features = self._get_significant_features(train_data)

            if not significant_features:
                self.logger.warning(f"Fold {fold_idx + 1}: No significant features")
                continue

            # Generate patterns from training data
            train_patterns = []

            if pattern_type is None or pattern_type == "reject_rule":
                reject_patterns = self._generate_single_feature_patterns(
                    train_data,
                    target_decision="reject",
                    significant_features=significant_features,
                )
                for pattern_def in reject_patterns:
                    evaluated = self._evaluate_pattern(
                        pattern_def, train_data, target_decision="reject"
                    )
                    if evaluated:
                        train_patterns.append(evaluated)

            if pattern_type is None or pattern_type == "accept_rule":
                accept_patterns = self._generate_single_feature_patterns(
                    train_data,
                    target_decision="accept",
                    significant_features=significant_features,
                )
                for pattern_def in accept_patterns:
                    evaluated = self._evaluate_pattern(
                        pattern_def, train_data, target_decision="accept"
                    )
                    if evaluated:
                        train_patterns.append(evaluated)

            # Evaluate each pattern on test data (held-out fold)
            for pattern in train_patterns:
                # Compute metrics on test data
                target_decision = (
                    "accept" if pattern.pattern_type == "accept_rule" else "reject"
                )

                # Build true/predicted labels for test data
                true_labels = [d["decision"] for d in test_data]
                predicted_labels = []

                for d in test_data:
                    # Check if pattern matches this candidate
                    candidate_features = CandidateFeatures(**d["features"])
                    matches = pattern.matches(candidate_features)
                    predicted_labels.append(target_decision if matches else "other")

                # Compute performance metrics
                test_metrics = compute_performance_metrics(
                    true_labels, predicted_labels, positive_label=target_decision
                )

                # Store metrics for this pattern in this fold
                pattern_name = pattern.pattern_name
                if pattern_name not in pattern_fold_metrics:
                    pattern_fold_metrics[pattern_name] = {
                        "pattern": pattern,
                        "fold_metrics": [],
                    }

                pattern_fold_metrics[pattern_name]["fold_metrics"].append(
                    {
                        "precision": test_metrics["precision"],
                        "recall": test_metrics["recall"],
                        "f1_score": test_metrics["f1_score"],
                        "support": test_metrics["support"],
                    }
                )

        # Aggregate metrics across folds
        cv_results = []

        for pattern_name, data in pattern_fold_metrics.items():
            pattern = data["pattern"]
            fold_metrics = data["fold_metrics"]

            # Skip if pattern didn't appear in enough folds
            if len(fold_metrics) < k // 2:  # Must appear in at least half the folds
                self.logger.debug(
                    f"Pattern '{pattern_name}' skipped (only {len(fold_metrics)}/{k} folds)"
                )
                continue

            # Compute mean and std for each metric
            precisions = [m["precision"] for m in fold_metrics]
            recalls = [m["recall"] for m in fold_metrics]
            f1_scores = [m["f1_score"] for m in fold_metrics]

            import statistics

            precision_mean = statistics.mean(precisions)
            precision_std = statistics.stdev(precisions) if len(precisions) > 1 else 0.0
            recall_mean = statistics.mean(recalls)
            recall_std = statistics.stdev(recalls) if len(recalls) > 1 else 0.0
            f1_mean = statistics.mean(f1_scores)
            f1_std = statistics.stdev(f1_scores) if len(f1_scores) > 1 else 0.0

            # Check stability (coefficient of variation)
            # CV = std / mean, but only if mean > 0
            is_stable = True
            if precision_mean > 0:
                cv = precision_std / precision_mean
                is_stable = cv <= max_variance

            # Filter by minimum precision (use CV mean)
            if precision_mean < self.min_pattern_precision:
                continue

            cv_results.append(
                {
                    "pattern": pattern,
                    "cv_precision_mean": precision_mean,
                    "cv_precision_std": precision_std,
                    "cv_recall_mean": recall_mean,
                    "cv_recall_std": recall_std,
                    "cv_f1_mean": f1_mean,
                    "cv_f1_std": f1_std,
                    "is_stable": is_stable,
                    "fold_count": len(fold_metrics),
                }
            )

        # Sort by F1 mean descending
        cv_results.sort(key=lambda r: r["cv_f1_mean"], reverse=True)

        # Log summary
        stable_count = sum(1 for r in cv_results if r["is_stable"])
        self.logger.info(
            f"Cross-validation complete: {len(cv_results)} patterns evaluated, "
            f"{stable_count} stable (CV <= {max_variance})"
        )

        return cv_results

    def detect_pattern_conflicts(
        self, patterns: List[LearnedPattern]
    ) -> Dict[str, Any]:
        """
        Detect contradictory and redundant patterns.

        Args:
            patterns: List of LearnedPattern objects to check

        Returns:
            Dict with:
                - contradictory: List of (pattern1, pattern2) pairs with same conditions but different decisions
                - redundant: List of (general_pattern, specific_pattern) pairs where specific is subset
                - warnings: List of warning strings
                - has_conflicts: bool

        Contradictory patterns:
            - Same conditions, different pattern_type (accept_rule vs reject_rule)
            - Example: keyword_distance < 30 → accept vs keyword_distance < 30 → reject

        Redundant patterns:
            - One pattern's conditions are a subset of another's
            - Both have same pattern_type
            - Example: is_in_table=True → reject (general) vs is_in_table=True AND keyword_distance>50 → reject (specific)
        """
        contradictory_pairs: List[tuple] = []
        redundant_pairs: List[tuple] = []
        warnings: List[str] = []

        # Check all pairs of patterns
        for i, pattern1 in enumerate(patterns):
            for j, pattern2 in enumerate(patterns):
                if i >= j:
                    continue  # Skip self-comparison and duplicates

                cond1 = pattern1.pattern_definition.get("conditions", [])
                cond2 = pattern2.pattern_definition.get("conditions", [])

                if not cond1 or not cond2:
                    continue

                # Check if conditions are equivalent
                are_equivalent = self._conditions_equivalent(cond1, cond2)

                if are_equivalent:
                    # Same conditions - check if contradictory
                    if pattern1.pattern_type != pattern2.pattern_type:
                        contradictory_pairs.append((pattern1, pattern2))
                        warnings.append(
                            f"CONTRADICTORY: '{pattern1.pattern_name}' ({pattern1.pattern_type}) "
                            f"vs '{pattern2.pattern_name}' ({pattern2.pattern_type}) have same conditions"
                        )

                # Check for redundancy (one is subset of other)
                if pattern1.pattern_type == pattern2.pattern_type:
                    if self._is_subset_conditions(cond1, cond2):
                        # pattern1 is more general (subset), pattern2 is more specific
                        redundant_pairs.append((pattern1, pattern2))
                        warnings.append(
                            f"REDUNDANT: '{pattern2.pattern_name}' is more specific than "
                            f"'{pattern1.pattern_name}' (both {pattern1.pattern_type})"
                        )
                    elif self._is_subset_conditions(cond2, cond1):
                        # pattern2 is more general, pattern1 is more specific
                        redundant_pairs.append((pattern2, pattern1))
                        warnings.append(
                            f"REDUNDANT: '{pattern1.pattern_name}' is more specific than "
                            f"'{pattern2.pattern_name}' (both {pattern1.pattern_type})"
                        )

        has_conflicts = len(contradictory_pairs) > 0 or len(redundant_pairs) > 0

        return {
            "contradictory": contradictory_pairs,
            "redundant": redundant_pairs,
            "warnings": warnings,
            "has_conflicts": has_conflicts,
        }

    def _conditions_equivalent(
        self, cond1: List[Dict], cond2: List[Dict]
    ) -> bool:
        """
        Check if two condition lists are equivalent (same field, op, value).

        Args:
            cond1: List of condition dicts
            cond2: List of condition dicts

        Returns:
            True if conditions are equivalent
        """
        if len(cond1) != len(cond2):
            return False

        # Normalize conditions for comparison (sort by field name)
        def normalize(cond: Dict) -> tuple:
            return (cond.get("field"), cond.get("op"), cond.get("value"))

        norm1 = sorted([normalize(c) for c in cond1])
        norm2 = sorted([normalize(c) for c in cond2])

        return norm1 == norm2

    def _is_subset_conditions(
        self, general: List[Dict], specific: List[Dict]
    ) -> bool:
        """
        Check if general conditions are a subset of specific conditions.

        Args:
            general: Potentially more general condition list
            specific: Potentially more specific condition list

        Returns:
            True if general is a proper subset of specific
            (all general conditions appear in specific, and specific has more)
        """
        if len(general) >= len(specific):
            return False  # Not a proper subset

        # Normalize conditions
        def normalize(cond: Dict) -> tuple:
            return (cond.get("field"), cond.get("op"), cond.get("value"))

        gen_set = set([normalize(c) for c in general])
        spec_set = set([normalize(c) for c in specific])

        # All general conditions must appear in specific
        return gen_set.issubset(spec_set)

    def _generate_single_feature_patterns(
        self,
        decisions_data: List[Dict[str, Any]],
        target_decision: str,
        significant_features: Optional[set] = None,
    ) -> List[Dict[str, Any]]:
        """
        Generate single-feature candidate patterns.

        Args:
            decisions_data: List of decision dicts with features
            target_decision: 'accept' or 'reject'
            significant_features: Optional set of feature names to include (default: all)

        Returns:
            List of pattern definition dicts, each with:
                - pattern_type: str ('accept_rule' or 'reject_rule')
                - conditions: List[Dict] with feature, operator, value
                - metric_id: Optional[str] (None for MVP - applies to all metrics)

        Process:
            For categorical features:
                - Create pattern for each unique value
            For numeric features:
                - Create patterns at quartile thresholds (25th, 50th, 75th)
                - Use '<=' and '>=' operators

        Note:
            MVP generates simple single-feature patterns.
            Future: combine features for conjunction patterns.
        """
        patterns = []

        # Categorical feature patterns
        for feature_name in self.CATEGORICAL_FEATURES:
            # Skip if not in significant features (when filtering is enabled)
            if significant_features is not None and feature_name not in significant_features:
                continue

            # Collect unique values
            values_set = set()
            for d in decisions_data:
                val = d["features"].get(feature_name)
                if val is not None:
                    # Convert boolean to string
                    if isinstance(val, bool):
                        val = str(val)
                    values_set.add(val)

            # Create pattern for each unique value
            for value in values_set:
                patterns.append(
                    {
                        "pattern_type": f"{target_decision}_rule",
                        "conditions": [
                            {"field": feature_name, "op": "eq", "value": value}
                        ],
                        "metric_id": None,  # Applies to all metrics
                    }
                )

        # Numeric feature patterns
        for feature_name in self.NUMERIC_FEATURES:
            # Skip if not in significant features (when filtering is enabled)
            if significant_features is not None and feature_name not in significant_features:
                continue

            # Collect numeric values
            values = []
            for d in decisions_data:
                val = d["features"].get(feature_name)
                if val is not None:
                    try:
                        values.append(float(val))
                    except (ValueError, TypeError):
                        continue

            if len(values) < 4:
                # Need at least 4 values to compute quartiles
                continue

            # Sort values
            values.sort()

            # Compute quartiles
            n = len(values)
            q1_idx = n // 4
            q2_idx = n // 2
            q3_idx = 3 * n // 4

            q1 = values[q1_idx]
            q2 = values[q2_idx]
            q3 = values[q3_idx]

            # Create patterns at quartile thresholds
            for threshold, op in [
                (q1, "lte"),
                (q2, "lte"),
                (q3, "lte"),
                (q1, "gte"),
                (q2, "gte"),
                (q3, "gte"),
            ]:
                patterns.append(
                    {
                        "pattern_type": f"{target_decision}_rule",
                        "conditions": [
                            {
                                "field": feature_name,
                                "op": op,
                                "value": threshold,
                            }
                        ],
                        "metric_id": None,
                    }
                )

        return patterns

    def _generate_two_feature_patterns(
        self,
        decisions_data: List[Dict[str, Any]],
        target_decision: str,
        significant_features: Optional[set] = None,
        max_features: int = 5,
    ) -> List[Dict[str, Any]]:
        """
        Generate two-feature conjunctive patterns (P2.1).

        Combines the top N most important features to create AND patterns.
        These often have higher precision than single-feature patterns.

        Args:
            decisions_data: List of decision dicts with features
            target_decision: 'accept' or 'reject'
            significant_features: Optional set of feature names to include
            max_features: Maximum number of top features to combine (default: 5)

        Returns:
            List of pattern definition dicts with two conditions each

        Process:
            1. Analyze feature importance (chi-squared for categorical, effect size for numeric)
            2. Select top max_features by importance
            3. Generate single-feature conditions for each top feature
            4. Combine pairs of conditions with AND logic
            5. Return pattern definitions with logic='and'

        Notes:
            - Avoids combinatorial explosion by limiting to top features
            - Only combines conditions from different features
            - Patterns require higher minimum support (recommend min_pattern_support >= 10)

        Example output:
            {
                "pattern_type": "reject_rule",
                "conditions": [
                    {"field": "keyword_distance", "op": "gte", "value": 75},
                    {"field": "is_in_risk_factors", "op": "eq", "value": True}
                ],
                "logic": "and",
                "metric_id": None
            }
        """
        import itertools

        # Step 1: Compute feature importance
        feature_importance = []

        # Compute importance for categorical features
        decisions = [d["decision"] for d in decisions_data]
        for feature_name in self.CATEGORICAL_FEATURES:
            if significant_features is not None and feature_name not in significant_features:
                continue

            feature_values = []
            for d in decisions_data:
                val = d["features"].get(feature_name)
                if val is not None:
                    feature_values.append(val)

            if len(feature_values) < 2:
                continue

            try:
                result = chi_squared_test(feature_values[:len(decisions)], decisions)
                if result["is_valid"]:
                    feature_importance.append((feature_name, result["chi_squared"], "categorical"))
            except:
                continue

        # Compute importance for numeric features
        for feature_name in self.NUMERIC_FEATURES:
            if significant_features is not None and feature_name not in significant_features:
                continue

            # Split by decision
            accept_values = []
            reject_values = []
            for d in decisions_data:
                val = d["features"].get(feature_name)
                if val is not None:
                    try:
                        numeric_val = float(val)
                        if d["decision"] == "accept":
                            accept_values.append(numeric_val)
                        elif d["decision"] == "reject":
                            reject_values.append(numeric_val)
                    except:
                        continue

            if len(accept_values) < 2 or len(reject_values) < 2:
                continue

            try:
                result = t_test_independent(accept_values, reject_values)
                if result["is_valid"]:
                    feature_importance.append((feature_name, abs(result["effect_size"]), "numeric"))
            except:
                continue

        # Step 2: Select top N features by importance
        feature_importance.sort(key=lambda x: x[1], reverse=True)
        top_features = feature_importance[:max_features]

        if len(top_features) < 2:
            self.logger.warning(
                f"Insufficient top features ({len(top_features)}) for two-feature patterns, need at least 2"
            )
            return []

        self.logger.info(
            f"Generating two-feature patterns from top {len(top_features)} features: "
            f"{[f[0] for f in top_features]}"
        )

        # Step 3: Generate single-feature conditions for top features
        feature_conditions = {}  # feature_name -> List[condition_dict]

        for feature_name, importance, feature_type in top_features:
            conditions = []

            if feature_type == "categorical":
                # Get unique values
                values_set = set()
                for d in decisions_data:
                    val = d["features"].get(feature_name)
                    if val is not None:
                        if isinstance(val, bool):
                            val = str(val)
                        values_set.add(val)

                for value in values_set:
                    conditions.append({"field": feature_name, "op": "eq", "value": value})

            elif feature_type == "numeric":
                # Get quartile thresholds
                values = []
                for d in decisions_data:
                    val = d["features"].get(feature_name)
                    if val is not None:
                        try:
                            values.append(float(val))
                        except:
                            continue

                if len(values) >= 4:
                    values.sort()
                    n = len(values)
                    q1 = values[n // 4]
                    q3 = values[3 * n // 4]

                    # Use only Q1 and Q3 for two-feature patterns (avoid too many combinations)
                    conditions.append({"field": feature_name, "op": "lte", "value": q1})
                    conditions.append({"field": feature_name, "op": "gte", "value": q3})

            feature_conditions[feature_name] = conditions

        # Step 4: Generate AND combinations
        patterns = []

        # Get all pairs of features
        feature_pairs = list(itertools.combinations(feature_conditions.keys(), 2))

        for feature1, feature2 in feature_pairs:
            conditions1 = feature_conditions[feature1]
            conditions2 = feature_conditions[feature2]

            # Combine each condition from feature1 with each from feature2
            for cond1 in conditions1:
                for cond2 in conditions2:
                    patterns.append(
                        {
                            "pattern_type": f"{target_decision}_rule",
                            "conditions": [cond1, cond2],
                            "logic": "and",
                            "metric_id": None,
                        }
                    )

        self.logger.info(
            f"Generated {len(patterns)} two-feature pattern candidates from {len(feature_pairs)} feature pairs"
        )

        return patterns

    def _evaluate_pattern(
        self,
        pattern_definition: Dict[str, Any],
        decisions_data: List[Dict[str, Any]],
        target_decision: str,
    ) -> Optional[LearnedPattern]:
        """
        Evaluate pattern performance against decisions.

        Args:
            pattern_definition: Pattern dict with pattern_type, conditions, metric_id
            decisions_data: List of decision dicts with features
            target_decision: 'accept' or 'reject'

        Returns:
            LearnedPattern object with computed metrics, or None if invalid

        Process:
            1. Create temporary LearnedPattern object
            2. For each decision: check if pattern.matches() returns True
            3. Build true_labels and predicted_labels lists
            4. Call compute_performance_metrics()
            5. Create final LearnedPattern with metrics
        """
        # Create temporary pattern for matching
        temp_pattern = LearnedPattern(
            pattern_type=pattern_definition["pattern_type"],
            pattern_name="temp",
            pattern_definition=pattern_definition,
            metric_id=pattern_definition.get("metric_id"),
            precision_score=0.0,
            recall_score=0.0,
            f1_score=0.0,
            sample_count=0,
            status="candidate",
        )

        # Build true and predicted labels
        true_labels = []
        predicted_labels = []

        for d in decisions_data:
            decision = d["decision"]
            features = CandidateFeatures.from_dict(d["features"])

            # True label: whether decision matches target
            true_label = "positive" if decision == target_decision else "negative"
            true_labels.append(true_label)

            # Predicted label: whether pattern matches
            matches = temp_pattern.matches(features)
            predicted_label = "positive" if matches else "negative"
            predicted_labels.append(predicted_label)

        # Compute performance metrics
        metrics = compute_performance_metrics(
            true_labels, predicted_labels, positive_label="positive"
        )

        # Check if we have any support
        if metrics["support"] == 0:
            return None

        # Generate pattern name
        pattern_name = self.generate_pattern_name(
            pattern_definition, pattern_definition["pattern_type"]
        )

        # Create final LearnedPattern
        return LearnedPattern(
            pattern_type=pattern_definition["pattern_type"],
            pattern_name=pattern_name,
            pattern_definition=pattern_definition,
            metric_id=pattern_definition.get("metric_id"),
            precision_score=metrics["precision"],
            recall_score=metrics["recall"],
            f1_score=metrics["f1_score"],
            sample_count=metrics["support"],
            status="candidate",
        )

    def _build_jsonb_where_clause(
        self, pattern_definition: Dict[str, Any]
    ) -> tuple[str, List[Any]]:
        """
        Build SQL WHERE clause from pattern conditions using JSONB operators.

        Args:
            pattern_definition: Pattern dict with conditions and logic

        Returns:
            Tuple of (where_clause, parameters) for safe SQL execution

        Example:
            Input:
                {
                    "conditions": [
                        {"field": "keyword_distance", "op": "lt", "value": 30},
                        {"field": "is_in_risk_factors", "op": "eq", "value": False}
                    ],
                    "logic": "and"
                }

            Output:
                (
                    "(features->>'keyword_distance')::numeric < %s AND (features->>'is_in_risk_factors')::boolean = %s",
                    [30, False]
                )

        Supported operators:
            - eq, ne: equality/inequality
            - gt, lt, gte, lte: numeric comparisons
            - in: value in list
            - contains: substring match (for strings)
        """
        conditions = pattern_definition.get("conditions", [])
        logic = pattern_definition.get("logic", "and").upper()

        if not conditions:
            return ("TRUE", [])

        condition_clauses = []
        parameters = []

        for condition in conditions:
            field_name = condition.get("field")
            op = condition.get("op", "eq")
            value = condition.get("value")

            # Determine the JSON cast based on value type
            if isinstance(value, bool):
                json_cast = "::boolean"
            elif isinstance(value, (int, float)):
                json_cast = "::numeric"
            else:
                json_cast = ""  # String, no cast needed

            # Build the condition based on operator
            if op == "eq":
                clause = f"(features->>'{field_name}'){json_cast} = %s"
                parameters.append(value)
            elif op == "ne":
                clause = f"(features->>'{field_name}'){json_cast} != %s"
                parameters.append(value)
            elif op == "gt":
                clause = f"(features->>'{field_name}'){json_cast} > %s"
                parameters.append(value)
            elif op == "lt":
                clause = f"(features->>'{field_name}'){json_cast} < %s"
                parameters.append(value)
            elif op == "gte":
                clause = f"(features->>'{field_name}'){json_cast} >= %s"
                parameters.append(value)
            elif op == "lte":
                clause = f"(features->>'{field_name}'){json_cast} <= %s"
                parameters.append(value)
            elif op == "in":
                # For IN operator, use ANY with array
                clause = f"(features->>'{field_name}'){json_cast} = ANY(%s)"
                parameters.append(value)  # value should be a list
            elif op == "contains":
                # For substring match
                clause = f"(features->>'{field_name}') LIKE %s"
                parameters.append(f"%{value}%")
            else:
                # Unknown operator - skip this condition
                logger.warning(f"Unknown operator '{op}' in pattern condition")
                continue

            condition_clauses.append(clause)

        if not condition_clauses:
            return ("TRUE", [])

        # Combine conditions with AND/OR
        combined_clause = f" {logic} ".join(condition_clauses)

        # Wrap in parentheses if multiple conditions
        if len(condition_clauses) > 1:
            combined_clause = f"({combined_clause})"

        return (combined_clause, parameters)

    def _evaluate_pattern_db_side(
        self,
        pattern_definition: Dict[str, Any],
        filing_id: Optional[int] = None,
        metric_id: Optional[str] = None,
        target_decision: str = "reject",
    ) -> Optional[LearnedPattern]:
        """
        Evaluate pattern performance using database-side queries.

        This method generates SQL queries with JSONB operators to count matches
        directly in PostgreSQL, which is 10-100x faster than Python-side evaluation
        for large datasets (1000+ decisions).

        Args:
            pattern_definition: Pattern dict with conditions and logic
            filing_id: Optional filter to specific filing
            metric_id: Optional filter to specific metric
            target_decision: 'accept' or 'reject'

        Returns:
            LearnedPattern object with computed metrics, or None if invalid

        Process:
            1. Build SQL WHERE clause from pattern conditions
            2. Execute 4 SQL queries to count:
               - True positives (pattern matches AND decision matches target)
               - False positives (pattern matches AND decision != target)
               - False negatives (pattern doesn't match AND decision matches target)
               - True negatives (pattern doesn't match AND decision != target)
            3. Compute precision/recall/F1 from counts
            4. Create LearnedPattern with metrics

        Performance:
            - Python-side (1000 decisions): ~500-1000ms
            - Database-side (1000 decisions): ~10-50ms
            - Speedup: 10-100x
        """
        # Build WHERE clause for pattern conditions
        pattern_where, pattern_params = self._build_jsonb_where_clause(
            pattern_definition
        )

        # Build base WHERE clause for filing/metric filters
        base_where_parts = []
        base_params = []

        if filing_id is not None:
            base_where_parts.append("rc.filing_id = %s")
            base_params.append(filing_id)

        if metric_id is not None:
            base_where_parts.append("rc.suggested_metric_id = %s")
            base_params.append(metric_id)

        base_where = " AND ".join(base_where_parts) if base_where_parts else "TRUE"

        # Execute count queries
        connection = self.db.get_connection()
        cursor = connection.cursor()

        try:
            # Count true positives (pattern matches AND decision matches target)
            tp_query = f"""
                SELECT COUNT(*)
                FROM review_candidates rc
                INNER JOIN review_decisions rd ON rc.candidate_id = rd.candidate_id
                WHERE {base_where}
                  AND {pattern_where}
                  AND rd.decision = %s
            """
            tp_params = base_params + pattern_params + [target_decision]
            cursor.execute(tp_query, tp_params)
            true_positives = cursor.fetchone()[0]

            # Count false positives (pattern matches AND decision != target)
            fp_query = f"""
                SELECT COUNT(*)
                FROM review_candidates rc
                INNER JOIN review_decisions rd ON rc.candidate_id = rd.candidate_id
                WHERE {base_where}
                  AND {pattern_where}
                  AND rd.decision != %s
            """
            fp_params = base_params + pattern_params + [target_decision]
            cursor.execute(fp_query, fp_params)
            false_positives = cursor.fetchone()[0]

            # Count false negatives (pattern doesn't match AND decision matches target)
            fn_query = f"""
                SELECT COUNT(*)
                FROM review_candidates rc
                INNER JOIN review_decisions rd ON rc.candidate_id = rd.candidate_id
                WHERE {base_where}
                  AND NOT ({pattern_where})
                  AND rd.decision = %s
            """
            fn_params = base_params + pattern_params + [target_decision]
            cursor.execute(fn_query, fn_params)
            false_negatives = cursor.fetchone()[0]

            # Count true negatives (pattern doesn't match AND decision != target)
            tn_query = f"""
                SELECT COUNT(*)
                FROM review_candidates rc
                INNER JOIN review_decisions rd ON rc.candidate_id = rd.candidate_id
                WHERE {base_where}
                  AND NOT ({pattern_where})
                  AND rd.decision != %s
            """
            tn_params = base_params + pattern_params + [target_decision]
            cursor.execute(tn_query, tn_params)
            true_negatives = cursor.fetchone()[0]

        finally:
            cursor.close()

        # Compute metrics
        support = true_positives + false_negatives
        if support == 0:
            return None

        precision = (
            true_positives / (true_positives + false_positives)
            if (true_positives + false_positives) > 0
            else 0.0
        )

        recall = true_positives / support

        f1_score = (
            2 * (precision * recall) / (precision + recall)
            if (precision + recall) > 0
            else 0.0
        )

        # Generate pattern name
        pattern_name = self.generate_pattern_name(
            pattern_definition, pattern_definition["pattern_type"]
        )

        # Create LearnedPattern
        return LearnedPattern(
            pattern_type=pattern_definition["pattern_type"],
            pattern_name=pattern_name,
            pattern_definition=pattern_definition,
            metric_id=pattern_definition.get("metric_id"),
            precision_score=precision,
            recall_score=recall,
            f1_score=f1_score,
            sample_count=support,
            status="candidate",
        )

    def generate_pattern_name(
        self,
        pattern_definition: Dict[str, Any],
        pattern_type: str,
    ) -> str:
        """
        Generate human-readable pattern name from definition.

        Args:
            pattern_definition: Pattern dict with conditions
            pattern_type: 'accept_rule' or 'reject_rule'

        Returns:
            Human-readable pattern name string

        Examples:
            - "Reject: is_in_risk_factors=True"
            - "Accept: keyword_distance <= 25"
            - "Reject: keyword_distance >= 100 AND contains_definition=True"

        Operator mapping:
            - 'eq': '='
            - 'ne': '!='
            - 'lt': '<'
            - 'gt': '>'
            - 'lte': '<='
            - 'gte': '>='
        """
        # Map operators to symbols
        operator_symbols = {
            "eq": "=",
            "ne": "!=",
            "lt": "<",
            "gt": ">",
            "lte": "<=",
            "gte": ">=",
        }

        # Extract action from pattern_type
        action = pattern_type.split("_")[0].capitalize()  # 'accept' or 'reject'

        # Build condition strings
        condition_strings = []
        for condition in pattern_definition["conditions"]:
            field = condition.get("field", condition.get("feature"))  # Support both
            op = condition.get("op", condition.get("operator"))  # Support both
            value = condition["value"]

            # Format value
            if isinstance(value, float):
                value_str = f"{value:.2f}"
            else:
                value_str = str(value)

            # Build condition string
            op_symbol = operator_symbols.get(op, op)
            condition_strings.append(f"{field} {op_symbol} {value_str}")

        # Join conditions with AND
        conditions_str = " AND ".join(condition_strings)

        return f"{action}: {conditions_str}"

    def save_patterns(
        self,
        patterns: List[LearnedPattern],
        auto_approve_threshold: Optional[float] = None,
    ) -> Dict[str, int]:
        """
        Save patterns to database.

        Args:
            patterns: List of LearnedPattern objects to save
            auto_approve_threshold: If provided, auto-approve patterns with
                precision >= this threshold

        Returns:
            Dict with:
                - saved_count: int - Total patterns saved
                - approved_count: int - Patterns auto-approved
                - candidate_count: int - Patterns saved as candidates

        Process:
            1. For each pattern: check if precision >= auto_approve_threshold
            2. If yes: set status='approved', approved_at=now()
            3. Call db.insert_learned_pattern() for each
            4. Return counts
        """
        saved_count = 0
        approved_count = 0
        candidate_count = 0

        for pattern in patterns:
            # Determine status
            if (
                auto_approve_threshold is not None
                and pattern.precision_score >= auto_approve_threshold
            ):
                pattern.status = "approved"
                from datetime import datetime

                pattern.approved_at = datetime.now()
                approved_count += 1
            else:
                pattern.status = "candidate"
                candidate_count += 1

            # Save to database
            success = self.db.insert_learned_pattern(pattern)
            if success:
                saved_count += 1
            else:
                self.logger.warning(
                    f"Failed to save pattern: {pattern.pattern_name}"
                )

        self.logger.info(
            f"Saved {saved_count} patterns "
            f"({approved_count} approved, {candidate_count} candidates)"
        )

        return {
            "saved_count": saved_count,
            "approved_count": approved_count,
            "candidate_count": candidate_count,
        }

    def generate_pattern_explanation(
        self,
        pattern: LearnedPattern,
        filing_id: Optional[int] = None,
        metric_id: Optional[str] = None,
        num_examples: int = 3,
    ) -> str:
        """
        Generate natural language explanation for a pattern (P2.3).

        Args:
            pattern: LearnedPattern to explain
            filing_id: Optional filing_id to filter candidates
            metric_id: Optional metric_id to filter candidates
            num_examples: Number of example candidates to include (default 3)

        Returns:
            Human-readable explanation string with:
                - Pattern description in plain language
                - 2-3 example candidates that match
                - Precision/recall interpretation

        Example:
            >>> explanation = analyzer.generate_pattern_explanation(pattern)
            >>> print(explanation)
            Pattern: "Reject: keyword_distance > 75"

            Explanation:
            This pattern rejects candidates where the metric keyword is more than 75
            characters away from the number...

            Examples:
            - "Revenue was $5M... [80 chars later] ...customers increased" → Rejected ✓

            Performance:
            Precision: 87% (13/15 correct rejections)
            Recall: 32% (13/41 total rejections matched this pattern)
        """
        lines = []

        # Header
        lines.append(f"Pattern: \"{pattern.pattern_name}\"")
        lines.append("")

        # Natural language explanation
        lines.append("Explanation:")
        explanation_text = self._generate_pattern_description(pattern)
        lines.append(explanation_text)
        lines.append("")

        # Examples
        examples = self._get_pattern_examples(
            pattern, filing_id, metric_id, num_examples
        )
        if examples:
            lines.append("Examples:")
            for example in examples:
                lines.append(example)
            lines.append("")

        # Performance metrics
        lines.append("Performance:")
        performance_text = self._format_performance_metrics(pattern)
        lines.append(performance_text)

        return "\n".join(lines)

    def _generate_pattern_description(self, pattern: LearnedPattern) -> str:
        """
        Generate plain language description of what the pattern does.

        Args:
            pattern: LearnedPattern to describe

        Returns:
            Natural language description string
        """
        pattern_def = pattern.pattern_definition
        pattern_type = pattern.pattern_type
        conditions = pattern_def.get("conditions", [])
        logic = pattern_def.get("logic", "and")

        if not conditions:
            return "This pattern has no conditions (matches all candidates)."

        # Build description based on pattern type
        action = "rejects" if pattern_type == "reject_rule" else "accepts"

        # Single condition
        if len(conditions) == 1:
            cond = conditions[0]
            cond_desc = self._describe_condition(cond)
            return f"This pattern {action} candidates where {cond_desc}."

        # Multiple conditions
        connector = logic.upper()
        condition_descriptions = [
            self._describe_condition(cond) for cond in conditions
        ]

        if connector == "AND":
            main_desc = f"This pattern {action} candidates where ALL of the following are true:\n"
            for i, desc in enumerate(condition_descriptions, 1):
                main_desc += f"  {i}. {desc}\n"
            return main_desc.rstrip()
        else:  # OR
            main_desc = f"This pattern {action} candidates where ANY of the following are true:\n"
            for i, desc in enumerate(condition_descriptions, 1):
                main_desc += f"  {i}. {desc}\n"
            return main_desc.rstrip()

    def _describe_condition(self, condition: Dict[str, Any]) -> str:
        """
        Convert a single condition to natural language.

        Args:
            condition: Dict with field, op, value keys

        Returns:
            Natural language description
        """
        field = condition["field"]
        op = condition["op"]
        value = condition["value"]

        # Field name mappings to readable names
        field_names = {
            "keyword_distance": "the distance from the number to the metric keyword",
            "keyword_position": "the position of the keyword relative to the number",
            "number_format": "the number format",
            "value_magnitude": "the magnitude of the value (log10)",
            "is_in_table": "the candidate is in a table",
            "is_in_risk_factors": "the candidate is in the risk factors section",
            "contains_definition_language": "the context contains definition language",
            "has_period_mention": "the context mentions a time period",
            "surrounding_numbers_count": "the count of nearby numbers",
            "context_word_count": "the number of context words",
        }

        field_name = field_names.get(field, field)

        # Operator mappings
        if op == "eq":
            if isinstance(value, bool):
                return f"{field_name} is {value}"
            return f"{field_name} equals {value}"
        elif op == "ne":
            if isinstance(value, bool):
                return f"{field_name} is not {value}"
            return f"{field_name} does not equal {value}"
        elif op == "lt":
            return f"{field_name} is less than {value}"
        elif op == "gt":
            return f"{field_name} is greater than {value}"
        elif op == "lte":
            return f"{field_name} is at most {value}"
        elif op == "gte":
            return f"{field_name} is at least {value}"
        elif op == "in":
            values_str = ", ".join(str(v) for v in value)
            return f"{field_name} is one of: {values_str}"
        elif op == "contains":
            return f"{field_name} contains {value}"
        else:
            return f"{field_name} {op} {value}"

    def _get_pattern_examples(
        self,
        pattern: LearnedPattern,
        filing_id: Optional[int],
        metric_id: Optional[str],
        num_examples: int,
    ) -> List[str]:
        """
        Get example candidates that match the pattern.

        Args:
            pattern: LearnedPattern to get examples for
            filing_id: Optional filing_id filter
            metric_id: Optional metric_id filter
            num_examples: Number of examples to return

        Returns:
            List of formatted example strings
        """
        from src.review.models import CandidateFeatures

        # Query database directly for candidates with all fields
        if filing_id:
            candidates = self.db.get_review_candidates_with_decisions(
                filing_id=filing_id,
                status="reviewed",
            )
        else:
            candidates = self.db.get_all_reviewed_candidates_with_decisions(
                metric_id=metric_id,
            )

        if not candidates:
            return []

        # Find matching candidates
        matching_candidates = []
        for candidate in candidates:
            # Skip if no decision
            if not candidate.get("decision"):
                continue

            # Skip if filtering by metric_id
            if metric_id and candidate.get("suggested_metric_id") != metric_id:
                continue

            # Check if pattern matches
            features_dict = candidate.get("features")
            if not features_dict:
                continue

            try:
                features = CandidateFeatures.from_dict(features_dict)
                if pattern.matches(features):
                    matching_candidates.append(candidate)
            except Exception as e:
                self.logger.warning(
                    f"Failed to create CandidateFeatures from dict: {e}"
                )
                continue

        if not matching_candidates:
            return []

        # Format examples (limit to num_examples)
        examples = []
        for candidate in matching_candidates[:num_examples]:
            # Extract key info
            context = candidate.get("context_text", "")
            raw_number = candidate.get("raw_number_text", "")
            keyword = candidate.get("triggering_keyword", "")
            decision = candidate.get("decision", "unknown")

            # Truncate long context
            if len(context) > 120:
                context = context[:117] + "..."

            # Format decision result
            if pattern.pattern_type == "reject_rule":
                result = "✓" if decision == "reject" else "✗"
            else:
                result = "✓" if decision == "accept" else "✗"

            # Build example string
            example = f'  - "{context}" [keyword: {keyword}, value: {raw_number}] → {result}'
            examples.append(example)

        return examples

    def _format_performance_metrics(self, pattern: LearnedPattern) -> str:
        """
        Format precision/recall metrics with interpretation.

        Args:
            pattern: LearnedPattern with performance metrics

        Returns:
            Formatted performance string
        """
        precision = pattern.precision_score
        recall = pattern.recall_score
        f1 = pattern.f1_score

        # Get counts if available
        tp = pattern.true_positives if hasattr(pattern, "true_positives") else None
        fp = pattern.false_positives if hasattr(pattern, "false_positives") else None
        fn = pattern.false_negatives if hasattr(pattern, "false_negatives") else None

        lines = []

        # Precision interpretation
        if precision is not None:
            if tp is not None and (tp + fp) > 0:
                precision_pct = int(precision * 100)
                total_predictions = tp + fp
                lines.append(
                    f"  Precision: {precision_pct}% ({tp}/{total_predictions} correct predictions)"
                )
            else:
                precision_pct = int(precision * 100)
                lines.append(f"  Precision: {precision_pct}%")

        # Recall interpretation
        if recall is not None:
            if tp is not None and fn is not None and (tp + fn) > 0:
                recall_pct = int(recall * 100)
                total_actual = tp + fn
                lines.append(
                    f"  Recall: {recall_pct}% ({tp}/{total_actual} cases detected)"
                )
            else:
                recall_pct = int(recall * 100)
                lines.append(f"  Recall: {recall_pct}%")

        # F1 score
        if f1 is not None:
            f1_pct = int(f1 * 100)
            lines.append(f"  F1 Score: {f1_pct}%")

        return "\n".join(lines)
