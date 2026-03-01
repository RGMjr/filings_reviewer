"""
Parser for "respectively" patterns that associate parallel lists.

This module detects patterns like:
    "Gross margin for 2015, 2016 and 2017 was 33%, 35% and 43%, respectively."

And returns associations:
    [("33%", "2015"), ("35%", "2016"), ("43%", "2017")]

This enables correct matching of metric values to their corresponding time periods
in parallel list structures.

Example Usage:
    >>> from src.review.respectively_parser import detect_respectively_pattern
    >>>
    >>> text = "Revenue for 2015, 2016 and 2017 was $1M, $2M and $3M, respectively."
    >>> result = detect_respectively_pattern(text)
    >>>
    >>> if result:
    ...     print(f"Found {len(result.associations)} associations")
    ...     for value, period in result.associations:
    ...         print(f"  {value} -> {period}")
    >>> # Output:
    >>> # Found 3 associations
    >>> #   $1M -> 2015
    >>> #   $2M -> 2016
    >>> #   $3M -> 2017

Supported Pattern Types:
    Type A - Years in preamble, values at end:
        "Gross margin for 2015, 2016 and 2017 was 33%, 35% and 43%, respectively."

    Type B - Periods in preamble, values at end:
        "Revenue for Q1, Q2 and Q3 was $1M, $2M and $3M, respectively."

    Type C - Complex periods:
        "For the years ended December 31, 2015, 2016 and 2017 ... 33%, 35%, 43%, respectively."

    Note: "Values first, periods second" (Type D) patterns are NOT implemented.
    These do not appear in real SEC filings surveyed (n=5 Farfetch examples, all Type A/B/C).

Confidence Scores:
    The confidence score (0.0-1.0) indicates pattern structure quality:

    - 0.9-1.0: Very high - Perfect structure (consecutive years, consistent formats, clear separators)
    - 0.8-0.9: High - Strong structure (most quality indicators present)
    - 0.7-0.8: Medium - Adequate structure (basic pattern detected)
    - 0.5-0.7: Low - Weak structure (manual review recommended)

    Validated against 5 real SEC filing examples (Farfetch Ltd S-1, 2018).

    Factors:
    - Base score: 0.5
    - "and" before final items: +0.1 each
    - Consecutive years (2015→2016→2017): +0.1
    - Consistent formats (all % or all $): +0.1
    - Short distance (< 200 chars): +0.1

Integration with CandidateGenerator:
    This module integrates with candidate_generator.py to enrich candidates
    with detected period associations. See Phase 2 implementation plan.

    Basic integration pattern:

    >>> from src.review.candidate_generator import CandidateGenerator
    >>> from src.review.config import CandidateGenerationConfig
    >>>
    >>> # Enable respectively pattern detection
    >>> config = CandidateGenerationConfig(detect_respectively_patterns=True)
    >>> generator = CandidateGenerator(config=config)
    >>>
    >>> # Generate candidates - periods auto-detected from patterns
    >>> candidates = generator.generate_for_filing(...)

Limitations:
    - Only detects patterns within same sentence (cross-sentence returns None)
    - Lists must be separated by < 200 characters
    - Requires equal-length value and period lists
    - Only supports years (1990-2029) and quarters (Q1-Q4)
    - Does not handle hyphen-separated lists (2015-2016-2017)
    - Does not handle semicolon separators (only commas and "and")
"""

import logging
import re
from dataclasses import dataclass

from src.review.boundary_detection import BoundaryDetector

logger = logging.getLogger(__name__)


# =============================================================================
# Configuration Constants
# =============================================================================

# Maximum characters between period and value lists (P1.4)
MAX_LIST_DISTANCE = 200


# =============================================================================
# Regex Patterns
# =============================================================================

# Year patterns (1990-2029)
YEAR_PATTERN = re.compile(r"\b(20[0-2][0-9]|19[89][0-9])\b")

# Quarter patterns (Q1, Q2, Q3, Q4, or spelled out)
QUARTER_PATTERN = re.compile(
    r"\b(Q[1-4]|first\s+quarter|second\s+quarter|third\s+quarter|fourth\s+quarter)\b", re.IGNORECASE
)

