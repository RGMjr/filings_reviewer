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
from datetime import UTC, date, datetime
from typing import TYPE_CHECKING

from src.extraction_v2.exceptions import V2FatalError
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
        self._last_post_transfer_collisions: int = 0

    def process(self, context: PipelineContext) -> StageResult:
        """
        Deduplicate facts and link alternates.

        Args:
            context: Pipeline context with facts populated

        Returns:
            StageResult with deduplication statistics
        """
        from src.extraction_v2.pipeline import PipelineStage, StageResult

        try:
            start_time = datetime.now(UTC)
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

            # Second pass: collapse same-value facts with different periods
            after_identity = len(primaries)
            primaries = self._fuzzy_period_dedup(primaries, tolerance)
            fuzzy_removed = after_identity - len(primaries)

            # Store deduplicated facts
            context.deduplicated_facts = primaries

            # Build result
            duration_ms = int((datetime.now(UTC) - start_time).total_seconds() * 1000)
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
                    "fuzzy_period_removed": fuzzy_removed,
                    "post_transfer_collisions": self._last_post_transfer_collisions,
                },
            )
        except V2FatalError:
            raise
        except Exception as e:
            raise V2FatalError(str(e), stage_name="deduplication") from e

    def _group_duplicates(
        self, facts: list[MetricFact], tolerance: float
    ) -> list[list[MetricFact]]:
        """
        Group facts that are duplicates of each other.

        Pre-groups facts by non-value identity fields (O(n)), then runs
        pairwise value-tolerance comparison only within each pre-group (O(k²)
        where k is group size, typically small).

        Args:
            facts: List of facts to group
            tolerance: Value tolerance for duplicate detection

        Returns:
            List of groups, where each group contains duplicate facts
        """
        if not facts:
            return []

        # Pre-group by identity fields (excluding value) for O(n) bucketing
        identity_buckets: dict[
            tuple[str, date | None, date | None, str, str, str, str],
            list[MetricFact],
        ] = {}
        for fact in facts:
            bucket_key = (
                fact.canonical_metric_id,
                fact.period_start,
                fact.period_end,
                fact.unit.value,
                fact.scope.value,
                fact.cohort_def or "",
                fact.customer_type or "",
            )
            identity_buckets.setdefault(bucket_key, []).append(fact)

        groups: list[list[MetricFact]] = []

        for _bucket_key, bucket_facts in identity_buckets.items():
            if len(bucket_facts) == 1:
                groups.append(bucket_facts)
                continue

            # Within each bucket, group by value tolerance (O(k²) but k is small)
            used: set[str] = set()
            for i, fact in enumerate(bucket_facts):
                if fact.fact_id in used:
                    continue

                group = [fact]
                used.add(fact.fact_id)

                for other in bucket_facts[i + 1 :]:
                    if other.fact_id in used:
                        continue

                    if fact.is_duplicate_of(other, tolerance):
                        group.append(other)
                        used.add(other.fact_id)

                groups.append(group)

        if len(facts) > 100:
            bucket_sizes = [len(b) for b in identity_buckets.values()]
            logger.info(
                f"Dedup pre-grouping: {len(facts)} facts → "
                f"{len(identity_buckets)} identity buckets "
                f"(max bucket size: {max(bucket_sizes)})"
            )

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

        # Sort by source quality (desc), then confidence (desc).
        # Tie-break with stable content-derived keys (dom_locator provides document
        # position ordering; value_raw breaks remaining ties) so results are
        # deterministic across runs regardless of UUID or dict iteration order.
        return max(
            group,
            key=lambda f: (
                SOURCE_QUALITY_RANK.get(f.source_type, 0),
                f.confidence,
                f.source_locator.dom_locator or "",
                f.value_raw,
            ),
        )

    def _fuzzy_period_dedup(self, facts: list[MetricFact], tolerance: float) -> list[MetricFact]:
        """
        Second-pass dedup: collapse facts with same metric+value but different periods.

        When the same metric+value is extracted with slightly different period
        representations (e.g., "FY2019" vs "year ended Jan 31, 2019"), the
        identity-based dedup misses them because periods differ. This pass
        groups by (metric_id, unit, scope, value±tolerance) ignoring period,
        then keeps only the highest-confidence fact per group.
        """
        if not facts:
            return []

        # Group by non-period identity fields + value tolerance.
        # customer_type is intentionally excluded (like period): the same measurement
        # can appear multiple times with different surrounding context, causing one
        # mention to get a customer_type label and another not. Excluding customer_type
        # lets these same-value duplicates merge; the most-specific label is then
        # promoted to the primary (see below).
        buckets: dict[tuple[str, str, str, str], list[MetricFact]] = {}
        for fact in facts:
            bucket_key = (
                fact.canonical_metric_id,
                fact.unit.value,
                fact.scope.value,
                fact.cohort_def or "",
            )
            buckets.setdefault(bucket_key, []).append(fact)

        result: list[MetricFact] = []
        removed = 0

        for _bucket_key, bucket_facts in buckets.items():
            if len(bucket_facts) == 1:
                result.append(bucket_facts[0])
                continue

            # Sort bucket_facts by a stable key before chaining so that which
            # fact becomes the group seed (and therefore which facts merge together)
            # is deterministic regardless of dict iteration order.
            bucket_facts = sorted(
                bucket_facts,
                key=lambda f: (
                    SOURCE_QUALITY_RANK.get(f.source_type, 0),
                    f.confidence,
                    f.source_locator.dom_locator or "",
                    f.value_raw,
                ),
                reverse=True,
            )

            # Within bucket, group by value tolerance
            value_groups: list[list[MetricFact]] = []
            used: set[str] = set()

            for i, fact in enumerate(bucket_facts):
                if fact.fact_id in used:
                    continue

                group = [fact]
                used.add(fact.fact_id)

                for other in bucket_facts[i + 1 :]:
                    if other.fact_id in used:
                        continue
                    if not self._values_within_tolerance(fact.value, other.value, tolerance):
                        continue
                    # Only merge if periods overlap or one/both are missing
                    if not self._periods_compatible(fact, other):
                        continue
                    group.append(other)
                    used.add(other.fact_id)

                value_groups.append(group)

            for group in value_groups:
                if len(group) == 1:
                    result.append(group[0])
                else:
                    primary = self._select_primary(group)
                    # Transfer period/customer_type from group members onto the primary when
                    # the primary lacks those fields.  These mutations can cause two surviving
                    # primaries (from different value_groups) to end up with identical identity
                    # tuples — those post-transfer collisions are resolved by
                    # _collapse_post_transfer_collisions, called after this loop.
                    if not (primary.period_start and primary.period_end):
                        period_donors = [
                            f for f in group
                            if f.period_start and f.period_end and f.fact_id != primary.fact_id
                        ]
                        if period_donors:
                            donor = period_donors[0]
                            primary.period_start = donor.period_start
                            primary.period_end = donor.period_end
                            primary.period_type = donor.period_type
                    # Promote the most-specific customer_type label from the group onto
                    # the primary if the primary lacks one.  A fact labelled "Paid" from
                    # a mention that clearly names the segment is more informative than a
                    # label-less duplicate from a generic mention of the same value.
                    if primary.customer_type is None:
                        for f in group:
                            if f.customer_type is not None and f.fact_id != primary.fact_id:
                                primary.customer_type = f.customer_type
                                break
                    new_ids = [f.fact_id for f in group if f.fact_id != primary.fact_id]
                    existing = set(primary.alternate_evidence)
                    primary.alternate_evidence.extend(
                        fid for fid in dict.fromkeys(new_ids) if fid not in existing
                    )
                    result.append(primary)
                    removed += len(group) - 1

        result, post_transfer_collisions = self._collapse_post_transfer_collisions(result)
        self._last_post_transfer_collisions = post_transfer_collisions
        if post_transfer_collisions > 0:
            logger.info(
                "Post-transfer collision collapse: merged %d colliding primaries",
                post_transfer_collisions,
            )

        if removed > 0:
            logger.info(
                "Fuzzy period dedup: removed %d duplicate-value facts (%d → %d)",
                removed,
                len(facts),
                len(result),
            )

        return result

    def _collapse_post_transfer_collisions(
        self, primaries: list[MetricFact]
    ) -> tuple[list[MetricFact], int]:
        """
        Resolve identity-tuple collisions introduced by the period-transfer and
        customer_type-promotion mutations in _fuzzy_period_dedup. Winners are
        selected via _select_primary; losers are linked as alternate_evidence.

        The DB unique index (sql/23_chart_source_dedup.sql) enforces uniqueness on
        (doc_id, metric, period_start, period_end, unit, scope, cohort_def,
        customer_type, source_type). Two facts sharing all of these — even with
        different values — cannot coexist and must be collapsed here before INSERT.
        """
        buckets: dict[tuple, list[MetricFact]] = {}
        for fact in primaries:
            key = (
                fact.canonical_metric_id,
                fact.period_start,
                fact.period_end,
                fact.unit.value,
                fact.scope.value,
                fact.cohort_def or "",
                fact.customer_type or "",
                fact.source_type.value,
            )
            buckets.setdefault(key, []).append(fact)

        result: list[MetricFact] = []
        collisions = 0
        for bucket in buckets.values():
            if len(bucket) == 1:
                result.append(bucket[0])
                continue
            winner = self._select_primary(bucket)
            new_ids: list[str] = []
            for loser in bucket:
                if loser.fact_id == winner.fact_id:
                    continue
                new_ids.append(loser.fact_id)
                new_ids.extend(loser.alternate_evidence)
            existing = set(winner.alternate_evidence)
            winner.alternate_evidence.extend(
                fid for fid in dict.fromkeys(new_ids) if fid not in existing
            )
            collisions += len(bucket) - 1
            result.append(winner)
        return result, collisions

    @staticmethod
    def _periods_compatible(a: MetricFact, b: MetricFact) -> bool:
        """
        Check if two facts have compatible periods for fuzzy dedup.

        Compatible means: periods overlap, or one/both have no period set.
        Facts with genuinely different non-overlapping periods should NOT be merged.
        """
        # If either has no period, consider compatible (can't distinguish)
        if not a.period_start or not a.period_end:
            return True
        if not b.period_start or not b.period_end:
            return True
        # Check for overlap
        if a.period_end < b.period_start or b.period_end < a.period_start:
            return False
        return True

    @staticmethod
    def _values_within_tolerance(v1: float | None, v2: float | None, tolerance: float) -> bool:
        """Check if two values are within tolerance."""
        if v1 is None and v2 is None:
            return True
        if v1 is None or v2 is None:
            return False
        if v1 == 0 and v2 == 0:
            return True
        if v1 == 0 or v2 == 0:
            return abs(v1 - v2) <= tolerance
        return abs(v1 - v2) / abs(v2) <= tolerance
