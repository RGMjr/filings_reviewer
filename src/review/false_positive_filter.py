"""
False Positive Filter - Identify and filter out false positive number matches.

This module provides functionality to identify numbers that are unlikely to be
metrics, such as dates, years, page numbers, and other reference numbers.

Enhanced with temporal context patterns (2025-12-17) to improve date detection
in SEC filings by recognizing common temporal phrases like "as of", "ended",
"for the period ended", etc.

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
    >>> # - "likely_year": Number in year range (1990-2100) and 4-digit format
    >>> # - "below_min_value": Number below min_metric_value threshold
    >>> # - "part_of_date": Part of a date (e.g., "31" from "January 31, 2019")
    >>> # - "toc_proximity": Number near "Table of Contents" header
    >>> # - "toc_page_reference": Dot leader pattern (section name ... page number)
    >>> # - "reference_number": Matches FALSE_POSITIVE_CONTEXT_PATTERNS (page/note/section refs, TOC links)
    >>> # - None: Not a false positive
    >>> #
    >>> # Temporal phrases recognized (enhanced 2025-12-17):
    >>> # - "as of January 31, 2019"
    >>> # - "ended January 31, 2019"
    >>> # - "Year Ended January 31, 2019"
    >>> # - "Three Months Ended April 30, 2018"
    >>> # - "beginning January 31, 2019"

See Also:
    - candidate_generator.py: Uses FalsePositiveFilter internally
    - config.py: Configure filtering parameters
    - number_parsing.py: NumberMatch data structure
"""

import logging
import re
from re import Pattern

from src.review.config import DEFAULT_CONFIG, MIN_METRIC_VALUE, YEAR_MAX, YEAR_MIN
from src.review.number_parsing import SPELLED_NUMBER_REGEX, NumberMatch

logger = logging.getLogger(__name__)


# =============================================================================
# False Positive Detection Patterns
# =============================================================================

# Date patterns - to detect if a number is part of a date
DATE_CONTEXT_PATTERNS: list[Pattern[str]] = [
    # MM/DD/YYYY or DD/MM/YYYY
    re.compile(r"\d{1,2}/\d{1,2}/\d{2,4}"),
    # Month DD, YYYY
    re.compile(
        r"(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|"
        r"Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\.?,?\s+\d{1,2},?\s+\d{4}",
        re.IGNORECASE,
    ),
    # DD Month YYYY
    re.compile(
        r"\d{1,2}\s+(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|"
        r"Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\.?,?\s+\d{4}",
        re.IGNORECASE,
    ),
    # Temporal phrases with dates - "as of January 31, 2019"
    re.compile(
        r"\bas\s+of\s+(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|"
        r"Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\.?,?\s+\d{1,2},?\s+\d{4}",
        re.IGNORECASE,
    ),
    # "ended January 31, 2019"
    re.compile(
        r"\bended\s+(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|"
        r"Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\.?,?\s+\d{1,2},?\s+\d{4}",
        re.IGNORECASE,
    ),
    # "beginning January 31, 2019" or "beginning of period"
    re.compile(
        r"\bbeginning\s+(?:of\s+)?(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|"
        r"Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\.?,?\s+\d{1,2},?\s+\d{4}",
        re.IGNORECASE,
    ),
    # Fiscal year references - "Year Ended January 31, 2019"
    re.compile(
        r"\byear\s+ended\s+(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|"
        r"Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\.?,?\s+\d{1,2},?\s+\d{4}",
        re.IGNORECASE,
    ),
    # Quarter references - "Three Months Ended April 30, 2018"
    re.compile(
        r"\b(?:three|six|nine|twelve)\s+months\s+ended\s+(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|"
        r"Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\.?,?\s+\d{1,2},?\s+\d{4}",
        re.IGNORECASE,
    ),
    # DFP-1: Month DD without year - "January 31," in table headers
    # Matches: "January 31,", "June 30,", "Jul 31", "September 30" (with or without comma)
    # This catches day numbers from fiscal period headers that don't include a year
    re.compile(
        r"(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|"
        r"Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\.?,?\s+\d{1,2}\b",
        re.IGNORECASE,
    ),
]

