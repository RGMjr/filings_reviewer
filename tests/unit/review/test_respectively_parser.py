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

    def test_farfetch_ltv_cac_confidence(self):
        """Real example: LTV/CAC ratio should have high confidence."""
        text = (
            "Six month LTV/CAC ratio for the years ended December 31, "
            "2015, 2016 and 2017 cohorts was 1.42, 1.53 and 1.72, respectively"
        )
        result = detect_respectively_pattern(text)

        assert result is not None
        # Breakdown: Base 0.5 + consecutive 0.1 + "and" 0.2 + close 0.1 = 0.9
        assert result.confidence >= 0.85

    def test_farfetch_margin_confidence(self):
        """Real example: Platform margin should have high confidence."""
        text = (
            "Platform Order Contribution Margin for the years ended "
            "December 31, 2015, 2016 and 2017 was 33.0%, 35.0% and 43.0%, "
            "respectively."
        )
        result = detect_respectively_pattern(text)

        assert result is not None
        # Breakdown: Base 0.5 + consecutive 0.1 + "and" 0.2 + consistent 0.1 + close 0.1 = 1.0
        assert result.confidence >= 0.9

    def test_non_consecutive_years_lower_confidence(self):
        """Non-consecutive years should have lower confidence."""
        text1 = "Revenue for 2015, 2016 and 2017 was $1M, $2M and $3M, respectively."
        text2 = "Revenue for 2015, 2018 and 2022 was $1M, $2M and $3M, respectively."

        result1 = detect_respectively_pattern(text1)
        result2 = detect_respectively_pattern(text2)

        assert result1 is not None
        assert result2 is not None
        assert result1.confidence > result2.confidence

    def test_confidence_interpretation_documented(self):
        """Verify confidence values fall within documented ranges."""
        # High confidence pattern
        text = "Margin for 2015, 2016 and 2017 was 33%, 35% and 43%, respectively."
        result = detect_respectively_pattern(text)

        assert result is not None
        assert 0.8 <= result.confidence <= 1.0  # "High" range


class TestSentenceBoundaryRespect:
    """Tests for sentence boundary detection (P1.2)."""

    def test_cross_sentence_pattern_returns_none(self):
        """Values and periods in different sentences should not match."""
        text = (
            "Revenue grew in 2015, 2016 and 2017 as we expanded. "
            "Separately, gross margin was 33%, 35% and 43%, respectively."
        )
        result = detect_respectively_pattern(text)
        assert result is None  # Different sentences

    def test_same_sentence_pattern_matches(self):
        """Values and periods in same sentence should match."""
        text = (
            "Gross margin for 2015, 2016 and 2017 was "
            "33%, 35% and 43%, respectively."
        )
        result = detect_respectively_pattern(text)
        assert result is not None
        assert len(result.associations) == 3

    def test_sentence_with_abbreviation_not_split(self):
        """'Inc.' and 'Ltd.' should not split sentences."""
        text = (
            "Revenue for Acme Inc. for 2015, 2016 and 2017 was "
            "$1M, $2M and $3M, respectively."
        )
        result = detect_respectively_pattern(text)
        assert result is not None  # Single sentence despite "Inc."

    def test_sentence_with_decimal_not_split(self):
        """Decimal numbers (52.3%) should not split sentences."""
        text = (
            "Margin improved from 52.3% to 54.1% for 2015, 2016 and 2017 "
            "and was 33%, 35% and 43%, respectively."
        )
        result = detect_respectively_pattern(text)
        assert result is not None


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

    def test_very_long_distance_returns_none(self):
        """Lists separated by >200 chars should not match (P1.4)."""
        filler = " ".join(["word"] * 50)  # ~250 characters
        text = f"For 2015, 2016 and 2017 {filler} was 33%, 35% and 43%, respectively."

        result = detect_respectively_pattern(text)
        assert result is None  # Too far apart

    def test_distance_just_under_threshold_matches(self):
        """Lists separated by <200 chars should match (P1.4)."""
        filler = " ".join(["word"] * 35)  # ~180 characters
        text = f"For 2015, 2016 and 2017 {filler} was 33%, 35% and 43%, respectively."

        result = detect_respectively_pattern(text)
        assert result is not None  # Within threshold


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


class TestL1P11ConfigurableConfidenceFiltering:
    """Tests for L1-P1.1: Configurable confidence filtering."""

    def test_min_confidence_parameter_filters_low_confidence(self):
        """Should filter patterns below min_confidence threshold."""
        # This pattern has moderate confidence (~0.6-0.7)
        text = "For 2015 and 2016 was 33% and 35%, respectively."

        # Default min_confidence (0.6) should accept it
        result_default = detect_respectively_pattern(text)
        assert result_default is not None
        assert result_default.confidence >= 0.5

        # High min_confidence (0.9) should filter it
        result_high = detect_respectively_pattern(text, min_confidence=0.9)
        assert result_high is None

    def test_min_confidence_default_is_0_6(self):
        """Default min_confidence should be 0.6."""
        # Pattern with confidence ~0.7 should pass
        text = "Margin for 2015, 2016 and 2017 was 33%, 35% and 43%, respectively."
        result = detect_respectively_pattern(text)
        assert result is not None

    def test_high_confidence_pattern_passes_all_thresholds(self):
        """High confidence patterns should pass even strict thresholds."""
        # Farfetch pattern with high confidence (0.85-0.9)
        text = (
            "Six month LTV/CAC ratio for the years ended December 31, 2015, 2016 and 2017 cohorts "
            "was 1.42, 1.53 and 1.72, respectively"
        )

        # Should pass with default threshold
        result_default = detect_respectively_pattern(text)
        assert result_default is not None
        assert result_default.confidence >= 0.8

        # Should pass with strict threshold
        result_strict = detect_respectively_pattern(text, min_confidence=0.8)
        assert result_strict is not None
        assert result_strict.confidence >= 0.8

    def test_very_low_min_confidence_accepts_all(self):
        """Setting min_confidence=0.5 should accept all valid patterns."""
        # Simple pattern with lower confidence
        text = "For Q1 and Q2 was 10 and 20, respectively."

        result = detect_respectively_pattern(text, min_confidence=0.5)
        assert result is not None  # Should accept even low confidence
