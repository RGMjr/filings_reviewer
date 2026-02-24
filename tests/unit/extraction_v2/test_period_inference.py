"""
Unit tests for V2 Period Inference Stage.

Tests cover:
1. Quarter pattern parsing (Q1 2024, Q1'24, 1Q24)
2. Fiscal year pattern parsing (FY 2024, FY24)
3. Period ended patterns (Year Ended December 31, 2024)
4. Trailing patterns (TTM, LTM)
5. YTD patterns
6. Table header extraction
7. Text context extraction
8. Filing fallback
9. Ambiguous period handling
"""

from datetime import date
from unittest.mock import MagicMock

import pytest

from src.extraction_v2.models import (
    BoundValue,
    Cell,
    Document,
    PeriodType,
    Segment,
    SourceLocator,
    Table,
)
from src.extraction_v2.stages.period_inference import (
    PeriodInferenceStage,
)

# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def stage() -> PeriodInferenceStage:
    """Create a PeriodInferenceStage instance."""
    return PeriodInferenceStage()


@pytest.fixture
def mock_context() -> MagicMock:
    """Create a mock PipelineContext."""
    context = MagicMock()
    context.bound_values = []
    context.segments = []
    context.tables = []
    context.document = Document(fiscal_year=2024, fiscal_period="FY")
    return context


def make_table_with_headers(table_id: str, header_texts: list[str], data_rows: int = 2) -> Table:
    """Create a simple table with column headers."""
    table = Table(
        table_id=table_id,
        row_count=1 + data_rows,
        col_count=len(header_texts),
        header_rows=1,
        stub_cols=1,
    )
    cells = []
    # Header row
    for col, text in enumerate(header_texts):
        cells.append(Cell(row=0, col=col, text=text, is_header=True))
    # Data rows
    for row in range(1, 1 + data_rows):
        for col in range(len(header_texts)):
            cells.append(Cell(row=row, col=col, text=f"data_{row}_{col}"))
    table.cells = cells
    return table


def make_bound_value(
    candidate_id: str = "test",
    table_id: str | None = None,
    cell_row: int | None = None,
    cell_col: int | None = None,
    segment_id: str | None = None,
    text_span: tuple[int, int] | None = None,
) -> BoundValue:
    """Create a BoundValue for testing."""
    return BoundValue(
        candidate_id=candidate_id,
        value=100.0,
        value_raw="100",
        source_locator=SourceLocator(
            table_id=table_id,
            cell_row=cell_row,
            cell_col=cell_col,
            segment_id=segment_id,
            text_span=text_span,
        ),
    )


# ============================================================================
# Quarter Pattern Tests
# ============================================================================


class TestQuarterPatternParsing:
    """Tests for quarter period pattern parsing."""

    def test_q1_2024_standard(self, stage: PeriodInferenceStage) -> None:
        """Parse Q1 2024 format."""
        result = stage._try_parse_quarter("Q1 2024")
        assert result is not None
        assert result.period_type == PeriodType.QUARTERLY
        assert result.start == date(2024, 1, 1)
        assert result.end == date(2024, 3, 31)

    def test_q2_2024_standard(self, stage: PeriodInferenceStage) -> None:
        """Parse Q2 2024 format."""
        result = stage._try_parse_quarter("Q2 2024")
        assert result is not None
        assert result.period_type == PeriodType.QUARTERLY
        assert result.start == date(2024, 4, 1)
        assert result.end == date(2024, 6, 30)

    def test_q3_2024_standard(self, stage: PeriodInferenceStage) -> None:
        """Parse Q3 2024 format."""
        result = stage._try_parse_quarter("Q3 2024")
        assert result is not None
        assert result.period_type == PeriodType.QUARTERLY
        assert result.start == date(2024, 7, 1)
        assert result.end == date(2024, 9, 30)

    def test_q4_2024_standard(self, stage: PeriodInferenceStage) -> None:
        """Parse Q4 2024 format."""
        result = stage._try_parse_quarter("Q4 2024")
        assert result is not None
        assert result.period_type == PeriodType.QUARTERLY
        assert result.start == date(2024, 10, 1)
        assert result.end == date(2024, 12, 31)

    def test_q1_compact_apostrophe(self, stage: PeriodInferenceStage) -> None:
        """Parse Q1'24 compact format with apostrophe."""
        result = stage._try_parse_quarter("Q1'24")
        assert result is not None
        assert result.period_type == PeriodType.QUARTERLY
        assert result.start == date(2024, 1, 1)
        assert result.end == date(2024, 3, 31)

    def test_q3_compact_space_apostrophe(self, stage: PeriodInferenceStage) -> None:
        """Parse Q3 '25 format with space and apostrophe."""
        result = stage._try_parse_quarter("Q3 '25")
        assert result is not None
        assert result.period_type == PeriodType.QUARTERLY
        assert result.start == date(2025, 7, 1)
        assert result.end == date(2025, 9, 30)

    def test_reversed_1q24_format(self, stage: PeriodInferenceStage) -> None:
        """Parse 1Q24 reversed format."""
        result = stage._try_parse_quarter("1Q24")
        assert result is not None
        assert result.period_type == PeriodType.QUARTERLY
        assert result.start == date(2024, 1, 1)
        assert result.end == date(2024, 3, 31)

    def test_reversed_4q_2024_format(self, stage: PeriodInferenceStage) -> None:
        """Parse 4Q 2024 reversed format with space."""
        result = stage._try_parse_quarter("4Q 2024")
        assert result is not None
        assert result.period_type == PeriodType.QUARTERLY
        assert result.start == date(2024, 10, 1)
        assert result.end == date(2024, 12, 31)

    def test_lowercase_q1(self, stage: PeriodInferenceStage) -> None:
        """Parse lowercase q1 2024."""
        result = stage._try_parse_quarter("q1 2024")
        assert result is not None
        assert result.period_type == PeriodType.QUARTERLY

    def test_no_match_returns_none(self, stage: PeriodInferenceStage) -> None:
        """Return None when no quarter pattern found."""
        result = stage._try_parse_quarter("No quarter here")
        assert result is None


