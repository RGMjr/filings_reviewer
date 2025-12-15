"""
False Positive Filter - Identify and filter out false positive number matches.

This module provides functionality to identify numbers that are unlikely to be
metrics, such as dates, years, page numbers, and other reference numbers.

Extracted from candidate_generator.py as part of P1.3 module splitting
for improved maintainability and testability.

Automatic Usage (via CandidateGenerator):
    >>> from src.review import CandidateGenerator
    >>>
    >>> # False positive filtering enabled by default
    >>> generator = CandidateGenerator()
    >>> candidates = generator.generate_for_filing(
    ...     filing_id=123, company_id=456, segments=segments
    ... )
    >>> # Years (1990-2100), dates, page refs automatically filtered

Direct Usage (advanced):
    >>> from src.review.false_positive_filter import FalsePositiveFilter
    >>> from src.review.number_parsing import NumberMatch
    >>> from decimal import Decimal
    >>>
    >>> # Initialize filter
    >>> fp_filter = FalsePositiveFilter(
    ...     min_metric_value=10,
    ...     filter_years=True,
    ...     year_min=1990,
    ...     year_max=2100,
    ... )
    >>>
    >>> # Check if a number is a false positive
    >>> number = NumberMatch(
    ...     start=10, end=14, raw_text="2023", value=Decimal("2023"), unit="count"
    ... )
    >>> text = "In 2023, we had 50,000 customers"
    >>> is_fp, reason = fp_filter.is_false_positive(number, text)
    >>> print(f"False positive: {is_fp}, Reason: {reason}")

Configuring Filter Behavior:
    >>> from src.review.config import CandidateGenerationConfig
    >>>
    >>> # Adjust filtering thresholds
    >>> config = CandidateGenerationConfig(
    ...     min_metric_value=100,    # Only keep numbers >= 100
    ...     filter_years=False,      # Don't filter year-like numbers
    ...     filter_false_positives=True,  # Keep other FP filtering
    ... )
    >>> generator = CandidateGenerator(config=config)
    >>> candidates = generator.generate_for_filing(
    ...     filing_id=123, company_id=456, segments=segments
    ... )

Disabling False Positive Filtering (high recall):
    >>> from src.review.config import get_high_recall_config
    >>>
    >>> # Disable all false positive filtering
    >>> config = get_high_recall_config()
    >>> generator = CandidateGenerator(config=config)
    >>> candidates = generator.generate_for_filing(
    ...     filing_id=123, company_id=456, segments=segments
    ... )
    >>> # Will include years, dates, page refs, small numbers

Understanding Filter Reasons:
    >>> # Filter returns tuple (is_false_positive: bool, reason: str)
    >>> # Possible reasons:
    >>> # - "year_value": Number in year range (1990-2100)
    >>> # - "small_value": Number below min_metric_value threshold
    >>> # - "date_context": Part of a date (12/31/2023)
    >>> # - "page_reference": Page number ("page 123")
    >>> # - "note_reference": Note reference ("Note 5")
    >>> # - "version_number": Version number ("Version 2.0")
    >>> # - "toc_proximity": Number near "Table of Contents" header
    >>> # - "toc_page_reference": Dot leader pattern (section name ... page number)
    >>> # - None: Not a false positive

See Also:
    - candidate_generator.py: Uses FalsePositiveFilter internally
    - config.py: Configure filtering parameters
    - number_parsing.py: NumberMatch data structure
"""

import logging
import re
from typing import List, Optional, Pattern, Tuple

from src.review.config import DEFAULT_CONFIG, MIN_METRIC_VALUE, YEAR_MIN, YEAR_MAX
from src.review.number_parsing import NumberMatch

logger = logging.getLogger(__name__)


# =============================================================================
# False Positive Detection Patterns
# =============================================================================

# Date patterns - to detect if a number is part of a date
DATE_CONTEXT_PATTERNS: List[Pattern[str]] = [
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
FALSE_POSITIVE_CONTEXT_PATTERNS: List[Pattern[str]] = [
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
# (imported from config.py for centralized configuration)
YEAR_MIN = YEAR_MIN
YEAR_MAX = YEAR_MAX

# Minimum value threshold - very small numbers are rarely metrics
# (imported from config.py for centralized configuration)
MIN_METRIC_VALUE = MIN_METRIC_VALUE  # Filter out single-digit numbers by default

# Table of Contents proximity threshold - distance to look for TOC header
TOC_PROXIMITY_CHARS = 300  # Characters before number to search for TOC header

# Dot leader pattern - indicates page number in table of contents
# Matches patterns like "... 12" or "........ 23" (3+ dots followed by optional whitespace at end)
TOC_DOT_LEADER_PATTERN = re.compile(r'\.{3,}\s*$')


# =============================================================================
# Helper Functions for Table of Contents Detection
# =============================================================================


def is_near_table_of_contents(text: str, number_position: int) -> bool:
    """
    Check if a number appears near a "Table of Contents" header.

    Numbers near TOC headers are almost always page numbers, not customer metrics.
    Searches backwards from the number position for TOC indicators.

    Args:
        text: The full text containing the number
        number_position: Starting position of the number in the text

    Returns:
        True if "table of contents" found within TOC_PROXIMITY_CHARS before number

    Examples:
        >>> text = "TABLE OF CONTENTS\\nRisk Factors ... 12"
        >>> is_near_table_of_contents(text, text.find("12"))
        True

        >>> text = "We had 12 million customers in the quarter"
        >>> is_near_table_of_contents(text, text.find("12"))
        False
    """
    # Look backwards from number position
    search_start = max(0, number_position - TOC_PROXIMITY_CHARS)
    search_text = text[search_start:number_position]

    # Case-insensitive search for "table of contents"
    return "table of contents" in search_text.lower()


def is_toc_page_reference(text: str, number_position: int) -> bool:
    """
    Check if a number is part of a TOC page reference with dot leaders.

    Detects patterns like:
    - "Business Overview.........1"
    - "Risk Factors ... 12"
    - "Item 1A. Risk Factors....23"

    Args:
        text: The full text containing the number
        number_position: Starting position of the number in the text

    Returns:
        True if dot leader pattern found immediately before the number

    Examples:
        >>> text = "Risk Factors.........12"
        >>> is_toc_page_reference(text, text.find("12"))
        True

        >>> text = "We had 12 million customers"
        >>> is_toc_page_reference(text, text.find("12"))
        False
    """
    # Look backwards from number position for dot leader pattern
    # Check up to 50 characters before the number (should be enough for dot leaders)
    search_start = max(0, number_position - 50)
    preceding_text = text[search_start:number_position]

    # Check if the preceding text ends with dot leaders
    return TOC_DOT_LEADER_PATTERN.search(preceding_text) is not None


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
        filter_enabled: bool = DEFAULT_CONFIG.filter_false_positives,
        min_value: float = DEFAULT_CONFIG.min_metric_value,
        filter_years: bool = DEFAULT_CONFIG.filter_years,
    ):
        """
        Initialize the false positive filter.

        Args:
            filter_enabled: Whether to apply filtering (default from config)
            min_value: Minimum value threshold for count units (default from config)
            filter_years: Whether to filter year-like values (default from config)
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
        - Numbers near "Table of Contents" headers
        - TOC page references with dot leaders (e.g., "Risk Factors...12")
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

        # Check if number appears near "Table of Contents" header
        if is_near_table_of_contents(text, start):
            return True, "toc_proximity"

        # Check if number is part of a TOC page reference with dot leaders
        if is_toc_page_reference(text, start):
            return True, "toc_page_reference"

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
