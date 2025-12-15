"""
Unit tests for false_positive_filter module.

Tests extracted from test_candidate_generator.py as part of P1.3 module splitting.
"""

from decimal import Decimal
import pytest

from src.review.false_positive_filter import (
    DATE_CONTEXT_PATTERNS,
    FALSE_POSITIVE_CONTEXT_PATTERNS,
    FalsePositiveFilter,
    MIN_METRIC_VALUE,
    TOC_PROXIMITY_CHARS,
    YEAR_MIN,
    YEAR_MAX,
    is_near_table_of_contents,
    is_toc_page_reference,
)
from src.review.number_parsing import NumberMatch


# =============================================================================
# FalsePositiveFilter.is_false_positive Tests
# =============================================================================


class TestIsFalsePositive:
    """Tests for the FalsePositiveFilter.is_false_positive method."""

    @pytest.fixture
    def filter(self):
        """Create a FalsePositiveFilter instance."""
        return FalsePositiveFilter()

    def test_returns_tuple(self, filter):
        """Method should return (bool, reason) tuple."""
        number = NumberMatch(
            start=0, end=5, raw_text="50000", value=Decimal("50000"), unit="count"
        )
        result = filter.is_false_positive("50000 customers", number)
        assert isinstance(result, tuple)
        assert len(result) == 2

    def test_below_min_value_reason(self, filter):
        """Should return 'below_min_value' reason for small integers."""
        number = NumberMatch(
            start=0, end=1, raw_text="5", value=Decimal("5"), unit="count"
        )
        is_fp, reason = filter.is_false_positive("5 customers", number)
        assert is_fp is True
        assert reason == "below_min_value"

    def test_likely_year_reason(self, filter):
        """Should return 'likely_year' reason for year values."""
        number = NumberMatch(
            start=3, end=7, raw_text="2023", value=Decimal("2023"), unit="count"
        )
        is_fp, reason = filter.is_false_positive("In 2023 we had", number)
        assert is_fp is True
        assert reason == "likely_year"

    def test_part_of_date_reason(self, filter):
        """Should return 'part_of_date' reason for date components."""
        text = "As of 12/31/2023"
        # The "12" part
        number = NumberMatch(
            start=6, end=8, raw_text="12", value=Decimal("12"), unit="count"
        )
        is_fp, reason = filter.is_false_positive(text, number)
        assert is_fp is True
        assert reason == "part_of_date"

    def test_reference_number_reason(self, filter):
        """Should return 'reference_number' reason for page/note refs."""
        text = "See page 123 for details"
        number = NumberMatch(
            start=9, end=12, raw_text="123", value=Decimal("123"), unit="count"
        )
        is_fp, reason = filter.is_false_positive(text, number)
        assert is_fp is True
        assert reason == "reference_number"

    def test_not_false_positive_returns_none_reason(self, filter):
        """Should return (False, None) for valid metrics."""
        number = NumberMatch(
            start=8, end=14, raw_text="50,000", value=Decimal("50000"), unit="count"
        )
        is_fp, reason = filter.is_false_positive(
            "We have 50,000 customers", number
        )
        assert is_fp is False
        assert reason is None

    def test_filter_disabled(self):
        """When filter_enabled=False, should always return (False, None)."""
        filter_disabled = FalsePositiveFilter(filter_enabled=False)

        # Small number
        number = NumberMatch(
            start=0, end=1, raw_text="5", value=Decimal("5"), unit="count"
        )
        is_fp, reason = filter_disabled.is_false_positive("5 customers", number)
        assert is_fp is False
        assert reason is None

        # Year
        number = NumberMatch(
            start=3, end=7, raw_text="2023", value=Decimal("2023"), unit="count"
        )
        is_fp, reason = filter_disabled.is_false_positive("In 2023 we had", number)
        assert is_fp is False
        assert reason is None

    def test_custom_min_value(self):
        """Should respect custom min_value threshold."""
        filter_strict = FalsePositiveFilter(min_value=100)

        # 50 should be filtered with min_value=100
        number = NumberMatch(
            start=8, end=10, raw_text="50", value=Decimal("50"), unit="count"
        )
        is_fp, reason = filter_strict.is_false_positive("We have 50 customers", number)
        assert is_fp is True
        assert reason == "below_min_value"

    def test_years_filtering_disabled(self):
        """When filter_years=False, should not filter years."""
        filter_no_years = FalsePositiveFilter(filter_years=False)

        number = NumberMatch(
            start=3, end=7, raw_text="2023", value=Decimal("2023"), unit="count"
        )
        is_fp, reason = filter_no_years.is_false_positive("In 2023 we had", number)
        # Should not be filtered as a year
        assert is_fp is False
        assert reason is None

    def test_decimal_not_filtered_by_min_value(self, filter):
        """Decimal numbers should not be filtered by min_value."""
        # 1.25 is below MIN_METRIC_VALUE (10) but should not be filtered
        # because it has a decimal point (could be a ratio like 125%)
        number = NumberMatch(
            start=17, end=21, raw_text="1.25", value=Decimal("1.25"), unit="count"
        )
        is_fp, reason = filter.is_false_positive(
            "Our NRR was about 1.25 times last year", number
        )
        assert is_fp is False
        assert reason is None

    def test_percentage_not_filtered_by_min_value(self, filter):
        """Percentage numbers should not be filtered by min_value."""
        # 5% is below MIN_METRIC_VALUE (10) but should not be filtered
        # because it's a percentage unit
        number = NumberMatch(
            start=20, end=22, raw_text="5%", value=Decimal("0.05"), unit="%"
        )
        is_fp, reason = filter.is_false_positive(
            "Our churn rate was 5% last quarter", number
        )
        assert is_fp is False
        assert reason is None

    def test_currency_not_filtered_by_min_value(self, filter):
        """Currency numbers should not be filtered by min_value."""
        # $5 is below MIN_METRIC_VALUE (10) but should not be filtered
        # because it has currency unit
        number = NumberMatch(
            start=16, end=18, raw_text="$5", value=Decimal("5"), unit="usd"
        )
        is_fp, reason = filter.is_false_positive(
            "Average AOV was $5 per transaction", number
        )
        assert is_fp is False
        assert reason is None


