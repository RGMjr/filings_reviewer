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
    YEAR_MIN,
    YEAR_MAX,
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
