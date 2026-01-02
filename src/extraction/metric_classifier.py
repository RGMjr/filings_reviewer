"""
Metric Classifier - Classify segments for metric content.

This module scans source segments to identify:
- Numeric disclosures of metrics
- Metric definitions
- Calculation methodologies
- Which specific metrics are present

IMPORTANT: All keyword patterns are loaded from config/metric_keywords.yaml.
The YAML file is the SOLE authoritative source of truth for:
- Metric keyword patterns
- Exclusion patterns
- Specific patterns (for confidence bonuses)
- Required context patterns
- Metric aliases (for gold standard validation)

Do NOT add hardcoded keyword patterns to this file. Edit the YAML instead.
See CLAUDE.md design decision #8 (externalized keyword configuration).
"""

import logging
import re
import time
from dataclasses import dataclass, field
from typing import cast

from .models import SourceSegment
from .validators import ClassificationValidator

logger = logging.getLogger(__name__)


@dataclass
class ClassificationMetrics:
    """Metrics collected during segment classification.

    Tracks performance, classification statistics, and confidence distribution.
    """

    total_segments: int = 0
    definitions: int = 0
    methodologies: int = 0
    numeric_disclosures: int = 0
    total_confidence: float = 0.0
    metric_id_counts: dict[str, int] = field(default_factory=dict)
    classification_time_seconds: float = 0.0

    def avg_confidence(self) -> float:
        """Calculate average confidence score."""
        if self.total_segments == 0:
            return 0.0
        return self.total_confidence / self.total_segments

    def top_metrics(self, n: int = 5) -> list[tuple[str, int]]:
        """Get top N most common metric IDs.

        Returns:
            List of (metric_id, count) tuples sorted by count descending
        """
        sorted_metrics = sorted(
            self.metric_id_counts.items(), key=lambda x: x[1], reverse=True
        )
        return sorted_metrics[:n]

    def summary(self) -> str:
        """Generate human-readable summary."""
        top_5 = self.top_metrics(5)
        top_metrics_str = ", ".join(f"{mid}: {cnt}" for mid, cnt in top_5)
        return (
            f"{self.total_segments} segments in {self.classification_time_seconds:.3f}s "
            f"({self.definitions} definitions, {self.methodologies} methodologies, "
            f"{self.numeric_disclosures} numeric, avg confidence: {self.avg_confidence():.2f}, "
            f"top metrics: {top_metrics_str})"
        )


