"""
Unit tests for number_parsing module.

Tests extracted from test_candidate_generator.py as part of P1.3 module splitting.
"""

from decimal import Decimal
import pytest

from src.review.number_parsing import NUMBER_REGEX, NumberMatch, NumberParser


# =============================================================================
# NUMBER_REGEX Tests
# =============================================================================


class TestNumberRegex:
    """Tests for the NUMBER_REGEX pattern."""

    def test_simple_integer(self):
        """Match simple integer."""
        text = "We have 1234 customers"
        matches = list(NUMBER_REGEX.finditer(text))
        assert len(matches) == 1
        assert matches[0].group("number") == "1234"

    def test_integer_with_commas(self):
        """Match integer with comma separators."""
        text = "Revenue was 1,234,567 dollars"
        matches = list(NUMBER_REGEX.finditer(text))
        assert len(matches) == 1
        assert matches[0].group("number") == "1,234,567"

    def test_decimal_number(self):
        """Match decimal numbers."""
        text = "Growth rate of 12.5 percent"
        matches = list(NUMBER_REGEX.finditer(text))
        assert len(matches) == 1
        assert matches[0].group("number") == "12.5"

    def test_currency_prefix(self):
        """Match currency with dollar sign."""
        text = "We earned $45.6 million"
        matches = list(NUMBER_REGEX.finditer(text))
        assert len(matches) == 1
        assert matches[0].group("currency") == "$"
        assert matches[0].group("number") == "45.6"
        assert matches[0].group("suffix").lower() == "million"

    def test_percentage_suffix(self):
        """Match percentage suffix."""
        text = "Retention rate was 95%"
        matches = list(NUMBER_REGEX.finditer(text))
        assert len(matches) == 1
        assert matches[0].group("number") == "95"
        assert matches[0].group("suffix") == "%"

    def test_million_suffix(self):
        """Match million suffix."""
        text = "ARR of 500 million"
        matches = list(NUMBER_REGEX.finditer(text))
        assert len(matches) == 1
        assert matches[0].group("number") == "500"
        assert matches[0].group("suffix").lower() == "million"

    def test_billion_suffix(self):
        """Match billion suffix."""
        text = "$2.5 billion revenue"
        matches = list(NUMBER_REGEX.finditer(text))
        assert len(matches) == 1
        assert matches[0].group("currency") == "$"
        assert matches[0].group("number") == "2.5"
        assert matches[0].group("suffix").lower() == "billion"

    def test_negative_number(self):
        """Match negative numbers."""
        text = "Loss of -45 million"
        matches = list(NUMBER_REGEX.finditer(text))
        assert len(matches) == 1
        assert matches[0].group("number") == "-45"

    def test_multiple_numbers(self):
        """Match multiple numbers in text."""
        text = "We had 1,000 customers and $2.5 million revenue"
        matches = list(NUMBER_REGEX.finditer(text))
        assert len(matches) == 2
        assert matches[0].group("number") == "1,000"
        assert matches[1].group("currency") == "$"
        assert matches[1].group("number") == "2.5"


# =============================================================================
# NumberParser.parse_number Tests
# =============================================================================


class TestParseNumber:
    """Tests for NumberParser.parse_number method."""

    @pytest.fixture
    def parser(self):
        """Create a NumberParser instance."""
        return NumberParser()

    def test_parse_simple_integer(self, parser):
        """Parse simple integer."""
        value, unit = parser.parse_number("1234")
        assert value == Decimal("1234")
        assert unit == "count"

    def test_parse_with_commas(self, parser):
        """Parse number with commas."""
        value, unit = parser.parse_number("1,234,567")
        assert value == Decimal("1234567")
        assert unit == "count"

    def test_parse_decimal(self, parser):
        """Parse decimal number."""
        value, unit = parser.parse_number("12.5")
        assert value == Decimal("12.5")
        assert unit == "count"

    def test_parse_currency(self, parser):
        """Parse currency value."""
        value, unit = parser.parse_number("45.6", currency="$")
        assert value == Decimal("45.6")
        assert unit == "usd"

    def test_parse_percentage(self, parser):
        """Parse percentage value."""
        value, unit = parser.parse_number("95", suffix="%")
        assert value == Decimal("0.95")  # Converted to decimal
        assert unit == "%"

    def test_parse_million_multiplier(self, parser):
        """Parse number with million suffix."""
        value, unit = parser.parse_number("45.6", suffix="million")
        assert value == Decimal("45600000")
        assert unit == "count"

    def test_parse_billion_multiplier(self, parser):
        """Parse number with billion suffix."""
        value, unit = parser.parse_number("2.5", suffix="billion")
        assert value == Decimal("2500000000")
        assert unit == "count"

    def test_parse_thousand_multiplier(self, parser):
        """Parse number with thousand suffix."""
        value, unit = parser.parse_number("50", suffix="thousand")
        assert value == Decimal("50000")
        assert unit == "count"


# =============================================================================
# NumberParser.find_numbers Tests
# =============================================================================


class TestFindNumbers:
    """Tests for NumberParser.find_numbers method."""

    @pytest.fixture
    def parser(self):
        """Create a NumberParser instance."""
        return NumberParser()

    def test_find_single_number(self, parser):
        """Find single number in text."""
        text = "We have 10,000 active customers"
        numbers = parser.find_numbers(text)

        assert len(numbers) == 1
        assert numbers[0].raw_text == "10,000"
        assert numbers[0].value == Decimal("10000")
        assert numbers[0].unit == "count"

    def test_find_multiple_numbers(self, parser):
        """Find multiple numbers in text."""
        text = "We have 10,000 customers and $5.2 million in revenue"
        numbers = parser.find_numbers(text)

        assert len(numbers) == 2

        # First number
        assert numbers[0].raw_text == "10,000"
        assert numbers[0].value == Decimal("10000")

        # Second number
        assert numbers[1].raw_text == "$5.2 million"
        assert numbers[1].value == Decimal("5200000")
        assert numbers[1].unit == "usd"

    def test_find_numbers_with_positions(self, parser):
        """Verify positions are correct."""
        text = "Revenue: $100 million"
        numbers = parser.find_numbers(text)

        assert len(numbers) == 1
        assert numbers[0].start == text.index("$")
        assert text[numbers[0].start : numbers[0].end] == numbers[0].raw_text

    def test_finds_all_numbers_including_dates(self, parser):
        """
        NumberParser finds ALL numbers - no filtering.

        This is correct behavior - filtering happens in false_positive_filter.
        """
        text = "As of December 12, 2023, we had 50,000 active customers."
        numbers = parser.find_numbers(text)

        # Should find ALL numbers: 12, 2023, and 50,000
        assert len(numbers) == 3
        raw_texts = [n.raw_text for n in numbers]
        assert "12" in raw_texts
        assert "2023" in raw_texts
        assert "50,000" in raw_texts

    def test_finds_all_numbers_including_page_refs(self, parser):
        """NumberParser finds all numbers - page number filtering happens elsewhere."""
        text = "See page 123 for details. We had 50,000 customers."
        numbers = parser.find_numbers(text)

        # Should find both numbers - filtering is not NumberParser's job
        assert len(numbers) == 2
        raw_texts = [n.raw_text for n in numbers]
        assert "123" in raw_texts
        assert "50,000" in raw_texts
