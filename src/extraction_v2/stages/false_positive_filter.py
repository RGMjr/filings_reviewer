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
from src.extraction_v2.models import BoundValue, Unit
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

# Financial table annotation — "(In thousands)", "(In millions)", etc.
_FINANCIAL_ANNOTATION_RE = re.compile(
    r"\(\s*in\s+(?:thousands|millions|billions|hundreds)\s*\)",
    re.IGNORECASE,
)

# Stock-based compensation footnote — strong financial context signal
_SBC_RE = re.compile(r"stock[- ]based\s+compensation", re.IGNORECASE)

# Linearized table markers injected by the ingestion stage
_TABLE_MARKER_RE = re.compile(r"\[(?:CELL|ROW)\]")

# Maximum gap (chars) between end of a [CELL] marker and a value position for
# the value to be treated as a column entry rather than embedded prose text.
# Layout tables used for bullet indentation produce a [CELL] marker at column 1
# but the actual prose text (and any numbers within it) appear far to the right.
_CELL_VALUE_PROXIMITY = 40

# Company ranking names — "Fortune 100", "Forbes 500", "Global 2000", etc.
_RANKING_NAME_RE = re.compile(
    r"\b(?:Fortune|Forbes|Inc\.?|Global)\s+(\d[\d,]*)\b",
    re.IGNORECASE,
)

# Geographic revenue context — "international", "domestic", "geographic" etc.
# Used to suppress cm_revenue_concentration FPs from geographic revenue breakdowns.
_GEOGRAPHIC_REVENUE_RE = re.compile(
    r"\b(?:international|domestic|geographic|geography|united\s+states|americas|emea|apac|"
    r"asia[- ]pacific|europe|rest\s+of\s+(?:the\s+)?world)\b",
    re.IGNORECASE,
)

# Developer/engineer count context.
# Used to suppress cm_daily_active_users FPs from developer registration counts.
_DEVELOPER_COUNT_RE = re.compile(
    r"\b(?:registered\s+)?(?:developers?|engineers?|api\s+users?|third[- ]party\s+developers?)\b",
    re.IGNORECASE,
)

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


def _rule_linearized_table(bv: BoundValue, source_text: str, metric_id: str) -> str | None:
    """Suppress values that appear as column entries in linearized tables.

    [CELL]/[ROW] markers are injected by ingestion when a <TABLE> is flattened
    to text.  Layout tables (e.g., bullet-point indentation) also produce these
    markers but contain prose paragraphs, not columnar data.

    A value is treated as a column entry — and suppressed — only when it appears
    within _CELL_VALUE_PROXIMITY characters after a [CELL] or [ROW] marker.
    Prose values that happen to sit in a layout-table segment are left intact.
    """
    if not source_text:
        return None
    if not _TABLE_MARKER_RE.search(source_text):
        return None

    raw = (bv.value_raw or "").strip()
    if not raw:
        # Cannot locate value in text — suppress conservatively.
        return "v2_linearized_table"

    value_pos = source_text.find(raw)
    if value_pos < 0:
        # Value not found in source text — suppress conservatively.
        return "v2_linearized_table"

    # Fire only when value_raw is within proximity of a preceding marker.
    for m in _TABLE_MARKER_RE.finditer(source_text):
        marker_end = m.end()
        if marker_end <= value_pos <= marker_end + _CELL_VALUE_PROXIMITY:
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


def _rule_geographic_revenue(bv: BoundValue, source_text: str, metric_id: str) -> str | None:
    """Geographic revenue context for cm_revenue_concentration."""
    if not source_text or metric_id != "cm_revenue_concentration":
        return None
    raw = (bv.value_raw or "").strip()
    if not raw:
        return None
    geo_match = _GEOGRAPHIC_REVENUE_RE.search(source_text)
    if geo_match:
        value_pos = source_text.find(raw)
        if value_pos >= 0 and abs(geo_match.start() - value_pos) <= 200:
            return "v2_geographic_revenue"
    return None


def _rule_developer_count(bv: BoundValue, source_text: str, metric_id: str) -> str | None:
    """Developer/engineer count mistaken for cm_daily_active_users."""
    if not source_text or metric_id != "cm_daily_active_users":
        return None
    raw = (bv.value_raw or "").strip()
    if not raw:
        return None
    dev_match = _DEVELOPER_COUNT_RE.search(source_text)
    if dev_match:
        value_pos = source_text.find(raw)
        if value_pos >= 0 and abs(dev_match.start() - value_pos) <= 150:
            return "v2_developer_count"
    return None