# ============================================================================
# Fiscal Year Pattern Tests
# ============================================================================


class TestFiscalYearPatternParsing:
    """Tests for fiscal year pattern parsing."""

    def test_fy_2024_standard(self, stage: PeriodInferenceStage) -> None:
        """Parse FY 2024 format."""
        result = stage._try_parse_fiscal_year("FY 2024")
        assert result is not None
        assert result.period_type == PeriodType.ANNUAL
        assert result.start == date(2024, 1, 1)
        assert result.end == date(2024, 12, 31)

    def test_fy24_compact(self, stage: PeriodInferenceStage) -> None:
        """Parse FY24 compact format."""
        result = stage._try_parse_fiscal_year("FY24")
        assert result is not None
        assert result.period_type == PeriodType.ANNUAL
        assert result.start == date(2024, 1, 1)
        assert result.end == date(2024, 12, 31)

    def test_fy_apostrophe_24(self, stage: PeriodInferenceStage) -> None:
        """Parse FY'24 format with apostrophe."""
        result = stage._try_parse_fiscal_year("FY'24")
        assert result is not None
        assert result.period_type == PeriodType.ANNUAL

    def test_fiscal_year_2024(self, stage: PeriodInferenceStage) -> None:
        """Parse Fiscal Year 2024 format."""
        result = stage._try_parse_fiscal_year("Fiscal Year 2024")
        assert result is not None
        assert result.period_type == PeriodType.ANNUAL
        assert result.end == date(2024, 12, 31)

    def test_fiscal_2024(self, stage: PeriodInferenceStage) -> None:
        """Parse Fiscal 2024 format."""
        result = stage._try_parse_fiscal_year("Fiscal 2024")
        assert result is not None
        assert result.period_type == PeriodType.ANNUAL

    def test_lowercase_fy(self, stage: PeriodInferenceStage) -> None:
        """Parse lowercase fy 2024."""
        result = stage._try_parse_fiscal_year("fy 2024")
        assert result is not None
        assert result.period_type == PeriodType.ANNUAL

    def test_no_match_returns_none(self, stage: PeriodInferenceStage) -> None:
        """Return None when no fiscal year pattern found."""
        result = stage._try_parse_fiscal_year("Just a regular year")
        assert result is None


