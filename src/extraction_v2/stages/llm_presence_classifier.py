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
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from src.extraction_v2.models import LLMPresenceSignal

if TYPE_CHECKING:
    from src.extraction_v2.pipeline import PipelineContext, StageResult

logger = logging.getLogger(__name__)

# Minimum segment text length to bother classifying.
_MIN_SEGMENT_CHARS = 50


@dataclass(frozen=True)
class _ClassifyTask:
    """One unit of work for ThreadPoolExecutor: one segment × one metric set."""

    segment_id: str
    text: str
    metric_ids: list[str]
    section_type: str | None
    source: str  # "keyword" | "paraphrase"


@dataclass
class _ClassifyResult:
    """Output of one classify task. Either signals are populated or error_msg is."""

    task: _ClassifyTask
    signals: list[LLMPresenceSignal]
    tokens: dict[str, int]
    error_msg: str | None = None


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

        # --- Build task list (both paths) ---
        tasks: list[_ClassifyTask] = []

        # Keyword path: segments with at least one MetricCandidate.
        for seg_id, metric_ids in kw_seg_metrics.items():
            segment = segment_by_id.get(seg_id)
            if not segment or not segment.text or len(segment.text.strip()) < _MIN_SEGMENT_CHARS:
                continue
            # Only classify metrics that have a loaded prompt YAML.
            scoreable = [m for m in metric_ids if m in client.config.prompts]
            if not scoreable:
                continue
            sec_type = segment.section_type.value if segment.section_type else None
            tasks.append(
                _ClassifyTask(
                    segment_id=seg_id,
                    text=segment.text,
                    metric_ids=scoreable,
                    section_type=sec_type,
                    source="keyword",
                )
            )
        keyword_count = len(tasks)

        # Paraphrase-recall path (Part E): whitelisted-section segments
        # without a keyword hit, scored against the enrolled-metric set.
        if enrolled and section_whitelist:
            enrolled_with_prompts = [m for m in sorted(enrolled) if m in client.config.prompts]
            if enrolled_with_prompts:
                for segment in context.segments:
                    if segment.segment_id in kw_seg_metrics:
                        continue
                    if not segment.section_type:
                        continue
                    if segment.section_type.value not in section_whitelist:
                        continue
                    if not segment.text or len(segment.text.strip()) < _MIN_SEGMENT_CHARS:
                        continue
                    tasks.append(
                        _ClassifyTask(
                            segment_id=segment.segment_id,
                            text=segment.text,
                            metric_ids=enrolled_with_prompts,
                            section_type=segment.section_type.value,
                            source="paraphrase",
                        )
                    )
        paraphrase_count = len(tasks) - keyword_count

        # --- Execute tasks (concurrent if config.llm_presence_concurrency > 1) ---
        # Each classify_segment call is I/O-bound (Anthropic API), so threads
        # work without GIL contention. Anthropic's prompt cache is server-side
        # and benefits from concurrent reads on the same prefix.
        concurrency = max(1, int(getattr(context.config, "llm_presence_concurrency", 1)))
        results = _execute_tasks(tasks, client, concurrency)

        signals: list[LLMPresenceSignal] = []
        errors: list[str] = []
        total_input_tokens = 0
        total_output_tokens = 0
        total_cache_read = 0
        total_cache_create = 0
        for r in results:
            if r.error_msg:
                logger.warning(
                    "LLMPresenceClassifierStage: %s classify failed segment=%s: %s",
                    r.task.source,
                    r.task.segment_id,
                    r.error_msg,
                )
                errors.append(f"{r.task.source} segment {r.task.segment_id}: {r.error_msg}")
                continue
            signals.extend(r.signals)
            total_input_tokens += r.tokens.get("input_tokens", 0)
            total_output_tokens += r.tokens.get("output_tokens", 0)
            total_cache_read += r.tokens.get("cache_read", 0)
            total_cache_create += r.tokens.get("cache_create", 0)

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


def _classify_one(task: _ClassifyTask, client: Any) -> _ClassifyResult:
    """Run one classify_segment call and convert to LLMPresenceSignal list.

    Pure function — safe to call from worker threads. Captures any exception
    in ``error_msg`` so the orchestrator can log + continue.
    """
    try:
        classifications, seg_tokens = client.classify_segment(
            task.text, task.metric_ids, section_type=task.section_type
        )
    except Exception as exc:  # noqa: BLE001 — error captured per-task
        return _ClassifyResult(task=task, signals=[], tokens={}, error_msg=str(exc))

    signals = [
        LLMPresenceSignal(
            segment_id=task.segment_id,
            section_type=task.section_type,
            metric_id=sc.metric_id,
            score=sc.score,
            present=sc.present,
            rationale=sc.rationale,
            model=sc.model,
            sonnet_fallback=sc.sonnet_fallback,
            prompt_version=sc.prompt_version,
            source=task.source,
        )
        for sc in classifications
    ]
    return _ClassifyResult(task=task, signals=signals, tokens=seg_tokens)


def _execute_tasks(
    tasks: list[_ClassifyTask],
    client: Any,
    concurrency: int,
) -> list[_ClassifyResult]:
    """Run all tasks; returns results in submission order.

    ``concurrency=1`` runs serially (single-threaded). ``concurrency>1`` uses
    a ThreadPoolExecutor; results are ordered to match ``tasks`` input order
    so log determinism is preserved.
    """
    if not tasks:
        return []
    if concurrency <= 1:
        return [_classify_one(t, client) for t in tasks]
    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        futures = [pool.submit(_classify_one, t, client) for t in tasks]
        return [f.result() for f in futures]


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
