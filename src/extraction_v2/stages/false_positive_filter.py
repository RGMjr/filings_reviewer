"""
V2 False Positive Filter Stage

Stage 7.5 of the V2 extraction pipeline. Runs between value binding (Stage 7)
and period inference (Stage 8) to remove false positive BoundValues.

Two-layer filtering:
1. V1 FalsePositiveFilter (positional date/reference/year/label overlap)
2. V2-native rules that exploit richer pipeline context:
   - Year values for ALL unit types (V1 only filters unit=count)
   - Linearized table text detection ([CELL]/[ROW] markers)
   - Financial table annotations ("In thousands", "stock-based compensation")
   - Company ranking names ("Fortune 100", "Forbes 500")

Design principles:
- Reuse V1 filters (single source of truth for shared logic)
- V2-native rules address gaps the V1 positional filter can't catch
- Log filter statistics per reason for diagnostics
- Non-destructive: only removes BoundValues from context.bound_values
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable
from datetime import UTC, datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from src.extraction_v2.exceptions import V2FatalError
from src.extraction_v2.models import BoundValue, SectionType, Unit
from src.extraction_v2.stages.value_binding import (
    _FINANCIAL_LINE_ITEM_STUB_ALLOW,
    _FINANCIAL_LINE_ITEM_STUB_RE,
)
from src.extraction_v2.unit_compatibility import _PERCENT_ONLY_METRICS
from src.review.false_positive_filter import FalsePositiveFilter
from src.review.number_parsing import NumberMatch

if TYPE_CHECKING:
    from src.extraction_v2.models import Segment, Table
    from src.extraction_v2.pipeline import PipelineContext, StageResult

logger = logging.getLogger(__name__)


# =============================================================================
# V2-native False Positive Patterns
# =============================================================================

_YEAR_MIN = 1990
_YEAR_MAX = 2100

# Financial table annotation — "(In thousands)", "(In millions)", "($ in thousands)", etc.
_FINANCIAL_ANNOTATION_RE = re.compile(
    r"\(\s*\$?\s*in\s+(?:thousands|millions|billions|hundreds)\s*\)",
    re.IGNORECASE,
)

# Stock-based compensation footnote — strong financial context signal
_SBC_RE = re.compile(r"stock[- ]based\s+compensation", re.IGNORECASE)

# Linearized table markers injected by the ingestion stage
_TABLE_MARKER_RE = re.compile(r"\[(?:CELL|ROW)\]")

# Company ranking names — "Fortune 100", "Forbes 500", "Global 2000", etc.
_RANKING_NAME_RE = re.compile(
    r"\b(?:Fortune|Forbes|Inc\.?|Global)\s+(\d[\d,]*)\b",
    re.IGNORECASE,
)

# Scale suffixes that indicate a raw value represents a large number
# (e.g., "3 million", "1.5 billion", "400,000").  Bare single/double-digit
# numbers without these suffixes are almost always noise in transcript text
# (slide numbers, quarter refs like "Q4", "5G", multipliers like "4 times").
_HAS_SCALE_SUFFIX_RE = re.compile(
    r"(?:million|billion|thousand|,\d{3})", re.IGNORECASE
)

_BARE_SMALL_NUMBER_THRESHOLD = 50
# Prepared-remarks sections in transcript mode: raise the threshold to 400 to
# suppress product-name-embedded numbers like "M365" → 365 and "Dynamics 365" → 365.
# No gold standard ACCEPT count values fall in the 50-400 range for prepared_remarks.
_BARE_SMALL_NUMBER_THRESHOLD_PREPARED = 400
# Q&A sections are noisier — analyst-repeated figures, basis points, financial refs.
# Raise the bare-count threshold to 500 to suppress these without hurting recall
# (all Q&A ACCEPT count values have scale suffixes or are >= 500).
_BARE_SMALL_NUMBER_THRESHOLD_QA = 500

# Metrics that are inherently user/activity counts — never currency.
# A dollar value bound to these metrics is always a false positive
# (e.g., "$224 million" extracted as cm_monthly_active_users).
# Used for percent-rejection in _rule_percent_on_count_metric (MAU/DAU have
# a special YoY escape hatch, so other count metrics are listed separately).
_COUNT_ONLY_METRICS = frozenset({
    "cm_monthly_active_users",
    "cm_daily_active_users",
    "cm_active_customers_total",
    "cm_customers_period_end",
    "cm_new_customers_acquired",
    "cm_large_customers_period_end",
})

# Extended set for currency-unit rejection: adds metrics where dollar values
# are always FPs but percent growth rates may appear in transcripts (so they
# are not gated by _COUNT_ONLY_METRICS percent check above).
_DOLLAR_REJECT_METRICS = _COUNT_ONLY_METRICS | frozenset({
    "cm_customers_period_end_by_tenure",
    "cm_purchase_transactions_overall",
    "cm_transactions_by_cohort",
    "cm_cac_payback_period",
})

# Retention metrics that can legitimately co-occur in the same filing segment.
# GRR, NRR, and customer retention rate measure different retention concepts
# and should not be cross-metric-deduped against each other.
_RETENTION_FAMILY = frozenset({
    "cm_gross_revenue_retention",
    "cm_net_revenue_retention",
    "cm_customer_retention_rate",
})

# Metrics whose values (percentages, ratios, small counts) are semantically
# incompatible with financial statement line items. V1 financial_line_item
# positional checks can fire for these metrics when they appear near financial
# tables, but the extracted values can never be revenue, cost, or balance-sheet
# amounts. Override V1 fp classification for this set.
_V1_FINANCIAL_OVERRIDE_METRICS = frozenset({
    "cm_repeat_purchase_rate",
    "cm_customer_retention_rate",
    "cm_customer_churn_rate",
    "cm_net_revenue_retention",
    "cm_gross_revenue_retention",
    "cm_ltv_to_cac_ratio",
    "cm_ltv_to_cac_ratio_by_cohort",
    "cm_cac_payback_period",
})

# Metrics where percent values need conjunction-clause gating (relaxed mode).
# In transcript text like "TPV grew 50% and MAAs grew 30%", both values
# fall in the 400-char proximity window, but only "30%" belongs to MAU.
_PERCENT_CLAUSE_GATE_METRICS = frozenset({
    "cm_monthly_active_users",
    "cm_daily_active_users",
})

# Conjunction/clause boundary pattern for splitting compound sentences.
_CONJUNCTION_RE = re.compile(r"\b(?:and|or|but|while)\b|;", re.IGNORECASE)

# Geographic revenue context — "international", "domestic", "geographic" etc.
# Used to suppress cm_revenue_concentration FPs from geographic revenue breakdowns.
_GEOGRAPHIC_REVENUE_RE = re.compile(
    r"\b(?:international|domestic|geographic|geography|united\s+states|north\s+america|americas|emea|apac|"
    r"asia[- ]pacific|europe|rest\s+of\s+(?:the\s+)?world)\b",
    re.IGNORECASE,
)

# CapEx context — "capex", "capital expenditure", "opex" etc.
# Used to suppress cm_revenue_concentration FPs from CapEx-as-%-of-revenue sentences
# (e.g., "CapEx for the fiscal year to be approximately 2% of revenue").
_CAPEX_REVENUE_RE = re.compile(
    r"\b(?:cap(?:ex|ital\s+expenditure)s?|opex|depreciation|amortization)\b",
    re.IGNORECASE,
)

# Cost-structure revenue context — "cost of revenue", "gross margin", etc.
# Used to suppress cm_revenue_concentration FPs where a percent appears in the
# context of cost structure analysis rather than customer revenue concentration.
_COST_STRUCTURE_REVENUE_RE = re.compile(
    r"\b(?:cost\s+(?:of\s+)?revenue|cost\s+structure|"
    r"(?:adjusted\s+)?(?:gross\s+)?margin|"
    r"(?:component|portion)\s+of\s+(?:total\s+)?(?:cost|revenue)|"
    r"guidance\s+range)\b",
    re.IGNORECASE,
)

# Repeat customer purchase rate context.
# "Repeat customers accounted for approximately 72% of net sales" describes
# the share of revenue from repeat purchasers — this is cm_repeat_purchase_rate,
# not customer revenue concentration. The cm_revenue_concentration keyword
# pattern matches "accounted for approximately X%" broadly, creating a
# false positive when the subject is "repeat customers" rather than a named
# customer entity.
_REPEAT_CUSTOMER_REVENUE_RE = re.compile(
    r"\b(?:repeat|existing|loyal|returning)\s+customers?\b",
    re.IGNORECASE,
)

# Developer/engineer count context.
# Used to suppress cm_daily_active_users FPs from developer registration counts.
_DEVELOPER_COUNT_RE = re.compile(
    r"\b(?:registered\s+)?(?:developers?|engineers?|api\s+users?|third[- ]party\s+developers?)\b",
    re.IGNORECASE,
)

# "per share" context — stock price references like "$67 per share".
# Used to suppress cm_revenue_per_customer / cm_average_order_value FPs from
# equity price mentions in Q&A sections.
_PER_SHARE_RE = re.compile(r"\bper\s+share\b", re.IGNORECASE)

# "N of the Fortune M" or "N of the Forbes M" — a subset-of-ranking phrase.
# Used to suppress cm_customers_period_end FPs from Fortune 100 company counts.
_FORTUNE_SUBSET_RE = re.compile(
    r"\bof\s+(?:the\s+)?(?:Fortune|Forbes)\s+\d+\b",
    re.IGNORECASE,
)

# Subscription tier qualifier keywords.
# Used to suppress cm_customers_period_end FPs from per-tier customer counts
# (e.g., Snowflake's Free/Standard/Enterprise/Business Critical tier breakdowns).
_TIER_QUALIFIER_RE = re.compile(
    r"\b(?:Free|Standard|Enterprise|Premium|Essentials|Business\s+Critical|VPS)\b",
    re.IGNORECASE,
)

# Dollar threshold customer qualifier — "Paid Customers >$100,000" or similar.
# Used to suppress FPs when a cell/proximity value comes from a threshold-qualified
# large-customer row (e.g., Slack's ">$100K ARR" rows) that should map to
# cm_large_customers_period_end, not cm_customers_period_end or NRR.
_DOLLAR_THRESHOLD_CUSTOMER_RE = re.compile(
    r"(?:Paid\s+)?[Cc]ustomers?\s*[>≥]\s*\$[\d,]+",
    re.IGNORECASE,
)

# Leading-zero number fragment — "018", "019", etc. from proximity window cutting "2018", "2019".
_LEADING_ZERO_RE = re.compile(r"^0\d{1,2}$")

# Q&A hedging language — analysts often speculate or ask about percentages
# without asserting them ("was it 20%?", "assuming 15% growth", etc.).
# These are false positives when a percent value is nearby.
_QA_HEDGING_RE = re.compile(
    r"\b(?:was\s+it|is\s+that|assuming|expect(?:ed|s|ing)?|guidance|outlook|"
    r"if\s+we|do\s+you|would\s+(?:you|that)|could\s+(?:you|that)|"
    r"are\s+you|what\s+(?:about|is|are|was)|thinking\s+about)\b",
    re.IGNORECASE,
)


def _is_percent_in_keyword_clause(
    source_text: str,
    keyword_span: tuple[int, int] | None,
    value_raw: str,
) -> bool:
    """
    Check if a percent value is in the same conjunction clause as the keyword.

    Splits text on conjunctions (and, or, but, while, ;) and verifies
    both the keyword and value fall in the same clause.

    Returns True (keep) if:
    - They are in the same clause
    - The text has no conjunctions (single clause — conservative)
    - Positions can't be determined (fail open)
    """
    kw_pos = keyword_span[0] if keyword_span else None
    if kw_pos is None:
        return True  # Can't determine keyword position; fail open

    val_pos = source_text.find(value_raw)
    if val_pos < 0:
        return True  # Can't find value in text; fail open

    conjunctions = list(_CONJUNCTION_RE.finditer(source_text))
    if not conjunctions:
        return True  # Single clause — keep (conservative)

    # Build clause boundaries from conjunction positions
    boundaries = [0]
    for m in conjunctions:
        boundaries.append(m.start())
    boundaries.append(len(source_text))

    # Find which clause each position falls in
    kw_clause = None
    val_clause = None
    for i in range(len(boundaries) - 1):
        start, end = boundaries[i], boundaries[i + 1]
        if start <= kw_pos < end:
            kw_clause = i
        if start <= val_pos < end:
            val_clause = i

    if kw_clause is None or val_clause is None:
        return True  # Can't determine; fail open

    return kw_clause == val_clause


def _locate_value(bv: BoundValue, source_text: str) -> tuple[str, int] | None:
    """Return (raw_value, position) or None if value cannot be located."""
    raw = (bv.value_raw or "").strip()
    if not raw:
        return None
    pos = source_text.find(raw)
    if pos < 0:
        return None
    return raw, pos


# =============================================================================
# Individual FP Rule Functions
# Each returns a reason string if it fires, None otherwise.
# Signature: (bv: BoundValue, source_text: str, metric_id: str) -> str | None
# =============================================================================


def _rule_year_value(bv: BoundValue, source_text: str, metric_id: str) -> str | None:
    """Year value for ALL units (V1 only filters unit=count)."""
    if bv.value is not None and _YEAR_MIN <= bv.value <= _YEAR_MAX:
        raw = (bv.value_raw or "").strip()
        stripped = raw.replace(",", "")
        if stripped.isdigit() and len(stripped) == 4:
            return "v2_year_value"
    return None


def _rule_percent_range(bv: BoundValue, source_text: str, metric_id: str) -> str | None:
    """Percentage-only metrics should have values in 0-500 range."""
    if bv.value is not None and metric_id in _PERCENT_ONLY_METRICS:
        if bv.value > 500 or bv.value < 0:
            return "v2_percent_range"
    return None


def _rule_garbage_value(bv: BoundValue, source_text: str, metric_id: str) -> str | None:
    """Numbers with >10 digits are almost certainly parsing artifacts."""
    if bv.value is not None and abs(bv.value) > 10_000_000_000:
        return "v2_garbage_value"
    return None


def _rule_year_fragment(bv: BoundValue, source_text: str, metric_id: str) -> str | None:
    """Leading-zero fragments like '018' from proximity window cutting '2018'."""
    raw = (bv.value_raw or "").strip()
    if raw and _LEADING_ZERO_RE.match(raw):
        return "v2_year_fragment"
    return None


def _rule_truncated_year(bv: BoundValue, source_text: str, metric_id: str) -> str | None:
    """Catch digit fragments from two patterns:

    1. Embedded in a longer contiguous digit run — e.g. "20" inside "2023" when
       the proximity window sliced the year. Adjacent-digit check is a strict
       correctness guard: a sub-span of a digit run is never a valid number.

    2. Two-digit fiscal-year column header — e.g. "20", "21", "22", "23" from
       a table header row like "| 20 | 21 | 22 | 23 |". Requires [CELL]/[ROW]
       markers and a sequential neighbor (N±1) in the same source_text.
    """
    if bv.unit != Unit.COUNT:
        return None
    raw = (bv.value_raw or "").strip()
    if not raw or not raw.isdigit():
        return None

    raw_escaped = re.escape(raw)
    occurrences = [m.start() for m in re.finditer(raw_escaped, source_text)]
    if occurrences:
        all_embedded = True
        for pos in occurrences:
            end = pos + len(raw)
            before = source_text[pos - 1] if pos > 0 else ""
            after = source_text[end] if end < len(source_text) else ""
            if not (before.isdigit() or after.isdigit()):
                all_embedded = False
                break
        if all_embedded:
            return "v2_truncated_year"

    if len(raw) == 2 and bv.value is not None and 15 <= bv.value <= 35:
        if _TABLE_MARKER_RE.search(source_text):
            n = int(raw)
            prev_str = str(n - 1).zfill(2)
            next_str = str(n + 1).zfill(2)
            if re.search(rf"\b{re.escape(prev_str)}\b", source_text) or \
               re.search(rf"\b{re.escape(next_str)}\b", source_text):
                return "v2_two_digit_year_header"

    return None


# Metrics that should never take negative values (counts, rates, ratios, currencies).
# Negative values on these metrics are almost always year fragments (e.g., -2019)
# or parsing artifacts from context windows containing subtraction expressions.
_POSITIVE_ONLY_METRICS: frozenset[str] = frozenset(
    {
        "cm_customers_period_end",
        "cm_active_customers_total",
        "cm_new_customers_acquired",
        "cm_large_customers_period_end",
        "cm_monthly_active_users",
        "cm_daily_active_users",
        "cm_average_order_value",
        "cm_repeat_purchase_rate",
        "cm_purchase_transactions_overall",
        "cm_revenue_per_customer",
        "cm_customer_acquisition_cost",
        "cm_lifetime_value_per_customer",
        "cm_ltv_to_cac_ratio",
        "cm_customer_retention_rate",
        "cm_net_revenue_retention",
        "cm_gross_revenue_retention",
    }
)


def _rule_negative_value(
    bv: BoundValue, source_text: str, metric_id: str
) -> str | None:
    """Block negative values on metrics that are definitionally non-negative.

    Negative metric values arise when a proximity window captures a subtraction
    expression (e.g., "2019" appearing after a minus sign) or when a year-like
    number is extracted with incorrect sign. Customer counts, rates, ratios, and
    per-customer currency values cannot be negative.
    """
    if metric_id not in _POSITIVE_ONLY_METRICS:
        return None
    if bv.value is not None and bv.value < 0:
        return "v2_negative_value"
    return None


def _rule_linearized_table(bv: BoundValue, source_text: str, metric_id: str) -> str | None:
    """Text with [CELL]/[ROW] markers is a linearized table duplicate."""
    if source_text and _TABLE_MARKER_RE.search(source_text):
        return "v2_linearized_table"
    return None


def _rule_financial_annotation(bv: BoundValue, source_text: str, metric_id: str) -> str | None:
    """Financial table annotations like '(In thousands)' near the value."""
    if not source_text or bv.source_locator.table_id is not None:
        return None
    raw = (bv.value_raw or "").strip()
    value_pos = source_text.find(raw) if raw else -1
    ann_match = _FINANCIAL_ANNOTATION_RE.search(source_text)
    if ann_match:
        if value_pos < 0 or abs(ann_match.start() - value_pos) <= 300:
            return "v2_financial_annotation"
    return None


def _rule_financial_sbc(bv: BoundValue, source_text: str, metric_id: str) -> str | None:
    """Stock-based compensation footnotes near the value."""
    if not source_text or bv.source_locator.table_id is not None:
        return None
    raw = (bv.value_raw or "").strip()
    value_pos = source_text.find(raw) if raw else -1
    sbc_match = _SBC_RE.search(source_text)
    if sbc_match:
        if value_pos < 0 or abs(sbc_match.start() - value_pos) <= 300:
            return "v2_financial_sbc"
    return None


def _rule_ranking_name(bv: BoundValue, source_text: str, metric_id: str) -> str | None:
    """Company ranking names like 'Fortune 100', 'Forbes 500'."""
    if not source_text:
        return None
    raw = (bv.value_raw or "").strip()
    if raw:
        for m in _RANKING_NAME_RE.finditer(source_text):
            if m.group(1) == raw:
                return "v2_ranking_name"
    return None


def _rule_per_share(bv: BoundValue, source_text: str, metric_id: str) -> str | None:
    """Stock price context — 'per share' near a currency value for ARPU/AOV metrics."""
    if bv.unit != Unit.CURRENCY:
        return None
    if metric_id not in {"cm_revenue_per_customer", "cm_average_order_value"}:
        return None
    if not source_text:
        return None
    match = _PER_SHARE_RE.search(source_text)
    if match:
        raw = (bv.value_raw or "").strip()
        value_pos = source_text.find(raw) if raw else -1
        if value_pos < 0 or abs(match.start() - value_pos) <= 150:
            return "v2_per_share"
    return None


def _rule_revenue_concentration_context(bv: BoundValue, source_text: str, metric_id: str) -> str | None:
    """Geographic, CapEx, or cost-structure revenue context for cm_revenue_concentration.

    Fires when the percent value is near:
    - Geographic breakdown language (e.g., "international revenue")
    - CapEx-as-%-of-revenue language (e.g., "CapEx for the fiscal year to be approximately 2% of revenue")
    - Cost-structure language (e.g., "cost of revenue was 18% of revenue", "gross margin")
    All indicate the percent is NOT customer revenue concentration.
    """
    if not source_text or metric_id != "cm_revenue_concentration":
        return None
    raw = (bv.value_raw or "").strip()
    if not raw:
        return None
    value_pos = source_text.find(raw)
    if value_pos < 0:
        # Value not in segment text — cross-segment binding artifact.
        # A revenue concentration percent that cannot be located in its own
        # segment text is almost certainly spurious; suppress it.
        return "v2_cross_segment_revenue_concentration"
    geo_match = _GEOGRAPHIC_REVENUE_RE.search(source_text)
    if geo_match and abs(geo_match.start() - value_pos) <= 200:
        return "v2_geographic_revenue"
    capex_match = _CAPEX_REVENUE_RE.search(source_text)
    if capex_match and abs(capex_match.start() - value_pos) <= 200:
        return "v2_capex_revenue"
    # Use finditer to find the nearest cost-structure pattern occurrence;
    # source_text.search() only finds the first match which may be far from the value.
    if any(abs(m.start() - value_pos) <= 200 for m in _COST_STRUCTURE_REVENUE_RE.finditer(source_text)):
        return "v2_cost_structure_revenue"
    # "Repeat/existing customers accounted for X% of net sales" describes
    # repeat purchase rate, not customer revenue concentration.
    repeat_match = _REPEAT_CUSTOMER_REVENUE_RE.search(source_text)
    if repeat_match and abs(repeat_match.start() - value_pos) <= 300:
        return "v2_repeat_customer_revenue"
    return None


def _rule_developer_count(bv: BoundValue, source_text: str, metric_id: str) -> str | None:
    """Developer/engineer count mistaken for cm_daily_active_users."""
    if not source_text or metric_id != "cm_daily_active_users":
        return None
    loc = _locate_value(bv, source_text)
    if loc is None:
        return None
    _, value_pos = loc
    dev_match = _DEVELOPER_COUNT_RE.search(source_text)
    if dev_match and abs(dev_match.start() - value_pos) <= 150:
        return "v2_developer_count"
    return None


def _rule_fortune_subset(bv: BoundValue, source_text: str, metric_id: str) -> str | None:
    """Fortune/Forbes subset count for cm_customers_period_end.

    Fires when a number near "of the Fortune/Forbes N" could be the ranking N
    itself (e.g., extracting 500 from "90% of the Fortune 500").  Does NOT fire
    when the extracted value is substantially larger than the ranking number
    (e.g., 230,000 customers is not a Fortune-500-subset count).
    """
    if not source_text or metric_id != "cm_customers_period_end":
        return None
    loc = _locate_value(bv, source_text)
    if loc is None:
        return None
    _, value_pos = loc
    fortune_match = _FORTUNE_SUBSET_RE.search(source_text)
    if fortune_match and abs(fortune_match.start() - value_pos) <= 100:
        # Only block if the extracted value is plausibly the ranking number itself
        # (i.e., small — Fortune 100, 500, 1000). A value like 230,000 is clearly
        # a separate customer count, not a Fortune subset ordinal.
        if bv.value is not None and bv.value <= 2000:
            return "v2_fortune_subset"
    return None


def _rule_tier_qualifier(bv: BoundValue, source_text: str, metric_id: str) -> str | None:
    """Per-tier customer counts for cm_customers_period_end.

    Suppresses FPs where the tier keyword appears in stub_path (for table
    cells) or within 150 characters of the numeric value position in prose.
    Avoids over-triggering on long segments that merely mention "Enterprise"
    in a different sentence from the value.
    """
    if not source_text or metric_id != "cm_customers_period_end":
        return None
    tier_match = _TIER_QUALIFIER_RE.search(source_text)
    if not tier_match:
        return None
    # Exception: "Number of [tier] Customers" labels are primary metrics, not
    # sub-segment counts.  E.g., Kingsoft's "Number of Public Cloud Service
    # Premium Customers" row — "Premium" is the main customer category, not a
    # tier sub-segment.  When "Number of" appears before the tier keyword in the
    # source text, treat the value as legitimate.
    if re.search(r"\bnumber\s+of\b", source_text[: tier_match.start()], re.IGNORECASE):
        return None
    # For text-sourced values, require the tier keyword to be within 150
    # characters of the value position to avoid false suppression on long
    # segments that mention tier names in passing.
    loc = bv.source_locator
    if loc.table_id is None and loc.segment_id is not None:
        # Text segment: check proximity between tier keyword and value
        raw = (bv.value_raw or "").strip()
        if raw:
            value_pos = source_text.find(raw)
            if value_pos >= 0 and abs(tier_match.start() - value_pos) > 150:
                return None
    return "v2_tier_qualifier"


def _rule_dollar_threshold_customer(
    bv: BoundValue, source_text: str, metric_id: str
) -> str | None:
    """Dollar-threshold customer subset counts.

    Suppresses FPs where source context contains a dollar threshold customer
    qualifier such as "Paid Customers >$100,000" — indicating the value is a
    large-customer (threshold-qualified) count extracted for the wrong metric.

    This pattern appears in Slack's quarterly key metrics table where ">$100K
    ARR" customer rows are adjacent to NRR and total customer rows, causing
    proximity binding to cm_customers_period_end and cm_net_revenue_retention.

    Does NOT fire for cm_large_customers_period_end — threshold-qualified
    customer counts are the correct values for that metric.

    Does NOT fire when the bound value is a PERCENT — a percent value near a
    dollar threshold is a legitimate NRR/GRR disclosure, not a count FP.
    (Flywire NRR 110-125% was incorrectly filtered by this rule.)
    """
    if not source_text or metric_id in ("cm_large_customers_period_end", "cm_revenue_concentration"):
        return None
    if bv.unit == Unit.PERCENT:
        return None
    loc = _locate_value(bv, source_text)
    if loc is None:
        return None
    _, value_pos = loc
    threshold_match = _DOLLAR_THRESHOLD_CUSTOMER_RE.search(source_text)
    if threshold_match and abs(threshold_match.start() - value_pos) <= 400:
        return "v2_dollar_threshold_customer"
    return None


# Growth-rate percent context — "up 27% year-over-year" or "up over 20% year-over-year".
# When a count-type metric (MAU, DAU) has a percent value that appears as a
# growth rate in the same sentence that also contains an absolute count, the
# percent is secondary (the count is the metric value).  Pattern: the percent
# raw text is immediately preceded within ~20 chars by "up [over] " or "grew ".
_GROWTH_RATE_PREFIX_RE = re.compile(
    r"\b(?:up|grew|grown|increased?)\s+(?:over\s+|around\s+|approximately\s+)?",
    re.IGNORECASE,
)
# Scale-suffixed count value in the same segment text — confirms an absolute value exists.
_SCALE_COUNT_RE = re.compile(
    r"\d+(?:\.\d+)?\s*(?:million|billion|thousand|,\d{3})",
    re.IGNORECASE,
)

# Metrics that are counts — a percent value for these metrics may be a growth rate.
_COUNT_TYPE_METRICS: frozenset[str] = frozenset({
    "cm_monthly_active_users",
    "cm_daily_active_users",
    "cm_active_customers_total",
    "cm_customers_period_end",
    "cm_new_customers_acquired",
    "cm_large_customers_period_end",
})

# Pure count metrics — MAU, DAU.  For these, a percent value with a growth-rate
# verb prefix is ALWAYS a growth rate (not the metric value), even when no
# scale-suffixed count appears in the same segment.  Unlike generic count metrics,
# MAU/DAU are never reported as percentages in earnings disclosures.
_PURE_COUNT_METRICS: frozenset[str] = frozenset({
    "cm_monthly_active_users",
    "cm_daily_active_users",
})


# Delta/growth count patterns — "increase of", "up by", "net additions of".
# When immediately preceding a count value, these indicate a growth delta,
# not an absolute stock value.
_DELTA_COUNT_RE = re.compile(
    r"(?:"
    r"(?:an?\s+)?(?:increase|decrease)\s+of"
    r"|(?:up|down)\s+(?:by\s+)?(?:more\s+than\s+|approximately\s+|nearly\s+|over\s+|about\s+)?"
    r"|(?:net\s+)?(?:additions?)\s+of"
    r"|,?\s*or\s+by\s+(?:more\s+than\s+|approximately\s+|nearly\s+|over\s+|about\s+)?"
    r"|(?:increas(?:e[ds]?|ing)|decreas(?:e[ds]?|ing)|grew|declined)\s+(?:by\s+)?(?:approximately\s+|nearly\s+|over\s+|about\s+|more\s+than\s+)?"
    r")\s*$",
    re.IGNORECASE,
)

_DELTA_BY_MORE_RE = re.compile(
    r"\b(?:up|down|grew|grown|increased?|decreased?)\b.{0,40}\bby[\s\u200b]+(?:more[\s\u200b]+than|approximately|nearly|over|about)[\s\u200b]*$",
    re.IGNORECASE | re.DOTALL,
)

# Indirect delta pattern: "increase in X by N" or "decrease of X by N" where a noun
# phrase (up to 60 chars) separates the delta verb from "by".  Catches constructions
# like "increase in the number of active customers by 3.8 million".  Applied inside
# _rule_delta_count_value after _DELTA_COUNT_RE and _DELTA_BY_MORE_RE.
_DELTA_INDIRECT_RE = re.compile(
    r"\b(?:increase|decrease)\b.{0,60}\bby\s+(?:approximately\s+|nearly\s+|over\s+|about\s+|more\s+than\s+)?$",
    re.IGNORECASE | re.DOTALL,
)

# Content engagement metrics (views, impressions, streams) near a bound value
# indicate the number is NOT a customer count.  Fires when the value raw text
# appears immediately adjacent to engagement vocabulary.
_CONTENT_ENGAGEMENT_RE = re.compile(
    r"\b(?:views?|impressions?|streams?|page\s+views?|video\s+views?)\b",
    re.IGNORECASE,
)

# Transactions-per-account ratio context — "transactions per account" or
# "transactions per active account".  When this phrase appears near a value
# bound to expansion revenue or an active-account count metric, the value is
# a TPA ratio (e.g., 57.6 transactions per active account), not an absolute
# revenue or customer count.
_TRANSACTIONS_PER_ACCOUNT_RE = re.compile(
    r"\btransactions?\s+per\s+(?:active\s+)?account",
    re.IGNORECASE,
)

_CUSTOMER_COUNT_METRICS: frozenset[str] = frozenset({
    "cm_customers_period_end",
    "cm_active_customers_total",
    "cm_new_customers_acquired",
    "cm_large_customers_period_end",
})


def _rule_content_engagement(bv: BoundValue, source_text: str, metric_id: str) -> str | None:
    """Block customer count metrics when value appears near engagement vocabulary (views, etc.)."""
    if metric_id not in _CUSTOMER_COUNT_METRICS:
        return None
    if not source_text:
        return None
    loc = _locate_value(bv, source_text)
    if loc is None:
        return None
    _, value_pos = loc
    engagement_match = _CONTENT_ENGAGEMENT_RE.search(source_text)
    if engagement_match and abs(engagement_match.start() - value_pos) <= 60:
        return "v2_content_engagement"
    return None


def _rule_transactions_per_account(
    bv: BoundValue, source_text: str, metric_id: str
) -> str | None:
    """Suppress TPA (transactions per active account) ratio values mis-classified
    as active account counts.

    Fires when the phrase 'transactions per [active] account' appears within
    150 characters of the bound value, and the metric is a count-type metric.
    TPA is a ratio (e.g., 57.6 transactions per active account) — never an
    absolute customer count.

    The window is 150 chars to cover prose like:
    "Payment transactions per active account ('TPA') on a trailing 12-month
    basis decreased 6% to 57.6" where the phrase precedes the value by ~85
    chars.
    """
    if metric_id not in _COUNT_TYPE_METRICS:
        return None
    if not source_text:
        return None
    loc = _locate_value(bv, source_text)
    if loc is None:
        return None
    _, value_pos = loc
    match = _TRANSACTIONS_PER_ACCOUNT_RE.search(source_text)
    if match and abs(match.start() - value_pos) <= 150:
        return "v2_transactions_per_account"
    return None


def _rule_delta_count_value(bv: BoundValue, source_text: str, metric_id: str) -> str | None:
    """Block delta/growth amounts bound as absolute count values.

    Fires when a count-type metric (excluding cm_new_customers_acquired) has
    its value preceded by delta language — "increase of", "up by", "net additions of".
    These patterns indicate the number is a growth amount, not an absolute stock.

    Two checks:
    1. 60-char pre-window: _DELTA_COUNT_RE ("increase of", "up by", "net additions of",
       "increased by", "increasing by", "grew by", "declined N")
    2. 60-char pre-window: _DELTA_BY_MORE_RE ("by more than", "by approximately", etc.)
    3. 60-char pre-window: _DELTA_INDIRECT_RE ("increase in X by N" with noun gap)

    Excludes cm_new_customers_acquired because "added/adding VALUE" is the canonical
    reporting pattern for net customer additions and should remain valid.
    """
    if metric_id not in _COUNT_TYPE_METRICS or metric_id == "cm_new_customers_acquired":
        return None
    if bv.unit not in (Unit.COUNT, Unit.OTHER):
        return None
    if not source_text:
        return None
    loc = _locate_value(bv, source_text)
    if loc is None:
        return None
    _, value_pos = loc
    # Check 60-char pre-window for primary delta patterns
    pre_start = max(0, value_pos - 60)
    pre_window = source_text[pre_start:value_pos]
    if _DELTA_COUNT_RE.search(pre_window):
        return "v2_delta_count_value"
    # Check 60-char pre-window for "by more than/approximately/etc."
    # (wider than the former 30-char window to catch "grew ... (MAU) by more than VALUE"
    # where a noun phrase separates the verb from "by")
    if _DELTA_BY_MORE_RE.search(pre_window):
        return "v2_delta_count_value"
    # Check for "increase in X by N" constructions where a noun phrase separates
    # the delta verb from "by".
    if _DELTA_INDIRECT_RE.search(pre_window):
        return "v2_delta_count_value"
    return None


def _rule_growth_rate_percent(bv: BoundValue, source_text: str, metric_id: str) -> str | None:
    """Block percent values that are growth rates rather than metric values.

    Fires when ALL of:
    1. The metric is a count-type metric (MAU, DAU, customers, etc.)
    2. The bound value unit is PERCENT
    3. The percent raw text is preceded by a growth-rate verb (up, grew, grown, increased)
       within a short window (~25 chars)
    4a. For MAU/DAU (pure count metrics): always fires — these are never reported as
        percentages in earnings calls, so a percent with a growth prefix is always a
        growth rate (e.g. "monthly actives grew 30%").
    4b. For other count metrics: only fires when a scale-suffixed count value also
        appears in the same segment (e.g. "56 million"), confirming that the absolute
        count is available and the percent is secondary growth context.
    """
    if bv.unit != Unit.PERCENT:
        return None
    if metric_id not in _COUNT_TYPE_METRICS:
        return None
    if not source_text:
        return None
    loc = _locate_value(bv, source_text)
    if loc is None:
        return None
    _, value_pos = loc
    # Check for growth-rate prefix immediately before the percent value
    window_start = max(0, value_pos - 25)
    window = source_text[window_start:value_pos]
    if not _GROWTH_RATE_PREFIX_RE.search(window):
        return None
    # For MAU/DAU: percent with growth prefix is always a growth rate (no scale count needed)
    if metric_id in _PURE_COUNT_METRICS:
        return "v2_growth_rate_percent"
    # For other count metrics: only fire when an absolute count exists in the text
    if not _SCALE_COUNT_RE.search(source_text):
        return None
    return "v2_growth_rate_percent"


def _rule_arpu_percent(bv: BoundValue, source_text: str, metric_id: str) -> str | None:
    """Percent values for cm_revenue_per_customer are always growth rates, not metric values.

    ARPA/ARPU is always a dollar amount; "ARPA grew 3%" or "ARPU growth of 4%"
    is a growth rate, not the ARPA value.
    """
    if bv.unit == Unit.PERCENT and metric_id == "cm_revenue_per_customer":
        return "v2_arpu_percent"
    return None


# "per day" context near a MAU value — signals a daily rate (e.g., "1 million sign-ups
# per day"), not a monthly active user count.  Only applies to cm_monthly_active_users.
_PER_DAY_RE = re.compile(r"\bper\s+day\b", re.IGNORECASE)

# ARPU context for cm_average_order_value.
# When "ARPU" or "average revenue per user" appears within ±30 chars of a value
# that's bound to cm_average_order_value, the value is really an ARPU figure,
# not an average order value.
_ARPU_LABEL_RE = re.compile(
    r"\b(?:ARPU|average\s+revenue\s+per\s+(?:user|account|subscriber))\b",
    re.IGNORECASE,
)


def _rule_arpu_as_aov(bv: BoundValue, source_text: str, metric_id: str) -> str | None:
    """Block ARPU values from binding to cm_average_order_value.

    Fires when metric_id == 'cm_average_order_value' and 'ARPU' or
    'average revenue per user/account/subscriber' appears within ±30 chars
    of the value — indicating the value is an ARPU figure rather than a
    genuine average order value.
    """
    if metric_id != "cm_average_order_value" or not source_text:
        return None
    loc = _locate_value(bv, source_text)
    if loc is None:
        return None
    raw, value_pos = loc
    window_start = max(0, value_pos - 30)
    window_end = min(len(source_text), value_pos + len(raw) + 30)
    window = source_text[window_start:window_end]
    if _ARPU_LABEL_RE.search(window):
        return "v2_arpu_as_aov"
    return None


# Year-over-year / YoY context — signals that a percent value is a growth rate
# disclosure rather than an adoption rate.  Used to escape _rule_percent_on_count_metric
# for MAU/DAU metrics: "growing 23% year-over-year" → legitimate growth rate (ACCEPT).
_YOY_CONTEXT_RE = re.compile(
    r"\byear[- ]over[- ]year\b|\bYoY\b|\bY/Y\b|\byear[- ]on[- ]year\b",
    re.IGNORECASE,
)


# Forward guidance detection — applies in relaxed mode (transcripts/presentations).
# Fires when present-tense guidance language appears within ±80 chars of the value,
# indicating a projected figure rather than a reported actual.
_FORWARD_GUIDANCE_RE = re.compile(
    r"\b(?:we\s+expect|our\s+expectation|our\s+outlook|we\s+guide|"
    r"we\s+project|we\s+anticipate|we\s+forecast|"
    r"guidance\s+(?:of|is|for|at)|full[- ]year\s+guidance|"
    r"expect(?:ing)?\s+to\s+(?:add|reach|achieve|deliver|generate)|"
    r"goal\s+(?:of|to)\s+(?:reach(?:ing)?|achiev(?:e|ing)|grow(?:ing)?|serv(?:e|ing))|"
    r"target\s+(?:of|to)\s+(?:reach(?:ing)?|achiev(?:e|ing))|"
    r"aspir(?:e|ing|ation)\s+to|"
    r"on\s+track\s+to)\b",
    re.IGNORECASE,
)


def _rule_mau_daily_rate(bv: BoundValue, source_text: str, metric_id: str) -> str | None:
    """Block MAU values described as a 'per day' rate rather than a monthly count.

    Fires when 'per day' appears within ~50 chars of the value for
    cm_monthly_active_users — e.g., 'adding more than 1 million sign-ups per day'
    is a daily signup rate, not a monthly active user count.
    """
    if metric_id != "cm_monthly_active_users" or not source_text:
        return None
    raw = (bv.value_raw or "").strip()
    if not raw:
        return None
    value_pos = source_text.find(raw)
    per_day_match = _PER_DAY_RE.search(source_text)
    if per_day_match:
        if value_pos < 0 or abs(per_day_match.start() - value_pos) <= 50:
            return "v2_mau_daily_rate"
    return None


def _rule_percent_on_count_metric(bv: BoundValue, source_text: str, metric_id: str) -> str | None:
    """Block percent values from binding to count-only metrics.

    Fires when a PERCENT unit value is bound to a metric that can only be an
    absolute count (MAU, DAU, customers, etc.).

    These FPs arise when a feature adoption rate appears near a count keyword:
    "Photoshop GenAI monthly active users at approximately 35%" → 35% is a
    feature adoption rate, not an absolute MAU count.

    MAU/DAU escape: For cm_monthly_active_users and cm_daily_active_users,
    percent values WITH year-over-year/YoY context within ±100 chars are
    legitimate growth rate disclosures ("growing 23% year-over-year") and
    are NOT rejected by this rule.  These are handled as growth rate values.

    For other count metrics (customers_period_end, new_customers_acquired, etc.),
    percent is always a false positive (no legitimate percent representation exists).
    """
    if bv.unit != Unit.PERCENT or metric_id not in _COUNT_ONLY_METRICS:
        return None
    # MAU/DAU escape: year-over-year context → legitimate growth rate disclosure.
    if metric_id in _PURE_COUNT_METRICS and source_text:
        raw = (bv.value_raw or "").strip()
        if raw:
            value_pos = source_text.find(raw)
            if value_pos >= 0:
                window_start = max(0, value_pos - 100)
                window_end = min(len(source_text), value_pos + len(raw) + 100)
                window = source_text[window_start:window_end]
                if _YOY_CONTEXT_RE.search(window):
                    return None  # YoY growth context — legitimate growth rate
    return "v2_percent_on_count"


# Q&A-specific rules below are injected via _is_v2_false_positive after the
# registry loop because they require the section_type argument, which rule
# functions in the registry do not receive.

def _qa_hedging_percent_near_value(source_text: str, value_raw: str) -> bool:
    """
    Return True if Q&A hedging language appears within ~10 words of the value.

    Only called for percent values in Q&A sections.
    Searches a ±60-character window around the value position to approximate
    a 10-word radius without full tokenisation.
    """
    raw = value_raw.strip()
    if not raw:
        return False
    value_pos = source_text.find(raw)
    if value_pos < 0:
        return False
    window_start = max(0, value_pos - 60)
    window_end = min(len(source_text), value_pos + len(raw) + 60)
    window = source_text[window_start:window_end]
    return bool(_QA_HEDGING_RE.search(window))



# NRR context keywords — net revenue retention / net dollar retention.
# Used to suppress cm_customer_retention_rate FPs where the source text
# describes NRR/NDR (which can exceed 100%) rather than customer retention.
_NRR_CONTEXT_RE = re.compile(
    r"\b(?:net\s+(?:revenue|dollar)\s+retention|nrr|ndr|"
    r"dollar[- ]based\s+(?:net\s+)?retention|"
    r"revenue[- ]based\s+retention)\b",
    re.IGNORECASE,
)


def _rule_retention_rate_over_100(
    bv: BoundValue, source_text: str, metric_id: str
) -> str | None:
    """Block cm_customer_retention_rate for values >100 or in NRR context.

    Customer retention rate is 0-100%. Any value above 100 is NRR (net
    revenue retention), not customer retention rate. Also blocks when NRR
    keywords appear within 80 chars of the value position (proximity-scoped
    to avoid false blocks when NRR language appears elsewhere in the same
    segment).
    """
    if metric_id != "cm_customer_retention_rate":
        return None
    if bv.value is not None and bv.value > 100:
        return "v2_retention_rate_over_100"
    if source_text and _NRR_CONTEXT_RE.search(source_text):
        raw = (bv.value_raw or "").strip()
        if raw:
            value_pos = source_text.find(raw)
            if value_pos >= 0:
                window_start = max(0, value_pos - 80)
                window_end = min(len(source_text), value_pos + len(raw) + 80)
                window = source_text[window_start:window_end]
                if _NRR_CONTEXT_RE.search(window):
                    return "v2_retention_rate_nrr_context"
                return None  # NRR context exists but far from value — not a block
        # Fallback: value_raw not locatable in source — use full-text check
        return "v2_retention_rate_nrr_context"
    return None



# Maximum plausible values per metric (to catch magnitude errors from cross-metric mis-binding).
_METRIC_MAX_VALUE: dict[str, float] = {
    "cm_lifetime_value_per_customer": 10_000_000,   # $10M max LTV
    "cm_ltv_to_cac_ratio": 25,                       # 25x max LTV/CAC; real ratios rarely exceed 20x
    "cm_customer_acquisition_cost": 50_000,          # $50K max CAC; larger values are financial figures
    "cm_revenue_per_customer": 100_000,              # $100K max ARPU
    "cm_large_customers_period_end": 20_000,         # >20K would be total customers, not "large" segment
    "cm_net_revenue_retention": 250,                 # >250% NRR is a financial figure, not NRR
}

# Minimum plausible values for specific metrics.
# Used by _rule_magnitude_sanity alongside _METRIC_MAX_VALUE.
_METRIC_MIN_VALUE: dict[str, float] = {
    "cm_net_revenue_retention": 31,                  # <31% NRR is implausible; blocks 30.0 mis-binding; active gold min is 44% (Samsara)
    "cm_customer_retention_rate": 50,                # <50% CRR is implausible; active gold min is 66% (Chewy)
}


def _rule_magnitude_sanity(
    bv: BoundValue, source_text: str, metric_id: str
) -> str | None:
    """Block values outside the plausible range for a metric.

    Catches cross-metric mis-binding where financial figures (revenue,
    market size) are assigned to per-customer or ratio metrics, and
    where implausibly small values are assigned to rate metrics.
    """
    if bv.value is None:
        return None
    max_val = _METRIC_MAX_VALUE.get(metric_id)
    if max_val is not None and bv.value > max_val:
        return "v2_magnitude_sanity"
    min_val = _METRIC_MIN_VALUE.get(metric_id)
    if min_val is not None and bv.value < min_val:
        return "v2_magnitude_sanity"
    return None


# ---------------------------------------------------------------------------
# Wave 4: Cross-metric row disambiguation
# ---------------------------------------------------------------------------

_ARPU_CONTEXT_RE = re.compile(
    r"""
    \b(?:
        net\s+sales\s+per\s+(?:active\s+)?customer
        | revenue\s+per\s+(?:active\s+)?customer
        | sales\s+per\s+(?:active\s+)?customer
        | spend\s+per\s+(?:active\s+)?customer
        | average\s+(?:net\s+)?(?:revenue|sales|spend)\s+per\s+(?:active\s+)?customer
        | avg\s+(?:revenue|spend)\s+per
        | average\s+order\s+value
        | arpu
        | arpd
    )
    """,
    re.IGNORECASE | re.VERBOSE,
)

_LTV_CONTEXT_RE = re.compile(
    r"\b(?:lifetime\s+value|ltv\b|lTV\b)",
    re.IGNORECASE,
)

_CUSTOMER_COUNT_METRICS = frozenset({
    "cm_active_customers_total",
    "cm_customers_period_end",
})


_TABLE_BINDING_TYPES = frozenset({"table_header", "table_stub"})


def _rule_arpu_context_on_customer_count(
    bv: BoundValue, source_text: str, metric_id: str
) -> str | None:
    """Block customer-count metrics when source text contains ARPU context.

    Revenue-per-customer values (ARPU, ARPC, net sales per active customer) in
    tables are frequently misbound to cm_active_customers_total or
    cm_customers_period_end because their numeric magnitude overlaps with small
    customer counts.

    The rule is restricted to table bindings (table_header / table_stub) because
    the source_text for table values is composed from the header_path + stub_path,
    which directly label the row.  For text_proximity bindings the source_text is
    an entire paragraph that may mention ARPU incidentally while the bound value
    is a legitimate customer count — firing the rule there causes many false
    removals in dense SEC filing prose.
    """
    if metric_id not in _CUSTOMER_COUNT_METRICS:
        return None
    if not source_text:
        return None
    if bv.binding_type not in _TABLE_BINDING_TYPES:
        return None
    if _ARPU_CONTEXT_RE.search(source_text):
        return "v2_arpu_context_on_customer_count"
    return None


# ---------------------------------------------------------------------------
# Wave 5: Revenue concentration keyword check
# ---------------------------------------------------------------------------

_REVENUE_CONCENTRATION_KEYWORD_RE = re.compile(
    r"""
    \b(?:
        concentrat(?:ion|ed)
        | top\s+\d+\s+customer
        | top\s+(?:five|ten|twenty|twenty-five|fifty|hundred)\s+customer
        | largest\s+customer
        | accounted\s+for
        | contribut(?:ed|es?)\s+(?:\w+\s+){0,4}(?:revenue|sales)
        # Dollar-threshold customer counts (e.g., "customers over $100K in ARR")
        | customers?\s+(?:over|above|exceeding|greater\s+than|with\s+more\s+than)\s+\$
        | number\s+of\s+customers?\s+(?:over|above|exceeding|with)
        | customers?\s+with\s+(?:annual|arr|revenue|contract)
    )
    """,
    re.IGNORECASE | re.VERBOSE,
)


def _rule_revenue_concentration_keyword(
    bv: BoundValue, source_text: str, metric_id: str
) -> str | None:
    """Block cm_revenue_concentration when source text lacks concentration keywords.

    Revenue concentration metrics must be accompanied by language that
    explicitly describes customer-level revenue concentration (e.g., 'top N
    customers', 'largest customers', 'accounted for X%').  Small integers
    extracted from tables without this language are false positives.
    """
    if metric_id != "cm_revenue_concentration":
        return None
    if not source_text or not _REVENUE_CONCENTRATION_KEYWORD_RE.search(source_text):
        return "v2_revenue_concentration_no_keyword"
    return None


# ---------------------------------------------------------------------------
# Wave 6: Financial context on customer metrics
# ---------------------------------------------------------------------------

_FINANCIAL_CONTEXT_KEYWORD_RE = re.compile(
    r"""
    \b(?:
        ebitda
        | (?:adjusted\s+)?ebitda
        | free\s+cash\s+flow
        | (?:net\s+)?cash\s+(?:and\s+cash\s+equivalents?|position|balance|flow)
        | net\s+(?:loss|income|sales)
        | net\s+revenue(?!\s+retention)  # "net revenue" but NOT "net revenue retention"
        | operating\s+(?:income|loss|expense|margin|cash)
        | gross\s+(?:profit|margin|loss)
        | total\s+(?:revenue|sales|assets|liabilities|debt)
        | capital\s+expenditures?
        | (?:cost|costs)\s+of\s+(?:goods\s+sold|revenue|sales)
        | working\s+capital
        | interest\s+expense
        | depreciation\s+(?:and\s+amortization)?
        | amortization
        | loss\s+from\s+operations
        | comparable\s+(?:store\s+)?sales
        | number\s+of\s+stores?
        | (?:store|location|outlet|restaurant|branch)\s+count
    )\b
    """,
    re.IGNORECASE | re.VERBOSE,
)

# Customer count metrics that should not appear in financial statement context.
# Restricted to pure count/customer metrics. Financial-adjacent metrics like
# cm_lifetime_value_per_customer and cm_customer_retention_rate are excluded
# because financial context (gross margin, cost of revenue) legitimately
# appears in their disclosures. Table bindings use the rule broadly; text
# bindings require proximity since financial keywords may appear in the same
# section without directly labeling the value.
_FINANCIAL_CONTEXT_BLOCKED_METRICS = _COUNT_ONLY_METRICS | frozenset({
    "cm_large_customers_period_end",
})


def _rule_financial_context_on_customer_metric(
    bv: BoundValue, source_text: str, metric_id: str
) -> str | None:
    """Block customer metrics when source context is dominated by financial statement language.

    Financial figures (EBITDA, cash flow, net loss, gross profit, store counts)
    frequently appear near customer metric keywords in SEC filings and S-1/F-1
    prospectuses, causing spurious bindings. This rule suppresses such extractions
    for metrics that cannot take financial-statement values.

    Table bindings: always fire when a financial keyword appears in the
    header/stub path (which directly labels the row/column).
    Text bindings: fire only when the keyword is within 100 chars of the value.
    Uses a window-based check around the value to avoid being misled by an
    early financial keyword far from the actual bound value position.
    """
    if metric_id not in _FINANCIAL_CONTEXT_BLOCKED_METRICS:
        return None
    if not source_text:
        return None
    # Table-sourced: header/stub path directly labels the cell — always fire
    # if any financial keyword appears anywhere in source_text.
    if bv.source_locator.table_id is not None:
        # Exempt cm_large_customers_period_end from table financial context
        # blocking when value is in a plausible customer count range (100-1M).
        # Large customer counts commonly appear in tables alongside financial
        # keywords (gross margin, total revenue) without being financial values.
        if (
            metric_id == "cm_large_customers_period_end"
            and 100 <= bv.value <= 1_000_000
        ):
            return None
        if _FINANCIAL_CONTEXT_KEYWORD_RE.search(source_text):
            return "v2_financial_context_customer_metric"
        return None
    # Text-sourced: require a financial keyword in the 100-char pre-window.
    # Financial row labels appear BEFORE the values they describe in linearized
    # text.  Using the pre-window (not a symmetric window) prevents blocking
    # legitimate customer counts that appear before a financial row in the same
    # segment (e.g., "Customers 255 … Non-GAAP loss $(219,609)").
    loc = _locate_value(bv, source_text)
    if loc is None:
        return None
    _, value_pos = loc
    pre_window = source_text[max(0, value_pos - 100):value_pos]
    if _FINANCIAL_CONTEXT_KEYWORD_RE.search(pre_window):
        return "v2_financial_context_customer_metric"
    return None


# ---------------------------------------------------------------------------
# Wave 6: Metric definition / threshold value
# ---------------------------------------------------------------------------

_METRIC_DEFINITION_THRESHOLD_RE = re.compile(
    r"""
    (?:
        # Explicit definition language
        \bdefin(?:ed?\s+(?:as|of)|ition\s+of)\b
        # Customer-qualified threshold language (requires "customer" prefix)
        | \bcustomer[s]?\s+(?:with|spending|generating|having|represent(?:ing)?)\s+
          (?:over|more\s+than|at\s+least|greater\s+than|>\s*\$|>=\s*\$)
        # ARR-qualified threshold: "ARR of greater than $X", "ARR exceeding $X"
        | \bARR\s+(?:of\s+)?(?:over|greater\s+than|more\s+than|at\s+least|exceeding|>\s*)
        # "representing over $X in ARR" — subscription tier threshold
        | \brepresenting\s+(?:over|more\s+than|at\s+least|greater\s+than)\s+\$
        # Pure threshold marker (must appear immediately before a dollar sign or number)
        | \bthreshold\b
    )
    """,
    re.IGNORECASE | re.VERBOSE,
)


_METRIC_DEFINITION_THRESHOLD_POST_RE = re.compile(
    r"""
    (?:
        # "$X ARR customer(s)/deal(s)" — threshold for customer tier
        \bARR\s+(?:customer|deal|client)s?\b
        # "$X or more in ARR/annual recurring revenue"
        | \bor\s+more\s+in\s+(?:ARR|annual\s+recurring\s+revenue)\b
    )
    """,
    re.IGNORECASE | re.VERBOSE,
)


def _rule_metric_definition_value(
    bv: BoundValue, source_text: str, metric_id: str
) -> str | None:
    """Block currency values that represent metric definition thresholds, not reported values.

    Customer tier descriptions like 'customers with >$100K ARR' or 'defined as
    spending at least $5,000' produce currency candidates for the threshold amount
    rather than the company's actual metric value. This rule suppresses such
    extractions by detecting definition/threshold language in the 80-char window
    before the value, or ARR-threshold language in the 80-char window after it.
    """
    if bv.unit != Unit.CURRENCY:
        return None
    if not source_text:
        return None
    loc = _locate_value(bv, source_text)
    if loc is None:
        return None
    _, value_pos = loc
    pre_start = max(0, value_pos - 120)
    pre_window = source_text[pre_start:value_pos]
    if _METRIC_DEFINITION_THRESHOLD_RE.search(pre_window):
        return "v2_metric_definition_value"
    # Post-value window: catches "$X ARR customers", "$X or more in ARR"
    raw_len = len(bv.value_raw or "")
    post_end = min(len(source_text), value_pos + raw_len + 80)
    post_window = source_text[value_pos + raw_len:post_end]
    if _METRIC_DEFINITION_THRESHOLD_POST_RE.search(post_window):
        return "v2_metric_definition_value"
    return None


# ---------------------------------------------------------------------------
# Wave 6: Chart pricing and CAGR labels
# ---------------------------------------------------------------------------

_CHART_PRICING_RE = re.compile(
    r"\bper\s+(?:user|seat|month|year|license|account)\b",
    re.IGNORECASE,
)

_CHART_CAGR_RE = re.compile(
    r"\bCAGR\b|\bcompound\s+annual\s+growth\b",
    re.IGNORECASE,
)

_CHART_BINDING_TYPES = frozenset({"chart_label", "chart_annotation"})


def _rule_chart_pricing_label(
    bv: BoundValue, source_text: str, metric_id: str
) -> str | None:
    """Block chart-sourced values with pricing or CAGR labels.

    Chart extractions that carry pricing language ("per user per month", "per seat")
    or compound-growth labels (CAGR) are almost never customer metric disclosures —
    they are pricing tier labels or market-size projections. This rule fires only
    for chart_label and chart_annotation binding types.
    """
    if bv.binding_type not in _CHART_BINDING_TYPES:
        return None
    if not source_text:
        return None
    if _CHART_PRICING_RE.search(source_text):
        return "v2_chart_pricing_label"
    if _CHART_CAGR_RE.search(source_text):
        return "v2_chart_cagr_label"
    return None


# ---------------------------------------------------------------------------
# Wave 6: TAM / market size suppression
# ---------------------------------------------------------------------------

_TAM_MARKET_SIZE_RE = re.compile(
    r"\b(?:"
    r"total\s+addressable\s+market"
    r"|TAM\b"
    r"|SAM\b"
    r"|SOM\b"
    r"|serviceable\s+(?:addressable|obtainable)\s+market"
    r"|market\s+(?:size|opportunity)"
    r")\b",
    re.IGNORECASE,
)

# Metrics that should never take a total-market-size value.
_TAM_BLOCKED_METRICS = _FINANCIAL_CONTEXT_BLOCKED_METRICS | frozenset({
    "cm_lifetime_value_per_customer",
    "cm_ltv_to_cac_ratio",
    "cm_revenue_per_customer",
    "cm_revenue_by_cohort",
})


def _rule_tam_market_size(bv: BoundValue, source_text: str, metric_id: str) -> str | None:
    """Block values that represent TAM/SAM/SOM or market-size projections.

    Total addressable market figures appear in investor presentations and S-1
    filings near customer metric keywords, causing spurious extractions.  TAM
    values are never legitimate customer metric values — they measure the overall
    market, not the company's actual performance.

    Fires when TAM/market-size language appears within 200 chars of the value.
    """
    if metric_id not in _TAM_BLOCKED_METRICS:
        return None
    if not source_text:
        return None
    loc = _locate_value(bv, source_text)
    if loc is None:
        return None
    raw, value_pos = loc
    window_start = max(0, value_pos - 200)
    window_end = min(len(source_text), value_pos + len(raw) + 200)
    window = source_text[window_start:window_end]
    if _TAM_MARKET_SIZE_RE.search(window):
        return "v2_tam_market_size"
    return None


# ---------------------------------------------------------------------------
# Wave 7: Table stub-path contradiction for per-customer / retention metrics
# ---------------------------------------------------------------------------

# Per-metric contradiction regexes for table stub-path mismatches.
#
# When a metric keyword matches in a column header, the pipeline binds ALL
# data cells in that column to that metric — even when the row label (stub)
# clearly identifies a different metric.  For each metric below, the regex
# matches stub text that is definitive evidence of the WRONG row being bound.
#
# source_text for table values = header_path + stub_path + cell_text
# (false_positive_filter.py:_get_source_text), so stub tokens are matchable.
#
# CAUTION: "active customers" is intentionally excluded from cm_revenue_per_customer
# and cm_average_order_value — mixed tables in Chewy-style filings have legitimate
# ARPU rows sharing header context with active-customer-count rows, and adding
# "active customers" here caused false negatives in past iterations.
_STUB_DOMAIN_CONTRADICTIONS: dict[str, re.Pattern] = {
    # Retention metrics → block when stub names customer counts or per-customer metrics.
    # "number of … customers" allows up to 3 adjective words (e.g. "premium cloud service").
    "cm_net_revenue_retention": re.compile(
        r"\b(?:"
        r"number\s+of\s+(?:\w+\s+){0,3}customers?"
        r"|customer\s+count"
        r"|arpc"
        r"|average\s+revenues?\s+per"
        r"|revenue\s+per\s+customer"
        r"|arpu"
        r"|active\s+customers?"
        r")\b",
        re.IGNORECASE,
    ),
    "cm_gross_revenue_retention": re.compile(
        r"\b(?:"
        r"number\s+of\s+(?:\w+\s+){0,3}customers?"
        r"|customer\s+count"
        r"|arpc"
        r"|average\s+revenues?\s+per"
        r"|revenue\s+per\s+customer"
        r"|arpu"
        r"|active\s+customers?"
        r")\b",
        re.IGNORECASE,
    ),
    "cm_customer_retention_rate": re.compile(
        r"\b(?:"
        r"number\s+of\s+(?:\w+\s+){0,3}customers?"
        r"|customer\s+count"
        r"|arpc"
        r"|average\s+revenues?\s+per"
        r"|revenue\s+per\s+customer"
        r"|arpu"
        r"|active\s+customers?"
        r"|net\s+revenue\s+retention"
        r"|nrr\b"
        r")\b",
        re.IGNORECASE,
    ),
    # Per-customer metrics → block when stub names count/retention rows
    # NOTE: "active customers" deliberately excluded (see caution above)
    "cm_revenue_per_customer": re.compile(
        r"\b(?:"
        r"number\s+of\s+stores?"
        r"|store\s+count"
        r"|comparable\s+(?:store\s+)?sales"
        r"|square\s+(?:foot|footage|feet)"
        r"|sq\.\s*ft"
        r"|net\s+revenue\s+retention"
        r"|gross\s+revenue\s+retention"
        r"|(?:customer\s+)?(?:churn|retention)\s+rate"
        r")\b",
        re.IGNORECASE,
    ),
    "cm_average_order_value": re.compile(
        r"\b(?:"
        r"number\s+of\s+stores?"
        r"|store\s+count"
        r"|comparable\s+(?:store\s+)?sales"
        r"|square\s+(?:foot|footage|feet)"
        r"|sq\.\s*ft"
        r"|net\s+revenue\s+retention"
        r"|gross\s+revenue\s+retention"
        r"|(?:customer\s+)?(?:churn|retention)\s+rate"
        r")\b",
        re.IGNORECASE,
    ),
    # Customer count metrics → block when stub names per-customer or retention metrics
    # NOTE: "stores" intentionally excluded — does not indicate a non-customer-count row
    "cm_active_customers_total": re.compile(
        r"\b(?:"
        r"arpu"
        r"|arpc"
        r"|average\s+revenues?\s+per"
        r"|revenue\s+per\s+(?:active\s+)?customer"
        r"|net\s+sales\s+per"
        r"|net\s+revenue\s+retention"
        r"|gross\s+revenue\s+retention"
        r"|(?:customer\s+)?(?:churn|retention)\s+rate"
        r")\b",
        re.IGNORECASE,
    ),
    "cm_customers_period_end": re.compile(
        r"\b(?:"
        r"arpu"
        r"|arpc"
        r"|average\s+revenues?\s+per"
        r"|revenue\s+per\s+(?:active\s+)?customer"
        r"|net\s+sales\s+per"
        r"|net\s+revenue\s+retention"
        r"|gross\s+revenue\s+retention"
        r"|(?:customer\s+)?(?:churn|retention)\s+rate"
        r")\b",
        re.IGNORECASE,
    ),
}


def _rule_stub_metric_contradiction(
    bv: BoundValue, source_text: str, metric_id: str
) -> str | None:
    """Block table column-header bindings where the stub row labels a different metric.

    When a column header contains a metric keyword, the value-binding stage binds
    ALL data cells in that column to that metric — even when the row label (stub_path)
    clearly names a DIFFERENT metric.  For example, a 'Net Revenue Retention' column
    header may cause customer-count rows or ARPC rows to be mis-bound as NRR.

    The source_text for table cells is header_path + stub_path + cell_text, so stub
    tokens are present and matchable via _STUB_DOMAIN_CONTRADICTIONS.

    Only fires for table_header bindings (binding_type == 'table_header') where the
    stub row contradicts the bound metric.  table_stub bindings are correct by
    construction — the stub IS the matched keyword.
    """
    contradiction_re = _STUB_DOMAIN_CONTRADICTIONS.get(metric_id)
    if contradiction_re is None:
        return None
    if bv.binding_type != "table_header":
        return None
    if bv.source_locator.table_id is None:
        return None
    if not source_text:
        return None
    if contradiction_re.search(source_text):
        return "v2_stub_metric_contradiction"
    return None


def _rule_stub_financial_line_item(
    bv: BoundValue, source_text: str, metric_id: str
) -> str | None:
    """Block table column-header bindings where source text contains a financial
    statement line-item label (margin, EBITDA, gross profit, accounts payable, etc.).

    For table_header bindings, source_text = header_path + stub_path + cell_text.
    The metric keyword that triggered the binding is in header_path (column). When
    source_text contains financial line-item terms, they are virtually always in
    stub_path (row label), indicating the bound row belongs to a different metric.

    Defense-in-depth complement to the upstream _bind_cells guard in value_binding.py.
    Not applied to metrics in _FINANCIAL_LINE_ITEM_STUB_ALLOW.
    """
    if metric_id in _FINANCIAL_LINE_ITEM_STUB_ALLOW:
        return None
    if bv.binding_type != "table_header":
        return None
    if bv.source_locator.table_id is None:
        return None
    if not source_text:
        return None
    m = _FINANCIAL_LINE_ITEM_STUB_RE.search(source_text)
    if m:
        return f"v2_financial_line_item_stub:{m.group(0).lower()}"
    return None


def _rule_revenue_per_customer_fin_annotation(
    bv: BoundValue, source_text: str, metric_id: str
) -> str | None:
    """Block large cm_revenue_per_customer values from '($ in thousands)' financial sections.

    Catches customer count values (e.g. 6,789 active customers) that appear in
    a financial statement section annotated with '($ in thousands)' or
    '(in thousands)' and are mistakenly bound as per-customer revenue because a
    'revenue per customer' keyword appears elsewhere in the same segment.

    Only fires when value >= 1,000 — legitimate ARPU values above $1,000 exist
    (e.g. Torrid ~$3,400) but those segments do not carry financial-statement
    scale annotations.
    """
    if metric_id != "cm_revenue_per_customer":
        return None
    if bv.value is None or bv.value < 1_000:
        return None
    if not source_text:
        return None
    if _FINANCIAL_ANNOTATION_RE.search(source_text):
        return "v2_revenue_per_customer_fin_annotation"
    return None


_RATIO_SUFFIX_RE = re.compile(r"\d+(?:\.\d+)?\s*[xX×]$")

_SMALL_ARR_THRESHOLD_RE = re.compile(
    r"\$\s*5[,.]?000\s*(?:in\s+)?(?:ARR|annual\s+recurring)",
    re.IGNORECASE,
)


def _rule_revenue_concentration_ratio_suffix(
    bv: BoundValue, source_text: str, metric_id: str
) -> str | None:
    """Block cm_revenue_concentration when raw value has a ratio suffix (e.g. '33.9x').

    Revenue concentration is a percentage (0-100). A trailing 'x' or '×' signals a
    ratio or multiplier metric (LTV/CAC, ARR multiple, etc.) being mis-bound as
    concentration.
    """
    if metric_id != "cm_revenue_concentration":
        return None
    raw = bv.value_raw or ""
    if _RATIO_SUFFIX_RE.search(raw.strip()):
        return "v2_revenue_concentration_ratio_suffix"
    return None


def _rule_large_customers_small_arr_threshold(
    bv: BoundValue, source_text: str, metric_id: str
) -> str | None:
    """Block cm_large_customers_period_end when source context mentions a $5K ARR threshold.

    The standard 'large customers' definition uses $100K+ ARR. A $5,000 ARR threshold
    indicates a total/core customer count (e.g. Samsara's 'Core Customers' = 13,000+
    with >$5K ARR) rather than the enterprise tier the metric is designed to track.

    Value guard (>5,000) prevents blocking the legitimate $100K-tier count (gold = 715)
    that appears in the same filing paragraph as the core-customer $5K definition.
    """
    if metric_id != "cm_large_customers_period_end":
        return None
    if bv.value is None or bv.value <= 5_000:
        return None
    if not source_text:
        return None
    if _SMALL_ARR_THRESHOLD_RE.search(source_text):
        return "v2_large_customers_small_arr_threshold"
    return None


# =============================================================================
# FP Rule Registry — order matters (first match wins)
# Tags are used by the relaxed-mode skip list below.
# =============================================================================

_FP_RULES: list[tuple[str, Callable[[BoundValue, str, str], str | None], bool]] = [
    ("year_value", _rule_year_value, False),
    ("percent_range", _rule_percent_range, False),
    ("garbage_value", _rule_garbage_value, False),
    ("negative_value", _rule_negative_value, False),
    ("year_fragment", _rule_year_fragment, False),
    ("truncated_year", _rule_truncated_year, False),
    ("linearized_table", _rule_linearized_table, True),
    ("financial_annotation", _rule_financial_annotation, True),
    ("financial_sbc", _rule_financial_sbc, True),
    ("ranking_name", _rule_ranking_name, False),
    ("per_share", _rule_per_share, False),
    ("revenue_concentration_context", _rule_revenue_concentration_context, False),
    ("developer_count", _rule_developer_count, True),
    ("fortune_subset", _rule_fortune_subset, False),
    ("tier_qualifier", _rule_tier_qualifier, False),
    ("dollar_threshold_customer", _rule_dollar_threshold_customer, False),
    ("content_engagement", _rule_content_engagement, True),
    ("transactions_per_account", _rule_transactions_per_account, True),
    ("delta_count_value", _rule_delta_count_value, True),
    ("growth_rate_percent", _rule_growth_rate_percent, False),
    ("arpu_percent", _rule_arpu_percent, False),
    ("arpu_as_aov", _rule_arpu_as_aov, False),
    ("percent_on_count", _rule_percent_on_count_metric, False),
    ("retention_rate_over_100", _rule_retention_rate_over_100, False),
    ("magnitude_sanity", _rule_magnitude_sanity, False),
    ("revenue_per_customer_fin_annotation", _rule_revenue_per_customer_fin_annotation, False),
    ("revenue_concentration_ratio_suffix", _rule_revenue_concentration_ratio_suffix, False),
    ("large_customers_small_arr_threshold", _rule_large_customers_small_arr_threshold, False),
    ("arpu_context_on_customer_count", _rule_arpu_context_on_customer_count, True),
    ("financial_context_customer_metric", _rule_financial_context_on_customer_metric, True),
    ("metric_definition_value", _rule_metric_definition_value, True),
    ("chart_pricing_label", _rule_chart_pricing_label, True),
    ("tam_market_size", _rule_tam_market_size, True),
    ("stub_metric_contradiction", _rule_stub_metric_contradiction, False),
    ("stub_financial_line_item", _rule_stub_financial_line_item, False),
]

# Rules skipped in relaxed mode per document type.
#
# Transcripts: skip linearized_table (HTML markers absent in spoken text),
# financial_annotation ("In thousands" etc.), and financial_sbc
# ("stock-based compensation") — these patterns appear in written filings but
# not in earnings call spoken content, causing false negatives on transcripts.
#
# Presentations: skip the same set as transcripts. Although presentations are
# HTML documents, SEC EDGAR earnings press releases often contain "(in thousands)"
# financial table footnotes in the same document as customer metric disclosures.
# Enabling financial_annotation for presentations causes false negatives where
# legitimate customer metric values near financial tables get incorrectly filtered.
# The _rule_financial_context_on_customer_metric rule handles financial context
# filtering for presentations more precisely.
_TRANSCRIPT_SKIP_TAGS = frozenset({"linearized_table", "financial_annotation", "financial_sbc"})
_PRESENTATION_SKIP_TAGS = frozenset({"linearized_table", "financial_annotation", "financial_sbc"})

# Retained for backward compatibility: callers that pass relaxed=True without
# a document_type (e.g., unit tests) get transcript-level skipping.
_RELAXED_SKIP_TAGS = _TRANSCRIPT_SKIP_TAGS

# Confidence floor above which soft (contextual/proximity-based) FP rules are bypassed.
# Only table bindings with exact keyword match in header/stub can reach this threshold
# (0.6 base + 0.2 exact match + 0.1 keyword-path bonus = 0.9). Text bindings max at
# ~0.65, so they are never exempted. This prevents metric-specific carve-outs in the
# filter by instead using structural confidence as the signal.
_SOFT_RULE_CONFIDENCE_FLOOR: float = 0.85

# Rules skipped in strict mode (SEC filings).
# Currently empty: the arpu_context_on_customer_count rule was previously
# strict-only but was made safe for all modes by adding a binding_type guard
# (only fires for table_header / table_stub bindings, not text_proximity).
_STRICT_SKIP_TAGS: frozenset[str] = frozenset()


def _is_v2_false_positive(
    bv: BoundValue,
    source_text: str,
    metric_id: str = "",
    relaxed: bool = False,
    section_type: SectionType = SectionType.UNKNOWN,
    document_type: str = "",
    binding_confidence: float = 0.0,
) -> tuple[bool, str | None]:
    """
    V2-native false positive checks that go beyond V1's positional filter.

    Iterates over registered FP rules and returns the first match.

    When relaxed=True (for transcripts/presentations), the same rules are skipped
    for both document types: "linearized_table", "financial_annotation", and
    "financial_sbc". Although the document_type parameter is available for future
    differentiation, empirical testing showed that re-enabling financial_annotation
    for presentations caused false negatives (SEC EDGAR press releases contain
    "(in thousands)" footnotes near legitimate customer metric values). Financial
    context filtering for presentations is instead handled by the more precise
    _rule_financial_context_on_customer_metric rule.

    When relaxed=False (for SEC filings), rules tagged in _STRICT_SKIP_TAGS
    are skipped.  _STRICT_SKIP_TAGS is currently empty; the arpu rule that
    formerly required this was made mode-agnostic via a binding_type guard.

    After the registry loop, additional transcript-specific checks are applied
    when relaxed=True:
    - Bare small count values (single/double-digit without scale suffix)
    - Q&A hedging percent: percent values with hedging language nearby
    - Q&A currency on count metric: currency values on count-only metrics

    Returns:
        Tuple of (is_false_positive, reason) — reason is None if not FP.
    """
    # Always suppress extraction from operator boilerplate and legal disclaimers.
    # These sections contain no meaningful metric disclosures.
    if section_type in (SectionType.OPERATOR, SectionType.DISCLAIMER):
        return True, "v2_suppressed_section"

    # Suppress facts from title slides and appendix slides.
    # Title slides typically contain dates, company names, and non-metric numbers
    # (e.g., copyright year, address numbers). Appendix slides contain supplemental
    # detail that may produce FPs from footnotes and reference numbers.
    if section_type in (SectionType.TITLE_SLIDE, SectionType.APPENDIX):
        return True, "v2_presentation_suppressed_section"

    # Suppress bare small integers from presentation slides (likely page numbers).
    # Slide numbers, footnote references, and other ordinals appear as small
    # integers (< 1000) in presentation context without scale suffixes.
    if (
        section_type in (SectionType.PRESENTATION_SLIDE, SectionType.TITLE_SLIDE, SectionType.APPENDIX)
        and bv.value is not None
        and bv.value < 1000
        and bv.unit in (Unit.COUNT, Unit.OTHER)
    ):
        return True, "v2_presentation_page_number"

    if relaxed:
        skip_tags = (
            _PRESENTATION_SKIP_TAGS
            if document_type == "investor_presentation"
            else _TRANSCRIPT_SKIP_TAGS
        )
    else:
        skip_tags = _STRICT_SKIP_TAGS

    for tag, rule_fn, soft in _FP_RULES:
        if tag in skip_tags:
            continue
        if soft and binding_confidence >= _SOFT_RULE_CONFIDENCE_FLOOR:
            continue
        reason = rule_fn(bv, source_text, metric_id)
        if reason is not None:
            return True, reason

    # Relaxed mode only: bare small count values.
    # In transcript text, bare single/double-digit numbers with unit=count or
    # unit=other are almost always noise — slide numbers ("Slide 6"), quarter
    # refs ("Q4" → 4), technology labels ("5G" → 5), multipliers ("4 times"),
    # product names ("Dynamics 365" → 365), or ranking superlatives ("top 10").
    # Legitimate count values in transcripts either use scale suffixes ("3,000",
    # "1.5 million") or are large enough to be unambiguous (>= 50).
    # Unit.OTHER is included because bare integers without commas/scale/currency
    # parse as OTHER (e.g., "4" from "4 or more workloads").
    if relaxed and bv.unit in (Unit.COUNT, Unit.OTHER):
        raw = (bv.value_raw or "").strip()
        if section_type == SectionType.QA:
            threshold = _BARE_SMALL_NUMBER_THRESHOLD_QA
        elif section_type == SectionType.PREPARED_REMARKS:
            threshold = _BARE_SMALL_NUMBER_THRESHOLD_PREPARED
        else:
            threshold = _BARE_SMALL_NUMBER_THRESHOLD
        if bv.value is not None and bv.value < threshold:
            if not _HAS_SCALE_SUFFIX_RE.search(raw):
                return True, "v2_bare_small_count"

    # Q&A-specific rules (only applied in Q&A sections in relaxed mode).
    if relaxed and section_type == SectionType.QA:

        # Rule: Q&A hedging percent.
        # Analysts frequently repeat growth rates speculatively or ask
        # "was it 20%?" / "assuming 15% margin" — these are not metric
        # disclosures.  Reject percent values when hedging language appears
        # within ~10 words of the value.
        # Conservative: only fires when hedging is detected; fails open
        # if value position cannot be determined.
        if bv.unit == Unit.PERCENT and source_text:
            if _qa_hedging_percent_near_value(source_text, bv.value_raw or ""):
                return True, "v2_qa_hedging_percent"

        # Rule: Q&A currency value on a count-only metric.
        # In Q&A, an analyst may quote a dollar figure near a customer-count
        # keyword (e.g., "How does the $50 million figure relate to MAUs?").
        # Count-only metrics can never take a currency value.
        # Note: a broader version of this check also runs in process() for
        # all sections; this check ensures it fires inside _is_v2_false_positive
        # so the reason tag reflects the Q&A context.
        if bv.unit == Unit.CURRENCY and metric_id in _DOLLAR_REJECT_METRICS:
            return True, "v2_qa_currency_on_count"

    # Relaxed mode: forward guidance detection (all sections).
    # Earnings calls sometimes contain forward guidance figures mixed with
    # reported actuals.  When present-tense guidance language ("we expect",
    # "our outlook", "we guide") appears within ±100 chars of the value,
    # the figure is projected rather than reported — reject it.
    # Uses ±100 chars (wider than ±80) to handle range-guidance phrasing like
    # "we expect ... between X and Y" where X may be ~90 chars before Y.
    if relaxed and source_text:
        raw = (bv.value_raw or "").strip()
        if raw:
            # Prefer the span from source_locator if available to avoid
            # mis-positioning when raw is a short string (e.g., "6") that
            # appears multiple times in the segment.
            text_span = bv.source_locator.text_span
            if text_span is not None:
                value_pos = text_span[0]
            else:
                value_pos = source_text.find(raw)
            if value_pos >= 0:
                window_start = max(0, value_pos - 100)
                window_end = min(len(source_text), value_pos + len(raw) + 100)
                window = source_text[window_start:window_end]
                if _FORWARD_GUIDANCE_RE.search(window):
                    return True, "v2_forward_guidance"

    return False, None


def _get_source_text(
    bv: BoundValue,
    candidate_map: dict[str, Any],
    segments: list[Segment],
    tables: list[Table],
) -> str:
    """
    Get the source text surrounding a BoundValue for false positive checking.

    For table-sourced values, reconstructs context from header_path + stub_path + cell text.
    For text-sourced values, retrieves the segment text.
    """
    # Try to get the candidate for context
    candidate = candidate_map.get(bv.candidate_id)

    loc = bv.source_locator

    # Table-sourced values: build context from table structure
    if loc.table_id is not None:
        for table in tables:
            if table.table_id == loc.table_id:
                parts: list[str] = []
                if loc.cell_row is not None and loc.cell_col is not None:
                    cell = table.get_cell(loc.cell_row, loc.cell_col)
                    if cell:
                        parts.extend(cell.header_path)
                        parts.extend(cell.stub_path)
                        parts.append(cell.text)
                return " ".join(parts)

    # Text-sourced values: get the segment text
    if loc.segment_id is not None:
        for segment in segments:
            if segment.segment_id == loc.segment_id:
                return segment.text

    # Fall back to candidate context_text
    if candidate and hasattr(candidate, "context_text"):
        return candidate.context_text

    return ""


_UNIT_MAP = {
    Unit.PERCENT: "percentage",
    Unit.CURRENCY: "currency",
    Unit.COUNT: "count",
    Unit.RATIO: "count",
    Unit.BASIS_POINTS: "percentage",
    Unit.OTHER: "count",
}


def _make_number_matches(bv: BoundValue, source_text: str) -> list[NumberMatch]:
    """
    Create V1 NumberMatch(es) for every occurrence of the raw value in source_text.

    The V1 filter relies on the number's position in the text to check for
    overlap with date/reference patterns. V2 BoundValue text_span positions
    are relative to the proximity window, not the full segment text, so we
    find all occurrences of the raw value text and return a NumberMatch for
    each one.

    The caller should treat the value as FP only if ALL occurrences are FP.
    """
    v1_unit = _UNIT_MAP.get(bv.unit, "count")
    value_decimal = Decimal(str(bv.value)) if bv.value is not None else None
    raw = bv.value_raw or ""

    if not raw:
        return [NumberMatch(start=0, end=0, raw_text=raw, value=value_decimal, unit=v1_unit)]

    matches: list[NumberMatch] = []
    search_start = 0
    while True:
        pos = source_text.find(raw, search_start)
        if pos < 0:
            break
        matches.append(
            NumberMatch(
                start=pos,
                end=pos + len(raw),
                raw_text=raw,
                value=value_decimal,
                unit=v1_unit,
            )
        )
        search_start = pos + len(raw)

    if not matches:
        # Fallback: position-independent (filter still checks year/min-value)
        matches.append(
            NumberMatch(
                start=0,
                end=len(raw),
                raw_text=raw,
                value=value_decimal,
                unit=v1_unit,
            )
        )

    return matches


class FalsePositiveFilterStage:
    """
    Stage 7.5: False Positive Filtering.

    Two-layer filtering:

    V2-native rules (run first):
    - Year values for ALL unit types (V1 only handles unit=count)
    - Truncated year fragments: sub-spans of longer digit runs (v2_truncated_year) and
      2-digit fiscal-year column headers like "20"/"21" in table header rows (v2_two_digit_year_header)
    - Linearized table text ([CELL]/[ROW] marker detection) — skipped in relaxed mode
    - Financial table annotations ("In thousands", "stock-based compensation") — skipped in relaxed mode
    - Company ranking names ("Fortune 100", "Forbes 500")

    V1 FalsePositiveFilter (positional overlap):
    - Date components (numbers inside dates like "January 31, 2019")
    - Label-embedded values (">$100,000" threshold definitions)
    - Reference numbers (page, note, section, exhibit, figure, etc.)
    - Year values (standalone 4-digit years 1990-2100, count unit only)
    - Measurement units ("24-hour", "30-day")
    - TOC proximity and dot leader page references — skipped in relaxed mode
    - Financial statement line items — skipped in relaxed mode
    - Below-minimum-value counts

    Relaxed mode (for transcripts/presentations) disables SEC-filing-specific
    checks that cause excessive false negatives on spoken content.
    """

    def __init__(self) -> None:
        """Initialize with V1 FalsePositiveFilter instances (normal + relaxed)."""
        self._filter = FalsePositiveFilter()
        # Relaxed filter for transcripts/presentations:
        # - Disables financial statement context check (SEC-specific)
        # - Disables V1 year filtering (V2 rule 1 already catches year values)
        # - Lowers min_metric_value to 2 (transcripts report small growth
        #   percentages like "4%" that would be filtered at the default of 10)
        self._filter_relaxed = FalsePositiveFilter(
            filter_financial_statements=False,
            filter_years=False,
            min_value=2,
        )

    def process(self, context: PipelineContext) -> StageResult:
        """
        Filter false positive BoundValues.

        Iterates through context.bound_values, checks each against the V1
        FalsePositiveFilter, and removes those flagged as false positives.
        """
        try:
            start_time = datetime.now(UTC)
            errors: list[str] = []
            warnings: list[str] = []

            initial_count = len(context.bound_values)
            filter_reasons: dict[str, int] = {}
            conversion_reasons: dict[str, int] = {}

            # Read relaxed mode from config (for transcripts/presentations)
            relaxed = getattr(context.config, "relaxed_fp_filter", False)

            # Snapshot pre-filter state for FN diagnostics (only when requested)
            if getattr(context.config, "retain_context", False):
                context._pre_filter_bound_values = list(context.bound_values)

            # Build candidate lookup for context text
            candidate_map = {c.candidate_id: c for c in context.candidates}

            # Filter bound values
            kept: list[BoundValue] = []
            for bv in context.bound_values:
                try:
                    # Get source text for context
                    source_text = _get_source_text(
                        bv, candidate_map, context.segments, context.tables
                    )

                    if not source_text:
                        # No context available; keep the value (conservative)
                        kept.append(bv)
                        continue

                    # --- V2-native checks (run first, cheaper than V1) ---
                    candidate = candidate_map.get(bv.candidate_id)
                    metric_id = candidate.metric_id if candidate else ""
                    v2_fp, v2_reason = _is_v2_false_positive(
                        bv,
                        source_text,
                        metric_id=metric_id,
                        relaxed=relaxed,
                        section_type=candidate.section_type if candidate else SectionType.UNKNOWN,
                        document_type=context.document_type,
                        binding_confidence=bv.binding_confidence,
                    )
                    if v2_fp:
                        filter_reasons[v2_reason or "v2_unknown"] = (
                            filter_reasons.get(v2_reason or "v2_unknown", 0) + 1
                        )
                        logger.debug(
                            "V2 FP filter removed BoundValue %s: reason=%s value=%s raw=%r",
                            bv.bound_value_id,
                            v2_reason,
                            bv.value,
                            bv.value_raw,
                        )
                        continue

                    # --- V1 positional filter ---
                    # Build NumberMatches for all occurrences of the raw
                    # value in the source text. The value is FP only if ALL
                    # occurrences are flagged (conservative: if any occurrence
                    # is in a legitimate context, keep the value).
                    # Use relaxed filter for transcripts (skips financial
                    # statement context and TOC proximity checks).
                    v1_filter = self._filter_relaxed if relaxed else self._filter
                    number_matches = _make_number_matches(bv, source_text)

                    is_fp = True
                    reason: str | None = None
                    for nm in number_matches:
                        fp, r = v1_filter.is_false_positive(source_text, nm)
                        if not fp:
                            is_fp = False
                            reason = None
                            break
                        reason = r

                    # Override V1 financial_line_item for ratio/rate metrics.
                    # These values (percentages, ratios) can never be financial
                    # statement figures, so the V1 positional check is a false
                    # positive on a false positive.
                    if (
                        is_fp
                        and reason is not None
                        and reason.startswith("financial_line_item")
                        and (metric_id in _V1_FINANCIAL_OVERRIDE_METRICS
                             or bv.binding_confidence >= _SOFT_RULE_CONFIDENCE_FLOOR)
                    ):
                        is_fp = False
                        reason = None

                    if is_fp:
                        filter_reasons[reason or "unknown"] = (
                            filter_reasons.get(reason or "unknown", 0) + 1
                        )
                        logger.debug(
                            "FP filter removed BoundValue %s: reason=%s value=%s raw=%r",
                            bv.bound_value_id,
                            reason,
                            bv.value,
                            bv.value_raw,
                        )
                        continue

                    # --- Clause gate for percent on MAU/DAU (relaxed mode) ---
                    # In transcript text like "TPV grew 50% and MAAs grew 30%",
                    # both percents are in the proximity window but only "30%"
                    # belongs to MAU.  Split on conjunctions and verify the
                    # percent is in the same clause as the keyword.
                    if relaxed and bv.unit == Unit.PERCENT:
                        cand_gate = candidate_map.get(bv.candidate_id)
                        if (
                            cand_gate
                            and cand_gate.metric_id in _PERCENT_CLAUSE_GATE_METRICS
                        ):
                            if not _is_percent_in_keyword_clause(
                                source_text,
                                cand_gate.source_locator.text_span,
                                bv.value_raw or "",
                            ):
                                reason_str = "v2_percent_wrong_clause"
                                filter_reasons[reason_str] = (
                                    filter_reasons.get(reason_str, 0) + 1
                                )
                                logger.debug(
                                    "FP filter rejected percent in wrong clause "
                                    "for %s: %s raw=%r",
                                    cand_gate.metric_id,
                                    bv.value,
                                    bv.value_raw,
                                )
                                continue

                    # --- Currency on count-only metrics: reject as FP ---
                    # Metrics like MAU/DAU/active_customers are always counts.
                    # An explicit $/EUR/GBP prefix strongly signals a dollar
                    # amount, not a user count.  Reject rather than convert.
                    # Runs after V1 to let label-embedded filters (">$100,000")
                    # remove true FPs first.
                    if bv.unit == Unit.CURRENCY:
                        if candidate and candidate.metric_id in _DOLLAR_REJECT_METRICS:
                            reason_str = "v2_currency_on_count_metric"
                            filter_reasons[reason_str] = (
                                filter_reasons.get(reason_str, 0) + 1
                            )
                            logger.debug(
                                "FP filter rejected currency on count metric %s: %s raw=%r",
                                candidate.metric_id,
                                bv.value,
                                bv.value_raw,
                            )
                            continue

                    kept.append(bv)

                except Exception as e:
                    error_msg = f"Error filtering BoundValue {bv.bound_value_id}: {e}"
                    logger.error(error_msg)
                    errors.append(error_msg)
                    # On error, keep the value (fail open for individual items)
                    kept.append(bv)

            # --- Cross-metric dedup: same value + same segment → keep best ---
            # When the same raw value from the same segment is bound to multiple
            # metric IDs, only the highest-confidence binding is meaningful.
            # E.g., "20 million" → customers_period_end (0.46) AND
            #        large_customers_period_end (0.46) from the same segment.
            kept = self._cross_metric_dedup(kept, candidate_map, filter_reasons)

            removed_count = initial_count - len(kept)
            context.bound_values = kept

            # Log summary
            logger.info(
                "False positive filter: %d/%d removed, %d converted (%d kept). "
                "Reasons: %s. Conversions: %s",
                removed_count,
                initial_count,
                sum(conversion_reasons.values()),
                len(kept),
                dict(filter_reasons),
                dict(conversion_reasons),
            )

            return self._make_result(
                start_time,
                initial_count,
                len(kept),
                errors,
                warnings,
                filter_reasons,
                conversion_reasons,
            )
        except V2FatalError:
            raise
        except Exception as e:
            raise V2FatalError(str(e), stage_name="false_positive_filter") from e

    @staticmethod
    def _cross_metric_dedup(
        kept: list[BoundValue],
        candidate_map: dict[str, Any],
        filter_reasons: dict[str, int],
    ) -> list[BoundValue]:
        """
        When the same raw value from the same segment is bound to different
        metric IDs, keep only the highest-confidence binding.

        Groups by (segment_id, value_raw) and within each group, if multiple
        metric IDs are present, keeps only the one with the highest
        binding_confidence.  Ties broken by candidate_id for stability.
        """
        from collections import defaultdict

        # Group by (segment_id, value_raw)
        groups: dict[tuple[str | None, str], list[BoundValue]] = defaultdict(list)
        for bv in kept:
            key = (bv.source_locator.segment_id, bv.value_raw)
            groups[key].append(bv)

        result: list[BoundValue] = []
        removed = 0

        for (seg_id, raw), group in groups.items():
            if len(group) <= 1:
                result.extend(group)
                continue

            # Check if multiple metric IDs are present
            metric_ids = set()
            for bv in group:
                cand = candidate_map.get(bv.candidate_id)
                if cand:
                    metric_ids.add(cand.metric_id)

            if len(metric_ids) <= 1:
                # All same metric — not a cross-metric dup, keep all
                result.extend(group)
                continue

            # Don't dedup between a metric and its "_by_cohort" sibling —
            # they represent distinct real-world measurements (overall vs
            # per-cohort) and can legitimately co-occur in the same segment.
            # E.g., "LTV:CAC ratio of 1.42x (2013 cohort)" can match both
            # cm_ltv_to_cac_ratio and cm_ltv_to_cac_ratio_by_cohort.
            if any(
                m1 + "_by_cohort" in metric_ids
                for m1 in metric_ids
                if not m1.endswith("_by_cohort")
            ):
                result.extend(group)
                continue

            # Don't dedup across retention family members (GRR, NRR, CRR).
            # These measure distinct retention concepts and can co-occur in the
            # same section (e.g., a filing may report both gross and net retention
            # in the same paragraph).
            if len(metric_ids & _RETENTION_FAMILY) >= 2:
                result.extend(group)
                continue

            # Multiple unrelated metrics for same value+segment: keep the best.
            # Tie-break with stable content-derived keys (segment_id, cell position, raw
            # value) instead of random UUIDs so results are deterministic across runs.
            best = max(
                group,
                key=lambda bv: (
                    bv.binding_confidence,
                    bv.source_locator.segment_id or "",
                    bv.source_locator.cell_row or 0,
                    bv.source_locator.cell_col or 0,
                    bv.value_raw,
                ),
            )
            result.append(best)
            removed += len(group) - 1

            logger.debug(
                "Cross-metric dedup: kept %s (conf=%.2f) from %d bindings "
                "for value %r in segment %s",
                candidate_map.get(best.candidate_id, best.candidate_id),
                best.binding_confidence,
                len(group),
                raw,
                seg_id,
            )

        if removed > 0:
            filter_reasons["v2_cross_metric_dedup"] = (
                filter_reasons.get("v2_cross_metric_dedup", 0) + removed
            )

        return result

    def _make_result(
        self,
        start_time: datetime,
        items_processed: int,
        items_output: int,
        errors: list[str],
        warnings: list[str],
        filter_reasons: dict[str, int],
        conversion_reasons: dict[str, int] | None = None,
    ) -> StageResult:
        """Create a StageResult with timing and filter statistics."""
        end_time = datetime.now(UTC)
        duration_ms = int((end_time - start_time).total_seconds() * 1000)

        from src.extraction_v2.pipeline import PipelineStage, StageResult

        return StageResult(
            stage=PipelineStage.FALSE_POSITIVE_FILTER,
            success=len(errors) == 0,
            duration_ms=duration_ms,
            items_processed=items_processed,
            items_output=items_output,
            errors=errors,
            warnings=warnings,
            metadata={
                "removed_count": items_processed - items_output,
                "filter_reasons": filter_reasons,
                "conversion_reasons": conversion_reasons or {},
            },
        )
