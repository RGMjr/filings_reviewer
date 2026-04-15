"""Unit tests for the unified comparison module."""

from __future__ import annotations

from decimal import Decimal

import pytest

from src.extraction_v2.models import (
    EvidencePack,
    ExtractionMethod,
    MetricFact,
    PeriodType,
    ReviewStatus,
    Scope,
    SourceLocator,
    SourceType,
    Unit,
)
from src.gold_standard.unified_comparison import (
    NormalizedExtraction,
    match_extractions_to_gold,
    partition_by_source_type,
    v1_candidate_to_normalized,
    v2_fact_to_normalized,
)
from src.gold_standard.v2_validator import GoldStandardEntry
from src.review.models import CandidateFeatures, ReviewCandidate

# =============================================================================
# Fixture helpers
# =============================================================================


def make_gold_entry(
    metric_id: str = "cm_average_order_value",
    raw_value: str = "100",
    scaled_value: str = "",
    scale_unit: str = "",
    segment_type: str = "text",
    is_def_only: bool = False,
    company: str = "TestCo",
) -> GoldStandardEntry:
    """Create a minimal GoldStandardEntry for testing."""
    return GoldStandardEntry(
        document_url="https://sec.gov/test",
        company_name=company,
        metric_id=metric_id,
        name_in_text="annual recurring revenue",
        raw_value=raw_value,
        scaled_value=scaled_value,
        scale_unit=scale_unit,
        period="FY2022",
        definition="",
        quote_context="",
        segment_type=segment_type,
        is_definition_only=is_def_only,
        value_context="",
        detection_difficulty="easy",
        period_start=None,
        period_end=None,
    )


def make_normalized(
    metric_id: str = "cm_average_order_value",
    value: float = 100.0,
    source_type: str = "text",
    pipeline: str = "v2",
    extraction_id: str = "test-1",
) -> NormalizedExtraction:
    """Create a minimal NormalizedExtraction for testing."""
    return NormalizedExtraction(
        extraction_id=extraction_id,
        metric_id=metric_id,
        value=value,
        source_type=source_type,
        period_start=None,
        period_end=None,
        confidence=0.9,
        pipeline=pipeline,
        raw_context="",
    )


def make_metric_fact(
    canonical_metric_id: str = "cm_average_order_value",
    value: float = 100.0,
    source_type: SourceType = SourceType.TEXT,
    fact_id: str = "fact-1",
) -> MetricFact:
    """Create a minimal MetricFact for testing."""
    return MetricFact(
        fact_id=fact_id,
        doc_id="doc-1",
        canonical_metric_id=canonical_metric_id,
        value=value,
        value_raw=str(value),
        unit=Unit.OTHER,
        period_type=PeriodType.OTHER,
        scope=Scope.COMPANY,
        source_type=source_type,
        source_locator=SourceLocator(),
        evidence_pack=EvidencePack(snippet_html="<p>test</p>"),
        confidence=0.9,
        extraction_method=ExtractionMethod.EXACT_MATCH,
        requires_review=False,
        review_status=ReviewStatus.AUTO_ACCEPTED,
        pipeline_version="2.0.0",
    )


def make_review_candidate(
    suggested_metric_id: str = "cm_average_order_value",
    parsed_value: Decimal | None = Decimal("100"),
    suggestion_confidence: float | None = 0.8,
    is_in_table: bool = False,
    context_text: str = "test context",
    candidate_id: int | None = 42,
) -> ReviewCandidate:
    """Create a minimal ReviewCandidate for testing."""
    features = CandidateFeatures(
        keyword_distance=5,
        keyword_position="before",
        is_in_table=is_in_table,
        is_in_risk_factors=False,
        contains_definition_language=False,
        has_period_mention=False,
        number_format="integer",
    )
    return ReviewCandidate(
        filing_id=1,
        company_id=1,
        char_position=0,
        context_text=context_text,
        raw_number_text="100",
        triggering_keyword="ARR",
        keyword_distance=5,
        keyword_position="before",
        parsed_value=parsed_value,
        suggested_metric_id=suggested_metric_id,
        suggestion_confidence=suggestion_confidence,
        features=features,
        candidate_id=candidate_id,
    )


