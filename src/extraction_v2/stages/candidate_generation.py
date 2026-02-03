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
)
from src.extraction_v2.models import (
    MetricCandidate,
    SectionType,
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
            self._keywords = get_metric_keywords()
            self._exclusions = get_exclusion_patterns()
            self._required_context = get_required_context()
            self._specific_patterns = get_specific_patterns()
            self._compile_patterns()
            self._initialized = True
            logger.info(
                f"Candidate generation initialized: {len(self._keywords)} metrics"
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
                    logger.warning(
                        f"Invalid regex pattern for {metric_id}: {pattern!r} - {e}"
                    )
            self._compiled_patterns[metric_id] = compiled

        # Compile exclusion patterns
        for metric_id, patterns in self._exclusions.items():
            compiled = []
            for pattern in patterns:
                try:
                    compiled.append(re.compile(pattern, re.IGNORECASE))
                except re.error as e:
                    logger.warning(
                        f"Invalid exclusion pattern for {metric_id}: {pattern!r} - {e}"
                    )
            self._compiled_exclusions[metric_id] = compiled

        # Compile required context patterns with proximity
        for metric_id, config in self._required_context.items():
            compiled = []
            for pattern in config.get("patterns", []):
                try:
                    compiled.append(re.compile(pattern, re.IGNORECASE))
                except re.error as e:
                    logger.warning(
                        f"Invalid context pattern for {metric_id}: {pattern!r} - {e}"
                    )
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
            return self._make_result(
                start_time, 0, candidates_found, errors, warnings
            )

        # Scan segments
        for segment in context.segments:
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

        items_processed = len(context.segments) + len(context.tables)

        logger.info(
            f"Candidate generation complete: {candidates_found} candidates "
            f"from {len(context.segments)} segments, {len(context.tables)} tables"
        )

        return self._make_result(
            start_time, items_processed, candidates_found, errors, warnings
        )

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

        return self._deduplicate_candidates(candidates)

    def _scan_table(self, table: Table) -> list[MetricCandidate]:
        """
        Scan table cells for metric keyword matches.

        Scans both cell text and header_path/stub_path to catch metrics
        mentioned in table headers.

        Args:
            table: The table to scan

        Returns:
            List of MetricCandidate objects found
        """
        candidates: list[MetricCandidate] = []

        for cell in table.cells:
            # Build combined text: cell text + headers + stubs
            combined_parts = [cell.text]
            combined_parts.extend(cell.header_path)
            combined_parts.extend(cell.stub_path)
            combined_text = " ".join(combined_parts)

            if not combined_text.strip():
                continue

            for metric_id, patterns in self._compiled_patterns.items():
                for pattern in patterns:
                    for match in pattern.finditer(combined_text):
                        # Check exclusions
                        if self._is_excluded(metric_id, combined_text, match):
                            continue

                        # Check required context (proximity-based)
                        if not self._has_required_context(
                            metric_id, combined_text, match.start()
                        ):
                            continue

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

        return self._deduplicate_candidates(candidates)

    def _deduplicate_candidates(
        self, candidates: list[MetricCandidate]
    ) -> list[MetricCandidate]:
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

    def _is_excluded(
        self, metric_id: str, text: str, match: re.Match[str]
    ) -> bool:
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

    def _has_required_context(
        self, metric_id: str, text: str, match_position: int
    ) -> bool:
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

        # Bonus for table source (more structured)
        if source_type == SourceType.HTML_TABLE:
            confidence += self.TABLE_SOURCE_BONUS

        # Bonus for high-value sections (MD&A, Business)
        if section_type in self.HIGH_VALUE_SECTIONS:
            confidence += self.SECTION_BONUS

        return min(confidence, 1.0)

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
