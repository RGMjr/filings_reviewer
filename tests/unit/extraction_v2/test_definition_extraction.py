"""
Unit tests for V2 Definition Extraction Stage (Stage 9.5).

Tests cover:
1. No facts -> empty definitions
2. Facts but no DEFINITION/METHODOLOGY segments -> empty definitions
3. Facts with nearby DEFINITION segment -> MetricDefinition created
4. Alignment scoring: each of 4 flag values
5. Metric linking via candidate chain (candidate has segment_id, nearby segment is DEFINITION)
6. Multiple metrics each get their own definition
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

from src.extraction_v2.models import (
    Document,
    MetricCandidate,
    MetricFact,
    Segment,
    SegmentType,
    SourceLocator,
    SourceType,
)
from src.extraction_v2.stages.definition_extraction import (
    DEFINITION_SEARCH_WINDOW,
    DefinitionExtractionStage,
)


# ============================================================================
# Helpers / Mock objects
# ============================================================================


@dataclass
class MockPipelineConfig:
    min_confidence_auto_accept: float = 0.90
    retain_context: bool = False


@dataclass
class MockPipelineContext:
    html_path: Path = field(default_factory=lambda: Path("/test/file.html"))
    filing_id: int = 1
    config: MockPipelineConfig = field(default_factory=MockPipelineConfig)
    document: Document | None = field(default_factory=Document)
    segments: list[Segment] = field(default_factory=list)
    tables: list[Any] = field(default_factory=list)
    candidates: list[MetricCandidate] = field(default_factory=list)
    facts: list[MetricFact] = field(default_factory=list)
    definitions: list[Any] = field(default_factory=list)
    stage_results: list[Any] = field(default_factory=list)


def _seg(
    segment_id: str,
    sequence: int,
    segment_type: SegmentType,
    text: str,
) -> Segment:
    return Segment(
        segment_id=segment_id,
        segment_type=segment_type,
        text=text,
        sequence=sequence,
    )


def _fact(canonical_metric_id: str) -> MetricFact:
    return MetricFact(canonical_metric_id=canonical_metric_id)


def _candidate(candidate_id: str, metric_id: str, segment_id: str) -> MetricCandidate:
    return MetricCandidate(
        candidate_id=candidate_id,
        metric_id=metric_id,
        source_locator=SourceLocator(segment_id=segment_id),
        source_type=SourceType.TEXT,
    )


@pytest.fixture
def stage() -> DefinitionExtractionStage:
    return DefinitionExtractionStage()


# ============================================================================
# Test: no facts -> empty definitions
# ============================================================================


class TestNoFacts:
    def test_no_facts_returns_empty(self, stage):
        ctx = MockPipelineContext(facts=[], segments=[])
        result = stage.process(ctx)
        assert result.success is True
        assert result.items_output == 0
        assert ctx.definitions == []

    def test_no_facts_zero_duration(self, stage):
        ctx = MockPipelineContext(facts=[], segments=[])
        result = stage.process(ctx)
        assert result.duration_ms == 0


# ============================================================================
# Test: facts but no matching DEFINITION/METHODOLOGY segments
# ============================================================================


class TestNoDefinitionSegments:
    def test_only_paragraph_segments_produces_no_definitions(self, stage):
        seg = _seg("s1", 1, SegmentType.PARAGRAPH, "We had 100 customers.")
        ctx = MockPipelineContext(
            facts=[_fact("cm_customers_period_end")],
            segments=[seg],
            candidates=[_candidate("c1", "cm_customers_period_end", "s1")],
        )
        result = stage.process(ctx)
        assert result.success is True
        assert ctx.definitions == []

    def test_facts_with_no_candidates_have_no_seqs(self, stage):
        # Facts present but no candidates to link segments
        seg = _seg("s1", 1, SegmentType.DEFINITION, "A customer is a unique account.")
        ctx = MockPipelineContext(
            facts=[_fact("cm_customers_period_end")],
            segments=[seg],
            candidates=[],  # no candidates
        )
        result = stage.process(ctx)
        assert ctx.definitions == []


# ============================================================================
# Test: nearby DEFINITION segment produces MetricDefinition
# ============================================================================


class TestDefinitionSegmentFound:
    def test_adjacent_definition_segment_captured(self, stage):
        para = _seg("s1", 1, SegmentType.PARAGRAPH, "We had 100 customers.")
        defn = _seg("s2", 2, SegmentType.DEFINITION, "A customer is a unique buyer account.")
        ctx = MockPipelineContext(
            facts=[_fact("cm_customers_period_end")],
            segments=[para, defn],
            candidates=[_candidate("c1", "cm_customers_period_end", "s1")],
        )
        stage.process(ctx)
        assert len(ctx.definitions) == 1
        md = ctx.definitions[0]
        assert md.canonical_metric_id == "cm_customers_period_end"
        assert md.definition_text == "A customer is a unique buyer account."
        assert md.definition_segment_id == "s2"

    def test_methodology_segment_captured(self, stage):
        para = _seg("s1", 1, SegmentType.PARAGRAPH, "ARR was $10M.")
        meth = _seg("s2", 2, SegmentType.METHODOLOGY, "Calculated by summing monthly recurring revenue times 12.")
        ctx = MockPipelineContext(
            facts=[_fact("cm_arr")],
            segments=[para, meth],
            candidates=[_candidate("c1", "cm_arr", "s1")],
        )
        stage.process(ctx)
        assert len(ctx.definitions) == 1
        md = ctx.definitions[0]
        assert md.methodology_text == "Calculated by summing monthly recurring revenue times 12."
        assert md.methodology_segment_id == "s2"
        assert md.definition_text == ""

    def test_both_definition_and_methodology_captured(self, stage):
        para = _seg("s1", 5, SegmentType.PARAGRAPH, "Metric mention.")
        defn = _seg("s2", 6, SegmentType.DEFINITION, "The metric means X.")
        meth = _seg("s3", 7, SegmentType.METHODOLOGY, "Calculated as Y.")
        ctx = MockPipelineContext(
            facts=[_fact("cm_new_customers_acquired")],
            segments=[para, defn, meth],
            candidates=[_candidate("c1", "cm_new_customers_acquired", "s1")],
        )
        stage.process(ctx)
        assert len(ctx.definitions) == 1
        md = ctx.definitions[0]
        assert md.definition_text == "The metric means X."
        assert md.methodology_text == "Calculated as Y."

    def test_definition_outside_window_not_captured(self, stage):
        para = _seg("s1", 1, SegmentType.PARAGRAPH, "Metric mention.")
        # Place definition far beyond the window
        far_defn = _seg(
            "s2",
            1 + DEFINITION_SEARCH_WINDOW + 2,
            SegmentType.DEFINITION,
            "Too far away definition.",
        )
        ctx = MockPipelineContext(
            facts=[_fact("cm_customers_period_end")],
            segments=[para, far_defn],
            candidates=[_candidate("c1", "cm_customers_period_end", "s1")],
        )
        stage.process(ctx)
        assert ctx.definitions == []

    def test_definition_at_window_boundary_captured(self, stage):
        para = _seg("s1", 10, SegmentType.PARAGRAPH, "Metric mention.")
        boundary_defn = _seg(
            "s2",
            10 + DEFINITION_SEARCH_WINDOW,
            SegmentType.DEFINITION,
            "Boundary definition.",
        )
        ctx = MockPipelineContext(
            facts=[_fact("cm_customers_period_end")],
            segments=[para, boundary_defn],
            candidates=[_candidate("c1", "cm_customers_period_end", "s1")],
        )
        stage.process(ctx)
        assert len(ctx.definitions) == 1

    def test_doc_id_comes_from_context_document(self, stage):
        doc = Document()
        doc.doc_id = "test-doc-uuid-123"
        para = _seg("s1", 1, SegmentType.PARAGRAPH, "Metric mention.")
        defn = _seg("s2", 2, SegmentType.DEFINITION, "A definition.")
        ctx = MockPipelineContext(
            document=doc,
            facts=[_fact("cm_customers_period_end")],
            segments=[para, defn],
            candidates=[_candidate("c1", "cm_customers_period_end", "s1")],
        )
        stage.process(ctx)
        assert ctx.definitions[0].doc_id == "test-doc-uuid-123"


# ============================================================================
# Test: alignment scoring
# ============================================================================


class TestAlignmentScoring:
    """Test _assess_alignment returns correct flags."""

    def test_unknown_for_empty_definition(self, stage):
        result = stage._assess_alignment("cm_new_customers_acquired", "")
        assert result == "unknown"

    def test_unknown_for_unknown_metric_id(self, stage):
        result = stage._assess_alignment("cm_totally_unknown_metric", "some definition text")
        assert result == "unknown"

    def test_aligned_when_many_keywords_match(self, stage):
        # cm_new_customers_acquired keywords: first, qualifying, economic, activity, purchase, transaction, period
        definition = (
            "First qualifying economic activity including purchase or transaction in the period."
        )
        result = stage._assess_alignment("cm_new_customers_acquired", definition)
        assert result == "aligned"

    def test_partial_when_some_keywords_match(self, stage):
        # Give ~30-70% of keywords
        definition = "First purchase in the period."
        result = stage._assess_alignment("cm_new_customers_acquired", definition)
        assert result in ("partial", "not_aligned", "aligned")
        # At least check it doesn't crash; specific threshold depends on keyword list
        # "first", "purchase", "period" = 3/7 = ~43% -> partial
        assert result == "partial"

    def test_not_aligned_when_few_keywords_match(self, stage):
        # Only one keyword matches (purchase)
        definition = "Number of purchase events."
        # keywords for cm_new_customers_acquired: first, qualifying, economic, activity, purchase, transaction, period
        # matches: "purchase" = 1/7 = ~14% -> not_aligned (0 < ratio < 0.3)
        result = stage._assess_alignment("cm_new_customers_acquired", definition)
        assert result == "not_aligned"

    def test_unknown_returned_when_no_keywords_match(self, stage):
        definition = "Revenue net of refunds."
        # No keywords from cm_new_customers_acquired in this definition
        result = stage._assess_alignment("cm_new_customers_acquired", definition)
        assert result == "unknown"


# ============================================================================
# Test: text normalization
# ============================================================================


class TestNormalizeText:
    def test_collapses_whitespace(self, stage):
        text = "A   customer   is    a   person."
        normalized = stage._normalize_text(text)
        assert "   " not in normalized
        assert normalized == "A customer is a person."

    def test_truncates_long_text(self, stage):
        long_text = "word " * 200  # ~1000 chars
        normalized = stage._normalize_text(long_text)
        assert len(normalized) <= 503  # 500 + "..."
        assert normalized.endswith("...")

    def test_empty_string_returns_empty(self, stage):
        assert stage._normalize_text("") == ""

    def test_short_text_not_truncated(self, stage):
        text = "Short definition."
        assert stage._normalize_text(text) == text


# ============================================================================
# Test: multiple metrics each get their own definition
# ============================================================================


class TestMultipleMetrics:
    def test_two_metrics_each_get_definition(self, stage):
        para1 = _seg("s1", 1, SegmentType.PARAGRAPH, "ARR mention.")
        defn1 = _seg("s2", 2, SegmentType.DEFINITION, "ARR is annualized recurring revenue.")
        para2 = _seg("s3", 10, SegmentType.PARAGRAPH, "Customer count mention.")
        defn2 = _seg("s4", 11, SegmentType.DEFINITION, "Customers are unique accounts.")
        ctx = MockPipelineContext(
            facts=[_fact("cm_arr"), _fact("cm_customers_period_end")],
            segments=[para1, defn1, para2, defn2],
            candidates=[
                _candidate("c1", "cm_arr", "s1"),
                _candidate("c2", "cm_customers_period_end", "s3"),
            ],
        )
        stage.process(ctx)
        assert len(ctx.definitions) == 2
        metric_ids = {d.canonical_metric_id for d in ctx.definitions}
        assert "cm_arr" in metric_ids
        assert "cm_customers_period_end" in metric_ids

    def test_same_metric_produces_one_definition(self, stage):
        # Two candidates for the same metric -> should produce one MetricDefinition
        para1 = _seg("s1", 1, SegmentType.PARAGRAPH, "First mention of ARR.")
        para2 = _seg("s2", 5, SegmentType.PARAGRAPH, "Second mention of ARR.")
        defn = _seg("s3", 2, SegmentType.DEFINITION, "ARR definition.")
        ctx = MockPipelineContext(
            facts=[_fact("cm_arr")],
            segments=[para1, para2, defn],
            candidates=[
                _candidate("c1", "cm_arr", "s1"),
                _candidate("c2", "cm_arr", "s2"),
            ],
        )
        stage.process(ctx)
        # Only one MetricDefinition per metric_id
        assert len(ctx.definitions) == 1
        assert ctx.definitions[0].canonical_metric_id == "cm_arr"

    def test_metric_with_no_nearby_definition_excluded(self, stage):
        # Two metrics, only one has a nearby definition
        para1 = _seg("s1", 1, SegmentType.PARAGRAPH, "ARR mention.")
        defn1 = _seg("s2", 2, SegmentType.DEFINITION, "ARR definition.")
        para2 = _seg("s3", 50, SegmentType.PARAGRAPH, "Customers mention, far from any definition.")
        ctx = MockPipelineContext(
            facts=[_fact("cm_arr"), _fact("cm_customers_period_end")],
            segments=[para1, defn1, para2],
            candidates=[
                _candidate("c1", "cm_arr", "s1"),
                _candidate("c2", "cm_customers_period_end", "s3"),
            ],
        )
        stage.process(ctx)
        # Only ARR should get a definition; customers metric has none nearby
        assert len(ctx.definitions) == 1
        assert ctx.definitions[0].canonical_metric_id == "cm_arr"


# ============================================================================
# Test: stage result metadata
# ============================================================================


class TestStageResult:
    def test_items_processed_equals_unique_metric_count(self, stage):
        para = _seg("s1", 1, SegmentType.PARAGRAPH, "Metric mention.")
        defn = _seg("s2", 2, SegmentType.DEFINITION, "Definition.")
        ctx = MockPipelineContext(
            facts=[_fact("cm_arr"), _fact("cm_customers_period_end")],
            segments=[para, defn],
            candidates=[
                _candidate("c1", "cm_arr", "s1"),
                _candidate("c2", "cm_customers_period_end", "s1"),
            ],
        )
        result = stage.process(ctx)
        assert result.items_processed == 2

    def test_items_output_equals_definitions_count(self, stage):
        para = _seg("s1", 1, SegmentType.PARAGRAPH, "Metric mention.")
        defn = _seg("s2", 2, SegmentType.DEFINITION, "Definition.")
        ctx = MockPipelineContext(
            facts=[_fact("cm_arr")],
            segments=[para, defn],
            candidates=[_candidate("c1", "cm_arr", "s1")],
        )
        result = stage.process(ctx)
        assert result.items_output == len(ctx.definitions)
