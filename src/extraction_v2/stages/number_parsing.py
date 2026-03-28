"""
Number parsing utilities for the V2 extraction pipeline.

Standalone module so the logic can be imported by any stage without pulling
in the full ValueBindingStage class.
"""

from __future__ import annotations

import logging
import re
from decimal import InvalidOperation

from src.extraction_v2.models import Unit

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Regex patterns
# ---------------------------------------------------------------------------

NUMBER_PATTERN = re.compile(
    r"""
    (?P<negative>-)?                    # Optional negative
    (?P<currency>[\$\€\£])?             # Optional currency symbol
    \s*
    (?P<number>
        \d{1,3}(?:,\d{3})+              # Comma-separated integer (requires at least one comma group)
        (?:\.\d+)?                       # Optional decimal
        |
        \d+(?:\.\d+)?                    # Plain number
    )
    \s*
    (?P<suffix>million|billion|thousand|mn|bn|k|m|b)?  # Scale suffix
    \s*
    (?P<percent>%|percent)?             # Percentage indicator
    """,
    re.IGNORECASE | re.VERBOSE,
)

# Table-level scale pattern: "(In thousands)", "(In millions)", etc.
TABLE_SCALE_PATTERN = re.compile(
    r"\(\s*(?:in|amounts?\s+in)\s+(thousands|millions|billions|hundreds)\b[^)]*\)",
    re.IGNORECASE,
)

# Pattern for "except as otherwise noted" / "except as noted" qualifiers
TABLE_SCALE_EXCEPT_PATTERN = re.compile(
    r"except\s+as\s+(?:otherwise\s+)?noted",
    re.IGNORECASE,
)

# ---------------------------------------------------------------------------
# Scale mapping constants
# ---------------------------------------------------------------------------

SCALE_MULTIPLIERS: dict[str, float] = {
    "thousand": 1_000,
    "k": 1_000,
    "million": 1_000_000,
    "mn": 1_000_000,
    "m": 1_000_000,
    "billion": 1_000_000_000,
    "bn": 1_000_000_000,
    "b": 1_000_000_000,
}

TABLE_SCALE_MAP: dict[str, float] = {
    "hundreds": 100,
    "thousands": 1_000,
    "millions": 1_000_000,
    "billions": 1_000_000_000,
}

# ---------------------------------------------------------------------------
# Functions
# ---------------------------------------------------------------------------


def parse_number(text: str) -> tuple[float, Unit, str] | None:
    """
    Parse a numeric value from text.

    Args:
        text: Text that may contain a number (e.g. "$1.2M", "112%", "50,000").

    Returns:
        Tuple of (value, unit, raw_text) or None if no parseable number found.
    """
    match = NUMBER_PATTERN.search(text)
    if not match:
        return None

    try:
        number_str = match.group("number")
        currency = match.group("currency")
        suffix = match.group("suffix")
        percent = match.group("percent")
        negative = match.group("negative")

        clean_number = number_str.replace(",", "")
        value = float(clean_number)

        if suffix:
            suffix_lower = suffix.lower()
            if suffix_lower in SCALE_MULTIPLIERS:
                value *= SCALE_MULTIPLIERS[suffix_lower]

        if negative:
            value = -value

        if percent:
            unit = Unit.PERCENT
        elif currency:
            unit = Unit.CURRENCY
        elif suffix or "," in number_str or "." in number_str:
            # Comma-separated integers, scaled values, or decimals → COUNT
            # (clearly-scaled quantities or structured numeric forms)
            unit = Unit.COUNT
        else:
            # Plain integers without comma/scale/decimal → OTHER
            # (ambiguous: could be currency amount or count in table context)
            unit = Unit.OTHER

        raw = match.group().strip()
        return (value, unit, raw)

    except (ValueError, InvalidOperation) as e:
        logger.debug(f"Could not parse number from '{text}': {e}")
        return None


def has_fractional_value(value_raw: str) -> bool:
    """Check if a raw value string contains a decimal point.

    Used to distinguish scaled counts (e.g. "796.3" in a "(in thousands)"
    table) from actual integer counts (e.g. "948").
    """
    return "." in value_raw
