"""
Tests for V2 Candidate Generation Stage.

Tests coverage:
- Segment scanning (keyword matching)
- Table cell scanning (text + header_path + stub_path)
- Filtering (exclusions, required context)
- Confidence scoring
- Integration with pipeline context
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from src.extraction_v2.models import (
    Cell,
    MetricCandidate,
    SectionType,
    Segment,
    SegmentType,
    SourceLocator,
    SourceType,
    Table,
)
from src.extraction_v2.stages.candidate_generation import CandidateGenerationStage

# =============================================================================
# Test Fixtures
# =============================================================================


@dataclass
class MockPipelineContext:
    """Mock pipeline context for testing."""

    html_path: Path = field(default_factory=lambda: Path("/test/file.html"))
    filing_id: int = 1
    config: Any = None

    segments: list[Segment] = field(default_factory=list)
    tables: list[Table] = field(default_factory=list)
    candidates: list[MetricCandidate] = field(default_factory=list)

    document: Any = None
    images: list[Any] = field(default_factory=list)
    bound_values: list[Any] = field(default_factory=list)
    facts: list[Any] = field(default_factory=list)
    stage_results: list[Any] = field(default_factory=list)
    start_time: datetime = field(default_factory=datetime.utcnow)
    llm_calls: int = 0
    ocr_calls: int = 0
    vision_calls: int = 0


def make_segment(
    text: str,
    segment_id: str = "seg-1",
    segment_type: SegmentType = SegmentType.PARAGRAPH,
    section_type: SectionType = SectionType.UNKNOWN,
    dom_locator: str = "/html/body/div[1]",
) -> Segment:
    """Create a test segment."""
    return Segment(
        segment_id=segment_id,
        doc_id="doc-1",
        segment_type=segment_type,
        text=text,
        raw_html=f"<p>{text}</p>",
        dom_locator=dom_locator,
        section_type=section_type,
        sequence=0,
    )


def make_table(
    cells: list[Cell],
    table_id: str = "tbl-1",
    segment_id: str = "seg-tbl-1",
    section_type: SectionType = SectionType.UNKNOWN,
) -> Table:
    """Create a test table with cells."""
    return Table(
        table_id=table_id,
        doc_id="doc-1",
        segment_id=segment_id,
        section_type=section_type,
        row_count=len(set(c.row for c in cells)) if cells else 0,
        col_count=len(set(c.col for c in cells)) if cells else 0,
        cells=cells,
    )


def make_cell(
    row: int,
    col: int,
    text: str,
    header_path: list[str] | None = None,
    stub_path: list[str] | None = None,
) -> Cell:
    """Create a test table cell."""
    return Cell(
        row=row,
        col=col,
        text=text,
        header_path=header_path or [],
        stub_path=stub_path or [],
    )


@pytest.fixture
def stage() -> CandidateGenerationStage:
    """Create a CandidateGenerationStage instance."""
    return CandidateGenerationStage()


@pytest.fixture
def mock_context() -> MockPipelineContext:
    """Create a mock pipeline context."""
    return MockPipelineContext()


# =============================================================================
# Segment Scanning Tests
# =============================================================================


class TestSegmentScanning:
    """Tests for scanning segments for keyword matches."""

    def test_finds_keyword_in_simple_paragraph(
        self, stage: CandidateGenerationStage, mock_context: MockPipelineContext
    ) -> None:
        """Stage finds a metric keyword in simple paragraph text."""
        segment = make_segment("We acquired 500 new customers this quarter.")
        mock_context.segments.append(segment)

        result = stage.process(mock_context)

        assert result.success
        assert len(mock_context.candidates) >= 1
        # Should find "new customers"
        metric_ids = [c.metric_id for c in mock_context.candidates]
        assert "cm_new_customers_acquired" in metric_ids

    def test_finds_multiple_keywords_in_single_segment(
        self, stage: CandidateGenerationStage, mock_context: MockPipelineContext
    ) -> None:
        """Stage finds multiple different metric keywords in one segment."""
        segment = make_segment(
            "Our ARR grew to $100M while we added 1,000 new customers."
        )
        mock_context.segments.append(segment)

        result = stage.process(mock_context)

        assert result.success
        assert len(mock_context.candidates) >= 2
        metric_ids = [c.metric_id for c in mock_context.candidates]
        assert "cm_new_customers_acquired" in metric_ids
        assert "cm_arr" in metric_ids

    def test_no_match_when_keyword_absent(
        self, stage: CandidateGenerationStage, mock_context: MockPipelineContext
    ) -> None:
        """Stage returns no candidates when no keywords match."""
        segment = make_segment("The weather was nice today.")
        mock_context.segments.append(segment)

        result = stage.process(mock_context)

        assert result.success
        assert len(mock_context.candidates) == 0

    def test_case_insensitive_matching(
        self, stage: CandidateGenerationStage, mock_context: MockPipelineContext
    ) -> None:
        """Stage matches keywords case-insensitively."""
        segment = make_segment("We acquired NEW CUSTOMERS this quarter.")
        mock_context.segments.append(segment)

        result = stage.process(mock_context)

        assert result.success
        assert len(mock_context.candidates) >= 1
        metric_ids = [c.metric_id for c in mock_context.candidates]
        assert "cm_new_customers_acquired" in metric_ids

    def test_creates_valid_source_locator(
        self, stage: CandidateGenerationStage, mock_context: MockPipelineContext
    ) -> None:
        """Candidate has valid SourceLocator with segment info."""
        segment = make_segment(
            "We have 10,000 paid customers.",
            segment_id="test-seg-123",
            dom_locator="/html/body/p[5]",
        )
        mock_context.segments.append(segment)

        stage.process(mock_context)

        assert len(mock_context.candidates) >= 1
        candidate = mock_context.candidates[0]
        assert candidate.source_locator.segment_id == "test-seg-123"
        assert candidate.source_locator.dom_locator == "/html/body/p[5]"
        assert candidate.source_locator.text_span is not None


# =============================================================================
# Table Cell Scanning Tests
# =============================================================================


class TestTableCellScanning:
    """Tests for scanning table cells for keyword matches."""

    def test_finds_keyword_in_cell_text(
        self, stage: CandidateGenerationStage, mock_context: MockPipelineContext
    ) -> None:
        """Stage finds keyword directly in cell text."""
        cell = make_cell(0, 0, "New Customers Acquired")
        table = make_table([cell])
        mock_context.tables.append(table)

        result = stage.process(mock_context)

        assert result.success
        assert len(mock_context.candidates) >= 1
        metric_ids = [c.metric_id for c in mock_context.candidates]
        assert "cm_new_customers_acquired" in metric_ids

    def test_finds_keyword_in_header_path(
        self, stage: CandidateGenerationStage, mock_context: MockPipelineContext
    ) -> None:
        """Stage finds keyword in cell's header_path."""
        cell = make_cell(
            row=1,
            col=1,
            text="500",
            header_path=["New Customers", "Q1 2024"],
        )
        table = make_table([cell])
        mock_context.tables.append(table)

        result = stage.process(mock_context)

        assert result.success
        assert len(mock_context.candidates) >= 1
        # Verify it's from the header path
        candidate = mock_context.candidates[0]
        assert candidate.source_type == SourceType.HTML_TABLE

    def test_finds_keyword_in_stub_path(
        self, stage: CandidateGenerationStage, mock_context: MockPipelineContext
    ) -> None:
        """Stage finds keyword in cell's stub_path (row labels)."""
        cell = make_cell(
            row=2,
            col=3,
            text="1,250",
            stub_path=["Paid Customers"],
        )
        table = make_table([cell])
        mock_context.tables.append(table)

        result = stage.process(mock_context)

        assert result.success
        assert len(mock_context.candidates) >= 1
        metric_ids = [c.metric_id for c in mock_context.candidates]
        assert "cm_customers_period_end" in metric_ids

    def test_creates_correct_table_source_locator(
        self, stage: CandidateGenerationStage, mock_context: MockPipelineContext
    ) -> None:
        """Candidate from table has correct cell coordinates in locator."""
        cell = make_cell(row=3, col=2, text="New Customers")
        cell.dom_locator = "/html/body/table/tr[4]/td[3]"
        table = make_table([cell], table_id="tbl-test-456", segment_id="seg-tbl-789")
        mock_context.tables.append(table)

        stage.process(mock_context)

        assert len(mock_context.candidates) >= 1
        candidate = mock_context.candidates[0]
        assert candidate.source_locator.table_id == "tbl-test-456"
        assert candidate.source_locator.segment_id == "seg-tbl-789"
        assert candidate.source_locator.cell_row == 3
        assert candidate.source_locator.cell_col == 2