class TestNonCalendarFiscalYear:
    """Tests for non-calendar fiscal year boundary calculation (WP-08)."""

    def test_january_fye_fy2020(self, stage: PeriodInferenceStage) -> None:
        """FY2020 with Jan 31 FYE (Slack/Snowflake): Feb 1 2019 - Jan 31 2020."""
        stage._fy_end_month = 1
        stage._fy_end_day = 31
        result = stage._try_parse_fiscal_year("FY 2020")
        assert result is not None
        assert result.period_type == PeriodType.ANNUAL
        assert result.start == date(2019, 2, 1)
        assert result.end == date(2020, 1, 31)

    def test_january_fye_fy2021(self, stage: PeriodInferenceStage) -> None:
        """FY2021 with Jan 31 FYE: Feb 1 2020 - Jan 31 2021."""
        stage._fy_end_month = 1
        stage._fy_end_day = 31
        result = stage._try_parse_fiscal_year("FY2021")
        assert result is not None
        assert result.start == date(2020, 2, 1)
        assert result.end == date(2021, 1, 31)

    def test_march_fye(self, stage: PeriodInferenceStage) -> None:
        """FY2020 with Mar 31 FYE: Apr 1 2019 - Mar 31 2020."""
        stage._fy_end_month = 3
        stage._fy_end_day = 31
        result = stage._try_parse_fiscal_year("FY 2020")
        assert result is not None
        assert result.start == date(2019, 4, 1)
        assert result.end == date(2020, 3, 31)

    def test_june_fye(self, stage: PeriodInferenceStage) -> None:
        """FY2020 with Jun 30 FYE: Jul 1 2019 - Jun 30 2020."""
        stage._fy_end_month = 6
        stage._fy_end_day = 30
        result = stage._try_parse_fiscal_year("FY 2020")
        assert result is not None
        assert result.start == date(2019, 7, 1)
        assert result.end == date(2020, 6, 30)

    def test_december_fye_calendar_year(self, stage: PeriodInferenceStage) -> None:
        """Dec 31 FYE still produces calendar year boundaries."""
        stage._fy_end_month = 12
        stage._fy_end_day = 31
        result = stage._try_parse_fiscal_year("FY 2024")
        assert result is not None
        assert result.start == date(2024, 1, 1)
        assert result.end == date(2024, 12, 31)

    def test_no_fye_falls_back_to_calendar_year(self, stage: PeriodInferenceStage) -> None:
        """When _fy_end_month is None, calendar year (Jan 1 - Dec 31) is used."""
        stage._fy_end_month = None
        stage._fy_end_day = None
        result = stage._try_parse_fiscal_year("FY 2024")
        assert result is not None
        assert result.start == date(2024, 1, 1)
        assert result.end == date(2024, 12, 31)

    def test_fye_day_defaults_to_last_day_of_month(self, stage: PeriodInferenceStage) -> None:
        """When _fy_end_day is None, defaults to last day of end month."""
        stage._fy_end_month = 1
        stage._fy_end_day = None  # Should default to Jan 31
        result = stage._try_parse_fiscal_year("FY 2020")
        assert result is not None
        assert result.end == date(2020, 1, 31)


# ============================================================================
# Period Ended Pattern Tests
# ============================================================================


class TestPeriodEndedPatternParsing:
    """Tests for 'period ended' date pattern parsing."""

    def test_year_ended_december_31_2024(self, stage: PeriodInferenceStage) -> None:
        """Parse Year Ended December 31, 2024."""
        result = stage._try_parse_period_ended("Year Ended December 31, 2024")
        assert result is not None
        assert result.period_type == PeriodType.ANNUAL
        assert result.end == date(2024, 12, 31)

    def test_for_the_year_ended(self, stage: PeriodInferenceStage) -> None:
        """Parse For the year ended March 31, 2025."""
        result = stage._try_parse_period_ended("For the year ended March 31, 2025")
        assert result is not None
        assert result.period_type == PeriodType.ANNUAL
        assert result.end == date(2025, 3, 31)

    def test_nine_months_ended(self, stage: PeriodInferenceStage) -> None:
        """Parse Nine Months Ended September 30, 2024."""
        result = stage._try_parse_period_ended("Nine Months Ended September 30, 2024")
        assert result is not None
        assert result.period_type == PeriodType.YTD
        assert result.end == date(2024, 9, 30)

    def test_quarter_ended(self, stage: PeriodInferenceStage) -> None:
        """Parse Quarter ended June 30, 2024."""
        result = stage._try_parse_period_ended("Quarter ended June 30, 2024")
        assert result is not None
        assert result.period_type == PeriodType.QUARTERLY
        assert result.end == date(2024, 6, 30)

    def test_three_months_ended(self, stage: PeriodInferenceStage) -> None:
        """Parse Three months ended March 31, 2024."""
        result = stage._try_parse_period_ended("Three months ended March 31, 2024")
        assert result is not None
        assert result.period_type == PeriodType.QUARTERLY
        assert result.end == date(2024, 3, 31)

    def test_six_months_ended(self, stage: PeriodInferenceStage) -> None:
        """Parse Six months ended June 30, 2024."""
        result = stage._try_parse_period_ended("Six months ended June 30, 2024")
        assert result is not None
        assert result.period_type == PeriodType.YTD
        assert result.end == date(2024, 6, 30)

    def test_period_ended_no_comma(self, stage: PeriodInferenceStage) -> None:
        """Parse without comma: Year Ended December 31 2024."""
        result = stage._try_parse_period_ended("Year Ended December 31 2024")
        assert result is not None
        assert result.end == date(2024, 12, 31)

    def test_abbreviated_month(self, stage: PeriodInferenceStage) -> None:
        """Parse with abbreviated month: Year ended Dec 31, 2024."""
        result = stage._try_parse_period_ended("Year ended Dec 31, 2024")
        assert result is not None
        assert result.end == date(2024, 12, 31)


