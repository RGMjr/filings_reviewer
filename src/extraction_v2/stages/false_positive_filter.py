"""
V2 False Positive Filter Stage

Stage 7.5 of the V2 extraction pipeline. Runs between value binding (Stage 7)
and period inference (Stage 8) to remove false positive BoundValues using V1's
proven FalsePositiveFilter.

This reuses V1's filter rather than duplicating logic:
- Date context patterns (8 patterns)
- Label-embedded value detection
- Reference number filtering (page, note, section, etc.)
- Year filtering (1990-2100)
- Min value threshold
- TOC proximity / dot leader detection
- Financial statement context detection
- Measurement unit patterns

Design principles:
- Reuse V1 filters (single source of truth)
- Log filter statistics per reason for diagnostics
- Non-destructive: only removes BoundValues from context.bound_values
"""

from __future__ import annotations

import logging
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from src.extraction_v2.models import BoundValue, SourceType, Unit
from src.review.false_positive_filter import FalsePositiveFilter
from src.review.number_parsing import NumberMatch

if TYPE_CHECKING:
    from src.extraction_v2.models import Segment, Table
    from src.extraction_v2.pipeline import PipelineContext, StageResult

logger = logging.getLogger(__name__)


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


def _make_number_matches(
    bv: BoundValue, source_text: str
) -> list[NumberMatch]:
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
        matches.append(NumberMatch(
            start=pos,
            end=pos + len(raw),
            raw_text=raw,
            value=value_decimal,
            unit=v1_unit,
        ))
        search_start = pos + len(raw)

    if not matches:
        # Fallback: position-independent (filter still checks year/min-value)
        matches.append(NumberMatch(
            start=0, end=len(raw), raw_text=raw,
            value=value_decimal, unit=v1_unit,
        ))

    return matches


class FalsePositiveFilterStage:
    """
    Stage 7.5: False Positive Filtering.

    Removes false positive BoundValues using V1's FalsePositiveFilter:
    - Date components (numbers inside dates like "January 31, 2019")
    - Label-embedded values (">$100,000" threshold definitions)
    - Reference numbers (page, note, section, exhibit, figure, etc.)
    - Year values (standalone 4-digit years 1990-2100)
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
                error_msg = (
                    f"Error filtering BoundValue {bv.bound_value_id}: {e}"
                )
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