class MetricClassifier:
    """
    Classify source segments for metric-related content.

    This classifier uses rule-based keyword matching to identify:
    1. Segments containing metric definitions
    2. Segments containing calculation methodologies
    3. Segments containing numeric disclosures
    4. Which specific metrics are mentioned (candidate_metric_ids)
    """

    # Definition indicators
    # Note: Patterns must be specific enough to avoid false positives.
    # For example, "\bmeans\b" alone matches "this means that" (implication),
    # not just "X means Y" (definition). Use patterns that require definition context.
    DEFINITION_PATTERNS = [
        r"\bwe\s+define\b",
        r"\bdefined\s+as\b",
        r"\bdefinition\s+of\b",
        r"\brefers\s+to\b",
        # "means" only when in clear definition context:
        # 1. Quoted term followed by "means" (handles straight ", curly "", and « quotes)
        r'[\u0022\u201c\u201d\u00ab\u00bb]\w[^\u0022\u201c\u201d\u00ab\u00bb]*[\u0022\u201c\u201d\u00ab\u00bb]\s*means\b',
        # 2. Bullet point definition at start: • "Term" means (limited to 50 chars for term)
        r'(?:^|[\n\u2022])\s*[\u0022\u201c\u201d][^\u0022\u201c\u201d]{1,50}[\u0022\u201c\u201d]\s*means\b',
        r"\bmeaning\s+of\b",  # More specific than just "meaning"
        r"\bmetric\s+definitions?\b",
        r"\bis\s+defined\b",
        # 3. Explicit "the term" definition pattern
        r'\bthe\s+term\s+[\u0022\u201c\u201d][^\u0022\u201c\u201d]+[\u0022\u201c\u201d]\s*means\b',
    ]

    # Methodology/calculation indicators
    METHODOLOGY_PATTERNS = [
        r"\bcalculated\s+as\b",
        r"\bcalculated\s+by\b",
        r"\bcalculation\b",
        r"\bcomputed\s+as\b",
        r"\bdetermined\s+by\b",
        r"\bformula\b",
        r"\bmethodology\b",
        r"\bcompute[ds]?\b",
    ]

    # NOTE: All metric keyword patterns are loaded from config/metric_keywords.yaml.
    # The _load_keywords() method reads patterns from YAML at initialization.
    # Do NOT add hardcoded patterns here. Edit the YAML file instead.
    # See CLAUDE.md design decision #8 (externalized keyword configuration).

    # CMASB Priority Metrics (for confidence boosting)
    CMASB_CORE_METRICS = {
        'cm_new_customers_acquired',
        'cm_customers_period_end_by_tenure',
        'cm_revenue_by_cohort',
        'cm_transactions_by_cohort',
    }

    CMASB_EXTENDED_METRICS = {
        'cm_customer_acquisition_cost',
        'cm_active_customers_total',
        'cm_customers_period_end',
        'cm_large_customers_period_end',
        'cm_revenue_per_customer',
        'cm_gross_margin_by_cohort',
        'cm_arr',
        'cm_mrr',
        'cm_revenue_concentration',
        'cm_customer_churn_rate',
        'cm_customer_retention_rate',
        'cm_net_revenue_retention',
        'cm_expansion_revenue',
        # T5: Revenue predictability metrics
        'cm_bookings',
        'cm_billings',
        # cm_deferred_revenue - REMOVED 2025-12-26 (financial metric, not customer metric)
        # T6: E-commerce metrics
        'cm_average_order_value',
        'cm_repeat_purchase_rate',
        # T7: Marketplace metrics
        'cm_gmv',
        # cm_take_rate - REMOVED 2026-01-02 (platform revenue metric, not customer metric)
        # T8: SaaS contract metrics
        'cm_acv',
        'cm_tcv',
    }

    # NOTE: Required context patterns are loaded from config/metric_keywords.yaml.
    # See the required_context field in YAML for metrics like cm_gmv, cm_tcv, etc.
    # Do NOT add hardcoded context requirements here. Edit the YAML file instead.

    # General customer/metric keywords (for numeric disclosure detection)
    GENERAL_METRIC_KEYWORDS = [
        r"\bcustomers?\b",
        r"\busers?\b",
        r"\bsubscribers?\b",
        r"\bcohort[s]?\b",
        r"\brevenue\b",
        r"\btransactions?\b",
        r"\bmetrics?\b",
    ]

    # Number patterns
    NUMBER_PATTERN = r"\b\d{1,3}(?:,\d{3})*(?:\.\d+)?(?:\s*(?:million|billion|thousand|%|percent))?\b"

    def __init__(self) -> None:
        """Initialize the metric classifier."""
        # Compile all patterns for performance
        self._definition_regex = [
            re.compile(p, re.IGNORECASE) for p in self.DEFINITION_PATTERNS
        ]
        self._methodology_regex = [
            re.compile(p, re.IGNORECASE) for p in self.METHODOLOGY_PATTERNS
        ]
        self._general_metric_regex = [
            re.compile(p, re.IGNORECASE) for p in self.GENERAL_METRIC_KEYWORDS
        ]
        self._number_regex = re.compile(self.NUMBER_PATTERN, re.IGNORECASE)

        # Load keyword patterns (YAML or hardcoded)
        keyword_source = self._load_keywords()

        # Compile metric-specific patterns
        self._metric_patterns = {}
        for metric_id, patterns in keyword_source.items():
            self._metric_patterns[metric_id] = [
                re.compile(p, re.IGNORECASE) for p in patterns
            ]

        # Metrics tracking
        self._metrics: ClassificationMetrics | None = None

    def _load_keywords(self) -> dict[str, list[str]]:
        """
        Load keyword patterns from YAML config.

        Returns:
            Dictionary mapping metric_id to list of regex patterns.

        Raises:
            KeywordConfigError: If YAML config cannot be loaded.
        """
        from .keyword_config import get_metric_keywords
        keywords = get_metric_keywords()
        logger.debug(f"Loaded {len(keywords)} metrics from YAML config")
        # Cast needed for mypy --strict when checking this file alone
        # (yaml stubs not installed, so get_metric_keywords return type is Any)
        return cast(dict[str, list[str]], keywords)

    def classify_segment(self, segment: SourceSegment, validate: bool = True) -> SourceSegment:
        """
        Classify a single segment.

        Updates the segment's classification flags and candidate_metric_ids.

        Args:
            segment: SourceSegment to classify
            validate: If True, validate segment before classification (default: True)

        Returns:
            Updated SourceSegment

        Raises:
            ValidationError: If segment validation fails and validate=True
        """
        # Validate segment if requested
        if validate:
            ClassificationValidator.validate_segment_for_classification(segment)

        text = segment.raw_text.lower()

        # Check for definition
        segment.contains_definition_flag = self._has_definition(text)

        # Check for methodology
        segment.contains_methodology_flag = self._has_methodology(text)

        # Check for numeric disclosure
        segment.contains_numeric_disclosure_flag = self._has_numeric_disclosure(text)

        # Identify candidate metrics
        segment.candidate_metric_ids = self._identify_candidate_metrics(text)

        # Compute confidence score
        segment.classifier_confidence = self._compute_confidence(segment)

        return segment

    def classify_batch(self, segments: list[SourceSegment], validate: bool = True) -> list[SourceSegment]:
        """
        Classify multiple segments efficiently with metrics collection.

        Args:
            segments: List of SourceSegments to classify
            validate: If True, validate segments before classification (default: True)

        Returns:
            List of updated SourceSegments
        """
        start_time = time.time()

        # Initialize metrics
        self._metrics = ClassificationMetrics()

        classified = []
        for segment in segments:
            classified_segment = self.classify_segment(segment, validate=validate)
            classified.append(classified_segment)

            # Update metrics
            self._metrics.total_segments += 1

            if classified_segment.contains_definition_flag:
                self._metrics.definitions += 1

            if classified_segment.contains_methodology_flag:
                self._metrics.methodologies += 1

            if classified_segment.contains_numeric_disclosure_flag:
                self._metrics.numeric_disclosures += 1

            # Track confidence
            confidence = classified_segment.classifier_confidence or 0.0
            self._metrics.total_confidence += confidence

            # Track metric IDs
            for metric_id in (classified_segment.candidate_metric_ids or []):
                self._metrics.metric_id_counts[metric_id] = (
                    self._metrics.metric_id_counts.get(metric_id, 0) + 1
                )

        # Finalize metrics
        self._metrics.classification_time_seconds = time.time() - start_time

        # Enhanced logging
        logger.info(f"Classified {len(classified)} segments: {self._metrics.summary()}")

        return classified

    def get_metrics(self) -> ClassificationMetrics | None:
        """Get metrics from most recent classification batch.

        Returns:
            ClassificationMetrics object or None if no classification has been performed

        Example:
            classifier = MetricClassifier()
            segments = classifier.classify_batch(segments)
            metrics = classifier.get_metrics()
            print(f"Avg confidence: {metrics.avg_confidence():.2f}")
        """
        return self._metrics

    def _has_definition(self, text: str) -> bool:
        """Check if text contains definition indicators."""
        for pattern in self._definition_regex:
            if pattern.search(text):
                return True
        return False

    def _has_methodology(self, text: str) -> bool:
        """Check if text contains methodology/calculation indicators."""
        for pattern in self._methodology_regex:
            if pattern.search(text):
                return True
        return False

    def _has_numeric_disclosure(self, text: str) -> bool:
        """
        Check if text contains numeric disclosure of metrics.

        A segment is considered a numeric disclosure if it contains:
        1. At least one number
        2. At least one general metric keyword
        """
        # Must have numbers
        if not self._number_regex.search(text):
            return False

        # Must have metric-related keywords
        for pattern in self._general_metric_regex:
            if pattern.search(text):
                return True

        return False

    def _identify_candidate_metrics(self, text: str) -> list[str]:
        """
        Identify which specific metrics might be present in the text.

        Returns:
            List of metric IDs that match keyword patterns
        """
        candidates = []

        for metric_id, patterns in self._metric_patterns.items():
            for pattern in patterns:
                if pattern.search(text):
                    candidates.append(metric_id)
                    break  # Only add each metric once

        return candidates

    def _has_cohort_patterns(self, text: str) -> bool:
        """
        Detect cohort analysis language patterns.

        Checks for keywords indicating cohort-based analysis which is a
        goldmine indicator for high-value metric segments.

        Args:
            text: Text to analyze

        Returns:
            True if cohort analysis language detected
        """
        if not text:
            return False

        text_lower = text.lower()

        cohort_keywords = [
            'cohort',
            'by tenure',
            'by vintage',
            'by acquisition',
            'first year customers',
            'repeat customers',
            'new vs existing',
            'existing vs new',
            'customer age',
            'customer lifetime',
            'acquired in 20',  # matches "acquired in 2015", "acquired in 2017", etc.
        ]

        return any(kw in text_lower for kw in cohort_keywords)

    def _has_temporal_patterns(self, text: str) -> bool:
        """
        Detect temporal trend language patterns.

        Checks for multiple year mentions indicating time-series data
        which is a goldmine indicator for high-value metric segments.

        Args:
            text: Text to analyze

        Returns:
            True if multiple time periods detected (2+ distinct years)
        """
        if not text:
            return False

        year_pattern = r'\b20\d{2}\b'
        years = re.findall(year_pattern, text)
        unique_years = set(years)

        return len(unique_years) >= 2

    def _compute_confidence(self, segment: SourceSegment) -> float:
        """
        Compute classifier confidence score (0-1).

        Confidence is based on:
        - Presence of strong signals (definition + numeric + specific metric keywords)
        - Length of text (longer text generally more reliable)
        - Number of candidate metrics (too many suggests generic text)
        - CMASB priority boost (Core > Extended > Other)
        - NEW: Multi-metric density, cohort patterns, temporal trends
        """
        confidence = 0.0

        # Base confidence from flags
        if segment.contains_numeric_disclosure_flag:
            confidence += 0.3

        if segment.contains_definition_flag:
            confidence += 0.2

        if segment.contains_methodology_flag:
            confidence += 0.2

        # Boost for specific metric identification
        num_candidates = len(segment.candidate_metric_ids)
        if num_candidates == 1:
            confidence += 0.3  # Very specific
        elif num_candidates == 2:
            confidence += 0.2  # Moderately specific
        elif num_candidates >= 3:
            confidence += 0.1  # Less specific (generic discussion)

        # CMASB PRIORITY BOOST - Ensure priority metrics aren't filtered out
        has_core_metric = False
        has_extended_metric = False
        core_metric_ids = []
        extended_metric_ids = []

        for metric_id in segment.candidate_metric_ids:
            if metric_id in self.CMASB_CORE_METRICS:
                has_core_metric = True
                core_metric_ids.append(metric_id)
            elif metric_id in self.CMASB_EXTENDED_METRICS:
                has_extended_metric = True
                extended_metric_ids.append(metric_id)

        if has_core_metric:
            boost_amount = 0.2
            confidence += boost_amount
            logger.debug(
                f"CMASB boost: Core metrics {core_metric_ids} +{boost_amount} "
                f"(segment {segment.sequence_index})"
            )
        elif has_extended_metric:
            boost_amount = 0.1
            confidence += boost_amount
            logger.debug(
                f"CMASB boost: Extended metrics {extended_metric_ids} +{boost_amount} "
                f"(segment {segment.sequence_index})"
            )

        # === Goldmine indicator bonuses ===
        raw_text = segment.raw_text or ""

        # Multi-metric density bonus (3+ metrics indicates rich segment)
        if num_candidates >= 3:
            confidence += 0.15
            logger.debug(
                f"Multi-metric density bonus +0.15 ({num_candidates} metrics, "
                f"segment {segment.sequence_index})"
            )

        # Cohort analysis bonus
        if self._has_cohort_patterns(raw_text):
            confidence += 0.15
            logger.debug(
                f"Cohort pattern bonus +0.15 (segment {segment.sequence_index})"
            )

        # Temporal trend bonus
        if self._has_temporal_patterns(raw_text):
            confidence += 0.10
            logger.debug(
                f"Temporal trend bonus +0.10 (segment {segment.sequence_index})"
            )

        # Penalize very short segments
        if len(raw_text) < 100:
            confidence *= 0.7

        # Cap at 1.0
        return min(confidence, 1.0)


# Convenience function
def classify_segments(segments: list[SourceSegment]) -> list[SourceSegment]:
    """
    Convenience function to classify a list of segments.

    Args:
        segments: List of SourceSegments to classify

    Returns:
        List of classified SourceSegments
    """
    classifier = MetricClassifier()
    return classifier.classify_batch(segments)