# =============================================================================
# TestMatchExtractionsToGold
# =============================================================================


class TestMatchExtractionsToGold:
    def test_exact_match(self) -> None:
        """One extraction matches one gold entry → TP=1, FP=0, FN=0, P=R=F1=1.0."""
        gold = [make_gold_entry(metric_id="cm_average_order_value", raw_value="100")]
        extractions = [make_normalized(metric_id="cm_average_order_value", value=100.0)]

        result = match_extractions_to_gold(extractions, gold)

        assert len(result.tp_pairs) == 1
        assert len(result.fp_extractions) == 0
        assert len(result.fn_entries) == 0
        assert result.precision == pytest.approx(1.0)
        assert result.recall == pytest.approx(1.0)
        assert result.f1 == pytest.approx(1.0)

    def test_close_match_within_tolerance(self) -> None:
        """Value 101.0 vs gold 100 (1% off, within 2% tolerance) → TP."""
        gold = [make_gold_entry(metric_id="cm_average_order_value", raw_value="100")]
        extractions = [make_normalized(metric_id="cm_average_order_value", value=101.0)]

        result = match_extractions_to_gold(extractions, gold, value_tolerance=0.02)

        assert len(result.tp_pairs) == 1
        assert len(result.fp_extractions) == 0
        assert len(result.fn_entries) == 0

    def test_value_outside_tolerance(self) -> None:
        """Value 103.0 vs gold 100 (3% off) → FP=1, FN=1."""
        gold = [make_gold_entry(metric_id="cm_average_order_value", raw_value="100")]
        extractions = [make_normalized(metric_id="cm_average_order_value", value=103.0)]

        result = match_extractions_to_gold(extractions, gold, value_tolerance=0.02)

        assert len(result.tp_pairs) == 0
        assert len(result.fp_extractions) == 1
        assert len(result.fn_entries) == 1

    def test_wrong_metric_no_match(self) -> None:
        """Extraction with wrong metric_id that IS in gold set → FP+FN."""
        gold = [
            make_gold_entry(metric_id="cm_average_order_value", raw_value="100"),
            make_gold_entry(metric_id="cm_nrr", raw_value="110"),
        ]
        # Extract cm_nrr value=100 but gold cm_nrr=110 — value mismatch
        extractions = [make_normalized(metric_id="cm_nrr", value=100.0)]

        result = match_extractions_to_gold(extractions, gold)

        # cm_nrr is in gold but value doesn't match — FP
        # cm_average_order_value has no extraction — FN; cm_nrr also unmatched — FN
        assert len(result.tp_pairs) == 0
        assert len(result.fp_extractions) == 1  # cm_nrr wrong value, in gold set
        assert len(result.fn_entries) == 2  # both gold entries unmatched

    def test_fp_scoping_unknown_metric(self) -> None:
        """Extraction with metric_id NOT in gold set → not counted as FP."""
        gold = [make_gold_entry(metric_id="cm_average_order_value", raw_value="100")]
        # Extract an entirely different metric not in gold
        extractions = [make_normalized(metric_id="cm_dau", value=50.0)]

        result = match_extractions_to_gold(extractions, gold)

        # cm_dau not in gold — not an FP; cm_average_order_value not matched — FN
        assert len(result.tp_pairs) == 0
        assert len(result.fp_extractions) == 0
        assert len(result.fn_entries) == 1

    def test_deduplication_gold_entries(self) -> None:
        """Two gold entries with same (metric_id, value) collapse to 1 — missing both counts as FN=1."""
        gold = [
            make_gold_entry(metric_id="cm_average_order_value", raw_value="100"),
            make_gold_entry(metric_id="cm_average_order_value", raw_value="100"),  # duplicate
        ]
        extractions: list[NormalizedExtraction] = []

        result = match_extractions_to_gold(extractions, gold)

        # After dedup: 1 unique gold entry; 0 extractions → FN=1
        assert len(result.fn_entries) == 1
        assert len(result.tp_pairs) == 0

    def test_definition_only_entries_skipped(self) -> None:
        """Gold entry with is_definition_only=True doesn't count in metrics."""
        gold = [make_gold_entry(metric_id="cm_average_order_value", raw_value="100", is_def_only=True)]
        extractions: list[NormalizedExtraction] = []

        result = match_extractions_to_gold(extractions, gold)

        # Definition-only entries are filtered out — no active gold
        assert len(result.tp_pairs) == 0
        assert len(result.fp_extractions) == 0
        assert len(result.fn_entries) == 0
        assert result.precision == 0.0
        assert result.recall == 0.0
        assert result.f1 == 0.0

    def test_greedy_no_double_claiming(self) -> None:
        """Two extractions, one gold entry — only one gets matched (greedy, 1-to-1)."""
        gold = [make_gold_entry(metric_id="cm_average_order_value", raw_value="100")]
        extractions = [
            make_normalized(metric_id="cm_average_order_value", value=100.0, extraction_id="e1"),
            make_normalized(metric_id="cm_average_order_value", value=100.0, extraction_id="e2"),
        ]

        result = match_extractions_to_gold(extractions, gold)

        # Only one extraction can claim the single gold entry
        assert len(result.tp_pairs) == 1
        # The other extraction is a FP (cm_average_order_value in gold set, unmatched)
        assert len(result.fp_extractions) == 1
        assert len(result.fn_entries) == 0

    def test_multiple_matches(self) -> None:
        """3 extractions, 3 gold entries, all match → P=R=1.0."""
        gold = [
            make_gold_entry(metric_id="cm_average_order_value", raw_value="100"),
            make_gold_entry(metric_id="cm_nrr", raw_value="110"),
            make_gold_entry(metric_id="cm_dau", raw_value="500"),
        ]
        extractions = [
            make_normalized(metric_id="cm_average_order_value", value=100.0, extraction_id="e1"),
            make_normalized(metric_id="cm_nrr", value=110.0, extraction_id="e2"),
            make_normalized(metric_id="cm_dau", value=500.0, extraction_id="e3"),
        ]

        result = match_extractions_to_gold(extractions, gold)

        assert len(result.tp_pairs) == 3
        assert len(result.fp_extractions) == 0
        assert len(result.fn_entries) == 0
        assert result.precision == pytest.approx(1.0)
        assert result.recall == pytest.approx(1.0)

    def test_percentage_value(self) -> None:
        """Gold raw_value='138', scale_unit='percent' matches extraction value=138.0."""
        gold = [make_gold_entry(metric_id="cm_nrr", raw_value="138", scale_unit="percent")]
        extractions = [make_normalized(metric_id="cm_nrr", value=138.0)]

        result = match_extractions_to_gold(extractions, gold)

        assert len(result.tp_pairs) == 1
        assert len(result.fp_extractions) == 0
        assert len(result.fn_entries) == 0

    def test_zero_gold_entries(self) -> None:
        """Empty gold list → MatchingResult with zeros, no crash."""
        result = match_extractions_to_gold(
            [make_normalized(metric_id="cm_average_order_value", value=100.0)],
            [],
        )

        assert len(result.tp_pairs) == 0
        assert len(result.fp_extractions) == 0
        assert len(result.fn_entries) == 0
        assert result.precision == 0.0
        assert result.recall == 0.0
        assert result.f1 == 0.0

    def test_precision_recall_f1_properties(self) -> None:
        """Verify P, R, F1 computed correctly from TP/FP/FN."""
        # 2 gold entries, 3 extractions: 1 TP, 1 FP (in-scope), 1 FN
        gold = [
            make_gold_entry(metric_id="cm_average_order_value", raw_value="100"),
            make_gold_entry(metric_id="cm_nrr", raw_value="110"),
        ]
        extractions = [
            make_normalized(metric_id="cm_average_order_value", value=100.0, extraction_id="e1"),  # TP
            make_normalized(metric_id="cm_average_order_value", value=200.0, extraction_id="e2"),  # FP (wrong val)
            # cm_nrr not extracted → FN
        ]

        result = match_extractions_to_gold(extractions, gold)

        tp = len(result.tp_pairs)
        fp = len(result.fp_extractions)
        fn = len(result.fn_entries)
        assert tp == 1
        assert fp == 1
        assert fn == 1

        expected_precision = tp / (tp + fp)
        expected_recall = tp / (tp + fn)
        expected_f1 = (
            2 * expected_precision * expected_recall / (expected_precision + expected_recall)
        )

        assert result.precision == pytest.approx(expected_precision)
        assert result.recall == pytest.approx(expected_recall)
        assert result.f1 == pytest.approx(expected_f1)


