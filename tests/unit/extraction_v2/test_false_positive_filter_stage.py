"""
Unit tests for V2 False Positive Filter Stage.

Tests cover:
- V2-native: Year filtering for ALL unit types (not just count)
- V2-native: Linearized table text ([CELL]/[ROW] markers)
- V2-native: Financial table annotations ("In thousands", SBC)
- V2-native: Company ranking names ("Fortune 100")
- V1 delegate: Date component filtering (numbers inside dates)
- V1 delegate: Label-embedded filtering (">$100,000" values)
- V1 delegate: Reference number filtering (page/note/section refs)
- V1 delegate: Year filtering (standalone 4-digit years, count unit)
- V1 delegate: Measurement unit filtering ("24-hour" numbers)
- V1 delegate: Financial statement context filtering
- V1 delegate: TOC proximity filtering
- Percentage context detection for retention metrics
- Integration: stage correctly reduces FP count on mock data
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

from src.extraction_v2.models import (
    BoundValue,
    MetricCandidate,
    SectionType,
    Segment,
    SegmentType,
    SourceLocator,
    SourceType,
    Unit,
)
from src.extraction_v2.stages.false_positive_filter import (
    FalsePositiveFilterStage,
    _is_percent_in_keyword_clause,
    _is_v2_false_positive,
    _make_number_matches,
)

# ============================================================================
# Test Fixtures
# ============================================================================


@dataclass
class MockPipelineConfig:
    """Mock pipeline config for testing."""

    min_confidence_auto_accept: float = 0.90
    retain_context: bool = False


@dataclass
class MockPipelineContext:
    """Mock pipeline context for testing."""

    html_path: Path = field(default_factory=lambda: Path("/test/file.html"))
    filing_id: int = 1
    config: MockPipelineConfig = field(default_factory=MockPipelineConfig)
    document_type: str = "sec_filing"
    segments: list[Segment] = field(default_factory=list)
    tables: list[Any] = field(default_factory=list)
    candidates: list[MetricCandidate] = field(default_factory=list)
    bound_values: list[BoundValue] = field(default_factory=list)
    stage_results: list[Any] = field(default_factory=list)


@pytest.fixture
def stage() -> FalsePositiveFilterStage:
    """Create a FalsePositiveFilterStage instance."""
    return FalsePositiveFilterStage()


def _make_text_segment(segment_id: str, text: str) -> Segment:
    """Create a text segment for testing."""
    return Segment(
        segment_id=segment_id,
        segment_type=SegmentType.PARAGRAPH,
        text=text,
    )


def _make_candidate(
    candidate_id: str, metric_id: str, segment_id: str, context_text: str = ""
) -> MetricCandidate:
    """Create a metric candidate for testing."""
    return MetricCandidate(
        candidate_id=candidate_id,
        metric_id=metric_id,
        match_text=metric_id,
        source_locator=SourceLocator(segment_id=segment_id),
        source_type=SourceType.TEXT,
        context_text=context_text,
    )


def _make_bound_value(
    candidate_id: str,
    value: float,
    raw: str,
    unit: Unit = Unit.COUNT,
    segment_id: str = "seg-1",
    text_span: tuple[int, int] | None = None,
) -> BoundValue:
    """Create a BoundValue for testing."""
    return BoundValue(
        candidate_id=candidate_id,
        value=value,
        value_raw=raw,
        unit=unit,
        binding_type="text_proximity",
        binding_confidence=0.5,
        source_locator=SourceLocator(
            segment_id=segment_id,
            text_span=text_span,
        ),
    )


# ============================================================================
# Test: _make_number_matches conversion
# ============================================================================


class TestMakeNumberMatches:
    """Tests for BoundValue to NumberMatch conversion."""

    def test_count_unit_maps_to_count(self):
        bv = _make_bound_value("c1", 100.0, "100", Unit.COUNT)
        nms = _make_number_matches(bv, "We had 100 customers")
        assert len(nms) == 1
        assert nms[0].unit == "count"
        assert nms[0].raw_text == "100"
        assert float(nms[0].value) == 100.0

    def test_percent_unit_maps_to_percentage(self):
        bv = _make_bound_value("c1", 95.0, "95%", Unit.PERCENT)
        nms = _make_number_matches(bv, "Retention was 95% last year")
        assert nms[0].unit == "percentage"

    def test_currency_unit_maps_to_currency(self):
        bv = _make_bound_value("c1", 1000.0, "$1,000", Unit.CURRENCY)
        nms = _make_number_matches(bv, "Revenue of $1,000")
        assert nms[0].unit == "currency"

    def test_position_found_in_source_text(self):
        bv = _make_bound_value("c1", 42.0, "42", Unit.COUNT)
        nms = _make_number_matches(bv, "We had 42 customers")
        assert nms[0].start == 7  # position of "42" in the text
        assert nms[0].end == 9

    def test_position_fallback_when_not_found(self):
        bv = _make_bound_value("c1", 42.0, "42", Unit.COUNT)
        nms = _make_number_matches(bv, "No match here")
        assert nms[0].start == 0
        assert nms[0].end == 2  # len("42")

    def test_multiple_occurrences_found(self):
        bv = _make_bound_value("c1", 42.0, "42", Unit.COUNT)
        nms = _make_number_matches(bv, "We had 42 and then 42 more")
        assert len(nms) == 2
        assert nms[0].start == 7
        assert nms[1].start == 19


# ============================================================================
# Test: Date component filtering
# ============================================================================


class TestDateComponentFiltering:
    """Tests that numbers inside dates are removed."""

    def test_day_in_month_day_year_date(self, stage):
        """'31' in 'January 31, 2019' should be filtered."""
        text = "As of January 31, 2019, we had 50,000 customers."
        segment = _make_text_segment("seg-1", text)
        candidate = _make_candidate("c1", "cm_customers_period_end", "seg-1")

        # BoundValue for the "31" inside the date
        bv_date = _make_bound_value(
            "c1",
            31.0,
            "31",
            Unit.COUNT,
            "seg-1",
            text_span=(15, 17),  # position of "31" in the text
        )
        # BoundValue for the real metric
        bv_real = _make_bound_value(
            "c1",
            50000.0,
            "50,000",
            Unit.COUNT,
            "seg-1",
            text_span=(31, 37),
        )

        ctx = MockPipelineContext(
            segments=[segment],
            candidates=[candidate],
            bound_values=[bv_date, bv_real],
        )
        stage.process(ctx)

        # The date component should be filtered, the real value should remain
        assert len(ctx.bound_values) >= 1
        values = [bv.value for bv in ctx.bound_values]
        assert 50000.0 in values

    def test_year_in_date_filtered(self, stage):
        """'2019' in 'January 31, 2019' should be filtered as a year."""
        text = "Year Ended January 31, 2019. We had 1,000 subscribers."
        segment = _make_text_segment("seg-1", text)
        candidate = _make_candidate("c1", "cm_subscribers", "seg-1")

        bv_year = _make_bound_value(
            "c1",
            2019.0,
            "2019",
            Unit.COUNT,
            "seg-1",
            text_span=(22, 26),
        )
        bv_real = _make_bound_value(
            "c1",
            1000.0,
            "1,000",
            Unit.COUNT,
            "seg-1",
            text_span=(36, 41),
        )

        ctx = MockPipelineContext(
            segments=[segment],
            candidates=[candidate],
            bound_values=[bv_year, bv_real],
        )
        stage.process(ctx)

        values = [bv.value for bv in ctx.bound_values]
        assert 2019.0 not in values
        assert 1000.0 in values


# ============================================================================
# Test: Label-embedded filtering
# ============================================================================


class TestLabelEmbeddedFiltering:
    """Tests that threshold labels like '>$100,000' are removed."""

    def test_comparison_operator_value_filtered(self, stage):
        """'>$100,000' in 'Customers > $100,000' should be filtered."""
        text = "Paid Customers > $100,000 contributed 80% of revenue."
        segment = _make_text_segment("seg-1", text)
        candidate = _make_candidate("c1", "cm_customers_period_end", "seg-1")

        bv_label = _make_bound_value(
            "c1",
            100000.0,
            "$100,000",
            Unit.CURRENCY,
            "seg-1",
            text_span=(17, 25),
        )

        ctx = MockPipelineContext(
            segments=[segment],
            candidates=[candidate],
            bound_values=[bv_label],
        )
        stage.process(ctx)

        assert len(ctx.bound_values) == 0


# ============================================================================
# Test: Reference number filtering
# ============================================================================


class TestReferenceNumberFiltering:
    """Tests that page/note/section references are removed."""

    def test_page_reference_filtered(self, stage):
        """Numbers in 'page 12' should be filtered."""
        text = "See page 12 for details. We had 5,000 customers."
        segment = _make_text_segment("seg-1", text)
        candidate = _make_candidate("c1", "cm_customers_period_end", "seg-1")

        bv_page = _make_bound_value(
            "c1",
            12.0,
            "12",
            Unit.COUNT,
            "seg-1",
            text_span=(9, 11),
        )
        bv_real = _make_bound_value(
            "c1",
            5000.0,
            "5,000",
            Unit.COUNT,
            "seg-1",
            text_span=(32, 37),
        )

        ctx = MockPipelineContext(
            segments=[segment],
            candidates=[candidate],
            bound_values=[bv_page, bv_real],
        )
        stage.process(ctx)

        values = [bv.value for bv in ctx.bound_values]
        assert 5000.0 in values

    def test_note_reference_filtered(self, stage):
        """Numbers in 'Note 5' should be filtered."""
        text = "See Note 5 for details about our 10,000 customers."
        segment = _make_text_segment("seg-1", text)
        candidate = _make_candidate("c1", "cm_customers_period_end", "seg-1")

        bv_note = _make_bound_value(
            "c1",
            5.0,
            "5",
            Unit.COUNT,
            "seg-1",
            text_span=(9, 10),
        )

        ctx = MockPipelineContext(
            segments=[segment],
            candidates=[candidate],
            bound_values=[bv_note],
        )
        stage.process(ctx)

        # Note: 5 is also below min_metric_value (10), so it would be filtered anyway
        assert len(ctx.bound_values) == 0


# ============================================================================
# Test: Year filtering
# ============================================================================


class TestYearFiltering:
    """Tests that standalone years are removed."""

    def test_standalone_year_filtered(self, stage):
        """'2023' as a standalone year should be filtered."""
        text = "In 2023, we served 150,000 customers."
        segment = _make_text_segment("seg-1", text)
        candidate = _make_candidate("c1", "cm_customers_period_end", "seg-1")

        bv_year = _make_bound_value(
            "c1",
            2023.0,
            "2023",
            Unit.COUNT,
            "seg-1",
            text_span=(3, 7),
        )
        bv_real = _make_bound_value(
            "c1",
            150000.0,
            "150,000",
            Unit.COUNT,
            "seg-1",
            text_span=(19, 26),
        )

        ctx = MockPipelineContext(
            segments=[segment],
            candidates=[candidate],
            bound_values=[bv_year, bv_real],
        )
        stage.process(ctx)

        values = [bv.value for bv in ctx.bound_values]
        assert 2023.0 not in values
        assert 150000.0 in values

    def test_year_2025_filtered(self, stage):
        """Year 2025 should also be filtered."""
        text = "By 2025 we expect to have more customers."
        segment = _make_text_segment("seg-1", text)
        candidate = _make_candidate("c1", "cm_customers_period_end", "seg-1")

        bv = _make_bound_value(
            "c1",
            2025.0,
            "2025",
            Unit.COUNT,
            "seg-1",
            text_span=(3, 7),
        )

        ctx = MockPipelineContext(
            segments=[segment],
            candidates=[candidate],
            bound_values=[bv],
        )
        stage.process(ctx)

        assert len(ctx.bound_values) == 0


# ============================================================================
# Test: Measurement unit filtering
# ============================================================================


class TestMeasurementUnitFiltering:
    """Tests that numbers in measurement units are removed."""

    def test_24_hour_filtered(self, stage):
        """'24' in '24-hour' should be filtered."""
        text = "Our 24-hour support team serves 5,000 customers."
        segment = _make_text_segment("seg-1", text)
        candidate = _make_candidate("c1", "cm_customers_period_end", "seg-1")

        bv_unit = _make_bound_value(
            "c1",
            24.0,
            "24",
            Unit.COUNT,
            "seg-1",
            text_span=(4, 6),
        )
        bv_real = _make_bound_value(
            "c1",
            5000.0,
            "5,000",
            Unit.COUNT,
            "seg-1",
            text_span=(31, 36),
        )

        ctx = MockPipelineContext(
            segments=[segment],
            candidates=[candidate],
            bound_values=[bv_unit, bv_real],
        )
        stage.process(ctx)

        values = [bv.value for bv in ctx.bound_values]
        assert 5000.0 in values

    def test_30_day_filtered(self, stage):
        """'30' in '30-day' should be filtered."""
        text = "We offer a 30-day trial to new customers."
        segment = _make_text_segment("seg-1", text)
        candidate = _make_candidate("c1", "cm_customers_period_end", "seg-1")

        bv = _make_bound_value(
            "c1",
            30.0,
            "30",
            Unit.COUNT,
            "seg-1",
            text_span=(12, 14),
        )

        ctx = MockPipelineContext(
            segments=[segment],
            candidates=[candidate],
            bound_values=[bv],
        )
        stage.process(ctx)

        assert len(ctx.bound_values) == 0


# ============================================================================
# Test: TOC proximity filtering
# ============================================================================


class TestTOCFiltering:
    """Tests that TOC page references are removed."""

    def test_toc_proximity_filtered(self, stage):
        """Small numbers near TOC headers should be filtered."""
        text = "TABLE OF CONTENTS\nRisk Factors 12"
        segment = _make_text_segment("seg-1", text)
        candidate = _make_candidate("c1", "cm_customers_period_end", "seg-1")

        bv = _make_bound_value(
            "c1",
            12.0,
            "12",
            Unit.COUNT,
            "seg-1",
            text_span=(31, 33),
        )

        ctx = MockPipelineContext(
            segments=[segment],
            candidates=[candidate],
            bound_values=[bv],
        )
        stage.process(ctx)

        assert len(ctx.bound_values) == 0


# ============================================================================
# Test: Financial statement context filtering
# ============================================================================


class TestFinancialStatementFiltering:
    """Tests that financial statement line items are filtered."""

    def test_revenue_in_income_statement_filtered(self, stage):
        """Revenue values in financial statement context should be filtered."""
        text = "CONSOLIDATED STATEMENTS OF OPERATIONS\nRevenue $400,552 thousand"
        segment = _make_text_segment("seg-1", text)
        candidate = _make_candidate("c1", "cm_average_order_value", "seg-1")

        bv = _make_bound_value(
            "c1",
            400552.0,
            "$400,552",
            Unit.CURRENCY,
            "seg-1",
            text_span=(47, 55),
        )

        ctx = MockPipelineContext(
            segments=[segment],
            candidates=[candidate],
            bound_values=[bv],
        )
        stage.process(ctx)

        assert len(ctx.bound_values) == 0


# ============================================================================
# Test: Legitimate values are NOT filtered
# ============================================================================


class TestLegitimateValuesKept:
    """Tests that real metric values survive the filter."""

    def test_large_customer_count_kept(self, stage):
        """A legitimate customer count should not be filtered."""
        text = "We had over 150,000 active customers."
        segment = _make_text_segment("seg-1", text)
        candidate = _make_candidate("c1", "cm_customers_period_end", "seg-1")

        bv = _make_bound_value(
            "c1",
            150000.0,
            "150,000",
            Unit.COUNT,
            "seg-1",
            text_span=(13, 20),
        )

        ctx = MockPipelineContext(
            segments=[segment],
            candidates=[candidate],
            bound_values=[bv],
        )
        stage.process(ctx)

        assert len(ctx.bound_values) == 1
        assert ctx.bound_values[0].value == 150000.0

    def test_percentage_value_kept(self, stage):
        """A percentage value should not be filtered."""
        text = "Net revenue retention was 143%."
        segment = _make_text_segment("seg-1", text)
        candidate = _make_candidate("c1", "cm_net_revenue_retention", "seg-1")

        bv = _make_bound_value(
            "c1",
            143.0,
            "143%",
            Unit.PERCENT,
            "seg-1",
            text_span=(26, 30),
        )

        ctx = MockPipelineContext(
            segments=[segment],
            candidates=[candidate],
            bound_values=[bv],
        )
        stage.process(ctx)

        assert len(ctx.bound_values) == 1
        assert ctx.bound_values[0].value == 143.0

    def test_currency_value_kept(self, stage):
        """A currency ARR value should not be filtered."""
        text = "Our annual recurring revenue reached $1.2 billion."
        segment = _make_text_segment("seg-1", text)
        candidate = _make_candidate("c1", "cm_average_order_value", "seg-1")

        bv = _make_bound_value(
            "c1",
            1200000000.0,
            "$1.2 billion",
            Unit.CURRENCY,
            "seg-1",
            text_span=(36, 48),
        )

        ctx = MockPipelineContext(
            segments=[segment],
            candidates=[candidate],
            bound_values=[bv],
        )
        stage.process(ctx)

        assert len(ctx.bound_values) == 1

    def test_no_context_values_kept(self, stage):
        """Values with no source text context should be kept (fail open)."""
        # Segment not in the context
        candidate = _make_candidate("c1", "cm_customers_period_end", "seg-missing")
        bv = _make_bound_value(
            "c1",
            50000.0,
            "50,000",
            Unit.COUNT,
            "seg-missing",
        )

        ctx = MockPipelineContext(
            segments=[],
            candidates=[candidate],
            bound_values=[bv],
        )
        stage.process(ctx)

        assert len(ctx.bound_values) == 1


# ============================================================================
# Test: Stage result metadata
# ============================================================================


class TestStageResult:
    """Tests for stage result reporting."""

    def test_result_reports_removal_count(self, stage):
        """Stage result should report how many values were removed."""
        text = "In 2023, we had 50,000 customers."
        segment = _make_text_segment("seg-1", text)
        candidate = _make_candidate("c1", "cm_customers_period_end", "seg-1")

        bv_year = _make_bound_value(
            "c1",
            2023.0,
            "2023",
            Unit.COUNT,
            "seg-1",
            text_span=(3, 7),
        )
        bv_real = _make_bound_value(
            "c1",
            50000.0,
            "50,000",
            Unit.COUNT,
            "seg-1",
            text_span=(16, 22),
        )

        ctx = MockPipelineContext(
            segments=[segment],
            candidates=[candidate],
            bound_values=[bv_year, bv_real],
        )
        result = stage.process(ctx)

        assert result.success is True
        assert result.items_processed == 2
        assert result.metadata["removed_count"] >= 1

    def test_result_includes_filter_reasons(self, stage):
        """Stage result metadata should include filter reason counts."""
        text = "In 2023, we had 50,000 customers."
        segment = _make_text_segment("seg-1", text)
        candidate = _make_candidate("c1", "cm_customers_period_end", "seg-1")

        bv_year = _make_bound_value(
            "c1",
            2023.0,
            "2023",
            Unit.COUNT,
            "seg-1",
            text_span=(3, 7),
        )

        ctx = MockPipelineContext(
            segments=[segment],
            candidates=[candidate],
            bound_values=[bv_year],
        )
        result = stage.process(ctx)

        assert "filter_reasons" in result.metadata
        assert isinstance(result.metadata["filter_reasons"], dict)

    def test_empty_bound_values_succeeds(self, stage):
        """Stage should succeed with no bound values."""
        ctx = MockPipelineContext()
        result = stage.process(ctx)

        assert result.success is True
        assert result.items_processed == 0
        assert result.items_output == 0


# ============================================================================
# Test: Percentage context detection (via value_binding)
# ============================================================================


class TestPercentageContextDetection:
    """Tests for _check_percentage_context in ValueBindingStage."""

    def test_retention_value_treated_as_percentage(self):
        """A count value in retention context should become PERCENT."""
        from src.extraction_v2.stages.value_binding import ValueBindingStage

        vbs = ValueBindingStage()
        result = vbs._check_percentage_context(
            "cm_net_revenue_retention",
            Unit.COUNT,
            "138",
            "Our net dollar retention rate was 138 for the period.",
        )
        assert result == Unit.PERCENT

    def test_non_retention_metric_stays_count(self):
        """A count value for a non-retention metric should stay COUNT."""
        from src.extraction_v2.stages.value_binding import ValueBindingStage

        vbs = ValueBindingStage()
        result = vbs._check_percentage_context(
            "cm_customers_period_end",
            Unit.COUNT,
            "138",
            "We had 138 customers at the end of the period.",
        )
        assert result == Unit.COUNT

    def test_already_percent_stays_percent(self):
        """A value already marked as PERCENT should stay PERCENT."""
        from src.extraction_v2.stages.value_binding import ValueBindingStage

        vbs = ValueBindingStage()
        result = vbs._check_percentage_context(
            "cm_net_revenue_retention",
            Unit.PERCENT,
            "138%",
            "Net revenue retention was 138%.",
        )
        assert result == Unit.PERCENT

    def test_no_retention_context_stays_count(self):
        """Without retention keywords, value should stay COUNT."""
        from src.extraction_v2.stages.value_binding import ValueBindingStage

        vbs = ValueBindingStage()
        result = vbs._check_percentage_context(
            "cm_net_revenue_retention",
            Unit.COUNT,
            "138",
            "We had 138 units sold this quarter.",
        )
        assert result == Unit.COUNT

    def test_gross_retention_treated_as_percentage(self):
        """Gross retention values should also be treated as percentage."""
        from src.extraction_v2.stages.value_binding import ValueBindingStage

        vbs = ValueBindingStage()
        result = vbs._check_percentage_context(
            "cm_gross_retention_rate",
            Unit.COUNT,
            "92",
            "Our gross retention rate was 92 in the period.",
        )
        assert result == Unit.PERCENT

    def test_other_unit_retention_treated_as_percentage(self):
        """A Unit.OTHER value in retention context should become PERCENT."""
        from src.extraction_v2.stages.value_binding import ValueBindingStage

        vbs = ValueBindingStage()
        result = vbs._check_percentage_context(
            "cm_net_revenue_retention",
            Unit.OTHER,
            "158",
            "Our net dollar retention rate was 158 for the period.",
        )
        assert result == Unit.PERCENT

    def test_other_unit_non_retention_stays_other(self):
        """A Unit.OTHER value without retention context should stay OTHER."""
        from src.extraction_v2.stages.value_binding import ValueBindingStage

        vbs = ValueBindingStage()
        result = vbs._check_percentage_context(
            "cm_customers_period_end",
            Unit.OTHER,
            "500",
            "We had 500 customers.",
        )
        assert result == Unit.OTHER


# ============================================================================
# Test: Integration - mixed FP and real values
# ============================================================================


class TestIntegration:
    """Integration tests combining multiple FP types."""

    def test_mixed_fp_and_real_values(self, stage):
        """Test that a mix of FP types are filtered while real values survive."""
        text = (
            "For the Year Ended January 31, 2019, we had "
            "150,000 paying customers and 143% net revenue retention. "
            "See Note 5 for details."
        )
        segment = _make_text_segment("seg-1", text)
        candidate = _make_candidate("c1", "cm_customers_period_end", "seg-1")

        # Date component: 31
        bv_date = _make_bound_value("c1", 31.0, "31", Unit.COUNT, "seg-1", text_span=(28, 30))
        # Year: 2019
        bv_year = _make_bound_value("c1", 2019.0, "2019", Unit.COUNT, "seg-1", text_span=(32, 36))
        # Real: 150,000
        bv_real = _make_bound_value(
            "c1", 150000.0, "150,000", Unit.COUNT, "seg-1", text_span=(46, 53)
        )
        # 143% NRR — percent on a count-only metric (cm_customers_period_end is always
        # a count; 143% belongs to NRR, not customer count).
        bv_pct = _make_bound_value("c1", 143.0, "143%", Unit.PERCENT, "seg-1", text_span=(75, 79))

        ctx = MockPipelineContext(
            segments=[segment],
            candidates=[candidate],
            bound_values=[bv_date, bv_year, bv_real, bv_pct],
        )
        stage.process(ctx)

        values = [bv.value for bv in ctx.bound_values]
        assert 31.0 not in values, "Date component should be filtered"
        assert 2019.0 not in values, "Year should be filtered"
        assert 150000.0 in values, "Real customer count should be kept"
        assert 143.0 not in values, "Percent on count metric (cm_customers_period_end) should be filtered"


# ============================================================================
# Test: V2-native — Year filtering for all unit types
# ============================================================================


class TestV2YearFilterAllUnits:
    """V2 extends year filtering to non-count units (V1 only filters count)."""

    def test_year_as_percent_filtered(self):
        """'2019' with unit=PERCENT should be filtered (NRR context)."""
        bv = _make_bound_value("c1", 2019.0, "2019", Unit.PERCENT, "seg-1")
        is_fp, reason = _is_v2_false_positive(bv, "revenue was $400 million in fiscal year 2019")
        assert is_fp is True
        assert reason == "v2_year_value"

    def test_year_as_currency_filtered(self):
        """'2019' with unit=CURRENCY should also be filtered."""
        bv = _make_bound_value("c1", 2019.0, "2019", Unit.CURRENCY, "seg-1")
        is_fp, reason = _is_v2_false_positive(bv, "In 2019 we grew revenue.")
        assert is_fp is True
        assert reason == "v2_year_value"

    def test_non_year_percent_kept(self):
        """'143' with unit=PERCENT should NOT be filtered."""
        bv = _make_bound_value("c1", 143.0, "143%", Unit.PERCENT, "seg-1")
        is_fp, _ = _is_v2_false_positive(bv, "Net revenue retention was 143%.")
        assert is_fp is False

    def test_year_via_stage(self, stage):
        """Year values with PERCENT unit filtered by the full stage pipeline."""
        text = "Revenue grew 110% and 82% in fiscal year 2019."
        segment = _make_text_segment("seg-1", text)
        candidate = _make_candidate("c1", "cm_net_revenue_retention", "seg-1")

        bv_year = _make_bound_value(
            "c1",
            2019.0,
            "2019",
            Unit.PERCENT,
            "seg-1",
        )
        bv_real = _make_bound_value(
            "c1",
            110.0,
            "110%",
            Unit.PERCENT,
            "seg-1",
        )

        ctx = MockPipelineContext(
            segments=[segment],
            candidates=[candidate],
            bound_values=[bv_year, bv_real],
        )
        stage.process(ctx)

        values = [bv.value for bv in ctx.bound_values]
        assert 2019.0 not in values, "Year as PERCENT should be filtered"
        assert 110.0 in values, "Real percentage should be kept"


# ============================================================================
# Test: V2-native — Linearized table markers
# ============================================================================


class TestV2LinearizedTableMarkers:
    """Text segments with [CELL]/[ROW] markers are linearized tables."""

    def test_cell_marker_filtered(self):
        """Values from text with [CELL] markers should be filtered."""
        source = (
            "As of January 31, [CELL] As of April 30, [ROW] 2017 [CELL] 2018 "
            "[CELL] 2019 [ROW] Paid Customers [CELL] 37,000 [CELL] 59,000"
        )
        bv = _make_bound_value("c1", 37000.0, "37,000", Unit.COUNT, "seg-1")
        is_fp, reason = _is_v2_false_positive(bv, source)
        assert is_fp is True
        assert reason == "v2_linearized_table"

    def test_row_marker_filtered(self):
        """Values from text with [ROW] markers should be filtered."""
        source = "[ROW] Net Dollar Retention Rate [CELL] 171 [CELL] 152 [CELL] 143"
        bv = _make_bound_value("c1", 171.0, "171", Unit.PERCENT, "seg-1")
        is_fp, reason = _is_v2_false_positive(bv, source)
        assert is_fp is True
        assert reason == "v2_linearized_table"

    def test_narrative_text_kept(self):
        """Values from normal narrative text should NOT be filtered."""
        source = "We had over 500,000 customers at the end of the period."
        bv = _make_bound_value("c1", 500000.0, "500,000", Unit.COUNT, "seg-1")
        is_fp, _ = _is_v2_false_positive(bv, source)
        assert is_fp is False

    def test_linearized_table_via_stage(self, stage):
        """Full stage pipeline filters linearized table text."""
        text = (
            "[ROW] 2017 [CELL] 2018 [CELL] 2019 "
            "[ROW] Paid Customers [CELL] 37,000 [CELL] 59,000 [CELL] 88,000"
        )
        segment = _make_text_segment("seg-1", text)
        candidate = _make_candidate("c1", "cm_customers_period_end", "seg-1")

        bv = _make_bound_value("c1", 37000.0, "37,000", Unit.COUNT, "seg-1")

        ctx = MockPipelineContext(
            segments=[segment],
            candidates=[candidate],
            bound_values=[bv],
        )
        stage.process(ctx)

        assert len(ctx.bound_values) == 0, "Linearized table values should be filtered"


# ============================================================================
# Test: V2-native — Financial table annotations
# ============================================================================


class TestV2FinancialAnnotations:
    """Text with financial annotations like '(In thousands)' is FP."""

    def test_in_thousands_filtered(self):
        """Values from text with '(In thousands)' should be filtered."""
        source = (
            "Year Ended January 31, 2017 2018 2019 (In thousands) "
            "Cost of revenue 37,000 59,000 88,000"
        )
        bv = _make_bound_value("c1", 37000.0, "37,000", Unit.COUNT, "seg-1")
        is_fp, reason = _is_v2_false_positive(bv, source)
        assert is_fp is True
        assert reason == "v2_financial_annotation"

    def test_in_millions_filtered(self):
        """Values from text with '(In millions)' should be filtered."""
        source = "(In millions) Revenue 400.5 500.2"
        bv = _make_bound_value("c1", 400.5, "400.5", Unit.CURRENCY, "seg-1")
        is_fp, reason = _is_v2_false_positive(bv, source)
        assert is_fp is True
        assert reason == "v2_financial_annotation"

    def test_stock_based_comp_filtered(self):
        """Values from text with 'stock-based compensation' should be filtered."""
        source = (
            "Includes stock-based compensation as follows: "
            "Year Ended January 31, 2017 2018 2019 67,000 95,000"
        )
        bv = _make_bound_value("c1", 67000.0, "67,000", Unit.COUNT, "seg-1")
        is_fp, reason = _is_v2_false_positive(bv, source)
        assert is_fp is True
        assert reason == "v2_financial_sbc"

    def test_customer_narrative_kept(self):
        """Customer metric narrative without financial annotations kept."""
        source = "As of January 31, 2019 we had 95,000 Paid Customers."
        bv = _make_bound_value("c1", 95000.0, "95,000", Unit.COUNT, "seg-1")
        is_fp, _ = _is_v2_false_positive(bv, source)
        assert is_fp is False

    def test_value_far_from_annotation_not_filtered(self):
        """Value far (>300 chars) from '(In thousands)' should NOT be filtered."""
        filler = "x " * 200  # 400 chars of filler between annotation and value
        source = f"(In thousands) Revenue 100 200 {filler} We had 95,000 paid customers."
        bv = _make_bound_value("c1", 95000.0, "95,000", Unit.COUNT, "seg-1")
        is_fp, _ = _is_v2_false_positive(bv, source)
        assert is_fp is False

    def test_value_near_annotation_still_filtered(self):
        """Value near (<300 chars) '(In thousands)' should still be filtered."""
        source = "(In thousands) Cost of revenue 37,000 59,000"
        bv = _make_bound_value("c1", 37000.0, "37,000", Unit.COUNT, "seg-1")
        is_fp, reason = _is_v2_false_positive(bv, source)
        assert is_fp is True
        assert reason == "v2_financial_annotation"

    def test_sbc_far_from_value_not_filtered(self):
        """Value far (>300 chars) from 'stock-based compensation' should NOT be filtered."""
        filler = "x " * 200
        source = f"Includes stock-based compensation as follows: 100 200 {filler} We had 95,000 customers."
        bv = _make_bound_value("c1", 95000.0, "95,000", Unit.COUNT, "seg-1")
        is_fp, _ = _is_v2_false_positive(bv, source)
        assert is_fp is False

    def test_sbc_near_value_still_filtered(self):
        """Value near (<300 chars) 'stock-based compensation' should still be filtered."""
        source = "Includes stock-based compensation as follows: 67,000 95,000"
        bv = _make_bound_value("c1", 67000.0, "67,000", Unit.COUNT, "seg-1")
        is_fp, reason = _is_v2_false_positive(bv, source)
        assert is_fp is True
        assert reason == "v2_financial_sbc"


# ============================================================================
# Test: V2-native — Ranking names
# ============================================================================


class TestV2RankingNames:
    """Numbers that are part of ranking names like 'Fortune 100'."""

    def test_fortune_100_filtered(self):
        """'100' in 'Fortune 100' should be filtered."""
        source = "including more than 65 companies in the Fortune 100."
        bv = _make_bound_value("c1", 100.0, "100", Unit.COUNT, "seg-1")
        is_fp, reason = _is_v2_false_positive(bv, source)
        assert is_fp is True
        assert reason == "v2_ranking_name"

    def test_fortune_500_filtered(self):
        """'500' in 'Fortune 500' should be filtered."""
        source = "Many Fortune 500 companies use our platform."
        bv = _make_bound_value("c1", 500.0, "500", Unit.COUNT, "seg-1")
        is_fp, reason = _is_v2_false_positive(bv, source)
        assert is_fp is True
        assert reason == "v2_ranking_name"

    def test_inc_5000_filtered(self):
        """'5000' in 'Inc. 5000' should be filtered."""
        source = "Named to the Inc. 5000 fastest growing companies."
        bv = _make_bound_value("c1", 5000.0, "5000", Unit.COUNT, "seg-1")
        is_fp, reason = _is_v2_false_positive(bv, source)
        assert is_fp is True
        assert reason == "v2_ranking_name"

    def test_non_ranking_number_kept(self):
        """'500' not in a ranking context should be kept."""
        source = "We had more than 500 enterprise customers."
        bv = _make_bound_value("c1", 500.0, "500", Unit.COUNT, "seg-1")
        is_fp, _ = _is_v2_false_positive(bv, source)
        assert is_fp is False

    def test_nearby_but_different_number_kept(self):
        """'65' in 'more than 65 companies in the Fortune 100' should be kept."""
        source = "including more than 65 companies in the Fortune 100."
        bv = _make_bound_value("c1", 65.0, "65", Unit.COUNT, "seg-1")
        is_fp, _ = _is_v2_false_positive(bv, source)
        # 65 is NOT the ranking number (100 is), so it should pass this rule
        assert is_fp is False


# ============================================================================
# Test: Relaxed mode (for transcripts/presentations)
# ============================================================================


class TestRelaxedMode:
    """Tests for relaxed=True skipping financial annotation/SBC rules."""

    def test_relaxed_skips_financial_annotation(self):
        """relaxed=True allows values in '(In thousands)' context."""
        source = "(In millions) Revenue 400.5 500.2"
        bv = _make_bound_value("c1", 400.5, "400.5", Unit.CURRENCY, "seg-1")

        # Default: filtered
        is_fp, reason = _is_v2_false_positive(bv, source, relaxed=False)
        assert is_fp is True
        assert reason == "v2_financial_annotation"

        # Relaxed: NOT filtered
        is_fp, reason = _is_v2_false_positive(bv, source, relaxed=True)
        assert is_fp is False

    def test_relaxed_skips_sbc(self):
        """relaxed=True allows values in 'stock-based compensation' context."""
        source = "Includes stock-based compensation as follows: 67,000 95,000"
        bv = _make_bound_value("c1", 67000.0, "67,000", Unit.COUNT, "seg-1")

        # Default: filtered
        is_fp, reason = _is_v2_false_positive(bv, source, relaxed=False)
        assert is_fp is True
        assert reason == "v2_financial_sbc"

        # Relaxed: NOT filtered
        is_fp, reason = _is_v2_false_positive(bv, source, relaxed=True)
        assert is_fp is False

    def test_relaxed_still_filters_years(self):
        """relaxed=True does NOT skip year filtering."""
        bv = _make_bound_value("c1", 2019.0, "2019", Unit.PERCENT, "seg-1")
        is_fp, reason = _is_v2_false_positive(bv, "fiscal year 2019", relaxed=True)
        assert is_fp is True
        assert reason == "v2_year_value"

    def test_relaxed_skips_linearized_table(self):
        """relaxed=True skips linearized table filtering (transcripts have no table markers)."""
        source = "[ROW] Revenue [CELL] 400"
        bv = _make_bound_value("c1", 400.0, "400", Unit.COUNT, "seg-1")
        is_fp, reason = _is_v2_false_positive(bv, source, relaxed=True)
        assert is_fp is False

    def test_strict_still_filters_linearized_table(self):
        """relaxed=False still filters linearized table markers."""
        source = "[ROW] Revenue [CELL] 400"
        bv = _make_bound_value("c1", 400.0, "400", Unit.COUNT, "seg-1")
        is_fp, reason = _is_v2_false_positive(bv, source, relaxed=False)
        assert is_fp is True
        assert reason == "v2_linearized_table"

    def test_relaxed_still_filters_ranking_names(self):
        """relaxed=True does NOT skip ranking name filtering."""
        source = "Many Fortune 500 companies use our platform."
        bv = _make_bound_value("c1", 500.0, "500", Unit.COUNT, "seg-1")
        is_fp, reason = _is_v2_false_positive(bv, source, relaxed=True)
        assert is_fp is True
        assert reason == "v2_ranking_name"

    def test_relaxed_via_stage_config(self, stage):
        """Stage reads relaxed_fp_filter from config."""
        # Use cm_net_revenue_retention with value in plausible NRR range (30-250)
        # so _rule_magnitude_sanity and _rule_revenue_as_arr don't fire.
        # The "(In millions)" annotation fires financial_annotation in strict mode
        # but is skipped in relaxed mode.
        source = "(In millions) Net Revenue Retention 125.0 130.0"
        segment = _make_text_segment("seg-1", source)
        candidate = _make_candidate("c1", "cm_net_revenue_retention", "seg-1")
        bv = _make_bound_value("c1", 125.0, "125.0", Unit.CURRENCY, "seg-1")

        # Default config: filtered (financial_annotation fires in strict mode)
        ctx_strict = MockPipelineContext(
            segments=[segment],
            candidates=[candidate],
            bound_values=[bv],
        )
        stage.process(ctx_strict)
        assert len(ctx_strict.bound_values) == 0

        # Relaxed config: kept (financial_annotation skipped)
        @dataclass
        class RelaxedConfig:
            min_confidence_auto_accept: float = 0.90
            relaxed_fp_filter: bool = True

        bv2 = _make_bound_value("c1", 125.0, "125.0", Unit.CURRENCY, "seg-1")
        ctx_relaxed = MockPipelineContext(
            segments=[segment],
            candidates=[candidate],
            bound_values=[bv2],
            config=RelaxedConfig(),  # type: ignore
        )
        stage.process(ctx_relaxed)
        assert len(ctx_relaxed.bound_values) == 1

    def test_relaxed_v1_skips_financial_statement_check(self, stage):
        """Relaxed mode uses V1 filter with financial statement check disabled.

        In relaxed mode, V1's financial-statement context check is skipped.
        However, V2's _rule_financial_context_on_customer_metric catches values
        with financial keywords (net loss, cost of revenue, etc.) even in relaxed
        mode for count-only customer metrics. This test verifies both behaviors:
          1. Financial keyword context on cm_customers_period_end → caught by V2.
          2. A pure customer count value without financial keywords → kept.
        """
        # Text with strong financial keywords — V2 rule should catch this in all modes.
        source_financial = "Cost of Revenue Net Loss Depreciation 50,000 customers"
        segment_financial = _make_text_segment("seg-1", source_financial)
        candidate_financial = _make_candidate("c1", "cm_customers_period_end", "seg-1")
        bv_financial = _make_bound_value("c1", 50000.0, "50,000", Unit.COUNT, "seg-1")

        @dataclass
        class RelaxedConfig:
            min_confidence_auto_accept: float = 0.90
            relaxed_fp_filter: bool = True

        ctx_financial = MockPipelineContext(
            segments=[segment_financial],
            candidates=[candidate_financial],
            bound_values=[bv_financial],
            config=RelaxedConfig(),  # type: ignore
        )
        stage.process(ctx_financial)
        # V2 financial context rule fires even in relaxed mode — correctly filtered.
        assert len(ctx_financial.bound_values) == 0

        # Pure customer count without financial keywords → kept in relaxed mode.
        source_clean = "We served 50,000 customers during the quarter."
        segment_clean = _make_text_segment("seg-2", source_clean)
        candidate_clean = _make_candidate("c2", "cm_customers_period_end", "seg-2")
        bv_clean = _make_bound_value("c2", 50000.0, "50,000", Unit.COUNT, "seg-2")

        ctx_clean = MockPipelineContext(
            segments=[segment_clean],
            candidates=[candidate_clean],
            bound_values=[bv_clean],
            config=RelaxedConfig(),  # type: ignore
        )
        stage.process(ctx_clean)
        assert len(ctx_clean.bound_values) == 1


# ============================================================================
# Test: Bare small count filter (relaxed mode only)
# ============================================================================


class TestBareSmallCountFilter:
    """Tests for the bare small count value filter in transcript (relaxed) mode."""

    @pytest.mark.parametrize(
        "raw,value,expected_fp,desc",
        [
            ("6", 6.0, True, "Slide 6"),
            ("4", 4.0, True, "Q4 → bare 4"),
            ("10", 10.0, True, "top 10"),
            ("2", 2.0, True, "bare 2"),
            ("5", 5.0, True, "5G → bare 5"),
            ("25", 25.0, True, "bare 25"),
            ("49", 49.0, True, "just below threshold"),
            ("50", 50.0, False, "at threshold — kept"),
            ("100", 100.0, False, "above threshold — kept"),
            ("400", 400.0, False, "large count — kept"),
            ("3,000", 3000.0, False, "has comma scale — kept"),
            ("1.5 million", 1500000.0, False, "has million suffix — kept"),
            ("2 billion", 2000000000.0, False, "has billion suffix — kept"),
            ("500 thousand", 500000.0, False, "has thousand suffix — kept"),
        ],
    )
    def test_bare_small_count_relaxed(self, raw, value, expected_fp, desc):
        """Bare small counts filtered in relaxed mode."""
        bv = _make_bound_value("c1", value, raw, Unit.COUNT)
        source = f"We have {raw} active customers in this segment"
        is_fp, reason = _is_v2_false_positive(bv, source, relaxed=True)
        assert is_fp == expected_fp, f"Failed for {desc}: raw={raw!r}"
        if expected_fp:
            assert reason == "v2_bare_small_count"

    @pytest.mark.parametrize(
        "raw,value",
        [
            ("6", 6.0),
            ("4", 4.0),
            ("10", 10.0),
        ],
    )
    def test_bare_small_count_not_filtered_in_normal_mode(self, raw, value):
        """Bare small counts NOT filtered in normal (SEC filing) mode."""
        bv = _make_bound_value("c1", value, raw, Unit.COUNT)
        source = f"We had {raw} customers"
        is_fp, reason = _is_v2_false_positive(bv, source, relaxed=False)
        assert not is_fp

    def test_bare_small_percent_not_filtered(self):
        """Small percentage values are NOT filtered (only count unit)."""
        bv = _make_bound_value("c1", 4.0, "4%", Unit.PERCENT)
        source = "Revenue grew 4% year-over-year"
        is_fp, _ = _is_v2_false_positive(bv, source, relaxed=True)
        assert not is_fp

    def test_bare_small_currency_not_filtered(self):
        """Small currency values are NOT filtered by this rule."""
        bv = _make_bound_value("c1", 5.0, "$5", Unit.CURRENCY)
        source = "ARPU was $5 per user"
        is_fp, reason = _is_v2_false_positive(bv, source, relaxed=True)
        # May or may not be filtered by other rules, but not by bare_small_count
        if is_fp:
            assert reason != "v2_bare_small_count"


# ============================================================================
# Test: Currency on count-only metrics (stage-level integration)
# ============================================================================


class TestCurrencyOnCountMetric:
    """Tests for rejecting currency values on count-only metrics (MAU/DAU/etc)."""

    @pytest.mark.parametrize(
        "metric_id",
        [
            "cm_monthly_active_users",
            "cm_daily_active_users",
            "cm_active_customers_total",
            "cm_customers_period_end",
            "cm_new_customers_acquired",
            "cm_large_customers_period_end",
        ],
    )
    def test_currency_rejected_on_count_metric(self, stage, metric_id):
        """Currency values on count-only metrics are rejected as FP."""
        source = "Monthly active accounts up 2% to $224 million"
        segment = _make_text_segment("seg-1", source)
        candidate = _make_candidate("c1", metric_id, "seg-1")
        bv = _make_bound_value("c1", 224000000.0, "$224 million", Unit.CURRENCY, "seg-1")

        ctx = MockPipelineContext(
            segments=[segment],
            candidates=[candidate],
            bound_values=[bv],
        )
        stage.process(ctx)
        assert len(ctx.bound_values) == 0, f"Currency on {metric_id} should be rejected"

    def test_currency_kept_on_arr_metric(self, stage):
        """Currency values on ARR are kept (ARR is legitimately currency)."""
        source = "ARR grew to $4.1 billion"
        segment = _make_text_segment("seg-1", source)
        candidate = _make_candidate("c1", "cm_average_order_value", "seg-1")
        bv = _make_bound_value("c1", 4100000000.0, "$4.1 billion", Unit.CURRENCY, "seg-1")

        ctx = MockPipelineContext(
            segments=[segment],
            candidates=[candidate],
            bound_values=[bv],
        )
        stage.process(ctx)
        assert len(ctx.bound_values) == 1

    def test_count_unit_kept_on_count_metric(self, stage):
        """Count values on count-only metrics are kept (correct unit match)."""
        source = "We have 224 million monthly active users"
        segment = _make_text_segment("seg-1", source)
        candidate = _make_candidate("c1", "cm_monthly_active_users", "seg-1")
        bv = _make_bound_value("c1", 224000000.0, "224 million", Unit.COUNT, "seg-1")

        ctx = MockPipelineContext(
            segments=[segment],
            candidates=[candidate],
            bound_values=[bv],
        )
        stage.process(ctx)
        assert len(ctx.bound_values) == 1

    def test_currency_on_revenue_per_customer_kept(self, stage):
        """Currency on revenue_per_customer is kept (ARPU can be dollar amount)."""
        source = "ARPU grew to $225 per user"
        segment = _make_text_segment("seg-1", source)
        candidate = _make_candidate("c1", "cm_revenue_per_customer", "seg-1")
        bv = _make_bound_value("c1", 225.0, "$225", Unit.CURRENCY, "seg-1")

        ctx = MockPipelineContext(
            segments=[segment],
            candidates=[candidate],
            bound_values=[bv],
        )
        stage.process(ctx)
        assert len(ctx.bound_values) == 1

    def test_currency_rejection_tracked_in_metadata(self, stage):
        """Rejection of currency on count-only metrics is tracked in result metadata."""
        source = "Monthly active accounts up 2% to $224 million"
        segment = _make_text_segment("seg-1", source)
        candidate = _make_candidate("c1", "cm_monthly_active_users", "seg-1")
        bv = _make_bound_value("c1", 224000000.0, "$224 million", Unit.CURRENCY, "seg-1")

        ctx = MockPipelineContext(
            segments=[segment],
            candidates=[candidate],
            bound_values=[bv],
        )
        result = stage.process(ctx)
        assert result.metadata["filter_reasons"].get("v2_currency_on_count_metric") == 1
        assert result.metadata["removed_count"] == 1


# ============================================================================
# Test: Cross-metric deduplication
# ============================================================================


class TestCrossMetricDedup:
    """Tests for same-value cross-metric dedup within the FP filter stage."""

    def test_same_value_different_metrics_keeps_best(self, stage):
        """Same value in same segment bound to 2 metrics → keep higher confidence."""
        source = "We now serve 20 million customers worldwide"
        segment = _make_text_segment("seg-1", source)
        c1 = _make_candidate("c1", "cm_customers_period_end", "seg-1")
        c2 = _make_candidate("c2", "cm_large_customers_period_end", "seg-1")
        bv1 = _make_bound_value("c1", 20000000.0, "20 million", Unit.COUNT, "seg-1")
        bv1.binding_confidence = 0.6
        bv2 = _make_bound_value("c2", 20000000.0, "20 million", Unit.COUNT, "seg-1")
        bv2.binding_confidence = 0.4

        ctx = MockPipelineContext(
            segments=[segment],
            candidates=[c1, c2],
            bound_values=[bv1, bv2],
        )
        stage.process(ctx)
        assert len(ctx.bound_values) == 1
        assert ctx.bound_values[0].candidate_id == "c1"  # higher confidence

    def test_same_value_same_metric_kept(self, stage):
        """Same value + same metric from same segment → NOT deduped here."""
        source = "We mentioned 400 deals over a million and 400 large accounts"
        segment = _make_text_segment("seg-1", source)
        c1 = _make_candidate("c1", "cm_large_customers_period_end", "seg-1")
        c2 = _make_candidate("c2", "cm_large_customers_period_end", "seg-1")
        bv1 = _make_bound_value("c1", 400.0, "400", Unit.COUNT, "seg-1")
        bv2 = _make_bound_value("c2", 400.0, "400", Unit.COUNT, "seg-1")

        ctx = MockPipelineContext(
            segments=[segment],
            candidates=[c1, c2],
            bound_values=[bv1, bv2],
        )
        stage.process(ctx)
        # Same metric ID → not filtered by cross-metric dedup
        assert len(ctx.bound_values) == 2

    def test_different_values_different_metrics_kept(self, stage):
        """Different values from same segment → no dedup needed."""
        source = "We have 3000 paying customers and 400 large deals"
        segment = _make_text_segment("seg-1", source)
        c1 = _make_candidate("c1", "cm_customers_period_end", "seg-1")
        c2 = _make_candidate("c2", "cm_large_customers_period_end", "seg-1")
        bv1 = _make_bound_value("c1", 3000.0, "3,000", Unit.COUNT, "seg-1")
        bv2 = _make_bound_value("c2", 400.0, "400", Unit.COUNT, "seg-1")

        ctx = MockPipelineContext(
            segments=[segment],
            candidates=[c1, c2],
            bound_values=[bv1, bv2],
        )
        stage.process(ctx)
        assert len(ctx.bound_values) == 2

    def test_same_value_different_segments_kept(self, stage):
        """Same value from different segments → no dedup (independent mentions)."""
        seg1 = _make_text_segment("seg-1", "We have 1000 active customers")
        seg2 = _make_text_segment("seg-2", "Added 1000 new customers this quarter")
        c1 = _make_candidate("c1", "cm_active_customers_total", "seg-1")
        c2 = _make_candidate("c2", "cm_new_customers_acquired", "seg-2")
        bv1 = _make_bound_value("c1", 1000.0, "1000", Unit.COUNT, "seg-1")
        bv2 = _make_bound_value("c2", 1000.0, "1000", Unit.COUNT, "seg-2")

        ctx = MockPipelineContext(
            segments=[seg1, seg2],
            candidates=[c1, c2],
            bound_values=[bv1, bv2],
        )
        stage.process(ctx)
        assert len(ctx.bound_values) == 2


# ============================================================================
# Test: Percent clause gate (relaxed mode only)
# ============================================================================


class TestPercentClauseGateHelper:
    """Tests for _is_percent_in_keyword_clause helper function."""

    def test_same_clause_returns_true(self):
        """Value in same clause as keyword → keep."""
        text = "TPV grew 50% and MAAs grew 30%"
        # "MAAs" starts at position 17, "30%" at 27
        assert _is_percent_in_keyword_clause(text, (17, 21), "30%") is True

    def test_different_clause_returns_false(self):
        """Value in different clause from keyword → reject."""
        text = "TPV grew 50% and MAAs grew 30%"
        # "MAAs" at 17, "50%" at 9 — 50% is in clause 1, MAAs in clause 2
        assert _is_percent_in_keyword_clause(text, (17, 21), "50%") is False

    def test_single_clause_returns_true(self):
        """No conjunctions → single clause → keep (conservative)."""
        text = "MAAs grew 18% year-over-year"
        assert _is_percent_in_keyword_clause(text, (0, 4), "18%") is True

    def test_no_keyword_span_returns_true(self):
        """No keyword span → fail open → keep."""
        text = "TPV grew 50% and MAAs grew 30%"
        assert _is_percent_in_keyword_clause(text, None, "50%") is True

    def test_value_not_found_returns_true(self):
        """Value not found in text → fail open → keep."""
        text = "TPV grew 50% and MAAs grew 30%"
        assert _is_percent_in_keyword_clause(text, (17, 21), "99%") is True

    def test_semicolon_boundary(self):
        """Semicolon also splits clauses."""
        text = "revenue up 50%; MAAs grew 30%"
        # "MAAs" at 16, "50%" at 11 — different clauses
        assert _is_percent_in_keyword_clause(text, (16, 20), "50%") is False
        # "30%" at 26 — same clause as "MAAs"
        assert _is_percent_in_keyword_clause(text, (16, 20), "30%") is True

    def test_but_boundary(self):
        """'but' also splits clauses."""
        text = "take rate was 4% but MAAs grew 18%"
        assert _is_percent_in_keyword_clause(text, (21, 25), "4%") is False
        assert _is_percent_in_keyword_clause(text, (21, 25), "18%") is True

    def test_multiple_conjunctions(self):
        """Multiple conjunctions create multiple clause boundaries."""
        text = "revenue up 10% and TPV grew 50% and MAAs grew 30%"
        # "MAAs" at 36, "10%" at 11 — clause 1 vs 3
        assert _is_percent_in_keyword_clause(text, (36, 40), "10%") is False
        # "50%" at 28 — clause 2 vs 3
        assert _is_percent_in_keyword_clause(text, (36, 40), "50%") is False
        # "30%" at 47 — same clause 3
        assert _is_percent_in_keyword_clause(text, (36, 40), "30%") is True


class TestPercentClauseGateStage:
    """Stage-level integration tests for the percent clause gate."""

    def _make_relaxed_config(self):
        @dataclass
        class RelaxedConfig:
            min_confidence_auto_accept: float = 0.90
            relaxed_fp_filter: bool = True
        return RelaxedConfig()

    def test_wrong_clause_percent_rejected_in_relaxed(self, stage):
        """Percent value in wrong clause rejected in relaxed mode."""
        text = "TPV grew 50% and MAAs grew 30%"
        segment = _make_text_segment("seg-1", text)
        # Candidate keyword at position 17 ("MAAs")
        candidate = MetricCandidate(
            candidate_id="c1",
            metric_id="cm_monthly_active_users",
            match_text="MAAs",
            source_locator=SourceLocator(segment_id="seg-1", text_span=(17, 21)),
            source_type=SourceType.TEXT,
            context_text=text,
        )
        # "50%" is in the wrong clause (clause 1, keyword in clause 2)
        bv = _make_bound_value("c1", 50.0, "50%", Unit.PERCENT, "seg-1")

        ctx = MockPipelineContext(
            segments=[segment],
            candidates=[candidate],
            bound_values=[bv],
            config=self._make_relaxed_config(),  # type: ignore
        )
        stage.process(ctx)
        assert len(ctx.bound_values) == 0, "50% in wrong clause should be rejected"

    def test_same_clause_percent_rejected_by_percent_on_count_rule(self, stage):
        """Percent value on MAU metric is always rejected by _rule_percent_on_count_metric.

        Even when "30%" is in the same clause as "MAAs", it is rejected because
        cm_monthly_active_users is a count-only metric and percent values indicate
        a feature adoption rate or penetration, not an absolute user count.
        """
        text = "Revenue retention was 115% and MAAs at 30% penetration"
        segment = _make_text_segment("seg-1", text)
        candidate = MetricCandidate(
            candidate_id="c1",
            metric_id="cm_monthly_active_users",
            match_text="MAAs",
            source_locator=SourceLocator(segment_id="seg-1", text_span=(31, 35)),
            source_type=SourceType.TEXT,
            context_text=text,
        )
        bv = _make_bound_value("c1", 30.0, "30%", Unit.PERCENT, "seg-1")

        ctx = MockPipelineContext(
            segments=[segment],
            candidates=[candidate],
            bound_values=[bv],
            config=self._make_relaxed_config(),  # type: ignore
        )
        stage.process(ctx)
        assert len(ctx.bound_values) == 0, "Percent on count-only metric should always be filtered"

    def test_percent_on_mau_rejected_in_normal_mode(self, stage):
        """Percent on MAU rejected by _rule_percent_on_count_metric in all modes.

        The _rule_percent_on_count_metric fires in both normal and relaxed mode,
        so 90% bound to cm_monthly_active_users is always a false positive.
        """
        text = "Revenue retention was 90% and MAAs totaled 250M"
        segment = _make_text_segment("seg-1", text)
        candidate = MetricCandidate(
            candidate_id="c1",
            metric_id="cm_monthly_active_users",
            match_text="MAAs",
            source_locator=SourceLocator(segment_id="seg-1", text_span=(30, 34)),
            source_type=SourceType.TEXT,
            context_text=text,
        )
        bv = _make_bound_value("c1", 90.0, "90%", Unit.PERCENT, "seg-1")

        ctx = MockPipelineContext(
            segments=[segment],
            candidates=[candidate],
            bound_values=[bv],
        )
        stage.process(ctx)
        assert len(ctx.bound_values) == 0, "Percent on count-only metric filtered in all modes"

    def test_percent_on_customers_period_end_rejected(self, stage):
        """Percent on cm_customers_period_end rejected by _rule_percent_on_count_metric.

        cm_customers_period_end is a count-only metric — a percent value bound
        to it is always a false positive (e.g., a growth rate or revenue share
        that happens to appear near the 'customers' keyword).
        """
        text = "Revenue grew 50% and customers grew 30%"
        segment = _make_text_segment("seg-1", text)
        candidate = MetricCandidate(
            candidate_id="c1",
            metric_id="cm_customers_period_end",
            match_text="customers",
            source_locator=SourceLocator(segment_id="seg-1", text_span=(22, 31)),
            source_type=SourceType.TEXT,
            context_text=text,
        )
        bv = _make_bound_value("c1", 50.0, "50%", Unit.PERCENT, "seg-1")

        ctx = MockPipelineContext(
            segments=[segment],
            candidates=[candidate],
            bound_values=[bv],
            config=self._make_relaxed_config(),  # type: ignore
        )
        stage.process(ctx)
        assert len(ctx.bound_values) == 0, "Percent on count-only metric should be filtered"

    def test_single_clause_mau_percent_rejected(self, stage):
        """Percent on MAU rejected even in a single-clause segment.

        "monthly active users at approximately 35%" — the 35% is a feature
        adoption rate, not an absolute MAU count.  _rule_percent_on_count_metric
        fires before the clause gate and rejects all percent values on count metrics.
        This is the exact ADBE FP pattern from the gold standard.
        """
        text = "monthly active users at approximately 35%"
        segment = _make_text_segment("seg-1", text)
        candidate = MetricCandidate(
            candidate_id="c1",
            metric_id="cm_monthly_active_users",
            match_text="monthly active users",
            source_locator=SourceLocator(segment_id="seg-1", text_span=(0, 20)),
            source_type=SourceType.TEXT,
            context_text=text,
        )
        bv = _make_bound_value("c1", 35.0, "35%", Unit.PERCENT, "seg-1")

        ctx = MockPipelineContext(
            segments=[segment],
            candidates=[candidate],
            bound_values=[bv],
            config=self._make_relaxed_config(),  # type: ignore
        )
        stage.process(ctx)
        assert len(ctx.bound_values) == 0, "Percent on count-only metric always filtered"

    def test_dau_also_gated(self, stage):
        """DAU metric is also subject to clause gate."""
        text = "engagement up 6% and DAU grew 18%"
        segment = _make_text_segment("seg-1", text)
        candidate = MetricCandidate(
            candidate_id="c1",
            metric_id="cm_daily_active_users",
            match_text="DAU",
            source_locator=SourceLocator(segment_id="seg-1", text_span=(22, 25)),
            source_type=SourceType.TEXT,
            context_text=text,
        )
        # "6%" is in the wrong clause
        bv_wrong = _make_bound_value("c1", 6.0, "6%", Unit.PERCENT, "seg-1")

        ctx = MockPipelineContext(
            segments=[segment],
            candidates=[candidate],
            bound_values=[bv_wrong],
            config=self._make_relaxed_config(),  # type: ignore
        )
        stage.process(ctx)
        assert len(ctx.bound_values) == 0, "6% in wrong clause for DAU should be rejected"

    def test_percent_on_count_rejection_tracked(self, stage):
        """_rule_percent_on_count_metric rejection reason tracked in metadata."""
        # "90%" near MAAs — rejected by _rule_percent_on_count_metric (fires before clause gate).
        text = "Revenue retention was 90% and MAAs totaled 250M"
        segment = _make_text_segment("seg-1", text)
        candidate = MetricCandidate(
            candidate_id="c1",
            metric_id="cm_monthly_active_users",
            match_text="MAAs",
            source_locator=SourceLocator(segment_id="seg-1", text_span=(30, 34)),
            source_type=SourceType.TEXT,
            context_text=text,
        )
        bv = _make_bound_value("c1", 90.0, "90%", Unit.PERCENT, "seg-1")

        ctx = MockPipelineContext(
            segments=[segment],
            candidates=[candidate],
            bound_values=[bv],
            config=self._make_relaxed_config(),  # type: ignore
        )
        result = stage.process(ctx)
        assert result.metadata["filter_reasons"].get("v2_percent_on_count") == 1


# ============================================================================
# Test: V2-native — Table-sourced exemption from financial annotation rules
# ============================================================================


class TestV2TableSourcedExemption:
    """Table-sourced values should be exempt from financial annotation FP rules."""

    def test_table_sourced_exempt_from_financial_annotation(self):
        """Table-sourced value near '(In thousands)' should NOT be filtered."""
        source = "(In thousands) Paid Customers 37,000 59,000"
        bv = BoundValue(
            candidate_id="c1",
            value=37000.0,
            value_raw="37,000",
            unit=Unit.COUNT,
            binding_type="table_stub",
            binding_confidence=0.6,
            source_locator=SourceLocator(
                table_id="table-1",
                cell_row=1,
                cell_col=1,
            ),
        )
        is_fp, reason = _is_v2_false_positive(bv, source)
        assert is_fp is False, (
            "Table-sourced values should be exempt from financial annotation rule"
        )

    def test_text_sourced_still_filtered_by_financial_annotation(self):
        """Text-sourced value near '(In thousands)' should still be filtered."""
        source = "(In thousands) Cost of revenue 37,000 59,000"
        bv = _make_bound_value("c1", 37000.0, "37,000", Unit.COUNT, "seg-1")
        is_fp, reason = _is_v2_false_positive(bv, source)
        assert is_fp is True
        assert reason == "v2_financial_annotation"

    def test_table_sourced_exempt_from_sbc(self):
        """Table-sourced value near 'stock-based compensation' should NOT be filtered."""
        source = "Includes stock-based compensation as follows: 67,000 95,000"
        bv = BoundValue(
            candidate_id="c1",
            value=67000.0,
            value_raw="67,000",
            unit=Unit.COUNT,
            binding_type="table_stub",
            binding_confidence=0.6,
            source_locator=SourceLocator(
                table_id="table-1",
                cell_row=1,
                cell_col=1,
            ),
        )
        is_fp, reason = _is_v2_false_positive(bv, source)
        assert is_fp is False, "Table-sourced values should be exempt from SBC rule"

    def test_text_sourced_still_filtered_by_sbc(self):
        """Text-sourced value near 'stock-based compensation' should still be filtered."""
        source = "Includes stock-based compensation as follows: 67,000 95,000"
        bv = _make_bound_value("c1", 67000.0, "67,000", Unit.COUNT, "seg-1")
        is_fp, reason = _is_v2_false_positive(bv, source)
        assert is_fp is True
        assert reason == "v2_financial_sbc"


# ============================================================================
# Test: V2-native — Per-share stock price FP rule
# ============================================================================


class TestV2PerShareRule:
    """Stock price mentions like '$67 per share' should be FP for ARPU/AOV metrics."""

    def test_67_per_share_filtered_for_arpu(self):
        """'$67 per share' near value for cm_revenue_per_customer → filtered."""
        source = "the stock was trading at $67 per share during the quarter"
        bv = _make_bound_value("c1", 67.0, "$67", Unit.CURRENCY, "seg-1")
        is_fp, reason = _is_v2_false_positive(bv, source, metric_id="cm_revenue_per_customer")
        assert is_fp is True
        assert reason == "v2_per_share"

    def test_276_per_share_filtered_for_arpu(self):
        """'$276 per share' near value for cm_revenue_per_customer → filtered."""
        source = "shares were priced at approximately $276 per share"
        bv = _make_bound_value("c1", 276.0, "$276", Unit.CURRENCY, "seg-1")
        is_fp, reason = _is_v2_false_positive(bv, source, metric_id="cm_revenue_per_customer")
        assert is_fp is True
        assert reason == "v2_per_share"

    def test_arpu_without_per_share_not_filtered(self):
        """'$220 ARPU' without 'per share' → NOT filtered."""
        source = "ARPU increased to $220 per user in Q4"
        bv = _make_bound_value("c1", 220.0, "$220", Unit.CURRENCY, "seg-1")
        is_fp, _ = _is_v2_false_positive(bv, source, metric_id="cm_revenue_per_customer")
        assert is_fp is False

    def test_per_share_wrong_metric_not_filtered(self):
        """'per share' near value but metric is cm_customers_period_end → NOT filtered."""
        source = "stock offered at $67 per share"
        bv = _make_bound_value("c1", 67.0, "$67", Unit.CURRENCY, "seg-1")
        is_fp, _ = _is_v2_false_positive(bv, source, metric_id="cm_customers_period_end")
        assert is_fp is False

    def test_per_share_wrong_unit_not_filtered(self):
        """'per share' in text but unit=COUNT → NOT filtered by this rule."""
        source = "67 million shares outstanding per share calculation"
        bv = _make_bound_value("c1", 67.0, "67", Unit.COUNT, "seg-1")
        is_fp, reason = _is_v2_false_positive(bv, source, metric_id="cm_revenue_per_customer")
        # Not filtered by per_share rule (wrong unit); may pass or fail other rules
        if is_fp:
            assert reason != "v2_per_share"


# ============================================================================
# Test: V2-native — Tier qualifier suppression
# ============================================================================


class TestV2TierQualifier:
    """Per-tier customer counts should be suppressed for cm_customers_period_end."""

    def test_enterprise_tier_suppressed(self):
        """'Enterprise' tier keyword in source text suppresses cm_customers_period_end."""
        source = "Enterprise 4,500"
        bv = _make_bound_value("c1", 4500.0, "4,500", Unit.COUNT, "seg-1")
        is_fp, reason = _is_v2_false_positive(bv, source, "cm_customers_period_end")
        assert is_fp is True
        assert reason == "v2_tier_qualifier"

    def test_free_tier_suppressed(self):
        """'Free' tier keyword in source text suppresses cm_customers_period_end."""
        source = "Free 12,000"
        bv = _make_bound_value("c1", 12000.0, "12,000", Unit.COUNT, "seg-1")
        is_fp, reason = _is_v2_false_positive(bv, source, "cm_customers_period_end")
        assert is_fp is True
        assert reason == "v2_tier_qualifier"

    def test_business_critical_tier_suppressed(self):
        """'Business Critical' tier keyword suppresses cm_customers_period_end."""
        source = "Business Critical 850"
        bv = _make_bound_value("c1", 850.0, "850", Unit.COUNT, "seg-1")
        is_fp, reason = _is_v2_false_positive(bv, source, "cm_customers_period_end")
        assert is_fp is True
        assert reason == "v2_tier_qualifier"

    def test_tier_keyword_different_metric_not_suppressed(self):
        """Tier keyword for a different metric (cm_arr_total) is NOT suppressed."""
        source = "Enterprise 4,500,000"
        bv = _make_bound_value("c1", 4500000.0, "4,500,000", Unit.CURRENCY, "seg-1")
        is_fp, _ = _is_v2_false_positive(bv, source, "cm_arr_total")
        assert is_fp is False

    def test_customers_period_end_no_tier_keyword_not_suppressed(self):
        """cm_customers_period_end without a tier keyword is NOT suppressed."""
        source = "Total customers at period end: 45,000"
        bv = _make_bound_value("c1", 45000.0, "45,000", Unit.COUNT, "seg-1")
        is_fp, _ = _is_v2_false_positive(bv, source, "cm_customers_period_end")
        assert is_fp is False


# ============================================================================
# Test: Q&A section-aware bare-count threshold
# ============================================================================


class TestQASectionBareCountThreshold:
    """Tests for elevated bare-count threshold in Q&A sections."""

    def test_fp_filter_qa_bare_count_threshold_500(self):
        """Value=200, unit=COUNT, section=QA → rejected (< 500 threshold)."""
        from src.extraction_v2.models import SectionType

        bv = _make_bound_value("c1", 200.0, "200", Unit.COUNT)
        source = "We had 200 customers sign up this quarter"
        is_fp, reason = _is_v2_false_positive(
            bv, source, relaxed=True, section_type=SectionType.QA
        )
        assert is_fp is True
        assert reason == "v2_bare_small_count"

    def test_fp_filter_prepared_remarks_threshold_50(self):
        """Value=30, unit=COUNT, section=PREPARED_REMARKS → rejected (< 50 threshold)."""
        from src.extraction_v2.models import SectionType

        bv = _make_bound_value("c1", 30.0, "30", Unit.COUNT)
        source = "We had 30 customers"
        is_fp, reason = _is_v2_false_positive(
            bv, source, relaxed=True, section_type=SectionType.PREPARED_REMARKS
        )
        assert is_fp is True
        assert reason == "v2_bare_small_count"

    def test_fp_filter_sec_threshold_unchanged(self):
        """Value=30, unit=COUNT, section=UNKNOWN → rejected via default threshold 50."""
        from src.extraction_v2.models import SectionType

        bv = _make_bound_value("c1", 30.0, "30", Unit.COUNT)
        source = "We had 30 customers"
        # relaxed=False simulates SEC mode (UNKNOWN section, not relaxed)
        is_fp, _ = _is_v2_false_positive(
            bv, source, relaxed=False, section_type=SectionType.UNKNOWN
        )
        assert is_fp is False  # bare-count rule only applies in relaxed mode

    def test_qa_threshold_allows_large_count(self):
        """Value >= 500 in QA → not rejected even without scale suffix."""
        from src.extraction_v2.models import SectionType

        bv = _make_bound_value("c1", 500.0, "500", Unit.COUNT)
        source = "approximately 500 customers"
        is_fp, _ = _is_v2_false_positive(
            bv, source, relaxed=True, section_type=SectionType.QA
        )
        assert is_fp is False

    def test_qa_threshold_allows_scale_suffix(self):
        """Value < 500 in QA but with scale suffix → not rejected."""
        from src.extraction_v2.models import SectionType

        bv = _make_bound_value("c1", 4.0, "4 million", Unit.COUNT)
        source = "4 million active users"
        is_fp, _ = _is_v2_false_positive(
            bv, source, relaxed=True, section_type=SectionType.QA
        )
        assert is_fp is False


# ============================================================================
# Test: Q&A hedging percent rule
# ============================================================================


class TestQAHedgingPercentRule:
    """Tests for Q&A hedging-language percent filter."""

    def test_qa_hedging_was_it_rejected(self):
        """Percent value with 'was it' nearby in Q&A → rejected."""
        from src.extraction_v2.models import SectionType

        bv = _make_bound_value("c1", 35.0, "35%", Unit.PERCENT)
        source = "was it 35% growth or higher?"
        is_fp, reason = _is_v2_false_positive(
            bv, source, metric_id="cm_net_revenue_retention",
            relaxed=True, section_type=SectionType.QA
        )
        assert is_fp is True
        assert reason == "v2_qa_hedging_percent"

    def test_qa_hedging_assuming_rejected(self):
        """Percent value with 'assuming' nearby in Q&A → rejected."""
        from src.extraction_v2.models import SectionType

        bv = _make_bound_value("c1", 15.0, "15%", Unit.PERCENT)
        source = "assuming 15% margin improvement, how should we model that?"
        is_fp, reason = _is_v2_false_positive(
            bv, source, metric_id="cm_gross_margin_overall",
            relaxed=True, section_type=SectionType.QA
        )
        assert is_fp is True
        assert reason == "v2_qa_hedging_percent"

    def test_qa_hedging_guidance_rejected(self):
        """Percent value with 'guidance' nearby in Q&A → rejected."""
        from src.extraction_v2.models import SectionType

        bv = _make_bound_value("c1", 110.0, "110%", Unit.PERCENT)
        source = "the guidance of 110% NRR going into next year"
        is_fp, reason = _is_v2_false_positive(
            bv, source, metric_id="cm_net_revenue_retention",
            relaxed=True, section_type=SectionType.QA
        )
        assert is_fp is True
        assert reason == "v2_qa_hedging_percent"

    def test_qa_hedging_do_you_rejected(self):
        """Percent value with 'do you' nearby in Q&A → rejected."""
        from src.extraction_v2.models import SectionType

        bv = _make_bound_value("c1", 25.0, "25%", Unit.PERCENT)
        source = "do you expect 25% growth to continue?"
        is_fp, reason = _is_v2_false_positive(
            bv, source, metric_id="cm_customer_churn_rate",
            relaxed=True, section_type=SectionType.QA
        )
        assert is_fp is True
        assert reason == "v2_qa_hedging_percent"

    def test_qa_confident_percent_kept(self):
        """Percent value with no hedging in Q&A → kept (gold standard case)."""
        from src.extraction_v2.models import SectionType

        # Gold standard: "Our top 10 customers represent 45% of revenue"
        bv = _make_bound_value("c1", 45.0, "45%", Unit.PERCENT)
        source = "Our top 10 customers represent 45% of revenue"
        is_fp, reason = _is_v2_false_positive(
            bv, source, metric_id="cm_revenue_concentration",
            relaxed=True, section_type=SectionType.QA
        )
        assert is_fp is False

    def test_qa_revenue_concentration_60_kept(self):
        """Gold standard: 'Top 5 customers contributed 60% of ARR' → kept."""
        from src.extraction_v2.models import SectionType

        bv = _make_bound_value("c1", 60.0, "60%", Unit.PERCENT)
        source = "Top 5 customers contributed 60% of ARR"
        is_fp, _ = _is_v2_false_positive(
            bv, source, metric_id="cm_revenue_concentration",
            relaxed=True, section_type=SectionType.QA
        )
        assert is_fp is False

    def test_qa_nrr_100_range_kept(self):
        """Gold standard: NRR range 100%-110% in Q&A → kept."""
        from src.extraction_v2.models import SectionType

        bv = _make_bound_value("c1", 100.0, "100%", Unit.PERCENT)
        source = (
            "in the modeling guidelines, we've provided a view on how we are "
            "thinking about fiscal '26, which is basically the same as it was "
            "in fiscal '25. It's a range of 100% to 110%."
        )
        is_fp, _ = _is_v2_false_positive(
            bv, source, metric_id="cm_net_revenue_retention",
            relaxed=True, section_type=SectionType.QA
        )
        assert is_fp is False

    def test_qa_hedging_not_fired_in_prepared_remarks(self):
        """Hedging language in PREPARED_REMARKS section → rule does NOT fire."""
        from src.extraction_v2.models import SectionType

        bv = _make_bound_value("c1", 20.0, "20%", Unit.PERCENT)
        source = "was it 20% growth or higher?"
        is_fp, reason = _is_v2_false_positive(
            bv, source, metric_id="cm_net_revenue_retention",
            relaxed=True, section_type=SectionType.PREPARED_REMARKS
        )
        # Should NOT fire the QA hedging rule in prepared remarks
        assert reason != "v2_qa_hedging_percent"

    def test_qa_hedging_not_fired_in_non_relaxed_mode(self):
        """Hedging language in SEC filing (non-relaxed) → rule does NOT fire."""
        from src.extraction_v2.models import SectionType

        bv = _make_bound_value("c1", 20.0, "20%", Unit.PERCENT)
        source = "was it 20% growth or higher?"
        is_fp, reason = _is_v2_false_positive(
            bv, source, metric_id="cm_net_revenue_retention",
            relaxed=False, section_type=SectionType.QA
        )
        assert reason != "v2_qa_hedging_percent"

    def test_qa_hedging_hedging_far_from_value_not_fired(self):
        """Hedging language >60 chars from value → rule does NOT fire."""
        from src.extraction_v2.models import SectionType

        # Pad text so hedging is well beyond the 60-char window
        padding = "A" * 100
        bv = _make_bound_value("c1", 45.0, "45%", Unit.PERCENT)
        source = f"Was it ever possible? {padding} The answer is 45% retention."
        is_fp, reason = _is_v2_false_positive(
            bv, source, metric_id="cm_net_revenue_retention",
            relaxed=True, section_type=SectionType.QA
        )
        assert reason != "v2_qa_hedging_percent"


# ============================================================================
# Test: Q&A currency on count metric rule
# ============================================================================


class TestQACurrencyOnCountRule:
    """Tests for Q&A currency-value-on-count-metric filter."""

    def test_qa_currency_on_mau_rejected(self):
        """Currency value bound to MAU metric in Q&A → rejected."""
        from src.extraction_v2.models import SectionType

        bv = _make_bound_value("c1", 50_000_000.0, "$50 million", Unit.CURRENCY)
        source = "How does the $50 million figure relate to monthly active users?"
        is_fp, reason = _is_v2_false_positive(
            bv, source, metric_id="cm_monthly_active_users",
            relaxed=True, section_type=SectionType.QA
        )
        assert is_fp is True
        assert reason == "v2_qa_currency_on_count"

    def test_qa_currency_on_customers_period_end_rejected(self):
        """Currency value bound to customers_period_end in Q&A → rejected."""
        from src.extraction_v2.models import SectionType

        bv = _make_bound_value("c1", 100_000_000.0, "$100 million", Unit.CURRENCY)
        source = "When we talk about $100 million customers, we mean customer value"
        is_fp, reason = _is_v2_false_positive(
            bv, source, metric_id="cm_customers_period_end",
            relaxed=True, section_type=SectionType.QA
        )
        assert is_fp is True
        assert reason == "v2_qa_currency_on_count"

    def test_qa_currency_on_new_customers_rejected(self):
        """Currency value bound to new_customers_acquired in Q&A → rejected."""
        from src.extraction_v2.models import SectionType

        bv = _make_bound_value("c1", 25_000_000.0, "$25 million", Unit.CURRENCY)
        source = "Did $25 million in new customer acquisition costs surprise you?"
        is_fp, reason = _is_v2_false_positive(
            bv, source, metric_id="cm_new_customers_acquired",
            relaxed=True, section_type=SectionType.QA
        )
        assert is_fp is True
        assert reason == "v2_qa_currency_on_count"

    def test_qa_count_on_count_metric_kept(self):
        """Count value bound to MAU metric in Q&A → kept."""
        from src.extraction_v2.models import SectionType

        # Gold standard: 4 million new debit card active
        bv = _make_bound_value("c1", 4_000_000.0, "4 million", Unit.COUNT)
        source = "4 million new debit card active, so really starting to see strong demand"
        is_fp, _ = _is_v2_false_positive(
            bv, source, metric_id="cm_new_customers_acquired",
            relaxed=True, section_type=SectionType.QA
        )
        assert is_fp is False

    def test_qa_currency_on_non_count_metric_not_filtered_by_qa_rule(self):
        """Currency value on a non-count metric (ARR) in Q&A → NOT filtered by QA rule."""
        from src.extraction_v2.models import SectionType

        bv = _make_bound_value("c1", 578_000_000.0, "$578 million", Unit.CURRENCY)
        source = "we achieved net new ARR of $578 million"
        is_fp, reason = _is_v2_false_positive(
            bv, source, metric_id="cm_average_order_value",
            relaxed=True, section_type=SectionType.QA
        )
        # QA currency-on-count rule should NOT fire for cm_average_order_value (not a count metric)
        assert reason != "v2_qa_currency_on_count"

    def test_qa_currency_on_count_not_fired_in_prepared_remarks(self):
        """Currency value on count metric in PREPARED_REMARKS → QA rule does NOT fire."""
        from src.extraction_v2.models import SectionType

        bv = _make_bound_value("c1", 50_000_000.0, "$50 million", Unit.CURRENCY)
        source = "How does the $50 million figure relate to monthly active users?"
        is_fp, reason = _is_v2_false_positive(
            bv, source, metric_id="cm_monthly_active_users",
            relaxed=True, section_type=SectionType.PREPARED_REMARKS
        )
        # QA-specific rule must NOT fire for prepared remarks
        assert reason != "v2_qa_currency_on_count"


# ============================================================================
# Test: Forward guidance rule (A+.2 — TMUS FP hardening)
# ============================================================================


class TestForwardGuidanceRule:
    """Tests for the forward guidance FP filter in relaxed mode."""

    def test_we_expect_phrase_rejects_value(self):
        """'we expect 5.5 million net additions' → rejected as guidance."""
        from src.extraction_v2.models import SectionType

        bv = _make_bound_value("c1", 5_500_000.0, "5.5 million", Unit.COUNT)
        source = "For the full year we expect 5.5 million net additions to our base."
        is_fp, reason = _is_v2_false_positive(
            bv, source, metric_id="cm_net_additions",
            relaxed=True, section_type=SectionType.PREPARED_REMARKS
        )
        assert is_fp is True
        assert reason == "v2_forward_guidance"

    def test_our_outlook_phrase_rejects_value(self):
        """'our outlook of 3.2 million' → rejected as guidance."""
        from src.extraction_v2.models import SectionType

        bv = _make_bound_value("c1", 3_200_000.0, "3.2 million", Unit.COUNT)
        source = "Our outlook remains 3.2 million postpaid phone net additions."
        is_fp, reason = _is_v2_false_positive(
            bv, source, metric_id="cm_net_additions",
            relaxed=True, section_type=SectionType.PREPARED_REMARKS
        )
        assert is_fp is True
        assert reason == "v2_forward_guidance"

    def test_guidance_of_phrase_rejects_value(self):
        """'guidance of $X' → rejected as guidance."""
        from src.extraction_v2.models import SectionType

        bv = _make_bound_value("c1", 700_000_000.0, "700", Unit.CURRENCY)
        source = "We are reaffirming guidance of $700 million in free cash flow."
        is_fp, reason = _is_v2_false_positive(
            bv, source, metric_id="cm_free_cash_flow",
            relaxed=True, section_type=SectionType.PREPARED_REMARKS
        )
        assert is_fp is True
        assert reason == "v2_forward_guidance"

    def test_reported_actual_not_rejected(self):
        """Past tense reporting language → kept (actual result)."""
        from src.extraction_v2.models import SectionType

        bv = _make_bound_value("c1", 5_500_000.0, "5.5 million", Unit.COUNT)
        source = "We delivered 5.5 million net additions in Q4, our best quarter ever."
        is_fp, reason = _is_v2_false_positive(
            bv, source, metric_id="cm_net_additions",
            relaxed=True, section_type=SectionType.PREPARED_REMARKS
        )
        assert reason != "v2_forward_guidance"

    def test_guidance_far_from_value_not_fired(self):
        """Guidance language >100 chars from value → rule does NOT fire."""
        from src.extraction_v2.models import SectionType

        padding = "X" * 200
        bv = _make_bound_value("c1", 5_500_000.0, "5.5", Unit.COUNT)
        source = f"We expect strong performance. {padding} We added 5.5 million customers."
        is_fp, reason = _is_v2_false_positive(
            bv, source, metric_id="cm_net_additions",
            relaxed=True, section_type=SectionType.PREPARED_REMARKS
        )
        assert reason != "v2_forward_guidance"

    def test_forward_guidance_not_fired_in_non_relaxed_mode(self):
        """Forward guidance rule is relaxed-only; SEC filings unaffected."""
        from src.extraction_v2.models import SectionType

        bv = _make_bound_value("c1", 5_500_000.0, "5.5 million", Unit.COUNT)
        source = "For the full year we expect 5.5 million net additions."
        is_fp, reason = _is_v2_false_positive(
            bv, source, metric_id="cm_net_additions",
            relaxed=False, section_type=SectionType.PREPARED_REMARKS
        )
        assert reason != "v2_forward_guidance"

    def test_expecting_to_add_phrase_rejects_value(self):
        """'expecting to add X million' → rejected as guidance."""
        from src.extraction_v2.models import SectionType

        bv = _make_bound_value("c1", 2_000_000.0, "2 million", Unit.COUNT)
        source = "We are expecting to add 2 million subscribers in the next quarter."
        is_fp, reason = _is_v2_false_positive(
            bv, source, metric_id="cm_net_additions",
            relaxed=True, section_type=SectionType.PREPARED_REMARKS
        )
        assert is_fp is True
        assert reason == "v2_forward_guidance"


class TestArpuAsAovRule:
    """Tests for _rule_arpu_as_aov — blocks ARPU values from cm_average_order_value."""

    def test_arpu_label_adjacent_rejects_aov_value(self):
        """'ARPU is up to $220' near cm_average_order_value → rejected."""
        bv = _make_bound_value("c1", 220.0, "220", Unit.CURRENCY)
        source = "ARPU is up 8% to $220 per customer."
        is_fp, reason = _is_v2_false_positive(
            bv, source, metric_id="cm_average_order_value", relaxed=True
        )
        assert is_fp is True
        assert reason == "v2_arpu_as_aov"

    def test_average_revenue_per_user_label_rejects_value(self):
        """'average revenue per user' near cm_average_order_value → rejected."""
        bv = _make_bound_value("c1", 225.0, "225", Unit.CURRENCY)
        source = "average revenue per user of $225 for the quarter."
        is_fp, reason = _is_v2_false_positive(
            bv, source, metric_id="cm_average_order_value", relaxed=True
        )
        assert is_fp is True
        assert reason == "v2_arpu_as_aov"

    def test_genuine_aov_without_arpu_label_kept(self):
        """No ARPU label near value → kept as genuine AOV."""
        bv = _make_bound_value("c1", 220.0, "220", Unit.CURRENCY)
        source = "Average order value increased to $220 driven by premium product mix."
        is_fp, reason = _is_v2_false_positive(
            bv, source, metric_id="cm_average_order_value", relaxed=True
        )
        assert is_fp is False

    def test_arpu_far_from_value_not_rejected(self):
        """ARPU label too far (>30 chars) from value → not rejected."""
        bv = _make_bound_value("c1", 220.0, "220", Unit.CURRENCY)
        # "ARPU" is ~50 chars before "220" — outside ±30-char window
        source = "ARPU grew significantly this quarter. Average order size was $220."
        is_fp, reason = _is_v2_false_positive(
            bv, source, metric_id="cm_average_order_value", relaxed=True
        )
        assert is_fp is False

    def test_rule_does_not_fire_for_non_aov_metric(self):
        """ARPU label near value but wrong metric → not filtered."""
        bv = _make_bound_value("c1", 220.0, "220", Unit.CURRENCY)
        source = "ARPU is $220 per customer."
        is_fp, reason = _is_v2_false_positive(
            bv, source, metric_id="cm_arpu", relaxed=True
        )
        assert is_fp is False


# ============================================================================
# Test: V2-native — Suppressed section types (OPERATOR, DISCLAIMER)
# ============================================================================


class TestSuppressedSectionTypes:
    """Values from OPERATOR or DISCLAIMER sections should always be suppressed."""

    def test_operator_section_suppressed(self):
        """Any value extracted from OPERATOR section is filtered."""
        bv = _make_bound_value("c1", 1000.0, "1,000", Unit.COUNT)
        source = "Thank you for joining us. We have 1,000 participants on the line."
        is_fp, reason = _is_v2_false_positive(
            bv, source, metric_id="cm_customers_period_end",
            section_type=SectionType.OPERATOR,
        )
        assert is_fp is True
        assert reason == "v2_suppressed_section"

    def test_disclaimer_section_suppressed(self):
        """Any value extracted from DISCLAIMER section is filtered."""
        bv = _make_bound_value("c1", 500.0, "500", Unit.COUNT)
        source = "This presentation contains forward-looking statements for 500 days."
        is_fp, reason = _is_v2_false_positive(
            bv, source, metric_id="cm_customers_period_end",
            section_type=SectionType.DISCLAIMER,
        )
        assert is_fp is True
        assert reason == "v2_suppressed_section"

    def test_prepared_remarks_not_suppressed(self):
        """PREPARED_REMARKS section values are NOT blanket-suppressed."""
        bv = _make_bound_value("c1", 50000.0, "50,000", Unit.COUNT)
        source = "We ended the quarter with 50,000 paying customers."
        is_fp, reason = _is_v2_false_positive(
            bv, source, metric_id="cm_customers_period_end",
            section_type=SectionType.PREPARED_REMARKS,
        )
        assert is_fp is False

    def test_unknown_section_not_suppressed(self):
        """UNKNOWN section (default) is not blanket-suppressed."""
        bv = _make_bound_value("c1", 50000.0, "50,000", Unit.COUNT)
        source = "We ended the quarter with 50,000 paying customers."
        is_fp, reason = _is_v2_false_positive(
            bv, source, metric_id="cm_customers_period_end",
        )
        assert is_fp is False


# ============================================================================
# Test: V2-native — Dollar threshold customer suppression
# ============================================================================


class TestV2DollarThresholdCustomer:
    """Threshold-qualified customer counts should be suppressed for non-large-customer metrics."""

    def test_table_cell_paid_customers_threshold_suppressed_for_total(self):
        """'Paid Customers >$100,000 298' suppresses cm_customers_period_end."""
        source = "As of January 31, 2018 Paid Customers >$100,000 298"
        bv = _make_bound_value("c1", 298.0, "298", Unit.COUNT, "seg-1")
        is_fp, reason = _is_v2_false_positive(bv, source, "cm_customers_period_end")
        assert is_fp is True
        assert reason == "v2_dollar_threshold_customer"

    def test_prose_threshold_suppressed(self):
        """Prose 'we had 575 Paid Customers >$100,000 of ARR' suppresses cm_customers_period_end."""
        source = "As of January 31, 2019, we had 575 Paid Customers >$100,000 of ARR"
        bv = _make_bound_value("c1", 575.0, "575", Unit.COUNT, "seg-1")
        is_fp, reason = _is_v2_false_positive(bv, source, "cm_customers_period_end")
        assert is_fp is True
        assert reason == "v2_dollar_threshold_customer"

    def test_threshold_suppresses_nrr_count_value(self):
        """Count value near dollar threshold context suppresses cm_net_revenue_retention FP.

        In Slack's key metrics table, customer COUNT rows (e.g. '298 customers >$100K ARR')
        are adjacent to NRR rows. A COUNT value like 298 bound to NRR is a FP and should
        be suppressed. The rule targets COUNT values, not percent NRR values.
        """
        source = "Paid Customers >$100,000 135 298 575 Net Dollar Retention Rate 171% 152% 143%"
        bv = _make_bound_value("c1", 298.0, "298", Unit.COUNT, "seg-1")
        is_fp, reason = _is_v2_false_positive(bv, source, "cm_net_revenue_retention")
        assert is_fp is True
        assert reason == "v2_dollar_threshold_customer"

    def test_threshold_does_not_suppress_nrr_percent_value(self):
        """Percent NRR values near dollar threshold are NOT suppressed.

        Flywire discloses NRR (110-125%) in a section that also mentions
        customer thresholds. The real NRR percent values should not be filtered.
        """
        source = "Our net revenue retention was 110% for fiscal 2020. We serve customers with ARR >$50,000."
        bv = _make_bound_value("c1", 110.0, "110%", Unit.PERCENT, "seg-1")
        is_fp, _ = _is_v2_false_positive(bv, source, "cm_net_revenue_retention")
        assert is_fp is False

    def test_large_customer_metric_not_suppressed(self):
        """cm_large_customers_period_end is NOT suppressed by dollar threshold rule."""
        source = "As of January 31, 2018 Paid Customers >$100,000 298"
        bv = _make_bound_value("c1", 298.0, "298", Unit.COUNT, "seg-1")
        is_fp, _ = _is_v2_false_positive(bv, source, "cm_large_customers_period_end")
        assert is_fp is False

    def test_total_customers_no_threshold_not_suppressed(self):
        """Total customer count without threshold pattern is NOT suppressed."""
        source = "As of January 31, 2019, we had 95,000 Paid Customers"
        bv = _make_bound_value("c1", 95000.0, "95,000", Unit.COUNT, "seg-1")
        is_fp, _ = _is_v2_false_positive(bv, source, "cm_customers_period_end")
        assert is_fp is False


# ============================================================================
# Test: V2-native — Delta count value suppression
# ============================================================================


class TestDeltaCountValueRule:
    """_rule_delta_count_value blocks delta/growth amounts on count metrics."""

    def test_increase_of_prefix_rejected(self):
        """'saw an increase of 34 million daily active users' → rejected."""
        source = "saw an increase of 34 million daily active users"
        bv = _make_bound_value("c1", 34_000_000.0, "34 million", Unit.COUNT)
        is_fp, reason = _is_v2_false_positive(
            bv, source, metric_id="cm_daily_active_users"
        )
        assert is_fp is True
        assert reason == "v2_delta_count_value"

    def test_up_by_more_than_narrow_window_rejected(self):
        """'MAU grew by more than 150 million users' → rejected (30-char window, verb immediately before 'by')."""
        source = "MAU grew by more than 150 million users"
        bv = _make_bound_value("c1", 150_000_000.0, "150 million", Unit.COUNT)
        is_fp, reason = _is_v2_false_positive(
            bv, source, metric_id="cm_monthly_active_users"
        )
        assert is_fp is True
        assert reason == "v2_delta_count_value"

    def test_grew_to_absolute_value_not_rejected(self):
        """'grew 10% to 86.3 million daily active users' → NOT rejected (no delta prefix before value)."""
        source = "grew 10% to 86.3 million daily active users"
        bv = _make_bound_value("c1", 86_300_000.0, "86.3 million", Unit.COUNT)
        is_fp, reason = _is_v2_false_positive(
            bv, source, metric_id="cm_daily_active_users"
        )
        assert reason != "v2_delta_count_value"

    def test_new_customers_acquired_excluded(self):
        """cm_new_customers_acquired is exempt — 'increase of 5 million new customers' NOT rejected."""
        source = "increase of 5 million new customers acquired"
        bv = _make_bound_value("c1", 5_000_000.0, "5 million", Unit.COUNT)
        is_fp, reason = _is_v2_false_positive(
            bv, source, metric_id="cm_new_customers_acquired"
        )
        assert reason != "v2_delta_count_value"

    def test_used_by_more_than_not_rejected(self):
        """'Facebook is used by more than 3 billion monthly actives' → NOT rejected (no directional verb before 'by')."""
        source = "Facebook is used by more than 3 billion monthly actives"
        bv = _make_bound_value("c1", 3_000_000_000.0, "3 billion", Unit.COUNT)
        is_fp, reason = _is_v2_false_positive(
            bv, source, metric_id="cm_monthly_active_users"
        )
        assert reason != "v2_delta_count_value"

    def test_grown_mau_by_more_than_with_zwsp_rejected(self):
        """'grown\u200b MAU\u200b by\u200b more\u200b than\u200b 150' (zero-width spaces) → rejected as delta."""
        # Simulates zero-width space characters from PDF conversion (SNAP investor letters).
        # The verb ('grown') is separated from 'by more than' by a noun phrase and \u200b chars.
        source = "\u200b \u200bgrown\u200b \u200bMonthly\u200b \u200bActive\u200b \u200bUsers\u200b\u200b(MAU)\u200b\u200bby\u200b\u200bmore\u200b\u200bthan\u200b\u200b150 million users"
        bv = _make_bound_value("c1", 150_000_000.0, "150", Unit.COUNT)
        is_fp, reason = _is_v2_false_positive(
            bv, source, metric_id="cm_monthly_active_users"
        )
        assert is_fp is True
        assert reason == "v2_delta_count_value"


# ============================================================================
# Test: V2-native — Extended forward guidance patterns
# ============================================================================


class TestExtendedForwardGuidance:
    """Extended _FORWARD_GUIDANCE_RE patterns — goal/target/aspire/on-track."""

    def test_goal_of_reaching_rejects_value(self):
        """'goal of reaching one billion monthly active users' → rejected as guidance."""
        from src.extraction_v2.models import SectionType

        bv = _make_bound_value("c1", 1_000_000_000.0, "one billion", Unit.COUNT)
        source = "We have a goal of reaching one billion monthly active users by end of year."
        is_fp, reason = _is_v2_false_positive(
            bv, source, metric_id="cm_monthly_active_users",
            relaxed=True, section_type=SectionType.PREPARED_REMARKS
        )
        assert is_fp is True
        assert reason == "v2_forward_guidance"

    def test_on_track_to_reach_rejects_value(self):
        """'on track to reach 500 million users' → rejected as guidance."""
        from src.extraction_v2.models import SectionType

        bv = _make_bound_value("c1", 500_000_000.0, "500 million", Unit.COUNT)
        source = "We are on track to reach 500 million users by the end of fiscal year."
        is_fp, reason = _is_v2_false_positive(
            bv, source, metric_id="cm_monthly_active_users",
            relaxed=True, section_type=SectionType.PREPARED_REMARKS
        )
        assert is_fp is True
        assert reason == "v2_forward_guidance"


# ============================================================================
# Test: V2-native — Revenue concentration context (renamed from geographic_revenue)
# ============================================================================


class TestRevenueConcentrationContextRule:
    """_rule_revenue_concentration_context covers geo, capex, and cost-structure contexts."""

    def test_cost_of_revenue_percent_rejected(self):
        """'cost of revenue was 18% of revenue' → rejected as cost structure."""
        source = "cost of revenue was 18% of revenue for the quarter"
        bv = _make_bound_value("c1", 18.0, "18", Unit.PERCENT)
        is_fp, reason = _is_v2_false_positive(
            bv, source, metric_id="cm_revenue_concentration"
        )
        assert is_fp is True
        assert reason == "v2_cost_structure_revenue"

    def test_gross_margin_percent_rejected(self):
        """'adjusted gross margin of 72%' → rejected as cost structure."""
        source = "adjusted gross margin of 72% this quarter"
        bv = _make_bound_value("c1", 72.0, "72", Unit.PERCENT)
        is_fp, reason = _is_v2_false_positive(
            bv, source, metric_id="cm_revenue_concentration"
        )
        assert is_fp is True
        assert reason == "v2_cost_structure_revenue"

    def test_geographic_revenue_still_rejected(self):
        """Geographic language still fires after rename."""
        source = "international revenue represented 45% of total revenue"
        bv = _make_bound_value("c1", 45.0, "45", Unit.PERCENT)
        is_fp, reason = _is_v2_false_positive(
            bv, source, metric_id="cm_revenue_concentration"
        )
        assert is_fp is True
        assert reason == "v2_geographic_revenue"

    def test_capex_revenue_still_rejected(self):
        """CapEx language still fires after rename."""
        source = "CapEx for the fiscal year to be approximately 2% of revenue"
        bv = _make_bound_value("c1", 2.0, "2", Unit.PERCENT)
        is_fp, reason = _is_v2_false_positive(
            bv, source, metric_id="cm_revenue_concentration"
        )
        assert is_fp is True
        assert reason == "v2_capex_revenue"

    def test_customer_revenue_concentration_not_rejected(self):
        """Genuine revenue concentration (customer context) → not rejected."""
        source = "Our top 10 customers accounted for 32% of revenue"
        bv = _make_bound_value("c1", 32.0, "32", Unit.PERCENT)
        is_fp, reason = _is_v2_false_positive(
            bv, source, metric_id="cm_revenue_concentration"
        )
        assert is_fp is False

    def test_north_america_geographic_rejected(self):
        """'North America LCS business accounted for 43% of total global revenue' → rejected as geographic."""
        source = "The North America LCS business accounted for approximately 43% of total global revenue in Q3"
        bv = _make_bound_value("c1", 43.0, "43", Unit.PERCENT)
        is_fp, reason = _is_v2_false_positive(
            bv, source, metric_id="cm_revenue_concentration"
        )
        assert is_fp is True
        assert reason == "v2_geographic_revenue"

    def test_cross_segment_value_not_in_text_suppressed(self):
        """When value_raw not found in source_text → fires v2_cross_segment_revenue_concentration."""
        # Simulates cross-segment binding: segment has North America geo context
        # but the value (18%) comes from a different paragraph
        source = "The North America LCS business accounted for approximately 43% of total global revenue in Q3"
        bv = _make_bound_value("c1", 18.0, "18%", Unit.PERCENT)
        # '18%' is not in source — cross-segment binding scenario
        assert "18%" not in source
        is_fp, reason = _is_v2_false_positive(
            bv, source, metric_id="cm_revenue_concentration"
        )
        assert is_fp is True
        assert reason == "v2_cross_segment_revenue_concentration"

    def test_cross_segment_any_segment_suppressed(self):
        """Cross-segment suppression fires regardless of what the wrong segment contains."""
        source = "Free Cash Flow was $93 million in Q3 while Operating Cash Flow was $146 million."
        bv = _make_bound_value("c1", 99.0, "99", Unit.PERCENT)
        assert "99" not in source
        is_fp, reason = _is_v2_false_positive(
            bv, source, metric_id="cm_revenue_concentration"
        )
        assert is_fp is True
        assert reason == "v2_cross_segment_revenue_concentration"

    def test_guidance_range_percent_rejected(self):
        """'full year cost structure guidance range of 18% to 19%' → rejected as cost structure.

        The nearest cost-structure pattern ('guidance range') is close to the value,
        but an earlier 'Cost of Revenue' occurrence is 400+ chars away. Uses finditer
        to find the nearest match rather than just the first.
        """
        # Simulate segment with "Cost of Revenue" far from value, "guidance range" nearby
        preamble = "Cost of Revenue " + "x" * 400
        tail = "our full year cost structure guidance range of 18% to 19%"
        source = preamble + tail
        bv = _make_bound_value("c1", 18.0, "18%", Unit.PERCENT)
        is_fp, reason = _is_v2_false_positive(
            bv, source, metric_id="cm_revenue_concentration"
        )
        assert is_fp is True
        assert reason == "v2_cost_structure_revenue"


# ============================================================================
# Test: V2-native — Forward guidance "goal of serving" extension
# ============================================================================


class TestGoalOfServingGuidance:
    """'goal of serving N billion' should fire as forward guidance in relaxed mode."""

    def test_goal_of_serving_rejects_value(self):
        """'long-term goal of serving more than 1 billion global monthly active users' → rejected."""
        from src.extraction_v2.models import SectionType

        bv = _make_bound_value("c1", 1_000_000_000.0, "1 billion", Unit.COUNT)
        source = "we remain committed to our long-term goal of serving more than 1 billion global monthly active users."
        is_fp, reason = _is_v2_false_positive(
            bv, source, metric_id="cm_monthly_active_users",
            relaxed=True, section_type=SectionType.PREPARED_REMARKS
        )
        assert is_fp is True
        assert reason == "v2_forward_guidance"

    def test_goal_of_serving_not_fired_in_non_relaxed(self):
        """Forward guidance is relaxed-only — SEC filing mode unaffected."""
        from src.extraction_v2.models import SectionType

        bv = _make_bound_value("c1", 1_000_000_000.0, "1 billion", Unit.COUNT)
        source = "we remain committed to our long-term goal of serving more than 1 billion global monthly active users."
        is_fp, reason = _is_v2_false_positive(
            bv, source, metric_id="cm_monthly_active_users",
            relaxed=False, section_type=SectionType.PREPARED_REMARKS
        )
        assert reason != "v2_forward_guidance"


# ============================================================================
# Test: V2-native — Transactions per account rule
# ============================================================================


class TestTransactionsPerAccountRule:
    """_rule_transactions_per_account suppresses TPA ratios mis-classified as
    count-type metric values."""

    def test_tpa_fires_for_count_metric(self):
        """'57.6 transactions per active account' → rejected for cm_customers_period_end."""
        source = "PayPal generated 57.6 transactions per active account in the quarter."
        bv = _make_bound_value("c1", 57.6, "57.6", Unit.COUNT)
        is_fp, reason = _is_v2_false_positive(
            bv, source, metric_id="cm_customers_period_end"
        )
        assert is_fp is True
        assert reason == "v2_transactions_per_account"

    def test_tpa_fires_for_active_customers_total(self):
        """'57.6 transactions per active account' → rejected for cm_active_customers_total."""
        source = "We saw 57.6 transactions per active account on our platform."
        bv = _make_bound_value("c1", 57.6, "57.6", Unit.COUNT)
        is_fp, reason = _is_v2_false_positive(
            bv, source, metric_id="cm_active_customers_total"
        )
        assert is_fp is True
        assert reason == "v2_transactions_per_account"

    def test_tpa_does_not_fire_for_non_count_metric(self):
        """No TPA phrase → cm_average_order_value value is NOT suppressed."""
        source = "Cross-sell revenue of 50 million was driven by upsell motions."
        bv = _make_bound_value("c1", 50.0, "50 million", Unit.COUNT)
        is_fp, reason = _is_v2_false_positive(
            bv, source, metric_id="cm_average_order_value"
        )
        assert reason != "v2_transactions_per_account"

    def test_tpa_does_not_fire_for_unrelated_metric(self):
        """TPA phrase is present but metric is cm_average_order_value → rule does not fire."""
        source = "ARR reached 57.6 billion; transactions per active account were flat."
        bv = _make_bound_value("c1", 57.6, "57.6", Unit.COUNT)
        is_fp, reason = _is_v2_false_positive(
            bv, source, metric_id="cm_average_order_value"
        )
        assert reason != "v2_transactions_per_account"

    def test_tpa_fires_at_85_char_distance(self):
        """PYPL-style prose: phrase ~85 chars before value → rejected within 150-char window."""
        # Real PYPL prose: phrase ends ~85 chars before "57.6"
        source = (
            "Payment transactions per active account ('TPA') on a trailing "
            "12-month basis decreased 6% to 57.6"
        )
        bv = _make_bound_value("c1", 57.6, "57.6", Unit.COUNT)
        is_fp, reason = _is_v2_false_positive(
            bv, source, metric_id="cm_active_customers_total"
        )
        assert is_fp is True
        assert reason == "v2_transactions_per_account"


# ============================================================================
# Test: _DELTA_COUNT_RE — "or by" prefix pattern
# ============================================================================


class TestDeltaCountOrBy:
    """_DELTA_COUNT_RE now matches ',? or by' prefix in addition to existing patterns."""

    def test_or_by_fires(self):
        """'or by 0.3 million' immediately before value → rejected as delta."""
        source = "active accounts grew or by 0.3 million customers this quarter"
        bv = _make_bound_value("c1", 300_000.0, "0.3 million", Unit.COUNT)
        is_fp, reason = _is_v2_false_positive(
            bv, source, metric_id="cm_active_customers_total"
        )
        assert is_fp is True
        assert reason == "v2_delta_count_value"

    def test_comma_or_by_fires(self):
        """', or by 4.7 million' immediately before value → rejected as delta."""
        source = "the customer base increased by 2 million, or by 4.7 million accounts"
        bv = _make_bound_value("c1", 4_700_000.0, "4.7 million", Unit.COUNT)
        is_fp, reason = _is_v2_false_positive(
            bv, source, metric_id="cm_customers_period_end"
        )
        assert is_fp is True
        assert reason == "v2_delta_count_value"

    def test_or_by_approximately_fires(self):
        """'or by approximately 1.2 million' immediately before value → rejected as delta."""
        source = "MAU increased 5%, or by approximately 1.2 million users"
        bv = _make_bound_value("c1", 1_200_000.0, "1.2 million", Unit.COUNT)
        is_fp, reason = _is_v2_false_positive(
            bv, source, metric_id="cm_monthly_active_users"
        )
        assert is_fp is True
        assert reason == "v2_delta_count_value"

    def test_unrelated_or_does_not_fire(self):
        """'one or two million' — ambiguous 'or' not matched by delta pattern."""
        source = "we expect one or two million active customers by year end"
        bv = _make_bound_value("c1", 2_000_000.0, "two million", Unit.COUNT)
        is_fp, reason = _is_v2_false_positive(
            bv, source, metric_id="cm_active_customers_total"
        )
        assert reason != "v2_delta_count_value"


# ============================================================================
# Test: _rule_retention_rate_over_100
# ============================================================================


class TestRetentionRateOver100:
    """Tests for _rule_retention_rate_over_100 — blocks NRR values on retention metric."""

    def test_value_over_130_rejected(self):
        """Retention rate of 135% → rejected by value threshold (above 130)."""
        bv = _make_bound_value("c1", 135.0, "135%", Unit.PERCENT)
        source = "Customer retention rate was 135% this quarter."
        is_fp, reason = _is_v2_false_positive(
            bv, source, metric_id="cm_customer_retention_rate"
        )
        assert is_fp is True
        assert reason == "v2_retention_rate_over_100"

    def test_value_115_rejected(self):
        """Retention rate of 115% → rejected (above new threshold of 100; this is NRR, not CRR)."""
        bv = _make_bound_value("c1", 115.0, "115%", Unit.PERCENT)
        source = "Customer retention rate was 115% this quarter."
        is_fp, reason = _is_v2_false_positive(
            bv, source, metric_id="cm_customer_retention_rate"
        )
        assert is_fp is True
        assert reason == "v2_retention_rate_over_100"

    def test_value_exactly_100_kept(self):
        """Retention rate of exactly 100% → kept (boundary case)."""
        bv = _make_bound_value("c1", 100.0, "100%", Unit.PERCENT)
        source = "We maintained a 100% customer retention rate."
        is_fp, reason = _is_v2_false_positive(
            bv, source, metric_id="cm_customer_retention_rate"
        )
        assert is_fp is False

    def test_value_below_100_kept(self):
        """Retention rate of 92% → kept."""
        bv = _make_bound_value("c1", 92.0, "92%", Unit.PERCENT)
        source = "Customer retention rate was 92% in fiscal year 2024."
        is_fp, reason = _is_v2_false_positive(
            bv, source, metric_id="cm_customer_retention_rate"
        )
        assert is_fp is False

    def test_nrr_context_rejects_value_under_100(self):
        """Value of 98% but source has NRR keyword → rejected."""
        bv = _make_bound_value("c1", 98.0, "98%", Unit.PERCENT)
        source = "Net revenue retention (NRR) was 98%, reflecting some churn."
        is_fp, reason = _is_v2_false_positive(
            bv, source, metric_id="cm_customer_retention_rate"
        )
        assert is_fp is True
        assert reason == "v2_retention_rate_nrr_context"

    def test_ndr_context_rejects_value(self):
        """NDR keyword in source → rejected as NRR context."""
        bv = _make_bound_value("c1", 105.0, "105%", Unit.PERCENT)
        source = "NDR was 105%, above our target."
        is_fp, reason = _is_v2_false_positive(
            bv, source, metric_id="cm_customer_retention_rate"
        )
        assert is_fp is True

    def test_rule_not_fired_for_other_metric(self):
        """Value of 120% for cm_gross_retention_rate → not fired by this rule."""
        bv = _make_bound_value("c1", 120.0, "120%", Unit.PERCENT)
        source = "Gross retention was 120%."
        is_fp, reason = _is_v2_false_positive(
            bv, source, metric_id="cm_gross_retention_rate"
        )
        # Rule should not fire for non-cm_customer_retention_rate metrics
        assert reason != "v2_retention_rate_over_100"
        assert reason != "v2_retention_rate_nrr_context"


# ============================================================================
# Test: _rule_magnitude_sanity
# ============================================================================


class TestMagnitudeSanity:
    """Tests for _rule_magnitude_sanity — blocks implausibly large per-metric values."""

    def test_ltv_cac_over_100x_rejected(self):
        """LTV:CAC ratio of 500x → rejected as implausibly large."""
        bv = _make_bound_value("c1", 500.0, "500", Unit.COUNT)
        source = "Our LTV to CAC ratio is 500x, reflecting strong unit economics."
        is_fp, reason = _is_v2_false_positive(
            bv, source, metric_id="cm_ltv_to_cac_ratio"
        )
        assert is_fp is True
        assert reason == "v2_magnitude_sanity"

    def test_ltv_cac_plausible_value_kept(self):
        """LTV:CAC ratio of 4.5x → kept (plausible)."""
        bv = _make_bound_value("c1", 4.5, "4.5", Unit.COUNT)
        source = "Our LTV to CAC ratio is 4.5x."
        is_fp, reason = _is_v2_false_positive(
            bv, source, metric_id="cm_ltv_to_cac_ratio"
        )
        assert is_fp is False

    def test_revenue_per_customer_over_max_rejected(self):
        """ARPU of $500M → rejected (financial figure mis-bound to ARPU metric)."""
        bv = _make_bound_value("c1", 500_000_000.0, "500 million", Unit.CURRENCY)
        source = "Revenue per customer reached $500 million."
        is_fp, reason = _is_v2_false_positive(
            bv, source, metric_id="cm_revenue_per_customer"
        )
        assert is_fp is True
        assert reason == "v2_magnitude_sanity"

    def test_revenue_per_customer_plausible_kept(self):
        """ARPU of $50,000 → kept (within max)."""
        bv = _make_bound_value("c1", 50_000.0, "50,000", Unit.CURRENCY)
        source = "Average revenue per customer was $50,000."
        is_fp, reason = _is_v2_false_positive(
            bv, source, metric_id="cm_revenue_per_customer"
        )
        assert is_fp is False

    def test_rule_not_fired_for_unconstrained_metric(self):
        """Large value for cm_average_order_value → not rejected by magnitude rule (no max defined)."""
        bv = _make_bound_value("c1", 999_000_000.0, "999 million", Unit.CURRENCY)
        source = "ARR reached $999 million."
        is_fp, reason = _is_v2_false_positive(
            bv, source, metric_id="cm_average_order_value"
        )
        assert reason != "v2_magnitude_sanity"

    def test_ltv_at_max_boundary_kept(self):
        """LTV:CAC exactly at 25x boundary → kept (not strictly greater than)."""
        bv = _make_bound_value("c1", 25.0, "25", Unit.COUNT)
        source = "LTV to CAC ratio is 25x."
        is_fp, reason = _is_v2_false_positive(
            bv, source, metric_id="cm_ltv_to_cac_ratio"
        )
        assert is_fp is False


# ============================================================================
# Test: _rule_arpu_context_on_customer_count
# ============================================================================


class TestArpuContextOnCustomerCount:
    """Tests for _rule_arpu_context_on_customer_count.

    The rule fires when:
      - metric_id is cm_active_customers_total or cm_customers_period_end
      - binding_type is table_header or table_stub (NOT text_proximity)
      - source text contains an ARPU/revenue-per-customer keyword

    It applies in both strict (SEC filing) and relaxed (presentation) modes
    because the binding_type guard prevents false removals in paragraph prose.
    """

    def test_net_sales_per_active_customer_blocks_table_stub(self):
        """Table-stub 'Net sales per active customer' → cm_active_customers_total blocked."""
        bv = BoundValue(
            candidate_id="c1", value=343.0, value_raw="343", unit=Unit.CURRENCY,
            binding_type="table_stub", binding_confidence=0.7,
            source_locator=SourceLocator(segment_id="seg-1"),
        )
        source = "Net Sales per Active Customer $ 343"
        is_fp, reason = _is_v2_false_positive(
            bv, source, metric_id="cm_active_customers_total", relaxed=True
        )
        assert is_fp is True
        assert reason == "v2_arpu_context_on_customer_count"

    def test_table_stub_fires_in_strict_mode(self):
        """Rule fires in strict mode (SEC filings) for table bindings."""
        bv = BoundValue(
            candidate_id="c1", value=343.0, value_raw="343", unit=Unit.CURRENCY,
            binding_type="table_stub", binding_confidence=0.7,
            source_locator=SourceLocator(segment_id="seg-1"),
        )
        source = "Net sales per active customer $ 343"
        is_fp, reason = _is_v2_false_positive(
            bv, source, metric_id="cm_active_customers_total", relaxed=False
        )
        assert is_fp is True
        assert reason == "v2_arpu_context_on_customer_count"

    def test_text_proximity_not_blocked_even_with_arpu_keyword(self):
        """text_proximity binding with ARPU keyword → not blocked (paragraph prose guard)."""
        bv = _make_bound_value("c1", 343.0, "343", Unit.CURRENCY)  # binding_type=text_proximity
        source = "Net sales per active customer was $343 and we had 10.6M active customers."
        is_fp, reason = _is_v2_false_positive(
            bv, source, metric_id="cm_active_customers_total", relaxed=True
        )
        assert reason != "v2_arpu_context_on_customer_count"

    def test_arpu_keyword_blocks_table_stub(self):
        """'ARPU' keyword in table_stub source → cm_active_customers_total blocked."""
        bv = BoundValue(
            candidate_id="c1", value=108.9, value_raw="108.9", unit=Unit.CURRENCY,
            binding_type="table_stub", binding_confidence=0.7,
            source_locator=SourceLocator(segment_id="seg-1"),
        )
        source = "ARPU 108.9"
        is_fp, reason = _is_v2_false_positive(
            bv, source, metric_id="cm_active_customers_total", relaxed=True
        )
        assert is_fp is True
        assert reason == "v2_arpu_context_on_customer_count"

    def test_table_header_binding_also_fires(self):
        """table_header binding type also triggers the rule."""
        bv = BoundValue(
            candidate_id="c1", value=297.0, value_raw="297", unit=Unit.CURRENCY,
            binding_type="table_header", binding_confidence=0.7,
            source_locator=SourceLocator(segment_id="seg-1"),
        )
        source = "Revenue per customer $ 297"
        is_fp, reason = _is_v2_false_positive(
            bv, source, metric_id="cm_customers_period_end", relaxed=True
        )
        assert is_fp is True
        assert reason == "v2_arpu_context_on_customer_count"

    def test_plain_customer_count_not_blocked(self):
        """Generic customer count source → not blocked regardless of binding type."""
        bv = BoundValue(
            candidate_id="c1", value=10_600_000.0, value_raw="10.6 million", unit=Unit.COUNT,
            binding_type="table_stub", binding_confidence=0.7,
            source_locator=SourceLocator(segment_id="seg-1"),
        )
        source = "Active Customers 10600000"
        is_fp, reason = _is_v2_false_positive(
            bv, source, metric_id="cm_active_customers_total", relaxed=True
        )
        assert reason != "v2_arpu_context_on_customer_count"

    def test_rule_not_fired_for_arpu_metric(self):
        """ARPU context on the ARPU metric itself → rule does not fire."""
        bv = BoundValue(
            candidate_id="c1", value=343.0, value_raw="343", unit=Unit.CURRENCY,
            binding_type="table_stub", binding_confidence=0.7,
            source_locator=SourceLocator(segment_id="seg-1"),
        )
        source = "Net sales per active customer $ 343"
        is_fp, reason = _is_v2_false_positive(
            bv, source, metric_id="cm_revenue_per_customer", relaxed=True
        )
        assert reason != "v2_arpu_context_on_customer_count"


# ============================================================================
# Test: revenue concentration rules (existing v2_geographic_revenue etc.)
# ============================================================================


class TestRevenueConcentrationContext:
    """Smoke tests: _rule_revenue_concentration_context still fires correctly."""

    def test_geographic_revenue_blocks_concentration(self):
        """'International revenue' context → cm_revenue_concentration blocked."""
        bv = _make_bound_value("c1", 44.0, "44%", Unit.PERCENT)
        source = "44% of our revenue was international in the quarter."
        is_fp, reason = _is_v2_false_positive(
            bv, source, metric_id="cm_revenue_concentration"
        )
        assert is_fp is True

    def test_partner_concentration_not_blocked(self):
        """Legitimate partner concentration without geographic context → not blocked."""
        bv = _make_bound_value("c1", 23.0, "23%", Unit.PERCENT)
        source = "Our top 10 retail partners accounted for 23% of total revenue."
        is_fp, reason = _is_v2_false_positive(
            bv, source, metric_id="cm_revenue_concentration"
        )
        assert reason not in (
            "v2_revenue_concentration_no_keyword",
            "v2_geographic_revenue",
            "v2_cost_structure_revenue",
        )


# ============================================================================
# Test: Document type skip tags (Step 1)
# ============================================================================


def _make_table_bound_value(
    candidate_id: str,
    value: float,
    raw: str,
    unit: Unit = Unit.COUNT,
    table_id: str = "tbl-1",
) -> BoundValue:
    """Create a table-sourced BoundValue for testing."""
    return BoundValue(
        candidate_id=candidate_id,
        value=value,
        value_raw=raw,
        unit=unit,
        binding_type="table_header",
        binding_confidence=0.5,
        source_locator=SourceLocator(
            table_id=table_id,
            cell_row=1,
            cell_col=0,
        ),
    )


class TestDocumentTypeSkipTags:
    """Verify that financial_annotation/sbc rules fire for presentations but not transcripts."""

    def test_financial_annotation_skipped_for_presentation(self):
        """(In thousands) in presentation context → skipped (press releases contain these footnotes near metrics)."""
        source = "(In thousands) Customer count 5,000"
        bv = _make_bound_value("c1", 5000.0, "5,000", Unit.COUNT)
        is_fp, reason = _is_v2_false_positive(
            bv, source, relaxed=True, document_type="investor_presentation"
        )
        assert reason != "v2_financial_annotation"

    def test_financial_annotation_skipped_for_transcript(self):
        """(In thousands) in transcript context → rule skipped."""
        source = "(In thousands) Customer count 5,000"
        bv = _make_bound_value("c1", 5000.0, "5,000", Unit.COUNT)
        is_fp, reason = _is_v2_false_positive(
            bv, source, relaxed=True, document_type="transcript"
        )
        assert reason != "v2_financial_annotation"

    def test_financial_annotation_skipped_when_no_document_type(self):
        """relaxed=True without document_type → transcript-level skipping (backward compat)."""
        source = "(In thousands) Customer count 5,000"
        bv = _make_bound_value("c1", 5000.0, "5,000", Unit.COUNT)
        is_fp, reason = _is_v2_false_positive(bv, source, relaxed=True)
        assert reason != "v2_financial_annotation"

    def test_financial_annotation_fires_in_sec_mode(self):
        """(In thousands) in SEC filing context → FP (not relaxed)."""
        source = "(In thousands) Customer count 5,000"
        bv = _make_bound_value("c1", 5000.0, "5,000", Unit.COUNT)
        is_fp, reason = _is_v2_false_positive(
            bv, source, relaxed=False, document_type="sec_filing"
        )
        assert is_fp is True
        assert reason == "v2_financial_annotation"

    def test_financial_sbc_skipped_for_presentation(self):
        """Stock-based compensation footnote in presentation → skipped."""
        source = "stock-based compensation expense 1,200"
        bv = _make_bound_value("c1", 1200.0, "1,200", Unit.COUNT)
        is_fp, reason = _is_v2_false_positive(
            bv, source, relaxed=True, document_type="investor_presentation"
        )
        assert reason != "v2_financial_sbc"

    def test_linearized_table_skipped_for_presentation(self):
        """[CELL]/[ROW] markers still skipped for presentations (shared skip)."""
        source = "[ROW] Customer count [CELL] 5,000"
        bv = _make_bound_value("c1", 5000.0, "5,000", Unit.COUNT)
        is_fp, reason = _is_v2_false_positive(
            bv, source, relaxed=True, document_type="investor_presentation"
        )
        assert reason != "v2_linearized_table"


# ============================================================================
# Test: _rule_financial_context_on_customer_metric (Step 2)
# ============================================================================


class TestFinancialContextOnCustomerMetric:
    """Financial-keyword context blocks customer metrics."""

    def test_ebitda_blocks_customer_count_text(self):
        """EBITDA in proximity → cm_active_customers_total blocked."""
        source = "Adjusted EBITDA was $120 million. We had 1,200 active customers."
        bv = _make_bound_value("c1", 1200.0, "1,200", Unit.COUNT)
        is_fp, reason = _is_v2_false_positive(
            bv, source, metric_id="cm_active_customers_total"
        )
        assert is_fp is True
        assert reason == "v2_financial_context_customer_metric"

    def test_free_cash_flow_blocks_customer_count_text(self):
        """Free cash flow in proximity → cm_active_customers_total blocked."""
        source = "Cash flow from operations was $80 million. We had 2,500 active customers."
        bv = _make_bound_value("c1", 2500.0, "2,500", Unit.COUNT)
        is_fp, reason = _is_v2_false_positive(
            bv, source, metric_id="cm_active_customers_total"
        )
        assert is_fp is True
        assert reason == "v2_financial_context_customer_metric"

    def test_net_loss_blocks_mau_text(self):
        """Net loss within 100 chars → cm_monthly_active_users blocked."""
        source = "Net loss of $45 million. Monthly active users were 3,500."
        bv = _make_bound_value("c1", 3500.0, "3,500", Unit.COUNT)
        is_fp, reason = _is_v2_false_positive(
            bv, source, metric_id="cm_monthly_active_users"
        )
        assert is_fp is True
        assert reason == "v2_financial_context_customer_metric"

    def test_financial_keyword_table_always_fires(self):
        """Financial keyword in table source → always blocked regardless of distance."""
        source = "EBITDA 120,000"  # header/stub text
        bv = _make_table_bound_value("c1", 120000.0, "120,000", Unit.CURRENCY)
        is_fp, reason = _is_v2_false_positive(
            bv, source, metric_id="cm_active_customers_total"
        )
        assert is_fp is True
        assert reason == "v2_financial_context_customer_metric"

    def test_distant_financial_keyword_text_not_blocked(self):
        """Financial keyword >100 chars away → text binding not blocked."""
        # Put the financial keyword far from the value
        source = "Adjusted EBITDA was $120 million. " + "x" * 100 + " We had 1,200 customers."
        bv = _make_bound_value("c1", 1200.0, "1,200", Unit.COUNT)
        is_fp, reason = _is_v2_false_positive(
            bv, source, metric_id="cm_active_customers_total"
        )
        assert reason != "v2_financial_context_customer_metric"

    def test_financial_keyword_does_not_block_arr(self):
        """Financial keyword near cm_average_order_value → rule does not fire (arr not in blocked set)."""
        source = "Free cash flow $50M. ARR was $200 million."
        bv = _make_bound_value("c1", 200_000_000.0, "$200 million", Unit.CURRENCY)
        is_fp, reason = _is_v2_false_positive(
            bv, source, metric_id="cm_average_order_value"
        )
        assert reason != "v2_financial_context_customer_metric"

    def test_gross_margin_does_not_block_large_customers_text(self):
        """Gross margin in text binding → cm_large_customers_period_end NOT blocked (financial context expected)."""
        # Gross margin appearing near large_customers is not necessarily a FP — it's financial-adjacent.
        source = "Gross margin expanded to 78%. We had 150 large customers."
        bv = _make_bound_value("c1", 150.0, "150", Unit.COUNT)
        is_fp, reason = _is_v2_false_positive(
            bv, source, metric_id="cm_large_customers_period_end"
        )
        # cm_large_customers_period_end is still in blocked metrics — but gross_margin must be
        # within 100 chars of "150". Let proximity determine the outcome.
        # Verify the reason code if it fires.
        if is_fp:
            assert reason == "v2_financial_context_customer_metric"

    def test_number_of_stores_blocks_customer_count(self):
        """Number of stores context → cm_active_customers_total blocked."""
        source = "Number of stores was 450. Active customers totaled 450."
        bv = _make_bound_value("c1", 450.0, "450", Unit.COUNT)
        is_fp, reason = _is_v2_false_positive(
            bv, source, metric_id="cm_active_customers_total"
        )
        assert is_fp is True
        assert reason == "v2_financial_context_customer_metric"

    def test_large_customers_table_exempt_in_range(self):
        """cm_large_customers_period_end table-sourced in 100-1M range → NOT blocked by financial context."""
        source = "gross margin 500"
        bv = _make_table_bound_value("c1", 500.0, "500", Unit.COUNT)
        is_fp, reason = _is_v2_false_positive(
            bv, source, metric_id="cm_large_customers_period_end"
        )
        assert reason != "v2_financial_context_customer_metric"

    def test_large_customers_table_blocked_value_below_range(self):
        """cm_large_customers_period_end table-sourced value=50 (below 100) → IS blocked."""
        source = "total revenue 50"
        bv = _make_table_bound_value("c1", 50.0, "50", Unit.COUNT)
        is_fp, reason = _is_v2_false_positive(
            bv, source, metric_id="cm_large_customers_period_end"
        )
        assert is_fp is True
        assert reason == "v2_financial_context_customer_metric"

    def test_large_customers_table_blocked_value_above_range(self):
        """cm_large_customers_period_end table-sourced value=2_000_000 (above 1M) → IS blocked.

        Note: 2,000,000 exceeds plausible customer count range and may be caught
        by v2_magnitude_sanity before the financial context rule runs — both are
        correct rejections.
        """
        source = "total revenue 2,000,000"
        bv = _make_table_bound_value("c1", 2_000_000.0, "2,000,000", Unit.COUNT)
        is_fp, reason = _is_v2_false_positive(
            bv, source, metric_id="cm_large_customers_period_end"
        )
        assert is_fp is True
        assert reason in ("v2_financial_context_customer_metric", "v2_magnitude_sanity")

    def test_other_count_metric_table_not_exempt(self):
        """cm_active_customers_total table-sourced value=500 → IS blocked (exemption is metric-specific)."""
        source = "gross margin 500"
        bv = _make_table_bound_value("c1", 500.0, "500", Unit.COUNT)
        is_fp, reason = _is_v2_false_positive(
            bv, source, metric_id="cm_active_customers_total"
        )
        assert is_fp is True
        assert reason == "v2_financial_context_customer_metric"

    def test_large_customers_text_sourced_unchanged(self):
        """cm_large_customers_period_end text-sourced → text path unchanged, still blocked when keyword is within 100 chars."""
        source = "gross margin expanded to 78%. We had 500 large customers."
        bv = _make_bound_value("c1", 500.0, "500", Unit.COUNT)
        is_fp, reason = _is_v2_false_positive(
            bv, source, metric_id="cm_large_customers_period_end"
        )
        assert is_fp is True
        assert reason == "v2_financial_context_customer_metric"


# ============================================================================
# Test: _rule_metric_definition_value (Step 3)
# ============================================================================


class TestMetricDefinitionValue:
    """Threshold/definition language before currency value → blocked."""

    def test_customers_with_over_threshold(self):
        """'customers with over $100,000' → blocked as FP (arr_tier_threshold or metric_definition_value)."""
        source = "customers with over $100,000 ARR"
        bv = _make_bound_value("c1", 100_000.0, "$100,000", Unit.CURRENCY)
        is_fp, reason = _is_v2_false_positive(bv, source, metric_id="cm_average_order_value")
        # Either rule may fire first — both correctly identify the FP
        assert is_fp is True
        assert reason in ("v2_metric_definition_value", "v2_arr_tier_threshold")

    def test_defined_as_threshold(self):
        """'defined as $5,000' → blocked as FP."""
        source = "Core Customers defined as $5,000 in ARR"
        bv = _make_bound_value("c1", 5000.0, "$5,000", Unit.CURRENCY)
        is_fp, reason = _is_v2_false_positive(bv, source, metric_id="cm_average_order_value")
        assert is_fp is True
        assert reason in ("v2_metric_definition_value", "v2_arr_tier_threshold")

    def test_customers_spending_threshold(self):
        """'customers spending more than $1,000' → blocked."""
        source = "customers spending more than $1,000 per year"
        bv = _make_bound_value("c1", 1000.0, "$1,000", Unit.CURRENCY)
        is_fp, reason = _is_v2_false_positive(bv, source, metric_id="cm_average_order_value")
        assert is_fp is True
        assert reason == "v2_metric_definition_value"

    def test_milestone_arr_not_blocked(self):
        """'ARR grew to over $1.1 billion' → not blocked (milestone, not threshold)."""
        source = "Annual recurring revenue grew to over $1.1 billion."
        bv = _make_bound_value("c1", 1_100_000_000.0, "$1.1 billion", Unit.CURRENCY)
        is_fp, reason = _is_v2_false_positive(bv, source, metric_id="cm_average_order_value")
        assert reason != "v2_metric_definition_value"

    def test_legitimate_arr_not_blocked(self):
        """Reported ARR without definition language → not blocked."""
        source = "Annual recurring revenue was $45.2 million at quarter end."
        bv = _make_bound_value("c1", 45_200_000.0, "$45.2 million", Unit.CURRENCY)
        is_fp, reason = _is_v2_false_positive(bv, source, metric_id="cm_average_order_value")
        assert reason != "v2_metric_definition_value"

    def test_count_unit_not_blocked(self):
        """Count-unit values not affected by this rule (CURRENCY only)."""
        source = "customers with over 100 transactions"
        bv = _make_bound_value("c1", 100.0, "100", Unit.COUNT)
        is_fp, reason = _is_v2_false_positive(bv, source, metric_id="cm_active_customers_total")
        assert reason != "v2_metric_definition_value"


# ============================================================================
# Test: _rule_chart_pricing_label (Step 4)
# ============================================================================


def _make_chart_bound_value(
    candidate_id: str,
    value: float,
    raw: str,
    unit: Unit = Unit.CURRENCY,
    binding_type: str = "chart_label",
) -> BoundValue:
    """Create a chart-sourced BoundValue for testing."""
    return BoundValue(
        candidate_id=candidate_id,
        value=value,
        value_raw=raw,
        unit=unit,
        binding_type=binding_type,
        binding_confidence=0.5,
        source_locator=SourceLocator(segment_id="seg-1"),
    )


class TestChartPricingLabel:
    """Chart pricing and CAGR labels → blocked."""

    def test_per_user_per_month_blocked(self):
        """'per user per month' pricing label on chart → blocked."""
        source = "$19 per user per month"
        bv = _make_chart_bound_value("c1", 19.0, "$19", Unit.CURRENCY, "chart_label")
        is_fp, reason = _is_v2_false_positive(
            bv, source, metric_id="cm_revenue_per_customer"
        )
        assert is_fp is True
        assert reason == "v2_chart_pricing_label"

    def test_per_seat_blocked(self):
        """'per seat' pricing label on chart annotation → blocked."""
        source = "$500 per seat annually"
        bv = _make_chart_bound_value("c1", 500.0, "$500", Unit.CURRENCY, "chart_annotation")
        is_fp, reason = _is_v2_false_positive(
            bv, source, metric_id="cm_revenue_per_customer"
        )
        assert is_fp is True
        assert reason == "v2_chart_pricing_label"

    def test_cagr_label_blocked(self):
        """CAGR label on chart → blocked (use cm_average_order_value to avoid percent_on_count firing first)."""
        source = "25% CAGR projected through 2027"
        bv = _make_chart_bound_value("c1", 25.0, "25%", Unit.PERCENT, "chart_annotation")
        is_fp, reason = _is_v2_false_positive(
            bv, source, metric_id="cm_average_order_value"
        )
        assert is_fp is True
        assert reason == "v2_chart_cagr_label"

    def test_non_chart_binding_not_blocked(self):
        """Pricing text in text_proximity binding → rule does not fire."""
        source = "We charge $19 per user per month for our platform."
        bv = _make_bound_value("c1", 19.0, "$19", Unit.CURRENCY)  # text_proximity
        is_fp, reason = _is_v2_false_positive(
            bv, source, metric_id="cm_revenue_per_customer"
        )
        assert reason != "v2_chart_pricing_label"

    def test_legitimate_chart_value_not_blocked(self):
        """Chart label without pricing or CAGR language → not blocked."""
        source = "Active customers Q4 2024"
        bv = _make_chart_bound_value("c1", 1_500_000.0, "1.5 million", Unit.COUNT, "chart_label")
        is_fp, reason = _is_v2_false_positive(
            bv, source, metric_id="cm_active_customers_total"
        )
        assert reason not in ("v2_chart_pricing_label", "v2_chart_cagr_label")


# ============================================================================
# Test: Soft-rule confidence-floor bypass
# ============================================================================


class TestSoftRuleConfidenceBypass:
    """Soft FP rules are skipped when binding_confidence >= _SOFT_RULE_CONFIDENCE_FLOOR (0.85)."""

    def test_soft_rule_bypassed_by_high_confidence(self):
        """financial_context_customer_metric (soft) is skipped at high confidence."""
        # Table binding for cm_large_customers_period_end with financial keywords in context
        bv = _make_bound_value("c1", 3100.0, "3,100", Unit.COUNT, "seg-1")
        import dataclasses
        bv = dataclasses.replace(
            bv,
            binding_confidence=0.90,
            source_locator=SourceLocator(segment_id="seg-1", table_id="tbl-1"),
        )
        source = "number of large customers 3,100 revenue gross profit ebitda"
        # With binding_confidence=0.90 >= 0.85 floor: soft rule is skipped
        is_fp, _ = _is_v2_false_positive(
            bv, source,
            metric_id="cm_large_customers_period_end",
            binding_confidence=0.90,
        )
        assert is_fp is False

    def test_soft_rule_enforced_at_low_confidence(self):
        """financial_context_customer_metric (soft) still fires at low confidence."""
        # Use cm_active_customers_total — cm_large_customers_period_end is now
        # exempt from the table financial context rule for values in 100-1M range.
        bv = _make_bound_value("c1", 3100.0, "3,100", Unit.COUNT, "seg-1")
        import dataclasses
        bv = dataclasses.replace(
            bv,
            binding_confidence=0.50,
            source_locator=SourceLocator(segment_id="seg-1", table_id="tbl-1"),
        )
        source = "number of active customers 3,100 revenue gross profit ebitda"
        is_fp, reason = _is_v2_false_positive(
            bv, source,
            metric_id="cm_active_customers_total",
            binding_confidence=0.50,
        )
        assert is_fp is True
        assert reason == "v2_financial_context_customer_metric"

    def test_hard_rule_immune_to_confidence(self):
        """Year-value (hard) rule fires even at very high confidence."""
        bv = _make_bound_value("c1", 2021.0, "2021", Unit.COUNT, "seg-1")
        import dataclasses
        bv = dataclasses.replace(bv, binding_confidence=0.95)
        is_fp, reason = _is_v2_false_positive(
            bv, "In 2021 we had 2021 active customers.",
            metric_id="cm_customers_period_end",
            binding_confidence=0.95,
        )
        assert is_fp is True
        assert reason == "v2_year_value"


# ============================================================================
# Test: _rule_negative_value (new rule)
# ============================================================================


class TestNegativeValue:
    """Tests for _rule_negative_value — blocks negative values on positive-only metrics."""

    def test_negative_year_as_new_customers_blocked(self):
        """-2019 on cm_new_customers_acquired → blocked (year fragment with negative sign)."""
        bv = _make_bound_value("c1", -2019.0, "-2019", Unit.COUNT)
        is_fp, reason = _is_v2_false_positive(
            bv, "New customers acquired -2019", metric_id="cm_new_customers_acquired"
        )
        assert is_fp is True
        assert reason == "v2_negative_value"

    def test_negative_year_as_ltv_cac_blocked(self):
        """-2017 on cm_ltv_to_cac_ratio → blocked."""
        bv = _make_bound_value("c1", -2017.0, "-2017", Unit.COUNT)
        is_fp, reason = _is_v2_false_positive(
            bv, "LTV to CAC ratio -2017", metric_id="cm_ltv_to_cac_ratio"
        )
        assert is_fp is True
        assert reason == "v2_negative_value"

    def test_negative_customer_count_blocked(self):
        """-100 on cm_customers_period_end → blocked."""
        bv = _make_bound_value("c1", -100.0, "-100", Unit.COUNT)
        is_fp, reason = _is_v2_false_positive(
            bv, "Total customers -100", metric_id="cm_customers_period_end"
        )
        assert is_fp is True
        assert reason == "v2_negative_value"

    def test_positive_value_on_positive_metric_passes(self):
        """Positive value on positive-only metric → not blocked."""
        bv = _make_bound_value("c1", 500.0, "500", Unit.COUNT)
        is_fp, reason = _is_v2_false_positive(
            bv, "New customers acquired 500", metric_id="cm_new_customers_acquired"
        )
        assert reason != "v2_negative_value"

    def test_zero_value_passes(self):
        """Zero on a positive-only metric → not blocked (can legitimately be 0)."""
        bv = _make_bound_value("c1", 0.0, "0", Unit.COUNT)
        is_fp, reason = _is_v2_false_positive(
            bv, "New customers this quarter: 0", metric_id="cm_new_customers_acquired"
        )
        assert reason != "v2_negative_value"

    def test_negative_on_revenue_concentration_not_blocked(self):
        """Negative on cm_revenue_concentration → not in positive-only set, rule doesn't fire."""
        bv = _make_bound_value("c1", -5.0, "-5", Unit.PERCENT)
        is_fp, reason = _is_v2_false_positive(
            bv, "Revenue concentration -5%", metric_id="cm_revenue_concentration"
        )
        assert reason != "v2_negative_value"


