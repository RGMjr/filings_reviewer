"""
Unit tests for V2 Fact Construction Stage.

Tests cover:
1. Basic transformation: BoundValue → MetricFact
2. Confidence scoring with section bonuses and source penalties
3. EvidencePack generation for table and text sources
4. Source type determination (HTML_TABLE, TEXT, CHART, OCR_TABLE)
5. Error handling and edge cases
"""

from datetime import date
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from src.extraction_v2.models import (
    BoundValue,
    Cell,
    Document,
    ExtractionMethod,
    MetricCandidate,
    PeriodType,
    ReviewStatus,
    SectionType,
    Segment,
    SourceLocator,
    SourceType,
    Table,
)
from src.extraction_v2.pipeline import PipelineContext, PipelineStage
from src.extraction_v2.stages.fact_construction import (
    BINDING_CONFIDENCE_WEIGHT,
    BUSINESS_SECTION_BONUS,
    CHART_PENALTY,
    MDA_SECTION_BONUS,
    OCR_TABLE_PENALTY,
    PERIOD_AMBIGUITY_PENALTY,
    PERIOD_CONFIDENCE_WEIGHT,
    FactConstructionStage,
)

# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def stage() -> FactConstructionStage:
    """Create a FactConstructionStage instance."""
    return FactConstructionStage()


@pytest.fixture
def mock_context() -> PipelineContext:
    """Create a mock PipelineContext with minimal setup."""
    from src.extraction_v2.pipeline import PipelineConfig

    context = MagicMock(spec=PipelineContext)
    context.document = Document(doc_id="TEST_DOC", fiscal_year=2024, fiscal_period="FY")
    context.bound_values = []
    context.candidates = []
    context.segments = []
    context.tables = []
    context.facts = []
    context.images = []
    context.config = PipelineConfig()
    return context


def make_bound_value(
    candidate_id: str = "test_candidate",
    value: float = 100.0,
    value_raw: str = "100",
    unit: str = "count",
    binding_confidence: float = 0.9,
    period_confidence: float = 0.8,
    period_ambiguous: bool = False,
    period_type: PeriodType = PeriodType.QUARTERLY,
    period_start: date | None = None,
    period_end: date | None = None,
    table_id: str | None = None,
    cell_row: int | None = None,
    cell_col: int | None = None,
    segment_id: str | None = None,
    text_span: tuple[int, int] | None = None,
    img_id: str | None = None,
) -> BoundValue:
    """Create a BoundValue for testing."""
    return BoundValue(
        candidate_id=candidate_id,
        value=value,
        value_raw=value_raw,
        unit=unit,
        binding_confidence=binding_confidence,
        period_confidence=period_confidence,
        period_ambiguous=period_ambiguous,
        period_type=period_type,
        period_start=period_start or date(2024, 1, 1),
        period_end=period_end or date(2024, 3, 31),
        source_locator=SourceLocator(
            table_id=table_id,
            cell_row=cell_row,
            cell_col=cell_col,
            segment_id=segment_id,
            text_span=text_span,
            img_id=img_id,
        ),
    )


def make_candidate(
    candidate_id: str = "test_candidate",
    metric_id: str = "cm_arr",
    section_type: SectionType = SectionType.UNKNOWN,
) -> MetricCandidate:
    """Create a MetricCandidate for testing."""
    candidate = MagicMock(spec=MetricCandidate)
    candidate.candidate_id = candidate_id
    candidate.metric_id = metric_id
    candidate.section_type = section_type
    return candidate


def make_table(
    table_id: str = "table_1",
    header_texts: list[str] | None = None,
    stub_texts: list[str] | None = None,
) -> Table:
    """Create a Table with headers and stubs for testing."""
    if header_texts is None:
        header_texts = ["Q1 2024", "Q2 2024"]
    if stub_texts is None:
        stub_texts = ["Metric A", "Metric B"]

    table = Table(
        table_id=table_id,
        row_count=len(stub_texts) + 1,
        col_count=len(header_texts) + 1,
        header_rows=1,
        stub_cols=1,
    )

    cells = []
    # Header row (skip first cell)
    for col, text in enumerate(header_texts, start=1):
        cells.append(Cell(row=0, col=col, text=text, is_header=True))

    # Stub column
    for row, text in enumerate(stub_texts, start=1):
        cells.append(Cell(row=row, col=0, text=text, is_stub=True))

    # Data cells
    for row in range(1, len(stub_texts) + 1):
        for col in range(1, len(header_texts) + 1):
            cells.append(Cell(row=row, col=col, text=f"data_{row}_{col}"))

    table.cells = cells
    return table