# ============================================================================
# Trailing Pattern Tests
# ============================================================================


class TestTrailingPatternParsing:
    """Tests for TTM/LTM trailing period parsing."""

    def test_ttm_pattern(self, stage: PeriodInferenceStage) -> None:
        """Parse TTM pattern."""
        result = stage._try_parse_trailing("TTM Revenue $100M")
        assert result is not None
        assert result.period_type == PeriodType.TRAILING

    def test_ltm_pattern(self, stage: PeriodInferenceStage) -> None:
        """Parse LTM pattern."""
        result = stage._try_parse_trailing("LTM EBITDA")
        assert result is not None
        assert result.period_type == PeriodType.TRAILING

    def test_trailing_twelve_months(self, stage: PeriodInferenceStage) -> None:
        """Parse Trailing Twelve Months pattern."""
        result = stage._try_parse_trailing("Trailing Twelve Months Revenue")
        assert result is not None
        assert result.period_type == PeriodType.TRAILING

    def test_trailing_12_months(self, stage: PeriodInferenceStage) -> None:
        """Parse Trailing 12 Months pattern."""
        result = stage._try_parse_trailing("Trailing 12 Months")
        assert result is not None
        assert result.period_type == PeriodType.TRAILING

    def test_last_twelve_months(self, stage: PeriodInferenceStage) -> None:
        """Parse Last Twelve Months pattern."""
        result = stage._try_parse_trailing("Last Twelve Months ended December 31")
        assert result is not None
        assert result.period_type == PeriodType.TRAILING

    def test_ttm_with_as_of_date(self, stage: PeriodInferenceStage) -> None:
        """Parse TTM with associated as of date."""
        result = stage._try_parse_trailing("TTM as of December 31, 2024")
        assert result is not None
        assert result.period_type == PeriodType.TRAILING
        assert result.end == date(2024, 12, 31)


# ============================================================================
# YTD Pattern Tests
# ============================================================================


class TestYTDPatternParsing:
    """Tests for YTD pattern parsing."""

    def test_ytd_pattern(self, stage: PeriodInferenceStage) -> None:
        """Parse YTD pattern."""
        result = stage._try_parse_ytd("YTD Revenue 2024")
        assert result is not None
        assert result.period_type == PeriodType.YTD

    def test_year_to_date_pattern(self, stage: PeriodInferenceStage) -> None:
        """Parse year-to-date pattern."""
        result = stage._try_parse_ytd("year-to-date results")
        assert result is not None
        assert result.period_type == PeriodType.YTD

    def test_nine_months_ended_ytd(self, stage: PeriodInferenceStage) -> None:
        """Parse nine months ended as YTD."""
        result = stage._try_parse_ytd("Nine months ended 2024")
        assert result is not None
        assert result.period_type == PeriodType.YTD
        assert result.end.month == 9

    def test_six_months_ended_ytd(self, stage: PeriodInferenceStage) -> None:
        """Parse six months ended as YTD."""
        result = stage._try_parse_ytd("Six months ended")
        assert result is not None
        assert result.period_type == PeriodType.YTD
        assert result.end.month == 6


# ============================================================================
# As Of Pattern Tests
# ============================================================================


