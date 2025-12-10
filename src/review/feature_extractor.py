"""
Feature Extractor - Compute ML features for review candidates.

This module extracts contextual features from candidate metrics
for use in confidence scoring and pattern analysis.

Features computed:
- Keyword proximity features (distance, position)
- Context features (definition language, period mentions, risk factors)
- Number format features (integer, decimal, percentage, currency)
- Section features (table vs paragraph, section name)
- Magnitude features (log10 of value)
"""

import logging
import math
import re
from decimal import Decimal
from typing import List, Optional, Pattern

from src.review.models import CandidateFeatures

logger = logging.getLogger(__name__)


# =============================================================================
# Feature Detection Patterns
# =============================================================================

# Patterns for definition language (suggests metric is being defined)
DEFINITION_PATTERNS: List[Pattern[str]] = [
    re.compile(r"\bwe\s+define\b", re.IGNORECASE),
    re.compile(r"\bdefined\s+as\b", re.IGNORECASE),
    re.compile(r"\bwe\s+calculate\b", re.IGNORECASE),
    re.compile(r"\bcalculated\s+as\b", re.IGNORECASE),
    re.compile(r"\bwe\s+measure\b", re.IGNORECASE),
    re.compile(r"\bmeasured\s+by\b", re.IGNORECASE),
    re.compile(r"\brefers\s+to\b", re.IGNORECASE),
    re.compile(r"\brepresents\b", re.IGNORECASE),
    re.compile(r"\bconsists\s+of\b", re.IGNORECASE),
]

# Patterns for period/date mentions (suggests time-specific metric)
PERIOD_PATTERNS: List[Pattern[str]] = [
    re.compile(r"\b(?:Q[1-4]|first|second|third|fourth)\s+quarter\b", re.IGNORECASE),
    re.compile(r"\b(?:fiscal|calendar)\s+year\b", re.IGNORECASE),
    re.compile(r"\byear(?:s)?\s+ended\b", re.IGNORECASE),
    re.compile(r"\b(?:three|six|nine|twelve)\s+months?\b", re.IGNORECASE),
    re.compile(r"\bas\s+of\s+(?:December|June|March|September)\b", re.IGNORECASE),
    re.compile(r"\b20[12]\d\b"),  # Years 2010-2029
    re.compile(r"\bperiod\s+end(?:ed|ing)?\b", re.IGNORECASE),
    re.compile(r"\bmonth(?:ly|s)?\b", re.IGNORECASE),
    re.compile(r"\bannual(?:ly|ized)?\b", re.IGNORECASE),
]

# Risk factors section indicators (high false positive rate)
RISK_FACTORS_PATTERNS: List[Pattern[str]] = [
    re.compile(r"\brisk\s+factors?\b", re.IGNORECASE),
    re.compile(r"\brisks?\s+related\b", re.IGNORECASE),
    re.compile(r"\bmay\s+(?:not|never|fail)\b", re.IGNORECASE),
    re.compile(r"\bcould\s+(?:adversely|negatively)\b", re.IGNORECASE),
    re.compile(r"\bno\s+assurance\b", re.IGNORECASE),
    re.compile(r"\bcannot\s+guarantee\b", re.IGNORECASE),
]


# =============================================================================
# FeatureExtractor Class
# =============================================================================


