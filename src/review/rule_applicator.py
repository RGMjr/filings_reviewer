"""
E2: Rule Applicator - Apply Learned Patterns to Filter Review Candidates

This module loads approved patterns from the learned_patterns table and applies
them as filters during candidate generation to improve precision.

Design:
- Loads patterns from database with caching (5-minute default reload interval)
- Applies reject_rule patterns to filter false positives
- Uses LearnedPattern.matches() for pattern evaluation (no code generation)
- Lazy-loaded by CandidateGenerator to avoid overhead when disabled

Workflow:
1. Human reviews candidates → decisions stored in review_decisions
2. E1 (PatternAnalyzer) discovers patterns → stored in learned_patterns (status='candidate')
3. Human approves patterns → status='approved'
4. E2 (RuleApplicator) loads approved patterns and filters candidates
5. Improved candidates → more human review → better patterns (feedback loop)

Example:
    from src.review.rule_applicator import RuleApplicator

    applicator = RuleApplicator(db_adapter)
    should_filter, reason = applicator.should_filter(candidate, features)
    if should_filter:
        print(f"Filtered: {reason}")
"""

import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from src.infra.db import DatabaseAdapter
from src.review.models import CandidateFeatures, LearnedPattern, ReviewCandidate

logger = logging.getLogger(__name__)


