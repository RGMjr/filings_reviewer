"""
Stage 6.5: LLM Presence Classifier (shadow mode).

Runs per-(segment, metric) LLM scoring via PresenceClassifierClient after
candidate_generation, before value_binding. Two scoring paths:

  keyword path  — segments that produced at least one MetricCandidate are
                  scored against their keyword-matched metric_ids.

  paraphrase path (Part E) — segments in whitelisted sections (MD&A,
                  Business, Risk Factors) that had NO keyword hit are
                  scored against the enrolled-metric set from
                  recall_augmentation.yaml, without requiring a keyword hit.
                  This is the mechanism for +5pt Tier-1 recall lift.

Shadow-mode invariant: this stage only writes to
``context.llm_presence_signals``. It never modifies ``context.candidates``,
``context.facts``, or ``context.presences``. MetricPresenceStage reads the
signals to populate ``MetricPresence.classifier_metadata`` but keyword/fact
evidence remains the authoritative presence signal. No new presence records
are created from LLM-only findings in shadow mode.

Gated by ``context.config.enable_llm_presence_classifier`` (defaults False).
When False the stage is a no-op and returns immediately.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from src.extraction_v2.models import LLMPresenceSignal

if TYPE_CHECKING:
    from src.extraction_v2.pipeline import PipelineContext, StageResult

logger = logging.getLogger(__name__)

# Minimum segment text length to bother classifying.
_MIN_SEGMENT_CHARS = 50


class LLMPresenceClassifierStage:
    """Stage 6.5 — LLM presence classifier in shadow mode.

    Accepts an optional pre-built ``client`` for dependency injection in
    tests. When ``None``, constructs ``PresenceClassifierClient`` lazily from
    the default config on first ``process()`` call.
    """

    def __init__(self, client: Any | None = None) -> None:
        self._client = client
        self._initialized_client: Any | None = None

    def _get_client(self) -> Any:
        if self._client is not None:
            return self._client
        if self._initialized_client is None:
            from src.llm.presence_classifier_client import PresenceClassifierClient

            self._initialized_client = PresenceClassifierClient()
        return self._initialized_client

    def process(self, context: PipelineContext) -> StageResult:
        from src.extraction_v2.pipeline import PipelineStage, StageResult

        start = datetime.now(UTC)

        # Defensive double-check: the stage is only registered in the pipeline
        # when the flag is on (pipeline.py:_setup_stages), so this branch is
        # unreachable in normal operation. Kept to protect callers that invoke
        # process() directly (e.g. tests or future orchestration paths).
        if not context.config.enable_llm_presence_classifier:
            return StageResult(
                stage=PipelineStage.LLM_PRESENCE_CLASSIFIER,
                success=True,
                duration_ms=int((datetime.now(UTC) - start).total_seconds() * 1000),
                items_processed=0,
                items_output=0,
            )

        try:
            client = self._get_client()
        except Exception as exc:
            logger.warning("LLMPresenceClassifierStage: client init failed: %s", exc)
            return StageResult(
                stage=PipelineStage.LLM_PRESENCE_CLASSIFIER,
                success=True,
                duration_ms=int((datetime.now(UTC) - start).total_seconds() * 1000),
                items_processed=0,
                items_output=0,
                warnings=[f"client init failed: {exc}"],
            )

        if not client.config.api_key:
            logger.warning("LLMPresenceClassifierStage: ANTHROPIC_API_KEY not set; skipping")
            return StageResult(
                stage=PipelineStage.LLM_PRESENCE_CLASSIFIER,
                success=True,
                duration_ms=int((datetime.now(UTC) - start).total_seconds() * 1000),
                items_processed=0,
                items_output=0,
                warnings=["ANTHROPIC_API_KEY not set"],
            )

        recall_cfg = client.config.recall_augmentation
        enrolled: frozenset[str] = recall_cfg.enrolled_metrics if recall_cfg else frozenset()
        section_whitelist: frozenset[str] = (
            recall_cfg.section_whitelist if recall_cfg else frozenset()
        )

        # Build segment lookup.
        segment_by_id = {s.segment_id: s for s in context.segments}

        # --- Keyword path ---
        # Group candidates by segment_id → set of metric_ids that fired.
        kw_seg_metrics: dict[str, set[str]] = defaultdict(set)
        for cand in context.candidates:
            seg_id = cand.source_locator.segment_id if cand.source_locator else None
            if seg_id:
                kw_seg_metrics[seg_id].add(cand.metric_id)

        signals: list[LLMPresenceSignal] = []
        errors: list[str] = []
        keyword_count = 0
        paraphrase_count = 0
        total_input_tokens = 0
        total_output_tokens = 0
        total_cache_read = 0
        total_cache_create = 0

        for seg_id, metric_ids in kw_seg_metrics.items():
            segment = segment_by_id.get(seg_id)
            if not segment or not segment.text or len(segment.text.strip()) < _MIN_SEGMENT_CHARS:
                continue
            # Only classify metrics that have a loaded prompt YAML.
            scoreable = [m for m in metric_ids if m in client.config.prompts]
            if not scoreable:
                continue
            try:
                sec_type = segment.section_type.value if segment.section_type else None
                classifications, seg_tokens = client.classify_segment(
                    segment.text, scoreable, section_type=sec_type
                )
                for sc in classifications:
                    signals.append(
                        LLMPresenceSignal(
                            segment_id=seg_id,
                            section_type=sec_type,
                            metric_id=sc.metric_id,
                            score=sc.score,
                            present=sc.present,
                            rationale=sc.rationale,
                            model=sc.model,
                            sonnet_fallback=sc.sonnet_fallback,
                            prompt_version=sc.prompt_version,
                            source="keyword",
                        )
                    )
                keyword_count += 1
                total_input_tokens += seg_tokens.get("input_tokens", 0)
                total_output_tokens += seg_tokens.get("output_tokens", 0)
                total_cache_read += seg_tokens.get("cache_read", 0)
                total_cache_create += seg_tokens.get("cache_create", 0)
            except Exception as exc:
                logger.warning(
                    "LLMPresenceClassifierStage: classify failed segment=%s metrics=%s: %s",
                    seg_id,
                    scoreable,
                    exc,
                )
                errors.append(f"segment {seg_id}: {exc}")

        # --- Paraphrase-recall path (Part E) ---
        # Score whitelisted-section segments that had NO keyword hit, against
        # the full enrolled-metric set. This is the source of recall lift.
        if enrolled and section_whitelist:
            enrolled_with_prompts = [m for m in sorted(enrolled) if m in client.config.prompts]
            if enrolled_with_prompts:
                for segment in context.segments:
                    if segment.segment_id in kw_seg_metrics:
                        continue  # Already scored in keyword path
                    if not segment.section_type:
                        continue
                    if segment.section_type.value not in section_whitelist:
                        continue
                    if not segment.text or len(segment.text.strip()) < _MIN_SEGMENT_CHARS:
                        continue
                    try:
                        sec_type = segment.section_type.value
                        classifications, seg_tokens = client.classify_segment(
                            segment.text, enrolled_with_prompts, section_type=sec_type
                        )
                        for sc in classifications:
                            signals.append(
                                LLMPresenceSignal(
                                    segment_id=segment.segment_id,
                                    section_type=sec_type,
                                    metric_id=sc.metric_id,
                                    score=sc.score,
                                    present=sc.present,
                                    rationale=sc.rationale,
                                    model=sc.model,
                                    sonnet_fallback=sc.sonnet_fallback,
                                    prompt_version=sc.prompt_version,
                                    source="paraphrase",
                                )
                            )
                        paraphrase_count += 1
                        total_input_tokens += seg_tokens.get("input_tokens", 0)
                        total_output_tokens += seg_tokens.get("output_tokens", 0)
                        total_cache_read += seg_tokens.get("cache_read", 0)
                        total_cache_create += seg_tokens.get("cache_create", 0)
                    except Exception as exc:
                        logger.warning(
                            "LLMPresenceClassifierStage: paraphrase classify failed segment=%s: %s",
                            segment.segment_id,
                            exc,
                        )
                        errors.append(f"paraphrase segment {segment.segment_id}: {exc}")

        context.llm_presence_signals = signals

        # Log disagreements: paraphrase-recall found a metric that keywords missed.
        if signals:
            _log_disagreements(signals, kw_seg_metrics, context.filing_id)

        duration_ms = int((datetime.now(UTC) - start).total_seconds() * 1000)
        logger.info(
            "LLMPresenceClassifierStage: filing_id=%s keyword_segs=%d "
            "paraphrase_segs=%d signals=%d errors=%d duration_ms=%d",
            context.filing_id,
            keyword_count,
            paraphrase_count,
            len(signals),
            len(errors),
            duration_ms,
        )

        return StageResult(
            stage=PipelineStage.LLM_PRESENCE_CLASSIFIER,
            success=True,
            duration_ms=duration_ms,
            items_processed=keyword_count + paraphrase_count,
            items_output=len(signals),
            errors=errors,
            metadata={
                "keyword_segments": keyword_count,
                "paraphrase_segments": paraphrase_count,
                "total_signals": len(signals),
                "error_count": len(errors),
                "total_input_tokens": total_input_tokens,
                "total_output_tokens": total_output_tokens,
                "total_cache_read": total_cache_read,
                "total_cache_create": total_cache_create,
            },
        )


def _log_disagreements(
    signals: list[LLMPresenceSignal],
    kw_seg_metrics: dict[str, set[str]],
    filing_id: int,
) -> None:
    """Log (metric, segment) pairs where LLM found presence but keywords didn't."""
    # Keyword-confirmed: (seg_id, metric_id) pairs where keyword fired.
    kw_pairs: set[tuple[str, str]] = set()
    for seg_id, metrics in kw_seg_metrics.items():
        for m in metrics:
            kw_pairs.add((seg_id, m))

    llm_only = [
        s
        for s in signals
        if s.present and s.source == "paraphrase" and (s.segment_id, s.metric_id) not in kw_pairs
    ]
    if llm_only:
        by_metric: dict[str, int] = defaultdict(int)
        for s in llm_only:
            by_metric[s.metric_id] += 1
        logger.info(
            "LLMPresenceClassifierStage: filing_id=%s llm_only_present=%d by_metric=%s",
            filing_id,
            len(llm_only),
            dict(sorted(by_metric.items())),
        )
