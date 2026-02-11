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
from decimal import InvalidOperation
from typing import TYPE_CHECKING

from src.extraction_v2.models import (
    BoundValue,
    ImageAsset,
    MetricCandidate,
    SourceLocator,
    SourceType,
    Unit,
)
from src.extraction_v2.unit_compatibility import is_unit_compatible
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

    # Text proximity settings
    DEFAULT_WORD_PROXIMITY: int = 10  # Max words between keyword and value
    DEFAULT_CHAR_PROXIMITY: int = 100  # Max chars for proximity search

    # Number parsing pattern
    # Matches: $1,234.56, 1,234, 45%, 1.5M, -$100, etc.
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

    # Scale multipliers
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
        if unit != Unit.COUNT:
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
            logger.warning(
                f"Table {loc.table_id} not found for candidate {candidate.candidate_id}"
            )
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

        # Strategy 1: Candidate is in a header cell → bind data cells in that column
        if candidate_cell.is_header or row < table.header_rows:
            header_path = table.get_header_path(col)
            bound_values.extend(
                self._bind_column_values(candidate, table, col, header_path)
            )

        # Strategy 2: Candidate is in a stub cell → bind data cells in that row
        if candidate_cell.is_stub or col < table.stub_cols:
            stub_path = table.get_stub_path(row)
            bound_values.extend(
                self._bind_row_values(candidate, table, row, stub_path)
            )

        # Strategy 3: Metric mentioned in header_path → bind column values
        if not bound_values and self._is_in_path(match_text_lower, candidate_cell.header_path):
            bound_values.extend(
                self._bind_column_values(
                    candidate, table, col, candidate_cell.header_path
                )
            )

        # Strategy 4: Metric mentioned in stub_path → bind row values
        if not bound_values and self._is_in_path(match_text_lower, candidate_cell.stub_path):
            bound_values.extend(
                self._bind_row_values(
                    candidate, table, row, candidate_cell.stub_path
                )
            )

        # Strategy 5: Candidate cell itself contains a value (data cell with both keyword and value)
        if not bound_values and candidate_cell.text:
            parsed = self._parse_number(candidate_cell.text)
            if parsed:
                value, unit, raw = parsed
                # Check percentage context from table headers/stubs
                context_text = " ".join(
                    candidate_cell.header_path + candidate_cell.stub_path
                )
                unit = self._check_percentage_context(
                    candidate.metric_id, unit, raw, context_text
                )
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

        return bound_values

    def _bind_column_values(
        self,
        candidate: MetricCandidate,
        table: Table,
        col: int | None,
        header_path: list[str],
    ) -> list[BoundValue]:
        """
        Bind values from data cells in the same column.

        Args:
            candidate: The metric candidate
            table: The table
            col: Column index
            header_path: Header path for confidence scoring

        Returns:
            List of BoundValue objects
        """
        bound_values: list[BoundValue] = []
        if col is None:
            return bound_values

        match_text_lower = candidate.match_text.lower()

        # Iterate through data rows (skip header rows)
        for row_idx in range(table.header_rows, table.row_count):
            cell = table.get_cell(row_idx, col)
            if not cell or not cell.text.strip():
                continue

            # Skip if cell is a header or stub
            if cell.is_header or cell.is_stub:
                continue

            # Try to parse the cell value
            parsed = self._parse_number(cell.text)
            if not parsed:
                continue

            value, unit, raw = parsed
            # Check percentage context from table headers/stubs
            context_text = " ".join(header_path + cell.stub_path)
            unit = self._check_percentage_context(
                candidate.metric_id, unit, raw, context_text
            )
            if self._should_filter_unit(candidate.metric_id, unit):
                continue

            confidence = self._compute_table_confidence(
                match_text_lower, header_path, cell.stub_path, unit
            )

            bound_values.append(
                BoundValue(
                    candidate_id=candidate.candidate_id,
                    value=value,
                    value_raw=raw,
                    unit=unit,
                    binding_type="table_header",
                    binding_confidence=confidence,
                    source_locator=SourceLocator(
                        table_id=table.table_id,
                        cell_row=row_idx,
                        cell_col=col,
                        dom_locator=cell.dom_locator,
                    ),
                )
            )

        return bound_values

    def _bind_row_values(
        self,
        candidate: MetricCandidate,
        table: Table,
        row: int | None,
        stub_path: list[str],
    ) -> list[BoundValue]:
        """
        Bind values from data cells in the same row.

        Args:
            candidate: The metric candidate
            table: The table
            row: Row index
            stub_path: Stub path for confidence scoring

        Returns:
            List of BoundValue objects
        """
        bound_values: list[BoundValue] = []
        if row is None:
            return bound_values

        match_text_lower = candidate.match_text.lower()

        # Iterate through data columns (skip stub columns)
        for col_idx in range(table.stub_cols, table.col_count):
            cell = table.get_cell(row, col_idx)
            if not cell or not cell.text.strip():
                continue

            # Skip if cell is a header or stub
            if cell.is_header or cell.is_stub:
                continue

            # Try to parse the cell value
            parsed = self._parse_number(cell.text)
            if not parsed:
                continue

            value, unit, raw = parsed
            # Check percentage context from table headers/stubs
            context_text = " ".join(cell.header_path + stub_path)
            unit = self._check_percentage_context(
                candidate.metric_id, unit, raw, context_text
            )
            if self._should_filter_unit(candidate.metric_id, unit):
                continue

            confidence = self._compute_table_confidence(
                match_text_lower, cell.header_path, stub_path, unit
            )

            bound_values.append(
                BoundValue(
                    candidate_id=candidate.candidate_id,
                    value=value,
                    value_raw=raw,
                    unit=unit,
                    binding_type="table_stub",
                    binding_confidence=confidence,
                    source_locator=SourceLocator(
                        table_id=table.table_id,
                        cell_row=row,
                        cell_col=col_idx,
                        dom_locator=cell.dom_locator,
                    ),
                )
            )

        return bound_values

    def _bind_text_candidate(
        self,
        candidate: MetricCandidate,
        segments: list[Segment],
    ) -> list[BoundValue]:
        """
        Bind a text-sourced candidate to values using proximity.

        Strategy:
        1. Find the segment containing the candidate
        2. Search for numbers within N words of the match
        3. Prefer values in same sentence

        Args:
            candidate: Text-sourced metric candidate
            segments: List of document segments

        Returns:
            List of BoundValue objects
        """
        bound_values: list[BoundValue] = []
        loc = candidate.source_locator

        # Find the segment
        segment = self._find_segment(loc.segment_id, segments)
        if not segment:
            logger.warning(
                f"Segment {loc.segment_id} not found for candidate {candidate.candidate_id}"
            )
            return bound_values

        # Get text span
        text = segment.text
        if not text:
            return bound_values

        # Determine search window
        if loc.text_span:
            match_start, match_end = loc.text_span
        else:
            # Fallback: search entire text
            match_start = 0
            match_end = len(text)

        # Calculate window bounds
        window_start = max(0, match_start - self.proximity_window)

        # Find numbers in proximity
        numbers = self._find_numbers_in_proximity(
            text, match_start, match_end, self.proximity_window
        )

        if not numbers:
            return bound_values

        # Apply ambiguity penalty if multiple values found
        ambiguity_penalty = self.AMBIGUITY_PENALTY if len(numbers) > 1 else 0.0

        # Get sentence bounds for the keyword match
        sentence_start, sentence_end = self._find_sentence_bounds(text, match_start)

        # Create bound values
        for num_match, value, unit, raw in numbers:
            # Check if count value should be treated as percentage (FIX-A)
            unit = self._check_percentage_context(
                candidate.metric_id, unit, raw, text
            )

            if self._should_filter_unit(candidate.metric_id, unit):
                continue

            # Check if value is in the same sentence as the keyword
            # num_match positions are relative to window_text, need to adjust to full text
            num_start_in_text = window_start + num_match.start()

            same_sentence = sentence_start <= num_start_in_text < sentence_end

            confidence = self._compute_text_confidence(unit, ambiguity_penalty, same_sentence)

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
                        text_span=(num_match.start(), num_match.end()),
                        dom_locator=segment.dom_locator,
                    ),
                )
            )

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
        asset = next(
            (img for img in images if img.img_id == loc.img_id), None
        )
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
        if any(
            s in label_lower
            for s in ("count", "number", "users", "customers", "subscribers")
        ):
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
        for match in self.NUMBER_PATTERN.finditer(window_text):
            parsed = self._parse_number(match.group())
            if parsed:
                value, unit, raw = parsed
                results.append((match, value, unit, raw))

        return results

    def _find_sentence_bounds(self, text: str, position: int) -> tuple[int, int]:
        """
        Find sentence boundaries around a given position.

        Uses regex to detect sentence endings: [.!?] followed by whitespace and capital letter,
        or start/end of text.

        Args:
            text: Full text to search
            position: Character position to find sentence bounds around

        Returns:
            Tuple of (sentence_start, sentence_end) positions
        """
        # Find sentence start (look backwards for sentence boundary)
        sentence_start = 0
        # Pattern for sentence boundary: period/exclamation/question followed by space and capital
        boundary_pattern = re.compile(r'[.!?]\s+[A-Z]')

        # Search backwards from position
        text_before = text[:position]
        boundaries_before = list(boundary_pattern.finditer(text_before))
        if boundaries_before:
            # Start after the last sentence boundary found
            last_boundary = boundaries_before[-1]
            # Start position is after the punctuation and whitespace
            sentence_start = last_boundary.end() - 1  # -1 to include the capital letter

        # Find sentence end (look forwards for sentence boundary)
        sentence_end = len(text)
        text_after = text[position:]
        boundary_match = boundary_pattern.search(text_after)
        if boundary_match:
            # End at the punctuation mark
            sentence_end = position + boundary_match.start() + 1  # +1 to include punctuation

        return (sentence_start, sentence_end)

    def _parse_number(self, text: str) -> tuple[float, Unit, str] | None:
        """
        Parse a number from text.

        Args:
            text: Text containing a number

        Returns:
            Tuple of (value, unit, raw_text) or None if not parseable
        """
        match = self.NUMBER_PATTERN.search(text)
        if not match:
            return None

        try:
            # Extract components
            number_str = match.group("number")
            currency = match.group("currency")
            suffix = match.group("suffix")
            percent = match.group("percent")
            negative = match.group("negative")

            # Clean number string
            clean_number = number_str.replace(",", "")
            value = float(clean_number)

            # Apply scale multiplier
            if suffix:
                suffix_lower = suffix.lower()
                if suffix_lower in self.SCALE_MULTIPLIERS:
                    value *= self.SCALE_MULTIPLIERS[suffix_lower]

            # Apply negative
            if negative:
                value = -value

            # Determine unit
            if percent:
                unit = Unit.PERCENT
                # Keep percentage as-is (don't convert to decimal)
            elif currency:
                unit = Unit.CURRENCY
            else:
                unit = Unit.COUNT

            # Raw text
            raw = match.group().strip()

            return (value, unit, raw)

        except (ValueError, InvalidOperation) as e:
            logger.debug(f"Could not parse number from '{text}': {e}")
            return None

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
    ) -> float:
        """
        Compute confidence for a text binding.

        Args:
            unit: Detected unit
            ambiguity_penalty: Penalty for multiple values
            same_sentence: Whether value is in same sentence as keyword

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

        return max(min(confidence, 1.0), 0.0)

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

    def _find_segment(
        self, segment_id: str | None, segments: list[Segment]
    ) -> Segment | None:
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
