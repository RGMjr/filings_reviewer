# GPT-4 Code Review: D2 Extraction Quality

**Copy this entire prompt and paste into GPT-4 (or GPT-4o)**

---

You are a senior software engineer reviewing the extraction quality of a system that pulls customer metrics from SEC filings.

## Project Context

- Extracts 45+ customer metrics (retention, churn, ARR, cohort data, etc.)
- **Current Performance**: Precision 91%, Recall 85%, F1 88%
- Pipeline: HTML parsing → keyword matching → value extraction → quality scoring
- Uses LLM (GPT-4o-mini) as fallback when rule-based extraction fails

## Static Analysis - Extraction Complexity

| Function | CC | File | Issue |
|----------|-----|------|-------|
| `_process_segment` | 57 | candidate_generator.py:481 | Core matching logic |
| `find_keywords_near_number` | 46 | keyword_matching.py:523 | Proximity matching |
| `_parse_table_row` | 34 | value_extractor.py:1179 | Table parsing |
| `is_false_positive` | 32 | false_positive_filter.py:722 | FP detection |

**Coverage Gap**: value_extractor.py has only 66% test coverage (critical module)

## Code to Review

### 1. Core Segment Processing (CC=57)
```python
# src/review/candidate_generator.py:481
def _process_segment(self, segment: Segment) -> List[ReviewCandidate]:
    """
    8 sequential phases:
    1. Extract numbers from text
    2. Find keywords near each number
    3. Check same-row constraint (tables)
    4. Apply false positive filters
    5. Extract context window
    6. Deduplicate by (position, metric_id)
    7. Score confidence
    8. Create ReviewCandidate objects
    """
    candidates = []
    numbers = self._extract_numbers(segment.text)  # Regex

    for num in numbers:
        keywords = self._find_keywords_near(num, segment.text)
        for kw in keywords:
            if self._is_same_row(num, kw, segment):  # Table check
                if not self._is_false_positive(num, kw, segment):
                    context = self._extract_context(num, segment)
                    # ... 200+ more lines of logic
```

### 2. Keyword Proximity Matching (CC=46)
```python
# src/review/keyword_matching.py:523
def find_keywords_near_number(
    self,
    number_position: int,
    text: str,
    max_distance: int = 100
) -> List[KeywordMatch]:
    """
    Search for metric keywords within max_distance chars of number.
    Handles:
    - Multiple keyword patterns per metric (45+ metrics)
    - Specific vs general patterns (confidence bonus)
    - Exclusion patterns (reject false matches)
    - Required context patterns (cohort, per-customer)
    """
```

### 3. Table Row Position Estimation
```python
# src/review/table_structure.py
def _find_row_boundaries(self, html: str, text: str) -> List[RowBoundary]:
    """
    Map character positions in extracted text back to HTML table rows.

    3-level fallback:
    1. Exact substring match
    2. Flexible whitespace match
    3. Approximate match (first few words)  # RISKY

    If boundaries wrong, can cause:
    - Cross-row false positives (matching keyword from different row)
    - Missed valid matches (false negatives)
    """
```

### 4. False Positive Filter Rules
```python
# src/review/false_positive_filter.py:722
def is_false_positive(self, number: ParsedNumber, keyword: str, segment: Segment) -> bool:
    """
    Multiple overlapping rules:
    - Date patterns (10 regex)
    - Reference patterns (page, note, section - 15 regex)
    - Year detection (1990-2100)
    - TOC proximity (within 50 chars)
    - Format validation (count vs $ vs %)
    - Min value threshold (default 10)
    - Label-embedded filtering ("Customers > $100K")
    """
```

### 5. LLM Metric Name Mapping (170+ entries)
```python
# src/extraction/value_extractor.py
METRIC_NAME_MAPPING = {
    "new customers": "cm_new_customers_acquired",
    "customers acquired": "cm_new_customers_acquired",
    "total customers": "cm_customers_period_end",
    "paid customers": "cm_customers_period_end",
    "active users": "cm_active_customers_total",
    # ... 170+ more entries
    # Manually maintained, no validation
}
```

### 6. Keyword Configuration (YAML)
```yaml
# config/metric_keywords.yaml (545 lines)
cm_new_customers_acquired:
  patterns:
    - '\bnew\s+customers?\b'
    - '\bcustomers?\s+acquired\b'
  exclusions:
    - '\bacquisition\s+cost\b'  # Avoid CAC confusion
  specific_patterns:
    - '\bnew\s+paid\s+customers\b'  # Higher confidence
```

## Review Questions

1. **False Positive Root Causes**: What patterns cause the 9% false positive rate?
2. **False Negative Gaps**: Why are 15% of valid metrics missed?
3. **Table Row Estimation**: Is the approximate matching fallback safe?
4. **LLM Mapping Maintainability**: 170+ manual entries - sustainable?
5. **Exclusion Completeness**: Are exclusion patterns comprehensive?
6. **Complexity**: Should CC=57 `_process_segment` be decomposed?

## Output Format

```json
{
  "dimension": "D2_EXTRACTION",
  "model": "gpt4",
  "findings": [
    {
      "id": "G-D2-001",
      "severity": "Critical|High|Medium|Low",
      "category": "extraction",
      "title": "Short title",
      "description": "Detailed description with specific patterns/code",
      "file": "path/to/file.py",
      "line_range": "100-150",
      "impact_on_metrics": "Affects precision/recall/F1 by...",
      "recommendation": "What to do",
      "effort": "XS|S|M|L|XL"
    }
  ],
  "summary": "Overall extraction quality assessment"
}
```

Provide 10-15 findings focusing on extraction accuracy improvements.


---

# ACTUAL SOURCE CODE

## src/extraction/value_extractor.py

