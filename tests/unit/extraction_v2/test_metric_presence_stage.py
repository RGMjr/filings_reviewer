"""
Unit tests for MetricPresenceStage.

Contract under the text-presence pivot: produce one MetricPresence record
per (doc, metric_id) with max score across contributing signals, union of
evidence segment IDs, and fact_id list for facts that contributed.
"""

from __future__ import annotations

import uuid
from datetime import date
from pathlib import Path

from src.extraction_v2.models import (
    ChartData,
    ChartSeries,
    ChartType,
    DataPoint,
    DetectedMetric,
    EvidencePack,
    ExtractionMethod,
    ImageAsset,
    ImageClassification,
    MetricDefinition,
    MetricFact,
    PeriodType,
    ReviewStatus,
    SourceLocator,
    SourceType,
    Unit,
)
from src.extraction_v2.pipeline import PipelineConfig, PipelineContext, PipelineStage
from src.extraction_v2.stages.metric_presence import MetricPresenceStage


def _make_context(
    *,
    facts: list[MetricFact] | None = None,
    dedup: list[MetricFact] | None = None,
    images: list[ImageAsset] | None = None,
    definitions: list[MetricDefinition] | None = None,
) -> PipelineContext:
    ctx = PipelineContext(
        html_path=Path("/test/filing.html"),
        filing_id=42,
        config=PipelineConfig(),
        document_date=date(2025, 1, 1),
    )
    ctx.facts = facts or []
    ctx.deduplicated_facts = dedup
    ctx.images = images or []
    ctx.definitions = definitions or []
    return ctx


def _fact(
    metric_id: str,
    *,
    confidence: float = 0.8,
    segment_id: str | None = None,
    fact_id: str | None = None,
) -> MetricFact:
    return MetricFact(
        fact_id=fact_id or str(uuid.uuid4()),
        doc_id="42",
        canonical_metric_id=metric_id,
        value=100.0,
        value_raw="100",
        unit=Unit.COUNT,
        period_type=PeriodType.ANNUAL,
        period_start=date(2024, 1, 1),
        period_end=date(2024, 12, 31),
        source_type=SourceType.TEXT,
        source_locator=SourceLocator(segment_id=segment_id),
        evidence_pack=EvidencePack(snippet_html="<p>100</p>"),
        confidence=confidence,
        extraction_method=ExtractionMethod.EXACT_MATCH,
        review_status=ReviewStatus.PENDING_REVIEW,
    )


def _chart_image(metrics: list[tuple[str, float]]) -> ImageAsset:
    return ImageAsset(
        img_id=str(uuid.uuid4()),
        classification=ImageClassification.CHART,
        chart_data=ChartData(
            chart_type=ChartType.BAR,
            series=[ChartSeries(name="x", points=[DataPoint(x="a", y=1.0)])],
        ),
        processed=True,
        confidence=0.9,
        relevance_score=0.9,
        detected_metrics=[DetectedMetric(metric_id=m, score=s) for m, s in metrics],
    )


