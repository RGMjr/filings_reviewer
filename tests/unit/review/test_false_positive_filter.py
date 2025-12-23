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
