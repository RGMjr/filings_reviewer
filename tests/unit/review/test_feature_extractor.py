"""
Unit tests for feature_extractor module.

Tests cover:
- FeatureExtractor class methods
- Pattern constants (validity, coverage)
- Module-level convenience functions
- Edge cases and error handling

Test Coverage Note (87% coverage is intentional):
=====================================================

The following exception handlers are intentionally NOT tested because they are
defensive code paths that cannot be reached with valid inputs:

1. Lines 152-153: AttributeError in context_text.split()
   - Line 124 coerces input to str, so split() always exists
   - Only reachable if str coercion is modified in future

2. Lines 208-210: ValueError/OverflowError/TypeError in math.log10()
   - Real Decimal objects convert to inf/nan, never raise exceptions
   - Verified empirically: Decimal("10")**10000 → inf, not OverflowError
   - Only reachable with broken mock objects

3. Lines 226-227: TypeError/AttributeError in pattern.search() (definition)
4. Lines 243-244: TypeError/AttributeError in pattern.search() (period)
5. Lines 276-277: TypeError/AttributeError in pattern.search() (risk factors)
   - isinstance(context_text, str) check ensures valid string before search
   - PATTERN lists are module-level compiled regexes, never broken
   - Only reachable if patterns are corrupted at runtime

These handlers provide protection if future code modifications introduce new
failure modes, but testing them would require complex mocking of impossible
scenarios. Testing defensive code through mocking provides minimal value and
creates brittle tests that don't reflect real-world behavior.

See commit 7e509a6 for detailed analysis of why 100% coverage was reverted.
"""

import math
from decimal import Decimal

import pytest

from src.review.feature_extractor import (
    DEFINITION_PATTERNS,
    PERIOD_PATTERNS,
    RISK_FACTORS_PATTERNS,
    FeatureExtractor,
    compute_features,
    determine_number_format,
)
from src.review.models import CandidateFeatures


# =============================================================================
# TestFeatureExtractor - Basic feature computation
# =============================================================================