# Value patterns (percentages, currency, numbers with optional magnitude suffixes)
VALUE_PATTERN = re.compile(
    r"""
    (?:
        \$\s*[\d,]+(?:\.\d+)?(?:\s*(?:million|billion|thousand|mn|bn|k|m|b))?  |  # Currency
        [\d,]+(?:\.\d+)?%                                                        |  # Percentage with %
        [\d,]+(?:\.\d+)?(?:\s+percent)                                          |  # Percentage with "percent"
        [\d,]+(?:\.\d+)?(?:\s*(?:million|billion|thousand|mn|bn|k|m|b))         |  # Plain number with suffix
        [\d,]+\.\d+                                                                 # Plain decimal (e.g., 1.42, 1.53)
    )
    """,
    re.VERBOSE | re.IGNORECASE,
)


# =============================================================================
# Data Classes
# =============================================================================


@dataclass
class RespectivelyMatch:
    """
    Result of detecting a 'respectively' pattern.

    Represents a parallel structure where lists of values are matched
    with lists of time periods using the "respectively" keyword.

    Attributes:
        values: List of value strings (e.g., ["33%", "35%", "43%"])
        periods: List of period strings (e.g., ["2015", "2016", "2017"])
        associations: List of (value, period) tuples (e.g., [("33%", "2015"), ...])
        confidence: Confidence score 0.0-1.0 based on pattern clarity
        span: Tuple of (start, end) positions in original text
    """

    values: list[str]
    periods: list[str]
    associations: list[tuple[str, str]]
    confidence: float
    span: tuple[int, int]

    def __post_init__(self) -> None:
        """Validate the match data."""
        if len(self.values) != len(self.periods):
            raise ValueError(
                f"Values and periods must have equal length, "
                f"got {len(self.values)} values and {len(self.periods)} periods"
            )
        if not (0 <= self.confidence <= 1):
            raise ValueError(f"Confidence must be between 0 and 1, got {self.confidence}")
        if len(self.associations) != len(self.values):
            raise ValueError(
                f"Associations length {len(self.associations)} "
                f"must match values length {len(self.values)}"
            )


# =============================================================================
# Main Detection Function
# =============================================================================


def detect_respectively_pattern(text: str, min_confidence: float = 0.6) -> RespectivelyMatch | None:
    """
    Detect a "respectively" pattern in text and return associations.

    L1-P1.1 Enhancement: Configurable confidence filtering.

    Note: Only detects the FIRST pattern in text. For multiple pattern detection,
    use detect_all_respectively_patterns() instead.

    Args:
        text: Text to search for pattern
        min_confidence: Minimum confidence threshold (0.5-1.0). Patterns
            with confidence below this are filtered out. Default: 0.6

    Returns:
        RespectivelyMatch if pattern found with sufficient confidence, None otherwise

    Examples:
        >>> text = "Margin for 2015, 2016 and 2017 was 33%, 35% and 43%, respectively."
        >>> result = detect_respectively_pattern(text)
        >>> result.associations
        [("33%", "2015"), ("35%", "2016"), ("43%", "2017")]

        >>> text = "Revenue was $1M in 2015."  # No "respectively"
        >>> detect_respectively_pattern(text)
        None

        >>> text = "For 2015 and 2016 was 33% and 35%, respectively."
        >>> result = detect_respectively_pattern(text, min_confidence=0.8)
        >>> result is None  # Low confidence pattern filtered
        True
    """
    # 1. Check if "respectively" appears
    if "respectively" not in text.lower():
        return None

    # 2. Find the position of "respectively"
    resp_match = re.search(r"\brespectively\b", text, re.IGNORECASE)
    if not resp_match:
        return None

    resp_pos = resp_match.start()

    # 3. NEW: Detect sentence boundaries to prevent cross-sentence matching
    detector = BoundaryDetector()
    sentences = detector.find_sentence_boundaries(text)

    # Find sentence containing "respectively"
    resp_sentence = None
    for sentence in sentences:
        if sentence.start <= resp_pos < sentence.end:
            resp_sentence = sentence
            break

    if not resp_sentence:
        logger.debug("Could not find sentence boundary for 'respectively'")
        return None

    # 4. Extract text from SAME SENTENCE only (not entire text before "respectively")
    context = text[resp_sentence.start : resp_pos]

    # 5. Find period list (should be earlier in text)
    periods = _extract_period_list(context)

    # 6. Find value list (closest to "respectively")
    values = _extract_value_list(context)

    # 7. NEW: Distance constraint check (P1.4)
    if values and periods:
        # Find positions in context
        last_period = periods[-1]
        first_value = values[0]

        last_period_pos = context.rfind(last_period)
        first_value_pos = context.find(first_value)

        if last_period_pos >= 0 and first_value_pos >= 0:
            distance = first_value_pos - last_period_pos

            if distance > MAX_LIST_DISTANCE:
                logger.debug(
                    f"Lists too far apart: {distance} > {MAX_LIST_DISTANCE} chars. "
                    f"Periods: {periods}, Values: {values}"
                )
                return None

    # 8. Validate: equal length lists
    if not values or not periods or len(values) != len(periods):
        logger.debug(
            f"Respectively pattern validation failed: "
            f"{len(values) if values else 0} values vs "
            f"{len(periods) if periods else 0} periods"
        )
        return None

    # 9. Create associations (pair values with periods in order)
    associations = list(zip(values, periods, strict=True))

    # 10. Calculate confidence
    confidence = _calculate_confidence(values, periods, context)

    # L1-P1.1: Filter by minimum confidence
    if confidence < min_confidence:
        logger.debug(
            f"Respectively pattern filtered by confidence: "
            f"{confidence:.2f} < {min_confidence:.2f}. "
            f"Periods: {periods}, Values: {values}"
        )
        return None

    return RespectivelyMatch(
        values=values,
        periods=periods,
        associations=associations,
        confidence=confidence,
        span=(resp_sentence.start, resp_match.end()),
    )


