"""
Unit tests for the number_parsing module.

Tests parse_number(), has_fractional_value(), scale multipliers,
and the year non-splitting regression (fix in 879f752).
"""

from __future__ import annotations

import pytest

from src.extraction_v2.models import Unit
from src.extraction_v2.stages.number_parsing import (
    SCALE_MULTIPLIERS,
    TABLE_SCALE_EXCEPT_PATTERN,
    TABLE_SCALE_MAP,
    TABLE_SCALE_PATTERN,
    has_fractional_value,
    parse_number,
)

# ============================================================================
# Basic Number Extraction
# ============================================================================


class TestBasicIntegers:
    def test_simple_integer(self) -> None:
        result = parse_number("42")
        assert result is not None
        value, unit, raw = result
        assert value == 42.0
        assert unit == Unit.OTHER

    def test_zero(self) -> None:
        result = parse_number("0")
        assert result is not None
        assert result[0] == 0.0

    def test_large_plain_integer(self) -> None:
        result = parse_number("1000000")
        assert result is not None
        assert result[0] == 1_000_000.0

    def test_comma_separated_integer(self) -> None:
        result = parse_number("1,234,567")
        assert result is not None
        value, unit, raw = result
        assert value == 1_234_567.0
        assert unit == Unit.OTHER

    def test_comma_separated_thousands(self) -> None:
        result = parse_number("50,000")
        assert result is not None
        assert result[0] == 50_000.0


class TestDecimals:
    def test_simple_decimal(self) -> None:
        result = parse_number("3.14")
        assert result is not None
        assert result[0] == pytest.approx(3.14)

    def test_decimal_with_commas(self) -> None:
        result = parse_number("1,234,567.89")
        assert result is not None
        assert result[0] == pytest.approx(1_234_567.89)

    def test_decimal_less_than_one(self) -> None:
        result = parse_number("0.75")
        assert result is not None
        assert result[0] == pytest.approx(0.75)


# ============================================================================
# Year Non-Splitting Regression (fix 879f752)
# ============================================================================


class TestYearNonSplitting:
    """Regression tests: a year like '2023' must not be split into fragments."""

    def test_year_2023_not_split(self) -> None:
        result = parse_number("2023")
        assert result is not None
        value, _, _ = result
        # Must parse as 2023, not 20, 23, 2, or 023 etc.
        assert value == 2023.0

    def test_year_2024_not_split(self) -> None:
        result = parse_number("2024")
        assert result is not None
        assert result[0] == 2024.0

    def test_year_in_sentence_not_split(self) -> None:
        result = parse_number("as of December 31, 2022")
        assert result is not None
        # Should parse the last number — could be 31 or 2022 depending on regex,
        # but it must NOT produce fragments like 20 or 22
        value = result[0]
        assert value in {31.0, 2022.0}

    def test_four_digit_year_is_single_match(self) -> None:
        result = parse_number("fiscal year 2021")
        assert result is not None
        assert result[0] == 2021.0


# ============================================================================
# Currency Symbol Detection
# ============================================================================


class TestCurrencySymbols:
    def test_dollar_sign(self) -> None:
        result = parse_number("$1,000")
        assert result is not None
        value, unit, _ = result
        assert value == 1_000.0
        assert unit == Unit.CURRENCY

    def test_euro_sign(self) -> None:
        result = parse_number("€500")
        assert result is not None
        _, unit, _ = result
        assert unit == Unit.CURRENCY

    def test_pound_sign(self) -> None:
        result = parse_number("£250")
        assert result is not None
        _, unit, _ = result
        assert unit == Unit.CURRENCY

    def test_dollar_with_decimal(self) -> None:
        result = parse_number("$1.2")
        assert result is not None
        value, unit, _ = result
        assert value == pytest.approx(1.2)
        assert unit == Unit.CURRENCY

    def test_no_currency_symbol_is_other(self) -> None:
        result = parse_number("500")
        assert result is not None
        _, unit, _ = result
        assert unit == Unit.OTHER


# ============================================================================
# Negative Numbers
# ============================================================================


class TestNegativeNumbers:
    def test_negative_plain(self) -> None:
        result = parse_number("-42")
        assert result is not None
        assert result[0] == -42.0

    def test_negative_currency(self) -> None:
        result = parse_number("-$100")
        assert result is not None
        value, unit, _ = result
        assert value == -100.0
        assert unit == Unit.CURRENCY

    def test_negative_large(self) -> None:
        result = parse_number("-1,000,000")
        assert result is not None
        assert result[0] == -1_000_000.0


# ============================================================================
# Percentage Parsing
# ============================================================================


class TestPercentage:
    def test_percent_symbol(self) -> None:
        result = parse_number("45.2%")
        assert result is not None
        value, unit, _ = result
        assert value == pytest.approx(45.2)
        assert unit == Unit.PERCENT

    def test_percent_integer(self) -> None:
        result = parse_number("100%")
        assert result is not None
        assert result[1] == Unit.PERCENT

    def test_percent_word(self) -> None:
        result = parse_number("12 percent")
        assert result is not None
        _, unit, _ = result
        assert unit == Unit.PERCENT

    def test_negative_percent(self) -> None:
        result = parse_number("-5%")
        assert result is not None
        value, unit, _ = result
        assert value == pytest.approx(-5.0)
        assert unit == Unit.PERCENT


# ============================================================================
# Scale Suffix Parsing
# ============================================================================


