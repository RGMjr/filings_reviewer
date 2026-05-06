"""
Stage 12: Metric Presence Aggregation.

Final stage of the V2 pipeline. Aggregates text-side signals —
deduplicated facts (text / html_table / ocr_table) and definitions —
into one ``MetricPresence`` record per ``(doc, canonical_metric_id)``
pair, persisted to ``v2_text_metric_presence``.

Chart-derived presence is owned by the image pipeline at per-image grain
(``v2_image_assets.detected_metrics`` JSONB today; ``v2_image_metric_presence``
under image-review Wave 2). Unified doc-grain presence is exposed via the
``v_doc_metric_presence`` view (UNION of text + image). See
``docs/operations/text-pipeline-presence-pivot-plan.md`` — agreement (5):
per-table ownership, no in-stage cross-write.

Primary scoring surface for the text-side Tier 1 regression gate under
the text-presence pivot.

Design invariants (must hold; downstream PRs depend on them):

- One record per ``(doc_id, canonical_metric_id)``. Duplicates are an error
  upstream; ``_persist_presence_in_tx`` upsert would otherwise collapse
  them silently.
- ``score`` is the MAX confidence across all contributing text signals.
- ``evidence_segment_ids`` is the union of segment IDs from contributing
  facts (via ``fact.source_locator.segment_id``) and from definitions
  (``definition_segment_id`` / ``methodology_segment_id``).
- ``advisory_fact_ids`` lists the fact IDs that contributed. Empty when
  presence comes solely from definitions.
- ``advisory_value_count`` is the count of contributing facts (not unique
  values). Rough disclosure-depth signal for downstream UI.

LLM presence-classifier integration (shadow mode, PR3b):

- Reads ``context.llm_presence_signals`` (written by
  ``LLMPresenceClassifierStage`` when ``presence_classifier_enabled`` is on).
- For metrics already in the keyword-confirmed accumulator: signals are
  attached as ``classifier_metadata`` only. ``score`` and ``detected_at_stage``
  are unchanged — keyword path remains authoritative.
- For metrics with at least one ``source="paraphrase"`` and ``present=True``
  signal AND no facts/definitions: a new presence record is created with
  ``detected_at_stage='llm_presence_classifier'``. This is the +5pt recall
  lift mechanism, kept distinguishable so the keyword-only baseline can be
  re-derived in SQL via ``WHERE detected_at_stage <> 'llm_presence_classifier'``.
- Keyword-pass LLM signals on metrics with no facts/definitions are
  discarded — they would create records that the keyword path itself
  rejected.

The stage never mutates ``context.facts`` / ``context.definitions`` — it
only reads them and writes ``context.presences``.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from src.extraction_v2.models import LLMPresenceSignal, MetricPresence

if TYPE_CHECKING:
    from src.extraction_v2.pipeline import PipelineContext, StageResult

logger = logging.getLogger(__name__)


# Score assigned to definition-only presence when no fact carries a
# canonical_metric_id. Facts always carry ``confidence``; definition-only
# presence is weaker than a value-bearing fact, so we floor it at 0.5.
_DEFINITION_ONLY_PRESENCE_SCORE = 0.5


class MetricPresenceStage:
    """Aggregate per-(doc, metric) text-presence records from facts + definitions."""

    def process(self, context: PipelineContext) -> StageResult:
        from src.extraction_v2.pipeline import PipelineStage, StageResult

        start_time = datetime.now(UTC)

        # Per-metric accumulator.
        # Keys are canonical_metric_id; values carry aggregated score,
        # segment-ID set, fact-ID list, fact count, and the stage that first
        # surfaced the metric (for downstream diagnostics).
        accumulator: dict[str, _Accumulator] = {}

        # Source 1: deduplicated facts (falls back to raw facts if dedup
        # hasn't populated yet — mirrors pipeline.process() output_facts logic).
        facts = (
            context.deduplicated_facts if context.deduplicated_facts is not None else context.facts
        )
        for fact in facts:
            if not fact.canonical_metric_id:
                continue
            acc = accumulator.setdefault(
                fact.canonical_metric_id,
                _Accumulator(first_stage=PipelineStage.FACT_CONSTRUCTION.value),
            )
            acc.score = max(acc.score, float(fact.confidence))
            acc.advisory_value_count += 1
            acc.fact_ids.append(fact.fact_id)
            seg_id = fact.source_locator.segment_id if fact.source_locator else None
            if seg_id:
                acc.segment_ids.add(seg_id)

        # Source 2: definitions (weaker signal; contributes only when
        # no stronger signal exists, but always adds evidence segment IDs).
        # Chart-derived presence is owned by the image pipeline and surfaces
        # via v_doc_metric_presence — see module docstring.
        for definition in context.definitions:
            if not definition.canonical_metric_id:
                continue
            acc = accumulator.setdefault(
                definition.canonical_metric_id,
                _Accumulator(first_stage=PipelineStage.DEFINITION_EXTRACTION.value),
            )
            acc.score = max(acc.score, _DEFINITION_ONLY_PRESENCE_SCORE)
            if definition.definition_segment_id:
                acc.segment_ids.add(definition.definition_segment_id)
            if definition.methodology_segment_id:
                acc.segment_ids.add(definition.methodology_segment_id)

        # Source 3 (shadow mode): LLM presence-classifier signals.
        # Group by metric_id. Two cases:
        #   (a) metric already has a keyword-confirmed accumulator entry
        #       → attach signals; do NOT touch score / first_stage.
        #   (b) metric has only paraphrase-positive signals (LLM found a
        #       presence keywords missed) → create a new accumulator entry
        #       with first_stage='llm_presence_classifier' so the record
        #       is filterable from keyword-only baseline queries.
        # Keyword-pass signals on metrics with no facts/definitions are
        # discarded (no record created) — keyword path is authoritative for
        # what the keyword pipeline produced.
        llm_signals: list[LLMPresenceSignal] = list(
            getattr(context, "llm_presence_signals", []) or []
        )
        llm_by_metric: dict[str, list[LLMPresenceSignal]] = defaultdict(list)
        for sig in llm_signals:
            llm_by_metric[sig.metric_id].append(sig)

        paraphrase_only_count = 0
        for metric_id, sigs in llm_by_metric.items():
            existing = accumulator.get(metric_id)
            if existing is not None:
                existing.llm_signals.extend(sigs)
                continue
            paraphrase_present = [s for s in sigs if s.source == "paraphrase" and s.present]
            if not paraphrase_present:
                continue
            acc = _Accumulator(first_stage=PipelineStage.LLM_PRESENCE_CLASSIFIER.value)
            acc.score = max(s.score for s in paraphrase_present)
            for s in paraphrase_present:
                if s.segment_id:
                    acc.segment_ids.add(s.segment_id)
            acc.llm_signals.extend(sigs)
            accumulator[metric_id] = acc
            paraphrase_only_count += 1

        context.presences = [
            MetricPresence(
                canonical_metric_id=metric_id,
                score=acc.score,
                detected_at_stage=acc.first_stage,
                evidence_segment_ids=sorted(acc.segment_ids),
                advisory_value_count=acc.advisory_value_count,
                advisory_fact_ids=list(acc.fact_ids),
                classifier_metadata=_build_classifier_metadata(acc.llm_signals)
                if acc.llm_signals
                else None,
            )
            for metric_id, acc in sorted(accumulator.items())
        ]

        duration_ms = int((datetime.now(UTC) - start_time).total_seconds() * 1000)
        logger.info(
            "MetricPresenceStage: doc_id=%s metrics_present=%s fact_contributors=%s "
            "paraphrase_only_presences=%d llm_signals=%d",
            context.filing_id,
            len(context.presences),
            sum(p.advisory_value_count for p in context.presences),
            paraphrase_only_count,
            len(llm_signals),
        )

        return StageResult(
            stage=PipelineStage.METRIC_PRESENCE,
            success=True,
            duration_ms=duration_ms,
            items_processed=len(facts) + len(context.definitions),
            items_output=len(context.presences),
            metadata={
                "metrics_present": len(context.presences),
                "fact_contributors": sum(p.advisory_value_count for p in context.presences),
                "definition_only_presences": sum(
                    1 for p in context.presences if p.advisory_value_count == 0
                ),
                "paraphrase_only_presences": paraphrase_only_count,
                "llm_signals_seen": len(llm_signals),
            },
        )


class _Accumulator:
    """Mutable per-metric aggregator used only within ``MetricPresenceStage``."""

    __slots__ = (
        "score",
        "first_stage",
        "segment_ids",
        "fact_ids",
        "advisory_value_count",
        "llm_signals",
    )

    def __init__(self, first_stage: str) -> None:
        self.score: float = 0.0
        self.first_stage: str = first_stage
        self.segment_ids: set[str] = set()
        self.fact_ids: list[str] = []
        self.advisory_value_count: int = 0
        self.llm_signals: list[LLMPresenceSignal] = []


def _build_classifier_metadata(signals: list[LLMPresenceSignal]) -> dict:
    """Serialize LLM signals for v2_text_metric_presence.classifier_metadata.

    Output: ``{"signals": [<per-signal dict>, ...]}``. Per-signal dict carries
    segment_id, source ("keyword"/"paraphrase"), score, present, model,
    sonnet_fallback, prompt_version, rationale. ``rationale`` is truncated to
    240 chars to keep JSONB row size bounded.
    """
    return {
        "signals": [
            {
                "segment_id": s.segment_id,
                "section_type": s.section_type,
                "source": s.source,
                "score": s.score,
                "present": s.present,
                "model": s.model,
                "sonnet_fallback": s.sonnet_fallback,
                "prompt_version": s.prompt_version,
                "rationale": (s.rationale or "")[:240],
            }
            for s in signals
        ],
    }