class TestFeatureExtractor:
    """Tests for FeatureExtractor class."""

    def test_compute_features_basic(self):
        """Should compute all features for a basic candidate."""
        extractor = FeatureExtractor()
        features = extractor.compute_features(
            number_value=Decimal("10000"),
            number_unit="count",
            number_raw_text="10,000",
            keyword_distance=15,
            keyword_position="after",
            context_text="We have 10,000 active customers.",
        )

        assert isinstance(features, CandidateFeatures)
        assert features.keyword_distance == 15
        assert features.keyword_position == "after"
        assert features.number_format == "integer"
        assert features.is_in_table is False
        assert features.context_word_count == 5

    def test_compute_features_with_definition_language(self):
        """Should detect definition language in context."""
        extractor = FeatureExtractor()
        features = extractor.compute_features(
            number_value=Decimal("5000"),
            number_unit=None,
            number_raw_text="5000",
            keyword_distance=20,
            keyword_position="before",
            context_text="We define active customers as those who logged in within 5000 days.",
        )

        assert features.contains_definition_language is True

    def test_compute_features_without_definition_language(self):
        """Should not detect definition language when absent."""
        extractor = FeatureExtractor()
        features = extractor.compute_features(
            number_value=Decimal("5000"),
            number_unit=None,
            number_raw_text="5000",
            keyword_distance=20,
            keyword_position="before",
            context_text="Our customers numbered 5000 last quarter.",
        )

        assert features.contains_definition_language is False

    def test_compute_features_with_period_mention(self):
        """Should detect period mentions in context."""
        extractor = FeatureExtractor()
        features = extractor.compute_features(
            number_value=Decimal("1000"),
            number_unit=None,
            number_raw_text="1000",
            keyword_distance=10,
            keyword_position="after",
            context_text="For the fiscal year ended December 2023, we had 1000 customers.",
        )

        assert features.has_period_mention is True

    def test_compute_features_in_table(self):
        """Should detect table context from segment_type."""
        extractor = FeatureExtractor()
        features = extractor.compute_features(
            number_value=Decimal("500"),
            number_unit=None,
            number_raw_text="500",
            keyword_distance=5,
            keyword_position="after",
            context_text="Customers | 500",
            segment_type="table",
        )

        assert features.is_in_table is True

    def test_compute_features_not_in_table(self):
        """Should not detect table when segment_type is paragraph."""
        extractor = FeatureExtractor()
        features = extractor.compute_features(
            number_value=Decimal("500"),
            number_unit=None,
            number_raw_text="500",
            keyword_distance=5,
            keyword_position="after",
            context_text="We have 500 customers.",
            segment_type="paragraph",
        )

        assert features.is_in_table is False

    def test_compute_features_in_risk_factors_from_heading(self):
        """Should detect risk factors from section heading."""
        extractor = FeatureExtractor()
        features = extractor.compute_features(
            number_value=Decimal("100"),
            number_unit=None,
            number_raw_text="100",
            keyword_distance=30,
            keyword_position="before",
            context_text="Some context text",
            section_heading="Risk Factors",
        )

        assert features.is_in_risk_factors is True

    def test_compute_features_in_risk_factors_from_path(self):
        """Should detect risk factors from section path."""
        extractor = FeatureExtractor()
        features = extractor.compute_features(
            number_value=Decimal("100"),
            number_unit=None,
            number_raw_text="100",
            keyword_distance=30,
            keyword_position="before",
            context_text="Some context text",
            section_path="Part I / Item 1A. Risk Factors",
        )

        assert features.is_in_risk_factors is True

    def test_compute_features_in_risk_factors_from_context(self):
        """Should detect risk factors from context patterns."""
        extractor = FeatureExtractor()
        features = extractor.compute_features(
            number_value=Decimal("100"),
            number_unit=None,
            number_raw_text="100",
            keyword_distance=30,
            keyword_position="before",
            context_text="We may not be able to retain 100 customers.",
        )

        assert features.is_in_risk_factors is True

    def test_compute_features_with_section_name(self):
        """Should capture section name from section_heading."""
        extractor = FeatureExtractor()
        features = extractor.compute_features(
            number_value=Decimal("100"),
            number_unit=None,
            number_raw_text="100",
            keyword_distance=10,
            keyword_position="after",
            context_text="Test context",
            section_heading="Business Overview",
        )

        assert features.section_name == "Business Overview"

    def test_compute_features_surrounding_numbers_count(self):
        """Should pass through surrounding_numbers_count."""
        extractor = FeatureExtractor()
        features = extractor.compute_features(
            number_value=Decimal("100"),
            number_unit=None,
            number_raw_text="100",
            keyword_distance=10,
            keyword_position="after",
            context_text="Test context",
            surrounding_numbers_count=5,
        )

        assert features.surrounding_numbers_count == 5


# =============================================================================
# TestDetermineNumberFormat - Format detection
# =============================================================================


class TestDetermineNumberFormat:
    """Tests for number format determination."""

    def test_percentage_format(self):
        """Should return 'percentage' for % unit."""
        extractor = FeatureExtractor()
        assert extractor.determine_number_format("%", "15%") == "percentage"

    def test_percentage_format_with_number(self):
        """Should return 'percentage' for % unit regardless of text."""
        extractor = FeatureExtractor()
        assert extractor.determine_number_format("%", "15.5") == "percentage"

    def test_currency_format(self):
        """Should return 'currency' for usd unit."""
        extractor = FeatureExtractor()
        assert extractor.determine_number_format("usd", "$1,000") == "currency"

    def test_currency_format_with_decimal(self):
        """Should return 'currency' for usd unit even with decimal."""
        extractor = FeatureExtractor()
        assert extractor.determine_number_format("usd", "$1,000.50") == "currency"

    def test_decimal_format(self):
        """Should return 'decimal' when raw text has decimal point."""
        extractor = FeatureExtractor()
        assert extractor.determine_number_format(None, "3.14") == "decimal"

    def test_decimal_format_with_count_unit(self):
        """Should return 'decimal' when raw text has decimal point."""
        extractor = FeatureExtractor()
        assert extractor.determine_number_format("count", "3.14") == "decimal"

    def test_integer_format(self):
        """Should return 'integer' for plain numbers."""
        extractor = FeatureExtractor()
        assert extractor.determine_number_format(None, "10000") == "integer"

    def test_integer_with_commas(self):
        """Should return 'integer' for comma-separated numbers."""
        extractor = FeatureExtractor()
        assert extractor.determine_number_format("count", "10,000") == "integer"

    def test_integer_with_none_raw_text(self):
        """Should handle None raw_text gracefully."""
        extractor = FeatureExtractor()
        # Should default to integer when raw_text is None
        assert extractor.determine_number_format(None, None) == "integer"


