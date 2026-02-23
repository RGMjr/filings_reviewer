"""
Number Parsing - Extract and parse numbers from text.

This module provides functionality to find and parse numbers in text,
including handling of currency symbols, comma separators, decimal points,
and magnitude suffixes (million, billion, etc.).

Extracted from candidate_generator.py as part of P1.3 module splitting
for improved maintainability and testability.

Automatic Usage (via CandidateGenerator):
    >>> from src.review import CandidateGenerator
    >>>
    >>> # Number parsing happens automatically
    >>> generator = CandidateGenerator()
    >>> candidates = generator.generate_for_filing(
    ...     filing_id=123, company_id=456, segments=segments
    ... )
    >>> # Each candidate has parsed_value field (Decimal)
    >>> print(candidates[0].parsed_value)  # e.g., Decimal("50000")
    >>> print(candidates[0].raw_number_text)  # e.g., "50,000"

Direct Usage (advanced):
    >>> from src.review.number_parsing import NumberParser
    >>>
    >>> # Initialize parser
    >>> parser = NumberParser()
    >>>
    >>> # Find all numbers in text
    >>> text = "We have $50,000 active customers and $100M in revenue."
    >>> numbers = parser.find_numbers(text)
    >>> for num in numbers:
    ...     print(f"{num.raw_text} -> {num.value} {num.unit}")
    >>> # Output:
    >>> # "$50,000" -> 50000 currency
    >>> # "$100M" -> 100000000 currency

Supported Number Formats:
    >>> # Simple integers
    >>> parser.parse_number("$50,000")  # -> (Decimal("50000"), "currency")
    >>> parser.parse_number("95%")      # -> (Decimal("95"), "percentage")
    >>>
    >>> # Decimals
    >>> parser.parse_number("1.25")     # -> (Decimal("1.25"), "count")
    >>> parser.parse_number("$12.50")   # -> (Decimal("12.50"), "currency")
    >>>
    >>> # Magnitude suffixes
    >>> parser.parse_number("$100M")    # -> (Decimal("100000000"), "currency")
    >>> parser.parse_number("2.5B")     # -> (Decimal("2500000000"), "count")
    >>> parser.parse_number("500K")     # -> (Decimal("500000"), "count")
    >>>
    >>> # Negative numbers
    >>> parser.parse_number("-45")      # -> (Decimal("-45"), "count")

Understanding Units:
    >>> # Units are determined by number format:
    >>> # - "currency": Has $ prefix
    >>> # - "percentage": Has % suffix
    >>> # - "count": Everything else (default)
    >>>
    >>> # Units used for feature extraction and confidence scoring

See Also:
    - candidate_generator.py: Uses NumberParser internally
    - false_positive_filter.py: Filters parsed numbers
"""

import logging
import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

logger = logging.getLogger(__name__)

# =============================================================================
# Spelled-out Number Conversion
# =============================================================================

# Word to number mappings
WORD_TO_NUMBER: dict[str, int] = {
    "zero": 0,
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "eleven": 11,
    "twelve": 12,
    "thirteen": 13,
    "fourteen": 14,
    "fifteen": 15,
    "sixteen": 16,
    "seventeen": 17,
    "eighteen": 18,
    "nineteen": 19,
    "twenty": 20,
    "thirty": 30,
    "forty": 40,
    "fifty": 50,
    "sixty": 60,
    "seventy": 70,
    "eighty": 80,
    "ninety": 90,
    "hundred": 100,
}

# Magnitude words that multiply the number
MAGNITUDE_WORDS: dict[str, int] = {
    "thousand": 1_000,
    "million": 1_000_000,
    "billion": 1_000_000_000,
    "trillion": 1_000_000_000_000,
}

# Pattern for spelled-out numbers (handles "six", "twenty-one", "six million", etc.)
SPELLED_NUMBER_PATTERN = r"""
    \b
    (?P<spelled>
        (?:zero|one|two|three|four|five|six|seven|eight|nine|
           ten|eleven|twelve|thirteen|fourteen|fifteen|sixteen|
           seventeen|eighteen|nineteen|twenty|thirty|forty|fifty|
           sixty|seventy|eighty|ninety|hundred)
        (?:[-\s]+(?:one|two|three|four|five|six|seven|eight|nine))?  # compound: twenty-one
    )
    (?:\s+(?P<magnitude>thousand|million|billion|trillion))?  # optional magnitude
    \b
"""

SPELLED_NUMBER_REGEX = re.compile(SPELLED_NUMBER_PATTERN, re.IGNORECASE | re.VERBOSE)


def parse_spelled_number(text: str) -> int | None:
    """
    Convert a spelled-out number to an integer.

    Args:
        text: Spelled-out number like "six", "twenty-one", "five million"

    Returns:
        Integer value or None if not parseable

    Examples:
        >>> parse_spelled_number("six")
        6
        >>> parse_spelled_number("twenty-one")
        21
        >>> parse_spelled_number("five million")
        5000000
    """
    text = text.lower().strip()

    # Check for magnitude suffix
    magnitude_multiplier = 1
    for mag_word, mag_value in MAGNITUDE_WORDS.items():
        if mag_word in text:
            magnitude_multiplier = mag_value
            text = text.replace(mag_word, "").strip()
            break

    # Handle compound numbers like "twenty-one" or "twenty one"
    parts = re.split(r"[-\s]+", text)

    total = 0
    for part in parts:
        if not part:
            continue
        if part in WORD_TO_NUMBER:
            val = WORD_TO_NUMBER[part]
            if val == 100:
                # "hundred" multiplies what comes before
                total = total * 100 if total > 0 else 100
            else:
                total += val
        else:
            # Unknown word
            return None

    if total == 0 and "zero" not in text.lower():
        return None

    return total * magnitude_multiplier