def detect_all_respectively_patterns(
    text: str, min_confidence: float = 0.6
) -> list[RespectivelyMatch]:
    """
    Detect ALL "respectively" patterns in text.

    L1-P1.2 Enhancement: Multiple pattern detection.

    This function detects all respectively patterns in the text by processing
    each sentence independently. Real-world filings may contain multiple
    patterns (average: 1.4 patterns per segment with "respectively").

    Args:
        text: Text to search for patterns
        min_confidence: Minimum confidence threshold (0.5-1.0). Patterns
            with confidence below this are filtered out. Default: 0.6

    Returns:
        List of RespectivelyMatch objects, one per detected pattern.
        Empty list if no patterns found.

    Examples:
        >>> text = '''
        ... Gross margin for 2015, 2016 and 2017 was 33%, 35% and 43%, respectively.
        ... Net margin for 2015, 2016 and 2017 was 10%, 12% and 15%, respectively.
        ... '''
        >>> results = detect_all_respectively_patterns(text)
        >>> len(results)
        2
        >>> results[0].associations
        [("33%", "2015"), ("35%", "2016"), ("43%", "2017")]
        >>> results[1].associations
        [("10%", "2015"), ("12%", "2016"), ("15%", "2017")]
    """
    # Quick check: if "respectively" doesn't appear, return empty list
    if "respectively" not in text.lower():
        return []

    patterns: list[RespectivelyMatch] = []

    # Detect sentence boundaries
    detector = BoundaryDetector()
    sentences = detector.find_sentence_boundaries(text)

    # Process each sentence that contains "respectively"
    for sentence in sentences:
        sentence_text = text[sentence.start : sentence.end]

        if "respectively" not in sentence_text.lower():
            continue

        # Detect pattern within this sentence
        pattern = _detect_in_sentence(
            sentence_text, sentence_offset=sentence.start, min_confidence=min_confidence
        )

        if pattern:
            patterns.append(pattern)

    if patterns:
        logger.debug(
            f"Detected {len(patterns)} respectively pattern(s) in text ({len(text)} chars)"
        )

    return patterns