class TestAsOfPatternParsing:
    """Tests for 'as of' point-in-time pattern parsing."""

    def test_as_of_december_31_2024(self, stage: PeriodInferenceStage) -> None:
        """Parse As of December 31, 2024."""
        result = stage._try_parse_as_of("As of December 31, 2024")
        assert result is not None
        assert result.period_type == PeriodType.POINT_IN_TIME
        assert result.start == date(2024, 12, 31)
        assert result.end == date(2024, 12, 31)

    def test_at_march_31_2024(self, stage: PeriodInferenceStage) -> None:
        """Parse At March 31, 2024."""
        result = stage._try_parse_as_of("At March 31, 2024")
        assert result is not None
        assert result.period_type == PeriodType.POINT_IN_TIME
        assert result.start == date(2024, 3, 31)


# ============================================================================
# Table Header Extraction Tests
# ============================================================================


class TestTableHeaderExtraction:
    """Tests for period extraction from table headers."""

    def test_period_in_direct_header(
        self, stage: PeriodInferenceStage, mock_context: MagicMock
    ) -> None:
        """Extract period from direct column header."""
        table = make_table_with_headers("t1", ["Metric", "Q1 2024", "Q2 2024"])
        mock_context.tables = [table]
        mock_context.segments = []

        bound_value = make_bound_value(table_id="t1", cell_row=1, cell_col=1)
        mock_context.bound_values = [bound_value]

        stage.process(mock_context)

        assert bound_value.period_type == PeriodType.QUARTERLY
        assert bound_value.period_start == date(2024, 1, 1)
        assert bound_value.period_end == date(2024, 3, 31)
        assert bound_value.period_source == "header_path"
        assert bound_value.period_confidence == stage.HEADER_PATH_CONFIDENCE

    def test_period_in_fiscal_year_header(
        self, stage: PeriodInferenceStage, mock_context: MagicMock
    ) -> None:
        """Extract period from FY header."""
        table = make_table_with_headers("t1", ["Description", "FY 2024", "FY 2023"])
        mock_context.tables = [table]
        mock_context.segments = []

        bound_value = make_bound_value(table_id="t1", cell_row=1, cell_col=1)
        mock_context.bound_values = [bound_value]

        stage.process(mock_context)

        assert bound_value.period_type == PeriodType.ANNUAL
        assert bound_value.period_end == date(2024, 12, 31)

    def test_year_ended_in_header(
        self, stage: PeriodInferenceStage, mock_context: MagicMock
    ) -> None:
        """Extract period from 'Year Ended' header."""
        table = make_table_with_headers(
            "t1", ["Item", "Year Ended December 31, 2024", "Year Ended December 31, 2023"]
        )
        mock_context.tables = [table]
        mock_context.segments = []

        bound_value = make_bound_value(table_id="t1", cell_row=1, cell_col=1)
        mock_context.bound_values = [bound_value]

        stage.process(mock_context)

        assert bound_value.period_type == PeriodType.ANNUAL
        assert bound_value.period_end == date(2024, 12, 31)


# ============================================================================
# Text Context Extraction Tests
# ============================================================================


class TestTextContextExtraction:
    """Tests for period extraction from text context."""

    def test_period_in_same_sentence(
        self, stage: PeriodInferenceStage, mock_context: MagicMock
    ) -> None:
        """Extract period from same sentence as value."""
        segment = Segment(
            segment_id="s1",
            text="In Q1 2024, we had 1,000 customers, representing significant growth.",
        )
        mock_context.segments = [segment]
        mock_context.tables = []

        bound_value = make_bound_value(segment_id="s1", text_span=(20, 25))
        mock_context.bound_values = [bound_value]

        stage.process(mock_context)

        assert bound_value.period_type == PeriodType.QUARTERLY
        assert bound_value.period_start == date(2024, 1, 1)
        assert bound_value.period_source == "text_context"

    def test_period_in_extended_context(
        self, stage: PeriodInferenceStage, mock_context: MagicMock
    ) -> None:
        """Extract period from extended text context."""
        segment = Segment(
            segment_id="s1",
            text="For fiscal year 2024, the company reported strong results. Total customers reached 50,000.",
        )
        mock_context.segments = [segment]
        mock_context.tables = []

        bound_value = make_bound_value(segment_id="s1", text_span=(70, 76))
        mock_context.bound_values = [bound_value]

        stage.process(mock_context)

        assert bound_value.period_type == PeriodType.ANNUAL
        assert bound_value.period_end == date(2024, 12, 31)


# ============================================================================
# Filing Fallback Tests
# ============================================================================


