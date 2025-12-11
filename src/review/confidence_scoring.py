"""
Confidence scoring for review candidates.

This module provides multi-signal confidence scoring to distinguish
likely true positives from false positives in metric extraction candidates.

The ConfidenceScorer combines 8 different signals:
- Keyword distance (closer = better)
- Keyword position (before/after)
- Definition language ("we define X as...")
- Period mentions (time context)
- Number format matching (currency for revenue metrics, etc.)
- Keyword specificity (multi-word patterns)
- Risk factors penalty (high false positive section)
- Surrounding numbers penalty (ambiguous context)
- Table ambiguity penalty (tables without definitions)

Score interpretation:
- 0.0-0.3: Low confidence (probable false positive)
- 0.3-0.5: Moderate (needs careful review)
- 0.5-0.7: Good (probably correct)
- 0.7-1.0: High (very likely correct)
"""

import logging
import re
from typing import Dict, List

from src.review.keyword_matching import SPECIFIC_KEYWORD_PATTERNS
from src.review.models import CandidateFeatures

logger = logging.getLogger(__name__)


# =============================================================================
# Confidence Scoring Constants
# =============================================================================

# Expected number formats for each metric type
METRIC_EXPECTED_FORMATS: Dict[str, List[str]] = {
    # Customer counts - expect integers
    "cm_active_customers_total": ["integer", "currency"],  # "$X customers" appears
    "cm_active_customers_enterprise": ["integer"],
    "cm_active_customers_smb": ["integer"],
    "cm_total_users": ["integer"],
    "cm_dau": ["integer"],
    "cm_mau": ["integer"],
    # Revenue metrics - expect currency or percentages
    "cm_arr": ["currency"],
    "cm_mrr": ["currency"],
    "cm_revenue_per_customer": ["currency", "decimal"],
    "cm_aov": ["currency", "decimal"],
    "cm_cac": ["currency"],
    "cm_ltv": ["currency"],
    # Retention metrics - expect percentages or decimals
    "cm_nrr": ["percentage", "decimal"],
    "cm_grr": ["percentage", "decimal"],
    "cm_churn_rate": ["percentage", "decimal"],
    "cm_customer_churn_rate": ["percentage", "decimal"],
    "cm_logo_retention": ["percentage", "decimal"],
    # Growth metrics - expect percentages or integers
    "cm_new_customers": ["integer"],
    "cm_net_customer_additions": ["integer"],
    "cm_customer_growth_rate": ["percentage"],
}


# =============================================================================
# ConfidenceScorer Class
# =============================================================================


class ConfidenceScorer:
    """
    Computes suggestion confidence for review candidates.

    The confidence score ranges from 0.0 (likely false positive) to 1.0
    (high confidence). It combines multiple signals:

    - Keyword distance: Closer = higher confidence
    - Keyword position: 'before' pattern is slightly stronger
    - Definition language: "we define X as..." is very strong signal
    - Period mention: Time context suggests real metric
    - Risk factors penalty: High false positive section
    - Format match: Number format matches metric type expectation
    - Keyword specificity: Multi-word keywords are more specific
    - Surrounding numbers penalty: Many numbers = ambiguous context

    Score interpretation:
    - 0.0-0.3: Low confidence (probable false positive)
    - 0.3-0.5: Moderate (needs careful review)
    - 0.5-0.7: Good (probably correct)
    - 0.7-1.0: High (very likely correct)
    """

    # Scoring weights
    BASE_SCORE = 0.30  # Starting score for any candidate
    DISTANCE_MAX_WEIGHT = 0.25  # Max bonus for close distance
    POSITION_BEFORE_BONUS = 0.05  # Bonus if keyword is before number
    DEFINITION_BONUS = 0.20  # Bonus for definition language
    PERIOD_BONUS = 0.05  # Bonus for period mention
    FORMAT_MATCH_BONUS = 0.10  # Bonus if format matches metric type
    SPECIFIC_KEYWORD_BONUS = 0.10  # Bonus for multi-word specific keyword
    RISK_FACTORS_PENALTY = 0.25  # Penalty for risk factors section
    SURROUNDING_NUMBERS_PENALTY_MAX = 0.15  # Max penalty for many numbers
    TABLE_AMBIGUITY_PENALTY = 0.05  # Penalty for table without definition

    def __init__(self, max_keyword_distance: int = 100):
        """
        Initialize the confidence scorer.

        Args:
            max_keyword_distance: Maximum distance for keyword matching
                                 (used to scale distance score)
        """
        self.max_keyword_distance = max_keyword_distance
        # Compile specific keyword patterns
        self._specific_patterns = [
            re.compile(p, re.IGNORECASE) for p in SPECIFIC_KEYWORD_PATTERNS
        ]

    def compute_confidence(
        self,
        keyword_distance: int,
        keyword_position: str,
        keyword: str,
        metric_id: str,
        features: CandidateFeatures,
    ) -> float:
        """
        Compute confidence score for a candidate.

        Args:
            keyword_distance: Character distance from number to keyword
            keyword_position: 'before' or 'after'
            keyword: The triggering keyword text
            metric_id: The suggested metric ID
            features: CandidateFeatures for this candidate

        Returns:
            Confidence score between 0.0 and 1.0
        """
        score = self.BASE_SCORE

        # Distance score: linear decay from max bonus at 0 to 0 at max_distance
        distance_ratio = 1.0 - min(
            keyword_distance / self.max_keyword_distance, 1.0
        )
        score += self.DISTANCE_MAX_WEIGHT * distance_ratio

        # Position bonus: keyword before number is slightly more reliable
        if keyword_position == "before":
            score += self.POSITION_BEFORE_BONUS

        # Definition language bonus: strong signal
        if features.contains_definition_language:
            score += self.DEFINITION_BONUS

        # Period mention bonus: suggests time-specific metric
        if features.has_period_mention:
            score += self.PERIOD_BONUS

        # Format match bonus: number format matches expected for metric
        expected_formats = METRIC_EXPECTED_FORMATS.get(metric_id, [])
        if features.number_format in expected_formats:
            score += self.FORMAT_MATCH_BONUS

        # Specific keyword bonus: multi-word keywords are more reliable
        if self._is_specific_keyword(keyword):
            score += self.SPECIFIC_KEYWORD_BONUS

        # Risk factors penalty: high false positive section
        if features.is_in_risk_factors:
            score -= self.RISK_FACTORS_PENALTY

        # Surrounding numbers penalty: many numbers suggests ambiguous context
        # Scale penalty: 0 at 0-2 numbers, max at 10+ numbers
        if features.surrounding_numbers_count > 2:
            ratio = min((features.surrounding_numbers_count - 2) / 8.0, 1.0)
            score -= self.SURROUNDING_NUMBERS_PENALTY_MAX * ratio

        # Table context: ambiguous if no definition language
        if features.is_in_table and not features.contains_definition_language:
            score -= self.TABLE_AMBIGUITY_PENALTY

        # Clamp to valid range
        return max(0.0, min(1.0, score))

    def _is_specific_keyword(self, keyword: str) -> bool:
        """
        Check if keyword is a specific multi-word pattern.

        Args:
            keyword: The keyword text

        Returns:
            True if keyword matches a specific pattern
        """
        keyword_lower = keyword.lower()
        for pattern in self._specific_patterns:
            if pattern.search(keyword_lower):
                return True
        return False