# =============================================================================
# TestValueMagnitude - Log10 computation
# =============================================================================


class TestValueMagnitude:
    """Tests for value magnitude computation."""

    def test_magnitude_positive_integer(self):
        """log10(10000) should be 4.0."""
        extractor = FeatureExtractor()
        features = extractor.compute_features(
            number_value=Decimal("10000"),
            number_unit=None,
            number_raw_text="10000",
            keyword_distance=10,
            keyword_position="after",
            context_text="Test",
        )
        assert features.value_magnitude == pytest.approx(4.0)

    def test_magnitude_decimal_value(self):
        """log10(1000.5) should be approximately 3.0."""
        extractor = FeatureExtractor()
        features = extractor.compute_features(
            number_value=Decimal("1000.5"),
            number_unit=None,
            number_raw_text="1000.5",
            keyword_distance=10,
            keyword_position="after",
            context_text="Test",
        )
        assert features.value_magnitude == pytest.approx(3.0, rel=0.01)

    def test_magnitude_negative_value(self):
        """Should use absolute value for negative numbers."""
        extractor = FeatureExtractor()
        features = extractor.compute_features(
            number_value=Decimal("-1000"),
            number_unit=None,
            number_raw_text="-1000",
            keyword_distance=10,
            keyword_position="after",
            context_text="Test",
        )
        assert features.value_magnitude == pytest.approx(3.0)

    def test_magnitude_small_value(self):
        """log10(1) should be 0."""
        extractor = FeatureExtractor()
        features = extractor.compute_features(
            number_value=Decimal("1"),
            number_unit=None,
            number_raw_text="1",
            keyword_distance=10,
            keyword_position="after",
            context_text="Test",
        )
        assert features.value_magnitude == pytest.approx(0.0)

    def test_magnitude_large_value(self):
        """log10(1000000000) should be 9."""
        extractor = FeatureExtractor()
        features = extractor.compute_features(
            number_value=Decimal("1000000000"),
            number_unit=None,
            number_raw_text="1,000,000,000",
            keyword_distance=10,
            keyword_position="after",
            context_text="Test",
        )
        assert features.value_magnitude == pytest.approx(9.0)

    def test_magnitude_zero_returns_none(self):
        """Should return None for zero values."""
        extractor = FeatureExtractor()
        features = extractor.compute_features(
            number_value=Decimal("0"),
            number_unit=None,
            number_raw_text="0",
            keyword_distance=10,
            keyword_position="after",
            context_text="Test",
        )
        assert features.value_magnitude is None

    def test_magnitude_none_value(self):
        """Should return None for None values."""
        extractor = FeatureExtractor()
        features = extractor.compute_features(
            number_value=None,
            number_unit=None,
            number_raw_text="unknown",
            keyword_distance=10,
            keyword_position="after",
            context_text="Test",
        )
        assert features.value_magnitude is None


# =============================================================================
# TestDefinitionPatterns - Pattern matching
# =============================================================================