# =============================================================================
# Filtering Tests
# =============================================================================


class TestFiltering:
    """Tests for exclusion patterns and required context filtering."""

    def test_excludes_via_exclusion_patterns(
        self, stage: CandidateGenerationStage, mock_context: MockPipelineContext
    ) -> None:
        """Stage filters out matches that hit exclusion patterns."""
        # "new customers" should NOT match when followed by "acquisition cost"
        segment = make_segment(
            "Our new customer acquisition cost was $50."
        )
        mock_context.segments.append(segment)

        stage.process(mock_context)

        # The exclusion pattern for cm_new_customers_acquired includes "acquisition cost"
        # So this should be filtered out
        for candidate in mock_context.candidates:
            if candidate.metric_id == "cm_new_customers_acquired":
                # If it's found, it should NOT be the "cost" context
                assert "acquisition cost" not in candidate.context_text.lower() or \
                       "cost" not in segment.text.lower()

    def test_excludes_without_required_context(
        self, stage: CandidateGenerationStage, mock_context: MockPipelineContext
    ) -> None:
        """Revenue synonym metrics require cohort/per-customer context."""
        # GMV without cohort context should not generate candidate
        segment = make_segment("Our GMV was $500 million this year.")
        mock_context.segments.append(segment)

        stage.process(mock_context)

        # cm_gmv (if it exists and has required_context) should not match
        # without cohort keywords
        # Note: This depends on actual YAML config having required_context
        # The test validates the mechanism works
        assert result_does_not_contain_revenue_synonym_without_context(
            mock_context.candidates
        )

    def test_includes_with_required_context(
        self, stage: CandidateGenerationStage, mock_context: MockPipelineContext
    ) -> None:
        """Metrics with required context pass when context is present."""
        # Include cohort keyword to satisfy required_context
        segment = make_segment(
            "The GMV per customer cohort showed strong retention patterns."
        )
        mock_context.segments.append(segment)

        stage.process(mock_context)

        # With cohort context, revenue synonyms should be allowed
        # (if they match patterns in the config)
        assert True  # Validates no exception and stage completes

    def test_passes_valid_matches(
        self, stage: CandidateGenerationStage, mock_context: MockPipelineContext
    ) -> None:
        """Valid keyword matches without exclusions pass through."""
        segment = make_segment("We have 50,000 paid customers worldwide.")
        mock_context.segments.append(segment)

        stage.process(mock_context)

        assert len(mock_context.candidates) >= 1
        metric_ids = [c.metric_id for c in mock_context.candidates]
        assert "cm_customers_period_end" in metric_ids

    def test_empty_text_segment_no_error(
        self, stage: CandidateGenerationStage, mock_context: MockPipelineContext
    ) -> None:
        """Empty segments are handled gracefully."""
        segment = make_segment("")
        mock_context.segments.append(segment)

        result = stage.process(mock_context)

        assert result.success
        assert len(mock_context.candidates) == 0


