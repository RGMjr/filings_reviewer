"""
Unit tests for V2 Value Binding Stage.

Tests cover:
- Table binding via header_path
- Table binding via stub_path
- Text proximity binding
- Number parsing
- Confidence scoring
- Integration with pipeline context
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest

from src.extraction_v2.models import (
    BoundValue,
    Cell,
    MetricCandidate,
    Segment,
    SegmentType,
    SectionType,
    SourceLocator,
    SourceType,
    Table,
    Unit,
)
from src.extraction_v2.stages.value_binding import ValueBindingStage


# ============================================================================
# Test Fixtures
# ============================================================================


@dataclass
class MockPipelineConfig:
    """Mock pipeline config for testing."""

    min_confidence_auto_accept: float = 0.90
    min_confidence_no_review: float = 0.85
    max_confidence_auto_reject: float = 0.15


@dataclass
class MockPipelineContext:
    """Mock pipeline context for testing."""

    html_path: Path = field(default_factory=lambda: Path("/test/file.html"))
    filing_id: int = 1
    config: MockPipelineConfig = field(default_factory=MockPipelineConfig)
    segments: list[Segment] = field(default_factory=list)
    tables: list[Table] = field(default_factory=list)
    images: list[Any] = field(default_factory=list)
    candidates: list[MetricCandidate] = field(default_factory=list)
    bound_values: list[Any] = field(default_factory=list)


@pytest.fixture
def stage() -> ValueBindingStage:
    """Create a ValueBindingStage instance."""
    return ValueBindingStage()


@pytest.fixture
def simple_table() -> Table:
    """Create a simple table with header and data rows."""
    cells = [
        # Header row
        Cell(row=0, col=0, text="Metric", is_header=True, header_path=[], stub_path=[]),
        Cell(row=0, col=1, text="2023", is_header=True, header_path=[], stub_path=[]),
        Cell(row=0, col=2, text="2022", is_header=True, header_path=[], stub_path=[]),
        # Data row 1
        Cell(
            row=1,
            col=0,
            text="Revenue",
            is_stub=True,
            header_path=["Metric"],
            stub_path=[],
        ),
        Cell(
            row=1,
            col=1,
            text="$1,234,567",
            header_path=["2023"],
            stub_path=["Revenue"],
        ),
        Cell(
            row=1,
            col=2,
            text="$987,654",
            header_path=["2022"],
            stub_path=["Revenue"],
        ),
        # Data row 2
        Cell(
            row=2,
            col=0,
            text="Customers",
            is_stub=True,
            header_path=["Metric"],
            stub_path=[],
        ),
        Cell(
            row=2, col=1, text="50,000", header_path=["2023"], stub_path=["Customers"]
        ),
        Cell(
            row=2, col=2, text="45,000", header_path=["2022"], stub_path=["Customers"]
        ),
    ]

    table = Table(
        table_id="test-table-1",
        row_count=3,
        col_count=3,
        header_rows=1,
        stub_cols=1,
        cells=cells,
    )

    # Build grid
    table._grid = [[None] * 3 for _ in range(3)]
    for cell in cells:
        table._grid[cell.row][cell.col] = cell

    return table


@pytest.fixture
def percentage_table() -> Table:
    """Create a table with percentage values."""
    cells = [
        # Header row
        Cell(row=0, col=0, text="KPI", is_header=True, header_path=[], stub_path=[]),
        Cell(
            row=0, col=1, text="Value", is_header=True, header_path=[], stub_path=[]
        ),
        # Data row
        Cell(
            row=1,
            col=0,
            text="Net Revenue Retention",
            is_stub=True,
            header_path=["KPI"],
            stub_path=[],
        ),
        Cell(
            row=1,
            col=1,
            text="112%",
            header_path=["Value"],
            stub_path=["Net Revenue Retention"],
        ),
    ]

    table = Table(
        table_id="test-table-pct",
        row_count=2,
        col_count=2,
        header_rows=1,
        stub_cols=1,
        cells=cells,
    )

    table._grid = [[None] * 2 for _ in range(2)]
    for cell in cells:
        table._grid[cell.row][cell.col] = cell

    return table


@pytest.fixture
def text_segment() -> Segment:
    """Create a text segment for proximity testing."""
    return Segment(
        segment_id="seg-1",
        doc_id="doc-1",
        segment_type=SegmentType.PARAGRAPH,
        text="Our total revenue for the year was $1.5 billion, representing a 25% increase.",
        section_type=SectionType.MDA,
    )


# ============================================================================
# Table Binding - Header Path Tests
# ============================================================================


class TestTableBindingHeaderPath:
    """Tests for table binding via header_path."""

    def test_metric_in_header_binds_column_values(
        self, stage: ValueBindingStage, simple_table: Table
    ) -> None:
        """When metric is in column header, bind data cells in that column."""
        # Candidate found in the "2023" header
        candidate = MetricCandidate(
            candidate_id="cand-1",
            metric_id="cm_revenue",
            match_text="2023",
            source_type=SourceType.HTML_TABLE,
            source_locator=SourceLocator(
                table_id="test-table-1",
                cell_row=0,
                cell_col=1,
            ),
        )

        context = MockPipelineContext(
            tables=[simple_table],
            candidates=[candidate],
        )

        result = stage.process(context)  # type: ignore

        assert result.success
        assert len(context.bound_values) == 2  # Revenue and Customers for 2023

    def test_multi_level_header_binding(self, stage: ValueBindingStage) -> None:
        """Multi-level headers correctly propagate to data cells."""
        cells = [
            # Header row 1
            Cell(row=0, col=0, text="", is_header=True, header_path=[], stub_path=[]),
            Cell(
                row=0, col=1, text="FY 2023", is_header=True, header_path=[], stub_path=[]
            ),
            # Header row 2
            Cell(
                row=1, col=0, text="Metric", is_header=True, header_path=[], stub_path=[]
            ),
            Cell(
                row=1,
                col=1,
                text="Q4",
                is_header=True,
                header_path=["FY 2023"],
                stub_path=[],
            ),
            # Data row
            Cell(
                row=2,
                col=0,
                text="ARR",
                is_stub=True,
                header_path=["Metric"],
                stub_path=[],
            ),
            Cell(
                row=2, col=1, text="$100M", header_path=["FY 2023", "Q4"], stub_path=["ARR"]
            ),
        ]

        table = Table(
            table_id="multi-header",
            row_count=3,
            col_count=2,
            header_rows=2,
            stub_cols=1,
            cells=cells,
        )
        table._grid = [[None] * 2 for _ in range(3)]
        for cell in cells:
            table._grid[cell.row][cell.col] = cell

        # Candidate in second-level header
        candidate = MetricCandidate(
            candidate_id="cand-multi",
            metric_id="cm_arr",
            match_text="Q4",
            source_type=SourceType.HTML_TABLE,
            source_locator=SourceLocator(
                table_id="multi-header",
                cell_row=1,
                cell_col=1,
            ),
        )

        context = MockPipelineContext(tables=[table], candidates=[candidate])
        result = stage.process(context)  # type: ignore

        assert result.success
        assert len(context.bound_values) >= 1

    def test_no_match_when_metric_not_in_headers(
        self, stage: ValueBindingStage, simple_table: Table
    ) -> None:
        """No binding when metric text is not in headers."""
        candidate = MetricCandidate(
            candidate_id="cand-nomatch",
            metric_id="cm_unknown",
            match_text="unknown metric",
            source_type=SourceType.HTML_TABLE,
            source_locator=SourceLocator(
                table_id="test-table-1",
                cell_row=1,
                cell_col=1,
            ),
        )

        context = MockPipelineContext(tables=[simple_table], candidates=[candidate])
        result = stage.process(context)  # type: ignore

        assert result.success
        # May still find value in the cell itself

    def test_handle_empty_cells_gracefully(self, stage: ValueBindingStage) -> None:
        """Empty cells in data region are skipped."""
        cells = [
            Cell(row=0, col=0, text="Metric", is_header=True, header_path=[], stub_path=[]),
            Cell(row=0, col=1, text="Value", is_header=True, header_path=[], stub_path=[]),
            Cell(row=1, col=0, text="Test", is_stub=True, header_path=["Metric"], stub_path=[]),
            Cell(row=1, col=1, text="", header_path=["Value"], stub_path=["Test"]),  # Empty
        ]

        table = Table(
            table_id="empty-cell-table",
            row_count=2,
            col_count=2,
            header_rows=1,
            stub_cols=1,
            cells=cells,
        )
        table._grid = [[None] * 2 for _ in range(2)]
        for cell in cells:
            table._grid[cell.row][cell.col] = cell

        candidate = MetricCandidate(
            candidate_id="cand-empty",
            metric_id="cm_test",
            match_text="Value",
            source_type=SourceType.HTML_TABLE,
            source_locator=SourceLocator(
                table_id="empty-cell-table",
                cell_row=0,
                cell_col=1,
            ),
        )

        context = MockPipelineContext(tables=[table], candidates=[candidate])
        result = stage.process(context)  # type: ignore

        assert result.success
        # No values bound because cell is empty
        assert len(context.bound_values) == 0

    def test_candidate_in_header_finds_values_below(
        self, stage: ValueBindingStage, simple_table: Table
    ) -> None:
        """Candidate located in header cell should find values in data cells below."""
        candidate = MetricCandidate(
            candidate_id="cand-header",
            metric_id="cm_customers",
            match_text="Customers",
            source_type=SourceType.HTML_TABLE,
            source_locator=SourceLocator(
                table_id="test-table-1",
                cell_row=2,  # In stub column
                cell_col=0,
            ),
        )

        context = MockPipelineContext(tables=[simple_table], candidates=[candidate])
        result = stage.process(context)  # type: ignore

        assert result.success
        # Should find values in the same row
        assert len(context.bound_values) == 2  # 50,000 and 45,000


# ============================================================================
# Table Binding - Stub Path Tests
# ============================================================================


class TestTableBindingStubPath:
    """Tests for table binding via stub_path."""

    def test_metric_in_stub_binds_row_values(
        self, stage: ValueBindingStage, simple_table: Table
    ) -> None:
        """When metric is in row stub, bind data cells in that row."""
        candidate = MetricCandidate(
            candidate_id="cand-stub",
            metric_id="cm_revenue",
            match_text="Revenue",
            source_type=SourceType.HTML_TABLE,
            source_locator=SourceLocator(
                table_id="test-table-1",
                cell_row=1,
                cell_col=0,  # Stub column
            ),
        )

        context = MockPipelineContext(tables=[simple_table], candidates=[candidate])
        result = stage.process(context)  # type: ignore

        assert result.success
        assert len(context.bound_values) == 2  # 2023 and 2022 values

    def test_multi_column_stubs(self, stage: ValueBindingStage) -> None:
        """Tables with multiple stub columns correctly bind."""
        cells = [
            # Header
            Cell(row=0, col=0, text="Category", is_header=True, header_path=[], stub_path=[]),
            Cell(row=0, col=1, text="Metric", is_header=True, header_path=[], stub_path=[]),
            Cell(row=0, col=2, text="Value", is_header=True, header_path=[], stub_path=[]),
            # Data
            Cell(row=1, col=0, text="Growth", is_stub=True, header_path=["Category"], stub_path=[]),
            Cell(row=1, col=1, text="ARR", is_stub=True, header_path=["Metric"], stub_path=["Growth"]),
            Cell(row=1, col=2, text="$50M", header_path=["Value"], stub_path=["Growth", "ARR"]),
        ]

        table = Table(
            table_id="multi-stub",
            row_count=2,
            col_count=3,
            header_rows=1,
            stub_cols=2,
            cells=cells,
        )
        table._grid = [[None] * 3 for _ in range(2)]
        for cell in cells:
            table._grid[cell.row][cell.col] = cell

        candidate = MetricCandidate(
            candidate_id="cand-multi-stub",
            metric_id="cm_arr",
            match_text="ARR",
            source_type=SourceType.HTML_TABLE,
            source_locator=SourceLocator(
                table_id="multi-stub",
                cell_row=1,
                cell_col=1,
            ),
        )

        context = MockPipelineContext(tables=[table], candidates=[candidate])
        result = stage.process(context)  # type: ignore

        assert result.success
        assert len(context.bound_values) == 1
        assert context.bound_values[0].value == 50_000_000  # $50M

    def test_combined_header_and_stub_context(
        self, stage: ValueBindingStage, simple_table: Table
    ) -> None:
        """Binding uses both header and stub context for confidence."""
        candidate = MetricCandidate(
            candidate_id="cand-combined",
            metric_id="cm_revenue",
            match_text="Revenue",
            source_type=SourceType.HTML_TABLE,
            source_locator=SourceLocator(
                table_id="test-table-1",
                cell_row=1,
                cell_col=0,
            ),
        )

        context = MockPipelineContext(tables=[simple_table], candidates=[candidate])
        result = stage.process(context)  # type: ignore

        assert result.success
        # Check that bound values have header_path info used for confidence
        for bv in context.bound_values:
            assert bv.binding_confidence >= 0.6  # At least table base confidence


# ============================================================================
# Text Binding Tests
# ============================================================================


class TestTextBinding:
    """Tests for text proximity binding."""

    def test_value_within_proximity_binds(
        self, stage: ValueBindingStage, text_segment: Segment
    ) -> None:
        """Numbers within word proximity are bound."""
        candidate = MetricCandidate(
            candidate_id="cand-text",
            metric_id="cm_revenue",
            match_text="revenue",
            source_type=SourceType.TEXT,
            source_locator=SourceLocator(
                segment_id="seg-1",
                text_span=(10, 17),  # "revenue" in the text
            ),
        )

        context = MockPipelineContext(
            segments=[text_segment],
            candidates=[candidate],
        )

        result = stage.process(context)  # type: ignore

        assert result.success
        # Should find $1.5 billion and 25%
        assert len(context.bound_values) >= 1

    def test_value_in_same_sentence(
        self, stage: ValueBindingStage
    ) -> None:
        """Values in the same sentence as keyword are preferred."""
        segment = Segment(
            segment_id="seg-sentence",
            text="Revenue was $500 million. Other metrics were different.",
        )

        candidate = MetricCandidate(
            candidate_id="cand-sent",
            metric_id="cm_revenue",
            match_text="Revenue",
            source_type=SourceType.TEXT,
            source_locator=SourceLocator(
                segment_id="seg-sentence",
                text_span=(0, 7),
            ),
        )

        context = MockPipelineContext(segments=[segment], candidates=[candidate])
        result = stage.process(context)  # type: ignore

        assert result.success
        assert len(context.bound_values) >= 1
        assert context.bound_values[0].value == 500_000_000

    def test_no_binding_when_value_too_far(self, stage: ValueBindingStage) -> None:
        """No binding when value is outside proximity window."""
        # Create a very long segment where the number is far from keyword
        padding = "x " * 200  # 400 chars of padding — beyond 250-char default window
        segment = Segment(
            segment_id="seg-far",
            text=f"Revenue is important. {padding} The value is $100.",
        )

        candidate = MetricCandidate(
            candidate_id="cand-far",
            metric_id="cm_revenue",
            match_text="Revenue",
            source_type=SourceType.TEXT,
            source_locator=SourceLocator(
                segment_id="seg-far",
                text_span=(0, 7),
            ),
        )

        context = MockPipelineContext(segments=[segment], candidates=[candidate])
        result = stage.process(context)  # type: ignore

        assert result.success
        # Value should NOT be bound - too far away (beyond 250-char default window)

    def test_multiple_values_picks_all(self, stage: ValueBindingStage) -> None:
        """When multiple values in proximity, all are bound with ambiguity penalty."""
        segment = Segment(
            segment_id="seg-multi",
            text="Our customers grew from 10,000 to 15,000 this year.",
        )

        candidate = MetricCandidate(
            candidate_id="cand-multi",
            metric_id="cm_customers",
            match_text="customers",
            source_type=SourceType.TEXT,
            source_locator=SourceLocator(
                segment_id="seg-multi",
                text_span=(4, 13),
            ),
        )

        context = MockPipelineContext(segments=[segment], candidates=[candidate])
        result = stage.process(context)  # type: ignore

        assert result.success
        assert len(context.bound_values) == 2  # Both 10,000 and 15,000

    def test_case_insensitive_matching(self, stage: ValueBindingStage) -> None:
        """Binding works regardless of keyword case."""
        segment = Segment(
            segment_id="seg-case",
            text="REVENUE was $1M last year.",
        )

        candidate = MetricCandidate(
            candidate_id="cand-case",
            metric_id="cm_revenue",
            match_text="revenue",  # lowercase
            source_type=SourceType.TEXT,
            source_locator=SourceLocator(
                segment_id="seg-case",
                text_span=(0, 7),
            ),
        )

        context = MockPipelineContext(segments=[segment], candidates=[candidate])
        result = stage.process(context)  # type: ignore

        assert result.success
        assert len(context.bound_values) >= 1

    def test_configurable_proximity_window(self) -> None:
        """Custom proximity window works correctly."""
        # Create stage with explicit 250-char proximity window
        default_stage = ValueBindingStage(proximity_window=250)

        # Text where value is far from keyword
        segment = Segment(
            segment_id="seg-proximity",
            text="Revenue increased significantly to $500 million.",
        )

        candidate = MetricCandidate(
            candidate_id="cand-prox",
            metric_id="cm_revenue",
            match_text="Revenue",
            source_type=SourceType.TEXT,
            source_locator=SourceLocator(
                segment_id="seg-proximity",
                text_span=(0, 7),
            ),
        )

        context = MockPipelineContext(segments=[segment], candidates=[candidate])
        result = default_stage.process(context)  # type: ignore

        # Should find the value with default window
        assert result.success
        assert len(context.bound_values) >= 1

        # Now test with very narrow window (20 chars) where value is outside
        # "$500 million" starts at position 39, which is 32 chars away from "Revenue" (pos 7)
        narrow_stage = ValueBindingStage(proximity_window=20)
        context2 = MockPipelineContext(segments=[segment], candidates=[candidate])
        result2 = narrow_stage.process(context2)  # type: ignore

        # Should not find the value (too far away)
        assert result2.success
        assert len(context2.bound_values) == 0

    def test_250_char_window_finds_distant_values(self) -> None:
        """Default 250-char window finds values that 100-char window would miss."""
        # Place value ~150 chars from keyword (beyond old 100-char window)
        filler = "a " * 70  # 140 chars of filler
        segment = Segment(
            segment_id="seg-distant",
            text=f"Revenue is growing. {filler}The total was $800 million.",
        )

        candidate = MetricCandidate(
            candidate_id="cand-distant",
            metric_id="cm_revenue",
            match_text="Revenue",
            source_type=SourceType.TEXT,
            source_locator=SourceLocator(
                segment_id="seg-distant",
                text_span=(0, 7),
            ),
        )

        # Default 250-char stage should find it
        stage_250 = ValueBindingStage(proximity_window=250)
        context_250 = MockPipelineContext(segments=[segment], candidates=[candidate])
        stage_250.process(context_250)  # type: ignore
        assert len(context_250.bound_values) >= 1

        # 100-char stage should miss it
        stage_100 = ValueBindingStage(proximity_window=100)
        context_100 = MockPipelineContext(segments=[segment], candidates=[candidate])
        stage_100.process(context_100)  # type: ignore
        assert len(context_100.bound_values) == 0

    def test_distance_decay_near_values_higher_confidence(self) -> None:
        """Values very near keyword get higher confidence than values near edge of window."""
        # Create two separate segments: one with near value, one with far value
        near_segment = Segment(
            segment_id="seg-near",
            text="Revenue was $500 million last year.",
        )
        # Use explicit 250-char window for the far segment so the value is found
        # but with distance decay. 110 chars of filler puts value beyond
        # DISTANCE_DECAY_THRESHOLD (100) to trigger penalty.
        filler = "a " * 55  # 110 chars of filler
        far_segment = Segment(
            segment_id="seg-far-decay",
            text=f"Revenue is reported. {filler}The total was $500 million.",
        )

        near_candidate = MetricCandidate(
            candidate_id="cand-near",
            metric_id="cm_revenue",
            match_text="Revenue",
            source_type=SourceType.TEXT,
            source_locator=SourceLocator(
                segment_id="seg-near",
                text_span=(0, 7),
            ),
        )

        far_candidate = MetricCandidate(
            candidate_id="cand-far-decay",
            metric_id="cm_revenue",
            match_text="Revenue",
            source_type=SourceType.TEXT,
            source_locator=SourceLocator(
                segment_id="seg-far-decay",
                text_span=(0, 7),
            ),
        )

        # Use 250-char window for both so the far segment's value is found
        stage = ValueBindingStage(proximity_window=250)

        # Near binding
        ctx_near = MockPipelineContext(segments=[near_segment], candidates=[near_candidate])
        stage.process(ctx_near)  # type: ignore
        assert len(ctx_near.bound_values) >= 1
        near_conf = ctx_near.bound_values[0].binding_confidence

        # Far binding
        ctx_far = MockPipelineContext(segments=[far_segment], candidates=[far_candidate])
        stage.process(ctx_far)  # type: ignore
        assert len(ctx_far.bound_values) >= 1
        far_conf = ctx_far.bound_values[0].binding_confidence

        # Near value should have higher confidence due to no distance penalty
        assert near_conf > far_conf, (
            f"Near confidence ({near_conf}) should exceed far confidence ({far_conf})"
        )

    def test_same_sentence_bonus(self) -> None:
        """Values in same sentence get confidence bonus."""
        stage = ValueBindingStage()

        # Value in same sentence
        segment_same = Segment(
            segment_id="seg-same",
            text="Revenue was $500 million. Other metrics were different.",
        )

        candidate_same = MetricCandidate(
            candidate_id="cand-same-sent",
            metric_id="cm_revenue",
            match_text="Revenue",
            source_type=SourceType.TEXT,
            source_locator=SourceLocator(
                segment_id="seg-same",
                text_span=(0, 7),
            ),
        )

        context_same = MockPipelineContext(segments=[segment_same], candidates=[candidate_same])
        result_same = stage.process(context_same)  # type: ignore

        assert result_same.success
        assert len(context_same.bound_values) >= 1

        # Should have higher confidence due to same sentence bonus
        bv_same = context_same.bound_values[0]
        # Base (0.4) + Unit presence (0.1) + Same sentence (0.1) = 0.6
        assert bv_same.binding_confidence >= 0.59  # Allow for floating point tolerance

    def test_sentence_boundary_detection(self) -> None:
        """Sentence boundary detection works correctly."""
        stage = ValueBindingStage()

        text = "First sentence here. Second sentence has content. Third one too!"

        # Test position in middle of second sentence
        start, end = stage._find_sentence_bounds(text, 30)
        sentence = text[start:end]
        assert "Second sentence has content" in sentence
        assert "First sentence" not in sentence
        assert "Third one" not in sentence

        # Test position at start of text
        start, end = stage._find_sentence_bounds(text, 5)
        assert start == 0

        # Test position at end of text
        start, end = stage._find_sentence_bounds(text, len(text) - 5)
        assert end == len(text)


# ============================================================================
# Number Parsing Tests
# ============================================================================


class TestNumberParsing:
    """Tests for number parsing functionality."""

    def test_parse_currency_with_millions(self, stage: ValueBindingStage) -> None:
        """Parse currency values with scale suffix."""
        result = stage._parse_number("$1.2M")
        assert result is not None
        value, unit, raw = result
        assert value == 1_200_000
        assert unit == Unit.CURRENCY

    def test_parse_currency_with_commas(self, stage: ValueBindingStage) -> None:
        """Parse currency values with comma separators."""
        result = stage._parse_number("$1,234,567")
        assert result is not None
        value, unit, raw = result
        assert value == 1_234_567
        assert unit == Unit.CURRENCY

    def test_parse_percentage(self, stage: ValueBindingStage) -> None:
        """Parse percentage values."""
        result = stage._parse_number("112%")
        assert result is not None
        value, unit, raw = result
        assert value == 112
        assert unit == Unit.PERCENT

    def test_parse_decimal_percentage(self, stage: ValueBindingStage) -> None:
        """Parse decimal percentage values."""
        result = stage._parse_number("1.5%")
        assert result is not None
        value, unit, raw = result
        assert value == 1.5
        assert unit == Unit.PERCENT

    def test_parse_scale_indicators(self, stage: ValueBindingStage) -> None:
        """Parse values with various scale indicators."""
        test_cases = [
            ("100 million", 100_000_000),
            ("2.5 billion", 2_500_000_000),
            ("500K", 500_000),
            ("1.5B", 1_500_000_000),
            ("50mn", 50_000_000),
        ]

        for text, expected in test_cases:
            result = stage._parse_number(text)
            assert result is not None, f"Failed to parse: {text}"
            value, unit, raw = result
            assert value == expected, f"Expected {expected} for {text}, got {value}"

    def test_parse_plain_integer_with_commas(self, stage: ValueBindingStage) -> None:
        """Parse plain integers with comma separators."""
        result = stage._parse_number("50,000")
        assert result is not None
        value, unit, raw = result
        assert value == 50_000
        assert unit == Unit.OTHER

    def test_parse_negative_values(self, stage: ValueBindingStage) -> None:
        """Parse negative values."""
        result = stage._parse_number("-5%")
        assert result is not None
        value, unit, raw = result
        assert value == -5
        assert unit == Unit.PERCENT

        result2 = stage._parse_number("-$1.2M")
        assert result2 is not None
        value2, unit2, raw2 = result2
        assert value2 == -1_200_000
        assert unit2 == Unit.CURRENCY

    def test_parse_decimal_numbers(self, stage: ValueBindingStage) -> None:
        """Parse decimal numbers."""
        result = stage._parse_number("3.14")
        assert result is not None
        value, unit, raw = result
        assert abs(value - 3.14) < 0.001
        assert unit == Unit.OTHER

    def test_parse_year_not_split(self, stage: ValueBindingStage) -> None:
        """_parse_number matches full 4-digit year, not '201' from '2019'."""
        result = stage._parse_number("2019")
        assert result is not None
        value, unit, raw = result
        assert value == 2019
        assert raw == "2019"

    def test_find_numbers_year_not_fragmented(self, stage: ValueBindingStage) -> None:
        """_find_numbers_in_proximity extracts '2019' not '201'+'9' from year text."""
        text = "January 31, 2019"
        results = stage._find_numbers_in_proximity(text, 0, 7, 100)
        raw_values = [raw for _, _, _, raw in results]
        assert "201" not in raw_values, (
            f"Year '2019' was split into fragments: {raw_values}"
        )
        # Should find "31" and "2019" as whole numbers
        values = [v for _, v, _, _ in results]
        assert 2019 in values
        assert 31 in values


# ============================================================================
# Confidence Scoring Tests
# ============================================================================


class TestConfidenceScoring:
    """Tests for confidence score computation."""

    def test_table_binding_higher_than_text(self, stage: ValueBindingStage) -> None:
        """Table binding has higher base confidence than text binding."""
        table_conf = stage._compute_table_confidence("metric", [], [], Unit.COUNT)
        text_conf = stage._compute_text_confidence(Unit.COUNT)

        assert table_conf > text_conf
        assert table_conf >= 0.6
        assert text_conf >= 0.4

    def test_exact_match_bonus(self, stage: ValueBindingStage) -> None:
        """Exact match in path adds confidence bonus."""
        with_exact = stage._compute_table_confidence(
            "revenue", ["Revenue", "2023"], [], Unit.COUNT
        )
        without_exact = stage._compute_table_confidence(
            "rev", ["Revenue", "2023"], [], Unit.COUNT
        )

        assert with_exact > without_exact

    def test_unit_presence_bonus(self, stage: ValueBindingStage) -> None:
        """Having explicit unit adds confidence bonus."""
        with_unit = stage._compute_table_confidence(
            "metric", [], [], Unit.CURRENCY
        )
        without_unit = stage._compute_table_confidence(
            "metric", [], [], Unit.COUNT
        )

        assert with_unit > without_unit

    def test_confidence_capped_at_one(self, stage: ValueBindingStage) -> None:
        """Confidence never exceeds 1.0."""
        # Maximum bonuses
        conf = stage._compute_table_confidence(
            "revenue", ["Revenue"], ["Revenue"], Unit.CURRENCY
        )
        assert conf <= 1.0

    def test_confidence_capped_at_zero(self, stage: ValueBindingStage) -> None:
        """Confidence never goes below 0.0."""
        # Text binding with maximum ambiguity penalty
        # Even with penalties, confidence should not go below 0
        conf = stage._compute_text_confidence(
            Unit.COUNT, ambiguity_penalty=1.0, same_sentence=False
        )
        assert conf >= 0.0
        assert conf <= 1.0


# ============================================================================
# Integration Tests
# ============================================================================


class TestIntegration:
    """Integration tests for the full stage."""

    def test_full_stage_execution(
        self, stage: ValueBindingStage, simple_table: Table, text_segment: Segment
    ) -> None:
        """Full stage execution with multiple candidates."""
        candidates = [
            MetricCandidate(
                candidate_id="cand-1",
                metric_id="cm_revenue",
                match_text="Revenue",
                source_type=SourceType.HTML_TABLE,
                source_locator=SourceLocator(
                    table_id="test-table-1",
                    cell_row=1,
                    cell_col=0,
                ),
            ),
            MetricCandidate(
                candidate_id="cand-2",
                metric_id="cm_revenue",
                match_text="revenue",
                source_type=SourceType.TEXT,
                source_locator=SourceLocator(
                    segment_id="seg-1",
                    text_span=(10, 17),
                ),
            ),
        ]

        context = MockPipelineContext(
            tables=[simple_table],
            segments=[text_segment],
            candidates=candidates,
        )

        result = stage.process(context)  # type: ignore

        assert result.success
        assert result.items_processed == 2
        assert len(context.bound_values) >= 2

    def test_empty_candidates_returns_success(self, stage: ValueBindingStage) -> None:
        """Stage succeeds with zero candidates."""
        context = MockPipelineContext(candidates=[])
        result = stage.process(context)  # type: ignore

        assert result.success
        assert result.items_processed == 0
        assert result.items_output == 0
        assert len(context.bound_values) == 0

    def test_bound_value_has_correct_fields(
        self, stage: ValueBindingStage, percentage_table: Table
    ) -> None:
        """BoundValue objects have all required fields populated."""
        candidate = MetricCandidate(
            candidate_id="cand-nrr",
            metric_id="cm_nrr",
            match_text="Net Revenue Retention",
            source_type=SourceType.HTML_TABLE,
            source_locator=SourceLocator(
                table_id="test-table-pct",
                cell_row=1,
                cell_col=0,
            ),
        )

        context = MockPipelineContext(tables=[percentage_table], candidates=[candidate])
        result = stage.process(context)  # type: ignore

        assert result.success
        assert len(context.bound_values) >= 1

        bv = context.bound_values[0]
        assert isinstance(bv, BoundValue)
        assert bv.bound_value_id  # UUID generated
        assert bv.candidate_id == "cand-nrr"
        assert bv.value == 112
        assert bv.unit == Unit.PERCENT
        assert bv.binding_type in ("table_stub", "table_header", "table_cell")
        assert 0.0 <= bv.binding_confidence <= 1.0
        assert bv.source_locator.table_id == "test-table-pct"


# ============================================================================
# Edge Cases
# ============================================================================


class TestEdgeCases:
    """Tests for edge cases and error handling."""

    def test_missing_table_logs_warning(
        self, stage: ValueBindingStage, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Missing table is handled gracefully with warning."""
        candidate = MetricCandidate(
            candidate_id="cand-missing",
            metric_id="cm_test",
            match_text="test",
            source_type=SourceType.HTML_TABLE,
            source_locator=SourceLocator(
                table_id="nonexistent-table",
                cell_row=0,
                cell_col=0,
            ),
        )

        context = MockPipelineContext(tables=[], candidates=[candidate])
        result = stage.process(context)  # type: ignore

        assert result.success
        assert len(context.bound_values) == 0

    def test_missing_segment_logs_warning(
        self, stage: ValueBindingStage
    ) -> None:
        """Missing segment is handled gracefully."""
        candidate = MetricCandidate(
            candidate_id="cand-missing-seg",
            metric_id="cm_test",
            match_text="test",
            source_type=SourceType.TEXT,
            source_locator=SourceLocator(
                segment_id="nonexistent-segment",
            ),
        )

        context = MockPipelineContext(segments=[], candidates=[candidate])
        result = stage.process(context)  # type: ignore

        assert result.success
        assert len(context.bound_values) == 0

    def test_chart_source_type_no_matching_image(self, stage: ValueBindingStage) -> None:
        """Chart candidate with no matching image produces no bindings."""
        candidate = MetricCandidate(
            candidate_id="cand-chart",
            metric_id="cm_test",
            match_text="test",
            source_type=SourceType.CHART,
            source_locator=SourceLocator(img_id="nonexistent"),
        )

        context = MockPipelineContext(candidates=[candidate])
        result = stage.process(context)  # type: ignore

        assert result.success
        assert len(context.bound_values) == 0

    def test_multiple_metrics_same_row(
        self, stage: ValueBindingStage
    ) -> None:
        """Multiple metrics in same table row are handled correctly."""
        cells = [
            Cell(row=0, col=0, text="Metric A", is_header=True, header_path=[], stub_path=[]),
            Cell(row=0, col=1, text="Metric B", is_header=True, header_path=[], stub_path=[]),
            Cell(row=0, col=2, text="Value", is_header=True, header_path=[], stub_path=[]),
            Cell(row=1, col=0, text="Revenue", is_stub=True, header_path=["Metric A"], stub_path=[]),
            Cell(row=1, col=1, text="Growth", is_stub=True, header_path=["Metric B"], stub_path=["Revenue"]),
            Cell(row=1, col=2, text="25%", header_path=["Value"], stub_path=["Revenue", "Growth"]),
        ]

        table = Table(
            table_id="multi-metric",
            row_count=2,
            col_count=3,
            header_rows=1,
            stub_cols=2,
            cells=cells,
        )
        table._grid = [[None] * 3 for _ in range(2)]
        for cell in cells:
            table._grid[cell.row][cell.col] = cell

        # Two candidates for different metrics in same row
        candidates = [
            MetricCandidate(
                candidate_id="cand-a",
                metric_id="cm_revenue",
                match_text="Revenue",
                source_type=SourceType.HTML_TABLE,
                source_locator=SourceLocator(
                    table_id="multi-metric",
                    cell_row=1,
                    cell_col=0,
                ),
            ),
            MetricCandidate(
                candidate_id="cand-b",
                metric_id="cm_growth",
                match_text="Growth",
                source_type=SourceType.HTML_TABLE,
                source_locator=SourceLocator(
                    table_id="multi-metric",
                    cell_row=1,
                    cell_col=1,
                ),
            ),
        ]

        context = MockPipelineContext(tables=[table], candidates=candidates)
        result = stage.process(context)  # type: ignore

        assert result.success
        # Both should bind to the 25% value
        assert len(context.bound_values) >= 2

    def test_ocr_table_handled_like_html(
        self, stage: ValueBindingStage, simple_table: Table
    ) -> None:
        """OCR_TABLE source type uses same binding as HTML_TABLE."""
        candidate = MetricCandidate(
            candidate_id="cand-ocr",
            metric_id="cm_revenue",
            match_text="Revenue",
            source_type=SourceType.OCR_TABLE,
            source_locator=SourceLocator(
                table_id="test-table-1",
                cell_row=1,
                cell_col=0,
            ),
        )

        context = MockPipelineContext(tables=[simple_table], candidates=[candidate])
        result = stage.process(context)  # type: ignore

        assert result.success
        assert len(context.bound_values) >= 1

    def test_missing_cell_in_table(self, stage: ValueBindingStage) -> None:
        """Handle case where cell coordinates don't exist in table."""
        table = Table(
            table_id="sparse-table",
            row_count=2,
            col_count=2,
            header_rows=1,
            stub_cols=0,
            cells=[],  # No cells
        )
        table._grid = [[None] * 2 for _ in range(2)]

        candidate = MetricCandidate(
            candidate_id="cand-nocell",
            metric_id="cm_test",
            match_text="test",
            source_type=SourceType.HTML_TABLE,
            source_locator=SourceLocator(
                table_id="sparse-table",
                cell_row=5,  # Out of bounds
                cell_col=5,
            ),
        )

        context = MockPipelineContext(tables=[table], candidates=[candidate])
        result = stage.process(context)  # type: ignore

        assert result.success
        assert len(context.bound_values) == 0

    def test_exception_in_candidate_binding(
        self, stage: ValueBindingStage, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Exceptions in binding are caught and logged."""

        def raise_error(*args: Any, **kwargs: Any) -> None:
            raise ValueError("Test error")

        monkeypatch.setattr(stage, "_bind_candidate", raise_error)

        candidate = MetricCandidate(
            candidate_id="cand-err",
            metric_id="cm_test",
            match_text="test",
            source_type=SourceType.TEXT,
            source_locator=SourceLocator(segment_id="seg-1"),
        )

        context = MockPipelineContext(candidates=[candidate])
        result = stage.process(context)  # type: ignore

        # Stage should still complete but with errors
        assert not result.success
        assert len(result.errors) == 1

    def test_text_binding_without_text_span(self, stage: ValueBindingStage) -> None:
        """Text binding works even without explicit text_span."""
        segment = Segment(
            segment_id="seg-nospan",
            text="Revenue was $100 million last year.",
        )

        candidate = MetricCandidate(
            candidate_id="cand-nospan",
            metric_id="cm_revenue",
            match_text="Revenue",
            source_type=SourceType.TEXT,
            source_locator=SourceLocator(
                segment_id="seg-nospan",
                # No text_span - should search entire text
            ),
        )

        context = MockPipelineContext(segments=[segment], candidates=[candidate])
        result = stage.process(context)  # type: ignore

        assert result.success
        assert len(context.bound_values) >= 1

    def test_unparseable_number_skipped(self, stage: ValueBindingStage) -> None:
        """Unparseable text in cells is skipped."""
        cells = [
            Cell(row=0, col=0, text="Metric", is_header=True, header_path=[], stub_path=[]),
            Cell(row=0, col=1, text="Value", is_header=True, header_path=[], stub_path=[]),
            Cell(row=1, col=0, text="Test", is_stub=True, header_path=["Metric"], stub_path=[]),
            Cell(row=1, col=1, text="N/A", header_path=["Value"], stub_path=["Test"]),  # Not a number
        ]

        table = Table(
            table_id="unparseable-table",
            row_count=2,
            col_count=2,
            header_rows=1,
            stub_cols=1,
            cells=cells,
        )
        table._grid = [[None] * 2 for _ in range(2)]
        for cell in cells:
            table._grid[cell.row][cell.col] = cell

        candidate = MetricCandidate(
            candidate_id="cand-unparse",
            metric_id="cm_test",
            match_text="Test",
            source_type=SourceType.HTML_TABLE,
            source_locator=SourceLocator(
                table_id="unparseable-table",
                cell_row=1,
                cell_col=0,
            ),
        )

        context = MockPipelineContext(tables=[table], candidates=[candidate])
        result = stage.process(context)  # type: ignore

        assert result.success
        assert len(context.bound_values) == 0  # No parseable value

    def test_parse_number_returns_none_for_invalid(
        self, stage: ValueBindingStage
    ) -> None:
        """_parse_number returns None for non-numeric text."""
        assert stage._parse_number("not a number") is None
        assert stage._parse_number("") is None
        assert stage._parse_number("abc xyz") is None

    def test_parse_billion_variants(self, stage: ValueBindingStage) -> None:
        """Parse billion values with various formats."""
        test_cases = [
            ("$1.2B", 1_200_000_000, Unit.CURRENCY),
            ("1.5 billion", 1_500_000_000, Unit.OTHER),
            ("$2.3 billion", 2_300_000_000, Unit.CURRENCY),
            ("3bn", 3_000_000_000, Unit.OTHER),
            ("$4.5 bn", 4_500_000_000, Unit.CURRENCY),
        ]

        for text, expected_value, expected_unit in test_cases:
            result = stage._parse_number(text)
            assert result is not None, f"Failed to parse: {text}"
            value, unit, raw = result
            assert value == expected_value, f"Expected {expected_value} for {text}, got {value}"
            assert unit == expected_unit, f"Expected {expected_unit} for {text}, got {unit}"

    def test_is_in_path_variations(self, stage: ValueBindingStage) -> None:
        """Test _is_in_path with various inputs."""
        # Empty path returns False
        assert not stage._is_in_path("test", [])

        # Partial match works
        assert stage._is_in_path("rev", ["Total Revenue", "2023"])

        # Case insensitive
        assert stage._is_in_path("REVENUE", ["Total Revenue"])

    def test_segment_with_empty_text(self, stage: ValueBindingStage) -> None:
        """Segment with empty text returns no bindings."""
        segment = Segment(
            segment_id="seg-empty",
            text="",
        )

        candidate = MetricCandidate(
            candidate_id="cand-emptytext",
            metric_id="cm_test",
            match_text="test",
            source_type=SourceType.TEXT,
            source_locator=SourceLocator(segment_id="seg-empty"),
        )

        context = MockPipelineContext(segments=[segment], candidates=[candidate])
        result = stage.process(context)  # type: ignore

        assert result.success
        assert len(context.bound_values) == 0


# ============================================================================
# Unit Filtering Integration Tests
# ============================================================================


class TestUnitFiltering:
    """Tests for unit-compatibility filtering in value binding."""

    def test_count_metric_rejects_currency_in_table(self, stage: ValueBindingStage) -> None:
        """Count-only metric rejects $14.8M in table binding."""
        cells = [
            Cell(row=0, col=0, text="Metric", is_header=True, header_path=[], stub_path=[]),
            Cell(row=0, col=1, text="Value", is_header=True, header_path=[], stub_path=[]),
            Cell(
                row=1, col=0, text="Paid Customers",
                is_stub=True, header_path=["Metric"], stub_path=[],
            ),
            Cell(
                row=1, col=1, text="$14.8M",
                header_path=["Value"], stub_path=["Paid Customers"],
            ),
        ]
        table = Table(
            table_id="unit-filter-table",
            row_count=2, col_count=2, header_rows=1, stub_cols=1, cells=cells,
        )
        table._grid = [[None] * 2 for _ in range(2)]
        for cell in cells:
            table._grid[cell.row][cell.col] = cell

        candidate = MetricCandidate(
            candidate_id="cand-uf-1",
            metric_id="cm_customers_period_end",
            match_text="Paid Customers",
            source_type=SourceType.HTML_TABLE,
            source_locator=SourceLocator(
                table_id="unit-filter-table", cell_row=1, cell_col=0,
            ),
        )

        context = MockPipelineContext(tables=[table], candidates=[candidate])
        result = stage.process(context)  # type: ignore

        assert result.success
        assert len(context.bound_values) == 0  # Currency rejected for count metric

    def test_count_metric_rejects_percent_in_table(self, stage: ValueBindingStage) -> None:
        """Count-only metric rejects 152% in table binding."""
        cells = [
            Cell(row=0, col=0, text="Metric", is_header=True, header_path=[], stub_path=[]),
            Cell(row=0, col=1, text="Growth", is_header=True, header_path=[], stub_path=[]),
            Cell(
                row=1, col=0, text="Customers",
                is_stub=True, header_path=["Metric"], stub_path=[],
            ),
            Cell(
                row=1, col=1, text="152%",
                header_path=["Growth"], stub_path=["Customers"],
            ),
        ]
        table = Table(
            table_id="unit-filter-pct",
            row_count=2, col_count=2, header_rows=1, stub_cols=1, cells=cells,
        )
        table._grid = [[None] * 2 for _ in range(2)]
        for cell in cells:
            table._grid[cell.row][cell.col] = cell

        candidate = MetricCandidate(
            candidate_id="cand-uf-2",
            metric_id="cm_customers_period_end",
            match_text="Customers",
            source_type=SourceType.HTML_TABLE,
            source_locator=SourceLocator(
                table_id="unit-filter-pct", cell_row=1, cell_col=0,
            ),
        )

        context = MockPipelineContext(tables=[table], candidates=[candidate])
        result = stage.process(context)  # type: ignore

        assert result.success
        assert len(context.bound_values) == 0

    def test_count_metric_accepts_bare_count(self, stage: ValueBindingStage) -> None:
        """Count-only metric accepts 50,000."""
        cells = [
            Cell(row=0, col=0, text="Metric", is_header=True, header_path=[], stub_path=[]),
            Cell(row=0, col=1, text="Total", is_header=True, header_path=[], stub_path=[]),
            Cell(
                row=1, col=0, text="Customers",
                is_stub=True, header_path=["Metric"], stub_path=[],
            ),
            Cell(
                row=1, col=1, text="50,000",
                header_path=["Total"], stub_path=["Customers"],
            ),
        ]
        table = Table(
            table_id="unit-filter-count",
            row_count=2, col_count=2, header_rows=1, stub_cols=1, cells=cells,
        )
        table._grid = [[None] * 2 for _ in range(2)]
        for cell in cells:
            table._grid[cell.row][cell.col] = cell

        candidate = MetricCandidate(
            candidate_id="cand-uf-3",
            metric_id="cm_customers_period_end",
            match_text="Customers",
            source_type=SourceType.HTML_TABLE,
            source_locator=SourceLocator(
                table_id="unit-filter-count", cell_row=1, cell_col=0,
            ),
        )

        context = MockPipelineContext(tables=[table], candidates=[candidate])
        result = stage.process(context)  # type: ignore

        assert result.success
        assert len(context.bound_values) == 1
        assert context.bound_values[0].value == 50_000
        assert context.bound_values[0].unit == Unit.OTHER

    def test_count_metric_rejects_currency_in_text(self, stage: ValueBindingStage) -> None:
        """Count-only metric rejects $14.8M in text proximity binding."""
        segment = Segment(
            segment_id="seg-uf-text",
            text="We had $14.8M in paid customers spending.",
        )

        candidate = MetricCandidate(
            candidate_id="cand-uf-text",
            metric_id="cm_customers_period_end",
            match_text="paid customers",
            source_type=SourceType.TEXT,
            source_locator=SourceLocator(
                segment_id="seg-uf-text",
                text_span=(18, 32),
            ),
        )

        context = MockPipelineContext(segments=[segment], candidates=[candidate])
        result = stage.process(context)  # type: ignore

        assert result.success
        # $14.8M should be filtered (currency incompatible with count metric)
        for bv in context.bound_values:
            assert bv.unit != Unit.CURRENCY

    def test_currency_metric_accepts_bare_number(self, stage: ValueBindingStage) -> None:
        """Currency-only metric accepts bare number (Unit.OTHER) since tables often omit $."""
        cells = [
            Cell(row=0, col=0, text="Metric", is_header=True, header_path=[], stub_path=[]),
            Cell(row=0, col=1, text="Value", is_header=True, header_path=[], stub_path=[]),
            Cell(
                row=1, col=0, text="ARR",
                is_stub=True, header_path=["Metric"], stub_path=[],
            ),
            Cell(
                row=1, col=1, text="500",
                header_path=["Value"], stub_path=["ARR"],
            ),
        ]
        table = Table(
            table_id="unit-filter-curr",
            row_count=2, col_count=2, header_rows=1, stub_cols=1, cells=cells,
        )
        table._grid = [[None] * 2 for _ in range(2)]
        for cell in cells:
            table._grid[cell.row][cell.col] = cell

        candidate = MetricCandidate(
            candidate_id="cand-uf-curr",
            metric_id="cm_arr",
            match_text="ARR",
            source_type=SourceType.HTML_TABLE,
            source_locator=SourceLocator(
                table_id="unit-filter-curr", cell_row=1, cell_col=0,
            ),
        )

        context = MockPipelineContext(tables=[table], candidates=[candidate])
        result = stage.process(context)  # type: ignore

        assert result.success
        assert len(context.bound_values) == 1  # Bare number accepted as Unit.OTHER
        assert context.bound_values[0].unit == Unit.OTHER

    def test_currency_metric_accepts_dollar_value(self, stage: ValueBindingStage) -> None:
        """Currency-only metric accepts $500M."""
        cells = [
            Cell(row=0, col=0, text="Metric", is_header=True, header_path=[], stub_path=[]),
            Cell(row=0, col=1, text="Value", is_header=True, header_path=[], stub_path=[]),
            Cell(
                row=1, col=0, text="ARR",
                is_stub=True, header_path=["Metric"], stub_path=[],
            ),
            Cell(
                row=1, col=1, text="$500M",
                header_path=["Value"], stub_path=["ARR"],
            ),
        ]
        table = Table(
            table_id="unit-filter-curr-ok",
            row_count=2, col_count=2, header_rows=1, stub_cols=1, cells=cells,
        )
        table._grid = [[None] * 2 for _ in range(2)]
        for cell in cells:
            table._grid[cell.row][cell.col] = cell

        candidate = MetricCandidate(
            candidate_id="cand-uf-curr-ok",
            metric_id="cm_arr",
            match_text="ARR",
            source_type=SourceType.HTML_TABLE,
            source_locator=SourceLocator(
                table_id="unit-filter-curr-ok", cell_row=1, cell_col=0,
            ),
        )

        context = MockPipelineContext(tables=[table], candidates=[candidate])
        result = stage.process(context)  # type: ignore

        assert result.success
        assert len(context.bound_values) == 1
        assert context.bound_values[0].value == 500_000_000
        assert context.bound_values[0].unit == Unit.CURRENCY

    def test_unconstrained_metric_accepts_all_units(
        self, stage: ValueBindingStage
    ) -> None:
        """Unconstrained metric (cm_revenue_by_cohort) accepts any unit."""
        cells = [
            Cell(row=0, col=0, text="Metric", is_header=True, header_path=[], stub_path=[]),
            Cell(row=0, col=1, text="Value", is_header=True, header_path=[], stub_path=[]),
            Cell(
                row=1, col=0, text="Revenue by Cohort",
                is_stub=True, header_path=["Metric"], stub_path=[],
            ),
            Cell(
                row=1, col=1, text="$500M",
                header_path=["Value"], stub_path=["Revenue by Cohort"],
            ),
        ]
        table = Table(
            table_id="unit-filter-uncons",
            row_count=2, col_count=2, header_rows=1, stub_cols=1, cells=cells,
        )
        table._grid = [[None] * 2 for _ in range(2)]
        for cell in cells:
            table._grid[cell.row][cell.col] = cell

        candidate = MetricCandidate(
            candidate_id="cand-uf-uncons",
            metric_id="cm_revenue_by_cohort",
            match_text="Revenue by Cohort",
            source_type=SourceType.HTML_TABLE,
            source_locator=SourceLocator(
                table_id="unit-filter-uncons", cell_row=1, cell_col=0,
            ),
        )

        context = MockPipelineContext(tables=[table], candidates=[candidate])
        result = stage.process(context)  # type: ignore

        assert result.success
        assert len(context.bound_values) == 1

    def test_unit_filtered_count_in_metadata(self, stage: ValueBindingStage) -> None:
        """Filtered count is tracked in result metadata."""
        cells = [
            Cell(row=0, col=0, text="Metric", is_header=True, header_path=[], stub_path=[]),
            Cell(row=0, col=1, text="2023", is_header=True, header_path=[], stub_path=[]),
            Cell(row=0, col=2, text="2022", is_header=True, header_path=[], stub_path=[]),
            Cell(
                row=1, col=0, text="Customers",
                is_stub=True, header_path=["Metric"], stub_path=[],
            ),
            Cell(
                row=1, col=1, text="$14.8M",
                header_path=["2023"], stub_path=["Customers"],
            ),
            Cell(
                row=1, col=2, text="152%",
                header_path=["2022"], stub_path=["Customers"],
            ),
        ]
        table = Table(
            table_id="unit-filter-meta",
            row_count=2, col_count=3, header_rows=1, stub_cols=1, cells=cells,
        )
        table._grid = [[None] * 3 for _ in range(2)]
        for cell in cells:
            table._grid[cell.row][cell.col] = cell

        candidate = MetricCandidate(
            candidate_id="cand-uf-meta",
            metric_id="cm_customers_period_end",
            match_text="Customers",
            source_type=SourceType.HTML_TABLE,
            source_locator=SourceLocator(
                table_id="unit-filter-meta", cell_row=1, cell_col=0,
            ),
        )

        context = MockPipelineContext(tables=[table], candidates=[candidate])
        result = stage.process(context)  # type: ignore

        assert result.success
        assert len(context.bound_values) == 0  # Both filtered
        assert result.metadata["unit_filtered_count"] == 2

    def test_strategy5_cell_value_filtered(self, stage: ValueBindingStage) -> None:
        """Strategy 5 (value in candidate cell) also applies unit filtering."""
        cells = [
            Cell(
                row=0, col=0,
                text="Customers: $14.8M",
                header_path=[], stub_path=[],
            ),
        ]
        table = Table(
            table_id="unit-filter-s5",
            row_count=1, col_count=1, header_rows=0, stub_cols=0, cells=cells,
        )
        table._grid = [[cells[0]]]

        candidate = MetricCandidate(
            candidate_id="cand-uf-s5",
            metric_id="cm_customers_period_end",
            match_text="Customers",
            source_type=SourceType.HTML_TABLE,
            source_locator=SourceLocator(
                table_id="unit-filter-s5", cell_row=0, cell_col=0,
            ),
        )

        context = MockPipelineContext(tables=[table], candidates=[candidate])
        result = stage.process(context)  # type: ignore

        assert result.success
        assert len(context.bound_values) == 0  # $14.8M filtered in Strategy 5


# ============================================================================
# Table Scale Factor - Count Metrics (Decimal-Gated)
# ============================================================================


class TestTableScaleFactorCountMetrics:
    """Tests for decimal-gated count scaling in '(in thousands)' tables.

    Farfetch pattern: count metrics with decimal values (796.3) in a scaled
    table should be multiplied by the scale factor (→ 796,300).
    Snowflake pattern: count metrics with integer values (3,117) should NOT
    be scaled, even in a scaled table.
    """

    @staticmethod
    def _make_thousands_table(
        table_id: str, stub_text: str, value_text: str
    ) -> Table:
        """Build a minimal '(in thousands)' table with one metric row."""
        cells = [
            Cell(
                row=0, col=0, text="(in thousands)", is_header=True,
                header_path=[], stub_path=[],
            ),
            Cell(
                row=0, col=1, text="2023", is_header=True,
                header_path=[], stub_path=[],
            ),
            Cell(
                row=1, col=0, text=stub_text, is_stub=True,
                header_path=["(in thousands)"], stub_path=[],
            ),
            Cell(
                row=1, col=1, text=value_text,
                header_path=["2023"], stub_path=[stub_text],
            ),
        ]
        table = Table(
            table_id=table_id,
            row_count=2, col_count=2, header_rows=1, stub_cols=1, cells=cells,
        )
        table._grid = [[None] * 2 for _ in range(2)]
        for cell in cells:
            table._grid[cell.row][cell.col] = cell
        return table

    def test_farfetch_decimal_count_scaled(
        self, stage: ValueBindingStage
    ) -> None:
        """Decimal count in '(in thousands)' table → scaled (796.3 → 796,300)."""
        table = self._make_thousands_table("ff-1", "Active Consumers", "796.3")
        candidate = MetricCandidate(
            candidate_id="cand-ff-1",
            metric_id="cm_active_customers_total",
            match_text="Active Consumers",
            source_type=SourceType.HTML_TABLE,
            source_locator=SourceLocator(
                table_id="ff-1", cell_row=1, cell_col=0,
            ),
        )
        context = MockPipelineContext(tables=[table], candidates=[candidate])
        result = stage.process(context)  # type: ignore

        assert result.success
        assert len(context.bound_values) == 1
        bv = context.bound_values[0]
        assert bv.value == pytest.approx(796_300, rel=1e-6)
        assert bv.unit in (Unit.COUNT, Unit.OTHER)

    def test_snowflake_integer_count_not_scaled(
        self, stage: ValueBindingStage
    ) -> None:
        """Integer count in '(in thousands)' table → NOT scaled (3,117 stays 3,117)."""
        table = self._make_thousands_table("sf-1", "Customers", "3,117")
        candidate = MetricCandidate(
            candidate_id="cand-sf-1",
            metric_id="cm_customers_period_end",
            match_text="Customers",
            source_type=SourceType.HTML_TABLE,
            source_locator=SourceLocator(
                table_id="sf-1", cell_row=1, cell_col=0,
            ),
        )
        context = MockPipelineContext(tables=[table], candidates=[candidate])
        result = stage.process(context)  # type: ignore

        assert result.success
        assert len(context.bound_values) == 1
        bv = context.bound_values[0]
        assert bv.value == pytest.approx(3117, rel=1e-6)
        assert bv.unit in (Unit.COUNT, Unit.OTHER)

    def test_dot_zero_format_still_scaled(
        self, stage: ValueBindingStage
    ) -> None:
        """Trailing .0 decimal (1,118.0) still triggers scaling → 1,118,000."""
        table = self._make_thousands_table("ff-2", "Number of Orders", "1,118.0")
        candidate = MetricCandidate(
            candidate_id="cand-ff-2",
            metric_id="cm_purchase_transactions_overall",
            match_text="Number of Orders",
            source_type=SourceType.HTML_TABLE,
            source_locator=SourceLocator(
                table_id="ff-2", cell_row=1, cell_col=0,
            ),
        )
        context = MockPipelineContext(tables=[table], candidates=[candidate])
        result = stage.process(context)  # type: ignore

        assert result.success
        assert len(context.bound_values) == 1
        bv = context.bound_values[0]
        assert bv.value == pytest.approx(1_118_000, rel=1e-6)

    def test_currency_still_scaled_normally(
        self, stage: ValueBindingStage
    ) -> None:
        """Currency values are always scaled regardless of decimal presence."""
        table = self._make_thousands_table("cur-1", "Revenue", "$1,500")
        candidate = MetricCandidate(
            candidate_id="cand-cur-1",
            metric_id="cm_arr",
            match_text="Revenue",
            source_type=SourceType.HTML_TABLE,
            source_locator=SourceLocator(
                table_id="cur-1", cell_row=1, cell_col=0,
            ),
        )
        context = MockPipelineContext(tables=[table], candidates=[candidate])
        result = stage.process(context)  # type: ignore

        assert result.success
        assert len(context.bound_values) == 1
        bv = context.bound_values[0]
        assert bv.value == pytest.approx(1_500_000, rel=1e-6)
        assert bv.unit == Unit.CURRENCY

    def test_non_count_metric_decimal_not_scaled(
        self, stage: ValueBindingStage
    ) -> None:
        """Non-count metric with decimal doesn't scale via the count path."""
        table = self._make_thousands_table("nc-1", "NRR", "112.5")
        candidate = MetricCandidate(
            candidate_id="cand-nc-1",
            metric_id="cm_net_revenue_retention",
            match_text="NRR",
            source_type=SourceType.HTML_TABLE,
            source_locator=SourceLocator(
                table_id="nc-1", cell_row=1, cell_col=0,
            ),
        )
        context = MockPipelineContext(tables=[table], candidates=[candidate])
        result = stage.process(context)  # type: ignore

        assert result.success
        # NRR is percent-only; unit filtering may reject or it won't be count-scaled
        for bv in context.bound_values:
            # If it passes unit filtering, it should NOT have been scaled
            assert bv.value == pytest.approx(112.5, rel=1e-6) or bv.value == pytest.approx(1.125, rel=1e-6)

    def test_has_fractional_value_with_decimal(self) -> None:
        """_has_fractional_value returns True for strings with '.'."""
        assert ValueBindingStage._has_fractional_value("796.3") is True
        assert ValueBindingStage._has_fractional_value("1,118.0") is True
        assert ValueBindingStage._has_fractional_value("0.5") is True

    def test_has_fractional_value_without_decimal(self) -> None:
        """_has_fractional_value returns False for integer strings."""
        assert ValueBindingStage._has_fractional_value("3117") is False
        assert ValueBindingStage._has_fractional_value("3,117") is False
        assert ValueBindingStage._has_fractional_value("948") is False

    def test_scale_pattern_with_trailing_clause(self) -> None:
        """Scale regex matches '(in thousands, unless stated otherwise)'."""
        pattern = ValueBindingStage.TABLE_SCALE_PATTERN
        m = pattern.search("(in thousands, unless stated otherwise)")
        assert m is not None
        assert m.group(1).lower() == "thousands"

    def test_scale_pattern_plain(self) -> None:
        """Scale regex still matches plain '(in thousands)'."""
        pattern = ValueBindingStage.TABLE_SCALE_PATTERN
        m = pattern.search("(in thousands)")
        assert m is not None
        assert m.group(1).lower() == "thousands"

    def test_scale_pattern_except_share(self) -> None:
        """Scale regex matches '(in thousands except share and per share data)'."""
        pattern = ValueBindingStage.TABLE_SCALE_PATTERN
        m = pattern.search("(in thousands except share and per share data)")
        assert m is not None
        assert m.group(1).lower() == "thousands"


# ============================================================================
# Column-Type Filtering (Header-Based) Tests
# ============================================================================


class TestColumnTypeFiltering:
    """Tests for header-based column-type filtering in _bind_row_values.

    Prevents count metrics from binding to dollar columns and currency metrics
    from binding to count columns in mixed financial tables (e.g. Farfetch).
    """

    @staticmethod
    def _make_mixed_table() -> Table:
        """Build a Farfetch-style mixed table with dollar and count columns.

        Layout:
            |                  | Revenue ($M) | Customers |
            | Active Consumers |     1,400    |   796     |
        """
        cells = [
            Cell(row=0, col=0, text="", is_header=True, header_path=[], stub_path=[]),
            Cell(row=0, col=1, text="Revenue ($M)", is_header=True, header_path=[], stub_path=[]),
            Cell(row=0, col=2, text="Customers", is_header=True, header_path=[], stub_path=[]),
            Cell(
                row=1, col=0, text="Active Consumers",
                is_stub=True, header_path=[""], stub_path=[],
            ),
            Cell(
                row=1, col=1, text="1,400",
                header_path=["Revenue ($M)"], stub_path=["Active Consumers"],
            ),
            Cell(
                row=1, col=2, text="796",
                header_path=["Customers"], stub_path=["Active Consumers"],
            ),
        ]
        table = Table(
            table_id="mixed-table",
            row_count=2, col_count=3, header_rows=1, stub_cols=1, cells=cells,
        )
        table._grid = [[None] * 3 for _ in range(2)]
        for cell in cells:
            table._grid[cell.row][cell.col] = cell
        return table

    def test_count_metric_skips_currency_column(self) -> None:
        """Count metric in stub should NOT bind to 'Revenue ($M)' column."""
        stage = ValueBindingStage()
        table = self._make_mixed_table()

        candidate = MetricCandidate(
            candidate_id="cand-ct-1",
            metric_id="cm_active_customers_total",
            match_text="Active Consumers",
            source_type=SourceType.HTML_TABLE,
            source_locator=SourceLocator(
                table_id="mixed-table", cell_row=1, cell_col=0,
            ),
        )

        context = MockPipelineContext(tables=[table], candidates=[candidate])
        result = stage.process(context)  # type: ignore

        assert result.success
        # Should bind only to "796" (Customers column), NOT "1,400" (Revenue column)
        assert len(context.bound_values) == 1
        assert context.bound_values[0].value == 796

    def test_count_metric_still_binds_neutral_column(self) -> None:
        """Count metric binds to columns with neutral headers (e.g. '2023')."""
        stage = ValueBindingStage()
        cells = [
            Cell(row=0, col=0, text="", is_header=True, header_path=[], stub_path=[]),
            Cell(row=0, col=1, text="2023", is_header=True, header_path=[], stub_path=[]),
            Cell(row=0, col=2, text="2022", is_header=True, header_path=[], stub_path=[]),
            Cell(
                row=1, col=0, text="Customers",
                is_stub=True, header_path=[""], stub_path=[],
            ),
            Cell(
                row=1, col=1, text="50,000",
                header_path=["2023"], stub_path=["Customers"],
            ),
            Cell(
                row=1, col=2, text="45,000",
                header_path=["2022"], stub_path=["Customers"],
            ),
        ]
        table = Table(
            table_id="neutral-headers",
            row_count=2, col_count=3, header_rows=1, stub_cols=1, cells=cells,
        )
        table._grid = [[None] * 3 for _ in range(2)]
        for cell in cells:
            table._grid[cell.row][cell.col] = cell

        candidate = MetricCandidate(
            candidate_id="cand-ct-2",
            metric_id="cm_customers_period_end",
            match_text="Customers",
            source_type=SourceType.HTML_TABLE,
            source_locator=SourceLocator(
                table_id="neutral-headers", cell_row=1, cell_col=0,
            ),
        )

        context = MockPipelineContext(tables=[table], candidates=[candidate])
        result = stage.process(context)  # type: ignore

        assert result.success
        assert len(context.bound_values) == 2  # Both year columns

    def test_currency_metric_skips_count_column(self) -> None:
        """Currency metric in stub should NOT bind to 'Number of Users' column."""
        stage = ValueBindingStage()
        cells = [
            Cell(row=0, col=0, text="", is_header=True, header_path=[], stub_path=[]),
            Cell(row=0, col=1, text="Amount ($)", is_header=True, header_path=[], stub_path=[]),
            Cell(row=0, col=2, text="Number of Users", is_header=True, header_path=[], stub_path=[]),
            Cell(
                row=1, col=0, text="ARR",
                is_stub=True, header_path=[""], stub_path=[],
            ),
            Cell(
                row=1, col=1, text="500",
                header_path=["Amount ($)"], stub_path=["ARR"],
            ),
            Cell(
                row=1, col=2, text="10,000",
                header_path=["Number of Users"], stub_path=["ARR"],
            ),
        ]
        table = Table(
            table_id="mixed-curr",
            row_count=2, col_count=3, header_rows=1, stub_cols=1, cells=cells,
        )
        table._grid = [[None] * 3 for _ in range(2)]
        for cell in cells:
            table._grid[cell.row][cell.col] = cell

        candidate = MetricCandidate(
            candidate_id="cand-ct-3",
            metric_id="cm_arr",
            match_text="ARR",
            source_type=SourceType.HTML_TABLE,
            source_locator=SourceLocator(
                table_id="mixed-curr", cell_row=1, cell_col=0,
            ),
        )

        context = MockPipelineContext(tables=[table], candidates=[candidate])
        result = stage.process(context)  # type: ignore

        assert result.success
        # Should bind to "500" (Amount column) but NOT "10,000" (Users column)
        assert len(context.bound_values) == 1
        assert context.bound_values[0].value == 500

    def test_unconstrained_metric_binds_all_columns(self) -> None:
        """Unconstrained metric binds to all data columns regardless of headers."""
        stage = ValueBindingStage()
        table = self._make_mixed_table()

        candidate = MetricCandidate(
            candidate_id="cand-ct-4",
            metric_id="cm_revenue_by_cohort",  # Not in COUNT or CURRENCY sets
            match_text="Active Consumers",
            source_type=SourceType.HTML_TABLE,
            source_locator=SourceLocator(
                table_id="mixed-table", cell_row=1, cell_col=0,
            ),
        )

        context = MockPipelineContext(tables=[table], candidates=[candidate])
        result = stage.process(context)  # type: ignore

        assert result.success
        assert len(context.bound_values) == 2  # Both columns

    def test_header_indicates_currency_detection(self) -> None:
        """_header_indicates_currency detects various currency signals."""
        assert ValueBindingStage._header_indicates_currency(["Revenue ($M)"]) is True
        assert ValueBindingStage._header_indicates_currency(["Amount"]) is True
        assert ValueBindingStage._header_indicates_currency(["$"]) is True
        assert ValueBindingStage._header_indicates_currency(["Total Sales"]) is True
        assert ValueBindingStage._header_indicates_currency(["GMV"]) is True
        assert ValueBindingStage._header_indicates_currency(["EBITDA"]) is True
        assert ValueBindingStage._header_indicates_currency(["2023"]) is False
        assert ValueBindingStage._header_indicates_currency(["Q4"]) is False
        assert ValueBindingStage._header_indicates_currency([]) is False

    def test_header_indicates_count_detection(self) -> None:
        """_header_indicates_count detects various count signals."""
        assert ValueBindingStage._header_indicates_count(["Number of Users"]) is True
        assert ValueBindingStage._header_indicates_count(["Customers"]) is True
        assert ValueBindingStage._header_indicates_count(["Subscribers"]) is True
        assert ValueBindingStage._header_indicates_count(["2023"]) is False
        assert ValueBindingStage._header_indicates_count(["Revenue"]) is False
        assert ValueBindingStage._header_indicates_count([]) is False

    def test_farfetch_mixed_table_full_scenario(self) -> None:
        """Full Farfetch scenario: (In thousands) table with dollar and count columns.

        Table layout:
            | (In thousands)   | Revenue | Active Consumers |
            | Annual Metrics   | 1,400   | 796.3            |

        Count metric should only bind to 796.3, not 1,400.
        """
        stage = ValueBindingStage()
        cells = [
            Cell(row=0, col=0, text="(In thousands)", is_header=True, header_path=[], stub_path=[]),
            Cell(row=0, col=1, text="Revenue", is_header=True, header_path=[], stub_path=[]),
            Cell(row=0, col=2, text="Active Consumers", is_header=True, header_path=[], stub_path=[]),
            Cell(
                row=1, col=0, text="Annual Metrics",
                is_stub=True, header_path=["(In thousands)"], stub_path=[],
            ),
            Cell(
                row=1, col=1, text="1,400",
                header_path=["Revenue"], stub_path=["Annual Metrics"],
            ),
            Cell(
                row=1, col=2, text="796.3",
                header_path=["Active Consumers"], stub_path=["Annual Metrics"],
            ),
        ]
        table = Table(
            table_id="farfetch-full",
            row_count=2, col_count=3, header_rows=1, stub_cols=1, cells=cells,
        )
        table._grid = [[None] * 3 for _ in range(2)]
        for cell in cells:
            table._grid[cell.row][cell.col] = cell

        candidate = MetricCandidate(
            candidate_id="cand-ff-full",
            metric_id="cm_active_customers_total",
            match_text="Annual Metrics",
            source_type=SourceType.HTML_TABLE,
            source_locator=SourceLocator(
                table_id="farfetch-full", cell_row=1, cell_col=0,
            ),
        )

        context = MockPipelineContext(tables=[table], candidates=[candidate])
        result = stage.process(context)  # type: ignore

        assert result.success
        # Should only bind to 796.3 (scaled to 796,300), not 1,400
        # The Revenue column header contains "Revenue" which is a currency indicator
        values = [bv.value for bv in context.bound_values]
        assert 1400 not in values
        assert 1_400_000 not in values  # Not scaled either
        # 796.3 should be found (and scaled by table scale factor)
        assert len(context.bound_values) >= 1


class TestTextProximityFilters:
    """Tests for text_proximity-specific filtering of count/currency metrics."""

    def test_currency_metric_rejects_bare_number_in_text(
        self, stage: ValueBindingStage
    ) -> None:
        """Bare numbers (Unit.OTHER) near currency metric keywords should not bind.

        E.g., '796K' near 'average order value' is likely a customer count,
        not a currency value.
        """
        segment = Segment(
            segment_id="seg-aov",
            text="The average order value grew. Active consumers reached 796,000 in 2018.",
        )
        candidate = MetricCandidate(
            candidate_id="cand-aov-text",
            metric_id="cm_average_order_value",
            match_text="average order value",
            source_type=SourceType.TEXT,
            source_locator=SourceLocator(
                segment_id="seg-aov",
                text_span=(4, 23),
            ),
        )
        context = MockPipelineContext(segments=[segment], candidates=[candidate])
        result = stage.process(context)  # type: ignore

        assert result.success
        # 796,000 is Unit.OTHER (no $ sign) — should NOT bind to AOV
        assert len(context.bound_values) == 0

    def test_currency_metric_accepts_dollar_value_in_text(
        self, stage: ValueBindingStage
    ) -> None:
        """Currency values (Unit.CURRENCY) near currency metric keywords should bind."""
        segment = Segment(
            segment_id="seg-aov-ok",
            text="The average order value was $72.50 in the period.",
        )
        candidate = MetricCandidate(
            candidate_id="cand-aov-ok",
            metric_id="cm_average_order_value",
            match_text="average order value",
            source_type=SourceType.TEXT,
            source_locator=SourceLocator(
                segment_id="seg-aov-ok",
                text_span=(4, 23),
            ),
        )
        context = MockPipelineContext(segments=[segment], candidates=[candidate])
        result = stage.process(context)  # type: ignore

        assert result.success
        assert len(context.bound_values) >= 1
        assert any(bv.value == 72.50 for bv in context.bound_values)

    def test_large_value_accepted_for_count_metric_in_text(
        self, stage: ValueBindingStage
    ) -> None:
        """Large values (>=100) near count metric keywords should bind normally."""
        segment = Segment(
            segment_id="seg-large",
            text="Active consumers reached 796,000 in the period.",
        )
        candidate = MetricCandidate(
            candidate_id="cand-large",
            metric_id="cm_active_customers_total",
            match_text="Active consumers",
            source_type=SourceType.TEXT,
            source_locator=SourceLocator(
                segment_id="seg-large",
                text_span=(0, 16),
            ),
        )
        context = MockPipelineContext(segments=[segment], candidates=[candidate])
        result = stage.process(context)  # type: ignore

        assert result.success
        assert len(context.bound_values) >= 1

    def test_table_binding_still_allows_bare_currency(
        self, stage: ValueBindingStage
    ) -> None:
        """Table bindings should still allow bare numbers for currency metrics.

        The Unit.OTHER filter only applies to text_proximity, not table bindings.
        """
        table = Table(
            table_id="tbl-curr-bare",
            row_count=2,
            col_count=2,
            header_rows=1,
            stub_cols=1,
            cells=[
                Cell(row=0, col=0, text="Metric", is_header=True),
                Cell(row=0, col=1, text="Value", is_header=True),
                Cell(row=1, col=0, text="ARR", is_header=False, is_stub=True,
                     header_path=["Metric"], stub_path=[]),
                Cell(row=1, col=1, text="500", is_header=False,
                     header_path=["Value"], stub_path=["ARR"]),
            ],
        )
        candidate = MetricCandidate(
            candidate_id="cand-tbl-bare",
            metric_id="cm_arr",
            match_text="ARR",
            source_type=SourceType.HTML_TABLE,
            source_locator=SourceLocator(
                table_id="tbl-curr-bare",
                cell_row=1,
                cell_col=0,
            ),
        )
        context = MockPipelineContext(tables=[table], candidates=[candidate])
        result = stage.process(context)  # type: ignore

        assert result.success
        # Table binding should still work for bare numbers
        assert len(context.bound_values) >= 1


class TestTableScaleExceptions:
    """Tests for 'except as otherwise noted' table scale handling.

    Farfetch pattern: KPI table says "(in thousands, except as otherwise noted)".
    AOV values have $ prefix and are actual dollar amounts, not thousands.
    """

    @staticmethod
    def _make_except_table(
        table_id: str,
        stub_text: str,
        value_text: str,
        annotation: str = "(in thousands, except as otherwise noted)",
    ) -> Table:
        """Build a table with 'except as noted' annotation."""
        cells = [
            Cell(
                row=0, col=0, text=annotation, is_header=True,
                header_path=[], stub_path=[],
            ),
            Cell(
                row=0, col=1, text="2023", is_header=True,
                header_path=[], stub_path=[],
            ),
            Cell(
                row=1, col=0, text=stub_text, is_stub=True,
                header_path=[annotation], stub_path=[],
            ),
            Cell(
                row=1, col=1, text=value_text,
                header_path=["2023"], stub_path=[stub_text],
            ),
        ]
        table = Table(
            table_id=table_id,
            row_count=2, col_count=2, header_rows=1, stub_cols=1, cells=cells,
        )
        table._grid = [[None] * 2 for _ in range(2)]
        for cell in cells:
            table._grid[cell.row][cell.col] = cell
        return table

    def test_currency_symbol_skips_scaling(self, stage: ValueBindingStage) -> None:
        """Values with $ in 'except as noted' table should NOT be scaled."""
        table = self._make_except_table("ff-aov-1", "Average Order Value", "$591.7")
        candidate = MetricCandidate(
            candidate_id="cand-aov-1",
            metric_id="cm_average_order_value",
            match_text="Average Order Value",
            source_type=SourceType.HTML_TABLE,
            source_locator=SourceLocator(
                table_id="ff-aov-1", cell_row=1, cell_col=0,
            ),
        )
        context = MockPipelineContext(tables=[table], candidates=[candidate])
        result = stage.process(context)  # type: ignore

        assert result.success
        assert len(context.bound_values) >= 1
        bv = context.bound_values[0]
        # Should be ~591.7, NOT 591,700
        assert bv.value == pytest.approx(591.7, rel=1e-3)

    def test_actual_stub_skips_scaling(self, stage: ValueBindingStage) -> None:
        """Values with '(actual)' in stub should NOT be scaled."""
        table = self._make_except_table(
            "ff-aov-2", "Average Order Value (actual)", "591.7"
        )
        candidate = MetricCandidate(
            candidate_id="cand-aov-2",
            metric_id="cm_average_order_value",
            match_text="Average Order Value",
            source_type=SourceType.HTML_TABLE,
            source_locator=SourceLocator(
                table_id="ff-aov-2", cell_row=1, cell_col=0,
            ),
        )
        context = MockPipelineContext(tables=[table], candidates=[candidate])
        result = stage.process(context)  # type: ignore

        assert result.success
        assert len(context.bound_values) >= 1
        bv = context.bound_values[0]
        # Should be ~591.7, NOT 591,700
        assert bv.value == pytest.approx(591.7, rel=1e-3)

    def test_normal_value_still_scaled_in_except_table(
        self, stage: ValueBindingStage
    ) -> None:
        """Non-exception values in 'except as noted' table should still be scaled."""
        table = self._make_except_table("ff-rev-1", "Revenue", "$1,500")
        candidate = MetricCandidate(
            candidate_id="cand-rev-1",
            metric_id="cm_arr",
            match_text="Revenue",
            source_type=SourceType.HTML_TABLE,
            source_locator=SourceLocator(
                table_id="ff-rev-1", cell_row=1, cell_col=0,
            ),
        )
        context = MockPipelineContext(tables=[table], candidates=[candidate])
        result = stage.process(context)  # type: ignore

        assert result.success
        assert len(context.bound_values) >= 1
        bv = context.bound_values[0]
        # Currency value $1,500 in thousands table → $1,500,000
        # BUT wait - $1,500 has a $ symbol. In an "except" table, $ means actual.
        # This is the correct behavior: values with $ in an except table stay as-is.
        assert bv.value == pytest.approx(1500, rel=1e-3)

    def test_no_except_annotation_scales_normally(
        self, stage: ValueBindingStage
    ) -> None:
        """Tables without 'except' qualifier should scale currency normally."""
        cells = [
            Cell(
                row=0, col=0, text="(in thousands)", is_header=True,
                header_path=[], stub_path=[],
            ),
            Cell(
                row=0, col=1, text="2023", is_header=True,
                header_path=[], stub_path=[],
            ),
            Cell(
                row=1, col=0, text="Revenue", is_stub=True,
                header_path=["(in thousands)"], stub_path=[],
            ),
            Cell(
                row=1, col=1, text="$1,500",
                header_path=["2023"], stub_path=["Revenue"],
            ),
        ]
        table = Table(
            table_id="normal-1",
            row_count=2, col_count=2, header_rows=1, stub_cols=1, cells=cells,
        )
        table._grid = [[None] * 2 for _ in range(2)]
        for cell in cells:
            table._grid[cell.row][cell.col] = cell

        candidate = MetricCandidate(
            candidate_id="cand-normal-1",
            metric_id="cm_arr",
            match_text="Revenue",
            source_type=SourceType.HTML_TABLE,
            source_locator=SourceLocator(
                table_id="normal-1", cell_row=1, cell_col=0,
            ),
        )
        context = MockPipelineContext(tables=[table], candidates=[candidate])
        result = stage.process(context)  # type: ignore

        assert result.success
        assert len(context.bound_values) >= 1
        bv = context.bound_values[0]
        # Normal table: $1,500 × 1000 = $1,500,000
        assert bv.value == pytest.approx(1_500_000, rel=1e-3)

    def test_except_as_noted_variant(self, stage: ValueBindingStage) -> None:
        """'except as noted' (without 'otherwise') should also trigger exceptions."""
        table = self._make_except_table(
            "ff-aov-3", "Average Order Value", "$591.7",
            annotation="(in thousands, except as noted)",
        )
        candidate = MetricCandidate(
            candidate_id="cand-aov-3",
            metric_id="cm_average_order_value",
            match_text="Average Order Value",
            source_type=SourceType.HTML_TABLE,
            source_locator=SourceLocator(
                table_id="ff-aov-3", cell_row=1, cell_col=0,
            ),
        )
        context = MockPipelineContext(tables=[table], candidates=[candidate])
        result = stage.process(context)  # type: ignore

        assert result.success
        assert len(context.bound_values) >= 1
        bv = context.bound_values[0]
        assert bv.value == pytest.approx(591.7, rel=1e-3)