class TestDefinitionPatterns:
    """Tests for DEFINITION_PATTERNS constant."""

    def test_patterns_are_valid_regex(self):
        """All patterns should be compiled regex objects."""
        for pattern in DEFINITION_PATTERNS:
            assert hasattr(pattern, "search")

    def test_we_define_pattern(self):
        """Should match 'we define' variations."""
        text = "We define active customers as..."
        assert any(p.search(text) for p in DEFINITION_PATTERNS)

    def test_defined_as_pattern(self):
        """Should match 'defined as' variations."""
        text = "Customer count is defined as the number of..."
        assert any(p.search(text) for p in DEFINITION_PATTERNS)

    def test_we_calculate_pattern(self):
        """Should match 'we calculate' variations."""
        text = "We calculate retention rate using..."
        assert any(p.search(text) for p in DEFINITION_PATTERNS)

    def test_calculated_as_pattern(self):
        """Should match 'calculated as' variations."""
        text = "Retention rate is calculated as..."
        assert any(p.search(text) for p in DEFINITION_PATTERNS)

    def test_represents_pattern(self):
        """Should match 'represents' pattern."""
        text = "This metric represents the total number..."
        assert any(p.search(text) for p in DEFINITION_PATTERNS)

    def test_case_insensitive(self):
        """All patterns should be case insensitive."""
        text_upper = "WE DEFINE active customers"
        text_lower = "we define active customers"
        text_mixed = "We Define Active Customers"
        assert any(p.search(text_upper) for p in DEFINITION_PATTERNS)
        assert any(p.search(text_lower) for p in DEFINITION_PATTERNS)
        assert any(p.search(text_mixed) for p in DEFINITION_PATTERNS)

    def test_no_false_positive(self):
        """Should not match unrelated text."""
        text = "Our customers love our product."
        assert not any(p.search(text) for p in DEFINITION_PATTERNS)


# =============================================================================
# TestPeriodPatterns - Date/period detection
# =============================================================================


class TestPeriodPatterns:
    """Tests for PERIOD_PATTERNS constant."""

    def test_patterns_are_valid_regex(self):
        """All patterns should be compiled regex objects."""
        for pattern in PERIOD_PATTERNS:
            assert hasattr(pattern, "search")

    def test_quarter_patterns(self):
        """Should match Q1, Q2, Q3, Q4."""
        for q in ["Q1 quarter", "Q2 quarter", "Q3 quarter", "Q4 quarter"]:
            assert any(p.search(q) for p in PERIOD_PATTERNS), f"Failed: {q}"

    def test_first_second_quarter_patterns(self):
        """Should match 'first quarter', 'second quarter', etc."""
        for text in [
            "first quarter",
            "second quarter",
            "third quarter",
            "fourth quarter",
        ]:
            assert any(p.search(text) for p in PERIOD_PATTERNS), f"Failed: {text}"

    def test_fiscal_year_pattern(self):
        """Should match fiscal year mentions."""
        text = "For fiscal year 2023"
        assert any(p.search(text) for p in PERIOD_PATTERNS)

    def test_calendar_year_pattern(self):
        """Should match calendar year mentions."""
        text = "For calendar year 2023"
        assert any(p.search(text) for p in PERIOD_PATTERNS)

    def test_year_ended_pattern(self):
        """Should match 'year ended' variations."""
        text = "Year ended December 31, 2023"
        assert any(p.search(text) for p in PERIOD_PATTERNS)

    def test_years_ended_pattern(self):
        """Should match 'years ended' variations."""
        text = "For the two years ended December 31, 2023"
        assert any(p.search(text) for p in PERIOD_PATTERNS)

    def test_months_pattern(self):
        """Should match 'three months', 'six months', etc."""
        for months in ["three months", "six months", "nine months", "twelve months"]:
            assert any(p.search(months) for p in PERIOD_PATTERNS), f"Failed: {months}"

    def test_year_numbers(self):
        """Should match years 2010-2029."""
        for year in [2010, 2015, 2020, 2023, 2024, 2029]:
            text = f"As of {year}"
            assert any(p.search(text) for p in PERIOD_PATTERNS), f"Failed: {year}"

    def test_monthly_pattern(self):
        """Should match 'monthly' and 'months'."""
        assert any(p.search("monthly active users") for p in PERIOD_PATTERNS)
        assert any(p.search("3 months ago") for p in PERIOD_PATTERNS)

    def test_annual_pattern(self):
        """Should match 'annual' and 'annually'."""
        assert any(p.search("annual revenue") for p in PERIOD_PATTERNS)
        assert any(p.search("billed annually") for p in PERIOD_PATTERNS)


# =============================================================================
# TestRiskFactorsPatterns - Risk section detection
# =============================================================================


