"""
Unit tests for SectionClassificationStage (Stage 2).

Tests section heading detection and classification into semantic sections.
"""

from pathlib import Path

import pytest

from src.extraction_v2.models import SectionType, Segment, SegmentType
from src.extraction_v2.pipeline import PipelineConfig, PipelineContext, PipelineStage
from src.extraction_v2.stages.section_classification import (
    SectionClassificationStage,
    _classify_presentation_slide,
)
from src.extraction_v2.text_utils import normalize_text


class TestNormalizeText:
    """Test text normalization for pattern matching."""

    def test_normalize_collapses_whitespace(self) -> None:
        """Test that multiple spaces/newlines are collapsed to single space."""
        text = "ITEM   1A    \n  RISK\n\nFACTORS"
        assert normalize_text(text) == "ITEM 1A RISK FACTORS"

    def test_normalize_trims_whitespace(self) -> None:
        """Test that leading/trailing whitespace is removed."""
        text = "  \n  RISK FACTORS  \n  "
        assert normalize_text(text) == "RISK FACTORS"

    def test_normalize_empty_string(self) -> None:
        """Test normalizing empty string."""
        assert normalize_text("") == ""
        assert normalize_text("   ") == ""


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
            filing_id=1,
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
            filing_id=1,
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
            filing_id=1,
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
                filing_id=1,
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
            filing_id=1,
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
            filing_id=1,
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
        assert (
            stage._detect_section_type("ITEM 7: MANAGEMENT DISCUSSION AND ANALYSIS")
            == SectionType.MDA
        )

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
        assert (
            stage._detect_section_type("FINANCIAL STATEMENTS AND SUPPLEMENTARY DATA")
            == SectionType.FINANCIALS
        )
        assert stage._detect_section_type("CONSOLIDATED BALANCE SHEETS") == SectionType.FINANCIALS

    def test_detect_notes(self) -> None:
        """Test detection of NOTES section."""
        stage = SectionClassificationStage()
        assert (
            stage._detect_section_type("NOTES TO CONSOLIDATED FINANCIAL STATEMENTS")
            == SectionType.NOTES
        )
        assert stage._detect_section_type("NOTE 1") == SectionType.NOTES

    def test_detect_exhibits(self) -> None:
        """Test detection of EXHIBITS section."""
        stage = SectionClassificationStage()
        assert stage._detect_section_type("ITEM 15. EXHIBITS") == SectionType.EXHIBITS
        assert (
            stage._detect_section_type("EXHIBITS AND FINANCIAL STATEMENT SCHEDULES")
            == SectionType.EXHIBITS
        )
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
                filing_id=1,
                segment_id="seg-1",
                segment_type=SegmentType.PARAGRAPH,
                text="Company overview text at the beginning.",
                dom_locator="/html/body[1]/p[1]",
                sequence=0,
            ),
            Segment(
                filing_id=1,
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
                filing_id=1,
                segment_id="seg-1",
                segment_type=SegmentType.PARAGRAPH,
                text="Cover page text.",
                dom_locator="/html/body[1]/p[1]",
                sequence=0,
            ),
            Segment(
                filing_id=1,
                segment_id="seg-2",
                segment_type=SegmentType.PARAGRAPH,
                text="RISK FACTORS",
                dom_locator="/html/body[1]/h1[1]",
                sequence=1,
            ),
            Segment(
                filing_id=1,
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
                filing_id=1,
                segment_id="seg-1",
                segment_type=SegmentType.PARAGRAPH,
                text="Cover text",
                dom_locator="/html/body[1]/p[1]",
                sequence=0,
            ),
            Segment(
                filing_id=1,
                segment_id="seg-2",
                segment_type=SegmentType.PARAGRAPH,
                text="RISK FACTORS",
                dom_locator="/html/body[1]/h1[1]",
                sequence=1,
            ),
            Segment(
                filing_id=1,
                segment_id="seg-3",
                segment_type=SegmentType.PARAGRAPH,
                text="Risk content",
                dom_locator="/html/body[1]/p[2]",
                sequence=2,
            ),
            Segment(
                filing_id=1,
                segment_id="seg-4",
                segment_type=SegmentType.PARAGRAPH,
                text="BUSINESS",
                dom_locator="/html/body[1]/h1[2]",
                sequence=3,
            ),
            Segment(
                filing_id=1,
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
                filing_id=1,
                segment_id="seg-1",
                segment_type=SegmentType.PARAGRAPH,
                text="BUSINESS",
                dom_locator="/html/body[1]/h1[1]",
                sequence=0,
            ),
            Segment(
                filing_id=1,
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
                filing_id=1,
                segment_id="seg-1",
                segment_type=SegmentType.PARAGRAPH,
                text="RISK FACTORS",
                dom_locator="/html/body[1]/h1[1]",
                sequence=0,
            ),
            Segment(
                filing_id=1,
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
                filing_id=1,
                segment_id="seg-1",
                segment_type=SegmentType.PARAGRAPH,
                text="Cover text",
                dom_locator="/html/body[1]/p[1]",
                sequence=0,
            ),
            Segment(
                filing_id=1,
                segment_id="seg-2",
                segment_type=SegmentType.PARAGRAPH,
                text="SOME UNKNOWN SECTION",
                dom_locator="/html/body[1]/h1[1]",
                sequence=1,
            ),
            Segment(
                filing_id=1,
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
                filing_id=1,
                segment_id="seg-1",
                segment_type=SegmentType.PARAGRAPH,
                text="BUSINESS",
                dom_locator="/html/body[1]/h1[1]",
                sequence=0,
            ),
            Segment(
                filing_id=1,
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
                filing_id=1,
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
                filing_id=1,
                segment_id="seg-1",
                segment_type=SegmentType.PARAGRAPH,
                text="BUSINESS",
                dom_locator="/html/body[1]/h1[1]",
                sequence=0,
            ),
            Segment(
                filing_id=1,
                segment_id="seg-2",
                segment_type=SegmentType.PARAGRAPH,
                text="Content 1",
                dom_locator="/html/body[1]/p[1]",
                sequence=1,
            ),
            Segment(
                filing_id=1,
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
            filing_id=1,
            segment_id="seg-1",
            segment_type=SegmentType.PARAGRAPH,
            text="    ",
            dom_locator="/html/body[1]/p[1]",
            sequence=0,
        )
        assert stage._is_section_heading(segment) is False


