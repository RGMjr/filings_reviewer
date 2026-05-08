"""Unit + small integration tests for LLMPresenceClassifierStage.

The Anthropic SDK is mocked end-to-end via a fake ``PresenceClassifierClient``
implementation — these tests never make a network call.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from src.extraction_v2.models import (
    LLMPresenceSignal,
    MetricCandidate,
    MetricPresence,
    SectionType,
    Segment,
    SegmentType,
    SourceLocator,
    SourceType,
)
from src.extraction_v2.pipeline import (
    PipelineConfig,
    PipelineContext,
    PipelineStage,
)
from src.extraction_v2.stages.llm_presence_classifier import LLMPresenceClassifierStage
from src.extraction_v2.stages.metric_presence import MetricPresenceStage

# ---------------------------------------------------------------------------
# Fakes / fixtures
# ---------------------------------------------------------------------------


@dataclass
class _FakeRecallCfg:
    enrolled_metrics: frozenset[str] = field(default_factory=frozenset)
    section_whitelist: frozenset[str] = field(default_factory=frozenset)


@dataclass
class _FakeClassifierConfig:
    api_key: str | None = "test-key"
    recall_augmentation: _FakeRecallCfg | None = None
    prompts: dict[str, object] = field(default_factory=dict)


class _FakeSegmentClassification:
    """Mirrors src.llm.presence_classifier_client.SegmentClassification fields."""

    def __init__(
        self,
        metric_id: str,
        score: float,
        present: bool,
        rationale: str = "",
        model: str = "claude-haiku-4-5-20251001",
        sonnet_fallback: bool = False,
        prompt_version: str = "0.1.0-template",
    ) -> None:
        self.metric_id = metric_id
        self.score = score
        self.present = present
        self.rationale = rationale
        self.model = model
        self.sonnet_fallback = sonnet_fallback
        self.prompt_version = prompt_version


def _make_client(
    *,
    api_key: str | None = "test-key",
    enrolled: frozenset[str] | None = None,
    section_whitelist: frozenset[str] | None = None,
    prompts: set[str] | None = None,
    classify_fn=None,
) -> MagicMock:
    """Build a fake PresenceClassifierClient suitable for stage injection."""
    config = _FakeClassifierConfig(
        api_key=api_key,
        recall_augmentation=_FakeRecallCfg(
            enrolled_metrics=enrolled or frozenset(),
            section_whitelist=section_whitelist or frozenset(),
        ),
        prompts={m: object() for m in (prompts or set())},
    )
    client = MagicMock()
    client.config = config
    client.classify_segment = (
        MagicMock(side_effect=classify_fn) if classify_fn else MagicMock(return_value=([], {}))
    )
    return client


def _make_context(
    *,
    enable: bool = True,
    segments: list[Segment] | None = None,
    candidates: list[MetricCandidate] | None = None,
    llm_presence_concurrency: int = 1,
) -> PipelineContext:
    cfg = PipelineConfig(
        enable_llm_presence_classifier=enable,
        llm_presence_concurrency=llm_presence_concurrency,
    )
    ctx = PipelineContext(
        html_path=Path("/dev/null"),
        filing_id=42,
        config=cfg,
    )
    if segments:
        ctx.segments = list(segments)
    if candidates:
        ctx.candidates = list(candidates)
    return ctx


def _seg(text: str, *, section: SectionType = SectionType.MDA, sid: str | None = None) -> Segment:
    return Segment(
        segment_id=sid or f"seg-{abs(hash(text)) % 10_000}",
        text=text,
        segment_type=SegmentType.PARAGRAPH,
        section_type=section,
    )


def _candidate(metric_id: str, segment: Segment) -> MetricCandidate:
    return MetricCandidate(
        metric_id=metric_id,
        match_text=metric_id.replace("cm_", ""),
        source_locator=SourceLocator(segment_id=segment.segment_id),
        source_type=SourceType.TEXT,
        section_type=segment.section_type,
    )


# ---------------------------------------------------------------------------
# Stage gating
# ---------------------------------------------------------------------------


def test_stage_is_noop_when_flag_disabled() -> None:
    client = _make_client()
    stage = LLMPresenceClassifierStage(client=client)
    ctx = _make_context(enable=False, segments=[_seg("Net revenue retention was 120%.")])

    result = stage.process(ctx)

    assert result.success is True
    assert result.items_output == 0
    assert ctx.llm_presence_signals == []
    client.classify_segment.assert_not_called()


def test_stage_is_noop_when_api_key_missing() -> None:
    client = _make_client(api_key=None)
    stage = LLMPresenceClassifierStage(client=client)
    ctx = _make_context(segments=[_seg("Net revenue retention was 120%.")])

    result = stage.process(ctx)

    assert result.success is True
    assert "ANTHROPIC_API_KEY not set" in (result.warnings or [])
    assert ctx.llm_presence_signals == []
    client.classify_segment.assert_not_called()


# ---------------------------------------------------------------------------
# Stage metadata — token fields
# ---------------------------------------------------------------------------


def test_stage_metadata_includes_token_fields_from_classify_calls() -> None:
    """Token counts returned by classify_segment accumulate into StageResult.metadata."""
    seg = _seg("X" * 80, section=SectionType.MDA, sid="seg-t")

    def fake_classify(text, metric_ids, section_type=None):
        return (
            [_FakeSegmentClassification(metric_id=m, score=0.9, present=True) for m in metric_ids],
            {"input_tokens": 150, "output_tokens": 40, "cache_read": 30, "cache_create": 10},
        )

    client = _make_client(prompts={"cm_net_revenue_retention"}, classify_fn=fake_classify)
    stage = LLMPresenceClassifierStage(client=client)
    ctx = _make_context(
        segments=[seg],
        candidates=[_candidate("cm_net_revenue_retention", seg)],
    )

    result = stage.process(ctx)

    assert result.metadata["total_input_tokens"] == 150
    assert result.metadata["total_output_tokens"] == 40
    assert result.metadata["total_cache_read"] == 30
    assert result.metadata["total_cache_create"] == 10


def test_stage_metadata_accumulates_across_multiple_segments() -> None:
    """Tokens from multiple classify_segment calls are summed."""
    seg1 = _seg("A" * 80, section=SectionType.MDA, sid="seg-1")
    seg2 = _seg("B" * 80, section=SectionType.MDA, sid="seg-2")

    def fake_classify(text, metric_ids, section_type=None):
        return (
            [_FakeSegmentClassification(metric_id=m, score=0.9, present=True) for m in metric_ids],
            {"input_tokens": 100, "output_tokens": 20, "cache_read": 0, "cache_create": 0},
        )

    client = _make_client(prompts={"cm_net_revenue_retention"}, classify_fn=fake_classify)
    stage = LLMPresenceClassifierStage(client=client)
    ctx = _make_context(
        segments=[seg1, seg2],
        candidates=[
            _candidate("cm_net_revenue_retention", seg1),
            _candidate("cm_net_revenue_retention", seg2),
        ],
    )

    result = stage.process(ctx)

    assert result.metadata["total_input_tokens"] == 200  # 2 × 100
    assert result.metadata["total_output_tokens"] == 40  # 2 × 20


# ---------------------------------------------------------------------------
# Keyword path
# ---------------------------------------------------------------------------


def test_keyword_path_scores_each_segment_with_its_keyword_metrics() -> None:
    seg = _seg(
        "Our net revenue retention rate was 120% for fiscal year 2024." * 2,
        section=SectionType.MDA,
        sid="seg-1",
    )

    def fake_classify(text, metric_ids, section_type=None):
        return (
            [
                _FakeSegmentClassification(metric_id=m, score=0.9, present=True, rationale="r")
                for m in metric_ids
            ],
            {},
        )

    client = _make_client(prompts={"cm_net_revenue_retention"}, classify_fn=fake_classify)
    stage = LLMPresenceClassifierStage(client=client)
    ctx = _make_context(
        segments=[seg],
        candidates=[_candidate("cm_net_revenue_retention", seg)],
    )

    result = stage.process(ctx)

    assert result.success is True
    assert len(ctx.llm_presence_signals) == 1
    sig = ctx.llm_presence_signals[0]
    assert sig.metric_id == "cm_net_revenue_retention"
    assert sig.source == "keyword"
    assert sig.segment_id == "seg-1"
    assert sig.score == pytest.approx(0.9)
    client.classify_segment.assert_called_once()


def test_keyword_path_skips_metrics_without_loaded_prompts() -> None:
    seg = _seg("X" * 80, section=SectionType.MDA, sid="seg-1")
    client = _make_client(prompts={"cm_net_revenue_retention"})
    stage = LLMPresenceClassifierStage(client=client)
    ctx = _make_context(
        segments=[seg],
        candidates=[_candidate("cm_no_prompt_metric", seg)],
    )

    stage.process(ctx)

    assert ctx.llm_presence_signals == []
    client.classify_segment.assert_not_called()


def test_keyword_path_skips_short_segments() -> None:
    seg = _seg("short", section=SectionType.MDA, sid="seg-1")
    client = _make_client(prompts={"cm_net_revenue_retention"})
    stage = LLMPresenceClassifierStage(client=client)
    ctx = _make_context(
        segments=[seg],
        candidates=[_candidate("cm_net_revenue_retention", seg)],
    )

    stage.process(ctx)

    assert ctx.llm_presence_signals == []
    client.classify_segment.assert_not_called()


def test_keyword_path_continues_after_classify_error() -> None:
    seg_ok = _seg("X" * 80, section=SectionType.MDA, sid="seg-ok")
    seg_bad = _seg("Y" * 80, section=SectionType.MDA, sid="seg-bad")

    def flaky(text, metric_ids, section_type=None):
        if "Y" in text[:5]:
            raise RuntimeError("rate limit")
        return ([_FakeSegmentClassification("cm_net_revenue_retention", 0.5, True)], {})

    client = _make_client(prompts={"cm_net_revenue_retention"}, classify_fn=flaky)
    stage = LLMPresenceClassifierStage(client=client)
    ctx = _make_context(
        segments=[seg_ok, seg_bad],
        candidates=[
            _candidate("cm_net_revenue_retention", seg_ok),
            _candidate("cm_net_revenue_retention", seg_bad),
        ],
    )

    result = stage.process(ctx)

    assert len(ctx.llm_presence_signals) == 1
    assert result.errors  # one error logged
    assert result.success is True


# ---------------------------------------------------------------------------
# Paraphrase path (Part E)
# ---------------------------------------------------------------------------


def test_paraphrase_path_scans_whitelisted_sections_without_keyword_hits() -> None:
    seg = _seg(
        "We had strong customer retention this period." * 3,
        section=SectionType.MDA,
        sid="seg-mda",
    )

    def fake_classify(text, metric_ids, section_type=None):
        return ([_FakeSegmentClassification(m, 0.8, True) for m in metric_ids], {})

    client = _make_client(
        prompts={"cm_net_revenue_retention"},
        enrolled=frozenset({"cm_net_revenue_retention"}),
        section_whitelist=frozenset({"mda"}),
        classify_fn=fake_classify,
    )
    stage = LLMPresenceClassifierStage(client=client)
    ctx = _make_context(segments=[seg])  # no candidates → pure paraphrase path

    stage.process(ctx)

    assert len(ctx.llm_presence_signals) == 1
    sig = ctx.llm_presence_signals[0]
    assert sig.source == "paraphrase"
    assert sig.metric_id == "cm_net_revenue_retention"


def test_paraphrase_path_skips_segments_outside_whitelist() -> None:
    seg = _seg(
        "Some boilerplate disclosure text..." * 3,
        section=SectionType.UNKNOWN,
        sid="seg-other",
    )
    client = _make_client(
        prompts={"cm_net_revenue_retention"},
        enrolled=frozenset({"cm_net_revenue_retention"}),
        section_whitelist=frozenset({"mda", "business", "risk_factors"}),
        classify_fn=lambda *a, **kw: (
            [_FakeSegmentClassification("cm_net_revenue_retention", 0.9, True)],
            {},
        ),
    )
    stage = LLMPresenceClassifierStage(client=client)
    ctx = _make_context(segments=[seg])

    stage.process(ctx)

    assert ctx.llm_presence_signals == []
    client.classify_segment.assert_not_called()


def test_paraphrase_path_skips_segments_already_in_keyword_pass() -> None:
    seg = _seg("X" * 80, section=SectionType.MDA, sid="seg-shared")
    call_log: list[tuple[str, ...]] = []

    def fake_classify(text, metric_ids, section_type=None):
        call_log.append(tuple(sorted(metric_ids)))
        return ([_FakeSegmentClassification(m, 0.7, True) for m in metric_ids], {})

    client = _make_client(
        prompts={"cm_net_revenue_retention", "cm_revenue_concentration"},
        enrolled=frozenset({"cm_revenue_concentration"}),
        section_whitelist=frozenset({"mda"}),
        classify_fn=fake_classify,
    )
    stage = LLMPresenceClassifierStage(client=client)
    ctx = _make_context(
        segments=[seg],
        candidates=[_candidate("cm_net_revenue_retention", seg)],
    )

    stage.process(ctx)

    assert len(call_log) == 1  # only keyword pass; no paraphrase pass on same segment
    assert all(s.source == "keyword" for s in ctx.llm_presence_signals)


# ---------------------------------------------------------------------------
# Integration with MetricPresenceStage (shadow mode)
# ---------------------------------------------------------------------------


def _run_metric_presence_with_signals(
    *,
    facts_metric: str | None,
    signals: list[LLMPresenceSignal],
) -> list[MetricPresence]:
    cfg = PipelineConfig()
    ctx = PipelineContext(html_path=Path("/dev/null"), filing_id=1, config=cfg)
    if facts_metric:
        from src.extraction_v2.models import MetricFact

        fact = MetricFact(
            fact_id="f1",
            canonical_metric_id=facts_metric,
            confidence=0.85,
            source_locator=SourceLocator(segment_id="seg-1"),
        )
        ctx.facts = [fact]
    ctx.llm_presence_signals = list(signals)  # type: ignore[assignment]
    MetricPresenceStage().process(ctx)
    return list(ctx.presences)


def test_metric_presence_attaches_classifier_metadata_to_keyword_records() -> None:
    sig = LLMPresenceSignal(
        segment_id="seg-1",
        section_type="mda",
        metric_id="cm_net_revenue_retention",
        score=0.9,
        present=True,
        rationale="found NRR",
        model="haiku",
        sonnet_fallback=False,
        prompt_version="v1",
        source="keyword",
    )

    out = _run_metric_presence_with_signals(
        facts_metric="cm_net_revenue_retention",
        signals=[sig],
    )

    assert len(out) == 1
    rec = out[0]
    assert rec.canonical_metric_id == "cm_net_revenue_retention"
    assert rec.detected_at_stage == PipelineStage.FACT_CONSTRUCTION.value
    assert rec.score == pytest.approx(0.85)  # fact confidence — UNCHANGED by LLM
    assert rec.classifier_metadata is not None
    assert len(rec.classifier_metadata["signals"]) == 1
    assert rec.classifier_metadata["signals"][0]["source"] == "keyword"


def test_metric_presence_creates_record_for_paraphrase_only_signal() -> None:
    sig = LLMPresenceSignal(
        segment_id="seg-2",
        section_type="mda",
        metric_id="cm_revenue_concentration",
        score=0.78,
        present=True,
        rationale="paraphrase match",
        model="haiku",
        sonnet_fallback=False,
        prompt_version="v1",
        source="paraphrase",
    )

    out = _run_metric_presence_with_signals(facts_metric=None, signals=[sig])

    assert len(out) == 1
    rec = out[0]
    assert rec.canonical_metric_id == "cm_revenue_concentration"
    assert rec.detected_at_stage == PipelineStage.LLM_PRESENCE_CLASSIFIER.value
    assert rec.score == pytest.approx(0.78)
    assert rec.advisory_value_count == 0
    assert rec.advisory_fact_ids == []
    assert "seg-2" in rec.evidence_segment_ids
    assert rec.classifier_metadata is not None
    assert rec.classifier_metadata["signals"][0]["source"] == "paraphrase"


def test_metric_presence_skips_paraphrase_negative_signals() -> None:
    sig = LLMPresenceSignal(
        segment_id="seg-2",
        section_type="mda",
        metric_id="cm_revenue_concentration",
        score=0.20,
        present=False,  # below threshold
        rationale="not present",
        model="haiku",
        sonnet_fallback=False,
        prompt_version="v1",
        source="paraphrase",
    )

    out = _run_metric_presence_with_signals(facts_metric=None, signals=[sig])

    assert out == []  # no record created from negative-only paraphrase signals


def test_metric_presence_discards_keyword_signals_without_facts() -> None:
    """LLM keyword-pass signals on metrics with no facts/definitions are discarded.
    The keyword path itself produced no facts; LLM signals do not promote them."""
    sig = LLMPresenceSignal(
        segment_id="seg-3",
        section_type="mda",
        metric_id="cm_lifetime_value_per_customer",
        score=0.95,
        present=True,
        rationale="strong",
        model="haiku",
        sonnet_fallback=False,
        prompt_version="v1",
        source="keyword",
    )

    out = _run_metric_presence_with_signals(facts_metric=None, signals=[sig])

    assert out == []


# ---------------------------------------------------------------------------
# Small integration test: stage + MetricPresenceStage on a single MD&A segment
# ---------------------------------------------------------------------------


def test_integration_single_mda_segment_full_path() -> None:
    """A single MD&A segment, no keyword candidates, paraphrase-recall finds NRR."""
    seg = _seg(
        "We measure customer health by tracking how much existing customers spend "
        "year over year, including upsells and excluding churn." * 2,
        section=SectionType.MDA,
        sid="seg-mda-only",
    )

    def fake_classify(text, metric_ids, section_type=None):
        # Paraphrase finds NRR present, gross retention absent.
        out = []
        for m in metric_ids:
            if m == "cm_net_revenue_retention":
                out.append(_FakeSegmentClassification(m, 0.82, True, "found"))
            else:
                out.append(_FakeSegmentClassification(m, 0.10, False, "miss"))
        return out, {}

    client = _make_client(
        prompts={"cm_net_revenue_retention", "cm_gross_revenue_retention"},
        enrolled=frozenset({"cm_net_revenue_retention", "cm_gross_revenue_retention"}),
        section_whitelist=frozenset({"mda"}),
        classify_fn=fake_classify,
    )
    stage = LLMPresenceClassifierStage(client=client)
    ctx = _make_context(segments=[seg])

    stage.process(ctx)
    MetricPresenceStage().process(ctx)

    presences_by_metric = {p.canonical_metric_id: p for p in ctx.presences}
    assert "cm_net_revenue_retention" in presences_by_metric
    assert "cm_gross_revenue_retention" not in presences_by_metric  # below threshold

    nrr = presences_by_metric["cm_net_revenue_retention"]
    assert nrr.detected_at_stage == PipelineStage.LLM_PRESENCE_CLASSIFIER.value
    assert nrr.score == pytest.approx(0.82)
    assert nrr.classifier_metadata is not None


# ---------------------------------------------------------------------------
# Concurrency
# ---------------------------------------------------------------------------


def test_concurrency_produces_same_results_as_serial() -> None:
    """concurrency=4 must produce the same signals as concurrency=1 (default).

    Order of insertion into ``signals`` is preserved across both modes so
    log determinism and downstream max-score aggregation are unchanged.
    """
    # 8 segments, all paraphrase-eligible (MDA, no keyword candidates).
    segs = [_seg("X" * 80, section=SectionType.MDA, sid=f"seg-{i}") for i in range(8)]

    def fake_classify(text, metric_ids, section_type=None):
        # The fake doesn't know which segment it's scoring directly; encode
        # the score in the segment text length variant. Simpler: same score
        # for all metrics in this call, derived from text hash.
        score = 0.10 + 0.10 * (sum(text[:5].encode()) % 8)
        return (
            [_FakeSegmentClassification(m, score=score, present=score >= 0.5) for m in metric_ids],
            {"input_tokens": 100, "output_tokens": 20, "cache_read": 0, "cache_create": 0},
        )

    enrolled = frozenset({"cm_net_revenue_retention"})
    section_whitelist = frozenset({"mda"})
    prompts = {"cm_net_revenue_retention"}

    # Serial baseline.
    serial_client = _make_client(
        prompts=prompts,
        enrolled=enrolled,
        section_whitelist=section_whitelist,
        classify_fn=fake_classify,
    )
    serial_ctx = _make_context(segments=segs)
    LLMPresenceClassifierStage(client=serial_client).process(serial_ctx)
    serial_signals = sorted(
        ((s.segment_id, s.metric_id, s.score, s.present) for s in serial_ctx.llm_presence_signals),
    )

    # Concurrent run.
    concurrent_client = _make_client(
        prompts=prompts,
        enrolled=enrolled,
        section_whitelist=section_whitelist,
        classify_fn=fake_classify,
    )
    concurrent_ctx = _make_context(segments=segs, llm_presence_concurrency=4)
    LLMPresenceClassifierStage(client=concurrent_client).process(concurrent_ctx)
    concurrent_signals = sorted(
        (
            (s.segment_id, s.metric_id, s.score, s.present)
            for s in concurrent_ctx.llm_presence_signals
        ),
    )

    assert serial_signals == concurrent_signals
    assert len(serial_signals) == 8
    # Output order is preserved (submission order, regardless of completion order).
    serial_seg_order = [s.segment_id for s in serial_ctx.llm_presence_signals]
    concurrent_seg_order = [s.segment_id for s in concurrent_ctx.llm_presence_signals]
    assert serial_seg_order == concurrent_seg_order