class TestRiskFactorsPatterns:
    """Tests for RISK_FACTORS_PATTERNS constant."""

    def test_patterns_are_valid_regex(self):
        """All patterns should be compiled regex objects."""
        for pattern in RISK_FACTORS_PATTERNS:
            assert hasattr(pattern, "search")

    def test_risk_factors_pattern(self):
        """Should match 'risk factors' mentions."""
        text = "See Risk Factors section"
        assert any(p.search(text) for p in RISK_FACTORS_PATTERNS)

    def test_risk_factor_singular(self):
        """Should match singular 'risk factor'."""
        text = "This is a risk factor"
        assert any(p.search(text) for p in RISK_FACTORS_PATTERNS)

    def test_risks_related_pattern(self):
        """Should match 'risks related' mentions."""
        text = "Risks related to our business"
        assert any(p.search(text) for p in RISK_FACTORS_PATTERNS)

    def test_may_not_pattern(self):
        """Should match hedging language 'may not'."""
        text = "We may not achieve our targets"
        assert any(p.search(text) for p in RISK_FACTORS_PATTERNS)

    def test_may_never_pattern(self):
        """Should match hedging language 'may never'."""
        text = "We may never be profitable"
        assert any(p.search(text) for p in RISK_FACTORS_PATTERNS)

    def test_may_fail_pattern(self):
        """Should match hedging language 'may fail'."""
        text = "We may fail to retain customers"
        assert any(p.search(text) for p in RISK_FACTORS_PATTERNS)

    def test_could_adversely_pattern(self):
        """Should match 'could adversely' pattern."""
        text = "This could adversely affect our business"
        assert any(p.search(text) for p in RISK_FACTORS_PATTERNS)

    def test_no_assurance_pattern(self):
        """Should match disclaimer language."""
        text = "There can be no assurance that we will succeed"
        assert any(p.search(text) for p in RISK_FACTORS_PATTERNS)

    def test_cannot_guarantee_pattern(self):
        """Should match 'cannot guarantee' language."""
        text = "We cannot guarantee future performance"
        assert any(p.search(text) for p in RISK_FACTORS_PATTERNS)


# =============================================================================
# TestDefensiveHandling - None/empty inputs
# =============================================================================


class TestDefensiveHandling:
    """Tests for defensive error handling."""

    def test_none_context_text(self):
        """Should handle None context_text gracefully."""
        extractor = FeatureExtractor()
        features = extractor.compute_features(
            number_value=Decimal("100"),
            number_unit=None,
            number_raw_text="100",
            keyword_distance=10,
            keyword_position="after",
            context_text=None,
        )
        assert features.contains_definition_language is False
        assert features.has_period_mention is False
        assert features.is_in_risk_factors is False
        assert features.context_word_count == 0

    def test_empty_context_text(self):
        """Should handle empty context_text."""
        extractor = FeatureExtractor()
        features = extractor.compute_features(
            number_value=Decimal("100"),
            number_unit=None,
            number_raw_text="100",
            keyword_distance=10,
            keyword_position="after",
            context_text="",
        )
        assert features.contains_definition_language is False
        assert features.context_word_count == 0

    def test_none_segment_type(self):
        """Should handle None segment_type."""
        extractor = FeatureExtractor()
        features = extractor.compute_features(
            number_value=Decimal("100"),
            number_unit=None,
            number_raw_text="100",
            keyword_distance=10,
            keyword_position="after",
            context_text="Test",
            segment_type=None,
        )
        assert features.is_in_table is False

    def test_none_section_heading(self):
        """Should handle None section_heading."""
        extractor = FeatureExtractor()
        features = extractor.compute_features(
            number_value=Decimal("100"),
            number_unit=None,
            number_raw_text="100",
            keyword_distance=10,
            keyword_position="after",
            context_text="Test",
            section_heading=None,
        )
        assert features.section_name is None

    def test_all_optional_params_none(self):
        """Should handle all optional params as None."""
        extractor = FeatureExtractor()
        features = extractor.compute_features(
            number_value=None,
            number_unit=None,
            number_raw_text="100",
            keyword_distance=10,
            keyword_position="after",
            context_text="Test",
            segment_type=None,
            section_heading=None,
            section_path=None,
            surrounding_numbers_count=0,
        )
        assert features.value_magnitude is None
        assert features.is_in_table is False
        assert features.section_name is None


# =============================================================================
# TestConvenienceFunctions - Module-level functions
# =============================================================================


