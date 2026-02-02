"""
Unit tests for SectionClassificationStage (Stage 2).

Tests section heading detection and classification into semantic sections.
"""

from pathlib import Path

import pytest

from src.extraction_v2.models import Segment, SegmentType, SectionType
from src.extraction_v2.pipeline import PipelineConfig, PipelineContext, PipelineStage
from src.extraction_v2.stages.section_classification import SectionClassificationStage


class TestNormalizeText:
    """Test text normalization for pattern matching."""

    def test_normalize_collapses_whitespace(self) -> None:
        """Test that multiple spaces/newlines are collapsed to single space."""
        stage = SectionClassificationStage()
        text = "ITEM   1A    \n  RISK\n\nFACTORS"
        normalized = stage._normalize_text(text)
        assert normalized == "ITEM 1A RISK FACTORS"

    def test_normalize_trims_whitespace(self) -> None:
        """Test that leading/trailing whitespace is removed."""
        stage = SectionClassificationStage()
        text = "  \n  RISK FACTORS  \n  "
        normalized = stage._normalize_text(text)
        assert normalized == "RISK FACTORS"

    def test_normalize_empty_string(self) -> None:
        """Test normalizing empty string."""
        stage = SectionClassificationStage()
        assert stage._normalize_text("") == ""
        assert stage._normalize_text("   ") == ""


class TestMostlyUppercase:
    """Test uppercase detection for heading identification."""

    def test_all_uppercase_text(self) -> None:
        """Test that all-uppercase text is detected."""
        stage = SectionClassificationStage()
        assert stage._is_mostly_uppercase("RISK FACTORS") is True

    def test_mostly_uppercase_above_threshold(self) -> None:
        """Test that text >70% uppercase is detected."""
        stage = SectionClassificationStage()
        # "RISK FACTORs" = 11 uppercase, 1 lowercase = 92%
        assert stage._is_mostly_uppercase("RISK FACTORs") is True

    def test_mixed_case_below_threshold(self) -> None:
        """Test that mixed case text below 70% is not detected."""
        stage = SectionClassificationStage()
        # "Risk Factors" = 2 uppercase, 10 lowercase = 17%
        assert stage._is_mostly_uppercase("Risk Factors") is False

    def test_lowercase_text(self) -> None:
        """Test that lowercase text is not detected."""
        stage = SectionClassificationStage()
        assert stage._is_mostly_uppercase("risk factors") is False

    def test_text_with_numbers_and_symbols(self) -> None:
        """Test that numbers/symbols are ignored in uppercase calculation."""
        stage = SectionClassificationStage()
        # Only "RISK FACTORS" counts (all uppercase letters)
        assert stage._is_mostly_uppercase("ITEM 1A: RISK FACTORS (2024)") is True

    def test_empty_string(self) -> None:
        """Test that empty string returns False."""
        stage = SectionClassificationStage()
        assert stage._is_mostly_uppercase("") is False

    def test_no_letters(self) -> None:
        """Test that text with no letters returns False."""
        stage = SectionClassificationStage()
        assert stage._is_mostly_uppercase("123 456") is False


class TestHeadingPrefix:
    """Test detection of section heading prefixes (PART, ITEM, SECTION)."""

    def test_detect_part_prefix(self) -> None:
        """Test detection of PART prefix."""
        stage = SectionClassificationStage()
        assert stage._has_heading_prefix("PART I") is True
        assert stage._has_heading_prefix("PART II - RISK FACTORS") is True
        assert stage._has_heading_prefix("PART IV") is True

    def test_detect_item_prefix(self) -> None:
        """Test detection of ITEM prefix."""
        stage = SectionClassificationStage()
        assert stage._has_heading_prefix("ITEM 1A") is True
        assert stage._has_heading_prefix("ITEM 7: Management's Discussion") is True
        assert stage._has_heading_prefix("ITEM 1. BUSINESS") is True

    def test_detect_section_prefix(self) -> None:
        """Test detection of SECTION prefix."""
        stage = SectionClassificationStage()
        assert stage._has_heading_prefix("SECTION 1") is True
        assert stage._has_heading_prefix("SECTION 3 - Risk Factors") is True

    def test_case_insensitive_matching(self) -> None:
        """Test that prefix detection is case-insensitive."""
        stage = SectionClassificationStage()
        assert stage._has_heading_prefix("item 1a") is True
        assert stage._has_heading_prefix("Part II") is True

    def test_no_prefix_detected(self) -> None:
        """Test that regular text without prefix returns False."""
        stage = SectionClassificationStage()
        assert stage._has_heading_prefix("Risk Factors") is False
        assert stage._has_heading_prefix("Management Discussion") is False