```python
"""
Value Extractor - Extract numeric metric values from segments.

This module extracts quantitative metric values from classified segments,
particularly focusing on table data with cohort breakdowns.
"""

import difflib
import html
import logging
import re
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import TYPE_CHECKING, Optional

from bs4 import BeautifulSoup

from ..review.false_positive_filter import FalsePositiveFilter
from ..review.number_parsing import NumberMatch
from ..review.table_structure import TableRowParser
from .models import MetricValue, SourceSegment

if TYPE_CHECKING:
    from ..llm.openai_client import OpenAIClient

logger = logging.getLogger(__name__)

# Quote verification constants
DEFAULT_SIMILARITY_THRESHOLD = 0.7  # Minimum similarity ratio for fuzzy matching
WINDOW_SIZE_MULTIPLIER = 1.3  # Window size = quote length * this multiplier
STRIDE_DIVISOR = 10  # Sample every quote_len / this value positions


# Mapping from LLM-returned metric names to canonical metric IDs
# The LLM returns free-form names; we need to map them to our taxonomy
METRIC_NAME_MAPPING = {
    # Core metrics
    "new_customers_acquired": "cm_new_customers_acquired",
    "new_customers": "cm_new_customers_acquired",
    "customer_acquisition": "cm_new_customers_acquired",
    "customers_acquired": "cm_new_customers_acquired",
    "new_customer_additions": "cm_new_customers_acquired",

    "customers_by_tenure": "cm_customers_period_end_by_tenure",
    "customer_count_by_tenure": "cm_customers_period_end_by_tenure",
    "customer_cohort_count": "cm_customers_period_end_by_tenure",

    "revenue_by_cohort": "cm_revenue_by_cohort",
    "cohort_revenue": "cm_revenue_by_cohort",
    "revenue_by_customer_cohort": "cm_revenue_by_cohort",

    "transactions_by_cohort": "cm_transactions_by_cohort",
    "purchases_by_cohort": "cm_transactions_by_cohort",
    "orders_by_cohort": "cm_transactions_by_cohort",

    # Extended metrics - customer counts
    "active_customers": "cm_active_customers_total",
    "active_customers_total": "cm_active_customers_total",
    "total_active_customers": "cm_active_customers_total",
    "active_users": "cm_active_customers_total",
    "customer_count": "cm_active_customers_total",
    "total_customers": "cm_active_customers_total",

    # Extended metrics - engagement
    "monthly_active_users": "cm_monthly_active_users",
    "mau": "cm_monthly_active_users",
    "monthly_active": "cm_monthly_active_users",

    "daily_active_users": "cm_daily_active_users",
    "dau": "cm_daily_active_users",
    "daily_active": "cm_daily_active_users",

    # Extended metrics - unit economics
    "revenue_per_customer": "cm_revenue_per_customer",
    "arpu": "cm_revenue_per_customer",
    "average_revenue_per_user": "cm_revenue_per_customer",
    "revenue_per_user": "cm_revenue_per_customer",

    "customer_acquisition_cost": "cm_customer_acquisition_cost",
    "cac": "cm_customer_acquisition_cost",
    "acquisition_cost": "cm_customer_acquisition_cost",

    "cac_payback_period": "cm_cac_payback_period",
    "cac_payback": "cm_cac_payback_period",
    "payback_period": "cm_cac_payback_period",

    "customer_lifetime_value": "cm_lifetime_value_per_customer",
    "lifetime_value": "cm_lifetime_value_per_customer",
    "ltv": "cm_lifetime_value_per_customer",
    "clv": "cm_lifetime_value_per_customer",

    "ltv_to_cac_ratio": "cm_ltv_to_cac_ratio",
    "ltv_cac": "cm_ltv_to_cac_ratio",
    "ltv_cac_ratio": "cm_ltv_to_cac_ratio",

    "ltv_to_cac_ratio_by_cohort": "cm_ltv_to_cac_ratio_by_cohort",
    "ltv_cac_by_cohort": "cm_ltv_to_cac_ratio_by_cohort",
    "cohort_ltv_cac": "cm_ltv_to_cac_ratio_by_cohort",

    # Extended metrics - retention
    "customer_retention_rate": "cm_customer_retention_rate",
    "retention_rate": "cm_customer_retention_rate",
    "customer_retention": "cm_customer_retention_rate",

    "customer_churn_rate": "cm_customer_churn_rate",
    "churn_rate": "cm_customer_churn_rate",
    "churn": "cm_customer_churn_rate",
    "attrition_rate": "cm_customer_churn_rate",

    "net_revenue_retention": "cm_net_revenue_retention",
    "nrr": "cm_net_revenue_retention",
    "net_dollar_retention": "cm_net_revenue_retention",
    "net_dollar_retention_rate": "cm_net_revenue_retention",
    "ndr": "cm_net_revenue_retention",
    "revenue_retention": "cm_net_revenue_retention",

    "gross_revenue_retention": "cm_gross_revenue_retention",
    "grr": "cm_gross_revenue_retention",

    # Extended metrics - customer counts specific (period-end stock count)
    "paid_customers": "cm_customers_period_end",
    "total_paid_customers": "cm_customers_period_end",
    "paid_customer_count": "cm_customers_period_end",
    "customers_period_end": "cm_customers_period_end",
    "period_end_customers": "cm_customers_period_end",
    "customer_base": "cm_customers_period_end",
    "total_customer_count": "cm_customers_period_end",
    "customers_at_period_end": "cm_customers_period_end",

    "paid_customers_100k": "cm_large_customers_period_end",
    "paid_customers_100k+": "cm_large_customers_period_end",
    "customers_over_100k": "cm_large_customers_period_end",
    "large_customers": "cm_large_customers_period_end",
    "enterprise_customers": "cm_large_customers_period_end",

    # Extended metrics - recurring revenue
    "arr": "cm_arr",
    "annual_recurring_revenue": "cm_arr",
    "annualized_recurring_revenue": "cm_arr",

    "mrr": "cm_mrr",
    "monthly_recurring_revenue": "cm_mrr",

    # Extended metrics - transactions
    "purchase_transactions": "cm_purchase_transactions_overall",
    "total_transactions": "cm_purchase_transactions_overall",
    "transaction_count": "cm_purchase_transactions_overall",
    "order_count": "cm_purchase_transactions_overall",
    "total_orders": "cm_purchase_transactions_overall",

    # Extended metrics - cohort economics
    "gross_margin_by_cohort": "cm_gross_margin_by_cohort",
    "cohort_gross_margin": "cm_gross_margin_by_cohort",
    "cohort_margin": "cm_gross_margin_by_cohort",

    # Extended metrics - expansion and concentration
    "expansion_revenue": "cm_expansion_revenue",
    "upsell_revenue": "cm_expansion_revenue",
    "cross_sell_revenue": "cm_expansion_revenue",

    "revenue_concentration": "cm_revenue_concentration",
    "customer_concentration": "cm_revenue_concentration",
    "top_customers": "cm_revenue_concentration",

    # Extended metrics - e-commerce
    "average_order_value": "cm_average_order_value",
    "aov": "cm_average_order_value",
    "avg_order_value": "cm_average_order_value",

    "repeat_purchase_rate": "cm_repeat_purchase_rate",
    "repeat_purchases": "cm_repeat_purchase_rate",
    "purchase_frequency": "cm_repeat_purchase_rate",
}

# Create reverse mapping for validation
VALID_METRIC_IDS = set(METRIC_NAME_MAPPING.values())


def map_llm_name_to_metric_id(
    llm_name: str,
    candidate_metric_ids: list[str] | None = None
) -> str | None:
    """
    Map an LLM-returned metric name to a canonical metric ID.

    Args:
        llm_name: The metric name returned by the LLM (e.g., "monthly_active_users")
        candidate_metric_ids: Optional list of candidate metric IDs to prefer

    Returns:
        Canonical metric ID (e.g., "cm_monthly_active_users") or None if no match
    """
    if not llm_name:
        return None

    # Normalize the LLM name: lowercase, replace spaces with underscores
    normalized = llm_name.lower().strip().replace(" ", "_").replace("-", "_")

    # 1. Check if it's already a valid metric ID
    if normalized in VALID_METRIC_IDS:
        return normalized

    # 2. Check if it's a valid metric ID with cm_ prefix
    if normalized.startswith("cm_") and normalized in VALID_METRIC_IDS:
        return normalized

    # 3. Try adding cm_ prefix
    with_prefix = f"cm_{normalized}"
    if with_prefix in VALID_METRIC_IDS:
        return with_prefix

    # 4. Check the mapping table
    if normalized in METRIC_NAME_MAPPING:
        mapped_id = METRIC_NAME_MAPPING[normalized]
        # If we have candidates, prefer the mapped ID if it's in candidates
        if candidate_metric_ids and mapped_id in candidate_metric_ids:
            return mapped_id
        return mapped_id

    # 5. Try partial matching with candidates
    if candidate_metric_ids:
        for candidate in candidate_metric_ids:
            # Check if the LLM name is a substring of the candidate (after removing cm_)
            candidate_base = candidate.replace("cm_", "")
            if normalized in candidate_base or candidate_base in normalized:
                return candidate

    # 6. No match found
    logger.debug(f"No metric ID mapping found for LLM name: {llm_name}")
    return None


def _normalize_text(text: str | None) -> str:
    """
    Normalize text for comparison.

    - Decode HTML entities (&amp; -> &, &nbsp; -> space, etc.)
    - Normalize whitespace (collapse multiple spaces, strip)
    - Normalize quote characters (" " -> ")
    """
    if not text:
        return ""

    # Decode HTML entities
    normalized = html.unescape(text)

    # Normalize quote characters (curly to straight)
    normalized = normalized.replace("\u201c", '"').replace("\u201d", '"')  # " and "
    normalized = normalized.replace("\u2018", "'").replace("\u2019", "'")  # ' and '

    # Aggressive normalization:
    # Keep alphanumerics (a-z, 0-9)
    # Keep critical context cues: . % $ € £
    # Replace everything else with space
    # This ensures "Net-Dollar Retention" matches "Net Dollar Retention"
    # while keeping "1.5" distinct from "15"
    normalized = re.sub(r'[^a-zA-Z0-9\.\%\$\€\£\s]', ' ', normalized)

    # Normalize whitespace (including newlines)
    normalized = " ".join(normalized.split())

    return normalized


def verify_quote_in_source(
    quote: str,
    source_text: str,
    threshold: float = DEFAULT_SIMILARITY_THRESHOLD,
) -> bool:
    """
    Verify that an LLM-extracted quote exists in the source text.

    Uses a sliding window approach with difflib.SequenceMatcher to find
    the best matching substring in the source and checks if similarity
    meets the threshold.

    Args:
        quote: The quote extracted by the LLM
        source_text: The original source text to verify against
        threshold: Minimum similarity ratio (default 0.8 = 80%)

    Returns:
        True if quote is verified, False otherwise
    """
    if not quote or not source_text:
        return False

    # Normalize both texts
    quote_normalized = _normalize_text(quote)
    source_normalized = _normalize_text(source_text)

    if not quote_normalized or not source_normalized:
        return False

    # Fast path: exact substring match
    if quote_normalized.lower() in source_normalized.lower():
        return True

    # Fuzzy matching: find best matching window in source
    # Use a window slightly larger than the quote to allow for minor differences
    quote_len = len(quote_normalized)
    window_size = int(quote_len * WINDOW_SIZE_MULTIPLIER)

    best_ratio = 0.0
    source_lower = source_normalized.lower()
    quote_lower = quote_normalized.lower()

    # Use stride to reduce iterations for large documents (O(n/stride) instead of O(n))
    stride = max(1, quote_len // STRIDE_DIVISOR)

    # Slide window across source to find best match
    for i in range(0, max(1, len(source_lower) - quote_len + 1), stride):
        window = source_lower[i : i + window_size]
        matcher = difflib.SequenceMatcher(None, quote_lower, window, autojunk=False)
        ratio = matcher.ratio()
        if ratio > best_ratio:
            best_ratio = ratio
            if best_ratio >= threshold:
                return True  # Early exit on good match

    return best_ratio >= threshold


class ValueExtractor:
    """
    Extract metric values from source segments.

    Focuses on:
    1. Table extraction (most reliable for cohort breakdowns)
    2. Text extraction (fallback for simple disclosures)
    3. Period parsing (fiscal quarters, years)
    4. Cohort label normalization
    """

    # Number patterns
    NUMBER_PATTERN = (
        r"[-]?\$?\s*(\d{1,3}(?:,\d{3})*(?:\.\d+)?)\s*(?:million|billion|thousand|%)?"
    )

    # Period patterns
    QUARTER_PATTERN = r"[qQ]([1-4])\s+(\d{4})"
    YEAR_PATTERN = r"(?:FY|fy)?\s*(\d{4})"

    # Cohort patterns
    ACQUISITION_COHORT_PATTERN = r"(\d{4})\s+[Cc]ohort"
    TENURE_COHORT_PATTERNS = [
        (r"(\d+)\s*-\s*(\d+)\s+(?:months?|mos?)", "months"),
        (r"(\d+)\s*-\s*(\d+)\s+years?", "years"),
        (r"(\d+)\+\s+years?", "years_plus"),
        (r"<\s*(\d+)\s+(?:months?|years?)", "less_than"),
    ]

    def __init__(self, llm_client: Optional["OpenAIClient"] = None):
        """
        Initialize the value extractor.

        Args:
            llm_client: Optional OpenAI client for LLM-enhanced extraction.
                       If provided, LLM extraction will be tried first before
                       falling back to rule-based extraction.
        """
        self._number_regex = re.compile(self.NUMBER_PATTERN, re.IGNORECASE)
        self._quarter_regex = re.compile(self.QUARTER_PATTERN)
        self._year_regex = re.compile(self.YEAR_PATTERN)
        self._acquisition_cohort_regex = re.compile(self.ACQUISITION_COHORT_PATTERN)
        self.llm_client = llm_client

        # Initialize false positive filter (EI-3: prevent extracting page numbers, years, dates)
        try:
            self._fp_filter = FalsePositiveFilter()
            logger.debug("False positive filter initialized successfully")
        except Exception as e:
            logger.warning(f"Failed to initialize false positive filter: {e}. Extraction will continue without filtering.")
            self._fp_filter = None

    def _is_false_positive_value(
        self,
        value_str: str,
        position: int | None,
        context_text: str,
        unit: str | None = None
    ) -> tuple[bool, str | None]:
        """
        Check if an extracted value is a false positive.

        Args:
            value_str: The raw value string (e.g., "2019", "45")
            position: Character position in context_text (None if unknown)
            context_text: The full text containing the value
            unit: Optional unit type ('count', 'currency', 'percentage')

        Returns:
            Tuple of (is_false_positive, reason_string)
        """
        # If filter not available, don't filter (fail open)
        if self._fp_filter is None:
            return False, None

        # If position not available, try to find it in context
        if position is None:
            try:
                position = context_text.find(value_str)
                if position == -1:
                    logger.debug(f"Could not find value '{value_str}' in context for false positive check")
                    return False, None  # Can't filter without position
            except Exception as e:
                logger.debug(f"Error finding position for value '{value_str}': {e}")
                return False, None

        # Create NumberMatch for the filter
        try:
            # Parse the numeric value to get a Decimal
            parsed_value = self._parse_number(value_str)

            # Determine unit if not provided
            if unit is None:
                if "$" in value_str or "usd" in value_str.lower():
                    unit = "currency"
                elif "%" in value_str or "percent" in value_str.lower():
                    unit = "percentage"
                else:
                    unit = "count"

            # Create NumberMatch
            number_match = NumberMatch(
                start=position,
                end=position + len(value_str),
                raw_text=value_str,
                value=parsed_value,
                unit=unit
            )

            # Check if it's a false positive
            is_fp, reason = self._fp_filter.is_false_positive(context_text, number_match)

            if is_fp:
                logger.debug(
                    f"False positive detected: value='{value_str}' reason={reason} "
                    f"context={context_text[max(0, position-30):min(len(context_text), position+30)]!r}"
                )

            return is_fp, reason

        except Exception as e:
            logger.warning(
                f"Error checking false positive for value '{value_str}': {e}. "
                "Proceeding without filtering."
            )
            return False, None  # Don't block extraction on filter errors

    def extract_from_segment(
        self, segment: SourceSegment, company_id: int
    ) -> list[MetricValue]:
        """
        Extract all metric values from a segment.

        Uses hybrid extraction strategy:
        1. Try LLM extraction if LLM client is available
        2. Fall back to rule-based extraction if LLM fails or not available

        Args:
            segment: Classified source segment
            company_id: Company ID for the filing

        Returns:
            List of MetricValue objects (may be multiple per segment)
        """
        # Only extract from segments with numeric disclosure flag
        if not segment.contains_numeric_disclosure_flag:
            return []

        # Try LLM extraction first if available
        if self.llm_client:
            try:
                logger.info(
                    f"Attempting LLM extraction for segment {segment.source_segment_id or segment.sequence_index}"
                )
                if segment.segment_type == "table":
                    values = self.extract_from_table_with_llm(segment, company_id)
                else:
                    values = self.extract_from_text_with_llm(segment, company_id)

                if values:  # LLM extraction succeeded
                    logger.info(
                        f"LLM extraction succeeded: {len(values)} values extracted"
                    )
                    return values
                else:
                    logger.info(
                        "LLM extraction returned no values, falling back to rules"
                    )

            except Exception as e:
                logger.warning(
                    f"LLM extraction failed for segment {segment.source_segment_id or segment.sequence_index}: {e}"
                )
                logger.info("Falling back to rule-based extraction")

        # Fall back to rule-based extraction
        logger.debug("Using rule-based extraction")
        if segment.segment_type == "table":
            return self.extract_from_table(segment, company_id)
        else:
            return self.extract_from_text(segment, company_id)

    def extract_from_table(
        self, segment: SourceSegment, company_id: int
    ) -> list[MetricValue]:
        """
        Extract structured data from table segments.

        Args:
            segment: Table segment
            company_id: Company ID

        Returns:
            List of MetricValue objects extracted from the table
        """
        if not segment.raw_html:
            logger.warning(f"No raw HTML for table segment {segment.source_segment_id}")
            return []

        # Parse table with BeautifulSoup
        soup = BeautifulSoup(segment.raw_html, "html.parser")
        table = soup.find("table")
        if not table:
            logger.warning(f"No table found in segment {segment.source_segment_id}")
            return []

        # Extract table structure
        rows = table.find_all("tr")
        if len(rows) < 2:  # Need at least header + 1 data row
            return []

        # EI-4: Create TableRowParser for row boundary validation
        row_parser: TableRowParser | None = None
        if segment.raw_html and segment.raw_text:
            try:
                row_parser = TableRowParser(segment.raw_html, segment.raw_text)
                logger.debug(f"TableRowParser created for segment {segment.source_segment_id}")
            except Exception as e:
                logger.warning(
                    f"Failed to create TableRowParser for segment {segment.source_segment_id}: {e}. "
                    "Proceeding without row validation."
                )

        # Parse header row to identify columns
        header_row = rows[0]
        headers = [
            self._clean_text(cell.get_text())
            for cell in header_row.find_all(["th", "td"])
        ]

        # Identify column types
        column_info = self._identify_columns(headers)

        # Parse data rows
        values = []
        for row in rows[1:]:
            cells = row.find_all(["td", "th"])
            if len(cells) != len(headers):
                continue  # Skip malformed rows

            row_values = self._parse_table_row(
                cells, headers, column_info, segment, company_id, row_parser
            )
            values.extend(row_values)

        logger.info(
            f"Extracted {len(values)} values from table segment {segment.source_segment_id}"
        )
        return values

    def extract_from_text(
        self, segment: SourceSegment, company_id: int
    ) -> list[MetricValue]:
        """
        Extract values from text segments using pattern matching with smart scoring.

        Args:
            segment: Text segment
            company_id: Company ID

        Returns:
            List of MetricValue objects
        """
        if not segment.raw_text:
            return []

        values = []
        candidate_metrics = segment.candidate_metric_ids or []
        filtered_count = 0

        # Regex patterns for exclusion
        # Matches "January 31, 2019" or "Jan 31 2019"
        # We want to ignore the day (31) and year (2019)
        date_pattern = re.compile(
            r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+(\d{1,2})(?:st|nd|rd|th)?(?:,)?\s+(\d{4})",
            re.IGNORECASE
        )

        # Matches standalone page numbers/TOC entries at start of line
        # e.g., "73 Table of Contents"
        toc_pattern = re.compile(r"^\s*(\d+)\s+(?:Table of Contents|Page)", re.IGNORECASE)

        # Helper to check if a match range overlaps with an exclusion range
        def is_excluded(start: int, end: int, exclusions: list[tuple[int, int]]) -> bool:
            for ex_start, ex_end in exclusions:
                # If overlap
                if start < ex_end and end > ex_start:
                    return True
            return False

        # Scoring function for candidates
        def score_candidate(val_str: str, full_match_str: str, context: str) -> float:
            score = 0.0

            # 1. Currency boost (High)
            if "$" in full_match_str or "USD" in full_match_str.upper():
                score += 5.0
            elif "€" in full_match_str or "£" in full_match_str:
                score += 5.0

            # 2. Magnitude boost (High)
            if "million" in full_match_str.lower():
                score += 4.0
            elif "billion" in full_match_str.lower():
                score += 4.0
            elif "thousand" in full_match_str.lower():
                score += 2.0

            # 3. Percentage boost (Medium - if relevant)
            if "%" in full_match_str:
                score += 3.0

            # 4. Precision boost (Small)
            if "." in val_str:
                score += 1.0

            # 5. Penalties
            # Penalty for "Day of month" lookalikes (1-31 integers)
            if re.match(r"^[1-3][0-9]$|^[1-9]$", val_str):
                score -= 2.0

            # Penalty for "Year" lookalikes (1990-2030) without currency
            if re.match(r"^(?:19|20)\d{2}$", val_str) and "$" not in full_match_str:
                score -= 3.0

            return score

        # Split text into sentences
        sentences = re.split(r'[.\n]+', segment.raw_text)

        # Import metric classifier to access patterns
        from .metric_classifier import MetricClassifier
        classifier = MetricClassifier()

        for sentence in sentences:
            sentence = sentence.strip()
            if not sentence:
                continue

            # 1. Identify Exclusion Ranges in this sentence
            exclusions = []

            # Find dates
            for m in date_pattern.finditer(sentence):
                # Exclude the day group (group 1) and year group (group 2)
                # Group 1 (Day)
                g1_start, g1_end = m.span(1)
                exclusions.append((g1_start, g1_end))
                # Group 2 (Year)
                g2_start, g2_end = m.span(2)
                exclusions.append((g2_start, g2_end))

            # Find TOC/Page numbers
            for m in toc_pattern.finditer(sentence):
                exclusions.append(m.span(1))

            # 2. Find all potential numbers
            # finditer gives us match objects with positions
            number_matches = list(self._number_regex.finditer(sentence))
            if not number_matches:
                continue

            # 3. Process By Metric
            for metric_id in candidate_metrics:
                # Check keywords exist in sentence
                patterns = classifier._metric_patterns.get(metric_id, [])
                has_keyword = False
                for pattern in patterns:
                    if pattern.search(sentence):
                        has_keyword = True
                        break

                if not has_keyword:
                    continue

                # Collect valid candidates and score them
                candidates = []

                for match in number_matches:
                    val_str = match.group(1) # The numeric part
                    full_str = match.group(0) # The full match including $ million etc.
                    start, end = match.span(1) # Span of the numeric part

                    # Skip if in excluded range (Date/Page)
                    if is_excluded(start, end, exclusions):
                        continue

                    # Skip if false positive (using existing filter)
                    position_in_full_text = segment.raw_text.find(sentence) + sentence.find(val_str)
                    is_fp, reason = self._is_false_positive_value(
                        value_str=val_str,
                        position=position_in_full_text,
                        context_text=segment.raw_text,
                        unit=None
                    )
                    if is_fp:
                        filtered_count += 1
                        continue

                    # Score it
                    score = score_candidate(val_str, full_str, sentence)
                    candidates.append({
                        "val_str": val_str,
                        "numeric_value": self._parse_number(val_str),
                        "unit": self._infer_unit(val_str, metric_id),
                        "score": score,
                        "full_match": full_str
                    })

                if not candidates:
                    continue

                # Pick the best candidate
                # Sort by score descending
                candidates.sort(key=lambda x: x["score"], reverse=True)
                best = candidates[0]

                # If best score is very low/negative, maybe skip?
                # For now, we trust the ranking. If it's a tie, first one wins.

                # Create value
                value = MetricValue(
                    filing_id=segment.filing_id,
                    company_id=company_id,
                    metric_id=metric_id,
                    source_segment_id=segment.sequence_index,
                    source_type="text",
                    extraction_method="rule_text_smart",
                    value_numeric=best["numeric_value"],
                    value_text=best["val_str"],
                    unit=best["unit"],
                    period_end=self._extract_period_from_text(sentence),
                    qa_status="unreviewed",
                )
                values.append(value)

                # Move to next metric (we only extract one value per metric per sentence)

        if filtered_count > 0:
            logger.debug(f"Filtered {filtered_count} false positive(s) from smart text extraction")

        return values

    def extract_from_text_with_llm(
        self, segment: SourceSegment, company_id: int
    ) -> list[MetricValue]:
        """
        Extract values from text segments using LLM.

        Args:
            segment: Text segment
            company_id: Company ID

        Returns:
            List of MetricValue objects
        """
        if not self.llm_client:
            raise ValueError("LLM client not available")

        # Import here to avoid circular imports
        from ..llm.prompts import PromptTemplates

        # Get metric names to look for
        metric_names = ", ".join(segment.candidate_metric_ids or [])
        if not metric_names:
            metric_names = "active_users, customer_count, revenue_retention, churn_rate"

        # Create prompt
        prompt = PromptTemplates.value_extraction_from_text(
            segment_text=segment.raw_text[:8000],  # Limit to 8000 chars
            metric_names=metric_names,
            context_text=segment.context_prefix,
        )

        # Get LLM response
        response = self.llm_client.complete(
            prompt, system_message=PromptTemplates.SYSTEM_VALUE_EXTRACTION
        )

        # Parse response
        try:
            data = PromptTemplates.parse_json_response(response.content)

            if not PromptTemplates.validate_value_extraction_response(data):
                logger.warning("LLM response failed validation")
                return []

            # Convert LLM response to MetricValue objects
            values = []
            filtered_count = 0
            for item in data:
                # Parse the numeric value
                numeric_value = self._parse_number(item["value"])
                if numeric_value is None:
                    continue

                # EI-3: Check if value is a false positive before further processing
                value_str = item["value"]
                position = segment.raw_text.find(value_str) if value_str else None
                is_fp, fp_reason = self._is_false_positive_value(
                    value_str=value_str,
                    position=position,
                    context_text=segment.raw_text,
                    unit=item.get("units")
                )

                if is_fp:
                    logger.debug(
                        f"Skipping false positive in LLM text extraction: "
                        f"value='{value_str}' reason={fp_reason}"
                    )
                    filtered_count += 1
                    continue  # Skip this value

                # Parse period if available
                period_end = None
                if item.get("period"):
                    period_end = self._extract_period_from_text(item["period"])

                # Determine metric_id using the mapping function
                llm_metric_name = item.get("metric_name")
                metric_id = map_llm_name_to_metric_id(
                    llm_metric_name,
                    segment.candidate_metric_ids
                )
                if not metric_id:
                    # Log unmapped metric names for debugging
                    logger.warning(
                        f"Could not map LLM metric name '{llm_metric_name}' to canonical ID. "
                        f"Candidates: {segment.candidate_metric_ids}"
                    )
                    continue  # Skip if we can't determine the metric type

                # Verify quote exists in source text
                quote = item.get("quote")
                qa_status = "unreviewed"

                if quote:
                    if verify_quote_in_source(quote, segment.raw_text):
                        qa_status = "pass"  # Quote verified
                    else:
                        # Log with details for debugging (truncate long quotes)
                        truncated_quote = (
                            quote[:100] + "..." if len(quote) > 100 else quote
                        )
                        logger.warning(
                            f"Quote verification failed for {metric_id}. "
                            f"Rejecting extraction. Quote: '{truncated_quote}'"
                        )
                        continue  # Skip this extraction - reject unverified quotes
                else:
                    # CRITICAL FIX: Reject empty quotes instead of accepting
                    logger.warning(
                        f"LLM returned empty quote for {metric_id} - "
                        "rejecting extraction (quote required for verification)"
                    )
                    continue  # Skip this extraction - require quotes

                # CRITICAL: Validate quote contains metric keyword AND value
                # This prevents extracting unrelated nearby numbers
                from .extraction_validation import (
                    ValidationResult,
                    get_rejection_reason,
                    should_reject_extraction,
                    validate_extraction,
                    validate_quote_contains_metric_keyword,
                )
                quote_keyword_result, reason = validate_quote_contains_metric_keyword(
                    metric_id=metric_id,
                    quote=quote,
                    value=float(numeric_value),
                )
                if quote_keyword_result == ValidationResult.FAIL_KEYWORD:
                    truncated_quote = quote[:100] + "..." if len(quote) > 100 else quote
                    logger.warning(
                        f"Quote-keyword validation failed for {metric_id}={numeric_value}: "
                        f"{reason}. Quote: '{truncated_quote}'"
                    )
                    continue  # Reject - quote doesn't prove metric-value association

                # Run additional post-extraction validation
                validation_issues = validate_extraction(
                    metric_id=metric_id,
                    value=numeric_value,
                    unit=item.get("units"),
                    quote=quote,
                    source_text=segment.raw_text,
                )
                if should_reject_extraction(validation_issues):
                    reason = get_rejection_reason(validation_issues)
                    logger.warning(
                        f"Validation failed for {metric_id}={numeric_value}: {reason}"
                    )
                    continue  # Skip this extraction - validation failed

                value = MetricValue(
                    filing_id=segment.filing_id,
                    company_id=company_id,
                    metric_id=metric_id,
                    source_segment_id=segment.source_segment_id
                    or segment.sequence_index,
                    source_type="text",
                    extraction_method="llm_text",
                    value_numeric=numeric_value,
                    value_text=item["value"],
                    unit=item.get("units"),
                    period_end=period_end,
                    cohort_bucket_raw=item.get("cohort_label"),
                    qa_status=qa_status,
                    qa_notes=quote,
                )
                values.append(value)

            if filtered_count > 0:
                logger.debug(f"Filtered {filtered_count} false positive(s) from LLM text extraction")

            logger.info(f"LLM extracted {len(values)} values from text segment")
            return values

        except Exception as e:
            logger.error(f"Failed to parse LLM response: {e}")
            return []

    def extract_from_table_with_llm(
        self, segment: SourceSegment, company_id: int
    ) -> list[MetricValue]:
        """
        Extract values from table segments using LLM.

        Args:
            segment: Table segment
            company_id: Company ID

        Returns:
            List of MetricValue objects
        """
        if not self.llm_client:
            raise ValueError("LLM client not available")

        if not segment.raw_html:
            logger.warning(f"No raw HTML for table segment {segment.source_segment_id}")
            return []

        # Import here to avoid circular imports
        from ..llm.prompts import PromptTemplates

        # Get metric names to look for
        metric_names = ", ".join(segment.candidate_metric_ids or [])
        if not metric_names:
            metric_names = "revenue_by_cohort, customers_by_tenure, retention_rate"

        # Create prompt with both text and HTML
        table_text = segment.raw_text[:4000]  # Limit text
        table_html = segment.raw_html[:4000]  # Limit HTML

        prompt = PromptTemplates.value_extraction_from_table(
            table_text=table_text,
            table_html=table_html,
            metric_names=metric_names,
            context_text=segment.context_prefix,
        )

        # Get LLM response
        response = self.llm_client.complete(
            prompt, system_message=PromptTemplates.SYSTEM_VALUE_EXTRACTION
        )

        # Parse response
        try:
            data = PromptTemplates.parse_json_response(response.content)

            if not PromptTemplates.validate_value_extraction_response(data):
                logger.warning("LLM response failed validation")
                return []

            # Convert LLM response to MetricValue objects
            values = []
            filtered_count = 0
            for item in data:
                # Parse the numeric value
                numeric_value = self._parse_number(item["value"])
                if numeric_value is None:
                    continue

                # EI-3: Check if value is a false positive before further processing
                value_str = item["value"]
                source_for_filtering = segment.raw_text or table_text
                position = source_for_filtering.find(value_str) if value_str else None
                is_fp, fp_reason = self._is_false_positive_value(
                    value_str=value_str,
                    position=position,
                    context_text=source_for_filtering,
                    unit=item.get("units")
                )

                if is_fp:
                    logger.debug(
                        f"Skipping false positive in LLM table extraction: "
                        f"value='{value_str}' reason={fp_reason}"
                    )
                    filtered_count += 1
                    continue  # Skip this value

                # Parse period if available
                period_end = None
                if item.get("period"):
                    period_end = self._extract_period_from_text(item["period"])

                # Parse cohort if available
                cohort_type = None
                cohort_normalized = None
                cohort_label = item.get("cohort_label") or item.get("row_label")
                if cohort_label:
                    cohort_type, cohort_normalized = self.parse_cohort_label(
                        cohort_label
                    )

                # Determine metric_id using the mapping function
                llm_metric_name = item.get("metric_name")
                metric_id = map_llm_name_to_metric_id(
                    llm_metric_name,
                    segment.candidate_metric_ids
                )
                if not metric_id:
                    # Log unmapped metric names for debugging
                    logger.warning(
                        f"Could not map LLM metric name '{llm_metric_name}' to canonical ID. "
                        f"Candidates: {segment.candidate_metric_ids}"
                    )
                    continue  # Skip if we can't determine the metric type

                # Verify quote exists in source text
                quote = item.get("quote")
                qa_status = "unreviewed"

                if quote:
                    # For tables, check against both raw_text and table_text
                    source_for_verification = segment.raw_text or table_text
                    if verify_quote_in_source(quote, source_for_verification):
                        qa_status = "pass"  # Quote verified
                    else:
                        truncated_quote = (
                            quote[:100] + "..." if len(quote) > 100 else quote
                        )
                        logger.warning(
                            f"Quote verification failed for table extraction: {metric_id}. "
                            f"Rejecting extraction. Quote: '{truncated_quote}'"
                        )
                        continue  # Reject unverified
                else:
                    # CRITICAL FIX: Reject empty quotes instead of accepting
                    logger.warning(
                        f"LLM returned empty quote for table extraction: {metric_id} - "
                        "rejecting extraction (quote required for verification)"
                    )
                    continue  # Skip this extraction - require quotes

                # CRITICAL: Validate quote contains metric keyword AND value
                # This prevents extracting unrelated nearby numbers
                from .extraction_validation import (
                    ValidationResult,
                    get_rejection_reason,
                    should_reject_extraction,
                    validate_extraction,
                    validate_quote_contains_metric_keyword,
                )
                quote_keyword_result, reason = validate_quote_contains_metric_keyword(
                    metric_id=metric_id,
                    quote=quote,
                    value=float(numeric_value),
                )
                if quote_keyword_result == ValidationResult.FAIL_KEYWORD:
                    truncated_quote = quote[:100] + "..." if len(quote) > 100 else quote
                    logger.warning(
                        f"Quote-keyword validation failed for table {metric_id}={numeric_value}: "
                        f"{reason}. Quote: '{truncated_quote}'"
                    )
                    continue  # Reject - quote doesn't prove metric-value association

                # Run additional post-extraction validation
                source_for_validation = segment.raw_text or table_text
                validation_issues = validate_extraction(
                    metric_id=metric_id,
                    value=numeric_value,
                    unit=item.get("units"),
                    quote=quote,
                    source_text=source_for_validation,
                )
                if should_reject_extraction(validation_issues):
                    reason = get_rejection_reason(validation_issues)
                    logger.warning(
                        f"Validation failed for table {metric_id}={numeric_value}: {reason}"
                    )
                    continue  # Skip this extraction - validation failed

                value = MetricValue(
                    filing_id=segment.filing_id,
                    company_id=company_id,
                    metric_id=metric_id,
                    source_segment_id=segment.source_segment_id
                    or segment.sequence_index,
                    source_type="table",
                    extraction_method="llm_table",
                    value_numeric=numeric_value,
                    value_text=item["value"],
                    unit=item.get("units"),
                    period_end=period_end,
                    cohort_type=cohort_type,
                    cohort_bucket_raw=cohort_label,
                    cohort_bucket_normalized=cohort_normalized,
                    qa_status=qa_status,
                    qa_notes=quote,
                )
                values.append(value)

            if filtered_count > 0:
                logger.debug(f"Filtered {filtered_count} false positive(s) from LLM table extraction")

            logger.info(f"LLM extracted {len(values)} values from table segment")
            return values

        except Exception as e:
            logger.error(f"Failed to parse LLM response: {e}")
            return []

    def _identify_columns(self, headers: list[str]) -> dict:
        """
        Identify the type of each column based on header text.

        Returns:
            Dictionary mapping column index to column type:
            - 'cohort': Column contains cohort labels
            - 'period': Column contains period labels
            - 'value': Column contains numeric values
        """
        column_info = {}

        for i, header in enumerate(headers):
            header_lower = header.lower()

            # Cohort column indicators
            if any(kw in header_lower for kw in ["cohort", "vintage", "year acquired"]):
                column_info[i] = {"type": "cohort"}

            # Period column indicators (Q1 2024, FY 2023, etc.)
            elif re.search(r"[qQ]\d|FY|20\d{2}", header):
                period_end = self._extract_period_from_text(header)
                column_info[i] = {"type": "value", "period_end": period_end}

            # Default to value column
            else:
                column_info[i] = {"type": "value", "period_end": None}

        return column_info

    def _parse_table_row(
        self,
        cells: list,
        headers: list[str],
        column_info: dict,
        segment: SourceSegment,
        company_id: int,
        row_parser: TableRowParser | None = None,
    ) -> list[MetricValue]:
        """
        Parse a single table row to extract metric values.

        Args:
            cells: List of table cells
            headers: List of header labels
            column_info: Column type information
            segment: Source segment
            company_id: Company ID
            row_parser: Optional TableRowParser for row boundary validation (EI-4)

        Returns:
            List of MetricValue objects from this row
        """
        values = []

        # Extract cohort label from first column if it's a cohort column
        cohort_label = None
        cohort_type = None
        cohort_normalized = None
        cohort_position = None  # EI-4: Track cohort position for row validation

        for i, info in column_info.items():
            if info["type"] == "cohort" and i < len(cells):
                cohort_label = self._clean_text(cells[i].get_text())
                cohort_type, cohort_normalized = self.parse_cohort_label(cohort_label)
                # EI-4: Find position of cohort label for row validation
                if cohort_label and segment.raw_text:
                    cohort_position = segment.raw_text.find(cohort_label)
                break

        # Extract values from value columns
        filtered_count = 0
        row_boundary_filtered_count = 0  # EI-4: Track cross-row rejections
        for i, info in column_info.items():
            if info["type"] != "value" or i >= len(cells):
                continue

            cell_text = self._clean_text(cells[i].get_text())
            numeric_value = self._parse_number(cell_text)

            if numeric_value is None:
                continue  # Skip non-numeric cells

            # EI-3: Check if value is a false positive before creating MetricValue
            # Use segment.raw_text as context for table filtering
            position = segment.raw_text.find(cell_text) if cell_text and segment.raw_text else None
            is_fp, reason = self._is_false_positive_value(
                value_str=cell_text,
                position=position,
                context_text=segment.raw_text or "",
                unit=None  # Will be inferred
            )

            if is_fp:
                logger.debug(
                    f"Skipping false positive in table extraction: "
                    f"value='{cell_text}' reason={reason}"
                )
                filtered_count += 1
                continue  # Skip this value

            # EI-4: Validate row boundary - check if cohort/label and value are in same row
            if row_parser is not None and cohort_position is not None and cohort_position != -1:
                value_position = position  # Already calculated above
                if value_position is not None and value_position != -1:
                    try:
                        if not row_parser.are_in_same_row(cohort_position, value_position):
                            logger.debug(
                                f"Cross-row match rejected: cohort='{cohort_label}' at pos {cohort_position}, "
                                f"value='{cell_text}' at pos {value_position}"
                            )
                            row_boundary_filtered_count += 1
                            continue  # Skip this value - cross-row match
                    except Exception as e:
                        # Fallback: if row validation fails, proceed with extraction
                        logger.debug(
                            f"Row boundary validation failed for value '{cell_text}': {e}. "
                            "Proceeding with extraction."
                        )

            # Determine which metric this value belongs to
            # STRICT: Check row label for metric keywords
            row_metric_id = None

            # Find the row label (first text cell usually)
            row_label_text = ""
            for cell in cells:
                txt = self._clean_text(cell.get_text())
                # Skip if it looks like a number
                if self._parse_number(txt) is None and txt:
                    row_label_text = txt
                    break

            # Check if row label matches any candidate metric
            if segment.candidate_metric_ids:
                from .metric_classifier import MetricClassifier
                classifier = MetricClassifier()
                for cid in segment.candidate_metric_ids:
                    patterns = classifier._metric_patterns.get(cid, [])
                    for pattern in patterns:
                        if pattern.search(row_label_text):
                            row_metric_id = cid
                            break
                    if row_metric_id:
                        break

            # Also check if column header implies metric (e.g. "Revenue")
            col_metric_id = self._infer_metric_from_context(segment, headers, i)

            # Combine: Row label match takes precedence, then Column header match
            metric_id = row_metric_id or col_metric_id

            if not metric_id:
                continue

            # Create MetricValue
            value = MetricValue(
                filing_id=segment.filing_id,
                company_id=company_id,
                metric_id=metric_id,
                source_segment_id=segment.source_segment_id or 0,
                source_type="table",
                extraction_method="rule_table",
                value_numeric=numeric_value,
                value_text=cell_text,
                unit=self._infer_unit(cell_text, metric_id),
                period_end=info.get("period_end"),
                cohort_type=cohort_type,
                cohort_bucket_raw=cohort_label,
                cohort_bucket_normalized=cohort_normalized,
                qa_status="unreviewed",
            )

            values.append(value)

        if filtered_count > 0:
            logger.debug(f"Filtered {filtered_count} false positive(s) from table row")
        if row_boundary_filtered_count > 0:
            logger.debug(f"Filtered {row_boundary_filtered_count} cross-row match(es) from table row")

        return values

    def _infer_metric_from_context(self, segment: SourceSegment, headers: list[str], column_index: int) -> str | None:
        """
        Infer metric ID from column context (header).
        """
        # Strict Row-Only Logic:
        # A value belongs to a metric IF AND ONLY IF:
        # 1. The column header explicity names it (e.g. "Revenue")
        # 2. OR The row label explicitily matches the metric keywords

        # 1. Check Column Header
        if column_index < len(headers):
            header = headers[column_index].lower()

            # Direct header matches
            if "revenue" in header and "cohort" in header:
                return "cm_revenue_by_cohort"
            if "transaction" in header and "cohort" in header:
                return "cm_transactions_by_cohort"
            if "customer" in header and "tenure" in header:
                return "cm_customers_period_end_by_tenure"

            # If the segment has candidates, check if header matches one of them
            if segment.candidate_metric_ids:
                from .metric_classifier import MetricClassifier
                classifier = MetricClassifier()

                for metric_id in segment.candidate_metric_ids:
                    patterns = classifier._metric_patterns.get(metric_id, [])
                    for pattern in patterns:
                         if pattern.search(header):
                             return metric_id

        return None

        # Current fallback (RESTRICTED):
        # We DO NOT fallback to "candidate_metrics[0]" blindly anymore.
        # If we can't find a match in the header, we return None (unless the table is VERY simple).

        return None

    def _infer_unit(self, value_text: str, metric_id: str) -> str | None:
        """Infer the unit from value text and metric type."""
        value_lower = value_text.lower()

        # Currency
        if "$" in value_text or "usd" in value_lower:
            return "usd"

        # Percentage
        if "%" in value_text or "percent" in value_lower:
            return "%"

        # From metric type
        if "revenue" in metric_id or "cost" in metric_id or "value" in metric_id:
            return "usd"

        if "rate" in metric_id:
            return "%"

        # Default to count for customer/user metrics
        if "customer" in metric_id or "user" in metric_id or "transaction" in metric_id:
            return "count"

        return None

    def parse_cohort_label(self, raw_label: str) -> tuple[str | None, str | None]:
        """
        Parse cohort label into type and normalized bucket.

        Args:
            raw_label: Raw cohort label from filing

        Returns:
            (cohort_type, cohort_bucket_normalized)

        Examples:
            "2021 Cohort" -> ("acquisition", "2021")
            "0-12 months" -> ("tenure", "0-1y")
            "2+ years" -> ("tenure", "2y+")
        """
        if not raw_label:
            return None, None

        # Check for acquisition cohort (year-based)
        match = self._acquisition_cohort_regex.search(raw_label)
        if match:
            year = match.group(1)
            return "acquisition", year

        # Check for tenure cohorts
        for pattern, cohort_subtype in self.TENURE_COHORT_PATTERNS:
            match = re.search(pattern, raw_label, re.IGNORECASE)
            if match:
                if cohort_subtype == "months":
                    start, end = match.groups()
                    # Convert to year buckets
                    start_years = int(start) // 12
                    end_years = int(end) // 12
                    return "tenure", f"{start_years}-{end_years}y"

                elif cohort_subtype == "years":
                    start, end = match.groups()
                    return "tenure", f"{start}-{end}y"

                elif cohort_subtype == "years_plus":
                    years = match.group(1)
                    return "tenure", f"{years}y+"

                elif cohort_subtype == "less_than":
                    value = match.group(1)
                    if "month" in raw_label.lower():
                        years = int(value) // 12
                        return "tenure", f"<{years}y"
                    else:
                        return "tenure", f"<{value}y"

        # Could not parse
        return "other", raw_label

    def _parse_number(self, text: str) -> Decimal | None:
        """
        Parse numeric value from text.

        Handles:
        - Comma separators: 1,234,567
        - Currency symbols: $1.2M
        - Negative numbers: -123
        - Scale indicators: million, billion

        Returns:
            Decimal value or None if unparseable
        """
        # Remove currency symbols and whitespace
        cleaned = text.replace("$", "").replace(",", "").strip()

        # Check for scale indicators
        scale = 1
        if "billion" in cleaned.lower():
            scale = 1_000_000_000
            cleaned = re.sub(r"billion", "", cleaned, flags=re.IGNORECASE).strip()
        elif "million" in cleaned.lower():
            scale = 1_000_000
            cleaned = re.sub(r"million", "", cleaned, flags=re.IGNORECASE).strip()
        elif "thousand" in cleaned.lower():
            scale = 1_000
            cleaned = re.sub(r"thousand", "", cleaned, flags=re.IGNORECASE).strip()

        # Remove percentage signs
        cleaned = cleaned.replace("%", "").strip()

        # Try to convert to Decimal
        try:
            value = Decimal(cleaned) * scale
            return value
        except (InvalidOperation, ValueError):
            return None

    def _extract_period_from_text(self, text: str) -> date | None:
        """
        Extract period end date from text.

        Looks for patterns like:
        - Q1 2024 -> 2024-03-31
        - Q4 2023 -> 2023-12-31
        - FY 2023 -> 2023-12-31
        """
        # Try quarter pattern first
        match = self._quarter_regex.search(text)
        if match:
            quarter = int(match.group(1))
            year = int(match.group(2))

            # Map quarter to month
            quarter_end_months = {1: 3, 2: 6, 3: 9, 4: 12}
            month = quarter_end_months.get(quarter, 12)

            # Last day of quarter
            if month in [3, 6, 9]:
                day = 30 if month == 6 or month == 9 else 31
            else:
                day = 31

            try:
                return date(year, month, day)
            except ValueError:
                return None

        # Try year pattern
        match = self._year_regex.search(text)
        if match:
            year = int(match.group(1))
            try:
                return date(year, 12, 31)
            except ValueError:
                return None

        return None

    def _clean_text(self, text: str) -> str:
        """Clean text content."""
        return re.sub(r"\s+", " ", text).strip()


# Convenience function
def extract_values(segment: SourceSegment, company_id: int) -> list[MetricValue]:
    """
    Convenience function to extract values from a segment.

    Args:
        segment: Source segment
        company_id: Company ID

    Returns:
        List of MetricValue objects
    """
    extractor = ValueExtractor()
    return extractor.extract_from_segment(segment, company_id)
```