class TestIntegrationSECFiling:
    """Integration tests with real SEC filing structure."""

    def test_full_sec_filing_section_classification(self, tmp_path: Path) -> None:
        """Test section classification on a realistic SEC filing with all major sections.

        This test verifies:
        - All major section types are detected (COVER, RISK_FACTORS, MDA, BUSINESS, etc.)
        - Segments are assigned correct section_type enum values
        - section_path is populated for hierarchical context
        - Integration with IngestionStage works correctly
        """
        from src.extraction_v2.stages.ingestion import IngestionStage

        # Load realistic SEC filing fixture
        fixture_path = (
            Path(__file__).parent.parent.parent
            / "fixtures"
            / "section_classification"
            / "sec_filing_sections.html"
        )

        # Run ingestion stage first
        ingestion_stage = IngestionStage()
        context = PipelineContext(
            filing_id=12345,
            html_path=fixture_path,
            config=PipelineConfig(),
        )

        ingestion_result = ingestion_stage.process(context)
        assert ingestion_result.success is True
        assert len(context.segments) > 0

        # Run section classification stage
        classification_stage = SectionClassificationStage()
        classification_result = classification_stage.process(context)
        assert classification_result.success is True

        # Collect sections detected
        sections_detected = set(seg.section_type for seg in context.segments)

        # Verify all major section types appear
        assert SectionType.COVER in sections_detected
        assert SectionType.RISK_FACTORS in sections_detected
        assert SectionType.MDA in sections_detected
        assert SectionType.BUSINESS in sections_detected
        assert SectionType.FINANCIALS in sections_detected
        assert SectionType.NOTES in sections_detected
        assert SectionType.EXHIBITS in sections_detected
        assert SectionType.SIGNATURES in sections_detected

        # Verify section_path is populated for all segments
        for segment in context.segments:
            assert segment.section_path is not None
            assert len(segment.section_path) > 0
            assert isinstance(segment.section_path, list)
            assert all(isinstance(s, str) for s in segment.section_path)

        # Verify specific section assignments by finding key phrases
        risk_factors_segments = [
            seg for seg in context.segments if "high degree of risk" in seg.text.lower()
        ]
        assert len(risk_factors_segments) > 0
        assert risk_factors_segments[0].section_type == SectionType.RISK_FACTORS
        assert "Risk Factors" in risk_factors_segments[0].section_path[0]

        mda_segments = [
            seg
            for seg in context.segments
            if "total customers" in seg.text.lower() and "50,000" in seg.text
        ]
        assert len(mda_segments) > 0
        assert mda_segments[0].section_type == SectionType.MDA
        assert "Mda" in mda_segments[0].section_path[0]

        business_segments = [
            seg for seg in context.segments if "cloud-based software" in seg.text.lower()
        ]
        assert len(business_segments) > 0
        assert business_segments[0].section_type == SectionType.BUSINESS
        assert "Business" in business_segments[0].section_path[0]

        financials_segments = [
            seg for seg in context.segments if seg.section_type == SectionType.FINANCIALS
        ]
        assert len(financials_segments) > 0
        assert any("balance sheets" in seg.text.lower() for seg in financials_segments)

        notes_segments = [seg for seg in context.segments if seg.section_type == SectionType.NOTES]
        assert len(notes_segments) > 0
        assert any("note 1" in seg.text.lower() for seg in notes_segments)

        # Verify cover section appears first
        first_content_segments = context.segments[:5]
        assert any(seg.section_type == SectionType.COVER for seg in first_content_segments)

        # Verify exhibits and signatures appear last
        last_segments = context.segments[-10:]
        assert any(seg.section_type == SectionType.EXHIBITS for seg in last_segments)
        assert any(seg.section_type == SectionType.SIGNATURES for seg in last_segments)