class TestSectionHeadingDetection:
    """Test _is_section_heading() method."""

    def test_detect_heading_by_uppercase(self) -> None:
        """Test heading detection by uppercase text."""
        stage = SectionClassificationStage()
        segment = Segment(
            doc_id="1",
            segment_id="seg-1",
            segment_type=SegmentType.PARAGRAPH,
            text="RISK FACTORS",
            dom_locator="/html/body[1]/p[1]",
            sequence=0,
        )
        assert stage._is_section_heading(segment) is True

    def test_detect_heading_by_prefix(self) -> None:
        """Test heading detection by ITEM/PART prefix."""
        stage = SectionClassificationStage()
        segment = Segment(
            doc_id=1,
            segment_id="seg-1",
            segment_type=SegmentType.PARAGRAPH,
            text="ITEM 1A. Risk Factors",
            dom_locator="/html/body[1]/p[1]",
            sequence=0,
        )
        assert stage._is_section_heading(segment) is True

    def test_detect_heading_by_xpath_h1(self) -> None:
        """Test heading detection by h1 tag in XPath."""
        stage = SectionClassificationStage()
        segment = Segment(
            doc_id=1,
            segment_id="seg-1",
            segment_type=SegmentType.PARAGRAPH,
            text="Risk Factors",
            dom_locator="/html/body[1]/h1[1]",
            sequence=0,
        )
        assert stage._is_section_heading(segment) is True

    def test_detect_heading_by_xpath_h2(self) -> None:
        """Test heading detection by h2-h6 tags in XPath."""
        stage = SectionClassificationStage()
        for tag in ["h2", "h3", "h4", "h5", "h6"]:
            segment = Segment(
                doc_id=1,
                segment_id="seg-1",
                segment_type=SegmentType.PARAGRAPH,
                text="Section Heading",
                dom_locator=f"/html/body[1]/{tag}[1]",
                sequence=0,
            )
            assert stage._is_section_heading(segment) is True

    def test_reject_heading_too_long(self) -> None:
        """Test that text >200 chars is not considered a heading."""
        stage = SectionClassificationStage()
        long_text = "ITEM 1A. " + "A" * 200
        segment = Segment(
            doc_id=1,
            segment_id="seg-1",
            segment_type=SegmentType.PARAGRAPH,
            text=long_text,
            dom_locator="/html/body[1]/p[1]",
            sequence=0,
        )
        assert stage._is_section_heading(segment) is False

    def test_reject_regular_paragraph(self) -> None:
        """Test that regular paragraphs are not headings."""
        stage = SectionClassificationStage()
        segment = Segment(
            doc_id=1,
            segment_id="seg-1",
            segment_type=SegmentType.PARAGRAPH,
            text="This is a regular paragraph with mixed case text.",
            dom_locator="/html/body[1]/p[1]",
            sequence=0,
        )
        assert stage._is_section_heading(segment) is False


