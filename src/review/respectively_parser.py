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

    Type D - Values first, periods second:
        "Revenue of $1M, $2M and $3M for 2015, 2016 and 2017, respectively."

Integration with CandidateGenerator:
    This module is currently standalone and will be integrated with
    candidate_generator.py in a future task to enhance time period detection.
"""

import logging
import re
from dataclasses import dataclass
from typing import List, Optional, Tuple

logger = logging.getLogger(__name__)


# =============================================================================
# Regex Patterns
# =============================================================================

# Year patterns (1990-2029)
YEAR_PATTERN = re.compile(r'\b(20[0-2][0-9]|19[89][0-9])\b')

# Quarter patterns (Q1, Q2, Q3, Q4, or spelled out)
QUARTER_PATTERN = re.compile(
    r'\b(Q[1-4]|first\s+quarter|second\s+quarter|third\s+quarter|fourth\s+quarter)\b',
    re.IGNORECASE
)

# Value patterns (percentages, currency, numbers with optional magnitude suffixes)
VALUE_PATTERN = re.compile(
    r'''
    (?:
        \$\s*[\d,]+(?:\.\d+)?(?:\s*(?:million|billion|thousand|mn|bn|k|m|b))?  |  # Currency
        [\d,]+(?:\.\d+)?%                                                        |  # Percentage with %
        [\d,]+(?:\.\d+)?(?:\s+percent)                                          |  # Percentage with "percent"
        [\d,]+(?:\.\d+)?(?:\s*(?:million|billion|thousand|mn|bn|k|m|b))         |  # Plain number with suffix
        [\d,]+\.\d+                                                                 # Plain decimal (e.g., 1.42, 1.53)
    )
    ''',
    re.VERBOSE | re.IGNORECASE
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
    values: List[str]
    periods: List[str]
    associations: List[Tuple[str, str]]
    confidence: float
    span: Tuple[int, int]

    def __post_init__(self) -> None:
        """Validate the match data."""
        if len(self.values) != len(self.periods):
            raise ValueError(
                f"Values and periods must have equal length, "
                f"got {len(self.values)} values and {len(self.periods)} periods"
            )
        if not (0 <= self.confidence <= 1):
            raise ValueError(
                f"Confidence must be between 0 and 1, got {self.confidence}"
            )
        if len(self.associations) != len(self.values):
            raise ValueError(
                f"Associations length {len(self.associations)} "
                f"must match values length {len(self.values)}"
            )


# =============================================================================
# Main Detection Function
# =============================================================================


def detect_respectively_pattern(text: str) -> Optional[RespectivelyMatch]:
    """
    Detect a "respectively" pattern in text and return associations.

    Args:
        text: Text to search for pattern

    Returns:
        RespectivelyMatch if pattern found, None otherwise

    Examples:
        >>> text = "Margin for 2015, 2016 and 2017 was 33%, 35% and 43%, respectively."
        >>> result = detect_respectively_pattern(text)
        >>> result.associations
        [("33%", "2015"), ("35%", "2016"), ("43%", "2017")]

        >>> text = "Revenue was $1M in 2015."  # No "respectively"
        >>> detect_respectively_pattern(text)
        None
    """
    # 1. Check if "respectively" appears
    if "respectively" not in text.lower():
        return None

    # 2. Find the position of "respectively"
    resp_match = re.search(r'\brespectively\b', text, re.IGNORECASE)
    if not resp_match:
        return None

    resp_pos = resp_match.start()

    # 3. Extract text before "respectively" (where lists should be)
    context = text[:resp_pos]

    # 4. Find period list (should be earlier in text)
    periods = _extract_period_list(context)

    # 5. Find value list (closest to "respectively")
    values = _extract_value_list(context)

    # 6. Validate: equal length lists
    if not values or not periods or len(values) != len(periods):
        logger.debug(
            f"Respectively pattern validation failed: "
            f"{len(values) if values else 0} values vs "
            f"{len(periods) if periods else 0} periods"
        )
        return None

    # 7. Create associations (pair values with periods in order)
    associations = list(zip(values, periods))

    # 8. Calculate confidence
    confidence = _calculate_confidence(values, periods, context)

    return RespectivelyMatch(
        values=values,
        periods=periods,
        associations=associations,
        confidence=confidence,
        span=(0, resp_match.end())
    )


# =============================================================================
# Helper Functions
# =============================================================================


def _extract_value_list(text: str) -> List[str]:
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
        between = text[current_match.end():next_match.start()]

        # Valid separators: ", " or " and " (with optional whitespace)
        if re.match(r'^\s*,\s*$', between) or re.match(r'^\s+and\s+$', between):
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


def _extract_period_list(text: str) -> List[str]:
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
            between = text[prev_match.end():current_match.start()]

            # Valid separators: ", " or " and " (with optional whitespace)
            # Also allow "December 31, " style prefixes
            if (re.search(r',\s*$', between) or
                re.search(r'\s+and\s+$', between) or
                re.match(r'^,\s*', between)):
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

            between = text[prev_match.end():current_match.start()]

            if re.search(r',\s*$', between) or re.search(r'\s+and\s+$', between):
                candidate_list.append(current_match.group())
            elif len(candidate_list) < 2:
                candidate_list = [current_match.group()]

        if len(candidate_list) >= 2:
            return candidate_list

    return []


def _calculate_confidence(
    values: List[str],
    periods: List[str],
    context: str
) -> float:
    """
    Calculate confidence score for a respectively pattern match.

    Considers multiple factors:
    - Equal list lengths (required, +0.3 base)
    - Clear "and" before final items (+0.2)
    - Consistent value formats (+0.2)
    - Consecutive years (+0.2)
    - Short distance between lists (+0.1)

    Args:
        values: List of value strings
        periods: List of period strings
        context: Text containing both lists

    Returns:
        Confidence score between 0.0 and 1.0
    """
    score = 0.5  # Base score

    # +0.2 if both lists end with "and" pattern
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
            consecutive = all(
                years[i] == years[i-1] + 1
                for i in range(1, len(years))
            )
            if consecutive:
                score += 0.1
    except (ValueError, IndexError):
        pass

    # +0.1 if values have consistent format (all %, all $, etc.)
    if values:
        has_percent = [('%' in v) for v in values]
        has_currency = [('$' in v) for v in values]

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