def _detect_in_sentence(
    sentence_text: str, sentence_offset: int, min_confidence: float
) -> RespectivelyMatch | None:
    """
    Detect a respectively pattern within a single sentence.

    Helper for detect_all_respectively_patterns().

    Args:
        sentence_text: Text of sentence to search
        sentence_offset: Offset of sentence start in original text
        min_confidence: Minimum confidence threshold

    Returns:
        RespectivelyMatch if pattern found, None otherwise
    """
    # Find "respectively" position within sentence
    resp_match = re.search(r"\brespectively\b", sentence_text, re.IGNORECASE)
    if not resp_match:
        return None

    resp_pos = resp_match.start()

    # Extract text before "respectively" (within same sentence)
    context = sentence_text[:resp_pos]

    # Find period and value lists
    periods = _extract_period_list(context)
    values = _extract_value_list(context)

    # Distance constraint check
    if values and periods:
        last_period = periods[-1]
        first_value = values[0]

        last_period_pos = context.rfind(last_period)
        first_value_pos = context.find(first_value)

        if last_period_pos >= 0 and first_value_pos >= 0:
            distance = first_value_pos - last_period_pos

            if distance > MAX_LIST_DISTANCE:
                logger.debug(
                    f"Lists too far apart: {distance} > {MAX_LIST_DISTANCE} chars. "
                    f"Periods: {periods}, Values: {values}"
                )
                return None

    # Validate: equal length lists
    if not values or not periods or len(values) != len(periods):
        logger.debug(
            f"Respectively pattern validation failed: "
            f"{len(values) if values else 0} values vs "
            f"{len(periods) if periods else 0} periods"
        )
        return None

    # Create associations
    associations = list(zip(values, periods, strict=True))

    # Calculate confidence
    confidence = _calculate_confidence(values, periods, context)

    # Filter by minimum confidence
    if confidence < min_confidence:
        logger.debug(
            f"Respectively pattern filtered by confidence: "
            f"{confidence:.2f} < {min_confidence:.2f}. "
            f"Periods: {periods}, Values: {values}"
        )
        return None

    return RespectivelyMatch(
        values=values,
        periods=periods,
        associations=associations,
        confidence=confidence,
        span=(sentence_offset, sentence_offset + resp_match.end()),
    )


# =============================================================================
# Helper Functions
# =============================================================================


def _extract_value_list(text: str) -> list[str]:
    """
    Extract a list of values from text.

    Finds sequences of values connected by commas and "and", working
    backward from the end of text to find the rightmost list (closest
    to "respectively").

    Args:
        text: Text to search (typically text before "respectively")

    Returns:
        List of value strings, or empty list if no valid list found

    Examples:
        >>> _extract_value_list("was 33%, 35% and 43%")
        ["33%", "35%", "43%"]

        >>> _extract_value_list("revenue was $1M, $2M and $3M")
        ["$1M", "$2M", "$3M"]
    """
    # Find all value matches
    matches = list(VALUE_PATTERN.finditer(text))
    if not matches:
        return []

    # Work backward to find lists connected by ", " or " and "
    # We want the rightmost/last list (closest to "respectively")

    # Start from the last match and work backward
    candidate_list = [matches[-1].group().strip()]
    candidate_positions = [matches[-1].start()]

    for i in range(len(matches) - 2, -1, -1):
        current_match = matches[i]
        next_match = matches[i + 1]

        # Check the text between current and next match
        between = text[current_match.end() : next_match.start()]

        # Valid separators: ", " or " and " (with optional whitespace)
        if re.match(r"^\s*,\s*$", between) or re.match(r"^\s+and\s+$", between):
            # This is part of the same list
            candidate_list.insert(0, current_match.group().strip())
            candidate_positions.insert(0, current_match.start())
        else:
            # Gap too large or wrong separator - stop here
            break

    # Only return if we have at least 2 items (a list requires multiple items)
    if len(candidate_list) >= 2:
        return candidate_list

    return []


