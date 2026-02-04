"""
V2 Deduplication Stage

Stage 10 of the V2 extraction pipeline. Identifies duplicate MetricFact objects
(same metric, period, value within tolerance), selects a primary based on source
quality, and links alternates via the alternate_evidence field.

Design principles:
- Rule-based only (no LLM calls)
- Preserve all evidence by linking alternates to primary
- Source quality ranking: HTML_TABLE > TEXT > OCR_TABLE > CHART
- Within same source type, prefer higher confidence
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import TYPE_CHECKING

from src.extraction_v2.models import MetricFact, SourceType

if TYPE_CHECKING:
    from src.extraction_v2.pipeline import PipelineContext, StageResult

logger = logging.getLogger(__name__)


# Source quality ranking (higher = better)
SOURCE_QUALITY_RANK: dict[SourceType, int] = {
    SourceType.HTML_TABLE: 4,
    SourceType.TEXT: 3,
    SourceType.OCR_TABLE: 2,
    SourceType.CHART: 1,
}


class DeduplicationStage:
    """
    Stage 10: Deduplication.

    Groups facts by identity tuple (metric_id, period, unit, value±tolerance,
    scope, cohort_def, customer_type), selects highest-quality source as primary,
    and links alternate fact_ids to preserve all evidence.
    """

    def __init__(self, value_tolerance: float = 0.02) -> None:
        """
        Initialize the deduplication stage.

        Args:
            value_tolerance: Tolerance for value comparison (default 2%)
        """
        self.value_tolerance = value_tolerance

    def process(self, context: PipelineContext) -> StageResult:
        """
        Deduplicate facts and link alternates.

        Args:
            context: Pipeline context with facts populated

        Returns:
            StageResult with deduplication statistics
        """
        from src.extraction_v2.pipeline import PipelineStage, StageResult

        start_time = datetime.utcnow()
        initial_count = len(context.facts)

        # Use tolerance from config if available
        tolerance = getattr(context.config, "value_tolerance", self.value_tolerance)

        # Group duplicates
        groups = self._group_duplicates(context.facts, tolerance)

        # Select primaries and link alternates
        primaries: list[MetricFact] = []
        groups_with_alternates = 0

        for group in groups:
            primary = self._select_primary(group)

            if len(group) > 1:
                # Link alternates to primary
                primary.alternate_evidence = [
                    f.fact_id for f in group if f.fact_id != primary.fact_id
                ]
                groups_with_alternates += 1
                logger.debug(
                    f"Merged {len(group)} duplicates for {primary.canonical_metric_id}, "
                    f"primary source: {primary.source_type.value}"
                )

            primaries.append(primary)

        # Store deduplicated facts
        context.deduplicated_facts = primaries

        # Build result
        duration_ms = int((datetime.utcnow() - start_time).total_seconds() * 1000)
        duplicates_removed = initial_count - len(primaries)

        return StageResult(
            stage=PipelineStage.DEDUPLICATION,
            success=True,
            duration_ms=duration_ms,
            items_processed=initial_count,
            items_output=len(primaries),
            metadata={
                "duplicates_removed": duplicates_removed,
                "groups_with_alternates": groups_with_alternates,
                "total_groups": len(groups),
            },
        )

    def _group_duplicates(
        self, facts: list[MetricFact], tolerance: float
    ) -> list[list[MetricFact]]:
        """
        Group facts that are duplicates of each other.

        Uses MetricFact.is_duplicate_of() for comparison which handles
        value tolerance and None comparisons.

        Args:
            facts: List of facts to group
            tolerance: Value tolerance for duplicate detection

        Returns:
            List of groups, where each group contains duplicate facts
        """
        if not facts:
            return []

        groups: list[list[MetricFact]] = []
        used: set[str] = set()

        for i, fact in enumerate(facts):
            if fact.fact_id in used:
                continue

            # Start a new group with this fact
            group = [fact]
            used.add(fact.fact_id)

            # Find all duplicates
            for other in facts[i + 1 :]:
                if other.fact_id in used:
                    continue

                if fact.is_duplicate_of(other, tolerance):
                    group.append(other)
                    used.add(other.fact_id)

            groups.append(group)

        return groups

    def _select_primary(self, group: list[MetricFact]) -> MetricFact:
        """
        Select the highest-quality fact as primary.

        Selection criteria (in order):
        1. Source quality: HTML_TABLE > TEXT > OCR_TABLE > CHART
        2. Confidence score (higher is better)

        Args:
            group: List of duplicate facts

        Returns:
            The fact selected as primary
        """
        if len(group) == 1:
            return group[0]

        # Sort by source quality (desc), then confidence (desc)
        return max(
            group,
            key=lambda f: (
                SOURCE_QUALITY_RANK.get(f.source_type, 0),
                f.confidence,
            ),
        )