# =============================================================================
# TestNormalizedConversions
# =============================================================================


class TestNormalizedConversions:
    def test_v2_fact_source_type_mapping_table(self) -> None:
        """SourceType.HTML_TABLE → 'table'."""
        fact = make_metric_fact(source_type=SourceType.HTML_TABLE)
        normalized = v2_fact_to_normalized(fact)
        assert normalized.source_type == "table"

    def test_v2_fact_source_type_mapping_ocr_table(self) -> None:
        """SourceType.OCR_TABLE → 'table'."""
        fact = make_metric_fact(source_type=SourceType.OCR_TABLE)
        normalized = v2_fact_to_normalized(fact)
        assert normalized.source_type == "table"

    def test_v2_fact_source_type_mapping_chart(self) -> None:
        """SourceType.CHART → 'chart'."""
        fact = make_metric_fact(source_type=SourceType.CHART)
        normalized = v2_fact_to_normalized(fact)
        assert normalized.source_type == "chart"

    def test_v2_fact_source_type_mapping_text(self) -> None:
        """SourceType.TEXT → 'text'."""
        fact = make_metric_fact(source_type=SourceType.TEXT)
        normalized = v2_fact_to_normalized(fact)
        assert normalized.source_type == "text"

    def test_v2_fact_pipeline_label(self) -> None:
        """v2_fact_to_normalized sets pipeline='v2'."""
        fact = make_metric_fact()
        normalized = v2_fact_to_normalized(fact)
        assert normalized.pipeline == "v2"

    def test_v2_fact_metric_id_preserved(self) -> None:
        """canonical_metric_id survives normalization."""
        fact = make_metric_fact(canonical_metric_id="cm_average_order_value")
        normalized = v2_fact_to_normalized(fact)
        assert normalized.metric_id == "cm_average_order_value"

    def test_v1_candidate_default_confidence(self) -> None:
        """None suggestion_confidence → 0.5."""
        candidate = make_review_candidate(suggestion_confidence=None)
        normalized = v1_candidate_to_normalized(candidate)
        assert normalized.confidence == pytest.approx(0.5)

    def test_v1_candidate_explicit_confidence(self) -> None:
        """Explicit suggestion_confidence is preserved."""
        candidate = make_review_candidate(suggestion_confidence=0.75)
        normalized = v1_candidate_to_normalized(candidate)
        assert normalized.confidence == pytest.approx(0.75)

    def test_v1_candidate_table_source_type(self) -> None:
        """Candidate with is_in_table=True → source_type='table'."""
        candidate = make_review_candidate(is_in_table=True)
        normalized = v1_candidate_to_normalized(candidate)
        assert normalized.source_type == "table"

    def test_v1_candidate_text_source_type(self) -> None:
        """Candidate with is_in_table=False → source_type='text'."""
        candidate = make_review_candidate(is_in_table=False)
        normalized = v1_candidate_to_normalized(candidate)
        assert normalized.source_type == "text"

    def test_v1_candidate_pipeline_label(self) -> None:
        """v1_candidate_to_normalized sets pipeline='v1'."""
        candidate = make_review_candidate()
        normalized = v1_candidate_to_normalized(candidate)
        assert normalized.pipeline == "v1"

    def test_v1_candidate_no_candidate_id_generates_uuid(self) -> None:
        """Candidate with candidate_id=None gets a UUID extraction_id."""
        candidate = make_review_candidate(candidate_id=None)
        normalized = v1_candidate_to_normalized(candidate)
        assert normalized.extraction_id  # non-empty
        assert len(normalized.extraction_id) == 36  # UUID format

    def test_v1_candidate_with_candidate_id(self) -> None:
        """Candidate with candidate_id uses it as extraction_id."""
        candidate = make_review_candidate(candidate_id=99)
        normalized = v1_candidate_to_normalized(candidate)
        assert normalized.extraction_id == "99"


