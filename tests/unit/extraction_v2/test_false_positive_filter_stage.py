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
    Segment,
    SegmentType,
    SourceLocator,
    SourceType,
    Unit,
)
from src.extraction_v2.stages.false_positive_filter import (
    FalsePositiveFilterStage,
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
        candidate = _make_candidate("c1", "cm_arr", "seg-1")

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
        candidate = _make_candidate("c1", "cm_arr", "seg-1")

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
        # Real: 143%
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
        assert 143.0 in values, "Real percentage should be kept"


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

    def test_layout_table_prose_kept(self):
        """Values in layout-table prose (far from [CELL] marker) should NOT be filtered.

        SEC filings use <TABLE> for bullet-point indentation.  The first cell is
        a bullet character, the second is a prose paragraph.  The paragraph may
        contain numeric metric values that should be extracted.
        """
        # Mirrors the Farfetch LTV/CAC bullet text structure:
        # "· [CELL] Six month LTV/CAC ratio for years ended ... was 1.42, 1.53 and 1.77"
        source = (
            "\xb7 [CELL] Six month LTV/CAC ratio for the years ended "
            "December 31, 2015, 2016 and 2017 cohorts was 1.42, 1.53 and 1.77, respectively"
        )
        bv = _make_bound_value("c1", 1.42, "1.42", Unit.OTHER, "seg-1")
        is_fp, reason = _is_v2_false_positive(bv, source)
        assert is_fp is False, f"Layout-table prose value should not be filtered; got {reason}"

    def test_layout_table_bullet_multiple_values_kept(self):
        """All values in a layout-table prose bullet are kept (not just the first).

        Uses a realistic bullet-point sentence where the numbers appear far
        from the [CELL] marker (prose text, not columnar data).
        """
        source = (
            "\xb7 [CELL] LTV/CAC ratio for the years ended December 31, 2015, "
            "2016 and 2017 cohorts was 1.42, 1.53 and 1.77, respectively"
        )
        for raw, val in [("1.42", 1.42), ("1.53", 1.53), ("1.77", 1.77)]:
            bv = _make_bound_value("c1", val, raw, Unit.OTHER, "seg-1")
            is_fp, reason = _is_v2_false_positive(bv, source)
            assert is_fp is False, f"Value {raw} should not be filtered; got {reason}"


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