class TestSectionTypeDetection:
    """Test _detect_section_type() method."""

    def test_detect_risk_factors_item_1a(self) -> None:
        """Test detection of RISK_FACTORS by ITEM 1A pattern."""
        stage = SectionClassificationStage()
        assert stage._detect_section_type("ITEM 1A. RISK FACTORS") == SectionType.RISK_FACTORS
        assert stage._detect_section_type("ITEM 1A: RISK FACTORS") == SectionType.RISK_FACTORS

    def test_detect_risk_factors_standalone(self) -> None:
        """Test detection of RISK_FACTORS by standalone pattern."""
        stage = SectionClassificationStage()
        assert stage._detect_section_type("RISK FACTORS") == SectionType.RISK_FACTORS

    def test_detect_mda_item_7(self) -> None:
        """Test detection of MDA by ITEM 7 pattern."""
        stage = SectionClassificationStage()
        assert stage._detect_section_type("ITEM 7. MANAGEMENT'S DISCUSSION") == SectionType.MDA
        assert stage._detect_section_type("ITEM 7: MANAGEMENT DISCUSSION AND ANALYSIS") == SectionType.MDA

    def test_detect_mda_standalone(self) -> None:
        """Test detection of MDA by standalone pattern."""
        stage = SectionClassificationStage()
        assert stage._detect_section_type("MANAGEMENT'S DISCUSSION AND ANALYSIS") == SectionType.MDA
        assert stage._detect_section_type("MD&A") == SectionType.MDA

    def test_detect_business_item_1(self) -> None:
        """Test detection of BUSINESS by ITEM 1 pattern."""
        stage = SectionClassificationStage()
        assert stage._detect_section_type("ITEM 1. BUSINESS") == SectionType.BUSINESS
        assert stage._detect_section_type("ITEM 1: BUSINESS") == SectionType.BUSINESS

    def test_detect_business_standalone(self) -> None:
        """Test detection of BUSINESS by standalone pattern."""
        stage = SectionClassificationStage()
        assert stage._detect_section_type("BUSINESS") == SectionType.BUSINESS
        assert stage._detect_section_type("DESCRIPTION OF BUSINESS") == SectionType.BUSINESS

    def test_detect_financials(self) -> None:
        """Test detection of FINANCIALS section."""
        stage = SectionClassificationStage()
        assert stage._detect_section_type("ITEM 8. FINANCIAL STATEMENTS") == SectionType.FINANCIALS
        assert stage._detect_section_type("FINANCIAL STATEMENTS AND SUPPLEMENTARY DATA") == SectionType.FINANCIALS
        assert stage._detect_section_type("CONSOLIDATED BALANCE SHEETS") == SectionType.FINANCIALS

    def test_detect_notes(self) -> None:
        """Test detection of NOTES section."""
        stage = SectionClassificationStage()
        assert stage._detect_section_type("NOTES TO CONSOLIDATED FINANCIAL STATEMENTS") == SectionType.NOTES
        assert stage._detect_section_type("NOTE 1") == SectionType.NOTES

    def test_detect_exhibits(self) -> None:
        """Test detection of EXHIBITS section."""
        stage = SectionClassificationStage()
        assert stage._detect_section_type("ITEM 15. EXHIBITS") == SectionType.EXHIBITS
        assert stage._detect_section_type("EXHIBITS AND FINANCIAL STATEMENT SCHEDULES") == SectionType.EXHIBITS
        assert stage._detect_section_type("EXHIBIT INDEX") == SectionType.EXHIBITS

    def test_detect_signatures(self) -> None:
        """Test detection of SIGNATURES section."""
        stage = SectionClassificationStage()
        assert stage._detect_section_type("SIGNATURES") == SectionType.SIGNATURES
        assert stage._detect_section_type("POWER OF ATTORNEY") == SectionType.SIGNATURES

    def test_detect_unknown(self) -> None:
        """Test that unrecognized text returns UNKNOWN."""
        stage = SectionClassificationStage()
        assert stage._detect_section_type("Some Other Section") == SectionType.UNKNOWN
        assert stage._detect_section_type("Random Text") == SectionType.UNKNOWN

    def test_case_insensitive_detection(self) -> None:
        """Test that section detection is case-insensitive."""
        stage = SectionClassificationStage()
        assert stage._detect_section_type("risk factors") == SectionType.RISK_FACTORS
        assert stage._detect_section_type("business") == SectionType.BUSINESS