class TestPresentationSlideClassification:
    """Tests for _classify_presentation_slide() and its integration with process()."""

    def test_key_metrics_heading(self) -> None:
        """'Key Metrics' heading maps to KEY_METRICS when slide type is PRESENTATION_SLIDE."""
        result = _classify_presentation_slide("Key Metrics", SectionType.PRESENTATION_SLIDE)
        assert result == SectionType.KEY_METRICS

    def test_key_metrics_heading_case_insensitive(self) -> None:
        """Pattern matching is case-insensitive."""
        result = _classify_presentation_slide("KEY METRICS", SectionType.PRESENTATION_SLIDE)
        assert result == SectionType.KEY_METRICS

    def test_kpi_heading(self) -> None:
        """'KPI' heading maps to KEY_METRICS."""
        result = _classify_presentation_slide("KPI Summary", SectionType.PRESENTATION_SLIDE)
        assert result == SectionType.KEY_METRICS

    def test_appendix_heading(self) -> None:
        """'Appendix' heading maps to APPENDIX when slide type is PRESENTATION_SLIDE."""
        result = _classify_presentation_slide("Appendix", SectionType.PRESENTATION_SLIDE)
        assert result == SectionType.APPENDIX

    def test_appendix_heading_non_gaap(self) -> None:
        """'Non-GAAP Reconciliation' heading maps to APPENDIX."""
        result = _classify_presentation_slide(
            "Non-GAAP Reconciliation", SectionType.PRESENTATION_SLIDE
        )
        assert result == SectionType.APPENDIX

    def test_guidance_heading_fy2025_outlook(self) -> None:
        """'FY2025 Outlook' heading maps to GUIDANCE when slide type is PRESENTATION_SLIDE."""
        result = _classify_presentation_slide("FY2025 Outlook", SectionType.PRESENTATION_SLIDE)
        assert result == SectionType.GUIDANCE

    def test_guidance_heading_guidance_word(self) -> None:
        """'Guidance' heading maps to GUIDANCE."""
        result = _classify_presentation_slide("FY2026 Guidance", SectionType.PRESENTATION_SLIDE)
        assert result == SectionType.GUIDANCE

    def test_financial_overview_heading(self) -> None:
        """'Financial Overview' heading maps to FINANCIAL_OVERVIEW."""
        result = _classify_presentation_slide("Financial Overview", SectionType.PRESENTATION_SLIDE)
        assert result == SectionType.FINANCIAL_OVERVIEW

    def test_financial_summary_heading(self) -> None:
        """'Financial Summary' heading maps to FINANCIAL_OVERVIEW."""
        result = _classify_presentation_slide("Financial Summary", SectionType.PRESENTATION_SLIDE)
        assert result == SectionType.FINANCIAL_OVERVIEW

    def test_non_presentation_section_unchanged(self) -> None:
        """Non-presentation section types are returned unchanged regardless of heading."""
        result = _classify_presentation_slide("Key Metrics", SectionType.MDA)
        assert result == SectionType.MDA

    def test_non_presentation_risk_factors_unchanged(self) -> None:
        """RISK_FACTORS section type is not reclassified."""
        result = _classify_presentation_slide("Key Metrics", SectionType.RISK_FACTORS)
        assert result == SectionType.RISK_FACTORS

    def test_no_match_returns_input_type(self) -> None:
        """If no pattern matches, the original PRESENTATION_SLIDE type is returned."""
        result = _classify_presentation_slide("Our Company Mission", SectionType.PRESENTATION_SLIDE)
        assert result == SectionType.PRESENTATION_SLIDE

    def test_unknown_section_can_be_classified(self) -> None:
        """UNKNOWN section type can also be reclassified to a slide type."""
        result = _classify_presentation_slide("Key Metrics", SectionType.UNKNOWN)
        assert result == SectionType.KEY_METRICS

    def test_process_refines_presentation_slide_segments(self) -> None:
        """process() refines PRESENTATION_SLIDE segments using heading text."""
        stage = SectionClassificationStage()
        context = PipelineContext(
            filing_id=1,
            html_path=Path("/tmp/test.html"),
            config=PipelineConfig(),
        )

        context.segments = [
            Segment(
                filing_id=1,
                segment_id="seg-1",
                segment_type=SegmentType.HEADING,
                text="Key Metrics",
                dom_locator="/html/body[1]/section[1]/h2[1]",
                section_type=SectionType.PRESENTATION_SLIDE,
                sequence=0,
            ),
            Segment(
                filing_id=1,
                segment_id="seg-2",
                segment_type=SegmentType.TABLE,
                text="ARR $100M",
                dom_locator="/html/body[1]/section[1]/table[1]",
                section_type=SectionType.PRESENTATION_SLIDE,
                sequence=1,
            ),
        ]

        result = stage.process(context)

        assert result.success is True
        # Heading segment gets refined
        assert context.segments[0].section_type == SectionType.KEY_METRICS
        # Non-heading PRESENTATION_SLIDE segment stays as-is (no text match triggers refinement)
        assert context.segments[1].section_type == SectionType.PRESENTATION_SLIDE

    def test_process_does_not_reclassify_other_section_types(self) -> None:
        """process() does not reclassify non-PRESENTATION_SLIDE pre-set section types."""
        stage = SectionClassificationStage()
        context = PipelineContext(
            filing_id=1,
            html_path=Path("/tmp/test.html"),
            config=PipelineConfig(),
        )

        context.segments = [
            Segment(
                filing_id=1,
                segment_id="seg-1",
                segment_type=SegmentType.PARAGRAPH,
                text="Key Metrics for our business.",
                dom_locator="/html/body[1]/p[1]",
                section_type=SectionType.MDA,
                sequence=0,
            ),
        ]

        result = stage.process(context)

        assert result.success is True
        assert context.segments[0].section_type == SectionType.MDA