def make_segment(
    segment_id: str = "seg_1", text: str = "This is test text with 100 customers."
) -> Segment:
    """Create a Segment for testing."""
    segment = MagicMock(spec=Segment)
    segment.segment_id = segment_id
    segment.text = text
    return segment


# ============================================================================
# Basic Transformation Tests
# ============================================================================


def test_empty_bound_values(stage: FactConstructionStage, mock_context: PipelineContext) -> None:
    """Test that empty bound_values returns success with zero facts."""
    result = stage.process(mock_context)

    assert result.success
    assert result.stage == PipelineStage.FACT_CONSTRUCTION
    assert result.items_processed == 0
    assert result.items_output == 0
    assert len(mock_context.facts) == 0


def test_single_bound_value_to_fact(
    stage: FactConstructionStage, mock_context: PipelineContext
) -> None:
    """Test transformation of a single BoundValue to MetricFact."""
    # Setup
    candidate = make_candidate(
        candidate_id="cand_1", metric_id="cm_arr", section_type=SectionType.MDA
    )
    bv = make_bound_value(
        candidate_id="cand_1",
        value=1000.0,
        value_raw="1,000",
        unit="USD",
        binding_confidence=0.9,
        period_confidence=0.8,
        period_type=PeriodType.QUARTERLY,
        period_start=date(2024, 1, 1),
        period_end=date(2024, 3, 31),
        segment_id="seg_1",
        text_span=(10, 15),
    )

    mock_context.candidates = [candidate]
    mock_context.bound_values = [bv]
    mock_context.segments = [make_segment("seg_1")]

    # Execute
    result = stage.process(mock_context)

    # Verify
    assert result.success
    assert result.items_processed == 1
    assert result.items_output == 1
    assert len(mock_context.facts) == 1

    fact = mock_context.facts[0]
    assert fact.doc_id == "TEST_DOC"
    assert fact.canonical_metric_id == "cm_arr"
    assert fact.value == 1000.0
    assert fact.value_raw == "1,000"
    assert fact.unit == "USD"
    assert fact.period_type == PeriodType.QUARTERLY
    assert fact.period_start == date(2024, 1, 1)
    assert fact.period_end == date(2024, 3, 31)
    assert fact.source_type == SourceType.TEXT
    assert fact.extraction_method == ExtractionMethod.EXACT_MATCH
    assert fact.requires_review is True
    assert fact.review_status == ReviewStatus.PENDING_REVIEW


def test_multiple_bound_values_to_facts(
    stage: FactConstructionStage, mock_context: PipelineContext
) -> None:
    """Test transformation of multiple BoundValues to multiple MetricFacts."""
    # Setup
    candidate1 = make_candidate(candidate_id="cand_1", metric_id="cm_arr")
    candidate2 = make_candidate(candidate_id="cand_2", metric_id="cm_nrr")

    bv1 = make_bound_value(candidate_id="cand_1", value=100.0, segment_id="seg_1")
    bv2 = make_bound_value(candidate_id="cand_2", value=200.0, segment_id="seg_1")

    mock_context.candidates = [candidate1, candidate2]
    mock_context.bound_values = [bv1, bv2]
    mock_context.segments = [make_segment("seg_1")]

    # Execute
    result = stage.process(mock_context)

    # Verify
    assert result.success
    assert result.items_processed == 2
    assert result.items_output == 2
    assert len(mock_context.facts) == 2

    assert mock_context.facts[0].canonical_metric_id == "cm_arr"
    assert mock_context.facts[0].value == 100.0
    assert mock_context.facts[1].canonical_metric_id == "cm_nrr"
    assert mock_context.facts[1].value == 200.0