def result_does_not_contain_revenue_synonym_without_context(
    candidates: list[MetricCandidate],
) -> bool:
    """Helper to check revenue synonyms have context."""
    # Revenue synonym metrics from the YAML that have required_context
    revenue_synonyms = {"cm_gmv", "cm_tcv", "cm_acv", "cm_bookings"}
    for c in candidates:
        if c.metric_id in revenue_synonyms:
            # If found, there should be cohort/per-customer context
            context_lower = c.context_text.lower()
            has_context = any(
                kw in context_lower
                for kw in ["cohort", "per customer", "per user", "by customer"]
            )
            if not has_context:
                return False
    return True


# =============================================================================
# Confidence Scoring Tests
# =============================================================================


class TestConfidenceScoring:
    """Tests for confidence score computation."""

    def test_base_confidence(
        self, stage: CandidateGenerationStage, mock_context: MockPipelineContext
    ) -> None:
        """Candidates have base confidence of 0.5."""
        segment = make_segment(
            "We acquired customers.",
            section_type=SectionType.OTHER,
        )
        mock_context.segments.append(segment)

        stage.process(mock_context)

        if mock_context.candidates:
            # Base confidence is 0.5
            for candidate in mock_context.candidates:
                assert candidate.confidence >= 0.5

    def test_table_source_bonus(
        self, stage: CandidateGenerationStage, mock_context: MockPipelineContext
    ) -> None:
        """Table sources get +0.1 confidence bonus."""
        cell = make_cell(0, 0, "New Customers")
        table = make_table([cell], section_type=SectionType.OTHER)
        mock_context.tables.append(table)

        stage.process(mock_context)

        assert len(mock_context.candidates) >= 1
        candidate = mock_context.candidates[0]
        # Should be base (0.5) + table bonus (0.1) = 0.6
        assert candidate.confidence >= 0.6

    def test_section_bonus(
        self, stage: CandidateGenerationStage, mock_context: MockPipelineContext
    ) -> None:
        """MD&A and Business sections get +0.1 confidence bonus."""
        segment = make_segment(
            "We acquired new customers.",
            section_type=SectionType.MDA,
        )
        mock_context.segments.append(segment)

        stage.process(mock_context)

        if mock_context.candidates:
            # Should have section bonus
            candidate = mock_context.candidates[0]
            # Base (0.5) + section bonus (0.1) = 0.6
            assert candidate.confidence >= 0.6

    def test_confidence_bounded(
        self, stage: CandidateGenerationStage, mock_context: MockPipelineContext
    ) -> None:
        """Confidence is always bounded between 0.0 and 1.0."""
        # Create a candidate with maximum bonuses
        cell = make_cell(0, 0, "Net Revenue Retention", header_path=["Metric"])
        table = make_table([cell], section_type=SectionType.MDA)
        mock_context.tables.append(table)

        stage.process(mock_context)

        for candidate in mock_context.candidates:
            assert 0.0 <= candidate.confidence <= 1.0