class TestMetricPresenceStage:
    def test_empty_context_emits_zero_presences(self) -> None:
        ctx = _make_context()
        MetricPresenceStage().process(ctx)
        assert ctx.presences == []

    def test_facts_aggregated_one_row_per_metric(self) -> None:
        # Two facts for same metric, different segments and confidences.
        f1 = _fact("cm_new_customers_acquired", confidence=0.6, segment_id="seg-1")
        f2 = _fact("cm_new_customers_acquired", confidence=0.9, segment_id="seg-2")
        ctx = _make_context(dedup=[f1, f2])

        MetricPresenceStage().process(ctx)

        assert len(ctx.presences) == 1
        p = ctx.presences[0]
        assert p.canonical_metric_id == "cm_new_customers_acquired"
        assert p.score == 0.9  # max
        assert p.advisory_value_count == 2
        assert set(p.advisory_fact_ids) == {f1.fact_id, f2.fact_id}
        assert set(p.evidence_segment_ids) == {"seg-1", "seg-2"}
        assert p.detected_at_stage == PipelineStage.FACT_CONSTRUCTION.value

    def test_prefers_deduplicated_facts_when_populated(self) -> None:
        raw = _fact("cm_a", confidence=0.5, segment_id="seg-raw")
        dedup = _fact("cm_a", confidence=0.7, segment_id="seg-dedup")
        ctx = _make_context(facts=[raw], dedup=[dedup])

        MetricPresenceStage().process(ctx)

        assert len(ctx.presences) == 1
        # Dedup fact used, not raw
        assert ctx.presences[0].score == 0.7
        assert ctx.presences[0].evidence_segment_ids == ["seg-dedup"]

    def test_falls_back_to_raw_facts_when_dedup_not_run(self) -> None:
        raw = _fact("cm_a", confidence=0.5, segment_id="seg-raw")
        ctx = _make_context(facts=[raw], dedup=None)

        MetricPresenceStage().process(ctx)

        assert len(ctx.presences) == 1
        assert ctx.presences[0].score == 0.5

    def test_chart_detected_metrics_contribute(self) -> None:
        img = _chart_image([("cm_revenue_by_cohort", 0.85)])
        ctx = _make_context(images=[img])

        MetricPresenceStage().process(ctx)

        assert len(ctx.presences) == 1
        p = ctx.presences[0]
        assert p.canonical_metric_id == "cm_revenue_by_cohort"
        assert p.score == 0.85
        assert p.advisory_value_count == 0  # chart-only, no text facts
        assert p.advisory_fact_ids == []
        assert p.evidence_segment_ids == []  # chart evidence lives on image
        assert p.detected_at_stage == PipelineStage.CHART_FACT_BRIDGE.value

    def test_fact_and_chart_merge_into_single_presence(self) -> None:
        # Chart detects metric at 0.7; text fact independently binds at 0.9.
        fact = _fact("cm_revenue_by_cohort", confidence=0.9, segment_id="seg-1")
        img = _chart_image([("cm_revenue_by_cohort", 0.7)])
        ctx = _make_context(dedup=[fact], images=[img])

        MetricPresenceStage().process(ctx)

        assert len(ctx.presences) == 1
        p = ctx.presences[0]
        assert p.score == 0.9  # max of fact + chart
        assert p.advisory_value_count == 1
        assert p.advisory_fact_ids == [fact.fact_id]
        assert p.evidence_segment_ids == ["seg-1"]
        # detected_at_stage comes from whoever seeded the accumulator first
        assert p.detected_at_stage == PipelineStage.FACT_CONSTRUCTION.value

    def test_definition_alone_emits_presence_at_floor_score(self) -> None:
        defn = MetricDefinition(
            canonical_metric_id="cm_net_revenue_retention",
            doc_id="42",
            definition_text="Net revenue retention measures...",
            definition_segment_id="seg-def",
        )
        ctx = _make_context(definitions=[defn])

        MetricPresenceStage().process(ctx)

        assert len(ctx.presences) == 1
        p = ctx.presences[0]
        assert p.canonical_metric_id == "cm_net_revenue_retention"
        assert p.score == 0.5  # _DEFINITION_ONLY_PRESENCE_SCORE
        assert p.evidence_segment_ids == ["seg-def"]
        assert p.advisory_value_count == 0

    def test_definition_does_not_downgrade_stronger_fact_score(self) -> None:
        fact = _fact("cm_a", confidence=0.95, segment_id="seg-f")
        defn = MetricDefinition(
            canonical_metric_id="cm_a",
            doc_id="42",
            definition_text="cm_a is...",
            definition_segment_id="seg-d",
        )
        ctx = _make_context(dedup=[fact], definitions=[defn])

        MetricPresenceStage().process(ctx)

        assert len(ctx.presences) == 1
        p = ctx.presences[0]
        assert p.score == 0.95  # fact wins; definition floor does not lower it
        assert set(p.evidence_segment_ids) == {"seg-f", "seg-d"}

    def test_presences_sorted_by_metric_id_for_determinism(self) -> None:
        ctx = _make_context(
            dedup=[
                _fact("cm_zebra", confidence=0.5, segment_id="s1"),
                _fact("cm_alpha", confidence=0.5, segment_id="s2"),
                _fact("cm_middle", confidence=0.5, segment_id="s3"),
            ]
        )

        MetricPresenceStage().process(ctx)

        metric_ids = [p.canonical_metric_id for p in ctx.presences]
        assert metric_ids == sorted(metric_ids)

    def test_fact_without_canonical_metric_id_is_skipped(self) -> None:
        ctx = _make_context(
            dedup=[
                _fact("", confidence=0.9, segment_id="s1"),
                _fact("cm_real", confidence=0.7, segment_id="s2"),
            ]
        )

        MetricPresenceStage().process(ctx)

        assert [p.canonical_metric_id for p in ctx.presences] == ["cm_real"]

    def test_stage_result_metadata_has_counters(self) -> None:
        fact = _fact("cm_a", confidence=0.8, segment_id="seg")
        img = _chart_image([("cm_b", 0.6)])
        ctx = _make_context(dedup=[fact], images=[img])

        result = MetricPresenceStage().process(ctx)

        assert result.success
        assert result.stage == PipelineStage.METRIC_PRESENCE
        assert result.items_output == 2
        assert result.metadata["metrics_present"] == 2
        assert result.metadata["fact_contributors"] == 1
        assert result.metadata["chart_only_presences"] == 1