# =============================================================================
# Table of Contents Filtering Tests
# =============================================================================


class TestTableOfContentsFiltering:
    """Tests for Table of Contents false positive detection."""

    @pytest.fixture
    def filter(self):
        """Create a FalsePositiveFilter instance."""
        return FalsePositiveFilter()

    def test_filters_numbers_near_toc_header(self, filter):
        """Should filter numbers appearing near 'TABLE OF CONTENTS' header."""
        text = "TABLE OF CONTENTS\nRisk Factors...12"
        number = NumberMatch(
            start=text.find("12"),
            end=text.find("12") + 2,
            raw_text="12",
            value=Decimal("12"),
            unit="count",
        )
        is_fp, reason = filter.is_false_positive(text, number)
        assert is_fp is True
        assert reason == "toc_proximity"

    def test_filters_dot_leader_page_references(self, filter):
        """Should filter numbers preceded by dot leaders (TOC page refs)."""
        text = "Business Overview.........15"
        number = NumberMatch(
            start=text.find("15"),
            end=text.find("15") + 2,
            raw_text="15",
            value=Decimal("15"),
            unit="count",
        )
        is_fp, reason = filter.is_false_positive(text, number)
        assert is_fp is True
        assert reason == "toc_page_reference"

    def test_filters_multiple_dot_patterns(self, filter):
        """Should filter various dot leader patterns."""
        # Three dots (minimum)
        text1 = "Risk Factors...23"
        number1 = NumberMatch(
            start=text1.find("23"),
            end=text1.find("23") + 2,
            raw_text="23",
            value=Decimal("23"),
            unit="count",
        )
        is_fp1, reason1 = filter.is_false_positive(text1, number1)
        assert is_fp1 is True
        assert reason1 == "toc_page_reference"

        # Many dots with spaces
        text2 = "Item 1A. Risk Factors........ 45"
        number2 = NumberMatch(
            start=text2.find("45"),
            end=text2.find("45") + 2,
            raw_text="45",
            value=Decimal("45"),
            unit="count",
        )
        is_fp2, reason2 = filter.is_false_positive(text2, number2)
        assert is_fp2 is True
        assert reason2 == "toc_page_reference"

    def test_does_not_filter_toc_unrelated_numbers(self, filter):
        """Should NOT filter numbers unrelated to TOC."""
        text = "We had 12 million customers in the quarter"
        number = NumberMatch(
            start=text.find("12"),
            end=text.find("12") + 2,
            raw_text="12",
            value=Decimal("12"),
            unit="count",
        )
        is_fp, reason = filter.is_false_positive(text, number)
        # Should be filtered for being below min_value (12 > 10, so not filtered by min)
        # But should NOT be filtered by TOC checks
        assert reason != "toc_proximity"
        assert reason != "toc_page_reference"

    def test_case_insensitivity(self, filter):
        """Should detect TOC headers case-insensitively."""
        # Lowercase
        text1 = "table of contents\nBusiness...12"
        number1 = NumberMatch(
            start=text1.find("12"),
            end=text1.find("12") + 2,
            raw_text="12",
            value=Decimal("12"),
            unit="count",
        )
        is_fp1, reason1 = filter.is_false_positive(text1, number1)
        assert is_fp1 is True
        assert reason1 == "toc_proximity"

        # Mixed case
        text2 = "Table Of Contents\nRisk Factors...23"
        number2 = NumberMatch(
            start=text2.find("23"),
            end=text2.find("23") + 2,
            raw_text="23",
            value=Decimal("23"),
            unit="count",
        )
        is_fp2, reason2 = filter.is_false_positive(text2, number2)
        assert is_fp2 is True
        assert reason2 == "toc_proximity"

    def test_toc_proximity_boundary(self, filter):
        """Should respect TOC_PROXIMITY_CHARS distance threshold."""
        # Create text with TOC header exactly TOC_PROXIMITY_CHARS chars before number
        toc_header = "TABLE OF CONTENTS\n"
        # Fill with filler text to reach exactly the boundary
        filler_needed = TOC_PROXIMITY_CHARS - len(toc_header)
        filler = "x" * filler_needed
        number_text = "12"

        # At boundary (should filter)
        text_at_boundary = toc_header + filler + number_text
        number_at = NumberMatch(
            start=len(toc_header) + filler_needed,
            end=len(toc_header) + filler_needed + 2,
            raw_text="12",
            value=Decimal("12"),
            unit="count",
        )
        is_fp_at, reason_at = filter.is_false_positive(text_at_boundary, number_at)
        assert is_fp_at is True
        assert reason_at == "toc_proximity"

        # Beyond boundary (should NOT filter by TOC proximity)
        filler_beyond = "x" * (filler_needed + 1)
        text_beyond = toc_header + filler_beyond + number_text
        number_beyond = NumberMatch(
            start=len(toc_header) + len(filler_beyond),
            end=len(toc_header) + len(filler_beyond) + 2,
            raw_text="12",
            value=Decimal("12"),
            unit="count",
        )
        is_fp_beyond, reason_beyond = filter.is_false_positive(text_beyond, number_beyond)
        # Should not be filtered by toc_proximity (beyond threshold)
        assert reason_beyond != "toc_proximity"

    def test_preserves_existing_filter_behavior(self, filter):
        """Should not break existing false positive checks."""
        # Test year filtering still works
        text_year = "In 2023 we had revenue"
        number_year = NumberMatch(
            start=text_year.find("2023"),
            end=text_year.find("2023") + 4,
            raw_text="2023",
            value=Decimal("2023"),
            unit="count",
        )
        is_fp_year, reason_year = filter.is_false_positive(text_year, number_year)
        assert is_fp_year is True
        assert reason_year == "likely_year"

        # Test date filtering still works
        text_date = "As of 12/31/2023"
        number_date = NumberMatch(
            start=text_date.find("12"),
            end=text_date.find("12") + 2,
            raw_text="12",
            value=Decimal("12"),
            unit="count",
        )
        is_fp_date, reason_date = filter.is_false_positive(text_date, number_date)
        assert is_fp_date is True
        assert reason_date == "part_of_date"

        # Test page reference filtering still works
        text_page = "See page 123 for details"
        number_page = NumberMatch(
            start=text_page.find("123"),
            end=text_page.find("123") + 3,
            raw_text="123",
            value=Decimal("123"),
            unit="count",
        )
        is_fp_page, reason_page = filter.is_false_positive(text_page, number_page)
        assert is_fp_page is True
        assert reason_page == "reference_number"