class FeatureExtractor:
    """
    Computes ML features for review candidates.

    Features are used for:
    - Confidence scoring in candidate generation
    - Pattern analysis to improve extraction rules
    - Training ML models for auto-classification
    """

    def __init__(self) -> None:
        """Initialize the feature extractor."""
        # Patterns are pre-compiled at module level for efficiency
        pass

    def compute_features(
        self,
        number_value: Optional[Decimal],
        number_unit: Optional[str],
        number_raw_text: str,
        keyword_distance: int,
        keyword_position: str,
        context_text: str,
        segment_type: Optional[str] = None,
        section_heading: Optional[str] = None,
        section_path: Optional[str] = None,
        surrounding_numbers_count: int = 0,
    ) -> CandidateFeatures:
        """
        Compute all ML features for a candidate.

        Args:
            number_value: Parsed numeric value (may be None)
            number_unit: Detected unit ('count', '%', 'usd', etc.)
            number_raw_text: Original text of the number
            keyword_distance: Distance to triggering keyword
            keyword_position: 'before' or 'after'
            context_text: Surrounding text context
            segment_type: Type of segment ('table', 'paragraph', etc.)
            section_heading: Section heading if available
            section_path: Full section path if available
            surrounding_numbers_count: Other numbers in segment

        Returns:
            CandidateFeatures instance with all computed features

        Note:
            This method uses defensive defaults for missing/invalid values
            to ensure graceful degradation rather than failures.
        """
        # Defensive: ensure context_text is a string
        if not isinstance(context_text, str):
            context_text = str(context_text) if context_text is not None else ""

        # Determine number format from unit and raw text
        number_format = self.determine_number_format(number_unit, number_raw_text)

        # Compute value magnitude (log10 of absolute value)
        value_magnitude = self._compute_value_magnitude(number_value)

        # Check for definition language in context
        contains_definition = self._check_definition_language(context_text)

        # Check for period/date mentions in context
        has_period = self._check_period_mention(context_text)

        # Check segment type for table
        is_in_table = (segment_type == "table") if segment_type else False

        # Check for risk factors section
        is_in_risk_factors = self._check_risk_factors(
            context_text, section_heading, section_path
        )

        # Get section name
        section_name = section_heading if section_heading else None

        # Count words in context
        # NOTE: Defensive exception handler - line 124 ensures context_text is str,
        # so split() should always exist. This catches future code modifications.
        try:
            context_word_count = len(context_text.split())
        except AttributeError:  # pragma: no cover - defensive, unreachable
            context_word_count = 0

        return CandidateFeatures(
            keyword_distance=keyword_distance,
            keyword_position=keyword_position,
            is_in_table=is_in_table,
            is_in_risk_factors=is_in_risk_factors,
            contains_definition_language=contains_definition,
            has_period_mention=has_period,
            number_format=number_format,
            value_magnitude=value_magnitude,
            surrounding_numbers_count=surrounding_numbers_count,
            section_name=section_name,
            context_word_count=context_word_count,
        )

    def _normalize_unit(self, number_unit: Optional[str]) -> Optional[str]:
        """
        Normalize unit variations to canonical format.

        Handles variations from different sources:
        - NumberParser: "%", "usd", "count"
        - ValueExtractor: "percent", "usd", "count"
        - LLM: "percent", "dollars", "currency", "thousands", "millions", etc.

        Args:
            number_unit: Unit string from any source

        Returns:
            Normalized unit: "%", "usd", "count", or None
        """
        if not number_unit:
            return None

        unit_lower = number_unit.lower().strip()

        # Percentage variations
        if unit_lower in ("percent", "percentage", "pct", "%"):
            return "%"

        # Currency variations
        if unit_lower in ("dollars", "currency", "dollar", "$", "usd"):
            return "usd"

        # Count variations (normalize magnitude indicators to "count")
        if unit_lower in ("thousands", "millions", "billions", "k", "m", "b", "count"):
            return "count"

        # Unknown unit - return lowercased for consistency
        return unit_lower

    def determine_number_format(
        self,
        number_unit: Optional[str],
        number_raw_text: str,
    ) -> str:
        """
        Determine the number format from unit and raw text.

        Normalizes unit variations before classification:
        - Accepts: "%", "percent", "percentage", "pct" → "percentage"
        - Accepts: "usd", "dollars", "currency", "$" → "currency"
        - Accepts: "count", "thousands", "millions" → "integer"/"decimal"

        Args:
            number_unit: Detected unit (accepts variations)
            number_raw_text: Original text of the number

        Returns:
            One of: 'integer', 'decimal', 'percentage', 'currency'
        """
        # Normalize unit variations
        normalized_unit = self._normalize_unit(number_unit)

        if normalized_unit == "%":
            return "percentage"
        if normalized_unit == "usd":
            return "currency"
        if "." in (number_raw_text or ""):
            return "decimal"
        return "integer"

    def _compute_value_magnitude(
        self, number_value: Optional[Decimal]
    ) -> Optional[float]:
        """
        Compute log10 of absolute value.

        Args:
            number_value: The numeric value (may be None or 0)

        Returns:
            Log10 of absolute value, or None if cannot compute
        """
        if number_value is None or number_value == 0:
            return None
        # NOTE: Defensive exception handler - Real Decimal objects convert to
        # inf/nan and never raise these exceptions. This protects against future
        # changes or unexpected input types.
        try:
            return math.log10(abs(float(number_value)))
        except (ValueError, OverflowError, TypeError):  # pragma: no cover - defensive
            return None

    def _check_definition_language(self, context_text: str) -> bool:
        """
        Check if context contains definition language.

        Args:
            context_text: The surrounding text context

        Returns:
            True if definition language patterns are found
        """
        if not context_text or not isinstance(context_text, str):
            return False
        # NOTE: Defensive exception handler - isinstance check ensures valid string,
        # and DEFINITION_PATTERNS are pre-compiled regexes. This protects against
        # runtime corruption of pattern list or future modifications.
        try:
            return any(p.search(context_text) for p in DEFINITION_PATTERNS)
        except (TypeError, AttributeError):  # pragma: no cover - defensive
            return False

    def _check_period_mention(self, context_text: str) -> bool:
        """
        Check if context contains period/date mentions.

        Args:
            context_text: The surrounding text context

        Returns:
            True if period/date patterns are found
        """
        if not context_text or not isinstance(context_text, str):
            return False
        # NOTE: Defensive exception handler - see _check_definition_language
        try:
            return any(p.search(context_text) for p in PERIOD_PATTERNS)
        except (TypeError, AttributeError):  # pragma: no cover - defensive
            return False

    def _check_risk_factors(
        self,
        context_text: str,
        section_heading: Optional[str],
        section_path: Optional[str],
    ) -> bool:
        """
        Check if candidate is in risk factors section.

        Args:
            context_text: The surrounding text context
            section_heading: Section heading if available
            section_path: Full section path if available

        Returns:
            True if risk factors indicators are found
        """
        # Check section heading/path
        heading = section_heading or ""
        path = section_path or ""
        combined_section = f"{heading} {path}".lower()

        if "risk factor" in combined_section:
            return True

        # Check context text patterns
        if not context_text or not isinstance(context_text, str):
            return False
        # NOTE: Defensive exception handler - see _check_definition_language
        try:
            return any(p.search(context_text) for p in RISK_FACTORS_PATTERNS)
        except (TypeError, AttributeError):  # pragma: no cover - defensive
            return False


