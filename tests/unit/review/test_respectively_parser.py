"""Tests for respectively_parser module (L1)."""

import pytest
from src.review.respectively_parser import (
    detect_respectively_pattern,
    RespectivelyMatch,
    _extract_value_list,
    _extract_period_list,
    _calculate_confidence,
)


class TestRespectivelyPatternDetection:
    """Core pattern detection tests."""

    def test_basic_year_value_pattern(self):
        """Standard pattern: years then values then respectively."""
        text = "Gross margin for 2015, 2016 and 2017 was 33%, 35% and 43%, respectively."
        result = detect_respectively_pattern(text)

        assert result is not None
        assert result.values == ["33%", "35%", "43%"]
        assert result.periods == ["2015", "2016", "2017"]
        assert result.associations == [
            ("33%", "2015"),
            ("35%", "2016"),
            ("43%", "2017"),
        ]

    def test_complex_date_pattern(self):
        """Pattern with 'years ended December 31' preamble."""
        text = (
            "For the years ended December 31, 2015, 2016 and 2017, "
            "revenue was $1M, $2M and $3M, respectively."
        )
        result = detect_respectively_pattern(text)

        assert result is not None
        assert len(result.associations) == 3
        assert result.periods == ["2015", "2016", "2017"]
        assert result.values == ["$1M", "$2M", "$3M"]

    def test_quarter_pattern(self):
        """Pattern with quarters instead of years."""
        text = "Revenue for Q1, Q2 and Q3 was $10M, $12M and $15M, respectively."
        result = detect_respectively_pattern(text)

        assert result is not None
        assert len(result.periods) == 3
        assert all("Q" in period for period in result.periods)
        assert result.values == ["$10M", "$12M", "$15M"]

    def test_currency_values(self):
        """Pattern with currency values."""
        text = (
            "Cost was $1.2 million, $1.5 million and $1.8 million for "
            "2016, 2017 and 2018, respectively."
        )
        result = detect_respectively_pattern(text)

        assert result is not None
        assert len(result.associations) == 3
        # Values and periods should be associated correctly
        assert result.periods == ["2016", "2017", "2018"]
        assert len(result.values) == 3

    def test_no_respectively_returns_none(self):
        """Text without 'respectively' returns None."""
        text = "Revenue was $1M in 2015 and $2M in 2016."
        result = detect_respectively_pattern(text)
        assert result is None

    def test_mismatched_list_lengths_returns_none(self):
        """Unequal list lengths return None."""
        text = "Revenue for 2015 and 2016 was $1M, $2M and $3M, respectively."
        result = detect_respectively_pattern(text)
        # 2 periods vs 3 values - should return None
        assert result is None

    def test_single_item_not_respectively_pattern(self):
        """Single item is not a 'respectively' pattern."""
        text = "Revenue was $1M, respectively."
        result = detect_respectively_pattern(text)
        # Single value, no list of periods - should return None
        assert result is None

    def test_two_item_lists(self):
        """Pattern with two-item lists (minimum for a list)."""
        text = "Margin for 2015 and 2016 was 33% and 35%, respectively."
        result = detect_respectively_pattern(text)

        assert result is not None
        assert result.values == ["33%", "35%"]
        assert result.periods == ["2015", "2016"]
        assert len(result.associations) == 2


class TestConfidenceScoring:
    """Tests for confidence score calculation."""

    def test_high_confidence_clear_pattern(self):
        """Clear pattern with consecutive years gets high confidence."""
        text = "Margin for 2015, 2016 and 2017 was 33%, 35% and 43%, respectively."
        result = detect_respectively_pattern(text)

        assert result is not None
        assert result.confidence >= 0.7
        # Should have high confidence due to:
        # - Consecutive years
        # - Consistent format (all percentages)
        # - Clear "and" separators

    def test_confidence_with_consecutive_years(self):
        """Consecutive years increase confidence."""
        text1 = "Revenue for 2015, 2016 and 2017 was $1M, $2M and $3M, respectively."
        result1 = detect_respectively_pattern(text1)

        text2 = "Revenue for 2015, 2018 and 2020 was $1M, $2M and $3M, respectively."
        result2 = detect_respectively_pattern(text2)

        # Both should succeed, but consecutive years should have higher confidence
        assert result1 is not None
        assert result2 is not None
        assert result1.confidence > result2.confidence

    def test_confidence_with_consistent_formats(self):
        """Consistent value formats increase confidence."""
        values = ["33%", "35%", "43%"]
        periods = ["2015", "2016", "2017"]
        context = "for 2015, 2016 and 2017 was 33%, 35% and 43%"

        confidence = _calculate_confidence(values, periods, context)

        # All percentages should contribute to confidence
        assert confidence > 0.5


class TestEdgeCases:
    """Edge case tests."""

    def test_respectively_capitalized(self):
        """Handles 'Respectively' (capitalized)."""
        text = "Revenue was $1M, $2M and $3M for 2015, 2016 and 2017, Respectively."
        result = detect_respectively_pattern(text)

        # Should still detect despite capitalization
        assert result is not None

    def test_respectively_with_period(self):
        """Handles 'respectively.' at end of sentence."""
        text = "Margin for 2015 and 2016 was 33% and 35%, respectively."
        result = detect_respectively_pattern(text)

        assert result is not None
        assert len(result.associations) == 2

    def test_multiple_respectively_returns_first(self):
        """Multiple 'respectively' patterns - detects first pattern."""
        text = (
            "Revenue for 2015 and 2016 was $1M and $2M, respectively. "
            "Margin for 2017 and 2018 was 30% and 35%, respectively."
        )
        result = detect_respectively_pattern(text)

        # Should detect the first pattern
        assert result is not None
        assert result.values == ["$1M", "$2M"]
        assert result.periods == ["2015", "2016"]

    def test_whitespace_variations(self):
        """Handles various whitespace patterns."""
        text = "Revenue for 2015,2016 and 2017 was $1M,$2M and $3M,respectively."
        result = detect_respectively_pattern(text)

        # Should handle tight spacing
        assert result is not None
        assert len(result.associations) == 3

    def test_decimal_values(self):
        """Handles decimal number values."""
        text = "Ratio for 2015, 2016 and 2017 was 1.42, 1.53 and 1.72, respectively."
        result = detect_respectively_pattern(text)

        assert result is not None
        assert len(result.values) == 3
        assert "1.42" in result.values[0]


