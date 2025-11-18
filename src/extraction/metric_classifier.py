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
from typing import List, Set, Tuple

from .models import SourceSegment

logger = logging.getLogger(__name__)


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
        r'\bwe\s+define\b',
        r'\bdefined\s+as\b',
        r'\bdefinition\s+of\b',
        r'\brefers\s+to\b',
        r'\bmeans\b',
        r'\bmeaning\b',
        r'\bmetric\s+definitions?\b',
        r'\bis\s+defined\b',
    ]

    # Methodology/calculation indicators
    METHODOLOGY_PATTERNS = [
        r'\bcalculated\s+as\b',
        r'\bcalculated\s+by\b',
        r'\bcalculation\b',
        r'\bcomputed\s+as\b',
        r'\bdetermined\s+by\b',
        r'\bformula\b',
        r'\bmethodology\b',
        r'\bcompute[ds]?\b',
    ]

    # Metric-specific keyword patterns
    # Format: metric_id -> list of keyword patterns
    METRIC_KEYWORDS = {
        # Core Metrics
        'cm_new_customers_acquired': [
            r'\bnew\s+customers?\b',
            r'\bcustomers?\s+acquired\b',
            r'\bcustomer\s+acquisition[s]?\b',
            r'\bacquired\s+customers?\b',
            r'\bnewly\s+acquired\b',
        ],
        'cm_customers_period_end_by_tenure': [
            r'\bcustomers?\s+by\s+tenure\b',
            r'\btenure\s+cohort\b',
            r'\bcustomers?\s+at\s+period\s+end\b',
            r'\bby\s+age\b',
            r'\btime\s+since\b',
        ],
        'cm_revenue_by_cohort': [
            r'\brevenue\s+by\s+cohort\b',
            r'\bcohort\s+revenue\b',
            r'\brevenue.*cohort\b',
            r'\bcohort.*revenue\b',
        ],
        'cm_transactions_by_cohort': [
            r'\btransactions?\s+by\s+cohort\b',
            r'\bcohort\s+transactions?\b',
            r'\bpurchase\s+transactions?\b',
            r'\btransactions?.*cohort\b',
        ],

        # Extended Metrics
        'cm_active_customers_total': [
            r'\bactive\s+customers?\b',
            r'\btotal\s+customers?\b',
            r'\bcustomer\s+base\b',
        ],
        'cm_revenue_per_customer': [
            r'\barpu\b',
            r'\baverage\s+revenue\s+per\s+user\b',
            r'\brevenue\s+per\s+customer\b',
            r'\brevenue\s+per\s+user\b',
            r'\bper\s+customer\s+revenue\b',
        ],
        'cm_customer_acquisition_cost': [
            r'\bcac\b',
            r'\bcustomer\s+acquisition\s+cost\b',
            r'\bacquisition\s+cost\b',
            r'\bcost\s+to\s+acquire\b',
        ],
        'cm_cac_payback_period': [
            r'\bcac\s+payback\b',
            r'\bpayback\s+period\b',
            r'\btime\s+to\s+recover\b',
        ],
        'cm_customer_retention_rate': [
            r'\bretention\s+rate\b',
            r'\bcustomer\s+retention\b',
            r'\bretained\s+customers?\b',
        ],
        'cm_customer_churn_rate': [
            r'\bchurn\s+rate\b',
            r'\bcustomer\s+churn\b',
            r'\battrition\s+rate\b',
        ],
        'cm_net_revenue_retention': [
            r'\bnrr\b',
            r'\bnet\s+revenue\s+retention\b',
            r'\bnet\s+retention\b',
        ],
        'cm_gross_revenue_retention': [
            r'\bgrr\b',
            r'\bgross\s+revenue\s+retention\b',
            r'\bgross\s+retention\b',
        ],
        'cm_monthly_active_users': [
            r'\bmau\b',
            r'\bmonthly\s+active\s+users?\b',
        ],
        'cm_daily_active_users': [
            r'\bdau\b',
            r'\bdaily\s+active\s+users?\b',
        ],

        # Future Metrics
        'cm_lifetime_value_per_customer': [
            r'\bltv\b',
            r'\blifetime\s+value\b',
            r'\bcustomer\s+lifetime\s+value\b',
            r'\bclv\b',
        ],
        'cm_ltv_to_cac_ratio': [
            r'\bltv\s*[:/]\s*cac\b',
            r'\bltv\s+to\s+cac\b',
            r'\blifetime\s+value\s+to\s+acquisition\s+cost\b',
        ],
    }

    # General customer/metric keywords (for numeric disclosure detection)
    GENERAL_METRIC_KEYWORDS = [
        r'\bcustomers?\b',
        r'\busers?\b',
        r'\bsubscribers?\b',
        r'\bcohort[s]?\b',
        r'\brevenue\b',
        r'\btransactions?\b',
        r'\bmetrics?\b',
    ]

    # Number patterns
    NUMBER_PATTERN = r'\b\d{1,3}(?:,\d{3})*(?:\.\d+)?(?:\s*(?:million|billion|thousand|%|percent))?\b'

    def __init__(self):
        """Initialize the metric classifier."""
        # Compile all patterns for performance
        self._definition_regex = [re.compile(p, re.IGNORECASE) for p in self.DEFINITION_PATTERNS]
        self._methodology_regex = [re.compile(p, re.IGNORECASE) for p in self.METHODOLOGY_PATTERNS]
        self._general_metric_regex = [re.compile(p, re.IGNORECASE) for p in self.GENERAL_METRIC_KEYWORDS]
        self._number_regex = re.compile(self.NUMBER_PATTERN, re.IGNORECASE)

        # Compile metric-specific patterns
        self._metric_patterns = {}
        for metric_id, patterns in self.METRIC_KEYWORDS.items():
            self._metric_patterns[metric_id] = [re.compile(p, re.IGNORECASE) for p in patterns]

    def classify_segment(self, segment: SourceSegment) -> SourceSegment:
        """
        Classify a single segment.

        Updates the segment's classification flags and candidate_metric_ids.

        Args:
            segment: SourceSegment to classify

        Returns:
            Updated SourceSegment
        """
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

    def classify_batch(self, segments: List[SourceSegment]) -> List[SourceSegment]:
        """
        Classify multiple segments efficiently.

        Args:
            segments: List of SourceSegments to classify

        Returns:
            List of updated SourceSegments
        """
        classified = []
        for segment in segments:
            classified.append(self.classify_segment(segment))

        logger.info(f"Classified {len(classified)} segments")
        return classified

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
