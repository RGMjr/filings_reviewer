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

from src.extraction_v2.models import BoundValue, SourceType, Unit
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

# Scale suffixes that indicate a raw value represents a large number
# (e.g., "3 million", "1.5 billion", "400,000").  Bare single/double-digit
# numbers without these suffixes are almost always noise in transcript text
# (slide numbers, quarter refs like "Q4", "5G", multipliers like "4 times").
_HAS_SCALE_SUFFIX_RE = re.compile(
    r"(?:million|billion|thousand|,\d{3})", re.IGNORECASE
)

_BARE_SMALL_NUMBER_THRESHOLD = 50

# Metrics that are inherently user/activity counts — never currency.
# A dollar value bound to these metrics is always a false positive
# (e.g., "$224 million" extracted as cm_monthly_active_users).
_COUNT_ONLY_METRICS = frozenset({
    "cm_monthly_active_users",
    "cm_daily_active_users",
    "cm_active_customers_total",
    "cm_customers_period_end",
    "cm_new_customers_acquired",
    "cm_large_customers_period_end",
})


def _is_v2_false_positive(
    bv: BoundValue,
    source_text: str,
    relaxed: bool = False,
) -> tuple[bool, str | None]:
    """
    V2-native false positive checks that go beyond V1's positional filter.

    These rules exploit V2 pipeline context that V1 doesn't have:
    - Year values across all unit types (V1 only checks unit=count)
    - Linearized table markers that indicate duplicate text extraction
    - Financial table annotations that mark non-metric financial data
    - Ranking names where a number is part of a name, not a value

    When relaxed=True (for transcripts/presentations), rules 3 and 4
    (financial annotation and SBC) are skipped because these patterns
    are common in earnings call language and cause excessive false negatives.

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

    if not source_text:
        return False, None

    # Rule 2: Linearized table text ([CELL]/[ROW] markers).
    # The ingestion stage injects these markers when linearizing HTML tables
    # into text segments.  The same table data is also processed by the
    # table-reconstruction path, so these text-sourced extractions are noisy
    # duplicates that bypass the structured header/stub binding.
    # Skipped in relaxed mode (transcripts never have table markers).
    if not relaxed and _TABLE_MARKER_RE.search(source_text):
        return True, "v2_linearized_table"

    # Rules 3+4 skipped in relaxed mode (transcripts/presentations)
    if not relaxed:
        # Rule 3: Financial table annotation text.
        # Segments containing "(In thousands)" or "stock-based compensation" are
        # financial statement text, not customer metric narrative.
        if _FINANCIAL_ANNOTATION_RE.search(source_text):
            return True, "v2_financial_annotation"
        if _SBC_RE.search(source_text):
            return True, "v2_financial_sbc"

    # Rule 4: Company ranking name.
    # "Fortune 100", "Forbes 500" — the number is part of the ranking name.
    if raw:
        for m in _RANKING_NAME_RE.finditer(source_text):
            if m.group(1) == raw:
                return True, "v2_ranking_name"

    # Rule 5 (relaxed mode only): Bare small count values.
    # In transcript text, bare single/double-digit numbers with unit=count
    # are almost always noise — slide numbers ("Slide 6"), quarter refs
    # ("Q4" → 4), technology labels ("5G" → 5), multipliers ("4 times"),
    # or ranking superlatives ("top 10").  Legitimate count values in
    # transcripts either use scale suffixes ("3,000", "1.5 million") or
    # are large enough to be unambiguous (>= 50).
    if relaxed and bv.unit == Unit.COUNT:
        if bv.value is not None and bv.value < _BARE_SMALL_NUMBER_THRESHOLD:
            if not _HAS_SCALE_SUFFIX_RE.search(raw):
                return True, "v2_bare_small_count"

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

    Two-layer filtering:

    V2-native rules (run first):
    - Year values for ALL unit types (V1 only handles unit=count)
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
        start_time = datetime.utcnow()
        errors: list[str] = []
        warnings: list[str] = []

        initial_count = len(context.bound_values)
        filter_reasons: dict[str, int] = {}

        # Read relaxed mode from config (for transcripts/presentations)
        relaxed = getattr(context.config, "relaxed_fp_filter", False)

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
                v2_fp, v2_reason = _is_v2_false_positive(bv, source_text, relaxed=relaxed)
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

                # --- Currency on count-only metrics ---
                # Metrics like MAU/DAU/active_customers are always counts.
                # Dollar values bound to them are false positives (e.g.,
                # "$224 million" mistakenly bound to cm_monthly_active_users).
                if bv.unit == Unit.CURRENCY:
                    candidate = candidate_map.get(bv.candidate_id)
                    if candidate and candidate.metric_id in _COUNT_ONLY_METRICS:
                        reason_str = "v2_currency_on_count_metric"
                        filter_reasons[reason_str] = (
                            filter_reasons.get(reason_str, 0) + 1
                        )
                        logger.debug(
                            "FP filter removed currency value on count metric %s: %s raw=%r",
                            candidate.metric_id,
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

            # Multiple metrics for same value+segment: keep the best
            best = max(
                group,
                key=lambda bv: (bv.binding_confidence, bv.candidate_id),
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