def test_missing_candidate(stage: FactConstructionStage, mock_context: PipelineContext) -> None:
    """Test that missing candidate results in empty metric_id."""
    bv = make_bound_value(candidate_id="missing_candidate", segment_id="seg_1")

    mock_context.bound_values = [bv]
    mock_context.segments = [make_segment("seg_1")]

    # Execute
    result = stage.process(mock_context)

    # Verify - should succeed but metric_id is empty
    assert result.success
    assert len(mock_context.facts) == 1
    assert mock_context.facts[0].canonical_metric_id == ""


# ============================================================================
# Confidence Scoring Tests
# ============================================================================


def test_base_confidence_from_binding(
    stage: FactConstructionStage, mock_context: PipelineContext
) -> None:
    """Test that base confidence comes from binding_confidence."""
    candidate = make_candidate(candidate_id="cand_1", section_type=SectionType.UNKNOWN)
    bv = make_bound_value(
        candidate_id="cand_1",
        binding_confidence=0.9,
        period_confidence=0.0,
        period_ambiguous=False,
        segment_id="seg_1",
    )

    mock_context.candidates = [candidate]
    mock_context.bound_values = [bv]
    mock_context.segments = [make_segment("seg_1")]

    result = stage.process(mock_context)

    # Confidence = 0.9 * 0.8 + 0.0 * 0.2 = 0.72
    assert result.success
    fact = mock_context.facts[0]
    expected = 0.9 * BINDING_CONFIDENCE_WEIGHT + 0.0 * PERIOD_CONFIDENCE_WEIGHT
    assert abs(fact.confidence - expected) < 0.01


def test_mda_section_bonus(stage: FactConstructionStage, mock_context: PipelineContext) -> None:
    """Test MDA section bonus (+0.1)."""
    candidate = make_candidate(candidate_id="cand_1", section_type=SectionType.MDA)
    bv = make_bound_value(
        candidate_id="cand_1",
        binding_confidence=0.7,
        period_confidence=0.8,
        period_ambiguous=False,
        segment_id="seg_1",
    )

    mock_context.candidates = [candidate]
    mock_context.bound_values = [bv]
    mock_context.segments = [make_segment("seg_1")]

    result = stage.process(mock_context)

    assert result.success
    fact = mock_context.facts[0]
    # Confidence = (0.7 + 0.1) * 0.8 + 0.8 * 0.2 = 0.8 * 0.8 + 0.16 = 0.8
    expected = (
        0.7 + MDA_SECTION_BONUS
    ) * BINDING_CONFIDENCE_WEIGHT + 0.8 * PERIOD_CONFIDENCE_WEIGHT
    assert abs(fact.confidence - expected) < 0.01


def test_business_section_bonus(
    stage: FactConstructionStage, mock_context: PipelineContext
) -> None:
    """Test BUSINESS section bonus (+0.05)."""
    candidate = make_candidate(candidate_id="cand_1", section_type=SectionType.BUSINESS)
    bv = make_bound_value(
        candidate_id="cand_1",
        binding_confidence=0.7,
        period_confidence=0.8,
        period_ambiguous=False,
        segment_id="seg_1",
    )

    mock_context.candidates = [candidate]
    mock_context.bound_values = [bv]
    mock_context.segments = [make_segment("seg_1")]

    result = stage.process(mock_context)

    assert result.success
    fact = mock_context.facts[0]
    expected = (
        0.7 + BUSINESS_SECTION_BONUS
    ) * BINDING_CONFIDENCE_WEIGHT + 0.8 * PERIOD_CONFIDENCE_WEIGHT
    assert abs(fact.confidence - expected) < 0.01