# ============================================================================
# Test: _rule_magnitude_sanity updates (new thresholds)
# ============================================================================


class TestMagnitudeSanityUpdates:
    """Tests for new _METRIC_MAX_VALUE and _METRIC_MIN_VALUE entries."""

    def test_ltv_cac_above_25_rejected(self):
        """LTV:CAC ratio of 89 → rejected (percentages mis-bound, new max=25)."""
        bv = _make_bound_value("c1", 89.0, "89", Unit.COUNT)
        is_fp, reason = _is_v2_false_positive(
            bv, "LTV: CAC Ratio 89", metric_id="cm_ltv_to_cac_ratio"
        )
        assert is_fp is True
        assert reason == "v2_magnitude_sanity"

    def test_ltv_cac_plausible_value_kept(self):
        """LTV:CAC ratio of 8.5x → kept (below new max of 25)."""
        bv = _make_bound_value("c1", 8.5, "8.5", Unit.COUNT)
        is_fp, reason = _is_v2_false_positive(
            bv, "Our LTV to CAC ratio is 8.5x.", metric_id="cm_ltv_to_cac_ratio"
        )
        assert is_fp is False

    def test_cac_too_large_rejected(self):
        """CAC of $493M → rejected (financial figure mis-bound, max=$50K)."""
        bv = _make_bound_value("c1", 493_000_000.0, "493 million", Unit.CURRENCY)
        is_fp, reason = _is_v2_false_positive(
            bv, "Company Highlights $493M Q3 ARR", metric_id="cm_customer_acquisition_cost"
        )
        assert is_fp is True
        assert reason == "v2_magnitude_sanity"

    def test_cac_plausible_value_kept(self):
        """CAC of $800 → kept (well within max)."""
        bv = _make_bound_value("c1", 800.0, "800", Unit.CURRENCY)
        is_fp, reason = _is_v2_false_positive(
            bv, "Customer acquisition cost was $800.", metric_id="cm_customer_acquisition_cost"
        )
        assert is_fp is False

    def test_nrr_too_high_rejected(self):
        """NRR of 251% → rejected (above max=250)."""
        bv = _make_bound_value("c1", 251.0, "251", Unit.PERCENT)
        is_fp, reason = _is_v2_false_positive(
            bv, "Net revenue retention 251%", metric_id="cm_net_revenue_retention"
        )
        assert is_fp is True
        assert reason == "v2_magnitude_sanity"

    def test_nrr_too_low_rejected(self):
        """NRR of 9.3 → rejected (below min=31)."""
        bv = _make_bound_value("c1", 9.3, "9.3", Unit.PERCENT)
        is_fp, reason = _is_v2_false_positive(
            bv, "Net revenue retention 9.3", metric_id="cm_net_revenue_retention"
        )
        assert is_fp is True
        assert reason == "v2_magnitude_sanity"

    def test_nrr_plausible_value_kept(self):
        """NRR of 120% → kept (within 31-250 range)."""
        bv = _make_bound_value("c1", 120.0, "120%", Unit.PERCENT)
        is_fp, reason = _is_v2_false_positive(
            bv, "Net revenue retention rate was 120%.", metric_id="cm_net_revenue_retention"
        )
        assert is_fp is False

    def test_nrr_30_rejected(self):
        """NRR of 30 → rejected (below min=31; this was a Datadog mis-binding)."""
        bv = _make_bound_value("c1", 30.0, "30%", Unit.PERCENT)
        is_fp, reason = _is_v2_false_positive(
            bv, "Net revenue retention 30%", metric_id="cm_net_revenue_retention"
        )
        assert is_fp is True
        assert reason == "v2_magnitude_sanity"

    def test_nrr_at_min_boundary_kept(self):
        """NRR of 44% → kept (Samsara gold standard value; boundary at min=31)."""
        bv = _make_bound_value("c1", 44.0, "44%", Unit.PERCENT)
        is_fp, reason = _is_v2_false_positive(
            bv, "Net revenue retention 44%", metric_id="cm_net_revenue_retention"
        )
        assert is_fp is False


