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

Automatic Usage (via CandidateGenerator):
    >>> from src.review import CandidateGenerator
    >>>
    >>> # Features extracted automatically for each candidate
    >>> generator = CandidateGenerator()
    >>> candidates = generator.generate_for_filing(
    ...     filing_id=123, company_id=456, segments=segments
    ... )
    >>> # Each candidate has features attribute
    >>> features = candidates[0].features
    >>> print(f"Keyword distance: {features.keyword_distance}")
    >>> print(f"Definition language: {features.contains_definition_language}")
    >>> print(f"Number format: {features.number_format}")

Direct Usage (advanced):
    >>> from src.review.feature_extractor import FeatureExtractor
    >>> from decimal import Decimal
    >>>
    >>> # Initialize extractor
    >>> extractor = FeatureExtractor()
    >>>
    >>> # Compute features for a candidate
    >>> features = extractor.compute_features(
    ...     number_value=Decimal("50000"),
    ...     number_unit="count",
    ...     number_raw_text="50,000",
    ...     keyword_distance=20,
    ...     keyword_position="before",
    ...     context_text="We define active customers as those who have...",
    ...     segment_type="paragraph",
    ...     section_heading="Business Overview",
    ... )
    >>> print(f"Features: {features}")

Feature Categories and Examples:
    >>> # Proximity features
    >>> features.keyword_distance  # Characters between number and keyword
    >>> features.keyword_position  # "before" or "after"
    >>>
    >>> # Context features (boolean flags)
    >>> features.contains_definition_language  # Has "we define", "calculated as"
    >>> features.has_period_mention  # Has "fiscal year", "as of December"
    >>> features.is_in_risk_factors  # In risk factors section
    >>>
    >>> # Number format features
    >>> features.number_format  # "integer", "decimal", "percentage", "currency"
    >>> features.value_magnitude  # log10(value) for large number handling
    >>>
    >>> # Section features
    >>> features.is_in_table  # Boolean: in table vs paragraph
    >>> features.section_name  # Section heading text
    >>>
    >>> # Derived features (P2.4)
    >>> features.surrounding_numbers_count  # Count of other numbers nearby
    >>> features.context_word_count  # Total words in context

Computing Derived Features (P2.4):
    >>> from src.review.feature_extractor import (
    ...     bin_keyword_distance,
    ...     bin_value_magnitude,
    ...     compute_distance_magnitude_interaction,
    ...     compute_strong_signal,
    ...     compute_weak_signal,
    ...     compute_very_weak_signal,
    ... )
    >>>
    >>> # Bin continuous features for interpretability
    >>> distance_bin = bin_keyword_distance(features.keyword_distance)
    >>> # Returns: "very_close" | "close" | "moderate" | "far" | "very_far"
    >>>
    >>> magnitude_bin = bin_value_magnitude(features.value_magnitude)
    >>> # Returns: "tiny" | "small" | "medium" | "large" | "huge"
    >>>
    >>> # Compute interaction features
    >>> interaction = compute_distance_magnitude_interaction(
    ...     keyword_distance=20,
    ...     value_magnitude=4.0,
    ... )
    >>>
    >>> # Compute composite signals
    >>> strong_signal = compute_strong_signal(features)  # High-confidence indicators
    >>> weak_signal = compute_weak_signal(features)      # Low-confidence indicators
    >>> very_weak_signal = compute_very_weak_signal(features)  # Very low confidence

Using Features for Pattern Analysis (E1):
    >>> from src.review.pattern_analyzer import PatternAnalyzer
    >>> from src.infra.db import DatabaseAdapter
    >>>
    >>> # Analyze which features predict true vs false metrics
    >>> db = DatabaseAdapter("postgresql://...")
    >>> analyzer = PatternAnalyzer(db)
    >>> patterns = analyzer.discover_patterns(pattern_type="reject_rule")
    >>> # Patterns identify which feature combinations indicate false positives

See Also:
    - candidate_generator.py: Uses FeatureExtractor internally
    - confidence_scoring.py: Uses features for confidence scoring
    - pattern_analyzer.py: Learns patterns from features (E1)
    - models.py: CandidateFeatures data structure