class TestFilingFallback:
    """Tests for filing fiscal period fallback."""

    def test_fallback_to_filing_fiscal_year(
        self, stage: PeriodInferenceStage, mock_context: MagicMock
    ) -> None:
        """Use filing fiscal year when no context period found."""
        mock_context.tables = []
        mock_context.segments = []
        mock_context.document = Document(fiscal_year=2024, fiscal_period="FY")

        # Create bound value with no table or segment reference
        bound_value = BoundValue(
            candidate_id="test",
            value=100.0,
            source_locator=SourceLocator(),
        )
        mock_context.bound_values = [bound_value]

        stage.process(mock_context)

        assert bound_value.period_type == PeriodType.ANNUAL
        assert bound_value.period_end == date(2024, 12, 31)
        assert bound_value.period_source == "filing_fallback"
        assert bound_value.period_confidence == stage.FILING_FALLBACK_CONFIDENCE

    def test_fallback_to_filing_quarter(
        self, stage: PeriodInferenceStage, mock_context: MagicMock
    ) -> None:
        """Use filing quarter when no context period found."""
        mock_context.tables = []
        mock_context.segments = []
        mock_context.document = Document(fiscal_year=2024, fiscal_period="Q3")

        bound_value = BoundValue(
            candidate_id="test",
            value=100.0,
            source_locator=SourceLocator(),
        )
        mock_context.bound_values = [bound_value]

        stage.process(mock_context)

        assert bound_value.period_type == PeriodType.QUARTERLY
        assert bound_value.period_start == date(2024, 7, 1)
        assert bound_value.period_end == date(2024, 9, 30)


# ============================================================================
# Ambiguous Period Tests
# ============================================================================


class TestAmbiguousPeriodHandling:
    """Tests for ambiguous period detection and flagging."""

    def test_no_period_found_flagged_ambiguous(
        self, stage: PeriodInferenceStage, mock_context: MagicMock
    ) -> None:
        """Flag as ambiguous when no period found at all."""
        segment = Segment(
            segment_id="s1",
            text="The company has many customers across different regions.",
        )
        mock_context.segments = [segment]
        mock_context.tables = []
        mock_context.document = None  # No filing fallback

        bound_value = make_bound_value(segment_id="s1", text_span=(20, 30))
        mock_context.bound_values = [bound_value]

        stage.process(mock_context)

        assert bound_value.period_ambiguous is True
        assert bound_value.period_type == PeriodType.OTHER


# ============================================================================
# Integration Tests
# ============================================================================


class TestPeriodInferenceIntegration:
    """Integration tests for the full stage."""

    def test_full_stage_execution(
        self, stage: PeriodInferenceStage, mock_context: MagicMock
    ) -> None:
        """Test full stage execution with mixed sources."""
        # Setup table with Q1 2024 header
        table = make_table_with_headers("t1", ["Metric", "Q1 2024"])
        mock_context.tables = [table]

        # Setup segment with FY reference
        segment = Segment(
            segment_id="s1",
            text="In FY 2024, revenue increased to $100 million.",
        )
        mock_context.segments = [segment]

        # Create bound values
        table_bound = make_bound_value(table_id="t1", cell_row=1, cell_col=1)
        text_bound = make_bound_value(segment_id="s1", text_span=(30, 35))
        mock_context.bound_values = [table_bound, text_bound]

        mock_context.document = Document(fiscal_year=2024, fiscal_period="FY")

        result = stage.process(mock_context)

        assert result.success is True
        assert result.items_processed == 2
        assert table_bound.period_type == PeriodType.QUARTERLY
        assert text_bound.period_type == PeriodType.ANNUAL

    def test_stage_result_metadata(
        self, stage: PeriodInferenceStage, mock_context: MagicMock
    ) -> None:
        """Test that stage result contains proper metadata."""
        mock_context.tables = []
        mock_context.segments = []
        mock_context.document = None

        bound_value = BoundValue(
            candidate_id="test",
            value=100.0,
            source_locator=SourceLocator(),
        )
        mock_context.bound_values = [bound_value]

        result = stage.process(mock_context)

        assert result.success is True
        assert result.items_processed == 1
        assert "ambiguous_count" in result.metadata
        assert result.metadata["ambiguous_count"] == 1


# ============================================================================
# Year Normalization Tests
# ============================================================================