class TestScaleSuffixes:
    def test_million_suffix(self) -> None:
        result = parse_number("1.2 million")
        assert result is not None
        assert result[0] == pytest.approx(1_200_000.0)

    def test_billion_suffix(self) -> None:
        result = parse_number("2.5 billion")
        assert result is not None
        assert result[0] == pytest.approx(2_500_000_000.0)

    def test_thousand_suffix(self) -> None:
        result = parse_number("500 thousand")
        assert result is not None
        assert result[0] == pytest.approx(500_000.0)

    def test_mn_abbreviation(self) -> None:
        result = parse_number("$10mn")
        assert result is not None
        assert result[0] == pytest.approx(10_000_000.0)

    def test_bn_abbreviation(self) -> None:
        result = parse_number("$3bn")
        assert result is not None
        assert result[0] == pytest.approx(3_000_000_000.0)

    def test_k_abbreviation(self) -> None:
        result = parse_number("500k")
        assert result is not None
        assert result[0] == pytest.approx(500_000.0)

    def test_m_abbreviation_currency(self) -> None:
        result = parse_number("$5m")
        assert result is not None
        value, unit, _ = result
        assert value == pytest.approx(5_000_000.0)
        assert unit == Unit.CURRENCY

    def test_b_abbreviation(self) -> None:
        result = parse_number("1b")
        assert result is not None
        assert result[0] == pytest.approx(1_000_000_000.0)


# ============================================================================
# Raw Text Capture
# ============================================================================


class TestRawTextCapture:
    def test_raw_text_is_stripped(self) -> None:
        result = parse_number("  $1,000  ")
        assert result is not None
        _, _, raw = result
        assert raw == raw.strip()

    def test_raw_text_nonempty(self) -> None:
        result = parse_number("42")
        assert result is not None
        _, _, raw = result
        assert len(raw) > 0


# ============================================================================
# Edge Cases — No Match
# ============================================================================


class TestEdgeCasesNoMatch:
    def test_empty_string_returns_none(self) -> None:
        assert parse_number("") is None

    def test_text_only_returns_none(self) -> None:
        assert parse_number("no numbers here") is None

    def test_whitespace_only_returns_none(self) -> None:
        assert parse_number("   ") is None

    def test_special_chars_only_returns_none(self) -> None:
        assert parse_number("!@#$%^&*") is None


# ============================================================================
# Multiple Numbers in Text
# ============================================================================


class TestMultipleNumbers:
    def test_returns_first_match(self) -> None:
        # parse_number uses .search() so it returns first match
        result = parse_number("100 and 200")
        assert result is not None
        assert result[0] == 100.0

    def test_currency_context_wins(self) -> None:
        result = parse_number("Revenue was $5 million in 2022")
        assert result is not None
        # First number with currency symbol should be found
        value, unit, _ = result
        assert unit == Unit.CURRENCY
        assert value == pytest.approx(5_000_000.0)


# ============================================================================
# has_fractional_value()
# ============================================================================


class TestHasFractionalValue:
    def test_integer_string_is_false(self) -> None:
        assert has_fractional_value("948") is False

    def test_decimal_string_is_true(self) -> None:
        assert has_fractional_value("796.3") is True

    def test_integer_with_commas_is_false(self) -> None:
        assert has_fractional_value("1,234") is False

    def test_zero_point_zero_is_true(self) -> None:
        assert has_fractional_value("0.0") is True

    def test_empty_string_is_false(self) -> None:
        assert has_fractional_value("") is False


# ============================================================================
# Scale Multiplier Constants
# ============================================================================


class TestScaleMultiplierConstants:
    def test_thousand_multiplier(self) -> None:
        assert SCALE_MULTIPLIERS["thousand"] == 1_000
        assert SCALE_MULTIPLIERS["k"] == 1_000

    def test_million_multiplier(self) -> None:
        assert SCALE_MULTIPLIERS["million"] == 1_000_000
        assert SCALE_MULTIPLIERS["mn"] == 1_000_000
        assert SCALE_MULTIPLIERS["m"] == 1_000_000

    def test_billion_multiplier(self) -> None:
        assert SCALE_MULTIPLIERS["billion"] == 1_000_000_000
        assert SCALE_MULTIPLIERS["bn"] == 1_000_000_000
        assert SCALE_MULTIPLIERS["b"] == 1_000_000_000

    def test_table_scale_map_hundreds(self) -> None:
        assert TABLE_SCALE_MAP["hundreds"] == 100

    def test_table_scale_map_thousands(self) -> None:
        assert TABLE_SCALE_MAP["thousands"] == 1_000

    def test_table_scale_map_millions(self) -> None:
        assert TABLE_SCALE_MAP["millions"] == 1_000_000

    def test_table_scale_map_billions(self) -> None:
        assert TABLE_SCALE_MAP["billions"] == 1_000_000_000


# ============================================================================
# TABLE_SCALE_PATTERN
# ============================================================================


class TestTableScalePattern:
    def test_matches_in_thousands(self) -> None:
        assert TABLE_SCALE_PATTERN.search("(In thousands)") is not None

    def test_matches_in_millions(self) -> None:
        assert TABLE_SCALE_PATTERN.search("(In millions)") is not None

    def test_matches_amounts_in_millions(self) -> None:
        assert TABLE_SCALE_PATTERN.search("(amounts in millions)") is not None

    def test_no_match_plain_text(self) -> None:
        assert TABLE_SCALE_PATTERN.search("thousands of customers") is None

    def test_except_as_noted_pattern(self) -> None:
        assert TABLE_SCALE_EXCEPT_PATTERN.search("except as otherwise noted") is not None
        assert TABLE_SCALE_EXCEPT_PATTERN.search("except as noted") is not None
        assert TABLE_SCALE_EXCEPT_PATTERN.search("no qualifier here") is None