# Patterns that indicate a number is NOT a metric (contextual false positives)
FALSE_POSITIVE_CONTEXT_PATTERNS: list[Pattern[str]] = [
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
    # Table of Contents references: "73 Table of Contents" (Issue 4 - standalone pattern)
    re.compile(r"\d+\s+(?:table\s+of\s+contents|toc)\b", re.IGNORECASE),
    # Measurement unit patterns (EI-2) - numbers within time units are not metrics
    # Matches: "24-hour", "30-day", "7 days", "12-month", "90-second"
    # These describe measurement timeframes, not actual metric values
    re.compile(r"\b\d+[-\s]?(?:hour|day|week|month|year|period|quarter)s?\b", re.IGNORECASE),
    re.compile(r"\b\d+[-\s]?(?:minute|second)s?\b", re.IGNORECASE),
    # Spelled-out temporal references: "twelve months", "twenty-four months"
    re.compile(
        r"\b(?:ten|eleven|twelve|thirteen|fourteen|fifteen|sixteen|seventeen|eighteen|"
        r"nineteen|"
        r"(?:twenty|thirty|forty|fifty|sixty|seventy|eighty|ninety)"
        r"(?:[-\s]+(?:one|two|three|four|five|six|seven|eight|nine))?"
        r")\s*[-\s]?\s*"
        r"(?:month|year|day|week|hour|minute|second|quarter|period)s?\b",
        re.IGNORECASE,
    ),
    # Fortune/Forbes list references: "65 of the Fortune 100", "companies in the Fortune 500"
    # Two patterns: leading-count ("65 of the Fortune 100") and rank-only ("Fortune 500")
    # Note: "Inc." deliberately excluded — it is a company name suffix, not a magazine reference.
    re.compile(
        r"\b\d+\s+(?:of\s+the\s+|companies?\s+in\s+the\s+)?(?:Fortune|Forbes)\s+\d+",
        re.IGNORECASE,
    ),
    re.compile(r"\b(?:Fortune|Forbes)\s+\d+", re.IGNORECASE),
    # Negative customer concentration assertions — "no customer exceeded 10%"
    # Patterns extend through the threshold number so the overlap check fires only on that number.
    # Example: "No single customer represented more than 10%" → filters "10", not nearby metrics.
    re.compile(
        r"\bno\s+(?:single\s+|individual\s+)?(?:customer|client|user|account)"
        r"\s+(?:\w+\s+){0,4}"
        r"(?:exceeded|represented|amounted(?:\s+for)?|accounted\s+for|comprised)"
        r"\s+(?:more\s+than\s+|less\s+than\s+|at\s+least\s+)?"
        r"(?:\w+\s+){0,2}"
        r"\d+(?:\.\d+)?",
        re.IGNORECASE,
    ),
    re.compile(
        r"\bnone\s+of\s+(?:our\s+)?(?:customers|clients|users|accounts)"
        r"\s+(?:\w+\s+){0,4}"
        r"(?:accounted\s+for|represented|exceeded)"
        r"\s+(?:more\s+than\s+|less\s+than\s+|at\s+least\s+)?"
        r"(?:\w+\s+){0,2}"
        r"\d+(?:\.\d+)?",
        re.IGNORECASE,
    ),
]

# Label-embedded value pattern (CMS-2)
# Detects numbers that are part of metric label thresholds, not actual values.
# Example: "Paid Customers > $100,000" - the $100,000 is part of the label, not a value.
# Matches patterns like:
#   - "> $100,000" or ">= $50M" (comparison + currency + number)
#   - "< 1000" or "<= 500" (comparison + number without currency)
#   - "≥ $100K" or "≤ $1 million" (unicode operators)
LABEL_EMBEDDED_VALUE_PATTERN: Pattern[str] = re.compile(
    r"(?:>=?|<=?|≥|≤)\s*"  # Comparison operator (>, >=, <, <=, ≥, ≤)
    r"\$?\s*"  # Optional currency symbol
    r"\d[\d,]*"  # Number (with optional commas)
    r"(?:\.\d+)?"  # Optional decimal
    r"(?:\s*(?:thousand|million|billion|mn|bn|[KMB]))?"  # Optional magnitude suffix
    r"\b",
    re.IGNORECASE,
)