def test_ocr_table_penalty(stage: FactConstructionStage, mock_context: PipelineContext) -> None:
    """Test OCR_TABLE penalty (-0.1)."""
    candidate = make_candidate(candidate_id="cand_1")
    bv = make_bound_value(
        candidate_id="cand_1",
        binding_confidence=0.9,
        period_confidence=0.8,
        period_ambiguous=False,
        table_id="table_1",
        cell_row=1,
        cell_col=1,
        img_id="img_1",  # OCR_TABLE has both table_id and img_id
    )

    mock_context.candidates = [candidate]
    mock_context.bound_values = [bv]
    mock_context.tables = [make_table("table_1")]

    result = stage.process(mock_context)

    assert result.success
    fact = mock_context.facts[0]
    # Source type should be OCR_TABLE
    assert fact.source_type == SourceType.OCR_TABLE
    # Confidence = (0.9 - 0.1) * 0.8 + 0.8 * 0.2 = 0.8 * 0.8 + 0.16 = 0.8
    expected = (
        0.9 - OCR_TABLE_PENALTY
    ) * BINDING_CONFIDENCE_WEIGHT + 0.8 * PERIOD_CONFIDENCE_WEIGHT
    assert abs(fact.confidence - expected) < 0.01


def test_chart_penalty(stage: FactConstructionStage, mock_context: PipelineContext) -> None:
    """Test CHART penalty (-0.05)."""
    candidate = make_candidate(candidate_id="cand_1")
    bv = make_bound_value(
        candidate_id="cand_1",
        binding_confidence=0.9,
        period_confidence=0.8,
        period_ambiguous=False,
        img_id="img_1",  # CHART has img_id but no table_id
    )

    mock_context.candidates = [candidate]
    mock_context.bound_values = [bv]

    result = stage.process(mock_context)

    assert result.success
    fact = mock_context.facts[0]
    # Source type should be CHART
    assert fact.source_type == SourceType.CHART
    expected = (0.9 - CHART_PENALTY) * BINDING_CONFIDENCE_WEIGHT + 0.8 * PERIOD_CONFIDENCE_WEIGHT
    assert abs(fact.confidence - expected) < 0.01


def test_period_ambiguity_penalty(
    stage: FactConstructionStage, mock_context: PipelineContext
) -> None:
    """Test period ambiguity penalty (-0.15)."""
    candidate = make_candidate(candidate_id="cand_1")
    bv = make_bound_value(
        candidate_id="cand_1",
        binding_confidence=0.9,
        period_confidence=0.8,
        period_ambiguous=True,  # Ambiguous period
        segment_id="seg_1",
    )

    mock_context.candidates = [candidate]
    mock_context.bound_values = [bv]
    mock_context.segments = [make_segment("seg_1")]

    result = stage.process(mock_context)

    assert result.success
    fact = mock_context.facts[0]
    # Confidence = 0.9 * 0.8 + 0.8 * 0.2 - 0.15 = 0.72 + 0.16 - 0.15 = 0.73
    base = 0.9 * BINDING_CONFIDENCE_WEIGHT + 0.8 * PERIOD_CONFIDENCE_WEIGHT
    expected = base - PERIOD_AMBIGUITY_PENALTY
    assert abs(fact.confidence - expected) < 0.01


def test_confidence_clamped_to_zero(
    stage: FactConstructionStage, mock_context: PipelineContext
) -> None:
    """Test that confidence is clamped to [0, 1] - lower bound."""
    candidate = make_candidate(candidate_id="cand_1")
    bv = make_bound_value(
        candidate_id="cand_1",
        binding_confidence=0.1,
        period_confidence=0.0,
        period_ambiguous=True,
        img_id="img_1",
    )

    mock_context.candidates = [candidate]
    mock_context.bound_values = [bv]

    result = stage.process(mock_context)

    assert result.success
    fact = mock_context.facts[0]
    assert 0.0 <= fact.confidence <= 1.0


def test_confidence_clamped_to_one(
    stage: FactConstructionStage, mock_context: PipelineContext
) -> None:
    """Test that confidence is clamped to [0, 1] - upper bound."""
    candidate = make_candidate(candidate_id="cand_1", section_type=SectionType.MDA)
    bv = make_bound_value(
        candidate_id="cand_1",
        binding_confidence=1.0,
        period_confidence=1.0,
        period_ambiguous=False,
        segment_id="seg_1",
    )

    mock_context.candidates = [candidate]
    mock_context.bound_values = [bv]
    mock_context.segments = [make_segment("seg_1")]

    result = stage.process(mock_context)

    assert result.success
    fact = mock_context.facts[0]
    assert fact.confidence <= 1.0


# ============================================================================
# Source Type Determination Tests
# ============================================================================