## src/review/keyword_matching.py

```python
"""
Keyword Matching - Find metric keywords in text and match them to numbers.

This module provides functionality to find metric keywords in text and
determine which keywords are near which numbers. It handles:
- Finding all keyword matches in text
- Filtering keywords by distance from numbers
- Calculating distances between text spans
- Table-aware matching with row boundary filtering (prevents cross-row matches)
- Row heading priority (prefers keywords in first cell of table rows)

Extracted from candidate_generator.py as part of P1.3 module splitting
for improved maintainability and testability.

Automatic Usage (via CandidateGenerator):
    >>> from src.review import CandidateGenerator
    >>>
    >>> # Keyword matching happens automatically
    >>> generator = CandidateGenerator()
    >>> candidates = generator.generate_for_filing(
    ...     filing_id=123, company_id=456, segments=segments
    ... )
    >>> # Each candidate has triggering_keyword field
    >>> print(candidates[0].triggering_keyword)  # e.g., "active customers"

Direct Usage (advanced):
    >>> from src.review.keyword_matching import KeywordMatcher
    >>> from src.review.number_parsing import NumberMatch
    >>> from decimal import Decimal
    >>>
    >>> # Initialize matcher
    >>> matcher = KeywordMatcher(max_keyword_distance=100)
    >>>
    >>> # Find all keywords in text
    >>> text = "We have 50,000 active customers and $100M in revenue."
    >>> keywords = matcher.find_all_keywords(text)
    >>> print(f"Found {len(keywords)} keyword matches")
    >>>
    >>> # Find keywords near a specific number
    >>> number = NumberMatch(
    ...     start=8, end=14, raw_text="50,000", value=Decimal("50000"), unit="count"
    ... )
    >>> nearby = matcher.find_keywords_near_number(number, keywords)
    >>> for kw in nearby:
    ...     print(f"{kw.keyword} (metric: {kw.metric_id}, distance: {kw.distance})")

Adjusting Proximity Threshold:
    >>> from src.review.config import CandidateGenerationConfig
    >>>
    >>> # Stricter proximity (high precision)
    >>> config = CandidateGenerationConfig(
    ...     max_keyword_distance=50,  # Only match if within 50 chars
    ... )
    >>> generator = CandidateGenerator(config=config)
    >>> candidates = generator.generate_for_filing(
    ...     filing_id=123, company_id=456, segments=segments
    ... )
    >>>
    >>> # Looser proximity (high recall)
    >>> config = CandidateGenerationConfig(
    ...     max_keyword_distance=150,  # Match within 150 chars
    ... )
    >>> generator = CandidateGenerator(config=config)

Understanding Distance Calculation:
    >>> # Distance is character distance between spans
    >>> # If keyword ends at position 50 and number starts at 60:
    >>> # distance = 60 - 50 = 10 characters
    >>> # Whitespace counts toward distance
    >>>
    >>> # Example: "active customers 50,000"
    >>> # Keyword: "active customers" (positions 0-16)
    >>> # Number: "50,000" (positions 17-23)
    >>> # Distance: 17 - 16 = 1 character

See Also:
    - candidate_generator.py: Uses KeywordMatcher internally
    - config.py: Configure max_keyword_distance
"""

import logging
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Optional, cast

from src.review.number_parsing import NumberMatch

if TYPE_CHECKING:
    from src.review.boundary_detection import TextBoundary
    from src.review.marker_row_parser import MarkerRowParser
    from src.review.table_structure import TableRowParser

logger = logging.getLogger(__name__)


# =============================================================================
# Keyword Loading Functions
# =============================================================================

def _load_metric_keywords() -> dict[str, list[str]]:
    """Load metric keywords from YAML config, excluding deprecated metrics.

    Raises:
        KeywordConfigError: If YAML config cannot be loaded.
    """
    from src.extraction.keyword_config import get_metric_keywords, is_metric_deprecated

    all_keywords = get_metric_keywords()

    # Filter out deprecated metrics
    active_keywords = {
        metric_id: patterns
        for metric_id, patterns in all_keywords.items()
        if not is_metric_deprecated(metric_id)
    }

    logger.info(
        f"Loaded {len(active_keywords)} active metrics "
        f"({len(all_keywords) - len(active_keywords)} deprecated, skipped)"
    )

    return cast(dict[str, list[str]], active_keywords)


def _load_exclusion_patterns() -> dict[str, list[str]]:
    """Load exclusion patterns from YAML config, excluding deprecated metrics.

    Raises:
        KeywordConfigError: If YAML config cannot be loaded.
    """
    from src.extraction.keyword_config import get_exclusion_patterns, is_metric_deprecated

    all_exclusions = get_exclusion_patterns()

    # Filter out deprecated metrics
    active_exclusions = {
        metric_id: patterns
        for metric_id, patterns in all_exclusions.items()
        if not is_metric_deprecated(metric_id)
    }

    return cast(dict[str, list[str]], active_exclusions)


def _load_specific_patterns() -> list[str]:
    """Load specific (multi-word) patterns from YAML config.

    Raises:
        KeywordConfigError: If YAML config cannot be loaded.
    """
    from src.extraction.keyword_config import get_specific_patterns
    return cast(list[str], get_specific_patterns())


def _load_required_context() -> dict[str, dict[str, Any]]:
    """Load required context patterns from YAML config, excluding deprecated metrics.

    Required context patterns gate which metrics generate review candidates.
    Metrics with required_context only generate candidates when at least one
    of the context patterns appears within proximity of the keyword match.

    Raises:
        KeywordConfigError: If YAML config cannot be loaded.
    """
    from src.extraction.keyword_config import get_required_context, is_metric_deprecated

    all_context = get_required_context()

    # Filter out deprecated metrics
    active_context = {
        metric_id: context
        for metric_id, context in all_context.items()
        if not is_metric_deprecated(metric_id)
    }

    return cast(dict[str, dict[str, Any]], active_context)


# =============================================================================
# Module-Level Keyword Data (loaded at import time)
# =============================================================================

# These are loaded once at module import and used throughout
METRIC_KEYWORDS: dict[str, list[str]] = _load_metric_keywords()
METRIC_EXCLUSION_PATTERNS: dict[str, list[str]] = _load_exclusion_patterns()
SPECIFIC_KEYWORD_PATTERNS: list[str] = _load_specific_patterns()
METRIC_REQUIRED_CONTEXT: dict[str, dict[str, Any]] = _load_required_context()


# =============================================================================
# Data Classes
# =============================================================================


@dataclass
class KeywordMatch:
    """A keyword match found in text."""

    start: int  # Character position
    end: int  # End position
    keyword: str  # The matched text
    metric_id: str  # Associated metric ID
    pattern: str  # The regex pattern that matched
    direction: str | None = None  # 'before' | 'after' | 'at' (relative to number, L3 enhancement)


# =============================================================================
# KeywordMatcher Class
# =============================================================================


class KeywordMatcher:
    """
    Matcher for finding metric keywords in text.

    Handles finding all keyword matches in text and filtering them by
    distance from numbers. Uses pre-compiled regex patterns for efficiency.

    P1 Enhancements:
    - Sort by distance first (closest keyword), then length (longest)
    - Boundary-aware matching (prefer keywords in same boundary as number)
    - Ambiguity logging when multiple keywords are equally close

    P1.5 Enhancements:
    - Sentence-aware matching (filter keywords from different sentences)

    L4 Enhancement:
    - Post-value distance multiplier (prefer keywords before values)
    - Context-dependent multipliers (Option C: different preferences by context)
    """

    def __init__(
        self,
        max_keyword_distance: int = 100,
        prefer_closest_keyword: bool = True,
        respect_bullet_boundaries: bool = True,
        respect_sentence_boundaries: bool = True,
        log_ambiguous_matches: bool = True,
        ambiguity_threshold: int = 10,
        post_value_distance_multiplier: float = 0.9,
        use_context_dependent_multipliers: bool = True,
        multiplier_bullet_points: float = 0.9,
        multiplier_parenthetical: float = 1.15,
        multiplier_tables: float = 0.85,
        multiplier_copula_verb: float = 0.9,
        multiplier_preposition: float = 1.1,
        multiplier_default: float = 0.9,
    ):
        """
        Initialize the keyword matcher.

        Args:
            max_keyword_distance: Maximum character distance between number
                                 and keyword for a match
            prefer_closest_keyword: Sort by distance first, then length (P1 enhancement)
            respect_bullet_boundaries: Prefer keywords in same boundary as number (P1 enhancement)
            respect_sentence_boundaries: Filter keywords from different sentences (P1.5 enhancement)
            log_ambiguous_matches: Log when multiple keywords are equally close (P1 enhancement)
            ambiguity_threshold: Characters to consider "equally close" (default: 10)
            post_value_distance_multiplier: Base multiplier for post-value keyword distances (L4 enhancement)
            use_context_dependent_multipliers: Enable context-dependent multiplier logic (L4 Option C)
            multiplier_bullet_points: Multiplier for bullet point contexts (L4 Option C)
            multiplier_parenthetical: Multiplier for parenthetical text (L4 Option C)
            multiplier_tables: Multiplier for table contexts (L4 Option C)
            multiplier_copula_verb: Multiplier for copula verb contexts (L4 Option C)
            multiplier_preposition: Multiplier for prepositional phrases (L4 Option C)
            multiplier_default: Default multiplier when no context detected (L4 Option C)
        """
        self.max_keyword_distance = max_keyword_distance
        self.prefer_closest_keyword = prefer_closest_keyword
        self.respect_bullet_boundaries = respect_bullet_boundaries
        self.respect_sentence_boundaries = respect_sentence_boundaries
        self.log_ambiguous_matches = log_ambiguous_matches
        self.ambiguity_threshold = ambiguity_threshold
        self.post_value_distance_multiplier = post_value_distance_multiplier

        # L4 Option C: Context-dependent multipliers
        self.use_context_dependent_multipliers = use_context_dependent_multipliers
        self.multiplier_bullet_points = multiplier_bullet_points
        self.multiplier_parenthetical = multiplier_parenthetical
        self.multiplier_tables = multiplier_tables
        self.multiplier_copula_verb = multiplier_copula_verb
        self.multiplier_preposition = multiplier_preposition
        self.multiplier_default = multiplier_default

        # Pre-compile all keyword patterns for reuse
        self._compiled_patterns: dict[str, list[tuple[re.Pattern[str], str]]] = {}
        for metric_id, patterns in METRIC_KEYWORDS.items():
            self._compiled_patterns[metric_id] = [
                (re.compile(pattern, re.IGNORECASE), pattern) for pattern in patterns
            ]

        # HRI-3: Pre-compile exclusion patterns for reuse
        self._compiled_exclusions: dict[str, list[re.Pattern[str]]] = {}
        for metric_id, exclusion_patterns in METRIC_EXCLUSION_PATTERNS.items():
            compiled_list: list[re.Pattern[str]] = []
            for pattern in exclusion_patterns:
                try:
                    compiled_list.append(re.compile(pattern, re.IGNORECASE))
                except re.error as e:
                    # Log and skip invalid patterns - don't crash
                    logger.warning(
                        f"Invalid exclusion pattern for {metric_id}: {pattern!r} - {e}"
                    )
            if compiled_list:
                self._compiled_exclusions[metric_id] = compiled_list

        # Pre-compile required context patterns for revenue synonym filtering
        # tuple of (compiled_patterns, proximity_chars)
        self._compiled_required_context: dict[str, tuple[list[re.Pattern[str]], int]] = {}
        for metric_id, ctx_config in METRIC_REQUIRED_CONTEXT.items():
            compiled_ctx_patterns: list[re.Pattern[str]] = []
            for pattern in ctx_config.get("patterns", []):
                try:
                    compiled_ctx_patterns.append(re.compile(pattern, re.IGNORECASE))
                except re.error as e:
                    logger.warning(
                        f"Invalid required_context pattern for {metric_id}: {pattern!r} - {e}"
                    )
            if compiled_ctx_patterns:
                proximity = ctx_config.get("proximity_chars", 1500)
                self._compiled_required_context[metric_id] = (
                    compiled_ctx_patterns,
                    proximity,
                )

    def _is_excluded(self, metric_id: str, context: str) -> bool:
        """
        Check if context contains an exclusion pattern for this metric.

        HRI-3 Enhancement: Prevents misclassifications by checking if the
        surrounding context indicates a different metric should be matched.

        Args:
            metric_id: The metric ID to check exclusions for
            context: The surrounding text context (typically ±50 chars)

        Returns:
            True if any exclusion pattern matches, False otherwise
        """
        if metric_id not in self._compiled_exclusions:
            return False

        for pattern in self._compiled_exclusions[metric_id]:
            if pattern.search(context):
                return True
        return False

    def should_exclude_for_number_context(
        self,
        metric_id: str,
        text: str,
        number_position: int,
        window_chars: int = 100,
        table_row_parser: "TableRowParser | MarkerRowParser | None" = None,
    ) -> tuple[bool, str | None]:
        """
        Check if a candidate should be excluded based on NUMBER context.

        Called by CandidateGenerator before feature extraction.
        Uses the same compiled exclusion patterns as keyword-context exclusions.

        This addresses the architecture issue where keyword-context exclusions
        (checked during find_all_keywords) use ±50 chars around the KEYWORD,
        but some false positives occur when numbers are far from keywords
        but near exclusion-worthy context.

        EXT-FN-1 Enhancement: When a table_row_parser is provided and the
        segment is a table, the exclusion context is limited to ONLY the text
        within the same table row as the number. This prevents false exclusions
        where keywords like "Net Dollar Retention Rate" in an adjacent row
        incorrectly exclude values from the "Paid Customers >$100,000" row.

        Args:
            metric_id: The metric ID to check exclusions for
            text: The full text containing the number
            number_position: Character position of the number in text
            window_chars: Characters around number position to check (default: 100)
            table_row_parser: Optional parser for table row boundaries. If provided
                and segment is a table, limits exclusion context to same row only.

        Returns:
            Tuple of (should_exclude, reason)
            reason is a string like "exclusion:number_context:<pattern>" if excluded,
            None if not excluded
        """
        if metric_id not in self._compiled_exclusions:
            return False, None

        # EXT-FN-1: If table_row_parser provided and it's a table,
        # limit exclusion context to the same row as the number
        if table_row_parser is not None and table_row_parser.is_table():
            row = table_row_parser.get_row_at_position(number_position)
            if row is not None:
                # Use row text as context instead of window-based context
                context = row.row_text
            else:
                # Position not in any row - fall back to window-based context
                # This is unexpected in normal operation, so log at debug level
                logger.debug(
                    f"EXT-FN-1: Position {number_position} not in parsed rows, "
                    f"using {window_chars}-char window fallback"
                )
                start = max(0, number_position - window_chars)
                end = min(len(text), number_position + window_chars)
                context = text[start:end]
        else:
            # No table parser or not a table - use original window-based context
            start = max(0, number_position - window_chars)
            end = min(len(text), number_position + window_chars)
            context = text[start:end]

        for pattern in self._compiled_exclusions[metric_id]:
            if pattern.search(context):
                return True, f"exclusion:number_context:{pattern.pattern}"

        return False, None

    def _has_required_context(
        self, metric_id: str, match_position: int, full_text: str
    ) -> bool:
        """
        Check if required context is present for a context-gated metric.

        For metrics with required_context configuration (e.g., cm_gmv, cm_tcv),
        this checks if at least one of the required context patterns (cohort,
        per customer, etc.) appears within the specified proximity of the
        keyword match.

        Revenue synonym metrics (GMV, TCV, ACV, Bookings, Billings) require
        cohort or per-customer context to be meaningful as customer metrics.
        Without this context, they are just aggregate revenue measures.

        Args:
            metric_id: The metric ID to check required context for
            match_position: The character position of the keyword match
            full_text: The full text to search for context

        Returns:
            True if no required context is configured for this metric, OR
            True if required context IS configured AND at least one pattern is found.
            False if required context IS configured but NO patterns are found.
        """
        if metric_id not in self._compiled_required_context:
            return True  # No required context for this metric - always matches

        patterns, proximity_chars = self._compiled_required_context[metric_id]

        # Define the search window around the match position
        context_start = max(0, match_position - proximity_chars)
        context_end = min(len(full_text), match_position + proximity_chars)
        context = full_text[context_start:context_end]

        # Check if ANY required context pattern matches
        for pattern in patterns:
            if pattern.search(context):
                logger.debug(
                    f"Required context found for {metric_id} at position {match_position}: "
                    f"pattern '{pattern.pattern}' matched within {proximity_chars} chars"
                )
                return True

        logger.debug(
            f"Required context NOT found for {metric_id} at position {match_position}: "
            f"no cohort/per-customer patterns within {proximity_chars} chars"
        )
        return False

    def find_all_keywords(self, text: str) -> list[KeywordMatch]:
        """
        Find all metric keywords in text.

        Searches text for all metric keyword patterns. Uses pre-compiled
        patterns for efficiency, but searches each pattern individually.
        This approach is faster than combining patterns due to regex engine
        behavior with large alternations.

        HRI-3 Enhancement:
        - Applies exclusion pattern filtering to prevent misclassifications
        - Checks surrounding context (±50 chars) for exclusion patterns
        - Skips matches where exclusion pattern indicates wrong metric

        Args:
            text: The full text to search

        Returns:
            List of all KeywordMatch objects found, sorted by position
        """
        all_matches = []

        # Search with each compiled pattern (faster than combined pattern due to early exits)
        for metric_id, compiled_patterns in self._compiled_patterns.items():
            for compiled_pattern, pattern_str in compiled_patterns:
                for match in compiled_pattern.finditer(text):
                    # HRI-3: Check exclusion patterns before adding match
                    # Get context around the match (±50 chars)
                    context_start = max(0, match.start() - 50)
                    context_end = min(len(text), match.end() + 50)
                    context = text[context_start:context_end]

                    # Skip if exclusion pattern matches in context
                    if self._is_excluded(metric_id, context):
                        logger.debug(
                            f"Excluded match: '{match.group()}' for {metric_id} "
                            f"due to exclusion pattern in context"
                        )
                        continue

                    all_matches.append(
                        KeywordMatch(
                            start=match.start(),
                            end=match.end(),
                            keyword=match.group(),
                            metric_id=metric_id,
                            pattern=pattern_str,
                        )
                    )

        # Sort by position
        all_matches.sort(key=lambda m: m.start)
        return all_matches

    def find_keywords_near_number(
        self,
        number: NumberMatch,
        all_keywords: list[KeywordMatch],
        boundaries: list["TextBoundary"] | None = None,
        sentence_boundaries: list["TextBoundary"] | None = None,
        text: str = "",
        segment_type: str | None = None,
        table_row_parser: Optional["TableRowParser"] = None,
        check_required_context: bool = True,
    ) -> list[KeywordMatch]:
        """
        Find metric keywords within max_keyword_distance of a number.

        Uses pre-computed keyword matches for efficiency. Returns at most
        one keyword per metric ID (the closest one). Filters out keywords
        that are substrings of other matched keywords at overlapping positions
        (e.g., if "LTV/CAC" is matched, don't also match "LTV" and "CAC").

        P1 Enhancements:
        - Sorts by distance first (closest), then length (longest)
        - Applies boundary constraints if boundaries provided
        - Logs ambiguous matches when multiple keywords are equally close

        P1.5 Enhancements:
        - Applies sentence boundary constraints if sentence_boundaries provided
        - Filters keywords from different sentences than the number

        L4 Option C Enhancement:
        - Context-dependent multipliers for post-value keywords
        - Different preferences based on textual context (tables, bullets, parentheticals)

        Table Row Filtering Enhancement:
        - Filters out keywords from different table rows than the number
        - Prevents false matches where keyword in one row associates with value from another row

        Args:
            number: The NumberMatch to search around
            all_keywords: Pre-computed list of all keyword matches in text
            boundaries: Optional list of TextBoundary objects for boundary-aware matching
            sentence_boundaries: Optional list of sentence boundaries for P1.5 filtering
            text: Optional full text for context detection (L4 Option C)
            segment_type: Optional segment type for context detection (L4 Option C)
            table_row_parser: Optional TableRowParser for table row filtering
            check_required_context: If True (default), filter out revenue synonym
                metrics (GMV, TCV, etc.) that lack cohort or per-customer context.
                Set to False to include all matches regardless of context.

        Returns:
            List of KeywordMatch objects within range (one per metric,
            prioritizing closest, then longest keywords)
        """
        # Phase 1: Collect all keywords within distance with their distances and directions
        # Store as (keyword, raw_distance, direction) for L4 multiplier application
        # Also filter by required context for revenue synonym metrics
        #
        # FIX-5: For tables with row/cell structure, skip distance filter in Phase 1
        # and rely on Phase 2.75 (table row filtering) instead. This prevents
        # missing values in wide tables where the row heading keyword is >100 chars
        # from some values in the same row. Distance is still computed for ranking.
        # Note: We check for table_row_parser presence (not just is_table()) because
        # single-row tables with [CELL] markers also need unrestricted same-row matching.
        has_table_structure = table_row_parser is not None

        candidates_with_distance: list[tuple[KeywordMatch, int]] = []
        for kw in all_keywords:
            dist = self.calculate_distance_from_positions(
                number.start, number.end, kw.start, kw.end
            )
            # Apply distance filter only if NOT in a table with row structure
            if not has_table_structure and dist > self.max_keyword_distance:
                continue

            # Check required context for context-gated metrics (GMV, TCV, etc.)
            if check_required_context and not self._has_required_context(
                kw.metric_id, kw.start, text
            ):
                logger.debug(
                    f"Filtered keyword '{kw.keyword}' ({kw.metric_id}): "
                    f"required cohort/per-customer context not present"
                )
                continue
            candidates_with_distance.append((kw, dist))

        if not candidates_with_distance:
            return []

        # Phase 2: Apply boundary constraints (P1 enhancement)
        if boundaries and self.respect_bullet_boundaries:
            # Find the boundary containing the number
            number_boundary = self._get_boundary_at_position(number.start, boundaries)

            if number_boundary is not None:
                # Separate candidates into same-boundary vs cross-boundary
                same_boundary = [
                    (kw, dist)
                    for kw, dist in candidates_with_distance
                    if self._is_in_same_boundary(kw.start, number_boundary, boundaries)
                ]

                # Prefer same-boundary candidates if any exist
                if same_boundary:
                    logger.debug(
                        f"Boundary filtering: {len(same_boundary)}/{len(candidates_with_distance)} "
                        f"keywords in same boundary as number at position {number.start}"
                    )
                    candidates_with_distance = same_boundary

        # Phase 2.5: Apply sentence boundary constraints (P1.5 enhancement)
        if sentence_boundaries and self.respect_sentence_boundaries:
            # Find the sentence containing the number
            number_sentence = self._get_boundary_at_position(
                number.start, sentence_boundaries
            )

            if number_sentence is not None:
                # Filter to keywords in the same sentence as the number
                same_sentence = [
                    (kw, dist)
                    for kw, dist in candidates_with_distance
                    if self._is_in_same_boundary(
                        kw.start, number_sentence, sentence_boundaries
                    )
                ]

                # Only filter if we have same-sentence candidates
                # (fallback: if no same-sentence keywords, keep all)
                if same_sentence:
                    if len(same_sentence) < len(candidates_with_distance):
                        logger.debug(
                            f"Sentence filtering: {len(same_sentence)}/{len(candidates_with_distance)} "
                            f"keywords in same sentence as number '{number.raw_text}'"
                        )
                    candidates_with_distance = same_sentence
                else:
                    # No same-sentence keywords found - keep all candidates (fallback)
                    logger.debug(
                        f"Sentence filtering fallback: no keywords in same sentence "
                        f"as number '{number.raw_text}'; keeping all {len(candidates_with_distance)} candidates"
                    )

        # Phase 2.75: Apply table row constraints (Table Row Filtering Enhancement)
        if table_row_parser is not None and table_row_parser.is_table():
            # Filter to keywords in the same table row as the number
            same_row = [
                (kw, dist)
                for kw, dist in candidates_with_distance
                if table_row_parser.are_in_same_row(kw.start, number.start)
            ]

            # Strict row filtering: only keep same-row keywords
            # Numbers without same-row keywords are not valid metric candidates
            if len(same_row) < len(candidates_with_distance):
                filtered_count = len(candidates_with_distance) - len(same_row)
                logger.debug(
                    f"Table row filtering: kept {len(same_row)}/{len(candidates_with_distance)} "
                    f"keywords in same row as '{number.raw_text}' (filtered {filtered_count} cross-row)"
                )
            candidates_with_distance = same_row

        # Phase 3: Sort by distance first, then length (P1 enhancement + L4 multiplier + L4 Option C)
        if self.prefer_closest_keyword:
            # L4 Option C: Compute effective distance using context-dependent multipliers
            candidates_with_effective_distance: list[tuple[KeywordMatch, int, float]] = []

            for kw, raw_distance in candidates_with_distance:
                # Compute direction to determine if multiplier applies
                direction = self.calculate_keyword_direction(kw.start, number.start)

                # Get context-appropriate multiplier (L4 Option C)
                multiplier = self.get_context_multiplier(
                    text=text,
                    number_position=number.start,
                    keyword_position=kw.start,
                    keyword_direction=direction,
                    boundaries=boundaries,
                    segment_type=segment_type,
                )

                # Apply multiplier to post-value keywords by dividing
                # Example: distance=100, multiplier=0.9 → effective=111.11 (less favorable)
                # Example: distance=100, multiplier=1.15 → effective=86.96 (more favorable)
                effective_distance = (
                    raw_distance / multiplier if direction == "after" else float(raw_distance)
                )

                # Row Heading Priority: Keywords in table row headings (first cell) get strong preference
                # This ensures we match "Gross profit" (row heading) over "Gross profit margin"
                # (different row) when a value appears in the "Gross profit" row
                if table_row_parser is not None and table_row_parser.is_table():
                    if table_row_parser.is_row_heading(kw.start):
                        # Apply 0.25x multiplier (75% reduction) to effective distance
                        # This makes row headings strongly preferred over other keywords
                        effective_distance *= 0.25
                        logger.debug(
                            f"Row heading priority: '{kw.keyword}' effective distance "
                            f"reduced {raw_distance:.1f} → {effective_distance:.1f}"
                        )

                candidates_with_effective_distance.append(
                    (kw, raw_distance, effective_distance)
                )

            # Sort by (effective_distance, -length): closest first, then longest
            candidates_with_effective_distance.sort(
                key=lambda x: (x[2], -len(x[0].keyword))
            )
        else:
            # Original behavior: sort by length only (longest first)
            # Still need to create tuples with effective distance for consistency
            candidates_with_effective_distance = [
                (kw, dist, float(dist)) for kw, dist in candidates_with_distance
            ]
            candidates_with_effective_distance.sort(key=lambda x: -len(x[0].keyword))

        # Phase 4: Detect and log ambiguous matches (P1 enhancement, B1 fix)
        # B1 Fix: Use EFFECTIVE distance for ambiguity detection, not raw distance
        if self.log_ambiguous_matches and len(candidates_with_effective_distance) > 1:
            min_effective_distance = candidates_with_effective_distance[0][2]
            ambiguous_keywords = [
                kw.keyword
                for kw, raw_dist, eff_dist in candidates_with_effective_distance
                if abs(eff_dist - min_effective_distance) <= self.ambiguity_threshold
            ]

            if len(ambiguous_keywords) > 1:
                logger.info(
                    f"Ambiguous match: {len(ambiguous_keywords)} keywords equally close "
                    f"(effective distance) to number '{number.raw_text}' "
                    f"at ~{min_effective_distance:.1f} chars: "
                    f"{', '.join(repr(k) for k in ambiguous_keywords[:5])}"
                )

        # Phase 5: Filter substring duplicates, deduplicate by metric, and add direction (L3)
        # Cross-metric substring suppression: when keywords from different metrics
        # overlap positionally AND one is a substring of the other, keep the longer match.
        matches: list[KeywordMatch] = []
        seen_metrics: set[str] = set()

        for kw, _raw_dist, _eff_dist in candidates_with_effective_distance:
            # Skip if we already have a match for this metric
            if kw.metric_id in seen_metrics:
                continue

            # Check if this keyword overlaps with any already-accepted keyword
            # and one is a substring of the other (cross-metric deduplication)
            is_substring_duplicate = False
            replace_index: int | None = None

            for i, accepted in enumerate(matches):
                if self._keywords_overlap(kw, accepted) and self._is_substring_match(
                    kw, accepted
                ):
                    # Overlapping substring match found - compare lengths
                    if len(kw.keyword) > len(accepted.keyword):
                        # New keyword is longer (more specific) - replace accepted
                        # Log at INFO for monitoring cross-metric suppression in production
                        logger.info(
                            f"CMS-1 cross-metric replacement: '{accepted.keyword}' "
                            f"({accepted.metric_id}) replaced by longer "
                            f"'{kw.keyword}' ({kw.metric_id})"
                        )
                        replace_index = i
                        # Remove old metric from seen so we can add new one
                        seen_metrics.discard(accepted.metric_id)
                    else:
                        # Accepted keyword is longer or equal - skip new one
                        # Log at INFO for monitoring cross-metric suppression in production
                        logger.info(
                            f"CMS-1 cross-metric suppression: '{kw.keyword}' "
                            f"({kw.metric_id}) suppressed by longer '{accepted.keyword}' "
                            f"({accepted.metric_id})"
                        )
                        is_substring_duplicate = True
                    break

            if not is_substring_duplicate:
                # L3: Compute direction relative to number
                direction = self.calculate_keyword_direction(kw.start, number.start)

                # Create new KeywordMatch with direction set
                match_with_direction = KeywordMatch(
                    start=kw.start,
                    end=kw.end,
                    keyword=kw.keyword,
                    metric_id=kw.metric_id,
                    pattern=kw.pattern,
                    direction=direction,
                )

                if replace_index is not None:
                    # Replace shorter keyword with longer one (cross-metric)
                    matches[replace_index] = match_with_direction
                else:
                    matches.append(match_with_direction)
                seen_metrics.add(kw.metric_id)

        return matches

    def _keywords_overlap(self, kw1: KeywordMatch, kw2: KeywordMatch) -> bool:
        """
        Check if two keyword matches overlap in position.

        Args:
            kw1: First keyword match
            kw2: Second keyword match

        Returns:
            True if keywords overlap, False otherwise
        """
        return not (kw1.end <= kw2.start or kw2.end <= kw1.start)

    def _is_substring_match(self, kw1: KeywordMatch, kw2: KeywordMatch) -> bool:
        """
        Check if kw1's keyword is a substring of kw2's keyword.

        Args:
            kw1: First keyword match
            kw2: Second keyword match

        Returns:
            True if kw1.keyword is a substring of kw2.keyword (case-insensitive)
        """
        kw1_lower = kw1.keyword.lower()
        kw2_lower = kw2.keyword.lower()
        return kw1_lower in kw2_lower or kw2_lower in kw1_lower

    def calculate_distance(self, number: NumberMatch, keyword: KeywordMatch) -> int:
        """
        Calculate character distance between number and keyword.

        Args:
            number: NumberMatch
            keyword: KeywordMatch

        Returns:
            Minimum distance in characters
        """
        return self.calculate_distance_from_positions(
            number.start, number.end, keyword.start, keyword.end
        )

    def calculate_distance_from_positions(
        self, n_start: int, n_end: int, k_start: int, k_end: int
    ) -> int:
        """
        Calculate distance between two spans.

        If spans overlap, distance is 0.
        Otherwise, distance is the gap between them.

        Args:
            n_start: Number start position
            n_end: Number end position
            k_start: Keyword start position
            k_end: Keyword end position

        Returns:
            Distance in characters
        """
        if n_end <= k_start:
            # Number is before keyword
            return k_start - n_end
        elif k_end <= n_start:
            # Keyword is before number
            return n_start - k_end
        else:
            # Overlapping
            return 0

    def calculate_keyword_direction(
        self, keyword_start: int, number_start: int
    ) -> str:
        """
        Calculate whether keyword appears before or after the number.

        Args:
            keyword_start: Keyword start position
            number_start: Number start position

        Returns:
            'before' if keyword appears before number,
            'after' if keyword appears after number,
            'at' if they start at the same position (edge case)
        """
        if keyword_start < number_start:
            return "before"
        elif keyword_start > number_start:
            return "after"
        else:
            return "at"

    def get_context_type(
        self,
        text: str,
        number_position: int,
        keyword_position: int,
        keyword_direction: str,
        boundaries: list["TextBoundary"] | None = None,
        segment_type: str | None = None,
    ) -> str:
        """
        Determine which context type applies to this keyword-number pair.

        This is used for E1 multiplier optimization to track which context
        triggered the multiplier selection.

        Args:
            text: Full text containing both keyword and number
            number_position: Character position of the number
            keyword_position: Character position of the keyword
            keyword_direction: 'before' or 'after' (from calculate_keyword_direction)
            boundaries: Optional list of TextBoundary objects
            segment_type: Optional segment type ('table', 'paragraph', etc.)

        Returns:
            Context type: 'table', 'parenthetical', 'bullet', 'copula', 'preposition', or 'default'
        """
        # For pre-value keywords, context doesn't affect multiplier (always 1.0)
        # But still track context for analysis

        # Priority 1: Table context (strongest signal)
        if segment_type == "table" or self._is_in_table(number_position, boundaries):
            return 'table'

        # Priority 2: Parenthetical text (strong signal for clarifications)
        if self._is_in_parentheses(number_position, text):
            return 'parenthetical'

        # Priority 3: Bullet points (strong signal for structured lists)
        if self._is_in_bullet_point(number_position, boundaries):
            return 'bullet'

        # Priority 4: Copula verb pattern (moderate signal)
        if self._has_copula_verb_between(
            text, min(keyword_position, number_position), max(keyword_position, number_position)
        ):
            return 'copula'

        # Priority 5: Prepositional phrase (moderate signal)
        if keyword_direction == "after" and self._has_preposition_after(text, number_position, keyword_position):
            return 'preposition'

        # Default: no special context
        return 'default'

    def get_context_multiplier(
        self,
        text: str,
        number_position: int,
        keyword_position: int,
        keyword_direction: str,
        boundaries: list["TextBoundary"] | None = None,
        segment_type: str | None = None,
    ) -> float:
        """
        Determine the appropriate multiplier based on textual context.

        This implements L4 Option C: context-dependent multipliers for post-value keywords.
        Different contexts have different patterns for where metrics appear relative to values.

        Args:
            text: Full text containing both keyword and number
            number_position: Character position of the number
            keyword_position: Character position of the keyword
            keyword_direction: 'before' or 'after' (from calculate_keyword_direction)
            boundaries: Optional list of TextBoundary objects
            segment_type: Optional segment type ('table', 'paragraph', etc.)

        Returns:
            Multiplier to apply to the effective distance (only for 'after' direction)
            - < 1.0: Penalize post-value keywords (prefer pre-value)
            - 1.0: No preference
            - > 1.0: Boost post-value keywords (prefer post-value)
        """
        # If context-dependent multipliers disabled, use base multiplier
        if not self.use_context_dependent_multipliers:
            return self.post_value_distance_multiplier

        # Only apply multiplier for post-value keywords
        if keyword_direction != "after":
            return 1.0  # No adjustment for pre-value keywords

        # Get context type and map to multiplier
        context_type = self.get_context_type(
            text, number_position, keyword_position, keyword_direction, boundaries, segment_type
        )

        # Map context type to multiplier
        context_multipliers = {
            'table': self.multiplier_tables,
            'parenthetical': self.multiplier_parenthetical,
            'bullet': self.multiplier_bullet_points,
            'copula': self.multiplier_copula_verb,
            'preposition': self.multiplier_preposition,
            'default': self.multiplier_default,
        }

        return context_multipliers.get(context_type, self.multiplier_default)

    def _is_in_parentheses(self, position: int, text: str) -> bool:
        """
        Check if a position is inside parentheses.

        Args:
            position: Character position to check
            text: Full text

        Returns:
            True if position is inside (...), False otherwise
        """
        # Count open parentheses before position
        text_before = text[:position]
        open_count = text_before.count("(") - text_before.count(")")

        # If more open than close, we're inside parentheses
        return open_count > 0

    def _is_in_table(
        self, position: int, boundaries: list["TextBoundary"] | None
    ) -> bool:
        """
        Check if a position is in a table boundary.

        Args:
            position: Character position to check
            boundaries: Optional list of boundaries

        Returns:
            True if position is in a table boundary, False otherwise
        """
        if boundaries is None:
            return False

        boundary = self._get_boundary_at_position(position, boundaries)
        if boundary is None:
            return False

        # Check if boundary type indicates table
        # Note: boundary_type might be "table" or have other indicators
        return getattr(boundary, "boundary_type", None) == "table"

    def _is_in_bullet_point(
        self, position: int, boundaries: list["TextBoundary"] | None
    ) -> bool:
        """
        Check if a position is in a bullet point boundary.

        Args:
            position: Character position to check
            boundaries: Optional list of boundaries

        Returns:
            True if position is in a bullet boundary, False otherwise
        """
        if boundaries is None:
            return False

        boundary = self._get_boundary_at_position(position, boundaries)
        if boundary is None:
            return False

        # Check if boundary type indicates bullet/list
        boundary_type = getattr(boundary, "boundary_type", None)
        return boundary_type in ("bullet", "numbered_list", "lettered_list")

    def _has_copula_verb_between(self, text: str, start: int, end: int) -> bool:
        """
        Check if there's a copula verb (is/was/were/are) between two positions.

        Copula verbs suggest subject-verb structure: "Gross margin was 33%"

        Args:
            text: Full text
            start: Start position
            end: End position

        Returns:
            True if copula verb found between positions, False otherwise
        """
        snippet = text[start:end].lower()
        # Match copula verbs with word boundaries
        copula_pattern = r"\b(is|was|were|are)\b"
        return bool(re.search(copula_pattern, snippet))

    def _has_preposition_after(
        self, text: str, number_position: int, keyword_position: int
    ) -> bool:
        """
        Check if there's a preposition (of/for/in) between number and keyword.

        Prepositions suggest the keyword is the object: "33% of revenue", "33% for margin"

        Args:
            text: Full text
            number_position: Number start position
            keyword_position: Keyword start position (must be after number)

        Returns:
            True if preposition found between number and keyword, False otherwise
        """
        if keyword_position <= number_position:
            return False

        # Check the gap between number and keyword (up to 50 chars)
        gap_start = number_position
        gap_end = min(number_position + 50, keyword_position + 10)
        snippet = text[gap_start:gap_end].lower()

        # Match common prepositions with word boundaries
        preposition_pattern = r"\b(of|for|in|from)\b"
        return bool(re.search(preposition_pattern, snippet))

    def _get_boundary_at_position(
        self, pos: int, boundaries: list["TextBoundary"]
    ) -> Optional["TextBoundary"]:
        """
        Find the boundary containing a position.

        Args:
            pos: Character position
            boundaries: List of TextBoundary objects

        Returns:
            The boundary containing the position, or None if not found
        """
        for boundary in boundaries:
            if boundary.contains_position(pos):
                return boundary
        return None

    def _is_in_same_boundary(
        self, pos: int, target_boundary: "TextBoundary", boundaries: list["TextBoundary"]
    ) -> bool:
        """
        Check if a position is in the same boundary as a target boundary.

        Args:
            pos: Character position to check
            target_boundary: The target boundary
            boundaries: List of all boundaries

        Returns:
            True if position is in the same boundary, False otherwise
        """
        boundary = self._get_boundary_at_position(pos, boundaries)
        return boundary is not None and boundary == target_boundary
```