# Ambiguous magnitude suffix pattern
# Detects "375 b", "610 b" etc. where a space precedes a single-letter suffix.
# Real magnitude suffixes are typically attached ("375B", "$610M") or spelled out
# ("375 billion"). A space + single letter usually means a column label or footnote.
AMBIGUOUS_MAGNITUDE_SUFFIX: Pattern[str] = re.compile(
    r"^\d[\d,]*\s+[bmkBMK]$"
)

# Year range - numbers in this range are likely years, not metrics
# (imported from config.py for centralized configuration)
YEAR_MIN = YEAR_MIN
YEAR_MAX = YEAR_MAX

# Minimum value threshold - very small numbers are rarely metrics
# (imported from config.py for centralized configuration)
MIN_METRIC_VALUE = MIN_METRIC_VALUE  # Filter out single-digit numbers by default

# Table of Contents proximity threshold - distance to look for TOC header
# (L2 enhancement - configurable via CandidateGenerationConfig)
TOC_PROXIMITY_CHARS = 300  # Characters before number to search for TOC header

# Dot leader window - distance to search for dot leader pattern
# (L2 enhancement - configurable via CandidateGenerationConfig)
TOC_DOT_LEADER_WINDOW = 50  # Characters before number to search for dot leaders

# Table of Contents header variations to recognize
# (L2 enhancement - handles multiple TOC formats in real filings)
TOC_HEADERS = [
    "table of contents",
    "contents",
    "index",
    "index to financial statements",
    "index to consolidated financial statements",
]

# Dot leader pattern - indicates page number in table of contents
# Matches patterns like "... 12" or "........ 23" (3+ dots followed by optional whitespace)
# Updated to handle whitespace before number more flexibly
TOC_DOT_LEADER_PATTERN = re.compile(r'\.{3,}\s*$')


# =============================================================================
# HRV-10: Financial Statement Context Detection (2025-12-26)
# =============================================================================

# Financial statement header patterns
FINANCIAL_STATEMENT_HEADERS: list[Pattern[str]] = [
    # Income statement / P&L variations
    re.compile(r'\bconsolidated\s+statements?\s+of\s+(?:operations|income)', re.IGNORECASE),
    re.compile(r'\bincome\s+statements?', re.IGNORECASE),
    re.compile(r'\bstatements?\s+of\s+(?:operations|earnings|income)', re.IGNORECASE),
    re.compile(r'\bconsolidated\s+results?\s+of\s+operations', re.IGNORECASE),

    # Balance sheet variations
    re.compile(r'\bconsolidated\s+balance\s+sheets?', re.IGNORECASE),
    re.compile(r'\bstatements?\s+of\s+financial\s+position', re.IGNORECASE),
    re.compile(r'\bbalance\s+sheet\s+data', re.IGNORECASE),

    # Cash flow statement variations
    re.compile(r'\bconsolidated\s+statements?\s+of\s+cash\s+flows?', re.IGNORECASE),
    re.compile(r'\bstatements?\s+of\s+cash\s+flows?', re.IGNORECASE),

    # Summary financial data tables
    re.compile(r'\bsummary\s+(?:consolidated\s+)?(?:financial|operating)\s+data', re.IGNORECASE),
    re.compile(r'\bselected\s+financial\s+data', re.IGNORECASE),
]

# Financial statement line item keywords that should NOT be treated as customer metrics
FINANCIAL_LINE_ITEM_KEYWORDS: list[str] = [
    # Income statement line items
    'revenue', 'total revenue', 'net revenue', 'revenues',
    'cost of revenue', 'cost of sales', 'cost of goods sold', 'cogs',
    'gross profit', 'gross income',
    'operating expenses', 'operating income', 'operating loss',
    'research and development', 'r&d expenses',
    'sales and marketing', 'general and administrative',
    'net income', 'net loss', 'net earnings',
    'income from operations', 'loss from operations',
    'earnings per share', 'eps', 'diluted eps', 'basic eps',

    # Balance sheet line items
    'total assets', 'current assets', 'non-current assets',
    'cash and cash equivalents', 'cash equivalents', 'marketable securities',
    'accounts receivable', 'inventory', 'prepaid expenses',
    'property and equipment', 'intangible assets', 'goodwill',
    'total liabilities', 'current liabilities', 'long-term liabilities',
    'accounts payable', 'accrued expenses', 'accrued liabilities',
    'deferred revenue', 'unearned revenue',
    'working capital',
    'stockholders equity', 'shareholders equity', 'total equity',

    # Cash flow line items
    'cash flows from operating activities',
    'cash flows from investing activities',
    'cash flows from financing activities',
    'free cash flow', 'operating cash flow',

    # Common financial ratios and changes
    '$ change', '% change', 'percent change',
    'increase', 'decrease',
]

