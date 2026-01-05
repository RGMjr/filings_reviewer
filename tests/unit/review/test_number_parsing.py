"""
Unit tests for number_parsing module.

Tests extracted from test_candidate_generator.py as part of P1.3 module splitting.
"""

from decimal import Decimal

import pytest

from src.review.number_parsing import (
    NUMBER_REGEX,
    SPELLED_NUMBER_REGEX,
    NumberParser,
    parse_spelled_number,
)

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


# =============================================================================
# Spelled-Out Number Tests
# =============================================================================


class TestSpelledNumberRegex:
    """Tests for SPELLED_NUMBER_REGEX pattern."""

    def test_simple_spelled_numbers(self):
        """Match simple spelled-out numbers."""
        test_cases = [
            ("one", "one"),
            ("two", "two"),
            ("six", "six"),
            ("ten", "ten"),
            ("twenty", "twenty"),
        ]
        for text, expected in test_cases:
            matches = list(SPELLED_NUMBER_REGEX.finditer(text))
            assert len(matches) == 1, f"Failed to match: {text}"
            assert matches[0].group("spelled").lower() == expected

    def test_compound_numbers(self):
        """Match compound spelled-out numbers like twenty-one."""
        test_cases = [
            ("twenty-one", "twenty-one"),
            ("twenty one", "twenty one"),
            ("forty-five", "forty-five"),
            ("ninety-nine", "ninety-nine"),
        ]
        for text, expected in test_cases:
            matches = list(SPELLED_NUMBER_REGEX.finditer(text))
            assert len(matches) == 1, f"Failed to match: {text}"
            assert matches[0].group("spelled").lower() == expected.lower()

    def test_magnitude_words(self):
        """Match spelled numbers with magnitude words."""
        test_cases = [
            ("five million", "million"),
            ("ten billion", "billion"),
            ("two thousand", "thousand"),
        ]
        for text, expected_mag in test_cases:
            matches = list(SPELLED_NUMBER_REGEX.finditer(text))
            assert len(matches) == 1, f"Failed to match: {text}"
            assert matches[0].group("magnitude").lower() == expected_mag

    def test_case_insensitive(self):
        """Match spelled numbers regardless of case."""
        # Note: "MILLION" alone isn't a number - it's a magnitude modifier
        # The regex requires a base number (one, two, etc.) with optional magnitude
        for text in ["Six", "SIX", "Twenty-One", "FIVE MILLION"]:
            matches = list(SPELLED_NUMBER_REGEX.finditer(text))
            assert len(matches) >= 1, f"Failed to match: {text}"


class TestParseSpelledNumber:
    """Tests for parse_spelled_number function."""

    def test_simple_numbers(self):
        """Parse simple spelled-out numbers."""
        assert parse_spelled_number("one") == 1
        assert parse_spelled_number("six") == 6
        assert parse_spelled_number("ten") == 10
        assert parse_spelled_number("zero") == 0

    def test_teens(self):
        """Parse teen numbers."""
        assert parse_spelled_number("eleven") == 11
        assert parse_spelled_number("fifteen") == 15
        assert parse_spelled_number("nineteen") == 19

    def test_compound_numbers(self):
        """Parse compound numbers like twenty-one."""
        assert parse_spelled_number("twenty-one") == 21
        assert parse_spelled_number("twenty one") == 21
        assert parse_spelled_number("forty-five") == 45
        assert parse_spelled_number("ninety-nine") == 99

    def test_magnitude_words(self):
        """Parse numbers with magnitude words."""
        assert parse_spelled_number("five million") == 5_000_000
        assert parse_spelled_number("ten billion") == 10_000_000_000
        assert parse_spelled_number("two thousand") == 2_000
        assert parse_spelled_number("one trillion") == 1_000_000_000_000

    def test_case_insensitive(self):
        """Parse spelled numbers regardless of case."""
        assert parse_spelled_number("SIX") == 6
        assert parse_spelled_number("Six") == 6
        assert parse_spelled_number("FIVE MILLION") == 5_000_000

    def test_invalid_input(self):
        """Return None for invalid input."""
        assert parse_spelled_number("foobar") is None
        assert parse_spelled_number("1234") is None
        assert parse_spelled_number("") is None

    def test_hundred(self):
        """Parse hundred as multiplier."""
        assert parse_spelled_number("hundred") == 100
        assert parse_spelled_number("one hundred") == 100
        assert parse_spelled_number("two hundred") == 200


class TestFindSpelledNumbers:
    """Tests for NumberParser finding spelled-out numbers."""

    @pytest.fixture
    def parser(self):
        """Create a NumberParser instance with spelled number support."""
        return NumberParser(include_spelled=True)

    @pytest.fixture
    def parser_no_spelled(self):
        """Create a NumberParser without spelled number support."""
        return NumberParser(include_spelled=False)

    def test_find_spelled_number_in_text(self, parser):
        """Find spelled-out number in text."""
        text = "The payback period on CAC is six months."
        numbers = parser.find_numbers(text)

        spelled = [n for n in numbers if n.raw_text.lower() == "six"]
        assert len(spelled) == 1
        assert spelled[0].value == Decimal("6")
        assert spelled[0].unit == "count"

    def test_find_spelled_number_with_magnitude(self, parser):
        """Find spelled-out number with magnitude word."""
        text = "We have ten million active users."
        numbers = parser.find_numbers(text)

        spelled = [n for n in numbers if "million" in n.raw_text.lower()]
        assert len(spelled) == 1
        assert spelled[0].value == Decimal("10000000")

    def test_mixed_numeric_and_spelled(self, parser):
        """Find both numeric and spelled numbers."""
        text = "We had $50,000 revenue and six new customers."
        numbers = parser.find_numbers(text)

        # Should find both: $50,000 and "six"
        raw_texts = [n.raw_text.lower() for n in numbers]
        assert any("50,000" in t for t in raw_texts)
        assert "six" in raw_texts

    def test_spelled_numbers_disabled(self, parser_no_spelled):
        """When disabled, don't find spelled numbers."""
        text = "The payback period is six months."
        numbers = parser_no_spelled.find_numbers(text)

        spelled = [n for n in numbers if n.raw_text.lower() == "six"]
        assert len(spelled) == 0

    def test_no_overlap_with_numeric(self, parser):
        """Spelled number pattern shouldn't overlap with numeric matches."""
        # "ten" appears in "10" which shouldn't cause issues
        text = "We had 10 million customers."
        numbers = parser.find_numbers(text)

        # Should find "10 million" as a single numeric match
        assert len(numbers) == 1
        assert numbers[0].value == Decimal("10000000")
