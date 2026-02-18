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
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any

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

# Company ranking names — "Fortune 100", "Forbes 500", "Global 2000", etc.
_RANKING_NAME_RE = re.compile(
    r"\b(?:Fortune|Forbes|Inc\.?|Global)\s+(\d[\d,]*)\b",
    re.IGNORECASE,
)


def _is_v2_false_positive(
    bv: BoundValue,
    source_text: str,
    metric_id: str = "",
) -> tuple[bool, str | None]:
    """
    V2-native false positive checks that go beyond V1's positional filter.

    These rules exploit V2 pipeline context that V1 doesn't have:
    - Year values across all unit types (V1 only checks unit=count)
    - Linearized table markers that indicate duplicate text extraction
    - Financial table annotations that mark non-metric financial data
    - Ranking names where a number is part of a name, not a value
    - Percentage-metric range validation (reject > 500 for percent-only metrics)
    - Garbage value detection (absurdly large numbers)

    Returns:
        Tuple of (is_false_positive, reason) — reason is None if not FP.
    """
    raw = (bv.value_raw or "").strip()

    # Rule 1: Year value for ALL units (V1 only filters unit=count).
    # Catches e.g. "2019" extracted as cm_net_revenue_retention with unit=PERCENT.
    if bv.value is not None and _YEAR_MIN <= bv.value <= _YEAR_MAX:
        stripped = raw.replace(",", "")
        if stripped.isdigit() and len(stripped) == 4:
            return True, "v2_year_value"

    # Rule 5: Percentage-metric range validation.
    # Percentage-only metrics (NRR, churn, etc.) should have values in 0-500 range.
    # Values like 37000 or 95000 near an NRR keyword are clearly not percentages.
    if bv.value is not None and metric_id in _PERCENT_ONLY_METRICS:
        if bv.value > 500 or bv.value < 0:
            return True, "v2_percent_range"

    # Rule 6: Garbage value detection.
    # Numbers with >10 digits (>10 billion) are almost certainly parsing artifacts
    # (e.g., concatenated dates like 9202020192020).
    if bv.value is not None and abs(bv.value) > 10_000_000_000:
        return True, "v2_garbage_value"

    if not source_text:
        return False, None

    # Rule 2: Linearized table text ([CELL]/[ROW] markers).
    # The ingestion stage injects these markers when linearizing HTML tables
    # into text segments.  The same table data is also processed by the
    # table-reconstruction path, so these text-sourced extractions are noisy
    # duplicates that bypass the structured header/stub binding.
    if _TABLE_MARKER_RE.search(source_text):
        return True, "v2_linearized_table"

    # Rule 3: Financial table annotation text.
    # Only flag as FP if annotation is within 300 chars of the bound value.
    # Exempt table-sourced values: structural header/stub binding is more
    # reliable than text proximity, and "(In thousands)" is a scale indicator,
    # not evidence of non-metric financial data in table context.
    if bv.source_locator.table_id is None:
        value_pos = source_text.find(raw) if raw else -1
        ann_match = _FINANCIAL_ANNOTATION_RE.search(source_text)
        if ann_match:
            if value_pos < 0 or abs(ann_match.start() - value_pos) <= 300:
                return True, "v2_financial_annotation"
        sbc_match = _SBC_RE.search(source_text)
        if sbc_match:
            if value_pos < 0 or abs(sbc_match.start() - value_pos) <= 300:
                return True, "v2_financial_sbc"

    # Rule 4: Company ranking name.
    # "Fortune 100", "Forbes 500" — the number is part of the ranking name.
    if raw:
        for m in _RANKING_NAME_RE.finditer(source_text):
            if m.group(1) == raw:
                return True, "v2_ranking_name"

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
        start_time = datetime.utcnow()
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
                source_text = _get_source_text(bv, candidate_map, context.segments, context.tables)

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
        end_time = datetime.utcnow()
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
