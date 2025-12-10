"""
False Positive Filter - Identify and filter out false positive number matches.

This module provides functionality to identify numbers that are unlikely to be
metrics, such as dates, years, page numbers, and other reference numbers.

Extracted from candidate_generator.py as part of P1.3 module splitting
for improved maintainability and testability.
"""

import logging
import re
from typing import List, Optional, Pattern, Tuple

from src.review.number_parsing import NumberMatch

logger = logging.getLogger(__name__)


# =============================================================================
# False Positive Detection Patterns
# =============================================================================

# Date patterns - to detect if a number is part of a date
DATE_CONTEXT_PATTERNS: List[Pattern] = [
    # MM/DD/YYYY or DD/MM/YYYY
    re.compile(r"\d{1,2}/\d{1,2}/\d{2,4}"),
    # Month DD, YYYY
    re.compile(
        r"(?:January|February|March|April|May|June|July|August|September|"
        r"October|November|December)\s+\d{1,2},?\s+\d{4}",
        re.IGNORECASE,
    ),
    # DD Month YYYY
    re.compile(
        r"\d{1,2}\s+(?:January|February|March|April|May|June|July|August|"
        r"September|October|November|December)\s+\d{4}",
        re.IGNORECASE,
    ),
]

# Patterns that indicate a number is NOT a metric (contextual false positives)
FALSE_POSITIVE_CONTEXT_PATTERNS: List[Pattern] = [
    # Page references: "page 123", "pages 10-20"
    re.compile(r"\bpages?\s+\d+", re.IGNORECASE),
    # Note references: "Note 5", "Notes 1-3"
    re.compile(r"\bnotes?\s+\d+", re.IGNORECASE),
    # Section references: "Section 5.1"
    re.compile(r"\bsections?\s+\d+", re.IGNORECASE),
    # Item references: "Item 1A"
    re.compile(r"\bitems?\s+\d+", re.IGNORECASE),
    # Version numbers: "Version 2.0", "v2.1"
    re.compile(r"\b(?:version|v)\s*\d+(?:\.\d+)*", re.IGNORECASE),
    # Exhibit references: "Exhibit 10.1"
    re.compile(r"\bexhibits?\s+\d+", re.IGNORECASE),
    # Table references: "Table 1"
    re.compile(r"\btables?\s+\d+", re.IGNORECASE),
    # Figure references: "Figure 3"
    re.compile(r"\bfigures?\s+\d+", re.IGNORECASE),
    # Footnote references: "[1]", "(1)"
    re.compile(r"[\[\(]\d+[\]\)]"),
    # Chapter references: "Chapter 5"
    re.compile(r"\bchapters?\s+\d+", re.IGNORECASE),
    # Part references: "Part II"
    re.compile(r"\bparts?\s+(?:I{1,3}|IV|V|VI{0,3}|\d+)", re.IGNORECASE),
]

# Year range - numbers in this range are likely years, not metrics
YEAR_MIN = 1990
YEAR_MAX = 2100

# Minimum value threshold - very small numbers are rarely metrics
MIN_METRIC_VALUE = 10  # Filter out single-digit numbers by default


# =============================================================================
# FalsePositiveFilter Class
# =============================================================================


class FalsePositiveFilter:
    """
    Filter for identifying false positive number matches.

    Handles filtering of numbers that are unlikely to be metrics:
    - Numbers below minimum threshold
    - Year values (1990-2100)
    - Numbers that are part of dates
    - Reference numbers (page, note, section, etc.)
    """

    def __init__(
        self,
        filter_enabled: bool = True,
        min_value: float = MIN_METRIC_VALUE,
        filter_years: bool = True,
    ):
        """
        Initialize the false positive filter.

        Args:
            filter_enabled: Whether to apply filtering (can disable for testing)
            min_value: Minimum value threshold for count units
            filter_years: Whether to filter year-like values
        """
        self.filter_enabled = filter_enabled
        self.min_value = min_value
        self.filter_years = filter_years

    def is_false_positive(
        self, text: str, number: NumberMatch
    ) -> Tuple[bool, Optional[str]]:
        """
        Check if a number match is likely a false positive.

        Filters out:
        - Numbers that are part of dates (12/31/2023)
        - Numbers that look like years (1990-2100)
        - Page/note/section/exhibit references
        - Version numbers
        - Numbers below minimum threshold

        Args:
            text: The full text containing the number
            number: The NumberMatch to check

        Returns:
            Tuple of (is_false_positive, reason)
            reason is None if not a false positive
        """
        if not self.filter_enabled:
            return False, None

        value = number.value
        start = number.start
        end = number.end

        # Check minimum value threshold (skip for percentages, currency, and decimals)
        # Decimals like 1.25 could be ratios (e.g., NRR of 125%)
        if number.unit == "count" and value is not None:
            is_decimal = "." in number.raw_text
            if not is_decimal and abs(float(value)) < self.min_value:
                return True, "below_min_value"

        # Check if number looks like a year (only for plain integers)
        if self.filter_years and number.unit == "count":
            if value is not None and YEAR_MIN <= float(value) <= YEAR_MAX:
                # Additional check: is it a 4-digit integer without decimal?
                if "." not in number.raw_text and len(number.raw_text.replace(",", "")) == 4:
                    return True, "likely_year"

        # Check if number is part of a date pattern
        # Look at surrounding context (30 chars each side)
        context_start = max(0, start - 30)
        context_end = min(len(text), end + 30)
        local_context = text[context_start:context_end]

        # Calculate the number's position relative to the local context
        num_rel_start = start - context_start
        num_rel_end = end - context_start

        for pattern in DATE_CONTEXT_PATTERNS:
            match = pattern.search(local_context)
            if match:
                # Check if our number overlaps with the date match (in local coords)
                if num_rel_start >= match.start() and num_rel_end <= match.end():
                    return True, "part_of_date"

        # Check for false positive context patterns (page refs, notes, etc.)
        for pattern in FALSE_POSITIVE_CONTEXT_PATTERNS:
            match = pattern.search(local_context)
            if match:
                # Check if our number overlaps with the reference pattern
                if num_rel_start >= match.start() and num_rel_end <= match.end():
                    return True, "reference_number"

        return False, None