class TestYearNormalization:
    """Tests for 2-digit to 4-digit year conversion."""

    def test_24_becomes_2024(self, stage: PeriodInferenceStage) -> None:
        """Convert 24 to 2024."""
        assert stage._normalize_year("24") == 2024

    def test_99_becomes_1999(self, stage: PeriodInferenceStage) -> None:
        """Convert 99 to 1999."""
        assert stage._normalize_year("99") == 1999

    def test_00_becomes_2000(self, stage: PeriodInferenceStage) -> None:
        """Convert 00 to 2000."""
        assert stage._normalize_year("00") == 2000

    def test_30_becomes_2030(self, stage: PeriodInferenceStage) -> None:
        """Convert 30 to 2030 (boundary case)."""
        assert stage._normalize_year("30") == 2030

    def test_31_becomes_1931(self, stage: PeriodInferenceStage) -> None:
        """Convert 31 to 1931 (boundary case)."""
        assert stage._normalize_year("31") == 1931

    def test_2024_stays_2024(self, stage: PeriodInferenceStage) -> None:
        """4-digit year unchanged."""
        assert stage._normalize_year("2024") == 2024


# ============================================================================
# Edge Cases
# ============================================================================


class TestEdgeCases:
    """Tests for edge cases and error handling."""

    def test_leap_year_february(self, stage: PeriodInferenceStage) -> None:
        """Handle leap year February correctly."""
        assert stage._last_day_of_month(2024, 2) == 29
        assert stage._last_day_of_month(2023, 2) == 28

    def test_non_calendar_fiscal_year(self, stage: PeriodInferenceStage) -> None:
        """Parse non-calendar fiscal year end (e.g., ends March 31)."""
        result = stage._try_parse_period_ended("For the year ended March 31, 2025")
        assert result is not None
        assert result.period_type == PeriodType.ANNUAL
        assert result.end == date(2025, 3, 31)

    def test_invalid_date_skipped(self, stage: PeriodInferenceStage) -> None:
        """Skip invalid dates gracefully."""
        result = stage._try_parse_period_ended("Year ended February 30, 2024")
        assert result is None

    def test_empty_header_path(self, stage: PeriodInferenceStage) -> None:
        """Handle empty header path."""
        result = stage._parse_period_from_headers([])
        assert result is None

    def test_missing_table_gracefully(
        self, stage: PeriodInferenceStage, mock_context: MagicMock
    ) -> None:
        """Handle missing table reference gracefully."""
        mock_context.tables = []
        mock_context.segments = []
        mock_context.document = Document(fiscal_year=2024, fiscal_period="FY")

        bound_value = make_bound_value(table_id="nonexistent", cell_row=1, cell_col=1)
        mock_context.bound_values = [bound_value]

        result = stage.process(mock_context)

        # Should fallback to filing period
        assert result.success is True
        assert bound_value.period_type == PeriodType.ANNUAL

    def test_plain_year_in_header(self, stage: PeriodInferenceStage) -> None:
        """Parse plain year from header as fiscal year."""
        result = stage._try_parse_plain_year("Results for 2024")
        assert result is not None
        assert result.period_type == PeriodType.ANNUAL
        assert result.start == date(2024, 1, 1)
        assert result.end == date(2024, 12, 31)

    def test_plain_year_no_match(self, stage: PeriodInferenceStage) -> None:
        """Return None when no plain year found."""
        result = stage._try_parse_plain_year("No year here")
        assert result is None

    def test_invalid_month_in_as_of(self, stage: PeriodInferenceStage) -> None:
        """Handle invalid month name in as_of pattern."""
        result = stage._try_parse_as_of("As of Smarch 31, 2024")
        assert result is None

    def test_fiscal_fallback_with_empty_period(self, stage: PeriodInferenceStage) -> None:
        """Fiscal fallback with empty fiscal period string."""
        result = stage._create_fiscal_fallback(2024, "")
        assert result is not None
        assert result.period_type == PeriodType.ANNUAL

    def test_fiscal_fallback_invalid_period(self, stage: PeriodInferenceStage) -> None:
        """Fiscal fallback returns None for invalid period."""
        result = stage._create_fiscal_fallback(2024, "Q5")
        assert result is None

    def test_text_context_without_span(
        self, stage: PeriodInferenceStage, mock_context: MagicMock
    ) -> None:
        """Parse period from text without text_span."""
        segment = Segment(
            segment_id="s1",
            text="In Q1 2024, we had 1,000 customers.",
        )
        mock_context.segments = [segment]
        mock_context.tables = []
        mock_context.document = None

        # BoundValue with no text_span
        bound_value = make_bound_value(segment_id="s1")
        mock_context.bound_values = [bound_value]

        stage.process(mock_context)

        assert bound_value.period_type == PeriodType.QUARTERLY

    def test_ytd_no_year_in_text(self, stage: PeriodInferenceStage) -> None:
        """YTD pattern without year uses current year."""
        result = stage._try_parse_ytd("YTD revenue increased")
        assert result is not None
        assert result.period_type == PeriodType.YTD

    def test_three_months_ytd(self, stage: PeriodInferenceStage) -> None:
        """Three months ended as YTD."""
        result = stage._try_parse_ytd("Three months ended")
        assert result is not None
        assert result.period_type == PeriodType.YTD
        assert result.end.month == 3

    def test_period_default_fallback(self, stage: PeriodInferenceStage) -> None:
        """Default to annual for generic period ended patterns."""
        result = stage._try_parse_period_ended("Period ended December 31, 2024")
        assert result is not None
        assert result.period_type == PeriodType.ANNUAL

    def test_invalid_year_normalization(self, stage: PeriodInferenceStage) -> None:
        """Invalid year string returns None."""
        assert stage._normalize_year("abc") is None

    def test_year_out_of_range(self, stage: PeriodInferenceStage) -> None:
        """Year out of reasonable range returns None."""
        assert stage._normalize_year("1800") is None
        assert stage._normalize_year("2200") is None