# Proximity threshold for financial statement context (characters)
FINANCIAL_STATEMENT_PROXIMITY_CHARS = 500


# =============================================================================
# Metric Type Validation (HRV Type Validation Enhancement - 2025-12-26)
# =============================================================================

# Metrics that should ONLY be percentages (not raw counts or dollar amounts)
PERCENTAGE_ONLY_METRICS: set[str] = {
    'cm_net_revenue_retention',  # NDR should be 143%, not 143 or $143
    'cm_gross_retention_rate',
    'cm_customer_retention_rate',
    'cm_customer_churn_rate',
    'cm_ltv_cac_ratio',  # Ratio, expect decimal or %
}

# Metrics that should ONLY be dollar amounts (not percentages or plain counts)
DOLLAR_ONLY_METRICS: set[str] = {
    'cm_arr',  # ARR should be $X million, not 40% or 100
    'cm_mrr',  # MRR should be $X million, not 40% or 100
    'cm_tcv',  # Total contract value
    'cm_acv',  # Annual contract value
    'cm_ltv',  # Lifetime value
    'cm_cac',  # Customer acquisition cost
    'cm_arpu',  # Average revenue per user
    'cm_gmv',  # GMV is monetary; percentages are growth rates not values
    'cm_average_order_value',  # AOV is monetary; "31.7%" is a growth rate not an AOV
}

# Metrics that should ONLY be counts (not percentages or dollars)
COUNT_ONLY_METRICS: set[str] = {
    'cm_customer',  # Customer count
    'cm_daily_active_users',  # DAU count
    'cm_weekly_active_users',  # WAU count
    'cm_monthly_active_users',  # MAU count
    'cm_paid_users',
    'cm_subscribers',
    # Customer count metrics (added 2026-01-07 - were missing, causing % false matches)
    'cm_customers_period_end',
    'cm_active_customers_total',
    'cm_large_customers_period_end',
    'cm_new_customers_acquired',
    # Transaction count (added 2026-03-19 - % and $ values are gross margin/take rates, not order counts)
    'cm_purchase_transactions_overall',
}


def is_spelled_out_number(raw_text: str) -> bool:
    """
    Check if a number text is spelled out rather than numeric.

    Spelled-out numbers (e.g., "six", "twenty-one", "five million") are
    intentionally written and unlikely to be page numbers or false positives.

    Args:
        raw_text: The raw text of the number match

    Returns:
        True if the number contains no digits (is spelled out)

    Examples:
        >>> is_spelled_out_number("six")
        True
        >>> is_spelled_out_number("twenty-one")
        True
        >>> is_spelled_out_number("123")
        False
        >>> is_spelled_out_number("$50,000")
        False
    """
    return not any(c.isdigit() for c in raw_text)


def is_percentage_format(raw_text: str, unit: str) -> bool:
    """Check if a number is in percentage format.

    Also accepts decimal ratios (0.5 to 2.5 range) as valid percentage representations,
    since metrics like NRR are often expressed as decimals (e.g., 1.25 = 125%).
    """
    # Explicit percentage format
    if '%' in raw_text or unit == 'percentage':
        return True

    # Decimal ratio format (common for retention rates like 1.25 = 125%)
    # Accept values in 0.5 to 2.5 range with decimal point
    # BUT skip if raw_text contains a scale suffix (e.g. "1.4 million" is NOT a ratio)
    if '.' in raw_text and unit == 'count':
        if not re.search(r'(?:million|billion|thousand|mn|bn)', raw_text, re.IGNORECASE):
            try:
                # Remove any non-numeric chars except decimal point
                cleaned = ''.join(c for c in raw_text if c.isdigit() or c == '.')
                val = float(cleaned)
                # Retention rates typically 0.5 (50%) to 2.0 (200%)
                if 0.5 <= val <= 2.5:
                    return True
            except (ValueError, TypeError):
                pass

    return False


