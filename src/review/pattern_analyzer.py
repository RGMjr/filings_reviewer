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
            The significance_threshold is currently not used (MVP returns p_value=None).
            It's included for future enhancement when p-value approximation is added.
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
            # Load across all filings (requires new method or query all filings)
            # For now, raise NotImplementedError - will add in Phase 4
            raise NotImplementedError(
                "Loading decisions across all filings not yet implemented. "
                "Pass filing_id parameter or wait for Phase 4 database enhancement."
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

    def discover_patterns(
        self,
        filing_id: Optional[int] = None,
        metric_id: Optional[str] = None,
        pattern_type: Optional[str] = None,
    ) -> List[LearnedPattern]:
        """
        Discover high-precision patterns from review decisions.

        Args:
            filing_id: Optional filter to specific filing
            metric_id: Optional filter to specific metric
            pattern_type: Optional filter by pattern type ('accept_rule' or 'reject_rule')

        Returns:
            List of LearnedPattern objects sorted by F1 score descending

        Process:
            1. Load decisions with features
            2. Generate candidate patterns (single-feature for MVP)
            3. For each candidate: evaluate precision/recall/F1
            4. Filter by min_pattern_precision and min_pattern_support
            5. Return patterns sorted by F1 descending

        Note:
            MVP implementation generates single-feature patterns only.
            Future enhancement: multi-feature conjunction patterns.
        """
        # Load decisions with features
        decisions_data = self._load_decisions_with_features(filing_id, metric_id)

        if not decisions_data:
            self.logger.warning("No decisions found, cannot discover patterns")
            return []

        # Generate candidate patterns
        patterns = []

        # Generate rejection patterns if requested
        if pattern_type is None or pattern_type == "reject_rule":
            reject_patterns = self._generate_single_feature_patterns(
                decisions_data, target_decision="reject"
            )
            for pattern_def in reject_patterns:
                evaluated = self._evaluate_pattern(
                    pattern_def, decisions_data, target_decision="reject"
                )
                if evaluated:
                    patterns.append(evaluated)

        # Generate acceptance patterns if requested
        if pattern_type is None or pattern_type == "accept_rule":
            accept_patterns = self._generate_single_feature_patterns(
                decisions_data, target_decision="accept"
            )
            for pattern_def in accept_patterns:
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

        self.logger.info(
            f"Discovered {len(filtered_patterns)} patterns "
            f"(precision >= {self.min_pattern_precision}, "
            f"support >= {self.min_pattern_support})"
        )

        return filtered_patterns

    def _generate_single_feature_patterns(
        self,
        decisions_data: List[Dict[str, Any]],
        target_decision: str,
    ) -> List[Dict[str, Any]]:
        """
        Generate single-feature candidate patterns.

        Args:
            decisions_data: List of decision dicts with features
            target_decision: 'accept' or 'reject'

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
                            {"feature": feature_name, "operator": "eq", "value": value}
                        ],
                        "metric_id": None,  # Applies to all metrics
                    }
                )

        # Numeric feature patterns
        for feature_name in self.NUMERIC_FEATURES:
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
            for threshold, operator in [
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
                                "feature": feature_name,
                                "operator": operator,
                                "value": threshold,
                            }
                        ],
                        "metric_id": None,
                    }
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
            feature = condition["feature"]
            operator = condition["operator"]
            value = condition["value"]

            # Format value
            if isinstance(value, float):
                value_str = f"{value:.2f}"
            else:
                value_str = str(value)

            # Build condition string
            op_symbol = operator_symbols.get(operator, operator)
            condition_strings.append(f"{feature} {op_symbol} {value_str}")

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