# =============================================================================
# Module-Level Singleton Instance
# =============================================================================

# Singleton instance to avoid repeated instantiation.
# FeatureExtractor is stateless, so a single instance is sufficient.
_feature_extractor = FeatureExtractor()


# =============================================================================
# Module-Level Convenience Functions
# =============================================================================


def compute_features(
    number_value: Optional[Decimal],
    number_unit: Optional[str],
    number_raw_text: str,
    keyword_distance: int,
    keyword_position: str,
    context_text: str,
    segment_type: Optional[str] = None,
    section_heading: Optional[str] = None,
    section_path: Optional[str] = None,
    surrounding_numbers_count: int = 0,
) -> CandidateFeatures:
    """
    Convenience function to compute features.

    See FeatureExtractor.compute_features() for documentation.
    """
    return _feature_extractor.compute_features(
        number_value=number_value,
        number_unit=number_unit,
        number_raw_text=number_raw_text,
        keyword_distance=keyword_distance,
        keyword_position=keyword_position,
        context_text=context_text,
        segment_type=segment_type,
        section_heading=section_heading,
        section_path=section_path,
        surrounding_numbers_count=surrounding_numbers_count,
    )


def determine_number_format(
    number_unit: Optional[str],
    number_raw_text: str,
) -> str:
    """
    Convenience function to determine number format.

    See FeatureExtractor.determine_number_format() for documentation.
    """
    return _feature_extractor.determine_number_format(number_unit, number_raw_text)