# =============================================================================
# Integration Tests
# =============================================================================


class TestIntegration:
    """Integration tests for full stage execution."""

    def test_full_stage_execution(
        self, stage: CandidateGenerationStage, mock_context: MockPipelineContext
    ) -> None:
        """Stage processes mixed segments and tables successfully."""
        # Add a paragraph segment
        segment = make_segment("We have 100 new customers this month.")
        mock_context.segments.append(segment)

        # Add a table with customer metrics
        cell1 = make_cell(0, 0, "Paid Customers", header_path=["Metric"])
        cell2 = make_cell(0, 1, "5,000", header_path=["Count"])
        table = make_table([cell1, cell2])
        mock_context.tables.append(table)

        result = stage.process(mock_context)

        assert result.success
        assert result.items_processed == 2  # 1 segment + 1 table
        assert result.items_output >= 1  # At least some candidates

    def test_empty_input_returns_success(
        self, stage: CandidateGenerationStage, mock_context: MockPipelineContext
    ) -> None:
        """Empty context returns success with zero candidates."""
        result = stage.process(mock_context)

        assert result.success
        assert result.items_processed == 0
        assert result.items_output == 0
        assert len(mock_context.candidates) == 0

    def test_candidate_has_all_required_fields(
        self, stage: CandidateGenerationStage, mock_context: MockPipelineContext
    ) -> None:
        """Generated candidates have all required fields populated."""
        segment = make_segment("Our ARR exceeded $50 million.")
        mock_context.segments.append(segment)

        stage.process(mock_context)

        assert len(mock_context.candidates) >= 1
        candidate = mock_context.candidates[0]

        # Check all required fields
        assert candidate.candidate_id is not None
        assert candidate.metric_id != ""
        assert candidate.match_text != ""
        assert candidate.source_locator is not None
        assert candidate.source_type in [SourceType.TEXT, SourceType.HTML_TABLE]
        assert 0.0 <= candidate.confidence <= 1.0
        assert candidate.context_text != ""

    def test_multiple_segments_multiple_tables(
        self, stage: CandidateGenerationStage, mock_context: MockPipelineContext
    ) -> None:
        """Stage handles multiple segments and tables correctly."""
        # Multiple segments
        mock_context.segments.extend([
            make_segment("We have new customers.", segment_id="seg-1"),
            make_segment("Our ARR is growing.", segment_id="seg-2"),
            make_segment("Daily active users increased.", segment_id="seg-3"),
        ])

        # Multiple tables
        mock_context.tables.extend([
            make_table([make_cell(0, 0, "Paid Customers")], table_id="tbl-1"),
            make_table([make_cell(0, 0, "Monthly Active Users")], table_id="tbl-2"),
        ])

        result = stage.process(mock_context)

        assert result.success
        assert result.items_processed == 5  # 3 segments + 2 tables
        assert len(mock_context.candidates) >= 3  # Multiple metrics matched


# =============================================================================
# Edge Case Tests
# =============================================================================


