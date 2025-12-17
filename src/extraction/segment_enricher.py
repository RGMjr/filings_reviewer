"""
Segment Enricher - Enrich classified segments with richness metadata.

This module computes richness metadata for SourceSegments after classification:
- Metric density (metrics per 100 characters)
- Distinct metric count
- Temporal trend detection
- (Future: cohort breakdowns, image detection, richness score)

The enricher operates on in-memory objects without database dependencies.
"""

import logging
import re
from typing import List, Pattern

from .models import SourceSegment

logger = logging.getLogger(__name__)


class SegmentEnricher:
    """
    Enrich classified segments with richness metadata.

    This class computes additional metadata for SourceSegments that have
    already been classified by MetricClassifier. It operates on in-memory
    objects and does not require database access.

    Current capabilities (G4-G5):
    - metric_density: metrics per 100 characters
    - distinct_metric_count: count of unique metric IDs
    - contains_temporal_trend: segment discusses multiple time periods (G5)

    Future capabilities (G6-G8):
    - contains_cohort_breakdown (G6)
    - image_count (G7)
    - richness_score (G8)
    """

    # Compiled regex patterns for temporal trend detection (G5)
    # Year pattern: 4-digit years in range 2000-2099
    YEAR_PATTERN: Pattern[str] = re.compile(r"\b20\d{2}\b")

    # Fiscal period pattern: FY2023, FY 2022, Q1 2023, Q4 2022, etc.
    FISCAL_PERIOD_PATTERN: Pattern[str] = re.compile(
        r"\b(?:FY|Q[1-4])\s*20\d{2}\b", re.IGNORECASE
    )

    # Year-over-year language patterns (case-insensitive)
    YOY_PATTERNS: List[Pattern[str]] = [
        re.compile(r"\byear[- ]over[- ]year\b", re.IGNORECASE),
        re.compile(r"\byoy\b", re.IGNORECASE),
        re.compile(
            r"\bcompared to (?:the )?(?:prior|previous|same)\s+(?:year|period)\b",
            re.IGNORECASE,
        ),
    ]

    def __init__(self) -> None:
        """Initialize enricher (stateless, patterns compiled at class level)."""
        pass

    def enrich_batch(self, segments: List[SourceSegment]) -> List[SourceSegment]:
        """
        Enrich all segments with richness metadata.

        Args:
            segments: Classified segments to enrich (mutated in place)

        Returns:
            Same segments list with enrichment fields populated
        """
        if not segments:
            logger.info("No segments to enrich")
            return segments

        enriched_count = 0
        warning_count = 0

        for segment in segments:
            try:
                self._enrich_segment(segment)
                enriched_count += 1
            except Exception as e:
                logger.warning(
                    f"Failed to enrich segment {segment.sequence_index}: {e}"
                )
                warning_count += 1

        logger.info(
            f"Enriched {enriched_count} segments"
            + (f" ({warning_count} warnings)" if warning_count else "")
        )

        return segments

    def _enrich_segment(self, segment: SourceSegment) -> None:
        """
        Enrich single segment (mutates in place).

        Args:
            segment: Segment to enrich
        """
        # Compute metric density and distinct count (G4)
        segment.metric_density = self._compute_metric_density(segment)
        segment.distinct_metric_count = self._compute_distinct_metric_count(segment)

        # Detect temporal trends (G5)
        segment.contains_temporal_trend = self._detect_temporal_trends(segment)

        # Future enrichments (G6-G8) will be added here:
        # - self._detect_cohort_breakdowns(segment)
        # - self._detect_images(segment)
        # - self._compute_richness_score(segment)

    def _compute_metric_density(self, segment: SourceSegment) -> float:
        """
        Compute metrics per 100 characters.

        Formula: (unique_metrics / text_length) * 100

        Args:
            segment: Segment to compute density for

        Returns:
            Metric density rounded to 2 decimal places, or 0.0 for edge cases
        """
        # Handle edge cases
        raw_text = segment.raw_text
        if raw_text is None:
            return 0.0

        text_length = len(raw_text)
        if text_length == 0:
            return 0.0

        candidate_metric_ids = segment.candidate_metric_ids
        if candidate_metric_ids is None:
            return 0.0

        unique_metrics = len(set(candidate_metric_ids))
        if unique_metrics == 0:
            return 0.0

        # Compute density: (unique_metrics / text_length) * 100
        density = (unique_metrics / text_length) * 100

        return round(density, 2)

    def _compute_distinct_metric_count(self, segment: SourceSegment) -> int:
        """
        Compute count of unique metric IDs in segment.

        Args:
            segment: Segment to count metrics for

        Returns:
            Count of unique metric IDs, or 0 for edge cases
        """
        candidate_metric_ids = segment.candidate_metric_ids
        if candidate_metric_ids is None:
            return 0

        return len(set(candidate_metric_ids))

    def _detect_temporal_trends(self, segment: SourceSegment) -> bool:
        """
        Detect if segment discusses multiple time periods.

        Returns True if any of these conditions are met:
        - 2+ distinct years (2000-2099) are mentioned
        - 2+ distinct fiscal periods (FY/Q1-Q4) are mentioned
        - Year-over-year comparison language is present

        Args:
            segment: Segment to analyze for temporal trends

        Returns:
            True if temporal trend detected, False otherwise
        """
        text = segment.raw_text

        # Handle edge cases: None, empty, or non-string
        if text is None:
            return False
        if not isinstance(text, str):
            logger.warning(
                f"Non-string raw_text in segment {segment.sequence_index}: {type(text)}"
            )
            return False
        if not text:
            return False

        # Check for multiple distinct years (primary signal)
        years = set(self.YEAR_PATTERN.findall(text))
        if len(years) >= 2:
            return True

        # Check for multiple distinct fiscal periods (secondary signal)
        fiscal_periods = set(self.FISCAL_PERIOD_PATTERN.findall(text.upper()))
        if len(fiscal_periods) >= 2:
            return True

        # Check for year-over-year language (tertiary signal)
        for pattern in self.YOY_PATTERNS:
            if pattern.search(text):
                return True

        return False