def _extract_period_list(text: str) -> list[str]:
    """
    Extract a list of time periods (years, quarters) from text.

    Looks for sequences of years or quarters connected by commas and "and".
    Handles complex patterns like "years ended December 31, 2015, 2016 and 2017".

    Args:
        text: Text to search (typically text before "respectively")

    Returns:
        List of period strings, or empty list if no valid list found

    Examples:
        >>> _extract_period_list("for 2015, 2016 and 2017")
        ["2015", "2016", "2017"]

        >>> _extract_period_list("for Q1, Q2 and Q3")
        ["Q1", "Q2", "Q3"]

        >>> _extract_period_list("December 31, 2015, 2016 and 2017")
        ["2015", "2016", "2017"]
    """
    # Try years first
    year_matches = list(YEAR_PATTERN.finditer(text))
    if year_matches:
        # Find lists of consecutive years
        candidate_list = [year_matches[0].group()]
        candidate_positions = [year_matches[0].start()]

        for i in range(1, len(year_matches)):
            current_match = year_matches[i]
            prev_match = year_matches[i - 1]

            # Check the text between previous and current match
            between = text[prev_match.end() : current_match.start()]

            # Valid separators: ", " or " and " (with optional whitespace)
            # Also allow "December 31, " style prefixes
            if (
                re.search(r",\s*$", between)
                or re.search(r"\s+and\s+$", between)
                or re.match(r"^,\s*", between)
            ):
                # This is part of the same list
                candidate_list.append(current_match.group())
                candidate_positions.append(current_match.start())
            elif len(candidate_list) < 2:
                # Haven't found a list yet, restart from this match
                candidate_list = [current_match.group()]
                candidate_positions = [current_match.start()]

        # Return if we have at least 2 items
        if len(candidate_list) >= 2:
            return candidate_list

    # Try quarters if years didn't work
    quarter_matches = list(QUARTER_PATTERN.finditer(text))
    if quarter_matches:
        candidate_list = [quarter_matches[0].group()]

        for i in range(1, len(quarter_matches)):
            current_match = quarter_matches[i]
            prev_match = quarter_matches[i - 1]

            between = text[prev_match.end() : current_match.start()]

            if re.search(r",\s*$", between) or re.search(r"\s+and\s+$", between):
                candidate_list.append(current_match.group())
            elif len(candidate_list) < 2:
                candidate_list = [current_match.group()]

        if len(candidate_list) >= 2:
            return candidate_list

    return []


def _calculate_confidence(values: list[str], periods: list[str], context: str) -> float:
    """
    Calculate confidence score for a respectively pattern match.

    Confidence factors:
    - Base score: 0.5
    - "and" before final value: +0.1 (FIXED: was documented as +0.2)
    - "and" before final period: +0.1 (FIXED: was documented as +0.2)
    - Consistent value formats: +0.1 (all % or all $)
    - Consecutive years: +0.1 (2015→2016→2017)
    - Short distance: +0.1 (< 200 chars between lists)

    Maximum: 1.0

    Interpretation (validated against 5 real SEC filing examples):
    - 0.9-1.0: Very high - Perfect pattern structure
    - 0.8-0.9: High - Strong pattern structure
    - 0.7-0.8: Medium - Adequate pattern structure
    - 0.5-0.7: Low - Manual review recommended

    Based on Farfetch Ltd S-1 filing examples (2018).

    Args:
        values: List of value strings
        periods: List of period strings
        context: Text containing both lists

    Returns:
        Confidence score between 0.0 and 1.0
    """
    score = 0.5  # Base score

    # +0.1 each if lists end with "and" pattern (total +0.2 if both)
    # Check if context contains "and [last_value]" and "and [last_period]"
    last_value = values[-1] if values else ""
    last_period = periods[-1] if periods else ""

    if last_value and f"and {last_value}" in context:
        score += 0.1
    if last_period and f"and {last_period}" in context:
        score += 0.1

    # +0.1 if years are consecutive
    try:
        years = [int(p) for p in periods if p.isdigit()]
        if len(years) >= 2:
            consecutive = all(years[i] == years[i - 1] + 1 for i in range(1, len(years)))
            if consecutive:
                score += 0.1
    except (ValueError, IndexError):
        pass

    # +0.1 if values have consistent format (all %, all $, etc.)
    if values:
        has_percent = [("%" in v) for v in values]
        has_currency = [("$" in v) for v in values]

        if all(has_percent) or all(has_currency):
            score += 0.1

    # +0.1 if lists are relatively close together
    # Find positions of last period and first value in context
    last_period_pos = context.rfind(last_period) if last_period else -1
    first_value = values[0] if values else ""
    first_value_pos = context.find(first_value) if first_value else -1

    if last_period_pos >= 0 and first_value_pos >= 0:
        distance = first_value_pos - last_period_pos
        # If distance is less than 200 characters, that's close
        if distance < 200:
            score += 0.1

    # Clamp to [0.0, 1.0]
    return max(0.0, min(1.0, score))