class TestEightKHeadingPatterns:
    """Test 8-K earnings-exhibit heading classification (legacy-059)."""

    @pytest.mark.parametrize(
        "heading,expected",
        [
            ("Financial Highlights", SectionType.FINANCIAL_OVERVIEW),
            ("Key Business Metrics", SectionType.KEY_METRICS),
            ("Key Operating Metrics", SectionType.KEY_METRICS),
            ("Business Highlights", SectionType.KEY_METRICS),
            ("Operating Highlights", SectionType.KEY_METRICS),
            ("Q3 2025 Highlights", SectionType.KEY_METRICS),
            ("Q4 2024 Highlights", SectionType.KEY_METRICS),
            ("Results of Operations", SectionType.MDA),
            ("FY 2026 Outlook", SectionType.GUIDANCE),
            ("FY2026 Outlook", SectionType.GUIDANCE),
            ("Q1 2026 Outlook", SectionType.GUIDANCE),
            ("Q2 2025 Guidance", SectionType.GUIDANCE),
        ],
    )
    def test_eight_k_heading_classified(self, heading: str, expected: SectionType) -> None:
        stage = SectionClassificationStage()
        assert stage._detect_section_type(heading) == expected

    def test_financial_highlights_in_body_text_not_classified_as_heading(self) -> None:
        """Body text containing the phrase should not be treated as a heading."""
        stage = SectionClassificationStage()
        long_body = (
            "We are pleased to present our financial highlights for the quarter, "
            "which include revenue growth and improved margins across all segments."
        )
        seg = Segment(
            filing_id=1,
            segment_id="seg-1",
            segment_type=SegmentType.PARAGRAPH,
            text=long_body,
            dom_locator="/html/body/p[3]",
            sequence=0,
        )
        assert stage._is_section_heading(seg) is False

    def test_pattern_precedence_stable(self) -> None:
        """Precedence lock: 'Financial Highlights' vs 'Q3 2025 Highlights'."""
        stage = SectionClassificationStage()
        assert stage._detect_section_type("Financial Highlights") == SectionType.FINANCIAL_OVERVIEW
        assert stage._detect_section_type("Q3 2025 Highlights") == SectionType.KEY_METRICS