class TestBuildSectionPath:
    """Test _build_section_path() method."""

    def test_build_path_risk_factors(self) -> None:
        """Test section path for RISK_FACTORS."""
        stage = SectionClassificationStage()
        path = stage._build_section_path(SectionType.RISK_FACTORS)
        assert path == ["Risk Factors"]

    def test_build_path_mda(self) -> None:
        """Test section path for MDA."""
        stage = SectionClassificationStage()
        path = stage._build_section_path(SectionType.MDA)
        assert path == ["Mda"]

    def test_build_path_business(self) -> None:
        """Test section path for BUSINESS."""
        stage = SectionClassificationStage()
        path = stage._build_section_path(SectionType.BUSINESS)
        assert path == ["Business"]

    def test_build_path_unknown(self) -> None:
        """Test section path for UNKNOWN."""
        stage = SectionClassificationStage()
        path = stage._build_section_path(SectionType.UNKNOWN)
        assert path == ["Unknown"]


class TestProcessMethod:
    """Test SectionClassificationStage.process() method."""

    def test_process_empty_segments(self) -> None:
        """Test processing with no segments."""
        stage = SectionClassificationStage()
        context = PipelineContext(
            filing_id=1,
            html_path=Path("/tmp/test.html"),
            config=PipelineConfig(),
        )

        result = stage.process(context)

        assert result.success is True
        assert result.stage == PipelineStage.SECTION_CLASSIFICATION
        assert result.items_processed == 0
        assert result.items_output == 0
        assert len(result.warnings) > 0

    def test_process_assigns_cover_initially(self) -> None:
        """Test that segments before first heading get COVER section."""
        stage = SectionClassificationStage()
        context = PipelineContext(
            filing_id=1,
            html_path=Path("/tmp/test.html"),
            config=PipelineConfig(),
        )

        # Add segments without any section headings
        context.segments = [
            Segment(
                doc_id=1,
                segment_id="seg-1",
                segment_type=SegmentType.PARAGRAPH,
                text="Company overview text at the beginning.",
                dom_locator="/html/body[1]/p[1]",
                sequence=0,
            ),
            Segment(
                doc_id=1,
                segment_id="seg-2",
                segment_type=SegmentType.PARAGRAPH,
                text="More introductory text in the cover section.",
                dom_locator="/html/body[1]/p[2]",
                sequence=1,
            ),
        ]

        result = stage.process(context)

        assert result.success is True
        assert result.items_processed == 2
        # Both segments should be COVER
        assert context.segments[0].section_type == SectionType.COVER
        assert context.segments[1].section_type == SectionType.COVER
        assert context.segments[0].section_path == ["Cover"]

    def test_process_switches_section_on_heading(self) -> None:
        """Test that section switches when heading is detected."""
        stage = SectionClassificationStage()
        context = PipelineContext(
            filing_id=1,
            html_path=Path("/tmp/test.html"),
            config=PipelineConfig(),
        )

        context.segments = [
            Segment(
                doc_id=1,
                segment_id="seg-1",
                segment_type=SegmentType.PARAGRAPH,
                text="Cover page text.",
                dom_locator="/html/body[1]/p[1]",
                sequence=0,
            ),
            Segment(
                doc_id=1,
                segment_id="seg-2",
                segment_type=SegmentType.PARAGRAPH,
                text="RISK FACTORS",
                dom_locator="/html/body[1]/h1[1]",
                sequence=1,
            ),
            Segment(
                doc_id=1,
                segment_id="seg-3",
                segment_type=SegmentType.PARAGRAPH,
                text="Risk factor content here.",
                dom_locator="/html/body[1]/p[2]",
                sequence=2,
            ),
        ]

        result = stage.process(context)

        assert result.success is True
        # First segment: COVER
        assert context.segments[0].section_type == SectionType.COVER
        # Second segment (heading): RISK_FACTORS
        assert context.segments[1].section_type == SectionType.RISK_FACTORS
        # Third segment: RISK_FACTORS (inherits from heading)
        assert context.segments[2].section_type == SectionType.RISK_FACTORS

    def test_process_multiple_sections(self) -> None:
        """Test processing document with multiple sections."""
        stage = SectionClassificationStage()
        context = PipelineContext(
            filing_id=1,
            html_path=Path("/tmp/test.html"),
            config=PipelineConfig(),
        )

        context.segments = [
            Segment(
                doc_id=1,
                segment_id="seg-1",
                segment_type=SegmentType.PARAGRAPH,
                text="Cover text",
                dom_locator="/html/body[1]/p[1]",
                sequence=0,
            ),
            Segment(
                doc_id=1,
                segment_id="seg-2",
                segment_type=SegmentType.PARAGRAPH,
                text="RISK FACTORS",
                dom_locator="/html/body[1]/h1[1]",
                sequence=1,
            ),
            Segment(
                doc_id=1,
                segment_id="seg-3",
                segment_type=SegmentType.PARAGRAPH,
                text="Risk content",
                dom_locator="/html/body[1]/p[2]",
                sequence=2,
            ),
            Segment(
                doc_id=1,
                segment_id="seg-4",
                segment_type=SegmentType.PARAGRAPH,
                text="BUSINESS",
                dom_locator="/html/body[1]/h1[2]",
                sequence=3,
            ),
            Segment(
                doc_id=1,
                segment_id="seg-5",
                segment_type=SegmentType.PARAGRAPH,
                text="Business content",
                dom_locator="/html/body[1]/p[3]",
                sequence=4,
            ),
        ]

        result = stage.process(context)

        assert result.success is True
        assert context.segments[0].section_type == SectionType.COVER
        assert context.segments[1].section_type == SectionType.RISK_FACTORS
        assert context.segments[2].section_type == SectionType.RISK_FACTORS
        assert context.segments[3].section_type == SectionType.BUSINESS
        assert context.segments[4].section_type == SectionType.BUSINESS

    def test_process_assigns_section_paths(self) -> None:
        """Test that section_path is assigned to all segments."""
        stage = SectionClassificationStage()
        context = PipelineContext(
            filing_id=1,
            html_path=Path("/tmp/test.html"),
            config=PipelineConfig(),
        )

        context.segments = [
            Segment(
                doc_id=1,
                segment_id="seg-1",
                segment_type=SegmentType.PARAGRAPH,
                text="BUSINESS",
                dom_locator="/html/body[1]/h1[1]",
                sequence=0,
            ),
            Segment(
                doc_id=1,
                segment_id="seg-2",
                segment_type=SegmentType.PARAGRAPH,
                text="Business content",
                dom_locator="/html/body[1]/p[1]",
                sequence=1,
            ),
        ]

        result = stage.process(context)

        assert result.success is True
        assert context.segments[0].section_path == ["Business"]
        assert context.segments[1].section_path == ["Business"]

    def test_process_returns_metadata(self) -> None:
        """Test that process() returns metadata with section counts."""
        stage = SectionClassificationStage()
        context = PipelineContext(
            filing_id=1,
            html_path=Path("/tmp/test.html"),
            config=PipelineConfig(),
        )

        context.segments = [
            Segment(
                doc_id=1,
                segment_id="seg-1",
                segment_type=SegmentType.PARAGRAPH,
                text="RISK FACTORS",
                dom_locator="/html/body[1]/h1[1]",
                sequence=0,
            ),
            Segment(
                doc_id=1,
                segment_id="seg-2",
                segment_type=SegmentType.PARAGRAPH,
                text="Risk content",
                dom_locator="/html/body[1]/p[1]",
                sequence=1,
            ),
        ]

        result = stage.process(context)

        assert result.success is True
        assert "sections_detected" in result.metadata
        assert "risk_factors" in result.metadata["sections_detected"]
        assert "section_types" in result.metadata

    def test_process_handles_unknown_heading(self) -> None:
        """Test that unknown headings don't switch section."""
        stage = SectionClassificationStage()
        context = PipelineContext(
            filing_id=1,
            html_path=Path("/tmp/test.html"),
            config=PipelineConfig(),
        )

        context.segments = [
            Segment(
                doc_id=1,
                segment_id="seg-1",
                segment_type=SegmentType.PARAGRAPH,
                text="Cover text",
                dom_locator="/html/body[1]/p[1]",
                sequence=0,
            ),
            Segment(
                doc_id=1,
                segment_id="seg-2",
                segment_type=SegmentType.PARAGRAPH,
                text="SOME UNKNOWN SECTION",
                dom_locator="/html/body[1]/h1[1]",
                sequence=1,
            ),
            Segment(
                doc_id=1,
                segment_id="seg-3",
                segment_type=SegmentType.PARAGRAPH,
                text="Content after unknown heading",
                dom_locator="/html/body[1]/p[2]",
                sequence=2,
            ),
        ]

        result = stage.process(context)

        assert result.success is True
        # All should remain COVER since unknown heading doesn't trigger section switch
        assert context.segments[0].section_type == SectionType.COVER
        assert context.segments[1].section_type == SectionType.COVER
        assert context.segments[2].section_type == SectionType.COVER

    def test_process_with_table_segments(self) -> None:
        """Test that table segments are also classified."""
        stage = SectionClassificationStage()
        context = PipelineContext(
            filing_id=1,
            html_path=Path("/tmp/test.html"),
            config=PipelineConfig(),
        )

        context.segments = [
            Segment(
                doc_id=1,
                segment_id="seg-1",
                segment_type=SegmentType.PARAGRAPH,
                text="BUSINESS",
                dom_locator="/html/body[1]/h1[1]",
                sequence=0,
            ),
            Segment(
                doc_id=1,
                segment_id="seg-2",
                segment_type=SegmentType.TABLE,
                text="Metric [CELL] Value [ROW] Customers [CELL] 100",
                dom_locator="/html/body[1]/table[1]",
                sequence=1,
            ),
        ]

        result = stage.process(context)

        assert result.success is True
        # Table should be classified as BUSINESS
        assert context.segments[1].section_type == SectionType.BUSINESS
        assert context.segments[1].section_path == ["Business"]

    def test_process_reports_duration(self) -> None:
        """Test that process() reports duration_ms."""
        stage = SectionClassificationStage()
        context = PipelineContext(
            filing_id=1,
            html_path=Path("/tmp/test.html"),
            config=PipelineConfig(),
        )

        context.segments = [
            Segment(
                doc_id=1,
                segment_id="seg-1",
                segment_type=SegmentType.PARAGRAPH,
                text="Test content",
                dom_locator="/html/body[1]/p[1]",
                sequence=0,
            ),
        ]

        result = stage.process(context)

        assert result.success is True
        assert result.duration_ms >= 0