# =============================================================================
# TestPartitionBySourceType
# =============================================================================


class TestPartitionBySourceType:
    def test_partitions_by_segment_type(self) -> None:
        """Gold entries with mixed segment_types get split into correct buckets."""
        gold = [
            make_gold_entry(metric_id="cm_average_order_value", raw_value="100", segment_type="text"),
            make_gold_entry(metric_id="cm_nrr", raw_value="110", segment_type="table"),
            make_gold_entry(metric_id="cm_dau", raw_value="500", segment_type="text"),
        ]
        extractions = [
            make_normalized(metric_id="cm_average_order_value", value=100.0),
            make_normalized(metric_id="cm_nrr", value=110.0),
            make_normalized(metric_id="cm_dau", value=500.0),
        ]

        result = partition_by_source_type(
            gold_entries=gold,
            v1_extractions=[],
            v2_full_extractions=extractions,
            v2_text_only_extractions=None,
        )

        assert "text" in result
        assert "table" in result
        assert result["text"].gold_count == 2
        assert result["table"].gold_count == 1

    def test_empty_segment_type_goes_to_unclassified(self) -> None:
        """Entries with segment_type='' are grouped under empty-string key."""
        gold = [
            make_gold_entry(metric_id="cm_average_order_value", raw_value="100", segment_type=""),
        ]

        result = partition_by_source_type(
            gold_entries=gold,
            v1_extractions=[],
            v2_full_extractions=[],
            v2_text_only_extractions=None,
        )

        # Empty string segment_type lands in the "" bucket
        assert "" in result
        assert result[""].gold_count == 1

    def test_v2_text_only_none_produces_none_result(self) -> None:
        """When v2_text_only_extractions=None, v2_text_only_result is None for all buckets."""
        gold = [make_gold_entry(metric_id="cm_average_order_value", raw_value="100", segment_type="text")]

        result = partition_by_source_type(
            gold_entries=gold,
            v1_extractions=[],
            v2_full_extractions=[],
            v2_text_only_extractions=None,
        )

        assert result["text"].v2_text_only_result is None

    def test_partition_scores_computed_per_bucket(self) -> None:
        """Each bucket gets its own MatchingResult from all extractions."""
        gold = [
            make_gold_entry(metric_id="cm_average_order_value", raw_value="100", segment_type="text"),
            make_gold_entry(metric_id="cm_nrr", raw_value="110", segment_type="chart"),
        ]
        extractions = [
            make_normalized(metric_id="cm_average_order_value", value=100.0),
            make_normalized(metric_id="cm_nrr", value=110.0),
        ]

        result = partition_by_source_type(
            gold_entries=gold,
            v1_extractions=[],
            v2_full_extractions=extractions,
            v2_text_only_extractions=None,
        )

        # text bucket: cm_average_order_value matched
        assert len(result["text"].v2_full_result.tp_pairs) == 1
        # chart bucket: cm_nrr matched
        assert len(result["chart"].v2_full_result.tp_pairs) == 1

    def test_empty_gold_produces_empty_result(self) -> None:
        """Empty gold list returns empty partition dict."""
        result = partition_by_source_type(
            gold_entries=[],
            v1_extractions=[],
            v2_full_extractions=[],
            v2_text_only_extractions=None,
        )

        assert result == {}