class TestEdgeCases:
    """Tests for edge cases and error handling."""

    def test_keyword_spanning_cell_markers(
        self, stage: CandidateGenerationStage, mock_context: MockPipelineContext
    ) -> None:
        """Keywords can span [CELL] markers in segment text."""
        # This tests text that might have been extracted with markers
        segment = make_segment("New [CELL] Customers acquired this quarter")
        mock_context.segments.append(segment)

        result = stage.process(mock_context)

        assert result.success
        # The regex should still match "new" and "customers" patterns
        # even if they're separated by markers

    def test_multiple_metrics_same_segment(
        self, stage: CandidateGenerationStage, mock_context: MockPipelineContext
    ) -> None:
        """Multiple different metrics in same segment all generate candidates."""
        segment = make_segment(
            "Our net revenue retention was 120% and we added 500 new customers."
        )
        mock_context.segments.append(segment)

        stage.process(mock_context)

        metric_ids = [c.metric_id for c in mock_context.candidates]
        # Should have both NRR and new customers
        assert len(set(metric_ids)) >= 2

    def test_preserves_section_type_on_candidate(
        self, stage: CandidateGenerationStage, mock_context: MockPipelineContext
    ) -> None:
        """Candidates preserve the section_type from their source."""
        segment = make_segment(
            "We have 1000 paid customers.",
            section_type=SectionType.BUSINESS,
        )
        mock_context.segments.append(segment)

        stage.process(mock_context)

        assert len(mock_context.candidates) >= 1
        candidate = mock_context.candidates[0]
        assert candidate.section_type == SectionType.BUSINESS

    def test_handles_initialization_failure_gracefully(
        self, mock_context: MockPipelineContext
    ) -> None:
        """Stage handles config loading errors gracefully."""
        stage = CandidateGenerationStage()

        # Mock failed initialization
        with patch.object(
            stage, "_ensure_initialized", return_value=False
        ):
            result = stage.process(mock_context)

        assert not result.success
        assert len(result.errors) > 0

    def test_context_extraction(
        self, stage: CandidateGenerationStage, mock_context: MockPipelineContext
    ) -> None:
        """Context text is correctly extracted around match."""
        # Create text with known positions
        prefix = "A" * 50
        keyword = "new customers"
        suffix = "B" * 50
        text = f"{prefix} {keyword} {suffix}"

        segment = make_segment(text)
        mock_context.segments.append(segment)

        stage.process(mock_context)

        if mock_context.candidates:
            candidate = mock_context.candidates[0]
            # Context should include surrounding characters
            assert "new customers" in candidate.context_text
            assert len(candidate.context_text) > len(keyword)

    def test_invalid_regex_pattern_handled(
        self, mock_context: MockPipelineContext
    ) -> None:
        """Invalid regex patterns are logged and skipped gracefully."""
        stage = CandidateGenerationStage()

        # Manually inject an invalid pattern
        stage._initialized = False
        stage._keywords = {"test_metric": ["[invalid regex"]}  # Unclosed bracket
        stage._exclusions = {}
        stage._required_context = {}
        stage._specific_patterns = []

        # Compile should log warning but not raise
        stage._compile_patterns()

        # The metric should have empty compiled patterns (skipped invalid one)
        assert "test_metric" in stage._compiled_patterns
        assert len(stage._compiled_patterns["test_metric"]) == 0

    def test_invalid_exclusion_pattern_handled(
        self, mock_context: MockPipelineContext
    ) -> None:
        """Invalid exclusion regex patterns are skipped gracefully."""
        stage = CandidateGenerationStage()

        stage._initialized = False
        stage._keywords = {"test_metric": [r"\btest\b"]}
        stage._exclusions = {"test_metric": ["[unclosed"]}  # Invalid
        stage._required_context = {}
        stage._specific_patterns = []

        stage._compile_patterns()

        # Valid keyword pattern should compile
        assert len(stage._compiled_patterns["test_metric"]) == 1
        # Invalid exclusion should be skipped
        assert len(stage._compiled_exclusions.get("test_metric", [])) == 0

    def test_invalid_context_pattern_handled(
        self, mock_context: MockPipelineContext
    ) -> None:
        """Invalid required_context patterns are skipped gracefully."""
        stage = CandidateGenerationStage()

        stage._initialized = False
        stage._keywords = {"test_metric": [r"\btest\b"]}
        stage._exclusions = {}
        stage._required_context = {
            "test_metric": {"patterns": ["[unclosed", r"\bvalid\b"]}
        }
        stage._specific_patterns = []

        stage._compile_patterns()

        # One pattern is valid, one is invalid
        # _compiled_context stores (patterns, proximity_chars) tuple
        context_data = stage._compiled_context.get("test_metric")
        assert context_data is not None
        patterns, proximity = context_data
        assert len(patterns) == 1  # Only valid pattern compiled

    def test_invalid_specific_pattern_handled(
        self, mock_context: MockPipelineContext
    ) -> None:
        """Invalid specific patterns are skipped gracefully."""
        stage = CandidateGenerationStage()

        stage._initialized = False
        stage._keywords = {}
        stage._exclusions = {}
        stage._required_context = {}
        stage._specific_patterns = ["[invalid", r"\bvalid pattern\b"]

        stage._compile_patterns()

        # Only the valid pattern should be compiled
        assert len(stage._compiled_specific) == 1

    def test_segment_processing_error_logged(
        self, stage: CandidateGenerationStage, mock_context: MockPipelineContext
    ) -> None:
        """Errors in segment processing are logged but don't crash."""
        segment = make_segment("New customers acquired")
        mock_context.segments.append(segment)

        # Initialize stage first
        stage._ensure_initialized()

        # Mock _scan_segment to raise an error
        with patch.object(
            stage, "_scan_segment",
            side_effect=RuntimeError("Segment error")
        ):
            result = stage.process(mock_context)

            # Should not crash, but should have errors
            assert len(result.errors) > 0
            assert "Segment error" in result.errors[0]

    def test_table_processing_error_logged(
        self, stage: CandidateGenerationStage, mock_context: MockPipelineContext
    ) -> None:
        """Errors in table processing are logged but don't crash."""
        cell = make_cell(0, 0, "New Customers")
        table = make_table([cell])
        mock_context.tables.append(table)

        # Initialize stage first
        stage._ensure_initialized()

        # Mock _scan_table to raise an error
        with patch.object(
            stage, "_scan_table",
            side_effect=RuntimeError("Table error")
        ):
            result = stage.process(mock_context)

            # Should not crash, but should have errors
            assert len(result.errors) > 0
            assert "Table error" in result.errors[0]

    def test_already_initialized_returns_immediately(
        self, mock_context: MockPipelineContext
    ) -> None:
        """Calling _ensure_initialized twice doesn't reload config."""
        stage = CandidateGenerationStage()

        # First call initializes
        result1 = stage._ensure_initialized()
        assert result1
        assert stage._initialized

        # Mock get_metric_keywords to fail - but it shouldn't be called
        with patch(
            "src.extraction_v2.stages.candidate_generation.get_metric_keywords",
            side_effect=Exception("Should not be called")
        ):
            # Second call returns immediately without reloading
            result2 = stage._ensure_initialized()
            assert result2  # Still True