# ============================================================================
# Respectively Pattern Period Hint Tests
# ============================================================================


class TestPeriodHintFromRespectively:
    """Tests for Strategy 0: period_hint pre-parsed by the respectively parser."""

    def test_period_hint_respected(
        self, stage: PeriodInferenceStage, mock_context: MagicMock
    ) -> None:
        """BoundValue with period_hint='2016' gets correct annual period."""
        bound_value = BoundValue(
            candidate_id="cand-resp-1",
            value=1.53,
            value_raw="1.53",
            binding_type="respectively_pattern",
            period_hint="2016",
            source_locator=SourceLocator(),
        )
        mock_context.bound_values = [bound_value]
        mock_context.segments = []
        mock_context.tables = []

        stage.process(mock_context)

        assert bound_value.period_type == PeriodType.ANNUAL
        assert bound_value.period_start == date(2016, 1, 1)
        assert bound_value.period_end == date(2016, 12, 31)
        assert bound_value.period_source == "respectively_hint"
        assert bound_value.period_confidence == pytest.approx(0.85)

    def test_period_hint_takes_priority_over_text_context(
        self, stage: PeriodInferenceStage, mock_context: MagicMock
    ) -> None:
        """Strategy 0 fires before Strategy 2 (text context)."""
        segment = Segment(
            segment_id="s-resp",
            doc_id="doc-1",
            text="Revenue for 2020 was high.",
        )
        mock_context.segments = [segment]
        mock_context.tables = []

        # BoundValue carries hint "2016" — should win over text context "2020"
        bound_value = BoundValue(
            candidate_id="cand-resp-2",
            value=1.42,
            value_raw="1.42",
            binding_type="respectively_pattern",
            period_hint="2016",
            source_locator=SourceLocator(segment_id="s-resp"),
        )
        mock_context.bound_values = [bound_value]

        stage.process(mock_context)

        assert bound_value.period_start == date(2016, 1, 1)
        assert bound_value.period_end == date(2016, 12, 31)

    def test_empty_period_hint_falls_through_to_normal_strategies(
        self, stage: PeriodInferenceStage, mock_context: MagicMock
    ) -> None:
        """An empty period_hint does not interfere with normal period inference."""
        segment = Segment(
            segment_id="s-normal",
            doc_id="doc-1",
            text="In Q1 2024, we had strong results.",
        )
        mock_context.segments = [segment]
        mock_context.tables = []

        bound_value = BoundValue(
            candidate_id="cand-normal-1",
            value=100.0,
            value_raw="100",
            period_hint="",  # empty — no respectively hint
            source_locator=SourceLocator(
                segment_id="s-normal",
                text_span=(7, 15),
            ),
        )
        mock_context.bound_values = [bound_value]

        stage.process(mock_context)

        # Normal strategies should still find Q1 2024 from text context
        assert bound_value.period_type == PeriodType.QUARTERLY
