"""
V2 Value Binding Stage

Stage 7 of the V2 extraction pipeline. Links metric keyword candidates to their
numeric values using structural rules (table header/stub binding, text proximity).

Design principles:
- Rule-based first (no LLM calls)
- Structure-first binding (table headers/stubs before text proximity)
- Conservative binding (skip if ambiguous, don't guess)
"""

from __future__ import annotations

import logging
import re
from datetime import datetime
from typing import TYPE_CHECKING

from src.extraction_v2.models import (
    BoundValue,
    ImageAsset,
    MetricCandidate,
    SourceLocator,
    SourceType,
    Unit,
)
from src.extraction_v2.stages import number_parsing as _np
from src.extraction_v2.text_utils import find_sentence_bounds
from src.extraction_v2.unit_compatibility import (
    _COUNT_ONLY_METRICS,
    _CURRENCY_ONLY_METRICS,
    is_unit_compatible,
)
from src.review.false_positive_filter import should_treat_as_percentage

if TYPE_CHECKING:
    from src.extraction_v2.models import Cell, Segment, Table
    from src.extraction_v2.pipeline import PipelineContext, StageResult

logger = logging.getLogger(__name__)


class ValueBindingStage:
    """
    Stage 7: Value Binding.

    Links metric candidates to numeric values:
    - Table candidates: bind via header_path and stub_path
    - Text candidates: bind via sentence proximity
    - Chart candidates: stub (returns empty, Phase 5 dependency)

    Confidence scoring:
    - Base: 0.6 for table binding, 0.4 for text binding
    - +0.2 if metric keyword is exact match in header_path/stub_path
    - +0.1 if value has explicit unit (e.g., "$" or "%")
    - -0.1 if value is ambiguous (multiple candidates in proximity)
    """

    # Confidence scoring constants
    TABLE_BINDING_BASE: float = 0.6
    TEXT_BINDING_BASE: float = 0.4
    EXACT_MATCH_BONUS: float = 0.2
    UNIT_PRESENCE_BONUS: float = 0.1
    AMBIGUITY_PENALTY: float = 0.1
    SAME_SENTENCE_BONUS: float = 0.1
    DISTANCE_DECAY_THRESHOLD: int = 100  # Chars before decay starts
    MAX_DISTANCE_PENALTY: float = 0.1  # Max penalty at edge of window

    # Text proximity settings
    DEFAULT_WORD_PROXIMITY: int = 10  # Max words between keyword and value
    DEFAULT_CHAR_PROXIMITY: int = 100  # Max chars for proximity search

    # Number parsing constants — defined in stages/number_parsing.py
    NUMBER_PATTERN = _np.NUMBER_PATTERN
    SCALE_MULTIPLIERS = _np.SCALE_MULTIPLIERS
    TABLE_SCALE_PATTERN = _np.TABLE_SCALE_PATTERN
    TABLE_SCALE_EXCEPT_PATTERN = _np.TABLE_SCALE_EXCEPT_PATTERN
    TABLE_SCALE_MAP = _np.TABLE_SCALE_MAP

    def __init__(self, proximity_window: int = 100) -> None:
        """
        Initialize the value binding stage.

        Args:
            proximity_window: Max characters to search for values near text keywords (default: 100)
        """
        self.proximity_window = proximity_window
        self._unit_filtered_count = 0

    def _check_percentage_context(
        self, metric_id: str, unit: Unit, raw_text: str, context_text: str
    ) -> Unit:
        """
        Check if a count value should be treated as a percentage.

        For percentage-only metrics (e.g., cm_net_revenue_retention), values
        like "138" that appear in retention context should be Unit.PERCENT
        rather than Unit.COUNT. Uses V1's should_treat_as_percentage().

        Args:
            metric_id: Canonical metric ID
            unit: Currently detected unit
            raw_text: Raw value text (e.g., "138")
            context_text: Surrounding text for context

        Returns:
            Updated unit (PERCENT if context indicates percentage, else original)
        """
        if unit not in (Unit.COUNT, Unit.OTHER):
            return unit

        # Map V2 unit to V1 string for the function call
        v1_unit = "count"
        if should_treat_as_percentage(metric_id, raw_text, v1_unit, context_text):
            logger.debug(
                "Percentage context detected for %s: treating %r as percent",
                metric_id,
                raw_text,
            )
            return Unit.PERCENT
        return unit

    def _should_filter_unit(self, metric_id: str, unit: Unit) -> bool:
        """
        Check if a value should be filtered due to unit incompatibility.

        Args:
            metric_id: Canonical metric ID from the candidate
            unit: Detected unit from value parsing

        Returns:
            True if the value should be filtered out (incompatible unit).
        """
        if is_unit_compatible(metric_id, unit):
            return False
        logger.debug(
            "Filtering incompatible unit %s for metric %s",
            unit.value,
            metric_id,
        )
        self._unit_filtered_count += 1
        return True

    def process(self, context: PipelineContext) -> StageResult:
        """
        Bind values to metric candidates.

        Args:
            context: Pipeline context with candidates and tables

        Returns:
            StageResult with processing metrics
        """
        start_time = datetime.utcnow()
        bindings_found = 0
        errors: list[str] = []
        warnings: list[str] = []
        self._unit_filtered_count = 0

        # Process each candidate
        for candidate in context.candidates:
            try:
                bound_values = self._bind_candidate(candidate, context)
                for bv in bound_values:
                    context.bound_values.append(bv)
                    bindings_found += 1
            except Exception as e:
                error_msg = f"Error binding candidate {candidate.candidate_id}: {e}"
                logger.error(error_msg)
                errors.append(error_msg)

        logger.info(
            f"Value binding complete: {bindings_found} bindings "
            f"from {len(context.candidates)} candidates "
            f"({self._unit_filtered_count} unit-filtered)"
        )

        return self._make_result(
            start_time,
            len(context.candidates),
            bindings_found,
            errors,
            warnings,
        )

    def _bind_candidate(
        self,
        candidate: MetricCandidate,
        context: PipelineContext,
    ) -> list[BoundValue]:
        """
        Bind a single candidate to its value(s).

        Args:
            candidate: The metric candidate to bind
            context: Pipeline context with tables and segments

        Returns:
            List of BoundValue objects (may be empty if no binding found)
        """
        # Route by source type
        if candidate.source_type in (SourceType.HTML_TABLE, SourceType.OCR_TABLE):
            # Both HTML and OCR tables use the same binding strategy
            return self._bind_table_candidate(candidate, context.tables)
        elif candidate.source_type == SourceType.TEXT:
            return self._bind_text_candidate(candidate, context.segments)
        elif candidate.source_type == SourceType.CHART:
            return self._bind_chart_candidate(candidate, context.images)
        # All SourceType values handled above
        return []

    def _bind_table_candidate(
        self,
        candidate: MetricCandidate,
        tables: list[Table],
    ) -> list[BoundValue]:
        """
        Bind a table-sourced candidate to values using header_path/stub_path.

        Strategy:
        1. Find the table containing the candidate
        2. If candidate is in header row → bind data cells in that column
        3. If candidate is in stub column → bind data cells in that row
        4. Otherwise, check if metric in header_path/stub_path

        Args:
            candidate: Table-sourced metric candidate
            tables: List of reconstructed tables

        Returns:
            List of BoundValue objects
        """
        bound_values: list[BoundValue] = []
        loc = candidate.source_locator

        # Find the table
        table = self._find_table(loc.table_id, tables)
        if not table:
            logger.warning(f"Table {loc.table_id} not found for candidate {candidate.candidate_id}")
            return bound_values

        # Find the cell where the candidate was found
        candidate_cell = self._find_cell(table, loc.cell_row, loc.cell_col)
        if not candidate_cell:
            logger.warning(
                f"Cell ({loc.cell_row}, {loc.cell_col}) not found in table {loc.table_id}"
            )
            return bound_values

        match_text_lower = candidate.match_text.lower()
        row = loc.cell_row if loc.cell_row is not None else 0
        col = loc.cell_col if loc.cell_col is not None else 0

        # Detect table-level scale factor
        table_scale, table_scale_has_exceptions = self._detect_table_scale(table)

        # Strategy 1: Candidate is in a header cell → bind data cells in that column
        if candidate_cell.is_header or row < table.header_rows:
            header_path = table.get_header_path(col)
            bound_values.extend(self._bind_column_values(candidate, table, col, header_path))

        # Strategy 2: Candidate is in a stub cell → bind data cells in that row
        if candidate_cell.is_stub or col < table.stub_cols:
            stub_path = table.get_stub_path(row)
            bound_values.extend(self._bind_row_values(candidate, table, row, stub_path))

        # Strategy 3: Metric mentioned in header_path → bind column values
        if not bound_values and self._is_in_path(match_text_lower, candidate_cell.header_path):
            bound_values.extend(
                self._bind_column_values(candidate, table, col, candidate_cell.header_path)
            )

        # Strategy 4: Metric mentioned in stub_path → bind row values
        if not bound_values and self._is_in_path(match_text_lower, candidate_cell.stub_path):
            bound_values.extend(
                self._bind_row_values(candidate, table, row, candidate_cell.stub_path)
            )

        # Strategy 5: Candidate cell itself contains a value (data cell with both keyword and value)
        if not bound_values and candidate_cell.text:
            parsed = self._parse_number(candidate_cell.text)
            if parsed:
                value, unit, raw = parsed
                # Check percentage context from table headers/stubs
                context_text = " ".join(candidate_cell.header_path + candidate_cell.stub_path)
                unit = self._check_percentage_context(candidate.metric_id, unit, raw, context_text)
                if not self._should_filter_unit(candidate.metric_id, unit):
                    confidence = self._compute_table_confidence(
                        match_text_lower,
                        candidate_cell.header_path,
                        candidate_cell.stub_path,
                        unit,
                    )
                    bound_values.append(
                        BoundValue(
                            candidate_id=candidate.candidate_id,
                            value=value,
                            value_raw=raw,
                            unit=unit,
                            binding_type="table_cell",
                            binding_confidence=confidence,
                            source_locator=SourceLocator(
                                table_id=table.table_id,
                                cell_row=candidate_cell.row,
                                cell_col=candidate_cell.col,
                                dom_locator=candidate_cell.dom_locator,
                            ),
                        )
                    )

        # Apply table-level scale factor
        # Currency values always get scaled. Count metrics get scaled only when
        # the raw cell contains a decimal point (e.g. "796.3" in a "(in thousands)"
        # table means 796,300). Integer counts (e.g. "948") are left as-is because
        # financial tables often mix dollar and count columns under a single header.
        #
        # When the table has "except as otherwise noted", skip scaling for values
        # with explicit currency symbols (already actual $) or stubs marked "(actual)".
        if table_scale != 1.0:
            for bv in bound_values:
                if bv.value is None:
                    continue
                # Check if this value is an exception to the table scale.
                # "(actual)" stub-path markers exempt unconditionally; currency-symbol
                # exemption only applies when the table has "except as otherwise noted".
                if self._is_scale_exception(bv, candidate, table, table_scale_has_exceptions):
                    logger.debug(
                        "Skipping table scale for exception value %s (%s)",
                        bv.value_raw,
                        candidate.metric_id,
                    )
                    continue
                if bv.unit == Unit.CURRENCY:
                    bv.value *= table_scale
                elif (
                    bv.unit in (Unit.COUNT, Unit.OTHER)
                    and candidate.metric_id in _COUNT_ONLY_METRICS
                    and self._has_fractional_value(bv.value_raw)
                ):
                    bv.value *= table_scale

        return bound_values

    def _bind_cells(
        self,
        candidate: MetricCandidate,
        table: Table,
        fixed_idx: int | None,
        fixed_path: list[str],
        binding_type: str,
        iterate_rows: bool,
    ) -> list[BoundValue]:
        """
        Unified cell binding for both column-scan and row-scan patterns.

        When iterate_rows=True (column binding):
          - Iterates data rows, fixed column index
          - fixed_path is the header_path; cell.stub_path is the dynamic path

        When iterate_rows=False (row binding):
          - Iterates data columns, fixed row index
          - fixed_path is the stub_path; cell.header_path is the dynamic path
          - Also applies count/currency column-type filters

        Args:
            candidate: The metric candidate.
            table: The table to search.
            fixed_idx: The fixed column (iterate_rows=True) or row (iterate_rows=False) index.
            fixed_path: The header_path or stub_path that is fixed for all cells in this scan.
            binding_type: "table_header" or "table_stub".
            iterate_rows: True to scan rows (column binding), False to scan columns (row binding).

        Returns:
            List of BoundValue objects.
        """
        bound_values: list[BoundValue] = []
        if fixed_idx is None:
            return bound_values

        match_text_lower = candidate.match_text.lower()
        indices = (
            range(table.header_rows, table.row_count)
            if iterate_rows
            else range(table.stub_cols, table.col_count)
        )

        for idx in indices:
            if iterate_rows:
                cell = table.get_cell(idx, fixed_idx)
                cell_row, cell_col = idx, fixed_idx
            else:
                cell = table.get_cell(fixed_idx, idx)
                cell_row, cell_col = fixed_idx, idx

            if not cell or not cell.text.strip():
                continue
            if cell.is_header or cell.is_stub:
                continue

            parsed = self._parse_number(cell.text)
            if not parsed:
                continue

            value, unit, raw = parsed

            if iterate_rows:
                header_path_eff = fixed_path
                stub_path_eff = cell.stub_path
            else:
                header_path_eff = cell.header_path
                stub_path_eff = fixed_path

            context_text = " ".join(header_path_eff + stub_path_eff)
            unit = self._check_percentage_context(candidate.metric_id, unit, raw, context_text)
            if self._should_filter_unit(candidate.metric_id, unit):
                continue

            # Column-type filter (row binding only): prevent count metrics from
            # binding to dollar columns (and vice versa) in mixed financial tables.
            if not iterate_rows:
                if candidate.metric_id in _COUNT_ONLY_METRICS and self._header_indicates_currency(
                    cell.header_path
                ):
                    logger.debug(
                        "Skipping currency-column cell (%d,%d) for count metric %s",
                        fixed_idx,
                        idx,
                        candidate.metric_id,
                    )
                    continue
                if candidate.metric_id in _CURRENCY_ONLY_METRICS and self._header_indicates_count(
                    cell.header_path
                ):
                    logger.debug(
                        "Skipping count-column cell (%d,%d) for currency metric %s",
                        fixed_idx,
                        idx,
                        candidate.metric_id,
                    )
                    continue

            confidence = self._compute_table_confidence(
                match_text_lower, header_path_eff, stub_path_eff, unit
            )

            bound_values.append(
                BoundValue(
                    candidate_id=candidate.candidate_id,
                    value=value,
                    value_raw=raw,
                    unit=unit,
                    binding_type=binding_type,
                    binding_confidence=confidence,
                    source_locator=SourceLocator(
                        table_id=table.table_id,
                        cell_row=cell_row,
                        cell_col=cell_col,
                        dom_locator=cell.dom_locator,
                    ),
                )
            )

        return bound_values

    def _bind_column_values(
        self,
        candidate: MetricCandidate,
        table: Table,
        col: int | None,
        header_path: list[str],
    ) -> list[BoundValue]:
        """Bind values from data cells in the same column (delegates to _bind_cells)."""
        return self._bind_cells(candidate, table, col, header_path, "table_header", iterate_rows=True)

    def _bind_row_values(
        self,
        candidate: MetricCandidate,
        table: Table,
        row: int | None,
        stub_path: list[str],
    ) -> list[BoundValue]:
        """Bind values from data cells in the same row (delegates to _bind_cells)."""
        return self._bind_cells(candidate, table, row, stub_path, "table_stub", iterate_rows=False)

    def _locate_text_window(
        self,
        candidate: MetricCandidate,
        segments: list[Segment],
    ) -> tuple[Segment, str, int, list[tuple[re.Match[str], float, Unit, str]], int, int, float] | None:
        """
        Locate the candidate's segment and extract the proximity search window.

        Finds the segment by ID, resolves the keyword span, runs number discovery
        within the proximity window, and computes sentence bounds and keyword center
        for use by downstream scoring.

        Args:
            candidate: Text-sourced metric candidate.
            segments: All document segments.

        Returns:
            Tuple of (segment, text, window_start, numbers, sentence_start,
            sentence_end, keyword_center), or None if the segment is missing or
            the text is empty / contains no numbers in proximity.
        """
        loc = candidate.source_locator

        segment = self._find_segment(loc.segment_id, segments)
        if not segment:
            logger.warning(
                f"Segment {loc.segment_id} not found for candidate {candidate.candidate_id}"
            )
            return None

        text = segment.text
        if not text:
            return None

        if loc.text_span:
            match_start, match_end = loc.text_span
        else:
            match_start = 0
            match_end = len(text)

        window_start = max(0, match_start - self.proximity_window)
        numbers = self._find_numbers_in_proximity(
            text, match_start, match_end, self.proximity_window
        )

        if not numbers:
            return None

        sentence_start, sentence_end = find_sentence_bounds(text, match_start)
        keyword_center = (match_start + match_end) / 2.0

        return segment, text, window_start, numbers, sentence_start, sentence_end, keyword_center

    def _score_text_numbers(
        self,
        candidate: MetricCandidate,
        segment: Segment,
        text: str,
        window_start: int,
        numbers: list[tuple[re.Match[str], float, Unit, str]],
        sentence_start: int,
        sentence_end: int,
        keyword_center: float,
    ) -> tuple[
        list[tuple[re.Match[str], float, Unit, str, float]],
        tuple[BoundValue, float] | None,
    ]:
        """
        Classify and score number matches from a proximity window.

        Applies unit compatibility filters and text-proximity-specific rules,
        then separates matches into same-sentence candidates (all kept) and
        the single best out-of-sentence candidate.

        Args:
            candidate: Text-sourced metric candidate.
            segment: The segment containing the candidate.
            text: Full segment text.
            window_start: Char offset where the proximity window begins.
            numbers: Output of _find_numbers_in_proximity.
            sentence_start: Start of the sentence containing the keyword.
            sentence_end: End of the sentence containing the keyword.
            keyword_center: Fractional char offset of keyword midpoint.

        Returns:
            Tuple of (same_sentence_candidates, out_of_sentence_best) where
            same_sentence_candidates is a list of
            (num_match, value, unit, raw, distance_penalty) and
            out_of_sentence_best is a (BoundValue, confidence) pair or None.
        """
        same_sentence_candidates: list[tuple[re.Match[str], float, Unit, str, float]] = []
        out_of_sentence_best: tuple[BoundValue, float] | None = None

        for num_match, value, unit, raw in numbers:
            unit = self._check_percentage_context(candidate.metric_id, unit, raw, text)

            if self._should_filter_unit(candidate.metric_id, unit):
                continue

            if candidate.metric_id in _CURRENCY_ONLY_METRICS and unit == Unit.OTHER:
                logger.debug(
                    "Skipping bare number for currency metric %s in text_proximity",
                    candidate.metric_id,
                )
                continue

            num_start_in_text = window_start + num_match.start()
            same_sentence = sentence_start <= num_start_in_text < sentence_end

            num_center = num_start_in_text + (num_match.end() - num_match.start()) / 2.0
            char_distance = abs(num_center - keyword_center)
            if char_distance > self.DISTANCE_DECAY_THRESHOLD:
                decay_range = self.proximity_window - self.DISTANCE_DECAY_THRESHOLD
                if decay_range > 0:
                    fraction = min(
                        (char_distance - self.DISTANCE_DECAY_THRESHOLD) / decay_range,
                        1.0,
                    )
                    distance_penalty = fraction * self.MAX_DISTANCE_PENALTY
                else:
                    distance_penalty = 0.0
            else:
                distance_penalty = 0.0

            if same_sentence:
                same_sentence_candidates.append((num_match, value, unit, raw, distance_penalty))
            else:
                ambiguity_penalty = self.AMBIGUITY_PENALTY if len(numbers) > 1 else 0.0
                confidence = self._compute_text_confidence(
                    unit, ambiguity_penalty, False, distance_penalty
                )
                bv = BoundValue(
                    candidate_id=candidate.candidate_id,
                    value=value,
                    value_raw=raw,
                    unit=unit,
                    binding_type="text_proximity",
                    binding_confidence=confidence,
                    source_locator=SourceLocator(
                        segment_id=segment.segment_id,
                        text_span=(
                            window_start + num_match.start(),
                            window_start + num_match.end(),
                        ),
                        dom_locator=segment.dom_locator,
                    ),
                )
                if out_of_sentence_best is None or confidence > out_of_sentence_best[1]:
                    out_of_sentence_best = (bv, confidence)

        return same_sentence_candidates, out_of_sentence_best

    def _bind_text_candidate(
        self,
        candidate: MetricCandidate,
        segments: list[Segment],
    ) -> list[BoundValue]:
        """
        Bind a text-sourced candidate to values using proximity.

        Strategy:
        1. Locate the segment and extract the proximity search window
        2. Score and classify number matches (same-sentence vs out-of-sentence)
        3. Prefer same-sentence matches; fall back to single best out-of-sentence

        Args:
            candidate: Text-sourced metric candidate
            segments: List of document segments

        Returns:
            List of BoundValue objects
        """
        located = self._locate_text_window(candidate, segments)
        if located is None:
            return []

        segment, text, window_start, numbers, sentence_start, sentence_end, keyword_center = located

        same_sentence_candidates, out_of_sentence_best = self._score_text_numbers(
            candidate, segment, text, window_start, numbers,
            sentence_start, sentence_end, keyword_center,
        )

        bound_values: list[BoundValue] = []

        if same_sentence_candidates:
            ambiguity_penalty = self.AMBIGUITY_PENALTY if len(same_sentence_candidates) > 1 else 0.0
            for num_match, value, unit, raw, distance_penalty in same_sentence_candidates:
                confidence = self._compute_text_confidence(
                    unit, ambiguity_penalty, True, distance_penalty
                )
                bound_values.append(
                    BoundValue(
                        candidate_id=candidate.candidate_id,
                        value=value,
                        value_raw=raw,
                        unit=unit,
                        binding_type="text_proximity",
                        binding_confidence=confidence,
                        source_locator=SourceLocator(
                            segment_id=segment.segment_id,
                            text_span=(
                                window_start + num_match.start(),
                                window_start + num_match.end(),
                            ),
                            dom_locator=segment.dom_locator,
                        ),
                    )
                )
        elif out_of_sentence_best is not None:
            bound_values.append(out_of_sentence_best[0])

        return bound_values

    def _bind_chart_candidate(
        self,
        candidate: MetricCandidate,
        images: list[ImageAsset],
    ) -> list[BoundValue]:
        """
        Bind chart candidate to data points from the chart.

        Each DataPoint in each series produces a BoundValue. The unit is
        inferred from the chart's y-axis label.

        Args:
            candidate: Chart-sourced metric candidate
            images: List of image assets

        Returns:
            List of BoundValue objects
        """
        bound_values: list[BoundValue] = []
        loc = candidate.source_locator

        # Find the image asset
        asset = next((img for img in images if img.img_id == loc.img_id), None)
        if not asset or not asset.chart_data:
            return bound_values

        chart = asset.chart_data
        unit = self._infer_unit_from_axis(chart.y_axis_label)

        # Check unit compatibility
        if self._should_filter_unit(candidate.metric_id, unit):
            return bound_values

        for series in chart.series:
            for point in series.points:
                if point.y is None:
                    continue

                # Slight discount on confidence for chart extraction
                binding_confidence = asset.confidence * 0.9

                bound_value = BoundValue(
                    candidate_id=candidate.candidate_id,
                    value=point.y,
                    value_raw=point.label or str(point.y),
                    unit=unit,
                    binding_type="chart_label",
                    binding_confidence=binding_confidence,
                    source_locator=SourceLocator(
                        img_id=asset.img_id,
                        dom_locator=asset.dom_locator,
                    ),
                )
                bound_values.append(bound_value)

        # Bind annotation values (less structured than data labels)
        for annotation in chart.annotations:
            if annotation.value is None:
                continue

            # Infer unit from annotation's unit string, fall back to axis-inferred unit
            ann_unit = self._annotation_unit_to_enum(annotation.unit) or unit

            # Check unit compatibility
            if self._should_filter_unit(candidate.metric_id, ann_unit):
                continue

            # Lower confidence multiplier for annotations (0.85x vs 0.9x for labels)
            binding_confidence = asset.confidence * 0.85

            bound_value = BoundValue(
                candidate_id=candidate.candidate_id,
                value=annotation.value,
                value_raw=annotation.text,
                unit=ann_unit,
                binding_type="chart_annotation",
                binding_confidence=binding_confidence,
                source_locator=SourceLocator(
                    img_id=asset.img_id,
                    dom_locator=asset.dom_locator,
                ),
            )
            bound_values.append(bound_value)

        return bound_values

    def _infer_unit_from_axis(self, axis_label: str) -> Unit:
        """
        Infer unit type from chart axis label.

        Args:
            axis_label: Y-axis label text (e.g., "Revenue ($M)", "Users")

        Returns:
            Inferred Unit enum value
        """
        label_lower = (axis_label or "").lower()
        if any(s in label_lower for s in ("$", "usd", "revenue", "gmv")):
            return Unit.CURRENCY
        if "%" in label_lower or "percent" in label_lower or "rate" in label_lower:
            return Unit.PERCENT
        if any(s in label_lower for s in ("count", "number", "users", "customers", "subscribers")):
            return Unit.COUNT
        return Unit.OTHER

    @staticmethod
    def _annotation_unit_to_enum(unit_str: str) -> Unit | None:
        """
        Map annotation unit string to Unit enum.

        Args:
            unit_str: Unit string from ChartAnnotation (e.g., "percent", "currency")

        Returns:
            Unit enum value, or None if unknown/empty (caller should use fallback)
        """
        mapping = {
            "percent": Unit.PERCENT,
            "currency": Unit.CURRENCY,
            "count": Unit.COUNT,
        }
        return mapping.get(unit_str.lower().strip()) if unit_str else None

    def _find_numbers_in_proximity(
        self,
        text: str,
        match_start: int,
        match_end: int,
        proximity_chars: int,
    ) -> list[tuple[re.Match[str], float, Unit, str]]:
        """
        Find numbers within proximity of a match.

        Args:
            text: Full text to search
            match_start: Start of keyword match
            match_end: End of keyword match
            proximity_chars: Max characters to search

        Returns:
            List of (match, value, unit, raw_text) tuples
        """
        results: list[tuple[re.Match[str], float, Unit, str]] = []

        # Define search window
        window_start = max(0, match_start - proximity_chars)
        window_end = min(len(text), match_end + proximity_chars)
        window_text = text[window_start:window_end]

        # Find all numbers in window
        for match in _np.NUMBER_PATTERN.finditer(window_text):
            parsed = self._parse_number(match.group())
            if parsed:
                value, unit, raw = parsed
                results.append((match, value, unit, raw))

        return results

    def _parse_number(self, text: str) -> tuple[float, Unit, str] | None:
        """Parse a number from text. Delegates to stages.number_parsing.parse_number."""
        return _np.parse_number(text)

    def _compute_table_confidence(
        self,
        match_text: str,
        header_path: list[str],
        stub_path: list[str],
        unit: Unit,
    ) -> float:
        """
        Compute confidence for a table binding.

        Args:
            match_text: Lowercase match text
            header_path: Column headers
            stub_path: Row stubs
            unit: Detected unit

        Returns:
            Confidence score 0.0-1.0
        """
        confidence = self.TABLE_BINDING_BASE

        # Exact match bonus
        all_paths = [h.lower() for h in header_path] + [s.lower() for s in stub_path]
        if any(match_text == path for path in all_paths):
            confidence += self.EXACT_MATCH_BONUS

        # Unit presence bonus
        if unit in (Unit.CURRENCY, Unit.PERCENT):
            confidence += self.UNIT_PRESENCE_BONUS

        return max(0.0, min(1.0, confidence))

    def _compute_text_confidence(
        self,
        unit: Unit,
        ambiguity_penalty: float = 0.0,
        same_sentence: bool = False,
        distance_penalty: float = 0.0,
    ) -> float:
        """
        Compute confidence for a text binding.

        Args:
            unit: Detected unit
            ambiguity_penalty: Penalty for multiple values
            same_sentence: Whether value is in same sentence as keyword
            distance_penalty: Penalty for distance from keyword (0.0-0.1)

        Returns:
            Confidence score 0.0-1.0
        """
        confidence = self.TEXT_BINDING_BASE

        # Unit presence bonus
        if unit in (Unit.CURRENCY, Unit.PERCENT):
            confidence += self.UNIT_PRESENCE_BONUS

        # Same sentence bonus
        if same_sentence:
            confidence += self.SAME_SENTENCE_BONUS

        # Apply ambiguity penalty
        confidence -= ambiguity_penalty

        # Apply distance decay penalty
        confidence -= distance_penalty

        return max(min(confidence, 1.0), 0.0)

    def _detect_table_scale(self, table: Table) -> tuple[float, bool]:
        """
        Detect table-level scale factor from header/early rows or caption text.

        Searches header cells, early stub cells, and section_path for patterns
        like "(In thousands)".

        Returns:
            Tuple of (scale_multiplier, has_exceptions) where has_exceptions
            is True when the annotation contains "except as otherwise noted".
        """
        scan_rows = min(table.header_rows + 3, table.row_count)
        for row_idx in range(scan_rows):
            for col_idx in range(table.col_count):
                cell = table.get_cell(row_idx, col_idx)
                if cell and cell.text:
                    match = _np.TABLE_SCALE_PATTERN.search(cell.text)
                    if match:
                        scale_word = match.group(1).lower()
                        scale = _np.TABLE_SCALE_MAP.get(scale_word, 1.0)
                        has_except = bool(_np.TABLE_SCALE_EXCEPT_PATTERN.search(cell.text))
                        return (scale, has_except)

        for path_item in table.section_path:
            match = _np.TABLE_SCALE_PATTERN.search(path_item)
            if match:
                scale_word = match.group(1).lower()
                scale = _np.TABLE_SCALE_MAP.get(scale_word, 1.0)
                has_except = bool(_np.TABLE_SCALE_EXCEPT_PATTERN.search(path_item))
                return (scale, has_except)

        return (1.0, False)

    @staticmethod
    def _has_fractional_value(value_raw: str) -> bool:
        """Check if raw value string contains a decimal point. Delegates to number_parsing."""
        return _np.has_fractional_value(value_raw)

    # Pattern matching explicit currency symbols in raw cell text
    _CURRENCY_SYMBOL_PATTERN = re.compile(r"[\$\€\£]")

    def _is_scale_exception(
        self,
        bv: BoundValue,
        candidate: MetricCandidate,
        table: Table,
        table_has_exceptions: bool = False,
    ) -> bool:
        """Check if a bound value is an exception to table-level scaling.

        Two independent signals exempt a value from scaling:
        1. Stub row is labelled "(actual)" — the row is already at true scale
           regardless of whether the table header says "except as noted".
        2. Raw value has an explicit currency symbol (e.g. "$591.7") — only
           honoured when the table itself declares "except as otherwise noted",
           because bare currency symbols can appear in scale-qualified tables.

        Args:
            bv: The bound value to check
            candidate: The metric candidate
            table: The table containing the value
            table_has_exceptions: True when the table header contains
                "except as otherwise noted" (enables currency-symbol exemption).

        Returns:
            True if this value should skip table-level scaling.
        """
        # Check if the stub path contains "(actual)" — unconditional exemption
        loc = bv.source_locator
        if loc.cell_row is not None:
            stub_path = table.get_stub_path(loc.cell_row)
            stub_text = " ".join(stub_path).lower()
            if "(actual)" in stub_text:
                return True

        # Currency-symbol exemption only when table explicitly says "except as noted"
        if table_has_exceptions and self._CURRENCY_SYMBOL_PATTERN.search(bv.value_raw):
            return True

        return False

    # Currency indicators in column headers (case-insensitive matching)
    _CURRENCY_HEADER_INDICATORS = re.compile(
        r"[\$\€\£]|(?:revenue|gmv|amount|dollars|spend|cost|earnings|income|"
        r"expense|proceeds|sales|margin|ebitda|profit|loss)",
        re.IGNORECASE,
    )

    # Count indicators in column headers (case-insensitive matching)
    _COUNT_HEADER_INDICATORS = re.compile(
        r"\b(?:count|number|users|customers|subscribers|members|accounts|"
        r"merchants|consumers|buyers|sellers|drivers|riders|hosts|guests)\b",
        re.IGNORECASE,
    )

    @staticmethod
    def _header_indicates_currency(header_path: list[str]) -> bool:
        """Check if a column's header path indicates currency values.

        Used to prevent count metrics from binding to dollar columns in
        mixed financial tables (e.g. Farfetch's '(In thousands)' tables
        that have both dollar and count columns).

        Args:
            header_path: Column header hierarchy (e.g. ["Revenue", "2023"])

        Returns:
            True if any header element contains a currency indicator.
        """
        combined = " ".join(header_path)
        return bool(ValueBindingStage._CURRENCY_HEADER_INDICATORS.search(combined))

    @staticmethod
    def _header_indicates_count(header_path: list[str]) -> bool:
        """Check if a column's header path indicates count values.

        Used to prevent currency metrics from binding to count columns.

        Args:
            header_path: Column header hierarchy

        Returns:
            True if any header element contains a count indicator.
        """
        combined = " ".join(header_path)
        return bool(ValueBindingStage._COUNT_HEADER_INDICATORS.search(combined))

    def _is_in_path(self, text: str, path: list[str]) -> bool:
        """Check if text appears in any path element."""
        text_lower = text.lower()
        return any(text_lower in p.lower() for p in path)

    def _find_table(self, table_id: str | None, tables: list[Table]) -> Table | None:
        """Find a table by ID."""
        if not table_id:
            return None
        for table in tables:
            if table.table_id == table_id:
                return table
        return None

    def _find_cell(self, table: Table, row: int | None, col: int | None) -> Cell | None:
        """Find a cell in a table."""
        if row is None or col is None:
            return None
        return table.get_cell(row, col)

    def _find_segment(self, segment_id: str | None, segments: list[Segment]) -> Segment | None:
        """Find a segment by ID."""
        if not segment_id:
            return None
        for segment in segments:
            if segment.segment_id == segment_id:
                return segment
        return None

    def _make_result(
        self,
        start_time: datetime,
        items_processed: int,
        items_output: int,
        errors: list[str],
        warnings: list[str],
    ) -> StageResult:
        """Create a StageResult with timing info."""
        end_time = datetime.utcnow()
        duration_ms = int((end_time - start_time).total_seconds() * 1000)

        # Import at runtime to avoid circular import
        from src.extraction_v2.pipeline import PipelineStage, StageResult

        return StageResult(
            stage=PipelineStage.VALUE_BINDING,
            success=len(errors) == 0,
            duration_ms=duration_ms,
            items_processed=items_processed,
            items_output=items_output,
            errors=errors,
            warnings=warnings,
            metadata={
                "binding_types": {},  # Could track counts per binding type
                "unit_filtered_count": self._unit_filtered_count,
            },
        )
