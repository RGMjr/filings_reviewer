"""
Metric Classifier - Classify segments for metric content.

This module scans source segments to identify:
- Numeric disclosures of metrics
- Metric definitions
- Calculation methodologies
- Which specific metrics are present
"""

import logging
import re
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from .models import SourceSegment
from .validators import ClassificationValidator
from .exceptions import ValidationError

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
    metric_id_counts: Dict[str, int] = field(default_factory=dict)
    classification_time_seconds: float = 0.0

    def avg_confidence(self) -> float:
        """Calculate average confidence score."""
        if self.total_segments == 0:
            return 0.0
        return self.total_confidence / self.total_segments

    def top_metrics(self, n: int = 5) -> List[tuple]:
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
    DEFINITION_PATTERNS = [
        r"\bwe\s+define\b",
        r"\bdefined\s+as\b",
        r"\bdefinition\s+of\b",
        r"\brefers\s+to\b",
        r"\bmeans\b",
        r"\bmeaning\b",
        r"\bmetric\s+definitions?\b",
        r"\bis\s+defined\b",
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

    # Metric-specific keyword patterns
    # Format: metric_id -> list of keyword patterns
    METRIC_KEYWORDS = {
        # Core Metrics
        "cm_new_customers_acquired": [
            r"\bnew\s+customers?\b",
            r"\bcustomers?\s+acquired\b",
            r"\bcustomer\s+acquisition[s]?\b",
            r"\bacquired\s+customers?\b",
            r"\bnewly\s+acquired\b",
            r"\bnew\s+customer\s+additions?\b",
            r"\bnet\s+new\s+customers?\b",
            r"\bcustomers?\s+added\b",
            r"\bcustomer\s+growth\b",
            r"\bacquisition\s+of\s+customers?\b",
            r"\bnew\s+users?\s+acquired\b",
            r"\bacquired\s+users?\b",
        ],
        "cm_customers_period_end_by_tenure": [
            r"\bcustomers?\s+by\s+tenure\b",
            r"\btenure\s+cohort\b",
            r"\bcustomers?\s+at\s+period\s+end\b",
            r"\bby\s+age\b",
            r"\btime\s+since\b",
        ],
        "cm_revenue_by_cohort": [
            r"\brevenue\s+by\s+cohort\b",
            r"\bcohort\s+revenue\b",
            r"\brevenue[^.;]{0,100}\bcohort\b",  # Fixed: limit to same sentence
            r"\bcohort[^.;]{0,100}\brevenue\b",  # Fixed: limit to same sentence
        ],
        "cm_transactions_by_cohort": [
            r"\btransactions?\s+by\s+cohort\b",
            r"\bcohort\s+transactions?\b",
            r"\bpurchase\s+transactions?\b",
            r"\btransactions?[^.;]{0,100}\bcohort\b",  # Fixed: limit to same sentence
        ],
        # Extended Metrics
        "cm_active_customers_total": [
            r"\bactive\s+customers?\b",
            r"\btotal\s+customers?\b",
            r"\bcustomer\s+base\b",
        ],
        "cm_revenue_per_customer": [
            r"\barpu\b",
            r"\baverage\s+revenue\s+per\s+user\b",
            r"\brevenue\s+per\s+customer\b",
            r"\brevenue\s+per\s+user\b",
            r"\bper\s+customer\s+revenue\b",
        ],
        "cm_customer_acquisition_cost": [
            r"\bcac\b",
            r"\bcustomer\s+acquisition\s+cost\b",
            r"\bacquisition\s+cost\b",
            r"\bcost\s+to\s+acquire\b",
        ],
        "cm_cac_payback_period": [
            r"\bcac\s+payback\b",
            r"\bpayback\s+period\b",
            r"\btime\s+to\s+recover\b",
        ],
        "cm_customer_retention_rate": [
            r"\bretention\s+rate\b",
            r"\bcustomer\s+retention\b",
            r"\bretained\s+customers?\b",
        ],
        "cm_customer_churn_rate": [
            r"\bchurn\s+rate\b",
            r"\bcustomer\s+churn\b",
            r"\battrition\s+rate\b",
        ],
        "cm_net_revenue_retention": [
            r"\bnrr\b",
            r"\bnet\s+revenue\s+retention\b",
            r"\bnet\s+retention\b",
            r"\bnet\s+dollar\s+retention\b",
            r"\bndr\b",
            r"\bretention\s+rate[^.;]{0,50}\d+%",  # Fixed: limit to same sentence
            r"\bnet\s+retention\s+rate\b",
        ],
        "cm_gross_revenue_retention": [
            r"\bgrr\b",
            r"\bgross\s+revenue\s+retention\b",
            r"\bgross\s+retention\b",
        ],
        "cm_monthly_active_users": [
            r"\bmau\b",
            r"\bmonthly\s+active\s+users?\b",
        ],
        "cm_daily_active_users": [
            r"\bdau\b",
            r"\bdaily\s+active\s+users?\b",
        ],
        "cm_gross_margin_overall": [
            r"\bgross\s+margin(?:\s+(?:was|of|is|at))?\s+\d",
            r"\boverall\s+gross\s+margin\b",
            r"\btotal\s+gross\s+margin\b",
            r"\bgross\s+profit\s+margin\b",
            r"\bgross\s+margin\s+(?:percentage|rate)\b",
            r"\b(?<!cohort\s)(?<!by\s)gross\s+margin\b",
        ],
        "cm_gross_margin_by_cohort": [
            r"\bgross\s+margin\s+by\s+cohort\b",
            r"\bcohort\s+(?:gross\s+)?margin\b",
            r"\bmargin\s+by\s+(?:acquisition\s+)?(?:vintage|cohort)\b",
        ],
        "cm_arr": [
            r"\barr\b",
            r"\bannual\s+recurring\s+revenue\b",
            r"\bannualized\s+recurring\s+revenue\b",
            r"\bannual\s+run[- ]?rate\b",
        ],
        "cm_mrr": [
            r"\bmrr\b",
            r"\bmonthly\s+recurring\s+revenue\b",
        ],
        "cm_expansion_revenue": [
            r"\bexpansion\s+revenue\b",
            r"\bcross[- ]sell\b",
            r"\bupsell\b",
            r"\bproducts?\s+per\s+customer\b",
            r"\baverage\s+products?\s+owned\b",
            r"\bexpand\b[^.;]{0,100}\brevenue\b",  # Fixed: limit to same sentence, max 100 chars
            r"\badditional\s+products?\b",
            r"\bmulti[- ]product\b",
        ],
        "cm_revenue_concentration": [
            r"\brevenue\s+concentration\b",
            r"\bcustomer\s+concentration\b",
            r"\btop\s+\d+\s+customers?\b",
            r"\blargest\s+customers?\b",
            r"\b\d+%\s+of\s+revenue\b",
            r"\bconcentration\s+risk\b",
            r"\bconcentration\s+of\s+revenue\b",
            r"\bmajor\s+customers?\b",
        ],
        # -----------------------------------------------------------------
        # Revenue Predictability Metrics (T5: cm_bookings group)
        # -----------------------------------------------------------------
        "cm_bookings": [
            r"\bbookings\b",                    # "bookings" standalone
            r"\btotal\s+bookings\b",            # "total bookings"
            r"\bnew\s+bookings\b",              # "new bookings"
            r"\bcontract\s+bookings\b",         # "contract bookings"
            r"\bnet\s+new\s+bookings\b",        # "net new bookings"
            r"\bquarterly\s+bookings\b",        # "quarterly bookings"
            r"\bannual\s+bookings\b",           # "annual bookings"
        ],
        "cm_billings": [
            r"\bbillings\b",                    # "billings" standalone
            r"\btotal\s+billings\b",            # "total billings"
            r"\bcalculated\s+billings\b",       # "calculated billings"
            r"\badjusted\s+billings\b",         # "adjusted billings"
        ],
        "cm_deferred_revenue": [
            r"\bdeferred\s+revenue\b",          # "deferred revenue"
            r"\bunearned\s+revenue\b",          # "unearned revenue"
            r"\bremaining\s+performance\s+obligation[s]?\b",  # RPO
            r"\brpo\b",                         # "RPO" acronym
            r"\bcontract\s+liabilit(?:y|ies)\b",  # "contract liability/liabilities"
            r"\bbacklog\b",                     # "backlog" (sometimes used synonymously)
        ],
        # -----------------------------------------------------------------
        # E-Commerce / Consumer Metrics (T6: AOV + Repeat Purchase group)
        # -----------------------------------------------------------------
        "cm_average_order_value": [
            r"\baov\b",                          # "AOV" acronym
            r"\baverage\s+order\s+value\b",      # "average order value"
            r"\baverage\s+order\s+size\b",       # "average order size"
            r"\baverage\s+ticket\s+(?:size|value)?\b",  # "average ticket [size/value]"
            r"\baverage\s+basket\s+(?:size|value)?\b",  # "average basket [size/value]"
            r"\border\s+value\s+per\s+(?:customer|user|transaction)\b",  # "order value per customer"
            r"\baverage\s+transaction\s+value\b",  # "average transaction value"
        ],
        "cm_repeat_purchase_rate": [
            r"\brepeat\s+purchase\s+rate\b",     # "repeat purchase rate"
            r"\brepeat\s+purchase(?:s)?\b",      # "repeat purchase(s)"
            r"\bpurchase\s+frequency\b",         # "purchase frequency"
            r"\brepeat\s+customers?\b",          # "repeat customer(s)"
            r"\brepeat\s+buyers?\b",             # "repeat buyer(s)"
            r"\brepeat\s+order\s+rate\b",        # "repeat order rate"
            r"\breorder\s+rate\b",               # "reorder rate"
            r"\brepurchase\s+rate\b",            # "repurchase rate"
        ],
        # -----------------------------------------------------------------
        # Marketplace / Platform Metrics (T7: GMV + Take Rate group)
        # -----------------------------------------------------------------
        "cm_gmv": [
            r"\bgmv\b",                           # "GMV" acronym
            r"\bgross\s+merchandise\s+value\b",   # "gross merchandise value"
            r"\bgross\s+merchandise\s+volume\b",  # "gross merchandise volume" variant
            r"\bgross\s+booking\s+value\b",       # "gross booking value" (ride-sharing)
            r"\bgross\s+bookings\s+value\b",      # "gross bookings value" variant
            r"\bgross\s+transaction\s+value\b",   # "gross transaction value"
            r"\btotal\s+transaction\s+value\b",   # "total transaction value"
            r"\bgross\s+order\s+value\b",         # "gross order value" (e-commerce)
            r"\bplatform\s+(?:transaction\s+)?volume\b",  # "platform volume"
        ],
        "cm_take_rate": [
            r"\btake\s+rate\b",                   # "take rate"
            r"\bplatform\s+take\s+rate\b",        # "platform take rate"
            r"\bcommission\s+rate\b",             # "commission rate" (marketplace)
            r"\bnet\s+take\s+rate\b",             # "net take rate"
            r"\bmonetization\s+rate\b",           # "monetization rate"
            r"\bservice\s+fee\s+rate\b",          # "service fee rate" (ride-sharing)
            r"\bplatform\s+fee\s+rate\b",         # "platform fee rate"
            r"\brevenue\s+as\s+a\s+percentage\s+of\s+gmv\b",  # explicit GMV relationship
        ],
        # Future Metrics
        "cm_lifetime_value_per_customer": [
            r"\bltv\b",
            r"\blifetime\s+value\b",
            r"\bcustomer\s+lifetime\s+value\b",
            r"\bclv\b",
        ],
        "cm_ltv_to_cac_ratio": [
            r"\bltv\s*[:/]\s*cac\b",
            r"\bltv\s+to\s+cac\b",
            r"\blifetime\s+value\s+to\s+acquisition\s+cost\b",
        ],
    }

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
        'cm_revenue_per_customer',
        'cm_gross_margin_overall',
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
        'cm_deferred_revenue',
        # T6: E-commerce metrics
        'cm_average_order_value',
        'cm_repeat_purchase_rate',
        # T7: Marketplace metrics
        'cm_gmv',
        'cm_take_rate',
    }

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

    def __init__(self):
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

        # Compile metric-specific patterns
        self._metric_patterns = {}
        for metric_id, patterns in self.METRIC_KEYWORDS.items():
            self._metric_patterns[metric_id] = [
                re.compile(p, re.IGNORECASE) for p in patterns
            ]

        # Metrics tracking
        self._metrics: Optional[ClassificationMetrics] = None

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

    def classify_batch(self, segments: List[SourceSegment], validate: bool = True) -> List[SourceSegment]:
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

    def get_metrics(self) -> Optional[ClassificationMetrics]:
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

    def _identify_candidate_metrics(self, text: str) -> List[str]:
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

    def _compute_confidence(self, segment: SourceSegment) -> float:
        """
        Compute classifier confidence score (0-1).

        Confidence is based on:
        - Presence of strong signals (definition + numeric + specific metric keywords)
        - Length of text (longer text generally more reliable)
        - Number of candidate metrics (too many suggests generic text)
        - CMASB priority boost (Core > Extended > Other)
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

        # Penalize very short segments
        if len(segment.raw_text) < 100:
            confidence *= 0.7

        # Cap at 1.0
        return min(confidence, 1.0)


# Convenience function
def classify_segments(segments: List[SourceSegment]) -> List[SourceSegment]:
    """
    Convenience function to classify a list of segments.

    Args:
        segments: List of SourceSegments to classify

    Returns:
        List of classified SourceSegments
    """
    classifier = MetricClassifier()
    return classifier.classify_batch(segments)