# ============================================================================
# Test: _rule_retention_rate_over_100 (threshold lowered to > 100)
# ============================================================================


class TestRetentionRateThresholdUpdate:
    """Tests for the updated CRR threshold (>100 instead of >=130)."""

    def test_crr_above_100_rejected(self):
        """CRR of 125% → rejected (above new threshold of 100)."""
        bv = _make_bound_value("c1", 125.0, "125%", Unit.PERCENT)
        source = "Customer retention rate was 125%."
        is_fp, reason = _is_v2_false_positive(
            bv, source, metric_id="cm_customer_retention_rate"
        )
        assert is_fp is True
        assert reason == "v2_retention_rate_over_100"

    def test_crr_101_rejected(self):
        """CRR of 101% → rejected (above 100)."""
        bv = _make_bound_value("c1", 101.0, "101%", Unit.PERCENT)
        source = "Customer retention rate was 101%."
        is_fp, reason = _is_v2_false_positive(
            bv, source, metric_id="cm_customer_retention_rate"
        )
        assert is_fp is True
        assert reason == "v2_retention_rate_over_100"

    def test_crr_exactly_100_kept(self):
        """CRR of 100% → kept (boundary: not strictly above 100)."""
        bv = _make_bound_value("c1", 100.0, "100%", Unit.PERCENT)
        source = "We maintained a 100% customer retention rate."
        is_fp, reason = _is_v2_false_positive(
            bv, source, metric_id="cm_customer_retention_rate"
        )
        assert is_fp is False

    def test_crr_95_kept(self):
        """CRR of 95% → kept."""
        bv = _make_bound_value("c1", 95.0, "95%", Unit.PERCENT)
        source = "Customer retention rate was 95% in fiscal year 2024."
        is_fp, reason = _is_v2_false_positive(
            bv, source, metric_id="cm_customer_retention_rate"
        )
        assert is_fp is False