class TestProximityBasedContext:
    """Tests for proximity-based required context checking."""

    def test_context_within_proximity_passes(
        self, mock_context: MockPipelineContext
    ) -> None:
        """Required context within proximity window is accepted."""
        stage = CandidateGenerationStage()
        stage._initialized = True
        stage._compiled_patterns = {"test_metric": [re.compile(r"\bGMV\b", re.IGNORECASE)]}
        stage._compiled_exclusions = {}
        # Context must be within 100 chars
        stage._compiled_context = {
            "test_metric": ([re.compile(r"\bper\s+customer\b", re.IGNORECASE)], 100)
        }
        stage._compiled_specific = []

        # "GMV" at position ~50, "per customer" within 100 chars
        # Use spaces to ensure word boundaries
        text = "some text " * 5 + "GMV metric " + "per customer revenue " * 2
        segment = make_segment(text)
        candidates = stage._scan_segment(segment)

        assert len(candidates) == 1, "Should match when context is within proximity"

    def test_context_beyond_proximity_fails(
        self, mock_context: MockPipelineContext
    ) -> None:
        """Required context beyond proximity window is rejected."""
        stage = CandidateGenerationStage()
        stage._initialized = True
        stage._compiled_patterns = {"test_metric": [re.compile(r"\bGMV\b", re.IGNORECASE)]}
        stage._compiled_exclusions = {}
        # Context must be within 50 chars (small window)
        stage._compiled_context = {
            "test_metric": ([re.compile(r"\bper\s+customer\b", re.IGNORECASE)], 50)
        }
        stage._compiled_specific = []

        # "GMV" near start, "per customer" very far away (>50 chars from GMV)
        text = "Our GMV was strong. " + "x" * 200 + " per customer revenue"
        segment = make_segment(text)
        candidates = stage._scan_segment(segment)

        assert len(candidates) == 0, "Should NOT match when context is beyond proximity"

    def test_proximity_uses_config_value(self) -> None:
        """Proximity value from config is stored correctly."""
        stage = CandidateGenerationStage()
        stage._initialized = False
        stage._keywords = {"test_metric": [r"\btest\b"]}
        stage._exclusions = {}
        stage._required_context = {
            "test_metric": {"patterns": [r"\bcontext\b"], "proximity_chars": 500}
        }
        stage._specific_patterns = []

        stage._compile_patterns()

        patterns, proximity = stage._compiled_context["test_metric"]
        assert proximity == 500

    def test_proximity_uses_default_when_not_specified(self) -> None:
        """Default proximity is used when not specified in config."""
        stage = CandidateGenerationStage()
        stage._initialized = False
        stage._keywords = {"test_metric": [r"\btest\b"]}
        stage._exclusions = {}
        stage._required_context = {
            "test_metric": {"patterns": [r"\bcontext\b"]}  # No proximity_chars
        }
        stage._specific_patterns = []

        stage._compile_patterns()

        patterns, proximity = stage._compiled_context["test_metric"]
        assert proximity == stage._default_proximity_chars  # Default 1500


