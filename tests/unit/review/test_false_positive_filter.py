"""
Unit tests for false_positive_filter module.

Tests extracted from test_candidate_generator.py as part of P1.3 module splitting.
"""

from decimal import Decimal

import pytest

from src.review.false_positive_filter import (
    DATE_CONTEXT_PATTERNS,
    FALSE_POSITIVE_CONTEXT_PATTERNS,
    MIN_METRIC_VALUE,
    TOC_DOT_LEADER_WINDOW,
    TOC_HEADERS,
    TOC_PROXIMITY_CHARS,
    YEAR_MAX,
    YEAR_MIN,
    FalsePositiveFilter,
    is_near_table_of_contents,
    is_spelled_out_number,
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
# Label-Embedded Value Filtering Tests (CMS-2)
# =============================================================================


class TestLabelEmbeddedValueFiltering:
    """Tests for filtering numbers that are part of metric label thresholds.

    Example: "Paid Customers > $100,000" - the $100,000 is part of the label,
    not an actual metric value to extract.
    """

    @pytest.fixture
    def filter(self):
        """Create a FalsePositiveFilter instance."""
        return FalsePositiveFilter()

    def test_filters_threshold_with_greater_than(self, filter):
        """Should filter numbers following > operator."""
        text = "Paid Customers > $100,000 grew to 500"
        number = NumberMatch(
            start=text.find("100,000"),
            end=text.find("100,000") + 7,
            raw_text="100,000",
            value=Decimal("100000"),
            unit="usd",
        )
        is_fp, reason = filter.is_false_positive(text, number)
        assert is_fp is True
        assert reason == "label_embedded_value"

    def test_filters_threshold_with_greater_equal(self, filter):
        """Should filter numbers following >= operator."""
        text = "ARR >= $50M is our target"
        number = NumberMatch(
            start=text.find("50"),
            end=text.find("50") + 2,
            raw_text="50",
            value=Decimal("50"),
            unit="usd",
        )
        is_fp, reason = filter.is_false_positive(text, number)
        assert is_fp is True
        assert reason == "label_embedded_value"

    def test_filters_threshold_with_less_than(self, filter):
        """Should filter numbers following < operator."""
        text = "Customers < $1000 are considered small"
        number = NumberMatch(
            start=text.find("1000"),
            end=text.find("1000") + 4,
            raw_text="1000",
            value=Decimal("1000"),
            unit="usd",
        )
        is_fp, reason = filter.is_false_positive(text, number)
        assert is_fp is True
        assert reason == "label_embedded_value"

    def test_filters_unicode_comparison_operators(self, filter):
        """Should filter numbers following unicode operators (≥, ≤)."""
        text = "Enterprise customers ≥ $100K annually"
        number = NumberMatch(
            start=text.find("100"),
            end=text.find("100") + 3,
            raw_text="100",
            value=Decimal("100"),
            unit="usd",
        )
        is_fp, reason = filter.is_false_positive(text, number)
        assert is_fp is True
        assert reason == "label_embedded_value"

    def test_does_not_filter_standalone_currency(self, filter):
        """Should NOT filter currency without comparison operator."""
        text = "We earned $100,000 in revenue"
        number = NumberMatch(
            start=text.find("100,000"),
            end=text.find("100,000") + 7,
            raw_text="100,000",
            value=Decimal("100000"),
            unit="usd",
        )
        is_fp, reason = filter.is_false_positive(text, number)
        assert is_fp is False
        assert reason is None

    def test_does_not_filter_plain_number(self, filter):
        """Should NOT filter plain numbers without comparison operator."""
        text = "We had 100000 customers"
        number = NumberMatch(
            start=text.find("100000"),
            end=text.find("100000") + 6,
            raw_text="100000",
            value=Decimal("100000"),
            unit="count",
        )
        is_fp, reason = filter.is_false_positive(text, number)
        assert is_fp is False
        assert reason is None

    def test_real_world_slack_example(self, filter):
        """Real-world example from Slack S-1: Paid Customers > $100,000."""
        text = "We have 500 Paid Customers > $100,000 in annual contract value"
        # The $100,000 should be filtered
        threshold_number = NumberMatch(
            start=text.find("100,000"),
            end=text.find("100,000") + 7,
            raw_text="100,000",
            value=Decimal("100000"),
            unit="usd",
        )
        is_fp, reason = filter.is_false_positive(text, threshold_number)
        assert is_fp is True
        assert reason == "label_embedded_value"

        # The 500 should NOT be filtered
        count_number = NumberMatch(
            start=text.find("500"),
            end=text.find("500") + 3,
            raw_text="500",
            value=Decimal("500"),
            unit="count",
        )
        is_fp, reason = filter.is_false_positive(text, count_number)
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
        """Should filter numbers preceded by dot leaders (TOC page refs).

        L2-P1.1: Now requires TOC context (header or section heading).
        """
        # Add TOC header to provide context
        text = "TABLE OF CONTENTS\nBusiness Overview.........15"
        number = NumberMatch(
            start=text.find("15"),
            end=text.find("15") + 2,
            raw_text="15",
            value=Decimal("15"),
            unit="count",
        )
        is_fp, reason = filter.is_false_positive(text, number)
        assert is_fp is True
        assert reason in ("toc_proximity", "toc_page_reference")

    def test_filters_multiple_dot_patterns(self, filter):
        """Should filter various dot leader patterns.

        L2-P1.1: Now requires TOC context (section heading pattern).
        """
        # Three dots (minimum) with section heading pattern
        text1 = "Item 1. Risk Factors...23"
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

        # Many dots with spaces (section heading provides context)
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
        # Fill with filler text to reach within the boundary
        filler_within = "x" * (TOC_PROXIMITY_CHARS - len(toc_header) - 1)
        number_text = "12"

        # Within boundary (should filter)
        text_within = toc_header + filler_within + number_text
        number_within = NumberMatch(
            start=len(toc_header) + len(filler_within),
            end=len(toc_header) + len(filler_within) + 2,
            raw_text="12",
            value=Decimal("12"),
            unit="count",
        )
        is_fp_within, reason_within = filter.is_false_positive(text_within, number_within)
        assert is_fp_within is True
        assert reason_within == "toc_proximity"

        # Well beyond boundary (should NOT filter by TOC proximity)
        # Use a larger number (50) to avoid below_min_value filter
        filler_beyond = "x" * (TOC_PROXIMITY_CHARS + 50)
        number_text_large = "50"
        text_beyond = toc_header + filler_beyond + number_text_large
        number_beyond = NumberMatch(
            start=len(toc_header) + len(filler_beyond),
            end=len(toc_header) + len(filler_beyond) + 2,
            raw_text="50",
            value=Decimal("50"),
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
        """Should return True for dot leader patterns with TOC context.

        L2-P1.1: Now requires TOC context (header or section heading).
        """
        text = "TABLE OF CONTENTS\nBusiness Overview.........15"
        position = text.find("15")
        assert is_toc_page_reference(text, position) is True

    def test_is_toc_page_reference_negative(self):
        """Should return False when no dot leaders present."""
        text = "We had 12 million customers"
        position = text.find("12")
        assert is_toc_page_reference(text, position) is False

    def test_is_toc_page_reference_minimum_dots(self):
        """Should require at least 3 dots to match.

        L2-P1.1: Now requires TOC context (section heading pattern).
        """
        # Two dots - should NOT match
        text1 = "Section 1..5"
        position1 = text1.find("5")
        assert is_toc_page_reference(text1, position1) is False

        # Three dots with section heading - should match
        text2 = "Section 1...5"
        position2 = text2.find("5")
        assert is_toc_page_reference(text2, position2) is True

    def test_is_near_table_of_contents_index_header(self):
        """Should detect 'INDEX' as TOC header variation."""
        text = "INDEX\nBusiness Overview...5"
        position = text.find("5")
        assert is_near_table_of_contents(text, position) is True

    def test_is_near_table_of_contents_contents_header(self):
        """Should detect 'CONTENTS' as TOC header variation."""
        text = "CONTENTS\nRisk Factors...12"
        position = text.find("12")
        assert is_near_table_of_contents(text, position) is True

    def test_is_near_table_of_contents_financial_statements_index(self):
        """Should detect 'INDEX TO FINANCIAL STATEMENTS'."""
        text = "INDEX TO FINANCIAL STATEMENTS\nBalance Sheet...F-1"
        # Use the first digit
        position = text.find("1")
        assert is_near_table_of_contents(text, position) is True


# =============================================================================
# Constants Tests
# =============================================================================


class TestTOCFilterEdgeCases:
    """Tests for TOC filter edge cases and potential false positives of the filter."""

    @pytest.fixture
    def filter(self):
        """Create a FalsePositiveFilter instance."""
        return FalsePositiveFilter()

    def test_valid_metric_beyond_toc_proximity_window(self, filter):
        """Should NOT filter valid metrics beyond TOC proximity window."""
        # Create text with TOC header, then content beyond 300 char window
        toc_header = "TABLE OF CONTENTS\n"
        # Add enough filler to exceed TOC_PROXIMITY_CHARS (300)
        filler = "x" * 310
        metric_text = "We serve 12 million active customers"
        text = toc_header + filler + metric_text

        number = NumberMatch(
            start=text.find("12"),
            end=text.find("12") + 2,
            raw_text="12",
            value=Decimal("12"),
            unit="count",
        )

        is_fp, reason = filter.is_false_positive(text, number)
        # Should NOT be filtered by TOC proximity (too far away)
        assert reason != "toc_proximity"

    def test_dots_in_non_toc_context(self, filter):
        """Should NOT filter dots used in regular text (ellipsis).

        L2-P1.1: Fixed by requiring TOC context (header or section heading).
        Narrative ellipsis without TOC context is no longer filtered.
        """
        text = "We expect...12 million customers this year"
        number = NumberMatch(
            start=text.find("12"),
            end=text.find("12") + 2,
            raw_text="12",
            value=Decimal("12"),
            unit="count",
        )

        is_fp, reason = filter.is_false_positive(text, number)
        # L2-P1.1 FIX: Now correctly NOT filtered (requires TOC context)
        assert is_fp is False or reason != "toc_page_reference"

    def test_multiple_toc_sections_in_document(self, filter):
        """Should filter numbers in any TOC section."""
        # Use larger numbers to avoid below_min_value filter (>= 10)
        text1 = "TABLE OF CONTENTS\nPart I...11\n\n" + ("x" * 500)
        text1 += "\nTABLE OF CONTENTS (continued)\nPart II...25"

        # First number (in first TOC)
        num1 = NumberMatch(
            start=text1.find("11"),
            end=text1.find("11") + 2,
            raw_text="11",
            value=Decimal("11"),
            unit="count",
        )
        is_fp1, reason1 = filter.is_false_positive(text1, num1)
        assert is_fp1 is True
        # Could be filtered by toc_proximity, toc_page_reference, or below_min_value
        assert reason1 in ("toc_proximity", "toc_page_reference", "below_min_value")

        # Second number (in continued TOC)
        num2 = NumberMatch(
            start=text1.find("25"),
            end=text1.find("25") + 2,
            raw_text="25",
            value=Decimal("25"),
            unit="count",
        )
        is_fp2, reason2 = filter.is_false_positive(text1, num2)
        assert is_fp2 is True
        assert reason2 in ("toc_proximity", "toc_page_reference")

    def test_toc_filter_with_custom_proximity_threshold(self):
        """Should respect custom proximity threshold."""
        # Create filter with shorter proximity window
        custom_filter = FalsePositiveFilter(toc_proximity_chars=50)

        toc_header = "TABLE OF CONTENTS\n"
        # Add 60 chars of filler (beyond 50 char custom threshold)
        filler = "x" * 60
        number_text = "12"
        text = toc_header + filler + number_text

        number = NumberMatch(
            start=len(toc_header) + 60,
            end=len(toc_header) + 60 + 2,
            raw_text="12",
            value=Decimal("12"),
            unit="count",
        )

        is_fp, reason = custom_filter.is_false_positive(text, number)
        # Should NOT filter (beyond custom 50 char threshold)
        assert reason != "toc_proximity"

    def test_toc_filter_with_custom_dot_leader_window(self):
        """Should respect custom dot leader window."""
        # Create filter with shorter dot leader window
        custom_filter = FalsePositiveFilter(toc_dot_leader_window=10)

        # Create text with dot leaders 15 chars before number (beyond custom 10 char window)
        # Use padding to ensure dots are >10 chars away
        padding = "x" * 6  # 6 chars of padding
        text = "..." + padding + "50"  # dots, padding, then number
        number = NumberMatch(
            start=text.find("50"),
            end=text.find("50") + 2,
            raw_text="50",
            value=Decimal("50"),
            unit="count",
        )

        is_fp, reason = custom_filter.is_false_positive(text, number)
        # Should NOT filter (dots beyond custom 10 char window)
        assert reason != "toc_page_reference"


class TestRealWorldTOCExamples:
    """Integration tests with realistic S-1 filing TOC snippets."""

    @pytest.fixture
    def filter(self):
        """Create a FalsePositiveFilter instance."""
        return FalsePositiveFilter()

    def test_typical_s1_toc_format(self, filter):
        """Should filter numbers in typical S-1 TOC format."""
        toc_snippet = """
TABLE OF CONTENTS

                                                                  Page
PART I
Item 1.   Business.................................................  1
Item 1A.  Risk Factors.............................................  12
Item 1B.  Unresolved Staff Comments................................  45
Item 2.   Properties...............................................  46
Item 3.   Legal Proceedings........................................  47
        """

        # Test page number 12
        num_12 = NumberMatch(
            start=toc_snippet.find("12"),
            end=toc_snippet.find("12") + 2,
            raw_text="12",
            value=Decimal("12"),
            unit="count",
        )
        is_fp_12, reason_12 = filter.is_false_positive(toc_snippet, num_12)
        assert is_fp_12 is True
        assert reason_12 in ("toc_proximity", "toc_page_reference")

        # Test page number 45
        num_45 = NumberMatch(
            start=toc_snippet.find("45"),
            end=toc_snippet.find("45") + 2,
            raw_text="45",
            value=Decimal("45"),
            unit="count",
        )
        is_fp_45, reason_45 = filter.is_false_positive(toc_snippet, num_45)
        assert is_fp_45 is True
        assert reason_45 in ("toc_proximity", "toc_page_reference")

    def test_index_to_financial_statements(self, filter):
        """Should filter numbers in financial statements index."""
        index_snippet = """
INDEX TO CONSOLIDATED FINANCIAL STATEMENTS

                                                                  Page
Balance Sheets..................................................... F-1
Statements of Operations........................................... F-2
Statements of Cash Flows........................................... F-3
        """

        # F-1 has the digit "1"
        num_1 = NumberMatch(
            start=index_snippet.find("1"),
            end=index_snippet.find("1") + 1,
            raw_text="1",
            value=Decimal("1"),
            unit="count",
        )
        is_fp_1, reason_1 = filter.is_false_positive(index_snippet, num_1)
        assert is_fp_1 is True
        assert reason_1 in ("toc_proximity", "toc_page_reference", "below_min_value")

    def test_valid_metric_in_business_section_after_toc(self, filter):
        """Should NOT filter valid metrics appearing after TOC section."""
        filing_snippet = """
TABLE OF CONTENTS
Business Overview.................................................. 5
Risk Factors....................................................... 12

""" + ("=" * 400) + """

BUSINESS OVERVIEW

We are a leading provider of cloud-based software. As of December 31, 2023,
we served 50000 active customers across 100 countries.
        """

        # Test the 50000 metric (should NOT be filtered - far from TOC)
        num_50000 = NumberMatch(
            start=filing_snippet.find("50000"),
            end=filing_snippet.find("50000") + 5,
            raw_text="50000",
            value=Decimal("50000"),
            unit="count",
        )
        is_fp_50000, reason_50000 = filter.is_false_positive(filing_snippet, num_50000)
        # Should NOT be filtered by TOC checks (well beyond proximity window)
        assert reason_50000 != "toc_proximity"
        assert reason_50000 != "toc_page_reference"


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

    def test_toc_headers_constant(self):
        """TOC_HEADERS should contain expected header variations."""
        assert len(TOC_HEADERS) >= 3  # At minimum: table of contents, contents, index
        assert "table of contents" in TOC_HEADERS
        assert "contents" in TOC_HEADERS
        assert "index" in TOC_HEADERS
        # All headers should be lowercase (for case-insensitive matching)
        assert all(header.islower() for header in TOC_HEADERS)

    def test_toc_proximity_chars_constant(self):
        """TOC_PROXIMITY_CHARS should be reasonable."""
        assert TOC_PROXIMITY_CHARS == 300
        assert TOC_PROXIMITY_CHARS > 0

    def test_toc_dot_leader_window_constant(self):
        """TOC_DOT_LEADER_WINDOW should be reasonable."""
        assert TOC_DOT_LEADER_WINDOW == 50
        assert TOC_DOT_LEADER_WINDOW > 0

class TestL2P11ContextAwareDotLeaders:
    """Tests for L2-P1.1: Context-aware dot leader detection.

    These tests verify that narrative ellipsis (e.g., "We expect...12 million")
    is NOT filtered, while genuine TOC page references with dot leaders ARE filtered.
    """

    @pytest.fixture
    def filter(self):
        """Create a FalsePositiveFilter instance."""
        return FalsePositiveFilter()

    def test_narrative_ellipsis_not_filtered(self, filter):
        """Narrative ellipsis without TOC context should NOT be filtered."""
        text = "We expect...12 million customers this year"
        number = NumberMatch(
            start=text.find("12"),
            end=text.find("12") + 2,
            raw_text="12",
            value=Decimal("12"),
            unit="count",
        )

        is_fp, reason = filter.is_false_positive(text, number)
        # Should NOT be filtered as toc_page_reference
        assert reason != "toc_page_reference"

    def test_narrative_ellipsis_variants(self, filter):
        """Test various narrative ellipsis patterns are NOT filtered."""
        test_cases = [
            "The company...50 employees strong",
            "Revenue growth...100% year over year",
            "Market share...25% and growing",
            "Expansion plans...30 new markets",
        ]

        for text in test_cases:
            # Find first number in text
            import re
            match = re.search(r'\d+', text)
            if not match:
                continue

            number = NumberMatch(
                start=match.start(),
                end=match.end(),
                raw_text=match.group(),
                value=Decimal(match.group()),
                unit="count",
            )

            is_fp, reason = filter.is_false_positive(text, number)
            # None of these should be filtered as TOC references
            assert reason != "toc_page_reference", f"Failed for: {text}"

    def test_toc_with_header_and_dots_filtered(self, filter):
        """TOC entries with header AND dot leaders should be filtered."""
        text = """TABLE OF CONTENTS

Business Overview.........12"""

        number = NumberMatch(
            start=text.find("12"),
            end=text.find("12") + 2,
            raw_text="12",
            value=Decimal("12"),
            unit="count",
        )

        is_fp, reason = filter.is_false_positive(text, number)
        # Should be filtered (has both TOC header and dot leaders)
        # Can be filtered by either toc_proximity or toc_page_reference
        assert is_fp is True
        assert reason in ("toc_proximity", "toc_page_reference")

    def test_section_heading_with_dots_filtered(self, filter):
        """TOC entries with section heading AND dot leaders should be filtered."""
        test_cases = [
            "Item 1A. Risk Factors....12",
            "Part II....50",
            "Section 3....100",
            "Chapter 5....25",
            "ITEM 2....15",  # Case insensitive
        ]

        for text in test_cases:
            # Find last number (the page number)
            import re
            matches = list(re.finditer(r'\d+', text))
            if not matches:
                continue
            match = matches[-1]  # Last number is the page number

            number = NumberMatch(
                start=match.start(),
                end=match.end(),
                raw_text=match.group(),
                value=Decimal(match.group()),
                unit="count",
            )

            is_fp, reason = filter.is_false_positive(text, number)
            # Should be filtered (has section heading + dot leaders)
            assert is_fp is True, f"Failed for: {text}"
            assert reason == "toc_page_reference", f"Wrong reason for: {text}"

    def test_dots_without_context_not_filtered(self, filter):
        """Dot leaders without TOC context should NOT be filtered."""
        # This has dot leaders but no TOC header or section heading
        text = "The trend continues....50 and rising"

        number = NumberMatch(
            start=text.find("50"),
            end=text.find("50") + 2,
            raw_text="50",
            value=Decimal("50"),
            unit="count",
        )

        is_fp, reason = filter.is_false_positive(text, number)
        # Should NOT be filtered (has dots but no TOC context)
        assert reason != "toc_page_reference"

    def test_section_heading_roman_numerals(self, filter):
        """Section headings with Roman numerals should work."""
        test_cases = [
            "Part II....12",
            "Part IV....50",
            "Section IX....100",
        ]

        for text in test_cases:
            import re
            matches = list(re.finditer(r'\d+', text))
            if not matches:
                continue
            match = matches[-1]

            number = NumberMatch(
                start=match.start(),
                end=match.end(),
                raw_text=match.group(),
                value=Decimal(match.group()),
                unit="count",
            )

            is_fp, reason = filter.is_false_positive(text, number)
            assert is_fp is True, f"Failed for: {text}"
            assert reason == "toc_page_reference", f"Wrong reason for: {text}"

    def test_section_heading_with_letter_suffix(self, filter):
        """Section headings with letter suffixes (Item 1A) should work."""
        text = "Item 1A. Risk Factors....12"

        number = NumberMatch(
            start=text.find("12"),
            end=text.find("12") + 2,
            raw_text="12",
            value=Decimal("12"),
            unit="count",
        )

        is_fp, reason = filter.is_false_positive(text, number)
        assert is_fp is True
        assert reason == "toc_page_reference"


# =============================================================================
# Issue 4 - Standalone TOC Pattern Tests
# =============================================================================


class TestIssue4StandaloneTOCPattern:
    """Tests for Issue 4 standalone TOC pattern filtering."""

    @pytest.fixture
    def filter(self):
        """Create a FalsePositiveFilter instance."""
        return FalsePositiveFilter()

    def test_filters_standalone_number_before_toc_text(self, filter):
        """Test filtering of '73 Table of Contents' pattern."""
        number = NumberMatch(
            start=0, end=2, raw_text="73", value=Decimal("73"), unit="count"
        )
        text = "73 Table of Contents"

        is_fp, reason = filter.is_false_positive(text, number)

        assert is_fp is True
        assert reason == "reference_number"

    def test_filters_toc_case_insensitive(self, filter):
        """Test case-insensitive matching for TOC patterns."""
        number = NumberMatch(
            start=0, end=2, raw_text="73", value=Decimal("73"), unit="count"
        )

        test_cases = [
            "73 Table of Contents",
            "73 TABLE OF CONTENTS",
            "73 table of contents",
            "73 Table Of Contents",
        ]

        for text in test_cases:
            is_fp, reason = filter.is_false_positive(text, number)
            assert is_fp is True, f"Failed for: {text}"
            assert reason == "reference_number", f"Wrong reason for: {text}"

    def test_filters_toc_abbreviation(self, filter):
        """Test filtering of '73 TOC' abbreviated pattern."""
        number = NumberMatch(
            start=0, end=2, raw_text="73", value=Decimal("73"), unit="count"
        )
        text = "73 TOC"

        is_fp, reason = filter.is_false_positive(text, number)

        assert is_fp is True
        assert reason == "reference_number"

    def test_does_not_filter_unrelated_numbers(self, filter):
        """Test that numbers unrelated to TOC are not filtered."""
        # Use a text that has no TOC-related words at all
        # "toc" in "stock" should not match because of word boundary
        text = "Our stock price grew 73% last quarter with strong momentum."
        number = NumberMatch(
            start=text.find("73"),
            end=text.find("73") + 2,
            raw_text="73",
            value=Decimal("73"),
            unit="percent",
        )

        is_fp, reason = filter.is_false_positive(text, number)

        # Should not be filtered - "toc" in "stock" doesn't match due to word boundary
        assert is_fp is False
        assert reason is None

    def test_filters_number_newline_before_toc(self, filter):
        """Test filtering when number and TOC are on different lines."""
        number = NumberMatch(
            start=0, end=2, raw_text="73", value=Decimal("73"), unit="count"
        )
        text = "73\nTable of Contents"

        is_fp, reason = filter.is_false_positive(text, number)

        assert is_fp is True
        assert reason == "reference_number"

    def test_filters_farfetch_filing_example(self, filter):
        """Test real example from Farfetch filing."""
        number = NumberMatch(
            start=25, end=27, raw_text="73", value=Decimal("73"), unit="count"
        )
        # Realistic context from filing
        text = "was 43.0%, respectively.\n73 Table of Contents\nLifetime Value"

        is_fp, reason = filter.is_false_positive(text, number)

        assert is_fp is True
        assert reason == "reference_number"

    def test_existing_filters_still_work(self, filter):
        """Ensure new pattern doesn't break existing functionality."""
        # Test existing patterns still work
        # Note: Use numbers >= 10 to avoid below_min_value filtering
        test_cases = [
            ("page 73", "73", Decimal("73"), True, "reference_number"),
            ("Note 15", "15", Decimal("15"), True, "reference_number"),
            ("In 2023 we", "2023", Decimal("2023"), True, "likely_year"),
        ]

        for text, raw_text, value, expected_fp, expected_reason in test_cases:
            number = NumberMatch(
                start=text.find(raw_text),
                end=text.find(raw_text) + len(raw_text),
                raw_text=raw_text,
                value=value,
                unit="count",
            )
            is_fp, reason = filter.is_false_positive(text, number)
            assert is_fp == expected_fp, f"Failed for: {text}"
            if expected_reason:
                assert reason == expected_reason, f"Wrong reason for: {text}"


# =============================================================================
# EI-2: Measurement Unit Pattern Tests
# =============================================================================


class TestMeasurementUnitPatterns:
    """EI-2: Measurement unit pattern filtering tests.

    Numbers that are part of measurement units (e.g., "24" in "24-hour period")
    should be filtered as false positives, as they describe measurement timeframes
    rather than actual metric values.
    """

    @pytest.fixture
    def filter(self):
        """Create a FalsePositiveFilter instance."""
        return FalsePositiveFilter()

    def test_24_hour_period_filtered(self, filter):
        """24-hour period should filter out 24."""
        text = "We define daily active users as users active in a 24-hour period"
        number = NumberMatch(
            start=text.find("24"),
            end=text.find("24") + 2,
            raw_text="24",
            value=Decimal("24"),
            unit="count",
        )
        is_fp, reason = filter.is_false_positive(text, number)
        assert is_fp is True
        assert reason == "reference_number"

    def test_30_day_window_filtered(self, filter):
        """30-day window should filter out 30."""
        text = "Users active within a 30-day window"
        number = NumberMatch(
            start=text.find("30"),
            end=text.find("30") + 2,
            raw_text="30",
            value=Decimal("30"),
            unit="count",
        )
        is_fp, reason = filter.is_false_positive(text, number)
        assert is_fp is True
        assert reason == "reference_number"

    def test_12_month_period_filtered(self, filter):
        """12-month period should filter out 12."""
        text = "Retention measured over a 12-month period"
        number = NumberMatch(
            start=text.find("12"),
            end=text.find("12") + 2,
            raw_text="12",
            value=Decimal("12"),
            unit="count",
        )
        is_fp, reason = filter.is_false_positive(text, number)
        assert is_fp is True
        assert reason == "reference_number"

    def test_7_week_average_filtered(self, filter):
        """7-week average should filter out 7.

        Note: 7 is below MIN_METRIC_VALUE by default, but we're testing
        that the pattern matches correctly.
        """
        text = "Computed as a 7-week average"
        number = NumberMatch(
            start=text.find("7"),
            end=text.find("7") + 1,
            raw_text="7",
            value=Decimal("7"),
            unit="count",
        )
        is_fp, reason = filter.is_false_positive(text, number)
        assert is_fp is True
        # Could be filtered by either below_min_value or reference_number
        assert reason in ("below_min_value", "reference_number")

    def test_24_hour_space_filtered(self, filter):
        """24 hour period (space) should filter out 24."""
        text = "Active within 24 hour timeframe"
        number = NumberMatch(
            start=text.find("24"),
            end=text.find("24") + 2,
            raw_text="24",
            value=Decimal("24"),
            unit="count",
        )
        is_fp, reason = filter.is_false_positive(text, number)
        assert is_fp is True
        assert reason == "reference_number"

    def test_30_day_space_filtered(self, filter):
        """30 day retention (space) should filter out 30."""
        text = "30 day retention metric"
        number = NumberMatch(
            start=text.find("30"),
            end=text.find("30") + 2,
            raw_text="30",
            value=Decimal("30"),
            unit="count",
        )
        is_fp, reason = filter.is_false_positive(text, number)
        assert is_fp is True
        assert reason == "reference_number"

    def test_90_second_filtered(self, filter):
        """90-second timeout should filter out 90."""
        text = "Session timeout set to 90-second interval"
        number = NumberMatch(
            start=text.find("90"),
            end=text.find("90") + 2,
            raw_text="90",
            value=Decimal("90"),
            unit="count",
        )
        is_fp, reason = filter.is_false_positive(text, number)
        assert is_fp is True
        assert reason == "reference_number"

    def test_5_minute_filtered(self, filter):
        """5-minute interval should filter out 5.

        Note: 5 is below MIN_METRIC_VALUE, but testing pattern match.
        """
        text = "Data refreshed every 5-minute interval"
        number = NumberMatch(
            start=text.find("5"),
            end=text.find("5") + 1,
            raw_text="5",
            value=Decimal("5"),
            unit="count",
        )
        is_fp, reason = filter.is_false_positive(text, number)
        assert is_fp is True
        # Could be filtered by either below_min_value or reference_number
        assert reason in ("below_min_value", "reference_number")

    def test_plural_days_filtered(self, filter):
        """30 days should filter out 30."""
        text = "Measured over 30 days"
        number = NumberMatch(
            start=text.find("30"),
            end=text.find("30") + 2,
            raw_text="30",
            value=Decimal("30"),
            unit="count",
        )
        is_fp, reason = filter.is_false_positive(text, number)
        assert is_fp is True
        assert reason == "reference_number"

    def test_plural_months_filtered(self, filter):
        """12 months should filter out 12."""
        text = "Calculated over 12 months"
        number = NumberMatch(
            start=text.find("12"),
            end=text.find("12") + 2,
            raw_text="12",
            value=Decimal("12"),
            unit="count",
        )
        is_fp, reason = filter.is_false_positive(text, number)
        assert is_fp is True
        assert reason == "reference_number"

    def test_24000_customers_not_filtered(self, filter):
        """24,000 customers should NOT be filtered by measurement units."""
        text = "We grew to 24,000 customers"
        number = NumberMatch(
            start=text.find("24,000"),
            end=text.find("24,000") + 6,
            raw_text="24,000",
            value=Decimal("24000"),
            unit="count",
        )
        is_fp, reason = filter.is_false_positive(text, number)
        assert is_fp is False
        assert reason is None

    def test_numeric_value_not_filtered(self, filter):
        """30% year over year should NOT be filtered."""
        text = "Revenue grew 30% year over year"
        number = NumberMatch(
            start=text.find("30"),
            end=text.find("30") + 2,
            raw_text="30",
            value=Decimal("30"),
            unit="percent",
        )
        is_fp, reason = filter.is_false_positive(text, number)
        # 30 may be filtered as below_min_value, but NOT by measurement unit
        # The key is that "30% year" doesn't match "30-year" or "30 year"
        if is_fp:
            assert reason == "below_min_value", "Should only be filtered by min value, not measurement unit"
        else:
            assert reason is None

    def test_standalone_number_not_filtered(self, filter):
        """We have 12 million users should NOT be filtered by measurement units."""
        text = "We have 12 million users"
        # Use a larger number to avoid below_min_value
        number = NumberMatch(
            start=text.find("12"),
            end=text.find("12") + 2,
            raw_text="12",
            value=Decimal("12000000"),  # 12 million
            unit="count",
        )
        is_fp, reason = filter.is_false_positive(text, number)
        # Should not be filtered by measurement unit patterns
        assert reason != "reference_number" or reason is None

    def test_quarter_filtered(self, filter):
        """4-quarter period should filter out 4."""
        text = "Rolling 4-quarter average"
        # Use larger number to avoid below_min_value filter
        number = NumberMatch(
            start=text.find("4"),
            end=text.find("4") + 1,
            raw_text="4",
            value=Decimal("4"),
            unit="count",
        )
        is_fp, reason = filter.is_false_positive(text, number)
        assert is_fp is True
        # Could be filtered by either below_min_value or reference_number
        assert reason in ("below_min_value", "reference_number")

    def test_year_singular_filtered(self, filter):
        """1-year period should filter out 1."""
        text = "Over a 1-year period"
        number = NumberMatch(
            start=text.find("1"),
            end=text.find("1") + 1,
            raw_text="1",
            value=Decimal("1"),
            unit="count",
        )
        is_fp, reason = filter.is_false_positive(text, number)
        assert is_fp is True
        # Could be filtered by either below_min_value or reference_number
        assert reason in ("below_min_value", "reference_number")

    def test_case_insensitive(self, filter):
        """Measurement unit patterns should be case insensitive."""
        # Uppercase
        text1 = "Within 24-HOUR period"
        number1 = NumberMatch(
            start=text1.find("24"),
            end=text1.find("24") + 2,
            raw_text="24",
            value=Decimal("24"),
            unit="count",
        )
        is_fp1, reason1 = filter.is_false_positive(text1, number1)
        assert is_fp1 is True
        assert reason1 == "reference_number"

        # Mixed case
        text2 = "Within 30-Day window"
        number2 = NumberMatch(
            start=text2.find("30"),
            end=text2.find("30") + 2,
            raw_text="30",
            value=Decimal("30"),
            unit="count",
        )
        is_fp2, reason2 = filter.is_false_positive(text2, number2)
        assert is_fp2 is True
        assert reason2 == "reference_number"


# =============================================================================
# HRV-10: Financial Statement Context Detection Tests
# =============================================================================


class TestFinancialStatementDetection:
    """Tests for HRV-10 financial statement context detection."""

    def test_is_in_financial_statement_context_income_statement(self):
        """Should detect Consolidated Statements of Operations header."""
        from src.review.false_positive_filter import is_in_financial_statement_context

        text = """CONSOLIDATED STATEMENTS OF OPERATIONS
(In thousands, except per share data)

Revenue $400,552 $318,519 $255,843"""
        position = text.find("400,552")
        assert is_in_financial_statement_context(text, position) is True

    def test_is_in_financial_statement_context_balance_sheet(self):
        """Should detect Consolidated Balance Sheets header."""
        from src.review.false_positive_filter import is_in_financial_statement_context

        text = """CONSOLIDATED BALANCE SHEETS
(In thousands)

Total assets $1,198,956"""
        position = text.find("1,198,956")
        assert is_in_financial_statement_context(text, position) is True

    def test_is_in_financial_statement_context_cash_flow(self):
        """Should detect Statements of Cash Flows header."""
        from src.review.false_positive_filter import is_in_financial_statement_context

        text = """CONSOLIDATED STATEMENTS OF CASH FLOWS
(In thousands)

Net cash from operating activities $125,000"""
        position = text.find("125,000")
        assert is_in_financial_statement_context(text, position) is True

    def test_is_in_financial_statement_context_summary_data(self):
        """Should detect Summary Financial Data header."""
        from src.review.false_positive_filter import is_in_financial_statement_context

        text = """SUMMARY CONSOLIDATED FINANCIAL DATA
(In thousands)

Revenue $400,552"""
        position = text.find("400,552")
        assert is_in_financial_statement_context(text, position) is True

    def test_is_in_financial_statement_context_negative(self):
        """Should NOT detect financial statement context for regular text."""
        from src.review.false_positive_filter import is_in_financial_statement_context

        text = "We had 10 million daily active users in Q4 2023."
        position = text.find("10")
        assert is_in_financial_statement_context(text, position) is False

    def test_is_in_financial_statement_context_respects_proximity(self):
        """Should NOT detect if header is too far away."""
        from src.review.false_positive_filter import is_in_financial_statement_context

        header = "CONSOLIDATED STATEMENTS OF OPERATIONS\n"
        filler = "x" * 600  # Exceeds default 500 char proximity
        text = header + filler + "Revenue $400,552"
        position = text.find("400,552")
        assert is_in_financial_statement_context(text, position) is False

    def test_contains_financial_line_item_keyword_revenue(self):
        """Should detect 'revenue' keyword."""
        from src.review.false_positive_filter import contains_financial_line_item_keyword

        result = contains_financial_line_item_keyword("Revenue [CELL] $400,552")
        assert result == "revenue"

    def test_contains_financial_line_item_keyword_total_assets(self):
        """Should detect 'total assets' keyword (multi-word)."""
        from src.review.false_positive_filter import contains_financial_line_item_keyword

        result = contains_financial_line_item_keyword("Total assets $1,198,956")
        assert result == "total assets"

    def test_contains_financial_line_item_keyword_cost_of_revenue(self):
        """Should detect 'cost of revenue' keyword (multi-word)."""
        from src.review.false_positive_filter import contains_financial_line_item_keyword

        result = contains_financial_line_item_keyword("Cost of revenue $200,000")
        assert result == "cost of revenue"

    def test_contains_financial_line_item_keyword_negative(self):
        """Should NOT detect customer metric text."""
        from src.review.false_positive_filter import contains_financial_line_item_keyword

        result = contains_financial_line_item_keyword("Daily active users: 10 million")
        assert result is None

    def test_contains_financial_line_item_case_insensitive(self):
        """Should match regardless of case."""
        from src.review.false_positive_filter import contains_financial_line_item_keyword

        result = contains_financial_line_item_keyword("GROSS PROFIT $150,000")
        assert result == "gross profit"

    def test_financial_statement_filter_integration(self):
        """Integration test: filter should flag financial statement line items."""
        fp_filter = FalsePositiveFilter(filter_financial_statements=True)

        text = """CONSOLIDATED STATEMENTS OF OPERATIONS
(In thousands)

Revenue $400,552 $318,519"""

        number = NumberMatch(
            start=text.find("400,552"),
            end=text.find("400,552") + 7,
            raw_text="$400,552",
            value=Decimal("400552"),
            unit="currency",
        )

        is_fp, reason = fp_filter.is_false_positive(text, number)
        assert is_fp is True
        assert reason is not None
        assert reason.startswith("financial_line_item:")

    def test_financial_statement_filter_disabled(self):
        """Should NOT filter when filter_financial_statements=False."""
        fp_filter = FalsePositiveFilter(filter_financial_statements=False)

        text = """CONSOLIDATED STATEMENTS OF OPERATIONS
Revenue $400,552"""

        number = NumberMatch(
            start=text.find("400,552"),
            end=text.find("400,552") + 7,
            raw_text="$400,552",
            value=Decimal("400552"),
            unit="currency",
        )

        is_fp, reason = fp_filter.is_false_positive(text, number)
        # Should not be flagged as financial_line_item when disabled
        if reason is not None:
            assert not reason.startswith("financial_line_item:")


# =============================================================================
# HRV-11: Metric Type Validation Tests
# =============================================================================


class TestMetricTypeValidation:
    """Tests for HRV-11 type validation helper functions."""

    def test_is_percentage_format_with_percent_sign(self):
        """Should detect explicit percentage format."""
        from src.review.false_positive_filter import is_percentage_format

        assert is_percentage_format("143%", "percentage") is True
        assert is_percentage_format("85.5%", "percentage") is True

    def test_is_percentage_format_with_unit(self):
        """Should detect percentage from unit even without % sign."""
        from src.review.false_positive_filter import is_percentage_format

        assert is_percentage_format("143", "percentage") is True

    def test_is_percentage_format_decimal_ratio(self):
        """Should detect decimal ratios as valid percentages (e.g., 1.25 = 125%)."""
        from src.review.false_positive_filter import is_percentage_format

        # Retention rates often expressed as decimals
        assert is_percentage_format("1.25", "count") is True  # 125%
        assert is_percentage_format("0.85", "count") is True  # 85%
        assert is_percentage_format("1.43", "count") is True  # 143%

    def test_is_percentage_format_negative(self):
        """Should NOT detect non-percentage formats."""
        from src.review.false_positive_filter import is_percentage_format

        assert is_percentage_format("$143", "currency") is False
        assert is_percentage_format("10000", "count") is False
        assert is_percentage_format("5.5", "count") is False  # Outside 0.5-2.5 range

    def test_is_dollar_format_with_dollar_sign(self):
        """Should detect dollar format from $ sign."""
        from src.review.false_positive_filter import is_dollar_format

        assert is_dollar_format("$100", "currency") is True
        assert is_dollar_format("$1.5 million", "currency") is True

    def test_is_dollar_format_with_unit(self):
        """Should detect dollar format from unit."""
        from src.review.false_positive_filter import is_dollar_format

        assert is_dollar_format("100", "currency") is True
        assert is_dollar_format("100", "usd") is True

    def test_is_dollar_format_negative(self):
        """Should NOT detect non-dollar formats."""
        from src.review.false_positive_filter import is_dollar_format

        assert is_dollar_format("100", "count") is False
        assert is_dollar_format("85%", "percentage") is False

    def test_is_count_format_plain_number(self):
        """Should detect plain count format."""
        from src.review.false_positive_filter import is_count_format

        assert is_count_format("10000", "count") is True
        assert is_count_format("1.5 million", "count") is True

    def test_is_count_format_negative(self):
        """Should NOT detect currency or percentage as count."""
        from src.review.false_positive_filter import is_count_format

        assert is_count_format("$100", "count") is False  # Has $ sign
        assert is_count_format("85%", "count") is False   # Has % sign
        assert is_count_format("100", "currency") is False  # Wrong unit

    def test_percentage_only_metrics_set(self):
        """PERCENTAGE_ONLY_METRICS should contain expected metrics."""
        from src.review.false_positive_filter import PERCENTAGE_ONLY_METRICS

        assert "cm_net_revenue_retention" in PERCENTAGE_ONLY_METRICS
        assert "cm_customer_churn_rate" in PERCENTAGE_ONLY_METRICS

    def test_dollar_only_metrics_set(self):
        """DOLLAR_ONLY_METRICS should contain expected metrics."""
        from src.review.false_positive_filter import DOLLAR_ONLY_METRICS

        assert "cm_arr" in DOLLAR_ONLY_METRICS
        assert "cm_ltv" in DOLLAR_ONLY_METRICS
        assert "cm_cac" in DOLLAR_ONLY_METRICS
        assert "cm_gmv" in DOLLAR_ONLY_METRICS
        assert "cm_average_order_value" in DOLLAR_ONLY_METRICS

    def test_count_only_metrics_set(self):
        """COUNT_ONLY_METRICS should contain expected metrics."""
        from src.review.false_positive_filter import COUNT_ONLY_METRICS

        assert "cm_customer" in COUNT_ONLY_METRICS
        assert "cm_daily_active_users" in COUNT_ONLY_METRICS
        assert "cm_monthly_active_users" in COUNT_ONLY_METRICS


# =============================================================================
# HRV-10/11: Financial Statement Header Patterns Tests
# =============================================================================


class TestFinancialStatementHeaderPatterns:
    """Tests for financial statement header pattern matching."""

    def test_income_statement_variations(self):
        """Should match various income statement header formats."""
        from src.review.false_positive_filter import FINANCIAL_STATEMENT_HEADERS

        test_headers = [
            "CONSOLIDATED STATEMENTS OF OPERATIONS",
            "Consolidated Statements of Income",
            "STATEMENTS OF OPERATIONS",
            "Income Statement",
            "CONSOLIDATED RESULTS OF OPERATIONS",
        ]

        for header in test_headers:
            matched = any(pattern.search(header) for pattern in FINANCIAL_STATEMENT_HEADERS)
            assert matched, f"Failed to match: {header}"

    def test_balance_sheet_variations(self):
        """Should match various balance sheet header formats."""
        from src.review.false_positive_filter import FINANCIAL_STATEMENT_HEADERS

        test_headers = [
            "CONSOLIDATED BALANCE SHEETS",
            "Consolidated Balance Sheet",
            "STATEMENTS OF FINANCIAL POSITION",
            "Balance Sheet Data",
        ]

        for header in test_headers:
            matched = any(pattern.search(header) for pattern in FINANCIAL_STATEMENT_HEADERS)
            assert matched, f"Failed to match: {header}"

    def test_cash_flow_variations(self):
        """Should match various cash flow statement header formats."""
        from src.review.false_positive_filter import FINANCIAL_STATEMENT_HEADERS

        test_headers = [
            "CONSOLIDATED STATEMENTS OF CASH FLOWS",
            "Statements of Cash Flow",
        ]

        for header in test_headers:
            matched = any(pattern.search(header) for pattern in FINANCIAL_STATEMENT_HEADERS)
            assert matched, f"Failed to match: {header}"

    def test_summary_data_variations(self):
        """Should match summary financial data header formats."""
        from src.review.false_positive_filter import FINANCIAL_STATEMENT_HEADERS

        test_headers = [
            "SUMMARY CONSOLIDATED FINANCIAL DATA",
            "Summary Financial Data",
            "SELECTED FINANCIAL DATA",
            "Summary Operating Data",
        ]

        for header in test_headers:
            matched = any(pattern.search(header) for pattern in FINANCIAL_STATEMENT_HEADERS)
            assert matched, f"Failed to match: {header}"


# =============================================================================
# Spelled-Out Number Detection Tests
# =============================================================================


class TestIsSpelledOutNumber:
    """Tests for the is_spelled_out_number helper function."""

    def test_spelled_out_returns_true(self):
        """Spelled-out numbers should return True."""
        assert is_spelled_out_number("six") is True
        assert is_spelled_out_number("twenty-one") is True
        assert is_spelled_out_number("five million") is True
        assert is_spelled_out_number("SIX") is True

    def test_numeric_returns_false(self):
        """Numeric strings should return False."""
        assert is_spelled_out_number("123") is False
        assert is_spelled_out_number("50,000") is False
        assert is_spelled_out_number("$1,234.56") is False
        assert is_spelled_out_number("100M") is False

    def test_mixed_returns_false(self):
        """Mixed alphanumeric should return False (contains digits)."""
        assert is_spelled_out_number("10 million") is False
        assert is_spelled_out_number("$5.2 million") is False


class TestSpelledOutNumberFilterExemption:
    """Tests that spelled-out numbers are exempt from certain filters."""

    @pytest.fixture
    def filter(self):
        """Create a FalsePositiveFilter instance."""
        return FalsePositiveFilter()

    def test_spelled_out_exempt_from_min_value(self, filter):
        """Bare spelled-out number without magnitude is filtered by spelled_out_no_magnitude.

        "six" passes the below_min_value check (exempt) but is caught by Fix A
        (spelled_out_no_magnitude) because real metrics always pair word-numbers
        with a magnitude ("six million"), so bare "six" is an ordinal/qualifier.
        """
        number = NumberMatch(
            start=0, end=3, raw_text="six", value=Decimal("6"), unit="count"
        )
        is_fp, reason = filter.is_false_positive("six months payback", number)
        # Filtered by spelled_out_no_magnitude, not below_min_value
        assert is_fp is True
        assert reason == "spelled_out_no_magnitude"

    def test_spelled_out_filtered_by_no_magnitude_before_toc(self, filter):
        """Bare spelled-out number is caught by spelled_out_no_magnitude before TOC check.

        "six" (no magnitude) near a TOC is rejected by Fix A before the TOC
        proximity check is reached — the TOC exemption applies only to numbers
        that reach that check.
        """
        text = "Table of Contents ... payback is six months"
        number = NumberMatch(
            start=text.find("six"), end=text.find("six") + 3,
            raw_text="six", value=Decimal("6"), unit="count"
        )
        is_fp, reason = filter.is_false_positive(text, number)
        # Caught by spelled_out_no_magnitude before TOC proximity check
        assert is_fp is True
        assert reason == "spelled_out_no_magnitude"

    def test_numeric_small_value_still_filtered(self, filter):
        """Numeric small values should still be filtered (not exempt)."""
        number = NumberMatch(
            start=0, end=1, raw_text="6", value=Decimal("6"), unit="count"
        )
        is_fp, reason = filter.is_false_positive("6 months payback", number)
        # Should be filtered - numeric small value
        assert is_fp is True
        assert reason == "below_min_value"


# =============================================================================
# DFP-1: Month DD Date Pattern Tests (without year)
# =============================================================================


class TestMonthDDDatePattern:
    """DFP-1: Tests for filtering day numbers from 'Month DD' patterns without year.

    Example: "January 31," in table headers - the "31" should be filtered.
    """

    @pytest.fixture
    def filter(self):
        """Create a FalsePositiveFilter instance."""
        return FalsePositiveFilter()

    def test_january_31_comma_filtered(self, filter):
        """'January 31,' should filter out '31' as part_of_date."""
        text = "Fiscal Year Ended January 31, Revenue"
        number = NumberMatch(
            start=text.find("31"),
            end=text.find("31") + 2,
            raw_text="31",
            value=Decimal("31"),
            unit="count",
        )
        is_fp, reason = filter.is_false_positive(text, number)
        assert is_fp is True
        assert reason == "part_of_date"

    def test_june_30_comma_filtered(self, filter):
        """'June 30,' should filter out '30' as part_of_date."""
        text = "Six Months Ended June 30, Results"
        number = NumberMatch(
            start=text.find("30"),
            end=text.find("30") + 2,
            raw_text="30",
            value=Decimal("30"),
            unit="count",
        )
        is_fp, reason = filter.is_false_positive(text, number)
        assert is_fp is True
        assert reason == "part_of_date"

    def test_september_30_no_comma_filtered(self, filter):
        """'September 30' (no comma) should filter out '30' as part_of_date."""
        text = "Quarter Ended September 30 Revenue"
        number = NumberMatch(
            start=text.find("30"),
            end=text.find("30") + 2,
            raw_text="30",
            value=Decimal("30"),
            unit="count",
        )
        is_fp, reason = filter.is_false_positive(text, number)
        assert is_fp is True
        assert reason == "part_of_date"

    def test_jul_31_abbreviated_filtered(self, filter):
        """'Jul 31' (abbreviated) should filter out '31' as part_of_date."""
        text = "Period Ended Jul 31 Performance"
        number = NumberMatch(
            start=text.find("31"),
            end=text.find("31") + 2,
            raw_text="31",
            value=Decimal("31"),
            unit="count",
        )
        is_fp, reason = filter.is_false_positive(text, number)
        assert is_fp is True
        assert reason == "part_of_date"

    def test_fiscal_year_ended_january_31_filtered(self, filter):
        """'Fiscal Year Ended January 31,' should filter '31'."""
        text = "Fiscal Year Ended January 31, Three Months Ended"
        number = NumberMatch(
            start=text.find("31"),
            end=text.find("31") + 2,
            raw_text="31",
            value=Decimal("31"),
            unit="count",
        )
        is_fp, reason = filter.is_false_positive(text, number)
        assert is_fp is True
        assert reason == "part_of_date"

    def test_six_months_ended_july_31_filtered(self, filter):
        """'Six Months Ended July 31,' should filter '31'."""
        text = "Six Months Ended July 31, Revenue Growth"
        number = NumberMatch(
            start=text.find("31"),
            end=text.find("31") + 2,
            raw_text="31",
            value=Decimal("31"),
            unit="count",
        )
        is_fp, reason = filter.is_false_positive(text, number)
        assert is_fp is True
        assert reason == "part_of_date"

    def test_31_million_customers_not_filtered(self, filter):
        """'31 million customers' should NOT be filtered (not a date)."""
        text = "We reached 31 million customers in the quarter"
        number = NumberMatch(
            start=text.find("31"),
            end=text.find("31") + 2,
            raw_text="31",
            value=Decimal("31000000"),  # 31 million
            unit="count",
        )
        is_fp, reason = filter.is_false_positive(text, number)
        # Should NOT be filtered as part_of_date
        assert reason != "part_of_date"

    def test_30_percent_growth_not_filtered(self, filter):
        """'30%' should NOT be filtered by date pattern."""
        text = "Revenue grew 30% year over year"
        number = NumberMatch(
            start=text.find("30"),
            end=text.find("30") + 2,
            raw_text="30%",
            value=Decimal("30"),
            unit="percentage",
        )
        is_fp, reason = filter.is_false_positive(text, number)
        # Should NOT be filtered as part_of_date
        assert reason != "part_of_date"

    def test_dollar_31_not_filtered(self, filter):
        """'$31' should NOT be filtered by date pattern."""
        text = "Average purchase was $31"
        number = NumberMatch(
            start=text.find("31"),
            end=text.find("31") + 2,
            raw_text="$31",
            value=Decimal("31"),
            unit="currency",
        )
        is_fp, reason = filter.is_false_positive(text, number)
        # Should NOT be filtered as part_of_date
        assert reason != "part_of_date"

    def test_dec_31_abbreviated_filtered(self, filter):
        """'Dec 31' (abbreviated) should filter out '31'."""
        text = "Year End Dec 31 Balance"
        number = NumberMatch(
            start=text.find("31"),
            end=text.find("31") + 2,
            raw_text="31",
            value=Decimal("31"),
            unit="count",
        )
        is_fp, reason = filter.is_false_positive(text, number)
        assert is_fp is True
        assert reason == "part_of_date"

    def test_sept_30_abbreviated_filtered(self, filter):
        """'Sept 30' (alternate September abbreviation) should filter out '30'."""
        text = "Quarter End Sept 30 Financials"
        number = NumberMatch(
            start=text.find("30"),
            end=text.find("30") + 2,
            raw_text="30",
            value=Decimal("30"),
            unit="count",
        )
        is_fp, reason = filter.is_false_positive(text, number)
        assert is_fp is True
        assert reason == "part_of_date"

    def test_case_insensitive_january(self, filter):
        """Pattern should be case-insensitive."""
        text = "JANUARY 31, fiscal year end"
        number = NumberMatch(
            start=text.find("31"),
            end=text.find("31") + 2,
            raw_text="31",
            value=Decimal("31"),
            unit="count",
        )
        is_fp, reason = filter.is_false_positive(text, number)
        assert is_fp is True
        assert reason == "part_of_date"

    def test_april_15_middle_month_filtered(self, filter):
        """'April 15' (mid-month date) should filter '15'."""
        text = "Due Date April 15 Payment"
        number = NumberMatch(
            start=text.find("15"),
            end=text.find("15") + 2,
            raw_text="15",
            value=Decimal("15"),
            unit="count",
        )
        is_fp, reason = filter.is_false_positive(text, number)
        assert is_fp is True
        assert reason == "part_of_date"


# =============================================================================
# Fix A: Bare word-number (no magnitude) rejection tests
# =============================================================================


class TestSpelledOutNoMagnitudeFiltering:
    """Bare word-numbers without magnitude words should be rejected (Fix A)."""

    @pytest.fixture
    def filter(self):
        return FalsePositiveFilter()

    def test_bare_three_rejected(self, filter):
        """'three' with no magnitude word → spelled_out_no_magnitude."""
        number = NumberMatch(
            start=0, end=5, raw_text="three", value=Decimal("3"), unit="count"
        )
        is_fp, reason = filter.is_false_positive("three customers", number)
        assert is_fp is True
        assert reason == "spelled_out_no_magnitude"

    def test_bare_one_rejected(self, filter):
        """'one' with no magnitude word → spelled_out_no_magnitude."""
        number = NumberMatch(
            start=0, end=3, raw_text="one", value=Decimal("1"), unit="count"
        )
        is_fp, reason = filter.is_false_positive("one customers", number)
        assert is_fp is True
        assert reason == "spelled_out_no_magnitude"

    def test_bare_nine_rejected(self, filter):
        """'nine' with no magnitude word → spelled_out_no_magnitude."""
        number = NumberMatch(
            start=0, end=4, raw_text="nine", value=Decimal("9"), unit="count"
        )
        is_fp, reason = filter.is_false_positive("nine customers", number)
        assert is_fp is True
        assert reason == "spelled_out_no_magnitude"

    def test_six_million_not_rejected(self, filter):
        """'six million' has magnitude word → should NOT be rejected."""
        number = NumberMatch(
            start=0, end=10, raw_text="six million", value=Decimal("6000000"), unit="count"
        )
        is_fp, reason = filter.is_false_positive("six million customers", number)
        assert is_fp is False

    def test_twelve_billion_not_rejected(self, filter):
        """'twelve billion' has magnitude word → should NOT be rejected."""
        number = NumberMatch(
            start=0, end=14, raw_text="twelve billion", value=Decimal("12000000000"), unit="count"
        )
        is_fp, reason = filter.is_false_positive("twelve billion users", number)
        assert is_fp is False

    def test_twenty_thousand_not_rejected(self, filter):
        """'twenty thousand' has magnitude word → should NOT be rejected."""
        number = NumberMatch(
            start=0, end=15, raw_text="twenty thousand", value=Decimal("20000"), unit="count"
        )
        is_fp, reason = filter.is_false_positive("twenty thousand customers", number)
        assert is_fp is False

    def test_fourteen_not_rejected(self, filter):
        """'fourteen' (value=14 > 9) should NOT be rejected — legitimate small count."""
        number = NumberMatch(
            start=0, end=8, raw_text="fourteen", value=Decimal("14"), unit="count"
        )
        is_fp, reason = filter.is_false_positive("fourteen enterprise customers", number)
        assert is_fp is False

    def test_forty_one_not_rejected(self, filter):
        """'forty-one' (value=41 > 9) should NOT be rejected."""
        number = NumberMatch(
            start=0, end=9, raw_text="forty-one", value=Decimal("41"), unit="count"
        )
        is_fp, reason = filter.is_false_positive("forty-one large customers", number)
        assert is_fp is False


# =============================================================================
# Temporal Spelled-Number Filter Tests
# =============================================================================


class TestTemporalSpelledNumberFilter:
    """Spelled-out numbers adjacent to temporal units should be filtered."""

    @pytest.fixture
    def filter(self):
        return FalsePositiveFilter()

    def test_twelve_months_filtered(self, filter):
        """'twelve months prior' should be filtered as reference_number."""
        number = NumberMatch(
            start=0, end=6, raw_text="twelve", value=Decimal("12"), unit="count"
        )
        is_fp, reason = filter.is_false_positive("twelve months prior to the offering", number)
        assert is_fp is True
        assert reason == "reference_number"

    def test_twenty_four_months_filtered(self, filter):
        """'twenty-four months' should be filtered as reference_number."""
        number = NumberMatch(
            start=0, end=11, raw_text="twenty-four", value=Decimal("24"), unit="count"
        )
        is_fp, reason = filter.is_false_positive(
            "twenty-four months ended December 31, 2023", number
        )
        assert is_fp is True
        assert reason == "reference_number"

    def test_twelve_customers_not_filtered(self, filter):
        """'twelve customers' has no temporal unit — should NOT be filtered here."""
        number = NumberMatch(
            start=0, end=6, raw_text="twelve", value=Decimal("12"), unit="count"
        )
        # Note: may still be filtered by spelled_out_no_magnitude for value <= 9,
        # but 12 > 9 so it is not filtered by that rule.
        is_fp, reason = filter.is_false_positive("twelve enterprise customers", number)
        # Should not be filtered by the temporal pattern
        assert reason != "reference_number"

    def test_twelve_million_users_not_filtered(self, filter):
        """'twelve million' has magnitude — bypasses spelled_out_no_magnitude anyway."""
        number = NumberMatch(
            start=0, end=14, raw_text="twelve million", value=Decimal("12000000"), unit="count"
        )
        is_fp, reason = filter.is_false_positive("twelve million users", number)
        assert is_fp is False


# =============================================================================
# Fortune/Forbes List Filter Tests
# =============================================================================


class TestFortuneForbesListFilter:
    """Numbers in Fortune/Forbes list references should be filtered."""

    @pytest.fixture
    def filter(self):
        return FalsePositiveFilter()

    def test_fortune_100_number_filtered(self, filter):
        """'65 of the Fortune 100' — 65 should be filtered."""
        text = "65 of the Fortune 100 companies use our platform"
        number = NumberMatch(
            start=0, end=2, raw_text="65", value=Decimal("65"), unit="count"
        )
        is_fp, reason = filter.is_false_positive(text, number)
        assert is_fp is True
        assert reason == "reference_number"

    def test_fortune_500_rank_filtered(self, filter):
        """'companies in the Fortune 500' — 500 should be filtered."""
        text = "companies in the Fortune 500"
        number = NumberMatch(
            start=25, end=28, raw_text="500", value=Decimal("500"), unit="count"
        )
        is_fp, reason = filter.is_false_positive(text, number)
        assert is_fp is True
        assert reason == "reference_number"

    def test_unrelated_number_not_filtered(self, filter):
        """'50,000 customers' has no Fortune context — should NOT be filtered."""
        text = "We had 50,000 active customers"
        number = NumberMatch(
            start=7, end=13, raw_text="50,000", value=Decimal("50000"), unit="count"
        )
        is_fp, reason = filter.is_false_positive(text, number)
        assert is_fp is False


# =============================================================================
# Negative Assertion Filter Tests
# =============================================================================


class TestNegativeAssertionFilter:
    """Numbers that are thresholds in negative concentration assertions should be filtered."""

    @pytest.fixture
    def filter(self):
        return FalsePositiveFilter()

    def test_no_single_customer_exceeded(self, filter):
        """'No single customer amounted for more than 10%' — 10 filtered."""
        text = "No single customer amounted for more than 10% of Group revenues"
        number = NumberMatch(
            start=41, end=43, raw_text="10", value=Decimal("10"), unit="percent"
        )
        is_fp, reason = filter.is_false_positive(text, number)
        assert is_fp is True
        assert reason == "reference_number"

    def test_no_customer_exceeded(self, filter):
        """'no customer exceeded 10% of revenue' — 10 filtered."""
        text = "no customer exceeded 10% of revenue"
        number = NumberMatch(
            start=21, end=23, raw_text="10", value=Decimal("10"), unit="percent"
        )
        is_fp, reason = filter.is_false_positive(text, number)
        assert is_fp is True
        assert reason == "reference_number"

    def test_none_of_customers_accounted(self, filter):
        """'None of our customers accounted for more than 10%' — 10 filtered."""
        text = "None of our customers accounted for more than 10% of our total revenue"
        number = NumberMatch(
            start=46, end=48, raw_text="10", value=Decimal("10"), unit="percent"
        )
        is_fp, reason = filter.is_false_positive(text, number)
        assert is_fp is True
        assert reason == "reference_number"

    def test_largest_customer_represented_not_filtered(self, filter):
        """'our largest customer represented 15%' — positive assertion, should NOT filter."""
        text = "our largest customer represented 15% of revenue in fiscal 2023"
        number = NumberMatch(
            start=33, end=35, raw_text="15", value=Decimal("15"), unit="percent"
        )
        is_fp, reason = filter.is_false_positive(text, number)
        assert is_fp is False

    def test_customer_exceeded_spend_not_filtered(self, filter):
        """'a customer exceeded $100,000 in annual spend' — positive, should NOT filter."""
        text = "a customer exceeded $100,000 in annual spend"
        number = NumberMatch(
            start=21, end=27, raw_text="100000", value=Decimal("100000"), unit="count"
        )
        is_fp, reason = filter.is_false_positive(text, number)
        assert is_fp is False

    def test_nearby_metric_not_filtered_by_assertion(self, filter):
        """Metric in same context as negative assertion should NOT be filtered if not the threshold."""
        # NRR of 158% is a real metric; the 10% concentration threshold is separate
        text = "Our net revenue retention rate was 158%. No single customer represented more than 10% of revenue."
        number = NumberMatch(
            start=35, end=38, raw_text="158", value=Decimal("158"), unit="percent"
        )
        is_fp, reason = filter.is_false_positive(text, number)
        assert is_fp is False