def should_treat_as_percentage(metric_id: str, raw_text: str, unit: str, context_text: str | None = None) -> bool:
    """
    Context-based percentage detection for retention metrics.

    FIX-A: Handles cases where retention percentages are extracted as plain numbers
    (e.g., "138" instead of "138%"). When a retention metric has retention context,
    treat the value as a percentage even without the % symbol.

    Args:
        metric_id: The metric identifier (e.g., 'cm_net_revenue_retention')
        raw_text: The raw text of the number match
        unit: The parsed unit (e.g., 'count', 'percentage', 'currency')
        context_text: Optional context text around the number

    Returns:
        True if the value should be treated as a percentage

    Examples:
        >>> # Explicit percentage
        >>> should_treat_as_percentage('cm_net_revenue_retention', '138%', 'percentage')
        True

        >>> # Plain number with retention context
        >>> should_treat_as_percentage('cm_net_revenue_retention', '138', 'count', 'net revenue retention of 138')
        True

        >>> # Plain number without retention context
        >>> should_treat_as_percentage('cm_net_revenue_retention', '138', 'count', 'customers of 138')
        False
    """
    # First check explicit percentage format
    if is_percentage_format(raw_text, unit):
        return True

    # FIX-A: Retention metrics with retention context are percentages
    # This handles values like "138" that should be "138%" in retention contexts
    if metric_id in {'cm_net_revenue_retention', 'cm_gross_revenue_retention', 'cm_gross_retention_rate'}:
        if context_text:
            context_lower = context_text.lower()
            # Check for retention-related keywords in context
            retention_keywords = [
                'retention', 'retained', 'churn', 'renewal', 'renewals',
                'net dollar retention', 'ndr', 'net revenue retention', 'nrr',
                'gross retention', 'grr', 'dollar-based net expansion'
            ]
            if any(keyword in context_lower for keyword in retention_keywords):
                return True

    return False


def is_dollar_format(raw_text: str, unit: str) -> bool:
    """Check if a number is in dollar format."""
    return '$' in raw_text or unit in ('currency', 'usd')


def is_count_format(raw_text: str, unit: str) -> bool:
    """Check if a number is a plain count (not percentage or dollar)."""
    return unit == 'count' and '%' not in raw_text and '$' not in raw_text


# =============================================================================
# Helper Functions for Financial Statement Detection (HRV-10)
# =============================================================================


def is_in_financial_statement_context(
    text: str,
    number_position: int,
    proximity_chars: int = FINANCIAL_STATEMENT_PROXIMITY_CHARS
) -> bool:
    """
    Check if a number appears within a financial statement context.

    Financial statements (income statement, balance sheet, cash flow statement)
    contain many numbers that are financial accounting line items, not customer
    metrics. This function detects financial statement headers to identify
    such contexts.

    Recognizes multiple financial statement variations:
    - "Consolidated Statements of Operations"
    - "Income Statement"
    - "Consolidated Balance Sheets"
    - "Statements of Cash Flows"
    - "Summary Financial Data"

    Args:
        text: The full text containing the number
        number_position: Starting position of the number in the text
        proximity_chars: Character distance to search backwards (default: 500)

    Returns:
        True if any financial statement header found within proximity_chars before number

    Examples:
        >>> text = "CONSOLIDATED STATEMENTS OF OPERATIONS\\nRevenue $400,552"
        >>> is_in_financial_statement_context(text, text.find("400,552"))
        True

        >>> text = "We had 400,552 daily active users"
        >>> is_in_financial_statement_context(text, text.find("400,552"))
        False
    """
    # Look backwards from number position
    search_start = max(0, number_position - proximity_chars)
    search_text = text[search_start:number_position]

    # Check for any financial statement header pattern
    return any(pattern.search(search_text) for pattern in FINANCIAL_STATEMENT_HEADERS)