# =============================================================================
# Number Pattern
# =============================================================================

# Pattern to match numbers with optional currency, commas, decimals, and suffixes
# Supports both comma-separated (1,234,567) and plain integers (1234567)
NUMBER_PATTERN = r"""
    (?P<currency>\$)?                           # Optional currency symbol
    \s*
    (?P<number>
        -?                                      # Optional negative sign
        (?:
            \d{1,3}(?:,\d{3})+                 # Comma-separated (1,234 or 1,234,567)
            |
            \d+                                 # Or plain integer (1234567)
        )
        (?:\.\d+)?                              # Optional decimal part
    )
    \s*
    (?P<suffix>million|billion|thousand|mn|bn|k|m|b|%|percent)?  # Optional suffix
"""

NUMBER_REGEX = re.compile(NUMBER_PATTERN, re.IGNORECASE | re.VERBOSE)


# =============================================================================
# Data Classes
# =============================================================================


@dataclass
class NumberMatch:
    """A number found in text with position and parsed value."""

    start: int  # Character position in text
    end: int  # End position
    raw_text: str  # Original text (e.g., "$1,234.56 million")
    value: Decimal | None  # Parsed numeric value
    unit: str | None  # Detected unit ('count', '%', 'usd', etc.)


# =============================================================================
# Number Parser
# =============================================================================


class NumberParser:
    """
    Parser for finding and extracting numbers from text.

    Handles various number formats including:
    - Currency: $1,234.56
    - Percentages: 45%
    - Magnitude suffixes: 123 million, 45 billion
    - Plain numbers: 1234567
    - Spelled-out numbers: six, twenty-one, five million
    """

    def __init__(self, include_spelled: bool = True) -> None:
        """
        Initialize the number parser.

        Args:
            include_spelled: Whether to include spelled-out numbers (default True)
        """
        self._regex = NUMBER_REGEX
        self._include_spelled = include_spelled

    def find_numbers(self, text: str) -> list[NumberMatch]:
        """
        Find all numbers in text, including spelled-out numbers.

        Args:
            text: The text to search

        Returns:
            List of NumberMatch objects with positions and parsed values
        """
        matches = []
        used_positions: set[tuple[int, int]] = set()

        # First find numeric numbers
        for match in self._regex.finditer(text):
            raw_text = match.group().strip()
            number_str = match.group("number")
            suffix = match.group("suffix")
            currency = match.group("currency")

            # Adjust positions to exclude leading/trailing whitespace
            # Find where the stripped text starts and ends
            match_text = match.group()
            lstrip_len = len(match_text) - len(match_text.lstrip())
            rstrip_len = len(match_text) - len(match_text.rstrip())

            adjusted_start = match.start() + lstrip_len
            adjusted_end = match.end() - rstrip_len

            # Parse the number
            try:
                value, unit = self.parse_number(number_str, suffix, currency)

                matches.append(
                    NumberMatch(
                        start=adjusted_start,
                        end=adjusted_end,
                        raw_text=raw_text,
                        value=value,
                        unit=unit,
                    )
                )
                used_positions.add((adjusted_start, adjusted_end))
            except (ValueError, InvalidOperation) as e:
                # Log but don't fail - just skip unparseable numbers
                logger.debug(
                    f"Could not parse number '{raw_text}' at position {match.start()}: {e}"
                )
                continue

        # Then find spelled-out numbers (if enabled)
        if self._include_spelled:
            for match in SPELLED_NUMBER_REGEX.finditer(text):
                raw_text = match.group().strip()
                start = match.start()
                end = match.end()

                # Skip if this position overlaps with an existing numeric match
                overlaps = any(
                    not (end <= pos_start or start >= pos_end)
                    for pos_start, pos_end in used_positions
                )
                if overlaps:
                    continue

                # Parse the spelled-out number
                spelled_value = parse_spelled_number(raw_text)
                if spelled_value is not None:
                    matches.append(
                        NumberMatch(
                            start=start,
                            end=end,
                            raw_text=raw_text,
                            value=Decimal(spelled_value),
                            unit="count",  # spelled-out numbers are counts
                        )
                    )
                    used_positions.add((start, end))

        # Sort by position
        matches.sort(key=lambda m: m.start)

        return matches

    def parse_number(
        self,
        number_str: str,
        suffix: str | None = None,
        currency: str | None = None,
    ) -> tuple[Decimal, str]:
        """
        Parse a number string into a Decimal value and unit.

        Args:
            number_str: The numeric part (e.g., "1,234.56")
            suffix: Optional suffix (e.g., "million", "%")
            currency: Optional currency symbol (e.g., "$")

        Returns:
            Tuple of (parsed_value, unit)
            unit is one of: 'count', 'usd', '%'

        Raises:
            ValueError: If number cannot be parsed
            InvalidOperation: If Decimal conversion fails
        """
        # Remove commas for parsing
        clean_number = number_str.replace(",", "")

        # Parse base number
        value = Decimal(clean_number)

        # Apply multipliers from suffix
        if suffix:
            suffix_lower = suffix.lower()
            if suffix_lower in ("million", "mn", "m"):
                value *= Decimal("1000000")
            elif suffix_lower in ("billion", "bn", "b"):
                value *= Decimal("1000000000")
            elif suffix_lower in ("thousand", "k"):
                value *= Decimal("1000")

        # Determine unit
        if suffix and suffix.lower() in ("%", "percent"):
            # Percentage - convert to decimal (45% -> 0.45)
            unit = "%"
            value = value / Decimal("100")
        elif currency == "$":
            unit = "usd"
        else:
            unit = "count"

        return value, unit