class RuleApplicator:
    """
    Apply learned patterns to filter review candidates during generation.

    Loads approved patterns from the learned_patterns database table and caches
    them in memory. Provides should_filter() method to check if a candidate
    matches any reject_rule patterns.

    Performance:
    - Patterns cached in memory (reload every 5 minutes by default)
    - Lazy evaluation (only loads patterns if apply_learned_rules=True)
    - O(1) pattern lookup by metric_id (P4 optimization)
    - Early exit on first matching reject pattern

    Attributes:
        db: DatabaseAdapter instance for loading patterns
        reload_interval: How often to reload patterns (seconds)
    """

    def __init__(self, db_adapter: DatabaseAdapter, reload_interval_seconds: int = 300):
        """
        Initialize rule applicator with database connection.

        Args:
            db_adapter: DatabaseAdapter instance for querying learned_patterns
            reload_interval_seconds: Cache expiration time (default: 5 minutes)

        Raises:
            ValueError: If reload_interval_seconds < 1
        """
        if reload_interval_seconds < 1:
            raise ValueError("reload_interval_seconds must be at least 1")

        self.db = db_adapter
        self.reload_interval = reload_interval_seconds
        self._patterns: List[LearnedPattern] = []
        self._patterns_by_metric: Dict[Optional[str], List[LearnedPattern]] = {}
        self._last_reload: Optional[datetime] = None
        self._reload_patterns()

    def _reload_patterns(self) -> None:
        """
        Load approved patterns from database and update cache.

        Queries learned_patterns table for status='approved', converts to
        LearnedPattern objects, builds metric_id index, and updates cache timestamp.

        Logs:
            INFO: Number of patterns loaded
            WARNING: If database query fails
        """
        try:
            patterns_data = self.db.get_learned_patterns(status="approved")
            self._patterns = [
                LearnedPattern.from_row(row) for row in patterns_data
            ]
            self._patterns_by_metric = self._build_index(self._patterns)
            self._last_reload = datetime.now()
            logger.info(f"Loaded {len(self._patterns)} approved patterns from database")
        except Exception as e:
            logger.warning(f"Failed to reload patterns: {e}", exc_info=True)
            # Keep existing patterns if reload fails
            if self._last_reload is None:
                # First load failed - start with empty pattern list
                self._patterns = []
                self._patterns_by_metric = {}
                self._last_reload = datetime.now()

    def _check_reload(self) -> None:
        """
        Check if pattern cache expired and reload if necessary.

        Reloads patterns if:
        - Cache has never been loaded (_last_reload is None)
        - Time since last reload exceeds reload_interval
        """
        if self._last_reload is None:
            self._reload_patterns()
        elif (datetime.now() - self._last_reload).total_seconds() > self.reload_interval:
            logger.debug("Pattern cache expired, reloading...")
            self._reload_patterns()

    def _build_index(
        self, patterns: List[LearnedPattern]
    ) -> Dict[Optional[str], List[LearnedPattern]]:
        """
        Build an index of patterns by metric_id for O(1) lookup.

        Groups reject_rule patterns by their metric_id to enable fast lookups
        during candidate filtering. Patterns with metric_id=None are stored
        under the None key (global patterns).

        Args:
            patterns: List of LearnedPattern objects to index

        Returns:
            Dictionary mapping metric_id (or None for global) to list of patterns

        Example:
            >>> index = self._build_index(patterns)
            >>> arr_patterns = index.get("annual_recurring_revenue", [])
            >>> global_patterns = index.get(None, [])
        """
        index: Dict[Optional[str], List[LearnedPattern]] = {}
        for pattern in patterns:
            # Only index reject_rule patterns (used in should_filter)
            if pattern.pattern_type == "reject_rule":
                key = pattern.metric_id  # None for global patterns
                if key not in index:
                    index[key] = []
                index[key].append(pattern)
        return index

    def should_filter(
        self, candidate: ReviewCandidate, features: CandidateFeatures
    ) -> Tuple[bool, Optional[str]]:
        """
        Check if candidate should be filtered based on learned reject patterns.

        Uses O(1) indexed lookup by metric_id for fast pattern matching.
        Applies patterns in this order:
        1. Metric-specific reject_rule patterns (where pattern.metric_id matches)
        2. Global reject_rule patterns (where pattern.metric_id is None)

        Returns on first matching pattern (early exit for performance).

        Args:
            candidate: ReviewCandidate object with metric info
            features: CandidateFeatures extracted from candidate

        Returns:
            Tuple of (should_filter, reason):
            - should_filter: True if candidate matches a reject_rule pattern
            - reason: Pattern name if filtered, None otherwise

        Example:
            >>> applicator = RuleApplicator(db)
            >>> should_filter, reason = applicator.should_filter(candidate, features)
            >>> if should_filter:
            ...     print(f"Rejected: {reason}")
            Rejected: Learned rule: risk_factors_filter
        """
        self._check_reload()

        # Apply metric-specific reject patterns first (O(1) lookup)
        if candidate.suggested_metric_id:
            metric_patterns = self._patterns_by_metric.get(
                candidate.suggested_metric_id, []
            )
            for pattern in metric_patterns:
                if pattern.matches(features):
                    return True, f"Learned rule: {pattern.pattern_name}"

        # Then apply global reject patterns (O(1) lookup)
        global_patterns = self._patterns_by_metric.get(None, [])
        for pattern in global_patterns:
            if pattern.matches(features):
                return True, f"Learned rule: {pattern.pattern_name}"

        return False, None

    def get_stats(self) -> Dict[str, Any]:
        """
        Return statistics about loaded patterns.

        Returns:
            Dictionary with keys:
            - total_patterns: Total number of approved patterns loaded
            - reject_patterns: Count of reject_rule patterns
            - accept_patterns: Count of accept_rule patterns
            - feature_weight_patterns: Count of feature_weight patterns
            - last_reload: ISO timestamp of last pattern reload (or None)
            - cache_age_seconds: Seconds since last reload (or None)

        Example:
            >>> stats = applicator.get_stats()
            >>> print(f"Loaded {stats['total_patterns']} patterns")
            Loaded 15 patterns
        """
        self._check_reload()

        reject_count = sum(
            1 for p in self._patterns if p.pattern_type == "reject_rule"
        )
        accept_count = sum(
            1 for p in self._patterns if p.pattern_type == "accept_rule"
        )
        weight_count = sum(
            1 for p in self._patterns if p.pattern_type == "feature_weight"
        )

        cache_age = None
        if self._last_reload:
            cache_age = (datetime.now() - self._last_reload).total_seconds()

        return {
            "total_patterns": len(self._patterns),
            "reject_patterns": reject_count,
            "accept_patterns": accept_count,
            "feature_weight_patterns": weight_count,
            "last_reload": (
                self._last_reload.isoformat() if self._last_reload else None
            ),
            "cache_age_seconds": cache_age,
        }

    def force_reload(self) -> None:
        """
        Force immediate reload of patterns from database.

        Useful when patterns are updated and immediate application is needed
        (bypasses cache expiration check).

        Example:
            >>> applicator.force_reload()
            >>> # Patterns now reflect latest database state
        """
        logger.info("Forcing pattern reload (bypassing cache)")
        self._reload_patterns()