## src/review/false_positive_filter.py

```python
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
from src.review.number_parsing import NumberMatch

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
    if '.' in raw_text and unit == 'count':
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

        # Check minimum value threshold (skip for percentages, currency, decimals, and spelled-out)
        # Decimals like 1.25 could be ratios (e.g., NRR of 125%)
        # Spelled-out numbers like "six" are intentionally written - likely meaningful
        if number.unit == "count" and value is not None:
            is_decimal = "." in number.raw_text
            if not is_decimal and not is_spelled_out_number(number.raw_text) and abs(float(value)) < self.min_value:
                return True, "below_min_value"

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

        if is_plain_count and is_integer_format and is_small_value and not is_spelled_out_number(number.raw_text):
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
```

## config/metric_keywords.yaml

```yaml
# Metric Keywords Configuration
# ==============================
# This file defines the keyword patterns used to identify customer metrics in SEC filings.
#
# Structure:
#   metric_id:
#     patterns: List of regex patterns (case-insensitive, use \b for word boundaries)
#     exclusions: Optional list of patterns that should NOT match this metric
#     specific_patterns: Optional list of multi-word patterns that get confidence bonus
#
# Notes:
# - All patterns are case-insensitive
# - Use \b for word boundaries to prevent partial matches
# - Use \s+ for flexible whitespace between words
# - Patterns are compiled with re.IGNORECASE
#
# To add a new metric:
# 1. Add a new metric_id key (use cm_ prefix for customer metrics)
# 2. Add patterns list with at least one regex pattern
# 3. Optionally add exclusions to prevent false positives
# 4. Optionally add specific_patterns for multi-word phrases that get bonus confidence

---
# =============================================================================
# Shared Context Requirements (YAML Anchors)
# =============================================================================
# Revenue synonym metrics require cohort or per-customer context to generate
# review candidates. Without this context, they are just revenue measures,
# not customer metrics. This anchor defines the shared context patterns.

_revenue_synonym_context: &revenue_synonym_context
  required_context:
    patterns:
      # Cohort keywords (from cohort_chart_detector.py)
      - '\bcohort\b'
      - '\bby\s+vintage\b'
      - '\bacquisition\s+year\b'
      - '\brevenue\s+(?:by|per)\s+cohort\b'
      - '\bretention\s+(?:by|per)\s+cohort\b'
      - '\bARR\s+(?:by|of\s+each)\s+cohort\b'
      - '\bLTV[/ ]CAC\b'
      # Per-customer keywords
      - '\bper\s+customer\b'
      - '\bper\s+user\b'
      - '\bper\s+account\b'
      - '\bper\s+subscriber\b'
      - '\bper\s+client\b'
      - '\baverage\s+per\b'
      - '\bby\s+customer\b'
      - '\bby\s+account\b'
      - '\bcustomer[- ]level\b'
      - '\baccount[- ]level\b'
    proximity_chars: 1500

# =============================================================================
# Core Metrics
# =============================================================================
# SEMANTIC DISTINCTIONS - Customer Count Metrics:
#   cm_customers_period_end: Stock count at period end ("total customers", "paid customers")
#   cm_active_customers_total: Engagement-based count ("active customers" - implies activity criteria)
#   These are DISTINCT metrics, not aliases. "Total" ≠ "Active"
# =============================================================================

cm_new_customers_acquired:
  patterns:
    - '\bnew\s+customers?\b'
    - '\bcustomers?\s+acquired\b'
    - '\bcustomer\s+acquisition[s]?\b'
    - '\bacquired\s+customers?\b'
    - '\bnewly\s+acquired\b'
    - '\bnew\s+customer\s+additions?\b'
    - '\bnet\s+new\s+customers?\b'
    - '\bcustomers?\s+added\b'
    - '\bacquisition\s+of\s+customers?\b'
    - '\bnew\s+users?\s+acquired\b'
    - '\bacquired\s+users?\b'
    - '\bnew\s+accounts?\s+acquired\b'
    - '\bnew\s+clients?\s+acquired\b'
    - '\bnew\s+logos?\b'
    # Consumer synonyms (e-commerce terminology)
    - '\bnew\s+consumers?\b'
    - '\bconsumers?\s+acquired\b'
    - '\bconsumer\s+acquisition[s]?\b'
    - '\bacquired\s+consumers?\b'
    - '\bconsumers?\s+added\b'
  exclusions:
    - '\bacquisition\s+cost\b'
    - '\bcac\b'
    - '\bcost\s+to\s+acquire\b'
    # FIX-FP: Exclude numbers followed by non-metric units (applications, integrations)
    - '\b\d[\d,]*(?:\s+[\w-]+){0,2}\s+(?:applications?|integrations?)\b'

cm_customers_period_end:
  # Period-end customer count (stock count at end of period)
  # Distinct from cm_active_customers_total which is engagement-based
  patterns:
    - '\bpaid\s+customers?\b'
    - '\bfree\s+(?:subscription\s+)?(?:plan\s+)?(?:organizations?|customers?)\b'
    - '\borganizations?\s+on\s+(?:our\s+)?free\s+(?:subscription\s+)?plan\b'
    - '\borganizations?\s+(?:with\s+)?(?:three|\d+)\s+(?:or\s+more\s+)?users?\b'
    - '\bcustomers?\s+\(?period\s*end\)?\b'
    - '\bend[- ]of[- ]period\s+customers?\b'
    - '\b(?:total\s+)?(?:paying|paid)\s+(?:organizations?|customers?)\b'
    - '\bactive\s+consumers?\b'
    # Total customer count patterns (moved from cm_active_customers_total 2026-01-07)
    # "Total customers" represents a stock count, not engagement-based "active" customers
    - '\btotal\s+customers?\b'
    - '\btotal\s+consumers?\b'
    - '\bcustomer\s+base\b'
    - '\bconsumer\s+base\b'
    - '\btotal\s+accounts?\b'
    - '\btotal\s+clients?\b'
  exclusions:
    - '\bretention\s+rate\b'
    - '\bnet\s+dollar\s+retention\b'
    - '\bndr\b'
    - '\bnrr\b'
    - '\b\d+%\s*(?:as\s+of|for|during)\b'
    # FIX-3: Exclude word-form numbers in non-customer contexts (languages, time periods, etc.)
    - '\b(?:eight|twelve|ten)\s+(?:languages?|months?|countries?|weeks?|days?)\b'
    - '\btrailing\s+twelve\s+months?\b'
    - '\bavailable\s+in\s+\w+\s+(?:languages?|countries?)\b'
    # FIX-FP: Exclude numbers followed by time units (e.g., "50 million hours")
    - '\b\d[\d,]*(?:\s+[\w-]+){0,2}\s+(?:hours?)\b'
  specific_patterns:
    - 'paid\s+customers?'
    - 'paying\s+customers?'
    - 'total\s+customers?'
    - 'total\s+consumers?'
    - 'customer\s+base'

cm_large_customers_period_end:
  patterns:
    - '\bpaid\s+customers?\s*>\s*\$[\d,]+'
    - '\bcustomers?\s*>\s*\$\d+(?:,\d+)*\s*(?:of\s+)?(?:arr|annual\s+recurring\s+revenue)\b'
    - '\blarge\s+(?:enterprise\s+)?customers?\b'
    - '\benterprise\s+customers?\b'
    - '\b\$\d+(?:,\d+)*(?:k|K)?\+?\s*arr\s+customers?\b'
    - '\bcustomers?\s+(?:with\s+)?(?:over|above|greater\s+than|>)\s*\$[\d,]+'
    - '\bpaid\s+customers?\s+(?:with|of)\s+\$[\d,]+\s*(?:\+|or\s+more)?'
  exclusions:
    - '\bretention\s+rate\b'
    - '\bnet\s+dollar\s+retention\b'
    - '\bndr\b'
    - '\bnrr\b'
    - '\b\d+%\s*(?:as\s+of|for|during)\b'
  specific_patterns:
    - 'enterprise\s+customers?'
    - 'large\s+customers?'

cm_customers_period_end_by_tenure:
  patterns:
    - '\bcustomers?\s+by\s+tenure\b'
    - '\btenure\s+cohort\b'
    - '\bcustomers?\s+at\s+period\s+end\b'
    - '\bby\s+age\b'
    - '\btime\s+since\b'

cm_revenue_by_cohort:
  patterns:
    - '\brevenue\s+by\s+cohort\b'
    - '\bcohort\s+revenue\b'
    - '\brevenue[^.;]{0,100}\bcohort\b'
    - '\bcohort[^.;]{0,100}\brevenue\b'

cm_transactions_by_cohort:
  patterns:
    - '\btransactions?\s+by\s+cohort\b'
    - '\bcohort\s+transactions?\b'
    - '\btransactions?[^.;]{0,100}\bcohort\b'
    # Orders variants for Farfetch terminology (orders = transactions)
    - '\borders?\s+by\s+cohort\b'
    - '\bcohort\s+orders?\b'
    - '\bnumber\s+of\s+orders?[^.;]{0,50}\bcohort\b'
  # NOTE: Plain 'number of orders' (without cohort) in cm_purchase_transactions_overall

cm_purchase_transactions_overall:
  patterns:
    - '\bnumber\s+of\s+orders?\b'
    - '\btotal\s+orders?\b'
    - '\bpurchase\s+transactions?\b(?!\s+by\s+cohort)'
    - '\border\s+count\b'
    - '\border\s+volume\b'
  exclusions:
    - '\bby\s+cohort\b'
    - '\bby\s+vintage\b'
  specific_patterns:
    - 'number\s+of\s+orders?'

# =============================================================================
# Extended Metrics
# =============================================================================

cm_active_customers_total:
  # "Active" customers implies engagement-based measurement (e.g., logged in, made purchase)
  # Distinct from "total" customers which is a simple headcount at period end
  # "Total" patterns moved to cm_customers_period_end (2026-01-07)
  patterns:
    - '\bactive\s+customers?\b'
    - '\bactive\s+consumers?\b'
    - '\bactive\s+accounts?\b'
    - '\bactive\s+clients?\b'
    - '\bactive\s+users?\b'
    - '\bactive\s+subscribers?\b'
  exclusions:
    # FIX-FP: Exclude numbers followed by non-metric units (hours, countries, languages)
    - '\b\d[\d,]*(?:\s+[\w-]+){0,2}\s+(?:hours?|countries?|languages?)\b'
  specific_patterns:
    - 'active\s+customers?'
    - 'active\s+consumers?'
    - 'active\s+accounts?'

cm_revenue_per_customer:
  patterns:
    - '\barpu\b'
    - '\baverage\s+revenue\s+per\s+user\b'
    - '\brevenue\s+per\s+customer\b'
    - '\brevenue\s+per\s+user\b'
    - '\bper\s+customer\s+revenue\b'
  exclusions:
    - '\bcost\s+per\s+customer\b'
    - '\bcost\s+per\s+user\b'
  specific_patterns:
    - 'average\s+revenue\s+per'

cm_customer_acquisition_cost:
  patterns:
    - '\bcac\b'
    - '\bcustomer\s+acquisition\s+cost\b'
    - '\bacquisition\s+cost\b'
    - '\bcost\s+to\s+acquire\b'
    # Consumer synonyms (e-commerce terminology)
    - '\bconsumer\s+acquisition\s+cost\b'
  exclusions:
    - '\bcontribution\s+margin\b'
    - '\bgross\s+margin\b'
    - '\bprofit\s+margin\b'
    - '\boperating\s+margin\b'
    - '\bplatform\s+order\s+contribution\b'
  specific_patterns:
    - 'customer\s+acquisition\s+cost'
    - 'consumer\s+acquisition\s+cost'

cm_cac_payback_period:
  patterns:
    - '\bcac\s+payback\b'
    - '\bpayback\s+period\b'
    - '\btime\s+to\s+recover\b'
    - '\bpayback\s+period\s+(?:on|for)\s+cac\b'
  specific_patterns:
    - 'payback period on CAC'
    - 'CAC payback period'

cm_customer_retention_rate:
  patterns:
    - '\bretention\s+rate\b'
    - '\bcustomer\s+retention\b'
    - '\bretained\s+customers?\b'
    # Consumer synonyms (e-commerce terminology)
    - '\bconsumer\s+retention\b'
    - '\bretained\s+consumers?\b'
  exclusions:
    - '\brevenue\s+retention\b'
    - '\bdollar\s+retention\b'
    - '\bnrr\b'
    - '\bgrr\b'

cm_customer_churn_rate:
  patterns:
    - '\bchurn\s+rate\b'
    - '\bcustomer\s+churn\b'
    - '\battrition\s+rate\b'
    # Consumer synonyms (e-commerce terminology)
    - '\bconsumer\s+churn\b'
    - '\bconsumer\s+attrition\b'

cm_net_revenue_retention:
  patterns:
    - '\bnrr\b'
    - '\bnet\s+revenue\s+retention\b'
    - '\bnet\s+retention\b'
    - '\bnet\s+dollar\s+retention\b'
    - '\bndr\b'
    - '\bretention\s+rate[^.;]{0,50}\d+%'
    - '\bnet\s+retention\s+rate\b'
  specific_patterns:
    - 'net\s+revenue\s+retention'
    - 'net\s+dollar\s+retention'

cm_gross_revenue_retention:
  patterns:
    - '\bgrr\b'
    - '\bgross\s+revenue\s+retention\b'
    - '\bgross\s+retention\b'
  specific_patterns:
    - 'gross\s+revenue\s+retention'

cm_monthly_active_users:
  patterns:
    - '\bmau\b'
    - '\bmonthly\s+active\s+users?\b'
  specific_patterns:
    - 'monthly\s+active\s+users?'

cm_daily_active_users:
  patterns:
    - '\bdau\b'
    - '\bdaily\s+active\s+users?\b'
  exclusions:
    # FIX-FP: Exclude numbers followed by non-metric units (applications, countries, languages)
    - '\b\d[\d,]*(?:\s+[\w-]+){0,2}\s+(?:applications?|countries?|languages?|integrations?)\b'
  specific_patterns:
    - 'daily\s+active\s+users?'

cm_gross_margin_by_cohort:
  # Only patterns that explicitly require "cohort" or "vintage" context
  # REMOVED (2026-01-02): '\border\s+contribution\s+margin\b' and
  # '\bplatform\s+order\s+contribution(?:\s+margin)?\b' - not cohort-specific
  patterns:
    - '\bgross\s+margin\s+by\s+cohort\b'
    - '\bcohort\s+(?:gross\s+)?margin\b'
    - '\bmargin\s+by\s+(?:acquisition\s+)?(?:vintage|cohort)\b'

cm_arr:
  patterns:
    - '\barr\b'
    - '\bannual\s+recurring\s+revenue\b'
    - '\bannualized\s+recurring\s+revenue\b'
    - '\bannual\s+run[- ]?rate\b'
  specific_patterns:
    - 'annual\s+recurring\s+revenue'

cm_mrr:
  patterns:
    - '\bmrr\b'
    - '\bmonthly\s+recurring\s+revenue\b'
  specific_patterns:
    - 'monthly\s+recurring\s+revenue'

cm_expansion_revenue:
  patterns:
    - '\bexpansion\s+revenue\b'
    - '\bcross[- ]sell\b'
    - '\bupsell\b'
    - '\bproducts?\s+per\s+customer\b'
    - '\baverage\s+products?\s+owned\b'
    - '\bexpand\b[^.;]{0,100}\brevenue\b'
    - '\badditional\s+products?\b'
    - '\bmulti[- ]product\b'

cm_revenue_concentration:
  patterns:
    - '\brevenue\s+concentration\b'
    - '\bcustomer\s+concentration\b'
    - '\btop\s+\d+\s+customers?\b'
    - '\blargest\s+customers?\b'
    - '\b\d+%\s+of\s+revenue\b'
    - '\bconcentration\s+risk\b'
    - '\bconcentration\s+of\s+revenue\b'
    - '\bmajor\s+customers?\b'
    - '\bcustomer\s+[A-D]\b'

# =============================================================================
# Revenue Predictability Metrics (DEPRECATED 2026-01-07)
# =============================================================================
# These are financial metrics, not customer metrics unless cohort-specific.
# Patterns retained for historical data interpretation but metrics are deprecated
# in the database and excluded from UI dropdowns.

cm_bookings:
  # DEPRECATED 2026-01-07: Financial metric, not customer metric unless cohort-specific
  <<: *revenue_synonym_context
  patterns:
    - '\bbookings\b'
    - '\btotal\s+bookings\b'
    - '\bnew\s+bookings\b'
    - '\bcontract\s+bookings\b'
    - '\bnet\s+new\s+bookings\b'
    - '\bquarterly\s+bookings\b'
    - '\bannual\s+bookings\b'

cm_billings:
  status: deprecated
  deprecation_reason: "GAAP financial metric, not customer-specific. Use ARR/MRR for recurring revenue metrics."
  # DEPRECATED 2026-01-07: Financial metric, not customer metric unless cohort-specific
  <<: *revenue_synonym_context
  patterns:
    - '\bbillings\b'
    - '\btotal\s+billings\b'
    - '\bcalculated\s+billings\b'
    - '\badjusted\s+billings\b'
  exclusions:
    # Cash flow metrics (from Slack table - these appear in same segment as "Calculated Billings")
    - '\bfree\s+cash\s+flows?\b'
    - '\badjusted\s+free\s+cash\s+flows?\b'
    - '\bcash\s+flows?\b'
    - '\boperating\s+(?:activities|cash|assets)\b'
    - '\bnet\s+loss\b'
    # Cash flow statement line items (common accounting terms)
    - '\bnon[- ]cash\s+charges?\b'
    - '\bdepreciation\s+and\s+amortization\b'
    - '\bstock[- ]based\s+compensation\b'
    - '\baccounts\s+(?:payable|receivable)\b'
    - '\bprepaid\s+expenses?\b'
    - '\baccrued\s+expenses?\b'
    # Tender offer / compensation items
    - '\btender\s+offer\b'
    - '\brepurchases?\s+deemed\s+compensation\b'
    # Revenue line items (general financial statements)
    - '\brevenue\b'
    - '\bdeferred\s+revenue\b'
    - '\bcost\s+of\s+(?:revenue|sales)\b'
    - '\bnet\s+revenue\b'
    # Period markers (accounting context)
    - '\b(?:beginning|end)\s+of\s+period\b'

# =============================================================================
# E-Commerce / Consumer Metrics
# =============================================================================

cm_average_order_value:
  patterns:
    - '\baov\b'
    - '\baverage\s+order\s+value\b'
    - '\baverage\s+order\s+size\b'
    - '\baverage\s+ticket\s+(?:size|value)?\b'
    - '\baverage\s+basket\s+(?:size|value)?\b'
    - '\border\s+value\s+per\s+(?:customer|user|transaction)\b'
    - '\baverage\s+transaction\s+value\b'

cm_repeat_purchase_rate:
  patterns:
    - '\brepeat\s+purchase\s+rate\b'
    - '\brepeat\s+purchase(?:s)?\b'
    - '\bpurchase\s+frequency\b'
    - '\brepeat\s+customers?\b'
    - '\brepeat\s+buyers?\b'
    - '\brepeat\s+order\s+rate\b'
    - '\breorder\s+rate\b'
    - '\brepurchase\s+rate\b'

# =============================================================================
# Marketplace / Platform Metrics (DEPRECATED 2026-01-07)
# =============================================================================
# GMV is a financial metric, not a customer metric unless cohort-specific.
# Patterns retained for historical data interpretation but metric is deprecated.

cm_gmv:
  # DEPRECATED 2026-01-07: Financial metric, not customer metric unless cohort-specific
  <<: *revenue_synonym_context
  patterns:
    - '\bgmv\b'
    - '\bgross\s+merchandise\s+value\b'
    - '\bgross\s+merchandise\s+volume\b'
    - '\bgross\s+booking\s+value\b'
    - '\bgross\s+bookings\s+value\b'
    - '\bgross\s+transaction\s+value\b'
    - '\btotal\s+transaction\s+value\b'
    - '\bgross\s+order\s+value\b'
    - '\bplatform\s+(?:transaction\s+)?volume\b'

# cm_take_rate: REMOVED (2026-01-02)
# Rationale: Take rate is a platform/marketplace revenue metric, not a customer metric.
# It measures the platform's revenue percentage, not customer behavior or value.

# =============================================================================
# SaaS Contract Metrics (DEPRECATED 2026-01-07)
# =============================================================================
# These are financial metrics, not customer metrics unless cohort-specific.
# Patterns retained for historical data interpretation but metrics are deprecated.

cm_acv:
  # DEPRECATED 2026-01-07: Financial metric, not customer metric unless cohort-specific
  <<: *revenue_synonym_context
  patterns:
    - '\bacv\b'
    - '\bannual\s+contract\s+value\b'
    - '\baverage\s+contract\s+value\b'
    - '\bannualized\s+contract\s+value\b'
    - '\baverage\s+annual\s+contract\b'
    - '\bcontract\s+value\s+per\s+customer\b'

cm_tcv:
  # DEPRECATED 2026-01-07: Financial metric, not customer metric unless cohort-specific
  <<: *revenue_synonym_context
  patterns:
    - '\btcv\b'
    - '\btotal\s+contract\s+value\b'
    - '\blifetime\s+contract\s+value\b'
    - '\bcontract\s+lifetime\s+value\b'

# =============================================================================
# Customer Value Metrics
# =============================================================================

cm_lifetime_value_per_customer:
  patterns:
    - '\bltv\b'
    - '\blifetime\s+value\b'
    - '\bcustomer\s+lifetime\s+value\b'
    - '\bclv\b'
    # Consumer synonyms and alternate phrasings
    - '\bconsumer\s+lifetime\s+value\b'
    - '\blifetime\s+value\s+of\s+a\s+(?:customer|consumer)\b'
  exclusions:
    - '\bltv\s*/\s*cac\b'
    - '\bltv\s+to\s+cac\b'
    - '\blifetime\s+value\s+to\s+(?:customer\s+)?acquisition\s+cost\b'
  specific_patterns:
    - 'lifetime\s+value'
    - 'customer\s+lifetime\s+value'
    - 'consumer\s+lifetime\s+value'
    - 'lifetime\s+value\s+of\s+a'

cm_ltv_to_cac_ratio:
  patterns:
    - '\bltv\s*[:/]\s*cac(?:\s+ratio)?\b'
    - '\bltv\s+to\s+cac(?:\s+ratio)?\b'
    - '\blifetime\s+value\s+to\s+acquisition\s+cost\b'

cm_ltv_to_cac_ratio_by_cohort:
  # LTV/CAC ratio analyzed by acquisition cohort (added 2026-01-07)
  patterns:
    - '\bltv\s*[:/]\s*cac\s+by\s+cohort\b'
    - '\bltv\s+to\s+cac\s+(?:ratio\s+)?by\s+cohort\b'
    - '\bcohort\s+ltv\s*[:/]\s*cac\b'
    - '\bltv[:/]cac[^.;]{0,50}\bcohort\b'
    - '\bcohort[^.;]{0,50}\bltv[:/]cac\b'
  specific_patterns:
    - 'ltv\s*[:/]\s*cac\s+by\s+cohort'
    - 'cohort\s+ltv\s*[:/]\s*cac'

# =============================================================================
# Growth Metrics - INTENTIONALLY NOT DETECTED
# =============================================================================
# Decision (2026-01-02): Growth metrics are not tracked separately because:
# 1. They always appear alongside base metrics (e.g., "1.1M customers, up 57%")
# 2. Growth can be calculated from period-over-period base metric values
# 3. Detecting both creates duplicate/confusing review candidates
#
# Previously removed metrics:
# - cm_active_customers_growth
# - cm_purchase_transactions_overall_growth
# =============================================================================
```
