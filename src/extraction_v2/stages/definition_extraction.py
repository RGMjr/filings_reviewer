"""
V2 Definition Extraction Stage

Stage 9.5 of the V2 extraction pipeline. Extracts definition and methodology
text for each metric found in context.facts, using DEFINITION/METHODOLOGY
segments near metric candidates.

Design principles:
- Pure rule-based (no LLM calls)
- Leverages segment classifications from ingestion stage
- One MetricDefinition per canonical_metric_id per document
"""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING

from src.extraction_v2.models import MetricDefinition, SegmentType

if TYPE_CHECKING:
    from src.extraction_v2.pipeline import PipelineContext, StageResult

logger = logging.getLogger(__name__)


# Canonical CMASB definitions for alignment assessment
# Ported from V1 src/extraction/definition_extractor.py
CANONICAL_DEFINITIONS: dict[str, dict] = {
    "cm_new_customers_acquired": {
        "keywords": [
            "first",
            "qualifying",
            "economic",
            "activity",
            "purchase",
            "transaction",
            "period",
        ],
        "definition": "Count of unique customers whose first qualifying economic activity with the company occurs in the reporting period.",
    },
    "cm_customers_period_end_by_tenure": {
        "keywords": [
            "active",
            "period",
            "end",
            "tenure",
            "cohort",
            "time",
            "since",
        ],
        "definition": "Number of customers active at period end, broken down by tenure cohorts.",
    },
    "cm_revenue_by_cohort": {
        "keywords": [
            "revenue",
            "gaap",
            "cohort",
            "acquisition",
            "tenure",
            "period",
        ],
        "definition": "Recognized GAAP revenue in the period, attributed to customer cohorts.",
    },
    "cm_transactions_by_cohort": {
        "keywords": ["transactions", "purchase", "cohort", "completed"],
        "definition": "Number of completed purchase transactions in the period, grouped by customer cohort.",
    },
}

# Window (in sequence order) to search for DEFINITION/METHODOLOGY segments
DEFINITION_SEARCH_WINDOW = 5


class DefinitionExtractionStage:
    """
    Stage 9.5: Definition Extraction.

    For each metric found in context.facts, searches nearby segments
    (within DEFINITION_SEARCH_WINDOW positions) for DEFINITION/METHODOLOGY
    segments and builds MetricDefinition objects.
    """

    def process(self, context: "PipelineContext") -> "StageResult":
        from datetime import datetime
        from src.extraction_v2.pipeline import PipelineStage, StageResult

        start = datetime.utcnow()

        if not context.facts:
            return StageResult(
                stage=PipelineStage.DEFINITION_EXTRACTION,
                success=True,
                duration_ms=0,
                items_processed=0,
                items_output=0,
            )

        # Build segment lookup by segment_id
        seg_by_id: dict[str, object] = {s.segment_id: s for s in context.segments}

        # Build sequence index for segments
        seg_by_seq: dict[int, object] = {s.sequence: s for s in context.segments}

        # Build segment_id -> sequence lookup
        seg_seq_by_id: dict[str, int] = {s.segment_id: s.sequence for s in context.segments}

        # Find candidate segment IDs per metric
        metric_segment_seqs: dict[str, set[int]] = {}
        for candidate in context.candidates:
            mid = candidate.metric_id
            sid = candidate.source_locator.segment_id if candidate.source_locator else None
            if sid and sid in seg_seq_by_id:
                metric_segment_seqs.setdefault(mid, set()).add(seg_seq_by_id[sid])

        # Collect unique metric IDs from facts
        metric_ids = list({f.canonical_metric_id for f in context.facts})

        definitions: list[MetricDefinition] = []

        for metric_id in metric_ids:
            candidate_seqs = metric_segment_seqs.get(metric_id, set())

            # Find all def/method segments in window around any candidate segment
            definition_segments = []
            methodology_segments = []

            for seq in candidate_seqs:
                for delta in range(-DEFINITION_SEARCH_WINDOW, DEFINITION_SEARCH_WINDOW + 1):
                    nearby_seg = seg_by_seq.get(seq + delta)
                    if nearby_seg is None:
                        continue
                    if nearby_seg.segment_type == SegmentType.DEFINITION:
                        if nearby_seg not in definition_segments:
                            definition_segments.append(nearby_seg)
                    elif nearby_seg.segment_type == SegmentType.METHODOLOGY:
                        if nearby_seg not in methodology_segments:
                            methodology_segments.append(nearby_seg)

            if not definition_segments and not methodology_segments:
                continue

            # Use first definition and methodology segments
            def_text = definition_segments[0].text if definition_segments else ""
            meth_text = methodology_segments[0].text if methodology_segments else ""

            def_normalized = self._normalize_text(def_text)
            meth_normalized = self._normalize_text(meth_text)

            # Assess alignment
            alignment_flag = self._assess_alignment(metric_id, def_normalized or meth_normalized)

            # Get the doc_id from context
            doc_id = context.document.doc_id if context.document else ""

            md = MetricDefinition(
                doc_id=doc_id,
                canonical_metric_id=metric_id,
                definition_text=def_text,
                definition_text_normalized=def_normalized,
                methodology_text=meth_text,
                methodology_text_normalized=meth_normalized,
                definition_segment_id=definition_segments[0].segment_id if definition_segments else None,
                methodology_segment_id=methodology_segments[0].segment_id if methodology_segments else None,
                alignment_flag=alignment_flag,
            )
            definitions.append(md)

        context.definitions = definitions

        end = datetime.utcnow()
        duration_ms = int((end - start).total_seconds() * 1000)

        logger.info(
            f"Definition extraction: {len(definitions)} definitions for "
            f"{len(metric_ids)} metrics in {duration_ms}ms"
        )

        return StageResult(
            stage=PipelineStage.DEFINITION_EXTRACTION,
            success=True,
            duration_ms=duration_ms,
            items_processed=len(metric_ids),
            items_output=len(definitions),
        )

    def _normalize_text(self, text: str) -> str:
        """Normalize definition text: remove excess whitespace, truncate to 500 chars."""
        if not text:
            return ""
        normalized = re.sub(r"\s+", " ", text).strip()
        if len(normalized) > 500:
            normalized = normalized[:500] + "..."
        return normalized

    def _assess_alignment(self, metric_id: str, issuer_definition: str) -> str:
        """
        Assess alignment between issuer and CMASB canonical definitions.

        Returns: 'aligned', 'partial', 'not_aligned', or 'unknown'
        """
        if not issuer_definition:
            return "unknown"

        canonical = CANONICAL_DEFINITIONS.get(metric_id)
        if not canonical:
            return "unknown"

        issuer_lower = issuer_definition.lower()
        keywords = canonical["keywords"]

        matches = sum(1 for kw in keywords if kw in issuer_lower)
        overlap_ratio = matches / len(keywords) if keywords else 0

        if overlap_ratio >= 0.7:
            return "aligned"
        elif overlap_ratio >= 0.3:
            return "partial"
        elif overlap_ratio > 0:
            return "not_aligned"
        else:
            return "unknown"