def contains_financial_line_item_keyword(text: str) -> str | None:
    """
    Check if text contains financial statement line item keywords.

    These keywords indicate financial accounting line items (Revenue, Cost of
    Revenue, Total Assets, etc.) which should not be treated as customer metrics,
    even though terms like "revenue" might appear in customer metric keyword lists.

    Args:
        text: Text to search (typically context text around a number)

    Returns:
        The matching keyword if found (lowercase), None otherwise

    Examples:
        >>> contains_financial_line_item_keyword("Revenue [CELL] $400,552")
        'revenue'

        >>> contains_financial_line_item_keyword("Total assets $1,198,956")
        'total assets'

        >>> contains_financial_line_item_keyword("Daily active users: 10 million")
        None
    """
    text_lower = text.lower()

    # Check for line item keywords (longest first to match "total revenue" before "revenue")
    # Sort by length descending
    sorted_keywords = sorted(FINANCIAL_LINE_ITEM_KEYWORDS, key=len, reverse=True)

    for keyword in sorted_keywords:
        if keyword in text_lower:
            return keyword

    return None


# =============================================================================
# Helper Functions for Table of Contents Detection
# =============================================================================


def is_near_table_of_contents(
    text: str,
    number_position: int,
    proximity_chars: int = TOC_PROXIMITY_CHARS
) -> bool:
    """
    Check if a number appears near a "Table of Contents" header.

    Numbers near TOC headers are almost always page numbers, not customer metrics.
    Searches backwards from the number position for TOC indicators.

    Recognizes multiple TOC header variations:
    - "Table of Contents"
    - "Contents"
    - "Index"
    - "Index to Financial Statements"
    - "Index to Consolidated Financial Statements"

    Args:
        text: The full text containing the number
        number_position: Starting position of the number in the text
        proximity_chars: Character distance to search backwards (default: TOC_PROXIMITY_CHARS)

    Returns:
        True if any TOC header found within proximity_chars before number

    Examples:
        >>> text = "TABLE OF CONTENTS\\nRisk Factors ... 12"
        >>> is_near_table_of_contents(text, text.find("12"))
        True

        >>> text = "INDEX\\nBusiness Overview ... 5"
        >>> is_near_table_of_contents(text, text.find("5"))
        True

        >>> text = "We had 12 million customers in the quarter"
        >>> is_near_table_of_contents(text, text.find("12"))
        False
    """
    # Look backwards from number position
    search_start = max(0, number_position - proximity_chars)
    search_text = text[search_start:number_position].lower()

    # Check for any TOC header variation (case-insensitive)
    return any(header in search_text for header in TOC_HEADERS)