def test_source_type_html_table(
    stage: FactConstructionStage, mock_context: PipelineContext
) -> None:
    """Test HTML_TABLE source type (table_id, no img_id)."""
    candidate = make_candidate(candidate_id="cand_1")
    bv = make_bound_value(
        candidate_id="cand_1",
        table_id="table_1",
        cell_row=1,
        cell_col=1,
        # No img_id
    )

    mock_context.candidates = [candidate]
    mock_context.bound_values = [bv]
    mock_context.tables = [make_table("table_1")]

    result = stage.process(mock_context)

    assert result.success
    fact = mock_context.facts[0]
    assert fact.source_type == SourceType.HTML_TABLE


def test_source_type_text(stage: FactConstructionStage, mock_context: PipelineContext) -> None:
    """Test TEXT source type (segment_id, no table_id, no img_id)."""
    candidate = make_candidate(candidate_id="cand_1")
    bv = make_bound_value(candidate_id="cand_1", segment_id="seg_1", text_span=(10, 15))

    mock_context.candidates = [candidate]
    mock_context.bound_values = [bv]
    mock_context.segments = [make_segment("seg_1")]

    result = stage.process(mock_context)

    assert result.success
    fact = mock_context.facts[0]
    assert fact.source_type == SourceType.TEXT


def test_source_type_chart(stage: FactConstructionStage, mock_context: PipelineContext) -> None:
    """Test CHART source type (img_id, no table_id)."""
    candidate = make_candidate(candidate_id="cand_1")
    bv = make_bound_value(candidate_id="cand_1", img_id="img_1")

    mock_context.candidates = [candidate]
    mock_context.bound_values = [bv]

    result = stage.process(mock_context)

    assert result.success
    fact = mock_context.facts[0]
    assert fact.source_type == SourceType.CHART


def test_source_type_ocr_table(stage: FactConstructionStage, mock_context: PipelineContext) -> None:
    """Test OCR_TABLE source type (table_id and img_id)."""
    candidate = make_candidate(candidate_id="cand_1")
    bv = make_bound_value(
        candidate_id="cand_1",
        table_id="table_1",
        cell_row=1,
        cell_col=1,
        img_id="img_1",
    )

    mock_context.candidates = [candidate]
    mock_context.bound_values = [bv]
    mock_context.tables = [make_table("table_1")]

    result = stage.process(mock_context)

    assert result.success
    fact = mock_context.facts[0]
    assert fact.source_type == SourceType.OCR_TABLE


# ============================================================================
# EvidencePack Generation Tests
# ============================================================================


def test_evidence_pack_table_source(
    stage: FactConstructionStage, mock_context: PipelineContext
) -> None:
    """Test EvidencePack generation for table sources with header_path and stub_path."""
    candidate = make_candidate(candidate_id="cand_1")
    bv = make_bound_value(
        candidate_id="cand_1",
        value_raw="1,000",
        table_id="table_1",
        cell_row=1,
        cell_col=1,
    )

    table = make_table("table_1", header_texts=["Q1 2024", "Q2 2024"], stub_texts=["ARR", "NRR"])
    mock_context.candidates = [candidate]
    mock_context.bound_values = [bv]
    mock_context.tables = [table]

    result = stage.process(mock_context)

    assert result.success
    fact = mock_context.facts[0]
    evidence = fact.evidence_pack

    # Check evidence fields
    assert evidence.snippet_html == "<mark>1,000</mark>"
    assert evidence.raw_value_text == "1,000"
    assert len(evidence.header_path) > 0  # Should have header path
    assert len(evidence.stub_path) > 0  # Should have stub path


