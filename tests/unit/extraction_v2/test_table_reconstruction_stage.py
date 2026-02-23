"""
Unit tests for TableReconstructionStage.

Tests table reconstruction stage integration with existing TableReconstructor.
"""

from __future__ import annotations

import pytest

from src.extraction_v2.models import (
    SectionType,
    Segment,
    SegmentType,
)
from src.extraction_v2.pipeline import PipelineConfig, PipelineContext, PipelineStage
from src.extraction_v2.stages.table_reconstruction import TableReconstructionStage


@pytest.fixture
def stage() -> TableReconstructionStage:
    """Create a TableReconstructionStage instance."""
    return TableReconstructionStage()


@pytest.fixture
def context() -> PipelineContext:
    """Create a basic pipeline context."""
    return PipelineContext(
        html_path="test.html",
        filing_id=1,
        config=PipelineConfig(),
    )


class TestTableReconstructionStage:
    """Test TableReconstructionStage processing."""

    def test_empty_segments_list(
        self, stage: TableReconstructionStage, context: PipelineContext
    ) -> None:
        """Test processing with no segments."""
        # No segments in context
        result = stage.process(context)

        assert result.success is True
        assert result.stage == PipelineStage.TABLE_RECONSTRUCTION
        assert result.items_processed == 0
        assert result.items_output == 0
        assert len(context.tables) == 0
        assert len(result.errors) == 0

    def test_no_table_segments(
        self, stage: TableReconstructionStage, context: PipelineContext
    ) -> None:
        """Test processing with only non-table segments."""
        # Add paragraph segments only
        context.segments = [
            Segment(
                segment_id="seg-1",
                segment_type=SegmentType.PARAGRAPH,
                raw_html="<p>Some text</p>",
                text="Some text",
                dom_locator="//p[1]",
            ),
            Segment(
                segment_id="seg-2",
                segment_type=SegmentType.HEADING,
                raw_html="<h2>Heading</h2>",
                text="Heading",
                dom_locator="//h2[1]",
            ),
        ]

        result = stage.process(context)

        assert result.success is True
        assert result.items_processed == 0
        assert result.items_output == 0
        assert len(context.tables) == 0
        assert len(result.errors) == 0

    def test_single_table_segment(
        self, stage: TableReconstructionStage, context: PipelineContext
    ) -> None:
        """Test processing with a single table segment."""
        # Add a simple table segment
        table_html = """
        <table>
            <tr><th>Header 1</th><th>Header 2</th></tr>
            <tr><td>Value 1</td><td>Value 2</td></tr>
        </table>
        """
        context.segments = [
            Segment(
                segment_id="seg-table-1",
                segment_type=SegmentType.TABLE,
                raw_html=table_html,
                text="Header 1 Header 2 Value 1 Value 2",
                dom_locator="//table[1]",
                section_type=SectionType.MDA,
                section_path=["Management Discussion & Analysis"],
            )
        ]

        result = stage.process(context)

        assert result.success is True
        assert result.items_processed == 1
        assert result.items_output == 1
        assert len(context.tables) == 1
        assert len(result.errors) == 0

        # Verify table structure
        table = context.tables[0]
        assert table.row_count == 2
        assert table.col_count == 2
        assert table.segment_id == "seg-table-1"
        assert table.section_type == SectionType.MDA
        assert table.section_path == ["Management Discussion & Analysis"]
        assert table.dom_locator == "//table[1]"

    def test_multiple_table_segments(
        self, stage: TableReconstructionStage, context: PipelineContext
    ) -> None:
        """Test processing with multiple table segments."""
        # Add multiple table segments
        table_html_1 = """
        <table>
            <tr><th>A</th><th>B</th></tr>
            <tr><td>1</td><td>2</td></tr>
        </table>
        """
        table_html_2 = """
        <table>
            <tr><th>X</th><th>Y</th><th>Z</th></tr>
            <tr><td>10</td><td>20</td><td>30</td></tr>
            <tr><td>40</td><td>50</td><td>60</td></tr>
        </table>
        """

        context.segments = [
            Segment(
                segment_id="seg-table-1",
                segment_type=SegmentType.TABLE,
                raw_html=table_html_1,
                text="A B 1 2",
                dom_locator="//table[1]",
            ),
            Segment(
                segment_id="seg-para",
                segment_type=SegmentType.PARAGRAPH,
                raw_html="<p>Text between tables</p>",
                text="Text between tables",
                dom_locator="//p[1]",
            ),
            Segment(
                segment_id="seg-table-2",
                segment_type=SegmentType.TABLE,
                raw_html=table_html_2,
                text="X Y Z 10 20 30 40 50 60",
                dom_locator="//table[2]",
            ),
        ]

        result = stage.process(context)

        assert result.success is True
        assert result.items_processed == 2
        assert result.items_output == 2
        assert len(context.tables) == 2
        assert len(result.errors) == 0

        # Verify first table
        assert context.tables[0].row_count == 2
        assert context.tables[0].col_count == 2
        assert context.tables[0].segment_id == "seg-table-1"

        # Verify second table
        assert context.tables[1].row_count == 3
        assert context.tables[1].col_count == 3
        assert context.tables[1].segment_id == "seg-table-2"

    def test_invalid_html_in_segment(
        self, stage: TableReconstructionStage, context: PipelineContext
    ) -> None:
        """Test handling of malformed HTML."""
        # Add segment with invalid HTML
        context.segments = [
            Segment(
                segment_id="seg-bad",
                segment_type=SegmentType.TABLE,
                raw_html="<table><tr><td>Missing closing tags",
                text="Missing closing tags",
                dom_locator="//table[1]",
            )
        ]

        # BeautifulSoup is forgiving, so this should still work
        result = stage.process(context)

        # BeautifulSoup will parse it anyway
        assert result.items_processed == 1
        # Should successfully process even malformed HTML
        assert len(context.tables) == 1

    def test_table_segment_without_table_element(
        self, stage: TableReconstructionStage, context: PipelineContext
    ) -> None:
        """Test segment marked as TABLE but containing no <table> element."""
        # Segment marked as TABLE but no actual table
        context.segments = [
            Segment(
                segment_id="seg-fake-table",
                segment_type=SegmentType.TABLE,
                raw_html="<div>Not a table</div>",
                text="Not a table",
                dom_locator="//div[1]",
            )
        ]

        result = stage.process(context)

        assert result.success is True
        assert result.items_processed == 1
        assert result.items_output == 0
        assert len(context.tables) == 0
        assert len(result.warnings) == 1
        assert "no <table> element found" in result.warnings[0]

    def test_source_segment_linkage(
        self, stage: TableReconstructionStage, context: PipelineContext
    ) -> None:
        """Test that tables are correctly linked to source segments."""
        table_html = """
        <table>
            <tr><th>Col1</th><th>Col2</th></tr>
            <tr><td>A</td><td>B</td></tr>
        </table>
        """
        segment_id = "seg-test-123"

        context.segments = [
            Segment(
                segment_id=segment_id,
                segment_type=SegmentType.TABLE,
                raw_html=table_html,
                text="Col1 Col2 A B",
                dom_locator="//table[5]",
                section_type=SectionType.BUSINESS,
                section_path=["Business", "Customer Metrics"],
            )
        ]

        result = stage.process(context)

        assert result.success is True
        assert len(context.tables) == 1

        table = context.tables[0]
        assert table.segment_id == segment_id
        assert table.dom_locator == "//table[5]"
        assert table.section_type == SectionType.BUSINESS
        assert table.section_path == ["Business", "Customer Metrics"]

    def test_table_with_colspan_rowspan(
        self, stage: TableReconstructionStage, context: PipelineContext
    ) -> None:
        """Test table with merged cells."""
        table_html = """
        <table>
            <tr><th colspan="2">Merged Header</th></tr>
            <tr><td>A</td><td>B</td></tr>
        </table>
        """

        context.segments = [
            Segment(
                segment_id="seg-merged",
                segment_type=SegmentType.TABLE,
                raw_html=table_html,
                text="Merged Header A B",
                dom_locator="//table[1]",
            )
        ]

        result = stage.process(context)

        assert result.success is True
        assert len(context.tables) == 1

        table = context.tables[0]
        # TableReconstructor should handle colspan resolution
        assert table.row_count == 2
        assert table.col_count == 2
        assert len(table.cells) > 0

    def test_empty_table(self, stage: TableReconstructionStage, context: PipelineContext) -> None:
        """Test table with no rows."""
        table_html = "<table></table>"

        context.segments = [
            Segment(
                segment_id="seg-empty",
                segment_type=SegmentType.TABLE,
                raw_html=table_html,
                text="",
                dom_locator="//table[1]",
            )
        ]

        result = stage.process(context)

        assert result.success is True
        assert len(context.tables) == 1

        table = context.tables[0]
        assert table.row_count == 0
        assert table.col_count == 0

    def test_mixed_segments_order_preserved(
        self, stage: TableReconstructionStage, context: PipelineContext
    ) -> None:
        """Test that only table segments are processed and order is preserved."""
        context.segments = [
            Segment(
                segment_id="seg-1",
                segment_type=SegmentType.PARAGRAPH,
                raw_html="<p>Para 1</p>",
                text="Para 1",
                dom_locator="//p[1]",
            ),
            Segment(
                segment_id="seg-table-1",
                segment_type=SegmentType.TABLE,
                raw_html="<table><tr><td>T1</td></tr></table>",
                text="T1",
                dom_locator="//table[1]",
            ),
            Segment(
                segment_id="seg-2",
                segment_type=SegmentType.PARAGRAPH,
                raw_html="<p>Para 2</p>",
                text="Para 2",
                dom_locator="//p[2]",
            ),
            Segment(
                segment_id="seg-table-2",
                segment_type=SegmentType.TABLE,
                raw_html="<table><tr><td>T2</td></tr></table>",
                text="T2",
                dom_locator="//table[2]",
            ),
        ]

        result = stage.process(context)

        assert result.success is True
        assert result.items_processed == 2
        assert len(context.tables) == 2

        # Verify order preserved
        assert context.tables[0].segment_id == "seg-table-1"
        assert context.tables[1].segment_id == "seg-table-2"

    def test_stage_result_metadata(
        self, stage: TableReconstructionStage, context: PipelineContext
    ) -> None:
        """Test that stage result includes correct metadata."""
        table_html = "<table><tr><td>Data</td></tr></table>"
        fake_table_html = "<div>Not a table</div>"

        context.segments = [
            Segment(
                segment_id="seg-table-1",
                segment_type=SegmentType.TABLE,
                raw_html=table_html,
                text="Data",
                dom_locator="//table[1]",
            ),
            Segment(
                segment_id="seg-fake",
                segment_type=SegmentType.TABLE,
                raw_html=fake_table_html,
                text="Not a table",
                dom_locator="//div[1]",
            ),
            Segment(
                segment_id="seg-table-2",
                segment_type=SegmentType.TABLE,
                raw_html=table_html,
                text="Data",
                dom_locator="//table[2]",
            ),
        ]

        result = stage.process(context)

        assert result.success is True
        assert result.metadata["tables_processed"] == 2
        assert result.metadata["tables_skipped"] == 1
        assert result.duration_ms >= 0