class TestConvenienceFunctions:
    """Tests for module-level convenience functions."""

    def test_compute_features_function(self):
        """Module-level compute_features should work identically."""
        features = compute_features(
            number_value=Decimal("1000"),
            number_unit=None,
            number_raw_text="1000",
            keyword_distance=10,
            keyword_position="after",
            context_text="Test context",
        )
        assert isinstance(features, CandidateFeatures)
        assert features.keyword_distance == 10

    def test_compute_features_with_all_params(self):
        """Module-level compute_features should accept all params."""
        features = compute_features(
            number_value=Decimal("1000"),
            number_unit="count",
            number_raw_text="1,000",
            keyword_distance=15,
            keyword_position="before",
            context_text="We define active customers as 1,000 users.",
            segment_type="paragraph",
            section_heading="Business Overview",
            section_path="Part I / Business",
            surrounding_numbers_count=3,
        )
        assert features.keyword_position == "before"
        assert features.contains_definition_language is True
        assert features.section_name == "Business Overview"
        assert features.surrounding_numbers_count == 3

    def test_determine_number_format_function(self):
        """Module-level determine_number_format should work identically."""
        assert determine_number_format("%", "50%") == "percentage"
        assert determine_number_format("usd", "$100") == "currency"
        assert determine_number_format(None, "3.14") == "decimal"
        assert determine_number_format("count", "1000") == "integer"


# =============================================================================
# TestFeaturesSerialization - Backward compatibility
# =============================================================================


class TestFeaturesSerialization:
    """Tests to ensure features serialize identically (backward compat)."""

    def test_features_to_dict_has_all_fields(self):
        """Features should have all expected fields in to_dict output."""
        features = compute_features(
            number_value=Decimal("10000"),
            number_unit=None,
            number_raw_text="10,000",
            keyword_distance=15,
            keyword_position="after",
            context_text="We have 10,000 active customers.",
            segment_type="paragraph",
            section_heading="Business Overview",
        )

        d = features.to_dict()

        # All expected fields present
        expected_fields = [
            "keyword_distance",
            "keyword_position",
            "is_in_table",
            "is_in_risk_factors",
            "contains_definition_language",
            "has_period_mention",
            "number_format",
            "value_magnitude",
            "surrounding_numbers_count",
            "section_name",
            "context_word_count",
            "sentence_position",
        ]
        for field_name in expected_fields:
            assert field_name in d, f"Missing field: {field_name}"

    def test_features_roundtrip(self):
        """Features should survive dict roundtrip."""
        features = compute_features(
            number_value=Decimal("10000"),
            number_unit=None,
            number_raw_text="10,000",
            keyword_distance=15,
            keyword_position="after",
            context_text="We define customers as 10,000 active users in 2023.",
            segment_type="table",
            section_heading="Key Metrics",
            surrounding_numbers_count=2,
        )

        # Convert to dict and back
        d = features.to_dict()
        restored = CandidateFeatures.from_dict(d)

        # All fields should match
        assert restored.keyword_distance == features.keyword_distance
        assert restored.keyword_position == features.keyword_position
        assert restored.is_in_table == features.is_in_table
        assert restored.is_in_risk_factors == features.is_in_risk_factors
        assert restored.contains_definition_language == features.contains_definition_language
        assert restored.has_period_mention == features.has_period_mention
        assert restored.number_format == features.number_format
        assert restored.value_magnitude == features.value_magnitude
        assert restored.surrounding_numbers_count == features.surrounding_numbers_count
        assert restored.section_name == features.section_name
        assert restored.context_word_count == features.context_word_count

    def test_features_values_match_expected(self):
        """Test specific feature values for known input."""
        features = compute_features(
            number_value=Decimal("1000000"),
            number_unit="%",
            number_raw_text="1,000,000%",
            keyword_distance=25,
            keyword_position="before",
            context_text="We define customer retention as calculated annually for fiscal year 2023.",
            segment_type="table",
            section_heading="Risk Factors",
        )

        assert features.keyword_distance == 25
        assert features.keyword_position == "before"
        assert features.number_format == "percentage"
        assert features.value_magnitude == pytest.approx(6.0)
        assert features.is_in_table is True
        assert features.is_in_risk_factors is True
        assert features.contains_definition_language is True
        assert features.has_period_mention is True
        assert features.section_name == "Risk Factors"