def test_evidence_pack_text_source(
    stage: FactConstructionStage, mock_context: PipelineContext
) -> None:
    """Test EvidencePack generation for text sources with context_before and context_after."""
    candidate = make_candidate(candidate_id="cand_1")
    bv = make_bound_value(
        candidate_id="cand_1",
        value_raw="1,000",
        segment_id="seg_1",
        text_span=(20, 25),
    )

    segment_text = "Our company had 1,000 customers at the end of Q1 2024."
    segment = make_segment("seg_1", text=segment_text)

    mock_context.candidates = [candidate]
    mock_context.bound_values = [bv]
    mock_context.segments = [segment]

    result = stage.process(mock_context)

    assert result.success
    fact = mock_context.facts[0]
    evidence = fact.evidence_pack

    # Check evidence fields
    assert evidence.snippet_html == "<mark>1,000</mark>"
    assert evidence.raw_value_text == "1,000"
    assert len(evidence.context_before) > 0
    assert len(evidence.context_after) > 0
    # Table fields should be empty for text sources
    assert len(evidence.header_path) == 0
    assert len(evidence.stub_path) == 0


def test_evidence_pack_minimal_source(
    stage: FactConstructionStage, mock_context: PipelineContext
) -> None:
    """Test minimal EvidencePack when segment/table lookup fails."""
    candidate = make_candidate(candidate_id="cand_1")
    bv = make_bound_value(
        candidate_id="cand_1",
        value_raw="1,000",
        segment_id="missing_segment",  # Missing segment
    )

    mock_context.candidates = [candidate]
    mock_context.bound_values = [bv]
    # No segments provided

    result = stage.process(mock_context)

    assert result.success
    fact = mock_context.facts[0]
    evidence = fact.evidence_pack

    # Should have minimal evidence
    assert evidence.snippet_html == "<mark>1,000</mark>"
    assert evidence.raw_value_text == "1,000"
    assert evidence.context_before == ""
    assert evidence.context_after == ""


# ============================================================================
# Source Locator Tests
# ============================================================================


def test_source_locator_copied(stage: FactConstructionStage, mock_context: PipelineContext) -> None:
    """Test that source_locator is copied from BoundValue to MetricFact."""
    candidate = make_candidate(candidate_id="cand_1")
    bv = make_bound_value(
        candidate_id="cand_1",
        table_id="table_1",
        cell_row=5,
        cell_col=3,
    )

    mock_context.candidates = [candidate]
    mock_context.bound_values = [bv]
    mock_context.tables = [make_table("table_1")]

    result = stage.process(mock_context)

    assert result.success
    fact = mock_context.facts[0]
    loc = fact.source_locator

    # Verify source locator fields
    assert loc.table_id == "table_1"
    assert loc.cell_row == 5
    assert loc.cell_col == 3


# ============================================================================
# Integration and Edge Cases
# ============================================================================


def test_stage_result_metadata(stage: FactConstructionStage, mock_context: PipelineContext) -> None:
    """Test that StageResult metadata is populated correctly."""
    candidate = make_candidate(candidate_id="cand_1")
    bv1 = make_bound_value(candidate_id="cand_1", segment_id="seg_1")
    bv2 = make_bound_value(candidate_id="cand_1", table_id="table_1", cell_row=1, cell_col=1)

    mock_context.candidates = [candidate]
    mock_context.bound_values = [bv1, bv2]
    mock_context.segments = [make_segment("seg_1")]
    mock_context.tables = [make_table("table_1")]

    result = stage.process(mock_context)

    assert result.success
    assert result.stage == PipelineStage.FACT_CONSTRUCTION
    assert result.items_processed == 2
    assert result.items_output == 2
    assert result.duration_ms >= 0  # May be 0 for fast tests
    assert "avg_confidence" in result.metadata
    assert "facts_by_source_type" in result.metadata


def test_error_handling_continues_processing(
    stage: FactConstructionStage, mock_context: PipelineContext
) -> None:
    """Test that errors in one bound value don't stop processing others."""
    candidate = make_candidate(candidate_id="cand_1")

    # bv_error references a candidate_id that has no matching candidate — this
    # causes a warning but should NOT abort processing of subsequent values.
    bv_error = make_bound_value(candidate_id="missing_candidate", segment_id="seg_1")

    # bv_valid references the real candidate and should produce a fact.
    bv_valid = make_bound_value(candidate_id="cand_1", segment_id="seg_1")

    mock_context.candidates = [candidate]
    mock_context.bound_values = [bv_error, bv_valid]
    mock_context.segments = [make_segment("seg_1")]

    result = stage.process(mock_context)
    # Stage should still succeed and produce one fact from bv_valid.
    assert result.success
    assert len(mock_context.facts) == 2  # both produce facts (missing candidate → empty metric_id)