def _rule_fortune_subset(bv: BoundValue, source_text: str, metric_id: str) -> str | None:
    """Fortune/Forbes subset count for cm_customers_period_end."""
    if not source_text or metric_id != "cm_customers_period_end":
        return None
    raw = (bv.value_raw or "").strip()
    if not raw:
        return None
    fortune_match = _FORTUNE_SUBSET_RE.search(source_text)
    if fortune_match:
        value_pos = source_text.find(raw)
        if value_pos >= 0 and abs(fortune_match.start() - value_pos) <= 100:
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
    """
    if not source_text or metric_id == "cm_large_customers_period_end":
        return None
    raw = (bv.value_raw or "").strip()
    if not raw:
        return None
    threshold_match = _DOLLAR_THRESHOLD_CUSTOMER_RE.search(source_text)
    if threshold_match:
        value_pos = source_text.find(raw)
        if value_pos >= 0 and abs(threshold_match.start() - value_pos) <= 400:
            return "v2_dollar_threshold_customer"
    return None


# =============================================================================
# FP Rule Registry — order matters (first match wins)
# =============================================================================

_FP_RULES: list[tuple[str, Callable[[BoundValue, str, str], str | None]]] = [
    ("year_value", _rule_year_value),
    ("percent_range", _rule_percent_range),
    ("garbage_value", _rule_garbage_value),
    ("year_fragment", _rule_year_fragment),
    ("linearized_table", _rule_linearized_table),
    ("financial_annotation", _rule_financial_annotation),
    ("financial_sbc", _rule_financial_sbc),
    ("ranking_name", _rule_ranking_name),
    ("geographic_revenue", _rule_geographic_revenue),
    ("developer_count", _rule_developer_count),
    ("fortune_subset", _rule_fortune_subset),
    ("tier_qualifier", _rule_tier_qualifier),
    ("dollar_threshold_customer", _rule_dollar_threshold_customer),
]


def _is_v2_false_positive(
    bv: BoundValue,
    source_text: str,
    metric_id: str = "",
) -> tuple[bool, str | None]:
    """
    V2-native false positive checks that go beyond V1's positional filter.

    Iterates over registered FP rules and returns the first match.

    Returns:
        Tuple of (is_false_positive, reason) — reason is None if not FP.
    """
    for _name, rule_fn in _FP_RULES:
        reason = rule_fn(bv, source_text, metric_id)
        if reason is not None:
            return True, reason
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
    - Linearized table text ([CELL]/[ROW] marker detection)
    - Financial table annotations ("In thousands", "stock-based compensation")
    - Company ranking names ("Fortune 100", "Forbes 500")

    V1 FalsePositiveFilter (positional overlap):
    - Date components (numbers inside dates like "January 31, 2019")
    - Label-embedded values (">$100,000" threshold definitions)
    - Reference numbers (page, note, section, exhibit, figure, etc.)
    - Year values (standalone 4-digit years 1990-2100, count unit only)
    - Measurement units ("24-hour", "30-day")
    - TOC proximity and dot leader page references
    - Financial statement line items
    - Below-minimum-value counts
    """

    def __init__(self) -> None:
        """Initialize with a V1 FalsePositiveFilter instance."""
        self._filter = FalsePositiveFilter()

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

            # Snapshot pre-filter state for FN diagnostics (only when requested)
            if context.config.retain_context:
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
                    v2_fp, v2_reason = _is_v2_false_positive(bv, source_text, metric_id)
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
                    number_matches = _make_number_matches(bv, source_text)

                    is_fp = True
                    reason: str | None = None
                    for nm in number_matches:
                        fp, r = self._filter.is_false_positive(source_text, nm)
                        if not fp:
                            is_fp = False
                            reason = None
                            break
                        reason = r

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
                    else:
                        kept.append(bv)

                except Exception as e:
                    error_msg = f"Error filtering BoundValue {bv.bound_value_id}: {e}"
                    logger.error(error_msg)
                    errors.append(error_msg)
                    # On error, keep the value (fail open for individual items)
                    kept.append(bv)

            removed_count = initial_count - len(kept)
            context.bound_values = kept

            # Log summary
            logger.info(
                "False positive filter: %d/%d removed (%d kept). Reasons: %s",
                removed_count,
                initial_count,
                len(kept),
                dict(filter_reasons),
            )

            return self._make_result(
                start_time,
                initial_count,
                len(kept),
                errors,
                warnings,
                filter_reasons,
            )
        except V2FatalError:
            raise
        except Exception as e:
            raise V2FatalError(str(e), stage_name="false_positive_filter") from e

    def _make_result(
        self,
        start_time: datetime,
        items_processed: int,
        items_output: int,
        errors: list[str],
        warnings: list[str],
        filter_reasons: dict[str, int],
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
            },
        )
