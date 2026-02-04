"""
V2 Validation & Review Routing Stage

Stage 11 of the V2 extraction pipeline. Validates fact schema completeness,
routes facts to human review or auto-acceptance based on confidence thresholds,
and sets appropriate review reasons.

Design principles:
- Rule-based only (no LLM calls)
- Conservative routing: when in doubt, flag for review
- Detailed review reasons for human reviewers
- Schema validation catches incomplete facts early
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import TYPE_CHECKING

from src.extraction_v2.models import MetricFact, ReviewStatus, SourceType

if TYPE_CHECKING:
    from src.extraction_v2.pipeline import PipelineContext, StageResult

logger = logging.getLogger(__name__)


class ValidationStage:
    """
    Stage 11: Validation & Review Routing.

    Validates schema completeness and routes facts by confidence:
    - confidence >= 0.90: auto-accept (no review needed)
    - confidence < 0.15: auto-reject candidate (flagged for review)
    - otherwise: pending review

    Facts from OCR or chart sources are always flagged for verification
    regardless of confidence score.
    """

    def __init__(
        self,
        auto_accept_threshold: float = 0.90,
        auto_reject_threshold: float = 0.15,
    ) -> None:
        """
        Initialize the validation stage.

        Args:
            auto_accept_threshold: Confidence threshold for auto-acceptance (default 0.90)
            auto_reject_threshold: Confidence below which facts are auto-reject candidates (default 0.15)
        """
        self.auto_accept_threshold = auto_accept_threshold
        self.auto_reject_threshold = auto_reject_threshold

    def process(self, context: PipelineContext) -> StageResult:
        """
        Validate and route facts by confidence.

        Args:
            context: Pipeline context with deduplicated_facts populated

        Returns:
            StageResult with validation and routing statistics
        """
        from src.extraction_v2.pipeline import PipelineStage, StageResult

        start_time = datetime.utcnow()

        # Use deduplicated facts if available, otherwise facts
        facts = context.deduplicated_facts if context.deduplicated_facts else context.facts

        # Get thresholds from config if available
        auto_accept = getattr(
            context.config, "min_confidence_auto_accept", self.auto_accept_threshold
        )
        auto_reject = getattr(
            context.config, "max_confidence_auto_reject", self.auto_reject_threshold
        )

        stats = {
            "auto_accepted": 0,
            "pending_review": 0,
            "auto_reject_candidates": 0,
            "schema_validation_failures": 0,
        }

        for fact in facts:
            # Validate schema first
            schema_issues = self._validate_schema(fact)
            if schema_issues:
                stats["schema_validation_failures"] += 1
                logger.debug(
                    f"Schema validation failed for fact {fact.fact_id}: {schema_issues}"
                )

            # Build review reasons
            reasons: list[str] = []

            # Schema issues are high priority
            if schema_issues:
                reasons.extend(schema_issues)

            # Source-based reasons (OCR and chart need verification)
            if fact.source_type == SourceType.OCR_TABLE:
                reasons.append("OCR-based extraction requires verification")
            elif fact.source_type == SourceType.CHART:
                reasons.append("Chart-based extraction requires verification")

            # Preserve existing review reason if present
            if fact.review_reason and fact.review_reason not in reasons:
                reasons.insert(0, fact.review_reason)

            # Route by confidence
            if fact.confidence >= auto_accept and not reasons:
                # High confidence and no issues - auto-accept
                fact.requires_review = False
                fact.review_status = ReviewStatus.AUTO_ACCEPTED
                fact.review_reason = None
                stats["auto_accepted"] += 1
            elif fact.confidence < auto_reject:
                # Very low confidence - auto-reject candidate
                fact.requires_review = True
                fact.review_status = ReviewStatus.PENDING_REVIEW
                reasons.append("Low confidence (auto-reject candidate)")
                fact.review_reason = "; ".join(reasons)
                stats["auto_reject_candidates"] += 1
                stats["pending_review"] += 1
            else:
                # Middle confidence or has issues - pending review
                fact.requires_review = True
                fact.review_status = ReviewStatus.PENDING_REVIEW
                if not reasons:
                    reasons.append(
                        f"Confidence {fact.confidence:.0%} below auto-accept threshold"
                    )
                fact.review_reason = "; ".join(reasons)
                stats["pending_review"] += 1

        # Build result
        duration_ms = int((datetime.utcnow() - start_time).total_seconds() * 1000)

        logger.info(
            f"Validation complete: {stats['auto_accepted']} auto-accepted, "
            f"{stats['pending_review']} pending review"
        )

        return StageResult(
            stage=PipelineStage.VALIDATION,
            success=True,
            duration_ms=duration_ms,
            items_processed=len(facts),
            items_output=len(facts),
            metadata=stats,
        )

    def _validate_schema(self, fact: MetricFact) -> list[str]:
        """
        Validate required schema fields for a fact.

        Checks:
        - canonical_metric_id is non-empty
        - value OR value_raw is populated
        - source_locator has at least one locator (segment_id, table_id, or img_id)
        - evidence_pack.snippet_html is non-empty

        Args:
            fact: The MetricFact to validate

        Returns:
            List of schema validation issues (empty if valid)
        """
        issues: list[str] = []

        # Check canonical_metric_id
        if not fact.canonical_metric_id:
            issues.append("Missing required field: canonical_metric_id")

        # Check value or value_raw (at least one required)
        if fact.value is None and not fact.value_raw:
            issues.append("Missing required field: value or value_raw")

        # Check source_locator has at least one locator
        loc = fact.source_locator
        if not (loc.segment_id or loc.table_id or loc.img_id):
            issues.append(
                "Missing required field: source_locator (no segment_id, table_id, or img_id)"
            )

        # Check evidence_pack.snippet_html
        if not fact.evidence_pack.snippet_html:
            issues.append("Missing required field: evidence_pack.snippet_html")

        return issues