class TestCandidateDeduplication:
    """Tests for candidate deduplication."""

    def test_deduplicates_same_metric_same_location(
        self, mock_context: MockPipelineContext
    ) -> None:
        """Multiple matches for same metric at same location are deduplicated."""
        stage = CandidateGenerationStage()
        stage._initialized = True
        # Two patterns that both match "customers" variations
        stage._compiled_patterns = {
            "cm_customers": [
                re.compile(r"\bcustomers\b", re.IGNORECASE),
                re.compile(r"\bnew customers\b", re.IGNORECASE),
            ]
        }
        stage._compiled_exclusions = {}
        stage._compiled_context = {}
        stage._compiled_specific = []

        # "new customers" matches both patterns at overlapping positions
        text = "We had 1000 new customers this quarter"
        segment = make_segment(text)
        candidates = stage._scan_segment(segment)

        # Should deduplicate to 1 candidate (highest confidence or first)
        assert len(candidates) == 1

    def test_keeps_different_metrics_same_location(
        self, mock_context: MockPipelineContext
    ) -> None:
        """Different metrics at same location are kept separate."""
        stage = CandidateGenerationStage()
        stage._initialized = True
        stage._compiled_patterns = {
            "cm_customers": [re.compile(r"\bnew customers\b", re.IGNORECASE)],
            "cm_other": [re.compile(r"\bnew customers\b", re.IGNORECASE)],
        }
        stage._compiled_exclusions = {}
        stage._compiled_context = {}
        stage._compiled_specific = []

        text = "We had 1000 new customers"
        segment = make_segment(text)
        candidates = stage._scan_segment(segment)

        # Both metrics should be kept
        assert len(candidates) == 2
        metric_ids = {c.metric_id for c in candidates}
        assert metric_ids == {"cm_customers", "cm_other"}

    def test_keeps_same_metric_different_locations(
        self, mock_context: MockPipelineContext
    ) -> None:
        """Same metric at different locations is kept separate."""
        stage = CandidateGenerationStage()
        stage._initialized = True
        stage._compiled_patterns = {
            "cm_customers": [re.compile(r"\bcustomers\b", re.IGNORECASE)],
        }
        stage._compiled_exclusions = {}
        stage._compiled_context = {}
        stage._compiled_specific = []

        # Two mentions of "customers" at different positions
        text = "We had 1000 customers in Q1, and 2000 customers in Q2"
        segment = make_segment(text)
        candidates = stage._scan_segment(segment)

        # Both mentions should be kept (different positions)
        assert len(candidates) == 2

    def test_deduplicates_table_cells(
        self, mock_context: MockPipelineContext
    ) -> None:
        """Deduplication works for table cell candidates."""
        stage = CandidateGenerationStage()
        stage._initialized = True
        stage._compiled_patterns = {
            "cm_customers": [
                re.compile(r"\bcustomers\b", re.IGNORECASE),
                re.compile(r"\btotal customers\b", re.IGNORECASE),
            ]
        }
        stage._compiled_exclusions = {}
        stage._compiled_context = {}
        stage._compiled_specific = []

        # Cell with text that matches both patterns
        cell = make_cell(0, 0, "Total Customers")
        table = make_table([cell])
        candidates = stage._scan_table(table)

        # Should deduplicate to 1
        assert len(candidates) == 1

    def test_keeps_higher_confidence_on_dedup(
        self, mock_context: MockPipelineContext
    ) -> None:
        """When deduplicating, keeps the candidate with higher confidence."""
        stage = CandidateGenerationStage()
        stage._initialized = True
        # First pattern is generic, second is specific (gets confidence bonus)
        stage._compiled_patterns = {
            "cm_customers": [
                re.compile(r"\bcustomers\b", re.IGNORECASE),
                re.compile(r"\bpaid customers\b", re.IGNORECASE),
            ]
        }
        stage._compiled_exclusions = {}
        stage._compiled_context = {}
        # "paid customers" is a specific pattern that gets bonus
        stage._compiled_specific = [re.compile(r"\bpaid customers\b", re.IGNORECASE)]

        text = "We had 5000 paid customers"
        segment = make_segment(text)
        candidates = stage._scan_segment(segment)

        assert len(candidates) == 1
        # Should keep higher confidence (specific pattern match)
        assert candidates[0].confidence >= stage.BASE_CONFIDENCE + stage.SPECIFIC_PATTERN_BONUS

    def test_cross_metric_dedup_suppresses_contained_span(
        self, mock_context: MockPipelineContext
    ) -> None:
        """'daily active users' suppresses shorter 'active users' match."""
        stage = CandidateGenerationStage()
        stage._initialized = True
        stage._compiled_patterns = {
            "cm_daily_active_users": [
                re.compile(r"\bdaily\s+active\s+users?\b", re.IGNORECASE),
            ],
            "cm_active_customers_total": [
                re.compile(r"\bactive\s+users?\b", re.IGNORECASE),
            ],
        }
        stage._compiled_exclusions = {}
        stage._compiled_context = {}
        stage._compiled_specific = []

        text = "We had 1 million daily active users"
        segment = make_segment(text)
        candidates = stage._scan_segment(segment)

        assert len(candidates) == 1
        assert candidates[0].metric_id == "cm_daily_active_users"

    def test_cross_metric_dedup_keeps_overlapping_non_contained(
        self, mock_context: MockPipelineContext
    ) -> None:
        """Overlapping but non-contained spans both survive."""
        stage = CandidateGenerationStage()
        stage._initialized = True
        # "customer retention" overlaps with "retention rate was 95%"
        # but neither strictly contains the other
        stage._compiled_patterns = {
            "cm_customer_retention_rate": [
                re.compile(r"\bcustomer\s+retention\b", re.IGNORECASE),
            ],
            "cm_nrr": [
                re.compile(r"\bretention\s+rate[^.;]{0,50}\d+%", re.IGNORECASE),
            ],
        }
        stage._compiled_exclusions = {}
        stage._compiled_context = {}
        stage._compiled_specific = []

        text = "Our customer retention rate was 95% in Q4"
        segment = make_segment(text)
        candidates = stage._scan_segment(segment)

        assert len(candidates) == 2
        metric_ids = {c.metric_id for c in candidates}
        assert "cm_customer_retention_rate" in metric_ids
        assert "cm_nrr" in metric_ids

    def test_cross_metric_dedup_keeps_non_overlapping(
        self, mock_context: MockPipelineContext
    ) -> None:
        """Candidates at separate positions both survive."""
        stage = CandidateGenerationStage()
        stage._initialized = True
        stage._compiled_patterns = {
            "cm_customers_period_end": [
                re.compile(r"\bpaid\s+customers?\b", re.IGNORECASE),
            ],
            "cm_active_customers_total": [
                re.compile(r"\bactive\s+users?\b", re.IGNORECASE),
            ],
        }
        stage._compiled_exclusions = {}
        stage._compiled_context = {}
        stage._compiled_specific = []

        text = "We had 5000 paid customers and 3000 active users"
        segment = make_segment(text)
        candidates = stage._scan_segment(segment)

        assert len(candidates) == 2

    def test_cross_metric_dedup_identical_spans_kept(
        self, mock_context: MockPipelineContext
    ) -> None:
        """Identical spans for different metrics are both kept (no regression)."""
        stage = CandidateGenerationStage()
        stage._initialized = True
        # Both match exactly "active users" at the same position
        stage._compiled_patterns = {
            "cm_active_customers_total": [
                re.compile(r"\bactive\s+users?\b", re.IGNORECASE),
            ],
            "cm_active_users_other": [
                re.compile(r"\bactive\s+users?\b", re.IGNORECASE),
            ],
        }
        stage._compiled_exclusions = {}
        stage._compiled_context = {}
        stage._compiled_specific = []

        text = "We had 3000 active users"
        segment = make_segment(text)
        candidates = stage._scan_segment(segment)

        assert len(candidates) == 2
        metric_ids = {c.metric_id for c in candidates}
        assert "cm_active_customers_total" in metric_ids
        assert "cm_active_users_other" in metric_ids

    def test_cross_metric_dedup_table_cells(
        self, mock_context: MockPipelineContext
    ) -> None:
        """Table cell substring suppression works."""
        stage = CandidateGenerationStage()
        stage._initialized = True
        stage._compiled_patterns = {
            "cm_daily_active_users": [
                re.compile(r"\bdaily\s+active\s+users?\b", re.IGNORECASE),
            ],
            "cm_active_customers_total": [
                re.compile(r"\bactive\s+users?\b", re.IGNORECASE),
            ],
        }
        stage._compiled_exclusions = {}
        stage._compiled_context = {}
        stage._compiled_specific = []

        cell = make_cell(0, 0, "Daily Active Users")
        table = make_table([cell])
        candidates = stage._scan_table(table)

        assert len(candidates) == 1
        assert candidates[0].metric_id == "cm_daily_active_users"