# =============================================================================
# Helper Function Tests
# =============================================================================


class TestHelperFunctions:
    """Tests for TOC detection helper functions."""

    def test_is_near_table_of_contents_positive(self):
        """Should return True when TOC header is within proximity."""
        text = "TABLE OF CONTENTS\nRisk Factors...12"
        position = text.find("12")
        assert is_near_table_of_contents(text, position) is True

    def test_is_near_table_of_contents_negative(self):
        """Should return False when no TOC header nearby."""
        text = "We had 12 million customers"
        position = text.find("12")
        assert is_near_table_of_contents(text, position) is False

    def test_is_near_table_of_contents_case_insensitive(self):
        """Should detect TOC header regardless of case."""
        text = "table of contents\nSection 1...5"
        position = text.find("5")
        assert is_near_table_of_contents(text, position) is True

    def test_is_toc_page_reference_positive(self):
        """Should return True for dot leader patterns."""
        text = "Business Overview.........15"
        position = text.find("15")
        assert is_toc_page_reference(text, position) is True

    def test_is_toc_page_reference_negative(self):
        """Should return False when no dot leaders present."""
        text = "We had 12 million customers"
        position = text.find("12")
        assert is_toc_page_reference(text, position) is False

    def test_is_toc_page_reference_minimum_dots(self):
        """Should require at least 3 dots to match."""
        # Two dots - should NOT match
        text1 = "Section..5"
        position1 = text1.find("5")
        assert is_toc_page_reference(text1, position1) is False

        # Three dots - should match
        text2 = "Section...5"
        position2 = text2.find("5")
        assert is_toc_page_reference(text2, position2) is True


# =============================================================================
# Constants Tests
# =============================================================================


class TestConstants:
    """Tests for module constants."""

    def test_date_context_patterns_not_empty(self):
        """DATE_CONTEXT_PATTERNS should contain patterns."""
        assert len(DATE_CONTEXT_PATTERNS) > 0
        # Check that all patterns are compiled
        for pattern in DATE_CONTEXT_PATTERNS:
            assert hasattr(pattern, 'search')

    def test_false_positive_context_patterns_not_empty(self):
        """FALSE_POSITIVE_CONTEXT_PATTERNS should not be empty."""
        assert len(FALSE_POSITIVE_CONTEXT_PATTERNS) > 0
        # Check that all patterns are compiled
        for pattern in FALSE_POSITIVE_CONTEXT_PATTERNS:
            assert hasattr(pattern, 'search')

    def test_year_range_constants(self):
        """YEAR_MIN and YEAR_MAX should be sensible."""
        assert YEAR_MIN == 1990
        assert YEAR_MAX == 2100
        assert YEAR_MIN < YEAR_MAX

    def test_min_metric_value_constant(self):
        """MIN_METRIC_VALUE should be positive."""
        assert MIN_METRIC_VALUE == 10
        assert MIN_METRIC_VALUE > 0