class TestEdgeCases:
    """Test edge cases and error handling."""

    def test_segment_path_is_copy_not_reference(self) -> None:
        """Test that each segment gets a copy of section_path, not reference."""
        stage = SectionClassificationStage()
        context = PipelineContext(
            filing_id=1,
            html_path=Path("/tmp/test.html"),
            config=PipelineConfig(),
        )

        context.segments = [
            Segment(
                doc_id=1,
                segment_id="seg-1",
                segment_type=SegmentType.PARAGRAPH,
                text="BUSINESS",
                dom_locator="/html/body[1]/h1[1]",
                sequence=0,
            ),
            Segment(
                doc_id=1,
                segment_id="seg-2",
                segment_type=SegmentType.PARAGRAPH,
                text="Content 1",
                dom_locator="/html/body[1]/p[1]",
                sequence=1,
            ),
            Segment(
                doc_id=1,
                segment_id="seg-3",
                segment_type=SegmentType.PARAGRAPH,
                text="Content 2",
                dom_locator="/html/body[1]/p[2]",
                sequence=2,
            ),
        ]

        result = stage.process(context)

        assert result.success is True
        # Modify one segment's path to verify they're independent copies
        context.segments[1].section_path.append("Modified")
        assert len(context.segments[1].section_path) == 2
        assert len(context.segments[2].section_path) == 1  # Should still be 1

    def test_whitespace_only_heading_not_detected(self) -> None:
        """Test that whitespace-only text is not detected as heading."""
        stage = SectionClassificationStage()
        segment = Segment(
            doc_id=1,
            segment_id="seg-1",
            segment_type=SegmentType.PARAGRAPH,
            text="    ",
            dom_locator="/html/body[1]/p[1]",
            sequence=0,
        )
        assert stage._is_section_heading(segment) is False
