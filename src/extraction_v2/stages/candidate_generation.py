"""
V2 Candidate Generation Stage

Stage 6 of the V2 extraction pipeline. Scans segments and table cells for metric
keyword matches using the YAML taxonomy, applying exclusion patterns and false
positive filtering to produce MetricCandidate objects.

Design principles:
- Rule-based first (no LLM calls)
- Reuse V1 keyword_config and false_positive_filter modules
- Conservative matching (filter false positives aggressively)
"""

from __future__ import annotations

import logging
import re
from datetime import datetime
from typing import TYPE_CHECKING, Any

from src.extraction.keyword_config import (
    KeywordConfigError,
    get_exclusion_patterns,
    get_metric_keywords,
    get_required_context,
    get_specific_patterns,
    is_metric_deprecated,
)
from src.extraction_v2.models import (
    ImageAsset,
    MetricCandidate,
    SectionType,
    SegmentType,
    SourceLocator,
    SourceType,
)

if TYPE_CHECKING:
    from src.extraction_v2.models import Segment, Table
    from src.extraction_v2.pipeline import PipelineContext, StageResult

logger = logging.getLogger(__name__)


class CandidateGenerationStage:
    """
    Stage 6: Metric Candidate Generation.

    Scans all content for metric keyword matches:
    - Segment text (paragraphs, lists, etc.)
    - Table cells (text + header_path + stub_path)

    Applies filtering:
    - Exclusion patterns per metric
    - Required context patterns (e.g., revenue synonyms need cohort context)

    Computes confidence scores:
    - Base: 0.5
    - +0.1 for specific (multi-word) pattern match
    - +0.1 for table source
    - +0.1 for MD&A or Business section
    """

    # Context extraction window (chars on each side of match)
    CONTEXT_WINDOW: int = 100

    # Confidence modifiers
    BASE_CONFIDENCE: float = 0.5
    SPECIFIC_PATTERN_BONUS: float = 0.1
    TABLE_SOURCE_BONUS: float = 0.1
    SECTION_BONUS: float = 0.1
    HIGH_VALUE_SECTIONS: set[SectionType] = {SectionType.MDA, SectionType.BUSINESS}

    def __init__(self) -> None:
        """Initialize stage with compiled regex patterns from V1 config."""
        self._keywords: dict[str, list[str]] = {}
        self._exclusions: dict[str, list[str]] = {}
        self._required_context: dict[str, dict[str, Any]] = {}
        self._specific_patterns: list[str] = []

        # Compiled patterns for performance
        self._compiled_patterns: dict[str, list[re.Pattern[str]]] = {}
        self._compiled_exclusions: dict[str, list[re.Pattern[str]]] = {}
        # Tuple of (compiled_patterns, proximity_chars)
        self._compiled_context: dict[str, tuple[list[re.Pattern[str]], int]] = {}
        self._compiled_specific: list[re.Pattern[str]] = []

        # Default proximity for required context (chars)
        self._default_proximity_chars: int = 1500

        self._initialized = False

    def _ensure_initialized(self) -> bool:
        """
        Load and compile patterns on first use.

        Returns:
            True if initialization succeeded, False otherwise.
        """
        if self._initialized:
            return True

        try:
            all_keywords = get_metric_keywords()
            self._keywords = {
                mid: p for mid, p in all_keywords.items() if not is_metric_deprecated(mid)
            }
            all_exclusions = get_exclusion_patterns()
            self._exclusions = {
                mid: p for mid, p in all_exclusions.items() if not is_metric_deprecated(mid)
            }
            all_context = get_required_context()
            self._required_context = {
                mid: c for mid, c in all_context.items() if not is_metric_deprecated(mid)
            }
            self._specific_patterns = get_specific_patterns()
            self._compile_patterns()
            self._initialized = True
            deprecated_count = len(all_keywords) - len(self._keywords)
            logger.info(
                f"Candidate generation initialized: {len(self._keywords)} metrics "
                f"({deprecated_count} deprecated excluded)"
            )
            return True
        except KeywordConfigError as e:
            logger.error(f"Failed to load keyword config: {e}")
            return False

    def _compile_patterns(self) -> None:
        """Compile all regex patterns for performance."""
        # Compile keyword patterns
        for metric_id, patterns in self._keywords.items():
            compiled: list[re.Pattern[str]] = []
            for pattern in patterns:
                try:
                    compiled.append(re.compile(pattern, re.IGNORECASE))
                except re.error as e:
                    logger.warning(f"Invalid regex pattern for {metric_id}: {pattern!r} - {e}")
            self._compiled_patterns[metric_id] = compiled

        # Compile exclusion patterns
        for metric_id, patterns in self._exclusions.items():
            compiled = []
            for pattern in patterns:
                try:
                    compiled.append(re.compile(pattern, re.IGNORECASE))
                except re.error as e:
                    logger.warning(f"Invalid exclusion pattern for {metric_id}: {pattern!r} - {e}")
            self._compiled_exclusions[metric_id] = compiled

        # Compile required context patterns with proximity
        for metric_id, config in self._required_context.items():
            compiled = []
            for pattern in config.get("patterns", []):
                try:
                    compiled.append(re.compile(pattern, re.IGNORECASE))
                except re.error as e:
                    logger.warning(f"Invalid context pattern for {metric_id}: {pattern!r} - {e}")
            proximity = config.get("proximity_chars", self._default_proximity_chars)
            self._compiled_context[metric_id] = (compiled, proximity)

        # Compile specific patterns
        for pattern in self._specific_patterns:
            try:
                self._compiled_specific.append(re.compile(pattern, re.IGNORECASE))
            except re.error as e:
                logger.warning(f"Invalid specific pattern: {pattern!r} - {e}")

    def process(self, context: PipelineContext) -> StageResult:
        """
        Generate metric candidates from segments and tables.

        Args:
            context: Pipeline context with segments and tables

        Returns:
            StageResult with processing metrics
        """
        start_time = datetime.utcnow()
        candidates_found = 0
        errors: list[str] = []
        warnings: list[str] = []

        # Initialize patterns if needed
        if not self._ensure_initialized():
            errors.append("Failed to initialize keyword configuration")
            return self._make_result(start_time, 0, candidates_found, errors, warnings)

        # Scan segments (skip TABLE segments — they are processed via _scan_table)
        for segment in context.segments:
            if segment.segment_type == SegmentType.TABLE:
                continue
            try:
                segment_candidates = self._scan_segment(segment)
                for candidate in segment_candidates:
                    context.candidates.append(candidate)
                    candidates_found += 1
            except Exception as e:
                error_msg = f"Error scanning segment {segment.segment_id}: {e}"
                logger.error(error_msg)
                errors.append(error_msg)

        # Scan table cells
        for table in context.tables:
            try:
                table_candidates = self._scan_table(table)
                for candidate in table_candidates:
                    context.candidates.append(candidate)
                    candidates_found += 1
            except Exception as e:
                error_msg = f"Error scanning table {table.table_id}: {e}"
                logger.error(error_msg)
                errors.append(error_msg)

        # Scan chart data from processed images
        charts_scanned = 0
        for asset in context.images:
            if asset.chart_data is not None:
                try:
                    chart_candidates = self._scan_chart(asset)
                    for candidate in chart_candidates:
                        context.candidates.append(candidate)
                        candidates_found += 1
                    charts_scanned += 1
                except Exception as e:
                    error_msg = f"Error scanning chart {asset.img_id}: {e}"
                    logger.error(error_msg)
                    errors.append(error_msg)

        items_processed = len(context.segments) + len(context.tables) + charts_scanned

        logger.info(
            f"Candidate generation complete: {candidates_found} candidates "
            f"from {len(context.segments)} segments, {len(context.tables)} tables, "
            f"{charts_scanned} charts"
        )

        return self._make_result(start_time, items_processed, candidates_found, errors, warnings)

    def _scan_segment(self, segment: Segment) -> list[MetricCandidate]:
        """
        Scan a segment for metric keyword matches.

        Args:
            segment: The segment to scan

        Returns:
            List of MetricCandidate objects found
        """
        candidates: list[MetricCandidate] = []
        text = segment.text

        if not text or not text.strip():
            return candidates

        for metric_id, patterns in self._compiled_patterns.items():
            for pattern in patterns:
                for match in pattern.finditer(text):
                    # Check exclusions
                    if self._is_excluded(metric_id, text, match):
                        continue

                    # Check required context (proximity-based)
                    if not self._has_required_context(metric_id, text, match.start()):
                        continue

                    # Extract context
                    context_text = self._extract_context(text, match.start(), match.end())

                    # Compute confidence
                    confidence = self._compute_confidence(
                        metric_id=metric_id,
                        match_text=match.group(),
                        source_type=SourceType.TEXT,
                        section_type=segment.section_type,
                    )

                    # Create candidate
                    candidate = MetricCandidate(
                        metric_id=metric_id,
                        match_text=match.group(),
                        source_locator=SourceLocator(
                            segment_id=segment.segment_id,
                            dom_locator=segment.dom_locator,
                            text_span=(match.start(), match.end()),
                        ),
                        source_type=SourceType.TEXT,
                        confidence=confidence,
                        context_text=context_text,
                        section_type=segment.section_type,
                    )
                    candidates.append(candidate)

        candidates = self._deduplicate_candidates(candidates)
        return self._cross_metric_dedup(candidates)

    def _scan_table(self, table: Table) -> list[MetricCandidate]:
        """
        Scan table cells for metric keyword matches.

        Scans both cell text and header_path/stub_path to catch metrics
        mentioned in table headers. When a metric matches only in header/stub
        (not in cell text), emits only one candidate per column to avoid
        broadcasting the same header match to every cell in the column.

        Args:
            table: The table to scan

        Returns:
            List of MetricCandidate objects found
        """
        candidates: list[MetricCandidate] = []
        # Track header-only matches: (metric_id, col) → already emitted
        header_only_emitted: set[tuple[str, int]] = set()

        for cell in table.cells:
            # Build combined text: cell text + headers + stubs
            combined_parts = [cell.text]
            combined_parts.extend(cell.header_path)
            combined_parts.extend(cell.stub_path)
            combined_text = " ".join(combined_parts)

            if not combined_text.strip():
                continue

            cell_text_lower = cell.text.lower().strip()

            for metric_id, patterns in self._compiled_patterns.items():
                for pattern in patterns:
                    for match in pattern.finditer(combined_text):
                        # Check exclusions
                        if self._is_excluded(metric_id, combined_text, match):
                            continue

                        # Check required context (proximity-based)
                        if not self._has_required_context(metric_id, combined_text, match.start()):
                            continue

                        # Determine if match is in cell text or only in header/stub
                        match_in_cell_text = (
                            bool(pattern.search(cell.text)) if cell_text_lower else False
                        )

                        if not match_in_cell_text:
                            # Header/stub-only match: emit only once per (metric, col)
                            dedup_key = (metric_id, cell.col)
                            if dedup_key in header_only_emitted:
                                continue
                            header_only_emitted.add(dedup_key)

                        # Extract context (use combined text)
                        context_text = self._extract_context(
                            combined_text, match.start(), match.end()
                        )

                        # Compute confidence (table source bonus)
                        confidence = self._compute_confidence(
                            metric_id=metric_id,
                            match_text=match.group(),
                            source_type=SourceType.HTML_TABLE,
                            section_type=table.section_type,
                        )

                        # Create candidate
                        candidate = MetricCandidate(
                            metric_id=metric_id,
                            match_text=match.group(),
                            source_locator=SourceLocator(
                                table_id=table.table_id,
                                segment_id=table.segment_id,
                                cell_row=cell.row,
                                cell_col=cell.col,
                                dom_locator=cell.dom_locator,
                            ),
                            source_type=SourceType.HTML_TABLE,
                            confidence=confidence,
                            context_text=context_text,
                            section_type=table.section_type,
                        )
                        candidates.append(candidate)

        candidates = self._deduplicate_candidates(candidates)
        return self._cross_metric_dedup(candidates)

    def _scan_chart(self, asset: ImageAsset) -> list[MetricCandidate]:
        """
        Scan chart metadata for metric keyword matches.

        Searches chart title, axis labels, and series names for metric
        keywords using the same compiled patterns as text/table scanning.

        Args:
            asset: Image asset with chart_data populated

        Returns:
            List of MetricCandidate objects found
        """
        candidates: list[MetricCandidate] = []
        chart = asset.chart_data
        if chart is None:
            return candidates

        # Build searchable text from chart metadata
        searchable_parts = [chart.title, chart.y_axis_label, chart.x_axis_label]
        searchable_parts.extend(s.name for s in chart.series)
        # Include annotation text in searchable metadata
        searchable_parts.extend(a.text for a in chart.annotations if a.text)
        combined_text = " ".join(p for p in searchable_parts if p)

        # Also prepare nearby_text for secondary search
        nearby_text = (asset.nearby_text or "").strip()

        if not combined_text.strip() and not nearby_text:
            return candidates

        # Track which metric_ids were found in chart metadata vs only in nearby_text
        found_in_metadata: set[str] = set()

        # First pass: search chart metadata (title, axes, series, annotations)
        if combined_text.strip():
            for metric_id, patterns in self._compiled_patterns.items():
                for pattern in patterns:
                    for match in pattern.finditer(combined_text):
                        if self._is_excluded(metric_id, combined_text, match):
                            continue
                        if not self._has_required_context(metric_id, combined_text, match.start()):
                            continue

                        confidence = self._compute_confidence(
                            metric_id=metric_id,
                            match_text=match.group(),
                            source_type=SourceType.CHART,
                            section_type=asset.section_type,
                        )

                        candidate = MetricCandidate(
                            metric_id=metric_id,
                            match_text=match.group(),
                            source_locator=SourceLocator(
                                img_id=asset.img_id,
                                dom_locator=asset.dom_locator,
                            ),
                            source_type=SourceType.CHART,
                            confidence=confidence,
                            context_text=combined_text[:200],
                            section_type=asset.section_type,
                        )
                        candidates.append(candidate)
                        found_in_metadata.add(metric_id)

        # Second pass: search nearby_text for metrics NOT already found in metadata
        if nearby_text:
            for metric_id, patterns in self._compiled_patterns.items():
                if metric_id in found_in_metadata:
                    continue  # Already found from chart metadata
                for pattern in patterns:
                    for match in pattern.finditer(nearby_text):
                        if self._is_excluded(metric_id, nearby_text, match):
                            continue
                        if not self._has_required_context(metric_id, nearby_text, match.start()):
                            continue

                        confidence = self._compute_confidence(
                            metric_id=metric_id,
                            match_text=match.group(),
                            source_type=SourceType.CHART,
                            section_type=asset.section_type,
                        )
                        # Penalty for nearby_text-only match (indirect link)
                        confidence = max(0.0, confidence - 0.05)

                        candidate = MetricCandidate(
                            metric_id=metric_id,
                            match_text=match.group(),
                            source_locator=SourceLocator(
                                img_id=asset.img_id,
                                dom_locator=asset.dom_locator,
                            ),
                            source_type=SourceType.CHART,
                            confidence=confidence,
                            context_text=nearby_text[:200],
                            section_type=asset.section_type,
                        )
                        candidates.append(candidate)

        return self._deduplicate_chart_candidates(candidates)

    def _deduplicate_chart_candidates(
        self, candidates: list[MetricCandidate]
    ) -> list[MetricCandidate]:
        """
        Deduplicate chart candidates by (metric_id, img_id).

        Charts produce at most one candidate per metric per image since
        the entire chart metadata is treated as one searchable unit.

        Args:
            candidates: Chart candidates to deduplicate

        Returns:
            Deduplicated list, keeping highest confidence per (metric_id, img_id)
        """
        if not candidates:
            return candidates

        seen: dict[tuple[str, str | None], MetricCandidate] = {}
        for candidate in candidates:
            key = (candidate.metric_id, candidate.source_locator.img_id)
            if key not in seen or candidate.confidence > seen[key].confidence:
                seen[key] = candidate
        return list(seen.values())

    def _cross_metric_dedup(self, candidates: list[MetricCandidate]) -> list[MetricCandidate]:
        """
        Suppress candidates whose match span is strictly contained by another
        candidate's span within the same segment or table cell.

        This handles wrong-metric bindings where e.g. "daily active users"
        creates candidates for both cm_daily_active_users (longer match) and
        cm_active_customers_total (shorter "active users" match).

        Rules:
        - Text candidates: group by segment_id; suppress when one span
          strictly contains another (inner.start >= outer.start AND
          inner.end <= outer.end, with at least one strict inequality).
        - Table candidates: group by (table_id, cell_row, cell_col);
          suppress when one match_text is a strict substring of another.
        - Identical spans are NOT suppressed (different metrics, same span).
        """
        if len(candidates) <= 1:
            return candidates

        # Separate text vs table candidates
        text_candidates: dict[str, list[MetricCandidate]] = {}
        table_candidates: dict[tuple, list[MetricCandidate]] = {}
        other: list[MetricCandidate] = []

        for c in candidates:
            loc = c.source_locator
            if loc.text_span:
                key = loc.segment_id or ""
                text_candidates.setdefault(key, []).append(c)
            elif loc.cell_row is not None and loc.cell_col is not None:
                key = (loc.table_id, loc.cell_row, loc.cell_col)
                table_candidates.setdefault(key, []).append(c)
            else:
                other.append(c)

        suppressed: set[int] = set()

        # Text span containment (including exact-span dedup for different metrics)
        for group in text_candidates.values():
            for i, a in enumerate(group):
                if id(a) in suppressed:
                    continue
                a_start, a_end = a.source_locator.text_span  # type: ignore[misc]
                for j, b in enumerate(group):
                    if i == j or id(b) in suppressed:
                        continue
                    b_start, b_end = b.source_locator.text_span  # type: ignore[misc]

                    # Exact same span: suppress the shorter match_text (less specific)
                    if b_start == a_start and b_end == a_end:
                        if len(b.match_text) < len(a.match_text):
                            suppressed.add(id(b))
                            logger.debug(
                                f"Cross-metric dedup: suppressed {b.metric_id} "
                                f"({b.match_text!r}, shorter) at same span as "
                                f"{a.metric_id} ({a.match_text!r})"
                            )
                        elif len(a.match_text) < len(b.match_text):
                            suppressed.add(id(a))
                            logger.debug(
                                f"Cross-metric dedup: suppressed {a.metric_id} "
                                f"({a.match_text!r}, shorter) at same span as "
                                f"{b.metric_id} ({b.match_text!r})"
                            )
                            break  # a is suppressed, move to next a
                        # Same length: both kept (genuinely ambiguous)
                        continue

                    # Check if b is strictly contained in a (same metric only)
                    if (
                        a.metric_id == b.metric_id
                        and b_start >= a_start
                        and b_end <= a_end
                        and (b_start > a_start or b_end < a_end)
                    ):
                        suppressed.add(id(b))
                        logger.debug(
                            f"Cross-metric dedup: suppressed {b.metric_id} "
                            f"({b.match_text!r}) contained in {a.metric_id} "
                            f"({a.match_text!r})"
                        )

        # Table cell substring containment
        for group in table_candidates.values():
            for i, a in enumerate(group):
                if id(a) in suppressed:
                    continue
                for j, b in enumerate(group):
                    if i == j or id(b) in suppressed:
                        continue
                    a_text = a.match_text.lower()
                    b_text = b.match_text.lower()
                    # Check if b's match_text is a strict substring of a's (same metric only)
                    if (
                        a.metric_id == b.metric_id
                        and b_text in a_text
                        and len(b_text) < len(a_text)
                    ):
                        suppressed.add(id(b))
                        logger.debug(
                            f"Cross-metric dedup (table): suppressed {b.metric_id} "
                            f"({b.match_text!r}) substring of {a.metric_id} "
                            f"({a.match_text!r})"
                        )

        result = [c for c in candidates if id(c) not in suppressed]
        if suppressed:
            logger.info(
                f"Cross-metric dedup: suppressed {len(suppressed)} of {len(candidates)} candidates"
            )
        return result

    def _deduplicate_candidates(self, candidates: list[MetricCandidate]) -> list[MetricCandidate]:
        """
        Remove duplicate candidates for the same metric at the same location.

        When multiple patterns match the same metric at the same or overlapping
        locations, keep only the highest-confidence candidate.

        For overlapping text spans (e.g., "customers" and "new customers"),
        uses the END position as the key since both patterns end at the same
        position when matching the same occurrence.

        Args:
            candidates: List of candidates to deduplicate

        Returns:
            Deduplicated list, keeping highest confidence per (metric_id, location)
        """
        if not candidates:
            return candidates

        # Group by (metric_id, location_key)
        # For segments: use text_span END position (handles overlapping patterns)
        # For tables: use (cell_row, cell_col)
        seen: dict[tuple[str, str], MetricCandidate] = {}

        for candidate in candidates:
            loc = candidate.source_locator
            if loc.text_span:
                # Segment-based: use END position as key
                # This handles overlapping patterns like "customers" and "new customers"
                # which both end at the same position when matching the same occurrence
                location_key = f"seg:{loc.segment_id}:{loc.text_span[1]}"
            elif loc.cell_row is not None and loc.cell_col is not None:
                # Table cell-based
                location_key = f"tbl:{loc.table_id}:{loc.cell_row}:{loc.cell_col}"
            else:
                # Fallback: use segment_id
                location_key = f"seg:{loc.segment_id}:0"

            key = (candidate.metric_id, location_key)

            if key not in seen or candidate.confidence > seen[key].confidence:
                seen[key] = candidate

        return list(seen.values())

    def _is_excluded(self, metric_id: str, text: str, match: re.Match[str]) -> bool:
        """
        Check if a match should be excluded by exclusion patterns.

        Args:
            metric_id: The metric being checked
            text: Full text containing the match
            match: The regex match object

        Returns:
            True if the match should be excluded
        """
        exclusions = self._compiled_exclusions.get(metric_id, [])
        if not exclusions:
            return False

        # Check if any exclusion pattern matches in the vicinity of our match
        # Use a window around the match for context-aware exclusions
        window_start = max(0, match.start() - 50)
        window_end = min(len(text), match.end() + 50)
        window_text = text[window_start:window_end]

        for exclusion in exclusions:
            if exclusion.search(window_text):
                return True

        return False

    def _has_required_context(self, metric_id: str, text: str, match_position: int) -> bool:
        """
        Check if required context patterns are present within proximity.

        Some metrics (e.g., revenue synonyms) require specific context
        like cohort or per-customer keywords to be considered candidates.
        Uses proximity-based checking to ensure context is near the match.

        Args:
            metric_id: The metric being checked
            text: Full text to check for context
            match_position: Position of the keyword match in text

        Returns:
            True if no required context OR required context is present within proximity
        """
        context_data = self._compiled_context.get(metric_id)
        if not context_data:
            # No required context for this metric
            return True

        patterns, proximity_chars = context_data

        # Extract text within proximity window of the match
        context_start = max(0, match_position - proximity_chars)
        context_end = min(len(text), match_position + proximity_chars)
        proximity_text = text[context_start:context_end]

        # At least one context pattern must match within the proximity window
        for pattern in patterns:
            if pattern.search(proximity_text):
                return True

        return False

    def _extract_context(self, text: str, start: int, end: int) -> str:
        """
        Extract surrounding context for a match.

        Args:
            text: Full text
            start: Match start position
            end: Match end position

        Returns:
            Context string with CONTEXT_WINDOW chars on each side
        """
        context_start = max(0, start - self.CONTEXT_WINDOW)
        context_end = min(len(text), end + self.CONTEXT_WINDOW)
        return text[context_start:context_end]

    def _compute_confidence(
        self,
        metric_id: str,
        match_text: str,
        source_type: SourceType,
        section_type: SectionType,
    ) -> float:
        """
        Compute confidence score for a candidate.

        Args:
            metric_id: The matched metric ID
            match_text: The matched text
            source_type: Source type (TEXT, HTML_TABLE, etc.)
            section_type: Section where match was found

        Returns:
            Confidence score between 0.0 and 1.0
        """
        confidence = self.BASE_CONFIDENCE

        # Bonus for specific (multi-word) pattern match
        for pattern in self._compiled_specific:
            if pattern.search(match_text):
                confidence += self.SPECIFIC_PATTERN_BONUS
                break

        # Bonus for structured source (table or chart)
        if source_type in (SourceType.HTML_TABLE, SourceType.OCR_TABLE, SourceType.CHART):
            confidence += self.TABLE_SOURCE_BONUS

        # Bonus for high-value sections (MD&A, Business)
        if section_type in self.HIGH_VALUE_SECTIONS:
            confidence += self.SECTION_BONUS

        return max(0.0, min(1.0, confidence))

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
            stage=PipelineStage.CANDIDATE_GENERATION,
            success=len(errors) == 0,
            duration_ms=duration_ms,
            items_processed=items_processed,
            items_output=items_output,
            errors=errors,
            warnings=warnings,
            metadata={
                "metrics_scanned": len(self._compiled_patterns),
            },
        )
