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
from typing import List, Optional, Tuple, TYPE_CHECKING
from bs4 import BeautifulSoup

from .models import SourceSegment, MetricValue
from ..review.false_positive_filter import FalsePositiveFilter
from ..review.number_parsing import NumberMatch
from ..review.table_structure import TableRowParser

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
    "customers_period_end": "cm_customers_period_end_by_tenure",
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

    # Extended metrics - customer counts specific
    "paid_customers": "cm_customers_period_end",
    "total_paid_customers": "cm_customers_period_end",
    "paid_customer_count": "cm_customers_period_end",
    
    "paid_customers_100k": "cm_large_customers_period_end",
    "paid_customers_100k+": "cm_large_customers_period_end",
    "customers_over_100k": "cm_large_customers_period_end",
    "large_customers": "cm_large_customers_period_end",
}

# Create reverse mapping for validation
VALID_METRIC_IDS = set(METRIC_NAME_MAPPING.values())


def map_llm_name_to_metric_id(
    llm_name: str,
    candidate_metric_ids: Optional[List[str]] = None
) -> Optional[str]:
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


def _normalize_text(text: Optional[str]) -> str:
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
        position: Optional[int],
        context_text: str,
        unit: Optional[str] = None
    ) -> Tuple[bool, Optional[str]]:
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
    ) -> List[MetricValue]:
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
    ) -> List[MetricValue]:
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
        row_parser: Optional[TableRowParser] = None
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
    ) -> List[MetricValue]:
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
        def is_excluded(start: int, end: int, exclusions: List[Tuple[int, int]]) -> bool:
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
    ) -> List[MetricValue]:
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
                    validate_extraction,
                    should_reject_extraction,
                    get_rejection_reason,
                    validate_quote_contains_metric_keyword,
                    ValidationResult,
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
    ) -> List[MetricValue]:
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
                    validate_extraction,
                    should_reject_extraction,
                    get_rejection_reason,
                    validate_quote_contains_metric_keyword,
                    ValidationResult,
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

    def _identify_columns(self, headers: List[str]) -> dict:
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
        headers: List[str],
        column_info: dict,
        segment: SourceSegment,
        company_id: int,
        row_parser: Optional[TableRowParser] = None,
    ) -> List[MetricValue]:
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
                    if row_metric_id: break
            
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

    def _infer_metric_from_context(self, segment: SourceSegment, headers: List[str], column_index: int) -> Optional[str]:
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
            if "revenue" in header and "cohort" in header: return "cm_revenue_by_cohort"
            if "transaction" in header and "cohort" in header: return "cm_transactions_by_cohort"
            if "customer" in header and "tenure" in header: return "cm_customers_period_end_by_tenure"
            
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

    def _infer_unit(self, value_text: str, metric_id: str) -> Optional[str]:
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

    def parse_cohort_label(self, raw_label: str) -> Tuple[Optional[str], Optional[str]]:
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

    def _parse_number(self, text: str) -> Optional[Decimal]:
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

    def _extract_period_from_text(self, text: str) -> Optional[date]:
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
def extract_values(segment: SourceSegment, company_id: int) -> List[MetricValue]:
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