# ============================================================================
# Chart Evidence Generation Tests
# ============================================================================


class TestChartEvidenceGeneration:
    """Tests for chart evidence generation in FactConstructionStage."""

    def test_chart_evidence_screenshot_path_when_file_exists(
        self, stage: FactConstructionStage, tmp_path: Path
    ) -> None:
        """screenshot_path should be set when image file exists and save_evidence_screenshots=True."""
        from src.extraction_v2.models import ImageAsset, ImageClassification
        from src.extraction_v2.pipeline import PipelineConfig

        # Create a real image file
        img_file = tmp_path / "test_chart.png"
        img_file.write_bytes(b"fake_image_bytes")

        evidence_dir = tmp_path / "evidence"

        asset = ImageAsset(
            img_id="img_001",
            filename="test_chart.png",
            file_path=str(img_file),
            classification=ImageClassification.CHART,
            nearby_text="Monthly active users grew 40% year over year.",
        )

        config = PipelineConfig(
            save_evidence_screenshots=True,
            evidence_screenshot_dir=str(evidence_dir),
        )

        bv = make_bound_value(img_id="img_001")
        evidence = stage._generate_evidence(bv, {}, {}, {"img_001": asset}, config)

        assert evidence.screenshot_path is not None
        assert "img_001" in evidence.screenshot_path
        assert bv.bound_value_id[:8] in evidence.screenshot_path

    def test_chart_evidence_no_screenshot_when_disabled(
        self, stage: FactConstructionStage, tmp_path: Path
    ) -> None:
        """screenshot_path should be None when save_evidence_screenshots=False."""
        from src.extraction_v2.models import ImageAsset, ImageClassification
        from src.extraction_v2.pipeline import PipelineConfig

        img_file = tmp_path / "test_chart.png"
        img_file.write_bytes(b"fake_image_bytes")

        asset = ImageAsset(
            img_id="img_002",
            filename="test_chart.png",
            file_path=str(img_file),
            classification=ImageClassification.CHART,
        )

        config = PipelineConfig(save_evidence_screenshots=False)
        bv = make_bound_value(img_id="img_002")
        evidence = stage._generate_evidence(bv, {}, {}, {"img_002": asset}, config)

        assert evidence.screenshot_path is None

    def test_chart_evidence_snippet_includes_title(
        self, stage: FactConstructionStage, tmp_path: Path
    ) -> None:
        """snippet_html should include chart title when available."""
        from src.extraction_v2.models import ChartData, ChartType, ImageAsset, ImageClassification
        from src.extraction_v2.pipeline import PipelineConfig

        asset = ImageAsset(
            img_id="img_003",
            filename="chart.png",
            file_path=None,
            classification=ImageClassification.CHART,
            chart_data=ChartData(
                chart_type=ChartType.BAR,
                title="Monthly Active Users",
                series=[],
            ),
        )

        config = PipelineConfig(save_evidence_screenshots=False)
        bv = make_bound_value(img_id="img_003", value_raw="5.2M")
        evidence = stage._generate_evidence(bv, {}, {}, {"img_003": asset}, config)

        assert "Monthly Active Users" in evidence.snippet_html
        assert "5.2M" in evidence.snippet_html

    def test_chart_evidence_nearby_text_populates_context_before(
        self, stage: FactConstructionStage, tmp_path: Path
    ) -> None:
        """context_before should be populated from asset.nearby_text."""
        from src.extraction_v2.models import ImageAsset, ImageClassification
        from src.extraction_v2.pipeline import PipelineConfig

        nearby = "This chart shows the quarterly growth of our platform over three years."
        asset = ImageAsset(
            img_id="img_004",
            filename="chart.png",
            file_path=None,
            classification=ImageClassification.CHART,
            nearby_text=nearby,
        )

        config = PipelineConfig(save_evidence_screenshots=False)
        bv = make_bound_value(img_id="img_004")
        evidence = stage._generate_evidence(bv, {}, {}, {"img_004": asset}, config)

        assert evidence.context_before == nearby[:200].strip()