"""

import logging
import math
import re
from decimal import Decimal
from typing import Any
from re import Pattern

from src.review.models import CandidateFeatures

logger = logging.getLogger(__name__)


# =============================================================================
# Feature Detection Patterns
# =============================================================================

# Patterns for definition language (suggests metric is being defined)
DEFINITION_PATTERNS: list[Pattern[str]] = [
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
PERIOD_PATTERNS: list[Pattern[str]] = [
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
RISK_FACTORS_PATTERNS: list[Pattern[str]] = [
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
        number_value: Decimal | None,
        number_unit: str | None,
        number_raw_text: str,
        keyword_distance: int,
        keyword_position: str,
        context_text: str | None,
        segment_type: str | None = None,
        section_heading: str | None = None,
        section_path: str | None = None,
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

            Word counting uses Python's str.split() which has limitations:
            - Splits on ASCII whitespace only (space, tab, newline, etc.)
            - Does not handle languages without spaces (Chinese, Japanese, Thai, etc.)
            - Does not recognize Unicode whitespace beyond ASCII
            - Counts hyphenated terms as single words

            This is acceptable for SEC filings (English text), but may
            undercount in mixed-language contexts or future internationalization.
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
        # Line 131-133 ensures context_text is always a string, so split() is safe
        context_word_count = len(context_text.split())

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

    def _normalize_unit(self, number_unit: str | None) -> str | None:
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
        number_unit: str | None,
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
        self, number_value: Decimal | None
    ) -> float | None:
        """
        Compute log10 of absolute value.

        Args:
            number_value: The numeric value (may be None or 0)

        Returns:
            Log10 of absolute value, or None if cannot compute
        """
        if number_value is None or number_value == 0:
            return None
        # Decimal objects convert to inf/nan for extreme values, never raise
        return math.log10(abs(float(number_value)))

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
        # isinstance check ensures valid string; DEFINITION_PATTERNS are pre-compiled
        return any(p.search(context_text) for p in DEFINITION_PATTERNS)

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
        # isinstance check ensures valid string; PERIOD_PATTERNS are pre-compiled
        return any(p.search(context_text) for p in PERIOD_PATTERNS)

    def _check_risk_factors(
        self,
        context_text: str,
        section_heading: str | None,
        section_path: str | None,
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
        # isinstance check ensures valid string; RISK_FACTORS_PATTERNS are pre-compiled
        return any(p.search(context_text) for p in RISK_FACTORS_PATTERNS)


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
    number_value: Decimal | None,
    number_unit: str | None,
    number_raw_text: str,
    keyword_distance: int,
    keyword_position: str,
    context_text: str,
    segment_type: str | None = None,
    section_heading: str | None = None,
    section_path: str | None = None,
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
    number_unit: str | None,
    number_raw_text: str,
) -> str:
    """
    Convenience function to determine number format.

    See FeatureExtractor.determine_number_format() for documentation.
    """
    return _feature_extractor.determine_number_format(number_unit, number_raw_text)


# =============================================================================
# Feature Engineering Helpers (P2.4)
# =============================================================================


def bin_keyword_distance(keyword_distance: int) -> str:
    """
    Bin keyword distance into interpretable categories (P2.4).

    Args:
        keyword_distance: Distance in characters from number to keyword

    Returns:
        One of: 'very_close' (0-20), 'close' (20-50), 'far' (50-100), 'very_far' (100+)

    Example:
        >>> bin_keyword_distance(15)
        'very_close'
        >>> bin_keyword_distance(75)
        'far'
    """
    if keyword_distance < 20:
        return "very_close"
    elif keyword_distance < 50:
        return "close"
    elif keyword_distance < 100:
        return "far"
    else:
        return "very_far"


def bin_value_magnitude(value_magnitude: float | None) -> str:
    """
    Bin value magnitude (log10) into interpretable size categories (P2.4).

    Args:
        value_magnitude: Log10 of absolute value (None if value is 0 or None)

    Returns:
        One of: 'unknown' (None), 'small' (<3), 'medium' (3-5), 'large' (5-6), 'very_large' (6+)

    Example:
        >>> bin_value_magnitude(None)
        'unknown'
        >>> bin_value_magnitude(2.5)  # ~300
        'small'
        >>> bin_value_magnitude(4.0)  # 10,000
        'medium'
        >>> bin_value_magnitude(6.5)  # 3,000,000
        'very_large'

    Note:
        Value ranges (approximate):
        - small: < 1,000 (log10 < 3)
        - medium: 1,000 - 100,000 (log10: 3-5)
        - large: 100,000 - 1,000,000 (log10: 5-6)
        - very_large: > 1,000,000 (log10 >= 6)
    """
    if value_magnitude is None:
        return "unknown"
    elif value_magnitude < 3:
        return "small"
    elif value_magnitude < 5:
        return "medium"
    elif value_magnitude < 6:
        return "large"
    else:
        return "very_large"


def compute_distance_magnitude_interaction(
    keyword_distance: int,
    value_magnitude: float | None,
) -> float | None:
    """
    Compute interaction feature between distance and magnitude (P2.4).

    This captures non-linear relationships where very large numbers
    far from keywords are suspicious, but small numbers nearby are okay.

    Args:
        keyword_distance: Distance in characters
        value_magnitude: Log10 of absolute value

    Returns:
        Product of distance and magnitude, or None if magnitude is None

    Example:
        >>> compute_distance_magnitude_interaction(50, 4.0)
        200.0
        >>> compute_distance_magnitude_interaction(10, None)
        None

    Interpretation:
        - High values (>500): Large number far from keyword → likely false positive
        - Low values (<100): Small number near keyword → likely true positive
        - Medium values: Requires context (definition, table, etc.)
    """
    if value_magnitude is None:
        return None
    return keyword_distance * value_magnitude


def compute_strong_signal(features: CandidateFeatures) -> bool:
    """
    Compute strong signal composite flag (P2.4).

    Strong signal indicates high confidence in the candidate:
    - Keyword very close (< 30 chars)
    - Contains definition language
    - NOT in risk factors section

    Args:
        features: CandidateFeatures object

    Returns:
        True if all strong signal conditions are met

    Example:
        >>> from src.review.models import CandidateFeatures
        >>> features = CandidateFeatures(
        ...     keyword_distance=25,
        ...     keyword_position='after',
        ...     is_in_table=False,
        ...     is_in_risk_factors=False,
        ...     contains_definition_language=True,
        ...     has_period_mention=True,
        ...     number_format='integer'
        ... )
        >>> compute_strong_signal(features)
        True
    """
    return (
        features.keyword_distance < 30
        and features.contains_definition_language
        and not features.is_in_risk_factors
    )


def compute_weak_signal(features: CandidateFeatures) -> bool:
    """
    Compute weak signal composite flag (P2.4).

    Weak signal indicates moderate confidence:
    - Keyword moderately far (50-100 chars)
    - OR in risk factors section
    - OR no definition language and not in table

    Args:
        features: CandidateFeatures object

    Returns:
        True if any weak signal conditions are met

    Example:
        >>> from src.review.models import CandidateFeatures
        >>> features = CandidateFeatures(
        ...     keyword_distance=75,
        ...     keyword_position='after',
        ...     is_in_table=False,
        ...     is_in_risk_factors=False,
        ...     contains_definition_language=False,
        ...     has_period_mention=False,
        ...     number_format='integer'
        ... )
        >>> compute_weak_signal(features)
        True
    """
    return (
        (50 <= features.keyword_distance < 100)
        or features.is_in_risk_factors
        or (not features.contains_definition_language and not features.is_in_table)
    )


def compute_very_weak_signal(features: CandidateFeatures) -> bool:
    """
    Compute very weak signal composite flag (P2.4).

    Very weak signal indicates low confidence (likely false positive):
    - Keyword very far (>= 100 chars)
    - AND (in risk factors OR no definition language)

    Args:
        features: CandidateFeatures object

    Returns:
        True if very weak signal conditions are met

    Example:
        >>> from src.review.models import CandidateFeatures
        >>> features = CandidateFeatures(
        ...     keyword_distance=150,
        ...     keyword_position='after',
        ...     is_in_table=False,
        ...     is_in_risk_factors=True,
        ...     contains_definition_language=False,
        ...     has_period_mention=False,
        ...     number_format='integer'
        ... )
        >>> compute_very_weak_signal(features)
        True
    """
    return features.keyword_distance >= 100 and (
        features.is_in_risk_factors or not features.contains_definition_language
    )


def compute_all_derived_features(features: CandidateFeatures) -> dict[str, Any]:
    """
    Compute all derived features from base features (P2.4).

    This convenience function computes binned, interaction, and composite
    features in one call for pattern analysis and ML applications.

    Args:
        features: CandidateFeatures object with base features

    Returns:
        Dictionary with all derived features:
            - keyword_distance_bin: str ('very_close', 'close', 'far', 'very_far')
            - value_magnitude_bin: str ('unknown', 'small', 'medium', 'large', 'very_large')
            - distance_magnitude_interaction: Optional[float]
            - strong_signal: bool
            - weak_signal: bool
            - very_weak_signal: bool

    Example:
        >>> from src.review.models import CandidateFeatures
        >>> features = CandidateFeatures(
        ...     keyword_distance=25,
        ...     keyword_position='after',
        ...     is_in_table=False,
        ...     is_in_risk_factors=False,
        ...     contains_definition_language=True,
        ...     has_period_mention=True,
        ...     number_format='integer',
        ...     value_magnitude=4.5
        ... )
        >>> derived = compute_all_derived_features(features)
        >>> derived['keyword_distance_bin']
        'close'
        >>> derived['strong_signal']
        True
    """
    return {
        "keyword_distance_bin": bin_keyword_distance(features.keyword_distance),
        "value_magnitude_bin": bin_value_magnitude(features.value_magnitude),
        "distance_magnitude_interaction": compute_distance_magnitude_interaction(
            features.keyword_distance, features.value_magnitude
        ),
        "strong_signal": compute_strong_signal(features),
        "weak_signal": compute_weak_signal(features),
        "very_weak_signal": compute_very_weak_signal(features),
    }