def is_toc_page_reference(
    text: str,
    number_position: int,
    window_chars: int = TOC_DOT_LEADER_WINDOW
) -> bool:
    """
    Check if a number is part of a TOC page reference with dot leaders.

    Detects patterns like:
    - "Business Overview.........1"
    - "Risk Factors ... 12"
    - "Item 1A. Risk Factors....23"

    L2-P1.1 Enhancement: Context-aware detection to prevent false positives
    from narrative ellipsis (e.g., "We expect...12 million customers").

    Now requires BOTH dot leaders AND TOC context (either header proximity
    or section heading pattern) to avoid filtering valid metrics.

    Args:
        text: The full text containing the number
        number_position: Starting position of the number in the text
        window_chars: Character distance to search backwards (default: TOC_DOT_LEADER_WINDOW)

    Returns:
        True if dot leader pattern found AND TOC context detected

    Examples:
        >>> text = "Risk Factors.........12"
        >>> is_toc_page_reference(text, text.find("12"))
        True

        >>> text = "We had 12 million customers"
        >>> is_toc_page_reference(text, text.find("12"))
        False

        >>> text = "We expect...12 million customers"  # Narrative ellipsis
        >>> is_toc_page_reference(text, text.find("12"))
        False  # No TOC context, not filtered
    """
    # Look backwards from number position for dot leader pattern
    search_start = max(0, number_position - window_chars)
    preceding_text = text[search_start:number_position]

    # First check: Must have dot leader pattern (3+ dots)
    if not TOC_DOT_LEADER_PATTERN.search(preceding_text):
        return False

    # L2-P1.1: Require TOC context to avoid narrative ellipsis false positives

    # Context check 1: TOC header within 200 chars (tighter than default 300)
    # This catches most genuine TOC entries
    if is_near_table_of_contents(text, number_position, proximity_chars=200):
        return True

    # Context check 2: TOC-like section heading pattern
    # Matches: "Item 1A.", "Part II", "Section 3", "Chapter 5"
    # Look for these patterns anywhere in the preceding text (not just at end)
    section_heading_pattern = re.compile(
        r'(?:Item|Part|Section|Chapter)\s+[IVX0-9]+[A-Z]?\b',
        re.IGNORECASE
    )
    if section_heading_pattern.search(preceding_text):
        return True

    # Has dot leaders but no TOC context - likely narrative ellipsis
    return False


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
    - Numbers near Table of Contents sections (L2 enhancement)
    - TOC page references with dot leaders (L2 enhancement)
    - Numbers near "Table of Contents" links (Issue 4 enhancement)
    """

    def __init__(
        self,
        filter_enabled: bool = DEFAULT_CONFIG.filter_false_positives,
        min_value: float = DEFAULT_CONFIG.min_metric_value,
        filter_years: bool = DEFAULT_CONFIG.filter_years,
        toc_proximity_chars: int = DEFAULT_CONFIG.toc_proximity_chars,
        toc_dot_leader_window: int = DEFAULT_CONFIG.toc_dot_leader_window,
        filter_financial_statements: bool = True,  # HRV-10/HRV-11
        financial_statement_proximity_chars: int = FINANCIAL_STATEMENT_PROXIMITY_CHARS,
    ):
        """
        Initialize the false positive filter.

        Args:
            filter_enabled: Whether to apply filtering (default from config)
            min_value: Minimum value threshold for count units (default from config)
            filter_years: Whether to filter year-like values (default from config)
            toc_proximity_chars: TOC header proximity threshold (default from config, L2)
            toc_dot_leader_window: Dot leader search window (default from config, L2)
            filter_financial_statements: Whether to filter financial statement line items (HRV-10/11)
            financial_statement_proximity_chars: Financial statement header proximity threshold (HRV-10)
        """
        self.filter_enabled = filter_enabled
        self.min_value = min_value
        self.filter_years = filter_years
        self.toc_proximity_chars = toc_proximity_chars
        self.toc_dot_leader_window = toc_dot_leader_window
        self.filter_financial_statements = filter_financial_statements
        self.financial_statement_proximity_chars = financial_statement_proximity_chars

    def is_false_positive(
        self, text: str, number: NumberMatch
    ) -> tuple[bool, str | None]:
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
        # Note: Spelled-out numbers ("three", "one") are no longer exempted because
        # bare spelled-out words below min_value are almost always narrative noise
        # (e.g., "three main factors"), while meaningful ones ("six million") have
        # values far above min_value after magnitude parsing.
        if number.unit == "count" and value is not None:
            is_decimal = "." in number.raw_text
            if not is_decimal and abs(float(value)) < self.min_value:
                return True, "below_min_value"

        # Check for ambiguous magnitude suffix (e.g., "375 b", "610 b")
        # A space before a single-letter suffix usually means a column label, not "billion"
        if AMBIGUOUS_MAGNITUDE_SUFFIX.match(number.raw_text.strip()):
            return True, "ambiguous_magnitude_suffix"

        # Check if spelled-out single-digit number lacks a magnitude word.
        # Bare "three", "one", "four" (values 1-9) are ordinals/qualifiers in
        # SEC filings and should not be treated as metric counts.
        # Scope: only single-digit word-numbers (value ≤ 9) to avoid blocking
        # legitimate small counts like "fourteen customers" or "forty-one enterprises".
        # Larger word-numbers with magnitude ("six million") are allowed by the
        # magnitude group check. "twelve" in definition text is handled by Fix D.
        spelled_match = SPELLED_NUMBER_REGEX.search(number.raw_text)
        if (
            spelled_match
            and spelled_match.group("magnitude") is None
            and value is not None
            and float(value) <= 9
        ):
            return True, "spelled_out_no_magnitude"

        # Check if number looks like a year (only for plain integers)
        if self.filter_years and number.unit == "count":
            if value is not None and YEAR_MIN <= float(value) <= YEAR_MAX:
                # Additional check: is it a 4-digit integer without decimal?
                if "." not in number.raw_text and len(number.raw_text.replace(",", "")) == 4:
                    return True, "likely_year"

        # Check if number appears near "Table of Contents" header
        # Only filter if it looks like a page number (small integer, no currency/decimals)
        # Real metrics (e.g. "31.0 million") often appear on pages with TOC headers
        # Spelled-out numbers (e.g., "six", "twenty") are unlikely to be page numbers
        is_plain_count = number.unit == "count"
        is_integer_format = "." not in number.raw_text
        is_small_value = value is not None and abs(float(value)) < 1000

        if is_plain_count and is_integer_format and is_small_value:
            if is_near_table_of_contents(text, start, self.toc_proximity_chars):
                logger.debug(
                    f"TOC proximity filter: number={number.raw_text} "
                    f"context={text[max(0, start-30):min(len(text), end+30)]!r}"
                )
                return True, "toc_proximity"

        # Check if number is part of a TOC page reference with dot leaders
        if is_toc_page_reference(text, start, self.toc_dot_leader_window):
            logger.debug(
                f"TOC dot leader filter: number={number.raw_text} "
                f"context={text[max(0, start-30):min(len(text), end+30)]!r}"
            )
            return True, "toc_page_reference"

        # Check if number is part of a date pattern
        # Look at surrounding context (100 chars each side to catch longer phrases)
        context_start = max(0, start - 100)
        context_end = min(len(text), end + 100)
        local_context = text[context_start:context_end]

        # Calculate the number's position relative to the local context
        num_rel_start = start - context_start
        num_rel_end = end - context_start

        for pattern in DATE_CONTEXT_PATTERNS:
            # FIX: Use finditer to check ALL matches in the context, not just the first one
            for match in pattern.finditer(local_context):
                # Check if our number overlaps with the date match (in local coords)
                if num_rel_start >= match.start() and num_rel_end <= match.end():
                    return True, "part_of_date"

        # Check for false positive context patterns (page refs, notes, etc.)
        for pattern in FALSE_POSITIVE_CONTEXT_PATTERNS:
            # FIX: Use finditer to check ALL matches inside the context
            for match in pattern.finditer(local_context):
                # Check if our number overlaps with the reference pattern
                if num_rel_start >= match.start() and num_rel_end <= match.end():
                    return True, "reference_number"

        # CMS-2: Check if number is part of a metric label threshold
        # Example: "Paid Customers > $100,000" - the $100,000 is label-embedded
        # Look for comparison operator immediately before the number
        if self._is_label_embedded_value(text, number):
            logger.debug(
                f"Label-embedded value filter: number={number.raw_text} "
                f"context={text[max(0, start-30):min(len(text), end+10)]!r}"
            )
            return True, "label_embedded_value"

        # HRV-11: Check if number appears in financial statement context
        if self.filter_financial_statements:
            # First check: Is this within a financial statement section?
            in_fin_statement = is_in_financial_statement_context(
                text, start, self.financial_statement_proximity_chars
            )

            if in_fin_statement:
                # Second check: Does the local context contain financial line item keywords?
                financial_keyword = contains_financial_line_item_keyword(local_context)

                if financial_keyword:
                    logger.debug(
                        f"Financial statement filter: number={number.raw_text} "
                        f"keyword={financial_keyword!r} "
                        f"context={text[max(0, start-50):min(len(text), end+50)]!r}"
                    )
                    return True, f"financial_line_item:{financial_keyword}"

        return False, None

    def _is_label_embedded_value(
        self, text: str, number: NumberMatch, window_chars: int = 20
    ) -> bool:
        """
        Check if a number is part of a metric label threshold pattern.

        Detects patterns like:
        - "Customers > $100,000" - the $100,000 is label-embedded
        - "ARR >= $50M" - the $50M is label-embedded
        - "Paid Customers > $100K" - part of a threshold label

        Args:
            text: Full text containing the number
            number: The NumberMatch to check
            window_chars: Characters before number to search for operator

        Returns:
            True if number appears to be part of a comparison pattern
        """
        # Look at text before the number (with some buffer)
        search_start = max(0, number.start - window_chars)

        # Include the number itself since pattern needs to match both operator and number
        search_text = text[search_start : number.end]

        # Check if pattern matches and includes our number
        match = LABEL_EMBEDDED_VALUE_PATTERN.search(search_text)
        if match:
            # Verify the pattern ends at or after our number position
            # (relative to search_text)
            num_rel_end = number.end - search_start
            if match.end() >= num_rel_end - 2:  # Allow small tolerance
                return True

        return False