class TestRealWorldExamples:
    """Tests using actual SEC filing examples."""

    def test_farfetch_ltv_cac_pattern(self):
        """Real example from Farfetch Ltd filing."""
        text = (
            "Six month LTV/CAC ratio for the years ended December 31, "
            "2015, 2016 and 2017 cohorts was 1.42, 1.53 and 1.72, respectively"
        )
        result = detect_respectively_pattern(text)

        assert result is not None
        assert len(result.values) == 3
        assert result.periods == ["2015", "2016", "2017"]
        # Values might have different formatting, just check count
        assert len(result.associations) == 3

    def test_farfetch_margin_pattern(self):
        """Real example from Farfetch Ltd filing."""
        text = (
            "Platform Order Contribution Margin for the years ended "
            "December 31, 2015, 2016 and 2017 was 33.0%, 35.0% and 43.0%, "
            "respectively."
        )
        result = detect_respectively_pattern(text)

        assert result is not None
        assert result.periods == ["2015", "2016", "2017"]
        assert len(result.values) == 3
        # Check that all values are percentages
        assert all("%" in v for v in result.values)

    def test_spelled_out_quarters(self):
        """Pattern with spelled out quarters."""
        text = (
            "Revenue for first quarter, second quarter and third quarter "
            "was $10M, $12M and $15M, respectively."
        )
        result = detect_respectively_pattern(text)

        assert result is not None
        assert len(result.periods) == 3
        assert len(result.associations) == 3


class TestHelperFunctions:
    """Tests for internal helper functions."""

    def test_extract_value_list_basic(self):
        """Extract basic value list."""
        text = "was 33%, 35% and 43%"
        values = _extract_value_list(text)

        assert values == ["33%", "35%", "43%"]

    def test_extract_value_list_currency(self):
        """Extract currency value list."""
        text = "revenue was $1M, $2M and $3M"
        values = _extract_value_list(text)

        assert len(values) == 3
        assert all("$" in v for v in values)

    def test_extract_value_list_no_list(self):
        """Returns empty list when no valid list found."""
        text = "revenue was $1M"
        values = _extract_value_list(text)

        # Single value is not a list
        assert values == []

    def test_extract_period_list_years(self):
        """Extract year list."""
        text = "for 2015, 2016 and 2017"
        periods = _extract_period_list(text)

        assert periods == ["2015", "2016", "2017"]

    def test_extract_period_list_quarters(self):
        """Extract quarter list."""
        text = "for Q1, Q2 and Q3"
        periods = _extract_period_list(text)

        assert len(periods) == 3
        assert all("Q" in p for p in periods)

    def test_extract_period_list_complex_date(self):
        """Extract years from complex date pattern."""
        text = "years ended December 31, 2015, 2016 and 2017"
        periods = _extract_period_list(text)

        assert periods == ["2015", "2016", "2017"]

    def test_extract_period_list_no_list(self):
        """Returns empty list when no valid period list found."""
        text = "in 2015"
        periods = _extract_period_list(text)

        # Single period is not a list
        assert periods == []

    def test_calculate_confidence_base_score(self):
        """Confidence calculation returns reasonable base score."""
        values = ["$1M", "$2M"]
        periods = ["2015", "2016"]
        context = "for 2015 and 2016 was $1M and $2M"

        confidence = _calculate_confidence(values, periods, context)

        assert 0.0 <= confidence <= 1.0
        assert confidence >= 0.5  # Should have at least base score


class TestRespectivelyMatchDataclass:
    """Tests for RespectivelyMatch dataclass validation."""

    def test_valid_match_creation(self):
        """Can create valid RespectivelyMatch."""
        match = RespectivelyMatch(
            values=["33%", "35%"],
            periods=["2015", "2016"],
            associations=[("33%", "2015"), ("35%", "2016")],
            confidence=0.85,
            span=(0, 50)
        )

        assert match.values == ["33%", "35%"]
        assert match.confidence == 0.85

    def test_validation_mismatched_lengths(self):
        """Raises error if values and periods have different lengths."""
        with pytest.raises(ValueError, match="equal length"):
            RespectivelyMatch(
                values=["33%", "35%", "43%"],
                periods=["2015", "2016"],  # Only 2 periods
                associations=[("33%", "2015"), ("35%", "2016")],
                confidence=0.85,
                span=(0, 50)
            )

    def test_validation_confidence_out_of_range(self):
        """Raises error if confidence is out of range."""
        with pytest.raises(ValueError, match="between 0 and 1"):
            RespectivelyMatch(
                values=["33%", "35%"],
                periods=["2015", "2016"],
                associations=[("33%", "2015"), ("35%", "2016")],
                confidence=1.5,  # Invalid confidence
                span=(0, 50)
            )

    def test_validation_associations_length(self):
        """Raises error if associations length doesn't match values."""
        with pytest.raises(ValueError, match="Associations length"):
            RespectivelyMatch(
                values=["33%", "35%"],
                periods=["2015", "2016"],
                associations=[("33%", "2015")],  # Only 1 association
                confidence=0.85,
                span=(0, 50)
            )