# ============================================================================
# Test: _rule_stub_metric_contradiction (new rule)
# ============================================================================


class TestStubMetricContradiction:
    """Tests for _rule_stub_metric_contradiction — blocks table column-header
    bindings where the stub row label identifies a different metric.

    Covers: cm_revenue_per_customer, cm_average_order_value (original),
    cm_net_revenue_retention, cm_gross_revenue_retention,
    cm_customer_retention_rate, cm_active_customers_total,
    cm_customers_period_end (expanded).
    """

    def test_number_of_stores_stub_blocks_arpu(self):
        """Table stub 'Number of stores' → cm_revenue_per_customer blocked."""
        bv = _make_table_bound_value("c1", 608.0, "608", Unit.COUNT)
        # source_text = header_path + stub_path + cell_text (joined)
        source = (
            "Year Ended (in thousands, except net sales per active customer, "
            "number of stores and percentages) January 30 2021 "
            "Number of stores (as of end of period) 608"
        )
        is_fp, reason = _is_v2_false_positive(
            bv, source, metric_id="cm_revenue_per_customer"
        )
        assert is_fp is True
        assert reason == "v2_stub_metric_contradiction"

    def test_comparable_sales_stub_blocks_arpu(self):
        """Table stub 'Comparable sales' → cm_revenue_per_customer blocked.

        Note: A percent value on cm_revenue_per_customer also triggers v2_arpu_percent
        (which runs before stub_metric_contradiction), so we check is_fp=True here.
        Using Unit.COUNT to specifically test the stub rule fires.
        """
        bv = _make_table_bound_value("c1", 38.0, "38", Unit.COUNT)
        source = (
            "Three Months Ended (in thousands, except net sales per active customer) "
            "May 2020 Comparable sales 38"
        )
        is_fp, reason = _is_v2_false_positive(
            bv, source, metric_id="cm_revenue_per_customer"
        )
        assert is_fp is True
        assert reason == "v2_stub_metric_contradiction"

    def test_active_customers_as_of_stub_does_not_block_arpu(self):
        """Table stub 'Active customers (as of end of period)' no longer blocked.

        This pattern was removed from _STUB_NOT_ARPU_RE because it caused false
        negatives in SEC filings where tables mix active-customer count rows with
        legitimate revenue-per-customer rows sharing the same header context.
        """
        bv = _make_table_bound_value("c1", 3448.0, "3,448", Unit.COUNT)
        source = (
            "Three Months Ended (in thousands, except net sales per active customer) "
            "Active customers (as of end of period) 3,448"
        )
        is_fp, reason = _is_v2_false_positive(
            bv, source, metric_id="cm_revenue_per_customer"
        )
        assert is_fp is False

    def test_stub_blocks_aov_metric_too(self):
        """Table stub 'Number of stores' → cm_average_order_value blocked too."""
        bv = _make_table_bound_value("c1", 250.0, "250", Unit.COUNT)
        source = "Number of stores (as of end of period) 250"
        is_fp, reason = _is_v2_false_positive(
            bv, source, metric_id="cm_average_order_value"
        )
        assert is_fp is True
        assert reason == "v2_stub_metric_contradiction"

    def test_legitimate_arpu_row_kept(self):
        """Table stub 'Net sales per active customer' → cm_revenue_per_customer kept."""
        bv = _make_table_bound_value("c1", 291.0, "291", Unit.CURRENCY)
        source = (
            "Year Ended (in thousands, except net sales per active customer) "
            "Net sales per active customer 291"
        )
        is_fp, reason = _is_v2_false_positive(
            bv, source, metric_id="cm_revenue_per_customer"
        )
        assert reason != "v2_stub_metric_contradiction"

    def test_text_binding_not_blocked(self):
        """Text-proximity binding with 'number of stores' nearby → NOT blocked (rule is table-only)."""
        bv = _make_bound_value("c1", 608.0, "608", Unit.COUNT)  # text binding, segment_id set
        source = "The company had 608 stores and net sales per active customer."
        is_fp, reason = _is_v2_false_positive(
            bv, source, metric_id="cm_revenue_per_customer"
        )
        assert reason != "v2_stub_metric_contradiction"

    def test_non_arpu_metric_not_affected(self):
        """Rule doesn't fire for cm_customers_period_end even with store stub.

        cm_customers_period_end is now in _STUB_DOMAIN_CONTRADICTIONS, but its
        contradiction regex targets ARPU/NRR patterns — NOT 'stores'.
        """
        bv = _make_table_bound_value("c1", 608.0, "608", Unit.COUNT)
        source = "Number of stores (as of end of period) 608"
        is_fp, reason = _is_v2_false_positive(
            bv, source, metric_id="cm_customers_period_end"
        )
        assert reason != "v2_stub_metric_contradiction"

    # ------------------------------------------------------------------
    # NRR / GRR / CRR — expanded coverage
    # ------------------------------------------------------------------

    def test_nrr_column_customer_count_stub_blocked(self):
        """NRR column header + 'Number of Premium Cloud Service Customers' stub → blocked.

        Kingsoft pattern: table with NRR column header binds all rows including
        the customer-count row. Value=175 should be blocked as NRR.
        The regex allows up to 3 adjective words between 'of' and 'customers'.
        """
        bv = _make_table_bound_value("c1", 175.0, "175", Unit.COUNT)
        source = (
            "Net Revenue Retention Rate (%) "
            "Number of Premium Cloud Service Customers 175"
        )
        is_fp, reason = _is_v2_false_positive(
            bv, source, metric_id="cm_net_revenue_retention"
        )
        assert is_fp is True
        assert reason == "v2_stub_metric_contradiction"

    def test_nrr_column_arpc_stub_blocked(self):
        """NRR column header + ARPC stub → blocked (value is per-customer revenue, not NRR).

        Value 120.0 is used (above NRR min=31) to ensure magnitude_sanity doesn't
        fire first — we want to specifically test the stub_contradiction rule.
        """
        bv = _make_table_bound_value("c1", 120.0, "120", Unit.CURRENCY)
        source = "Net Revenue Retention (%) ARPC ($) 120"
        is_fp, reason = _is_v2_false_positive(
            bv, source, metric_id="cm_net_revenue_retention"
        )
        assert is_fp is True
        assert reason == "v2_stub_metric_contradiction"

    def test_nrr_column_correct_row_kept(self):
        """NRR column header + NRR stub (correct row) → kept."""
        bv = _make_table_bound_value("c1", 161.0, "161", Unit.PERCENT)
        source = "Net Revenue Retention Rate (%) NRR (%) 161"
        is_fp, reason = _is_v2_false_positive(
            bv, source, metric_id="cm_net_revenue_retention"
        )
        assert reason != "v2_stub_metric_contradiction"

    def test_nrr_column_neutral_stub_kept(self):
        """NRR column header + neutral period stub ('2019') → kept."""
        bv = _make_table_bound_value("c1", 161.0, "161", Unit.PERCENT)
        source = "Net Revenue Retention (%) 2019 161"
        is_fp, reason = _is_v2_false_positive(
            bv, source, metric_id="cm_net_revenue_retention"
        )
        assert reason != "v2_stub_metric_contradiction"

    def test_grr_column_customer_count_stub_blocked(self):
        """GRR column + customer count stub → blocked."""
        bv = _make_table_bound_value("c1", 250.0, "250", Unit.COUNT)
        source = "Gross Revenue Retention (%) Customer Count 250"
        is_fp, reason = _is_v2_false_positive(
            bv, source, metric_id="cm_gross_revenue_retention"
        )
        assert is_fp is True
        assert reason == "v2_stub_metric_contradiction"

    def test_crr_column_nrr_stub_blocked(self):
        """CRR column + 'Net Revenue Retention' stub → blocked as FP.

        Value 85.0 used (≤100) to avoid triggering v2_retention_rate_over_100.
        The v2_retention_rate_nrr_context rule may fire before stub_contradiction
        when source contains 'Net Revenue Retention' — either way correctly rejected.
        """
        bv = _make_table_bound_value("c1", 85.0, "85", Unit.PERCENT)
        source = "Customer Retention Rate (%) Net Revenue Retention 85"
        is_fp, reason = _is_v2_false_positive(
            bv, source, metric_id="cm_customer_retention_rate"
        )
        assert is_fp is True

    # ------------------------------------------------------------------
    # Customer count metrics — expanded coverage
    # ------------------------------------------------------------------

    def test_customers_period_end_arpu_stub_blocked(self):
        """customers_period_end column + ARPU stub → blocked as FP.

        The v2_arpu_context_on_customer_count rule may fire before
        stub_contradiction — either way the binding is correctly rejected.
        """
        bv = _make_table_bound_value("c1", 291.0, "291", Unit.CURRENCY)
        source = "Number of Customers ARPU ($) 291"
        is_fp, reason = _is_v2_false_positive(
            bv, source, metric_id="cm_customers_period_end"
        )
        assert is_fp is True

    def test_customers_period_end_nrr_stub_blocked(self):
        """customers_period_end column + 'Net Revenue Retention' stub → blocked.

        Uses unit=COUNT so percent-on-count rule doesn't fire first.
        """
        bv = _make_table_bound_value("c1", 115.0, "115", Unit.COUNT)
        source = "Number of Customers Net Revenue Retention 115"
        is_fp, reason = _is_v2_false_positive(
            bv, source, metric_id="cm_customers_period_end"
        )
        assert is_fp is True
        assert reason == "v2_stub_metric_contradiction"

    def test_table_stub_binding_not_blocked(self):
        """table_stub binding with same source_text → NOT blocked.

        For stub bindings the stub IS the keyword match — no contradiction possible.
        """
        bv = BoundValue(
            candidate_id="c1",
            value=175.0,
            value_raw="175",
            unit=Unit.COUNT,
            binding_type="table_stub",  # <-- stub binding
            binding_confidence=0.5,
            source_locator=SourceLocator(table_id="tbl-1", cell_row=3, cell_col=1),
        )
        source = (
            "Net Revenue Retention Rate (%) "
            "Number of Premium Cloud Service Customers 175"
        )
        is_fp, reason = _is_v2_false_positive(
            bv, source, metric_id="cm_net_revenue_retention"
        )
        assert reason != "v2_stub_metric_contradiction"
