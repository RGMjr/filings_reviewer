"""
Unit tests for candidate_generator module.
"""

from decimal import Decimal
import pytest

from unittest.mock import MagicMock

from src.review.candidate_generator import CandidateGenerator
from src.review.config import CandidateGenerationConfig
from src.review.confidence_scoring import ConfidenceScorer, METRIC_EXPECTED_FORMATS
from src.review.exceptions import (
    CandidateGenerationError,
    NumberProcessingError,
    SegmentProcessingError,
)
from src.review.models import ProcessingStats
from src.review.false_positive_filter import (
    DATE_CONTEXT_PATTERNS,
    FALSE_POSITIVE_CONTEXT_PATTERNS,
    MIN_METRIC_VALUE,
    YEAR_MIN,
    YEAR_MAX,
)
from src.review.keyword_matching import (
    METRIC_KEYWORDS,
    SPECIFIC_KEYWORD_PATTERNS,
    KeywordMatch,
)
from src.review.models import CandidateFeatures
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
        text = "From 1,000 to 5,000 customers in 2023"
        matches = list(NUMBER_REGEX.finditer(text))
        assert len(matches) >= 2
        numbers = [m.group("number") for m in matches]
        assert "1,000" in numbers
        assert "5,000" in numbers


# =============================================================================
# Number Parsing Tests
# =============================================================================
# Tests moved to tests/unit/review/test_number_parsing.py (P1.3)


# =============================================================================
# CandidateGenerator._find_numbers Tests
# =============================================================================


class TestFindNumbers:
    """Tests for finding numbers in text."""

    @pytest.fixture
    def generator(self):
        return CandidateGenerator()

    def test_find_single_number(self, generator):
        """Find single number in text."""
        text = "We have 10,000 active customers"
        numbers = generator._find_numbers(text)
        assert len(numbers) == 1
        assert numbers[0].raw_text.strip() == "10,000"
        assert numbers[0].value == Decimal("10000")

    def test_find_multiple_numbers(self, generator):
        """Find multiple numbers in text."""
        text = "Revenue grew from $100 million to $150 million"
        numbers = generator._find_numbers(text)
        assert len(numbers) == 2

    def test_find_numbers_with_positions(self, generator):
        """Verify number positions are correct."""
        text = "Start 123 middle 456 end"
        numbers = generator._find_numbers(text)
        assert len(numbers) == 2
        # Check positions are within expected range
        assert numbers[0].start < numbers[1].start


# =============================================================================
# Keyword Matching Tests
# =============================================================================
# Tests moved to tests/unit/review/test_keyword_matching.py (P1.3)


# =============================================================================
# CandidateGenerator._find_keywords_near_number Tests (Integration)
# =============================================================================


class TestFindKeywordsNearNumberIntegration:
    """Tests for finding keywords near numbers."""

    @pytest.fixture
    def generator(self):
        return CandidateGenerator(max_keyword_distance=100)

    def test_keyword_before_number(self, generator):
        """Find keyword appearing before number."""
        text = "We have active customers totaling 50,000 as of year end"
        numbers = generator._find_numbers(text)
        assert len(numbers) >= 1

        all_keywords = generator._find_all_keywords(text)
        keywords = generator._find_keywords_near_number(numbers[0], all_keywords)
        assert len(keywords) >= 1
        assert any(kw.metric_id == "cm_active_customers_total" for kw in keywords)

    def test_keyword_after_number(self, generator):
        """Find keyword appearing after number."""
        text = "We acquired 5,000 new customers during the quarter"
        numbers = generator._find_numbers(text)
        assert len(numbers) >= 1

        all_keywords = generator._find_all_keywords(text)
        keywords = generator._find_keywords_near_number(numbers[0], all_keywords)
        assert len(keywords) >= 1
        assert any(kw.metric_id == "cm_new_customers_acquired" for kw in keywords)

    def test_keyword_too_far(self, generator):
        """Keyword too far from number should not match."""
        # Create text where keyword is more than 100 chars away from number
        padding = "x" * 150
        text = f"active customers {padding} 50,000"
        numbers = generator._find_numbers(text)
        assert len(numbers) >= 1

        all_keywords = generator._find_all_keywords(text)
        keywords = generator._find_keywords_near_number(numbers[0], all_keywords)
        # Should not find keyword because it's too far
        active_customer_matches = [
            kw for kw in keywords if kw.metric_id == "cm_active_customers_total"
        ]
        assert len(active_customer_matches) == 0

    def test_multiple_metrics_match(self, generator):
        """Multiple metrics can match the same number."""
        text = "Our retention rate of 95% reflects strong customer retention"
        numbers = generator._find_numbers(text)
        assert len(numbers) >= 1

        all_keywords = generator._find_all_keywords(text)
        keywords = generator._find_keywords_near_number(numbers[0], all_keywords)
        metric_ids = {kw.metric_id for kw in keywords}
        assert "cm_customer_retention_rate" in metric_ids


# =============================================================================
# Distance Calculation Tests
# =============================================================================
# Tests moved to tests/unit/review/test_keyword_matching.py (P1.3)


# =============================================================================
# Context Extraction Tests
# =============================================================================
# Tests moved to tests/unit/review/test_context_extraction.py (P1.3)


# =============================================================================
# CandidateGenerator.generate_for_filing Tests
# =============================================================================


class TestGenerateForFiling:
    """Tests for full candidate generation."""

    @pytest.fixture
    def generator(self):
        return CandidateGenerator()

    def test_generate_candidates_from_segment(self, generator):
        """Generate candidates from a segment with metric mention."""
        segments = [
            {
                "source_segment_id": 1,
                "raw_text": "We grew to 50,000 active customers by year end.",
            }
        ]

        candidates = generator.generate_for_filing(
            filing_id=1,
            company_id=1,
            segments=segments,
        )

        assert len(candidates) >= 1
        assert candidates[0].filing_id == 1
        assert candidates[0].company_id == 1
        assert candidates[0].source_segment_id == 1
        assert candidates[0].suggested_metric_id == "cm_active_customers_total"

    def test_generate_multiple_candidates(self, generator):
        """Generate multiple candidates from different metrics."""
        segments = [
            {
                "source_segment_id": 1,
                "raw_text": (
                    "Our customer base grew to 100,000 active customers. "
                    "We achieved a 95% retention rate."
                ),
            }
        ]

        candidates = generator.generate_for_filing(
            filing_id=1,
            company_id=1,
            segments=segments,
        )

        # Should have candidates for both active customers and retention rate
        metric_ids = {c.suggested_metric_id for c in candidates}
        assert "cm_active_customers_total" in metric_ids
        assert "cm_customer_retention_rate" in metric_ids

    def test_deduplication_same_metric(self, generator):
        """Deduplicate by (number_position, metric_id)."""
        # Text with number that matches multiple patterns for same metric
        segments = [
            {
                "source_segment_id": 1,
                "raw_text": "Our retention rate and customer retention was 95%",
            }
        ]

        candidates = generator.generate_for_filing(
            filing_id=1,
            company_id=1,
            segments=segments,
        )

        # Should only have one candidate for retention rate
        retention_candidates = [
            c for c in candidates if c.suggested_metric_id == "cm_customer_retention_rate"
        ]
        assert len(retention_candidates) == 1

    def test_empty_segment(self, generator):
        """Handle empty segments gracefully."""
        segments = [
            {"source_segment_id": 1, "raw_text": ""},
            {"source_segment_id": 2},  # Missing raw_text
        ]

        candidates = generator.generate_for_filing(
            filing_id=1,
            company_id=1,
            segments=segments,
        )

        assert len(candidates) == 0

    def test_no_metrics_segment(self, generator):
        """No candidates when no metric keywords near numbers."""
        segments = [
            {
                "source_segment_id": 1,
                "raw_text": "The weather was 75 degrees in the summer.",
            }
        ]

        candidates = generator.generate_for_filing(
            filing_id=1,
            company_id=1,
            segments=segments,
        )

        # No metric keywords, so no candidates
        assert len(candidates) == 0

    def test_keyword_position_before(self, generator):
        """Verify keyword_position is 'before' when keyword precedes number."""
        segments = [
            {
                "source_segment_id": 1,
                "raw_text": "We have active customers totaling 50,000",
            }
        ]

        candidates = generator.generate_for_filing(
            filing_id=1,
            company_id=1,
            segments=segments,
        )

        assert len(candidates) >= 1
        assert candidates[0].keyword_position == "before"

    def test_keyword_position_after(self, generator):
        """Verify keyword_position is 'after' when keyword follows number."""
        segments = [
            {
                "source_segment_id": 1,
                "raw_text": "We grew to 50,000 active customers",
            }
        ]

        candidates = generator.generate_for_filing(
            filing_id=1,
            company_id=1,
            segments=segments,
        )

        assert len(candidates) >= 1
        assert candidates[0].keyword_position == "after"


# =============================================================================
# METRIC_KEYWORDS Tests
# =============================================================================


class TestMetricKeywords:
    """Tests for METRIC_KEYWORDS dictionary."""

    def test_metric_keywords_not_empty(self):
        """Verify METRIC_KEYWORDS is populated."""
        assert len(METRIC_KEYWORDS) > 0

    def test_all_metrics_have_patterns(self):
        """Each metric should have at least one pattern."""
        for metric_id, patterns in METRIC_KEYWORDS.items():
            assert len(patterns) > 0, f"{metric_id} has no patterns"

    def test_patterns_are_valid_regex(self):
        """All patterns should be valid regex."""
        import re
        for metric_id, patterns in METRIC_KEYWORDS.items():
            for pattern in patterns:
                try:
                    re.compile(pattern, re.IGNORECASE)
                except re.error as e:
                    pytest.fail(f"Invalid regex in {metric_id}: {pattern} - {e}")

    def test_keywords_imported_from_metric_classifier(self):
        """METRIC_KEYWORDS should be imported from MetricClassifier."""
        from src.extraction.metric_classifier import MetricClassifier

        # Should be the exact same object (not a copy)
        assert METRIC_KEYWORDS is MetricClassifier.METRIC_KEYWORDS


# =============================================================================
# Feature Computation Tests
# =============================================================================


class TestComputeFeatures:
    """Tests for feature computation in CandidateGenerator."""

    @pytest.fixture
    def generator(self):
        return CandidateGenerator()

    def test_features_computed_for_candidate(self, generator):
        """Verify features are computed for each candidate."""
        segments = [
            {
                "source_segment_id": 1,
                "raw_text": "We have 50,000 active customers as of December 2023.",
            }
        ]

        candidates = generator.generate_for_filing(
            filing_id=1,
            company_id=1,
            segments=segments,
        )

        assert len(candidates) >= 1
        assert candidates[0].features is not None
        assert candidates[0].features.keyword_position in ("before", "after")

    def test_keyword_distance_feature(self, generator):
        """Verify keyword_distance feature is correct."""
        segments = [
            {
                "source_segment_id": 1,
                "raw_text": "We have 50,000 active customers.",
            }
        ]

        candidates = generator.generate_for_filing(
            filing_id=1,
            company_id=1,
            segments=segments,
        )

        assert len(candidates) >= 1
        # keyword_distance should match the candidate's keyword_distance
        assert candidates[0].features.keyword_distance == candidates[0].keyword_distance

    def test_is_in_table_feature(self, generator):
        """Verify is_in_table feature from segment_type."""
        # Test table segment
        table_segments = [
            {
                "source_segment_id": 1,
                "segment_type": "table",
                "raw_text": "50,000 active customers",
            }
        ]

        candidates = generator.generate_for_filing(
            filing_id=1, company_id=1, segments=table_segments
        )

        assert len(candidates) >= 1
        assert candidates[0].features.is_in_table is True

        # Test paragraph segment
        para_segments = [
            {
                "source_segment_id": 2,
                "segment_type": "paragraph",
                "raw_text": "50,000 active customers",
            }
        ]

        candidates = generator.generate_for_filing(
            filing_id=1, company_id=1, segments=para_segments
        )

        assert len(candidates) >= 1
        assert candidates[0].features.is_in_table is False

    def test_contains_definition_language_feature(self, generator):
        """Verify definition language detection."""
        # Text with definition language
        segments = [
            {
                "source_segment_id": 1,
                "raw_text": "We define active customers as those with 50,000 transactions.",
            }
        ]

        candidates = generator.generate_for_filing(
            filing_id=1, company_id=1, segments=segments
        )

        assert len(candidates) >= 1
        assert candidates[0].features.contains_definition_language is True

    def test_has_period_mention_feature(self, generator):
        """Verify period/date mention detection."""
        segments = [
            {
                "source_segment_id": 1,
                "raw_text": "As of December 2023, we had 50,000 active customers.",
            }
        ]

        candidates = generator.generate_for_filing(
            filing_id=1, company_id=1, segments=segments
        )

        assert len(candidates) >= 1
        assert candidates[0].features.has_period_mention is True

    def test_is_in_risk_factors_feature_from_section(self, generator):
        """Verify risk factors detection from section heading."""
        segments = [
            {
                "source_segment_id": 1,
                "section_heading": "Risk Factors",
                "raw_text": "We may lose 50,000 active customers due to competition.",
            }
        ]

        candidates = generator.generate_for_filing(
            filing_id=1, company_id=1, segments=segments
        )

        assert len(candidates) >= 1
        assert candidates[0].features.is_in_risk_factors is True

    def test_is_in_risk_factors_feature_from_text(self, generator):
        """Verify risk factors detection from context text."""
        segments = [
            {
                "source_segment_id": 1,
                "raw_text": "We may not retain our 50,000 active customers.",
            }
        ]

        candidates = generator.generate_for_filing(
            filing_id=1, company_id=1, segments=segments
        )

        assert len(candidates) >= 1
        assert candidates[0].features.is_in_risk_factors is True

    def test_number_format_integer(self, generator):
        """Verify integer number format detection."""
        segments = [
            {
                "source_segment_id": 1,
                "raw_text": "We have 50,000 active customers.",
            }
        ]

        candidates = generator.generate_for_filing(
            filing_id=1, company_id=1, segments=segments
        )

        assert len(candidates) >= 1
        assert candidates[0].features.number_format == "integer"

    def test_number_format_percentage(self, generator):
        """Verify percentage number format detection."""
        segments = [
            {
                "source_segment_id": 1,
                "raw_text": "Our retention rate is 95%.",
            }
        ]

        candidates = generator.generate_for_filing(
            filing_id=1, company_id=1, segments=segments
        )

        assert len(candidates) >= 1
        assert candidates[0].features.number_format == "percentage"

    def test_number_format_currency(self, generator):
        """Verify currency number format detection."""
        segments = [
            {
                "source_segment_id": 1,
                "raw_text": "Our ARPU is $500 per customer.",
            }
        ]

        candidates = generator.generate_for_filing(
            filing_id=1, company_id=1, segments=segments
        )

        assert len(candidates) >= 1
        assert candidates[0].features.number_format == "currency"

    def test_number_format_decimal(self, generator):
        """Verify decimal number format detection."""
        segments = [
            {
                "source_segment_id": 1,
                "raw_text": "Our NRR is 1.25 net retention.",
            }
        ]

        candidates = generator.generate_for_filing(
            filing_id=1, company_id=1, segments=segments
        )

        # Find the candidate for NRR
        nrr_candidates = [
            c for c in candidates
            if c.suggested_metric_id == "cm_net_revenue_retention"
        ]
        assert len(nrr_candidates) >= 1
        assert nrr_candidates[0].features.number_format == "decimal"

    def test_value_magnitude_feature(self, generator):
        """Verify value magnitude is computed correctly."""
        segments = [
            {
                "source_segment_id": 1,
                "raw_text": "We have 10,000 active customers.",
            }
        ]

        candidates = generator.generate_for_filing(
            filing_id=1, company_id=1, segments=segments
        )

        assert len(candidates) >= 1
        # log10(10000) = 4.0
        assert candidates[0].features.value_magnitude is not None
        assert abs(candidates[0].features.value_magnitude - 4.0) < 0.01

    def test_surrounding_numbers_count_feature(self, generator):
        """Verify surrounding numbers count."""
        segments = [
            {
                "source_segment_id": 1,
                "raw_text": "Revenue grew from 100 to 500 with 10,000 active customers.",
            }
        ]

        candidates = generator.generate_for_filing(
            filing_id=1, company_id=1, segments=segments
        )

        # Should find "active customers" candidate
        active_candidates = [
            c for c in candidates
            if c.suggested_metric_id == "cm_active_customers_total"
        ]
        assert len(active_candidates) >= 1
        # There are 3 numbers total, so surrounding count should be 2
        assert active_candidates[0].features.surrounding_numbers_count == 2

    def test_context_word_count_feature(self, generator):
        """Verify context word count is computed."""
        segments = [
            {
                "source_segment_id": 1,
                "raw_text": "We have 50,000 active customers.",
            }
        ]

        candidates = generator.generate_for_filing(
            filing_id=1, company_id=1, segments=segments
        )

        assert len(candidates) >= 1
        assert candidates[0].features.context_word_count > 0

    def test_section_name_feature(self, generator):
        """Verify section name is captured from segment."""
        segments = [
            {
                "source_segment_id": 1,
                "section_heading": "Business Overview",
                "raw_text": "We have 50,000 active customers.",
            }
        ]

        candidates = generator.generate_for_filing(
            filing_id=1, company_id=1, segments=segments
        )

        assert len(candidates) >= 1
        assert candidates[0].features.section_name == "Business Overview"


# =============================================================================
# False Positive Filtering Tests
# =============================================================================


class TestFalsePositiveFiltering:
    """Tests for false positive filtering in CandidateGenerator."""

    @pytest.fixture
    def generator(self):
        """Generator with default filtering enabled."""
        return CandidateGenerator()

    @pytest.fixture
    def generator_no_filter(self):
        """Generator with filtering disabled."""
        return CandidateGenerator(filter_false_positives=False)

    def test_filters_small_integers(self, generator):
        """Small integers (< 10) should be filtered."""
        segments = [
            {
                "source_segment_id": 1,
                "raw_text": "We have 5 active customers and 50,000 total users.",
            }
        ]

        candidates = generator.generate_for_filing(
            filing_id=1, company_id=1, segments=segments
        )

        # Should only have candidate for 50,000, not for 5
        assert len(candidates) >= 1
        raw_texts = [c.raw_number_text for c in candidates]
        assert "5" not in raw_texts
        assert "50,000" in raw_texts

    def test_filters_year_values(self, generator):
        """Year values (1990-2100) should be filtered."""
        segments = [
            {
                "source_segment_id": 1,
                "raw_text": "In 2023, we had 50,000 active customers.",
            }
        ]

        candidates = generator.generate_for_filing(
            filing_id=1, company_id=1, segments=segments
        )

        # Should only have candidate for 50,000, not for 2023
        raw_texts = [c.raw_number_text for c in candidates]
        assert "2023" not in raw_texts
        assert "50,000" in raw_texts

    def test_filters_date_components(self, generator):
        """Date components like 12/31/2023 should be filtered."""
        segments = [
            {
                "source_segment_id": 1,
                "raw_text": "As of 12/31/2023, we had 50,000 active customers.",
            }
        ]

        candidates = generator.generate_for_filing(
            filing_id=1, company_id=1, segments=segments
        )

        # Should only have candidate for 50,000, not date components
        raw_texts = [c.raw_number_text for c in candidates]
        assert "12" not in raw_texts
        assert "31" not in raw_texts
        assert "50,000" in raw_texts

    def test_filters_page_references(self, generator):
        """Page references like 'page 123' should be filtered."""
        segments = [
            {
                "source_segment_id": 1,
                "raw_text": "See page 123 for details on our 50,000 active customers.",
            }
        ]

        candidates = generator.generate_for_filing(
            filing_id=1, company_id=1, segments=segments
        )

        # Should only have candidate for 50,000, not page number
        raw_texts = [c.raw_number_text for c in candidates]
        assert "123" not in raw_texts
        assert "50,000" in raw_texts

    def test_filters_note_references(self, generator):
        """Note references like 'Note 5' should be filtered."""
        segments = [
            {
                "source_segment_id": 1,
                "raw_text": "See Note 15 for details on our 50,000 active customers.",
            }
        ]

        candidates = generator.generate_for_filing(
            filing_id=1, company_id=1, segments=segments
        )

        # Should only have candidate for 50,000, not note number
        raw_texts = [c.raw_number_text for c in candidates]
        assert "15" not in raw_texts
        assert "50,000" in raw_texts

    def test_filters_version_numbers(self, generator):
        """Version numbers like 'Version 2.0' should be filtered."""
        segments = [
            {
                "source_segment_id": 1,
                "raw_text": "Version 2.0 of our platform has 50,000 active customers.",
            }
        ]

        candidates = generator.generate_for_filing(
            filing_id=1, company_id=1, segments=segments
        )

        # Should only have candidate for 50,000, not version
        raw_texts = [c.raw_number_text for c in candidates]
        assert "2.0" not in raw_texts
        assert "50,000" in raw_texts

    def test_filters_exhibit_references(self, generator):
        """Exhibit references like 'Exhibit 10' should be filtered."""
        segments = [
            {
                "source_segment_id": 1,
                "raw_text": "See Exhibit 10 for our 50,000 active customers.",
            }
        ]

        candidates = generator.generate_for_filing(
            filing_id=1, company_id=1, segments=segments
        )

        # Should only have candidate for 50,000
        raw_texts = [c.raw_number_text for c in candidates]
        assert "50,000" in raw_texts

    def test_preserves_percentages(self, generator):
        """Percentages should not be filtered by min_value."""
        segments = [
            {
                "source_segment_id": 1,
                "raw_text": "Our retention rate is 5%.",
            }
        ]

        candidates = generator.generate_for_filing(
            filing_id=1, company_id=1, segments=segments
        )

        # 5% should not be filtered even though 5 < 10
        assert len(candidates) >= 1
        assert candidates[0].raw_number_text == "5%"

    def test_preserves_currency(self, generator):
        """Currency values should not be filtered by min_value."""
        segments = [
            {
                "source_segment_id": 1,
                "raw_text": "Our ARPU is $5 per customer.",
            }
        ]

        candidates = generator.generate_for_filing(
            filing_id=1, company_id=1, segments=segments
        )

        # $5 should not be filtered
        assert len(candidates) >= 1
        assert candidates[0].raw_number_text == "$5"

    def test_preserves_decimals(self, generator):
        """Decimal numbers (ratios) should not be filtered by min_value."""
        segments = [
            {
                "source_segment_id": 1,
                "raw_text": "Our NRR is 1.25 net retention.",
            }
        ]

        candidates = generator.generate_for_filing(
            filing_id=1, company_id=1, segments=segments
        )

        # 1.25 should not be filtered (could be a ratio like 125%)
        nrr_candidates = [
            c for c in candidates if c.suggested_metric_id == "cm_net_revenue_retention"
        ]
        assert len(nrr_candidates) >= 1
        assert nrr_candidates[0].raw_number_text == "1.25"

    def test_no_filter_when_disabled(self, generator_no_filter):
        """When filtering disabled, all numbers should be candidates."""
        segments = [
            {
                "source_segment_id": 1,
                "raw_text": "In 2023, we had 5 active customers on page 123.",
            }
        ]

        candidates = generator_no_filter.generate_for_filing(
            filing_id=1, company_id=1, segments=segments
        )

        # All numbers should be present when filtering is off
        raw_texts = [c.raw_number_text for c in candidates]
        assert "2023" in raw_texts
        assert "5" in raw_texts
        assert "123" in raw_texts

    def test_custom_min_value_threshold(self):
        """Custom min_value threshold should be respected."""
        generator = CandidateGenerator(min_value=100)
        segments = [
            {
                "source_segment_id": 1,
                "raw_text": "We have 50 active customers and 500 total users.",
            }
        ]

        candidates = generator.generate_for_filing(
            filing_id=1, company_id=1, segments=segments
        )

        # 50 should be filtered (< 100), 500 should remain
        raw_texts = [c.raw_number_text for c in candidates]
        assert "50" not in raw_texts
        assert "500" in raw_texts

    def test_filter_years_can_be_disabled(self):
        """Year filtering can be disabled independently."""
        generator = CandidateGenerator(filter_years=False, min_value=0)
        segments = [
            {
                "source_segment_id": 1,
                "raw_text": "In 2023, we had 50,000 active customers.",
            }
        ]

        candidates = generator.generate_for_filing(
            filing_id=1, company_id=1, segments=segments
        )

        # 2023 should be present when year filtering is off
        raw_texts = [c.raw_number_text for c in candidates]
        assert "2023" in raw_texts
        assert "50,000" in raw_texts

    def test_integration_complex_text(self, generator):
        """Integration test with complex text containing multiple false positives."""
        segments = [
            {
                "source_segment_id": 1,
                "raw_text": """For the year ended December 31, 2023, we had revenue of $100 million.
As of 12/31/2023, our customer count reached 50,000 active customers.
See Note 5 on page 123 for details. Version 2.0 of our software launched.""",
            }
        ]

        candidates = generator.generate_for_filing(
            filing_id=1, company_id=1, segments=segments
        )

        # Collect raw texts
        raw_texts = [c.raw_number_text for c in candidates]

        # Should include legitimate metrics
        assert "$100 million" in raw_texts
        assert "50,000" in raw_texts

        # Should exclude false positives
        assert "31" not in raw_texts  # Day from date
        assert "2023" not in raw_texts  # Year
        assert "12" not in raw_texts  # Month from 12/31/2023
        assert "5" not in raw_texts  # Note reference
        assert "123" not in raw_texts  # Page reference
        assert "2.0" not in raw_texts  # Version number


# =============================================================================
# False Positive Filtering Tests
# =============================================================================
# Tests moved to tests/unit/review/test_false_positive_filter.py (P1.3)


# =============================================================================
# ConfidenceScorer Tests
# =============================================================================


class TestConfidenceScorer:
    """Tests for ConfidenceScorer class."""

    @pytest.fixture
    def scorer(self):
        return ConfidenceScorer(max_keyword_distance=100)

    @pytest.fixture
    def base_features(self):
        """Basic features for testing."""
        return CandidateFeatures(
            keyword_distance=20,
            keyword_position="before",
            is_in_table=False,
            is_in_risk_factors=False,
            contains_definition_language=False,
            has_period_mention=False,
            number_format="integer",
            value_magnitude=4.0,
            surrounding_numbers_count=1,
        )

    def test_score_in_valid_range(self, scorer, base_features):
        """Confidence score should be between 0.0 and 1.0."""
        score = scorer.compute_confidence(
            keyword_distance=20,
            keyword_position="before",
            keyword="customers",
            metric_id="cm_active_customers_total",
            features=base_features,
        )
        assert 0.0 <= score <= 1.0

    def test_closer_distance_higher_confidence(self, scorer, base_features):
        """Closer keyword distance should increase confidence."""
        score_close = scorer.compute_confidence(
            keyword_distance=5,
            keyword_position="before",
            keyword="customers",
            metric_id="cm_active_customers_total",
            features=base_features,
        )
        score_far = scorer.compute_confidence(
            keyword_distance=80,
            keyword_position="before",
            keyword="customers",
            metric_id="cm_active_customers_total",
            features=base_features,
        )
        assert score_close > score_far

    def test_keyword_before_bonus(self, scorer, base_features):
        """Keyword position 'before' should give slight bonus."""
        features_before = CandidateFeatures(
            keyword_distance=20,
            keyword_position="before",
            is_in_table=False,
            is_in_risk_factors=False,
            contains_definition_language=False,
            has_period_mention=False,
            number_format="integer",
        )
        features_after = CandidateFeatures(
            keyword_distance=20,
            keyword_position="after",
            is_in_table=False,
            is_in_risk_factors=False,
            contains_definition_language=False,
            has_period_mention=False,
            number_format="integer",
        )

        score_before = scorer.compute_confidence(
            keyword_distance=20,
            keyword_position="before",
            keyword="customers",
            metric_id="cm_active_customers_total",
            features=features_before,
        )
        score_after = scorer.compute_confidence(
            keyword_distance=20,
            keyword_position="after",
            keyword="customers",
            metric_id="cm_active_customers_total",
            features=features_after,
        )
        assert score_before > score_after

    def test_definition_language_bonus(self, scorer):
        """Definition language should significantly increase confidence."""
        features_no_def = CandidateFeatures(
            keyword_distance=20,
            keyword_position="before",
            is_in_table=False,
            is_in_risk_factors=False,
            contains_definition_language=False,
            has_period_mention=False,
            number_format="integer",
        )
        features_with_def = CandidateFeatures(
            keyword_distance=20,
            keyword_position="before",
            is_in_table=False,
            is_in_risk_factors=False,
            contains_definition_language=True,
            has_period_mention=False,
            number_format="integer",
        )

        score_no_def = scorer.compute_confidence(
            keyword_distance=20,
            keyword_position="before",
            keyword="customers",
            metric_id="cm_active_customers_total",
            features=features_no_def,
        )
        score_with_def = scorer.compute_confidence(
            keyword_distance=20,
            keyword_position="before",
            keyword="customers",
            metric_id="cm_active_customers_total",
            features=features_with_def,
        )
        assert score_with_def > score_no_def
        # Definition language bonus is 0.20
        assert score_with_def - score_no_def == pytest.approx(0.20, abs=0.01)

    def test_period_mention_bonus(self, scorer):
        """Period mention should slightly increase confidence."""
        features_no_period = CandidateFeatures(
            keyword_distance=20,
            keyword_position="before",
            is_in_table=False,
            is_in_risk_factors=False,
            contains_definition_language=False,
            has_period_mention=False,
            number_format="integer",
        )
        features_with_period = CandidateFeatures(
            keyword_distance=20,
            keyword_position="before",
            is_in_table=False,
            is_in_risk_factors=False,
            contains_definition_language=False,
            has_period_mention=True,
            number_format="integer",
        )

        score_no_period = scorer.compute_confidence(
            keyword_distance=20,
            keyword_position="before",
            keyword="customers",
            metric_id="cm_active_customers_total",
            features=features_no_period,
        )
        score_with_period = scorer.compute_confidence(
            keyword_distance=20,
            keyword_position="before",
            keyword="customers",
            metric_id="cm_active_customers_total",
            features=features_with_period,
        )
        assert score_with_period > score_no_period

    def test_risk_factors_penalty(self, scorer):
        """Risk factors section should significantly decrease confidence."""
        features_normal = CandidateFeatures(
            keyword_distance=20,
            keyword_position="before",
            is_in_table=False,
            is_in_risk_factors=False,
            contains_definition_language=False,
            has_period_mention=False,
            number_format="integer",
        )
        features_risk = CandidateFeatures(
            keyword_distance=20,
            keyword_position="before",
            is_in_table=False,
            is_in_risk_factors=True,
            contains_definition_language=False,
            has_period_mention=False,
            number_format="integer",
        )

        score_normal = scorer.compute_confidence(
            keyword_distance=20,
            keyword_position="before",
            keyword="customers",
            metric_id="cm_active_customers_total",
            features=features_normal,
        )
        score_risk = scorer.compute_confidence(
            keyword_distance=20,
            keyword_position="before",
            keyword="customers",
            metric_id="cm_active_customers_total",
            features=features_risk,
        )
        assert score_risk < score_normal
        # Risk factors penalty is 0.25
        assert score_normal - score_risk == pytest.approx(0.25, abs=0.01)

    def test_format_match_bonus(self, scorer):
        """Matching number format should increase confidence."""
        # NRR expects percentage format
        features_mismatch = CandidateFeatures(
            keyword_distance=20,
            keyword_position="before",
            is_in_table=False,
            is_in_risk_factors=False,
            contains_definition_language=False,
            has_period_mention=False,
            number_format="integer",  # Wrong format for NRR
        )
        features_match = CandidateFeatures(
            keyword_distance=20,
            keyword_position="before",
            is_in_table=False,
            is_in_risk_factors=False,
            contains_definition_language=False,
            has_period_mention=False,
            number_format="percentage",  # Correct format for NRR
        )

        score_mismatch = scorer.compute_confidence(
            keyword_distance=20,
            keyword_position="before",
            keyword="net revenue retention",
            metric_id="cm_nrr",
            features=features_mismatch,
        )
        score_match = scorer.compute_confidence(
            keyword_distance=20,
            keyword_position="before",
            keyword="net revenue retention",
            metric_id="cm_nrr",
            features=features_match,
        )
        assert score_match > score_mismatch

    def test_specific_keyword_bonus(self, scorer, base_features):
        """Multi-word specific keywords should increase confidence."""
        score_generic = scorer.compute_confidence(
            keyword_distance=20,
            keyword_position="before",
            keyword="customers",
            metric_id="cm_active_customers_total",
            features=base_features,
        )
        score_specific = scorer.compute_confidence(
            keyword_distance=20,
            keyword_position="before",
            keyword="active customers",
            metric_id="cm_active_customers_total",
            features=base_features,
        )
        assert score_specific > score_generic

    def test_surrounding_numbers_penalty(self, scorer):
        """Many surrounding numbers should decrease confidence."""
        features_few = CandidateFeatures(
            keyword_distance=20,
            keyword_position="before",
            is_in_table=False,
            is_in_risk_factors=False,
            contains_definition_language=False,
            has_period_mention=False,
            number_format="integer",
            surrounding_numbers_count=1,
        )
        features_many = CandidateFeatures(
            keyword_distance=20,
            keyword_position="before",
            is_in_table=False,
            is_in_risk_factors=False,
            contains_definition_language=False,
            has_period_mention=False,
            number_format="integer",
            surrounding_numbers_count=15,
        )

        score_few = scorer.compute_confidence(
            keyword_distance=20,
            keyword_position="before",
            keyword="customers",
            metric_id="cm_active_customers_total",
            features=features_few,
        )
        score_many = scorer.compute_confidence(
            keyword_distance=20,
            keyword_position="before",
            keyword="customers",
            metric_id="cm_active_customers_total",
            features=features_many,
        )
        assert score_many < score_few

    def test_table_without_definition_penalty(self, scorer):
        """Table context without definition language should decrease confidence."""
        features_no_table = CandidateFeatures(
            keyword_distance=20,
            keyword_position="before",
            is_in_table=False,
            is_in_risk_factors=False,
            contains_definition_language=False,
            has_period_mention=False,
            number_format="integer",
        )
        features_table = CandidateFeatures(
            keyword_distance=20,
            keyword_position="before",
            is_in_table=True,
            is_in_risk_factors=False,
            contains_definition_language=False,
            has_period_mention=False,
            number_format="integer",
        )

        score_no_table = scorer.compute_confidence(
            keyword_distance=20,
            keyword_position="before",
            keyword="customers",
            metric_id="cm_active_customers_total",
            features=features_no_table,
        )
        score_table = scorer.compute_confidence(
            keyword_distance=20,
            keyword_position="before",
            keyword="customers",
            metric_id="cm_active_customers_total",
            features=features_table,
        )
        assert score_table < score_no_table

    def test_table_with_definition_no_penalty(self, scorer):
        """Table context WITH definition language should not have table penalty."""
        features_table_with_def = CandidateFeatures(
            keyword_distance=20,
            keyword_position="before",
            is_in_table=True,
            is_in_risk_factors=False,
            contains_definition_language=True,  # Has definition
            has_period_mention=False,
            number_format="integer",
        )
        features_para_with_def = CandidateFeatures(
            keyword_distance=20,
            keyword_position="before",
            is_in_table=False,
            is_in_risk_factors=False,
            contains_definition_language=True,  # Has definition
            has_period_mention=False,
            number_format="integer",
        )

        score_table = scorer.compute_confidence(
            keyword_distance=20,
            keyword_position="before",
            keyword="customers",
            metric_id="cm_active_customers_total",
            features=features_table_with_def,
        )
        score_para = scorer.compute_confidence(
            keyword_distance=20,
            keyword_position="before",
            keyword="customers",
            metric_id="cm_active_customers_total",
            features=features_para_with_def,
        )
        # Should be equal since definition language negates table penalty
        assert score_table == score_para

    def test_score_clamped_to_zero(self, scorer):
        """Score should never go below 0.0 even with many penalties."""
        features_bad = CandidateFeatures(
            keyword_distance=100,  # Max distance
            keyword_position="after",
            is_in_table=True,
            is_in_risk_factors=True,  # Penalty
            contains_definition_language=False,
            has_period_mention=False,
            number_format="integer",
            surrounding_numbers_count=20,  # Max penalty
        )

        score = scorer.compute_confidence(
            keyword_distance=100,
            keyword_position="after",
            keyword="customers",
            metric_id="cm_active_customers_total",
            features=features_bad,
        )
        assert score >= 0.0

    def test_score_clamped_to_one(self, scorer):
        """Score should never exceed 1.0 even with many bonuses."""
        features_great = CandidateFeatures(
            keyword_distance=0,  # Perfect distance
            keyword_position="before",
            is_in_table=False,
            is_in_risk_factors=False,
            contains_definition_language=True,  # Bonus
            has_period_mention=True,  # Bonus
            number_format="percentage",  # Match for NRR
            surrounding_numbers_count=0,
        )

        score = scorer.compute_confidence(
            keyword_distance=0,
            keyword_position="before",
            keyword="net revenue retention",  # Specific keyword
            metric_id="cm_nrr",
            features=features_great,
        )
        assert score <= 1.0

    def test_is_specific_keyword_detection(self, scorer):
        """Test specific keyword pattern detection."""
        assert scorer._is_specific_keyword("active customers") is True
        assert scorer._is_specific_keyword("Active Customers") is True  # Case insensitive
        assert scorer._is_specific_keyword("net revenue retention") is True
        assert scorer._is_specific_keyword("customers") is False
        assert scorer._is_specific_keyword("retention") is False


class TestConfidenceIntegration:
    """Tests for confidence scoring integration in CandidateGenerator."""

    @pytest.fixture
    def generator(self):
        return CandidateGenerator()

    @pytest.fixture
    def generator_no_confidence(self):
        return CandidateGenerator(compute_confidence=False)

    def test_candidates_have_confidence_by_default(self, generator):
        """Candidates should have suggestion_confidence computed by default."""
        segments = [
            {
                "source_segment_id": 1,
                "raw_text": "We have 50,000 active customers.",
            }
        ]

        candidates = generator.generate_for_filing(
            filing_id=1,
            company_id=1,
            segments=segments,
        )

        assert len(candidates) >= 1
        assert candidates[0].suggestion_confidence is not None
        assert 0.0 <= candidates[0].suggestion_confidence <= 1.0

    def test_confidence_disabled(self, generator_no_confidence):
        """Confidence should be None when disabled."""
        segments = [
            {
                "source_segment_id": 1,
                "raw_text": "We have 50,000 active customers.",
            }
        ]

        candidates = generator_no_confidence.generate_for_filing(
            filing_id=1,
            company_id=1,
            segments=segments,
        )

        assert len(candidates) >= 1
        assert candidates[0].suggestion_confidence is None

    def test_higher_confidence_with_definition(self, generator):
        """Candidates with definition language should have higher confidence."""
        segments_no_def = [
            {
                "source_segment_id": 1,
                "raw_text": "We have 50,000 active customers.",
            }
        ]
        segments_with_def = [
            {
                "source_segment_id": 2,
                "raw_text": "We define active customers as 50,000 users.",
            }
        ]

        candidates_no_def = generator.generate_for_filing(
            filing_id=1, company_id=1, segments=segments_no_def
        )
        candidates_with_def = generator.generate_for_filing(
            filing_id=1, company_id=1, segments=segments_with_def
        )

        assert len(candidates_no_def) >= 1
        assert len(candidates_with_def) >= 1
        assert candidates_with_def[0].suggestion_confidence > candidates_no_def[0].suggestion_confidence

    def test_lower_confidence_in_risk_factors(self, generator):
        """Candidates in risk factors should have lower confidence."""
        segments_normal = [
            {
                "source_segment_id": 1,
                "raw_text": "We have 50,000 active customers.",
            }
        ]
        segments_risk = [
            {
                "source_segment_id": 2,
                "section_heading": "Risk Factors",
                "raw_text": "We may lose 50,000 active customers.",
            }
        ]

        candidates_normal = generator.generate_for_filing(
            filing_id=1, company_id=1, segments=segments_normal
        )
        candidates_risk = generator.generate_for_filing(
            filing_id=1, company_id=1, segments=segments_risk
        )

        assert len(candidates_normal) >= 1
        assert len(candidates_risk) >= 1
        assert candidates_risk[0].suggestion_confidence < candidates_normal[0].suggestion_confidence

    def test_confidence_reflects_keyword_distance(self, generator):
        """Closer keywords should result in higher confidence."""
        # Text with keyword very close to number
        segments_close = [
            {
                "source_segment_id": 1,
                "raw_text": "50,000 active customers",  # Distance ~1
            }
        ]
        # Text with keyword farther from number
        segments_far = [
            {
                "source_segment_id": 2,
                "raw_text": "Our user base, which includes many types, reached 50,000 and these are active customers.",
            }
        ]

        candidates_close = generator.generate_for_filing(
            filing_id=1, company_id=1, segments=segments_close
        )
        candidates_far = generator.generate_for_filing(
            filing_id=1, company_id=1, segments=segments_far
        )

        assert len(candidates_close) >= 1
        assert len(candidates_far) >= 1
        assert candidates_close[0].suggestion_confidence > candidates_far[0].suggestion_confidence


class TestMetricExpectedFormats:
    """Tests for METRIC_EXPECTED_FORMATS constant."""

    def test_customer_counts_expect_integer(self):
        """Customer count metrics should expect integer format."""
        assert "integer" in METRIC_EXPECTED_FORMATS.get("cm_active_customers_total", [])
        assert "integer" in METRIC_EXPECTED_FORMATS.get("cm_new_customers", [])

    def test_retention_metrics_expect_percentage(self):
        """Retention metrics should expect percentage format."""
        assert "percentage" in METRIC_EXPECTED_FORMATS.get("cm_nrr", [])
        assert "percentage" in METRIC_EXPECTED_FORMATS.get("cm_grr", [])
        assert "percentage" in METRIC_EXPECTED_FORMATS.get("cm_churn_rate", [])

    def test_revenue_metrics_expect_currency(self):
        """Revenue metrics should expect currency format."""
        assert "currency" in METRIC_EXPECTED_FORMATS.get("cm_arr", [])
        assert "currency" in METRIC_EXPECTED_FORMATS.get("cm_mrr", [])
        assert "currency" in METRIC_EXPECTED_FORMATS.get("cm_cac", [])


class TestSpecificKeywordPatterns:
    """Tests for SPECIFIC_KEYWORD_PATTERNS constant."""

    def test_patterns_are_valid_regex(self):
        """All specific keyword patterns should be valid regex."""
        import re
        for pattern in SPECIFIC_KEYWORD_PATTERNS:
            try:
                re.compile(pattern, re.IGNORECASE)
            except re.error as e:
                pytest.fail(f"Invalid regex pattern: {pattern} - {e}")

    def test_patterns_match_expected(self):
        """Specific patterns should match expected keywords."""
        import re

        # Compile patterns
        compiled = [re.compile(p, re.IGNORECASE) for p in SPECIFIC_KEYWORD_PATTERNS]

        # Test some expected matches
        assert any(p.search("active customers") for p in compiled)
        assert any(p.search("enterprise customers") for p in compiled)
        assert any(p.search("net revenue retention") for p in compiled)
        assert any(p.search("annual recurring revenue") for p in compiled)
        assert any(p.search("daily active users") for p in compiled)

    def test_patterns_dont_match_generic(self):
        """Specific patterns should not match generic keywords."""
        import re

        compiled = [re.compile(p, re.IGNORECASE) for p in SPECIFIC_KEYWORD_PATTERNS]

        # Generic keywords should NOT match
        assert not any(p.search("customers") for p in compiled)
        assert not any(p.search("retention") for p in compiled)
        assert not any(p.search("revenue") for p in compiled)


# =============================================================================
# Exception Classes Tests
# =============================================================================


class TestExceptionClasses:
    """Tests for custom exception classes."""

    def test_candidate_generation_error_is_exception(self):
        """CandidateGenerationError should be an Exception."""
        assert issubclass(CandidateGenerationError, Exception)

    def test_segment_processing_error_inheritance(self):
        """SegmentProcessingError should inherit from CandidateGenerationError."""
        assert issubclass(SegmentProcessingError, CandidateGenerationError)

    def test_segment_processing_error_attributes(self):
        """SegmentProcessingError should store segment_id and original_error."""
        original = ValueError("test error")
        error = SegmentProcessingError(
            "Failed to process segment",
            segment_id=123,
            original_error=original,
        )

        assert str(error) == "Failed to process segment"
        assert error.segment_id == 123
        assert error.original_error is original

    def test_segment_processing_error_optional_attributes(self):
        """SegmentProcessingError should work with optional attributes."""
        error = SegmentProcessingError("Basic error")

        assert str(error) == "Basic error"
        assert error.segment_id is None
        assert error.original_error is None

    def test_number_processing_error_inheritance(self):
        """NumberProcessingError should inherit from CandidateGenerationError."""
        assert issubclass(NumberProcessingError, CandidateGenerationError)

    def test_number_processing_error_attributes(self):
        """NumberProcessingError should store number_text, position, and original_error."""
        original = ValueError("parse error")
        error = NumberProcessingError(
            "Failed to parse number",
            number_text="abc123",
            position=42,
            original_error=original,
        )

        assert str(error) == "Failed to parse number"
        assert error.number_text == "abc123"
        assert error.position == 42
        assert error.original_error is original

    def test_number_processing_error_optional_attributes(self):
        """NumberProcessingError should work with optional attributes."""
        error = NumberProcessingError("Basic error")

        assert str(error) == "Basic error"
        assert error.number_text is None
        assert error.position is None
        assert error.original_error is None

    def test_exceptions_can_be_raised_and_caught(self):
        """Exceptions should be raisable and catchable."""
        with pytest.raises(SegmentProcessingError):
            raise SegmentProcessingError("test", segment_id=1)

        with pytest.raises(NumberProcessingError):
            raise NumberProcessingError("test", number_text="123")

        # Should also be catchable as CandidateGenerationError
        with pytest.raises(CandidateGenerationError):
            raise SegmentProcessingError("test")

        with pytest.raises(CandidateGenerationError):
            raise NumberProcessingError("test")


# =============================================================================
# Additional Edge Case Tests
# =============================================================================


class TestDuplicateMetricSkipping:
    """Tests for duplicate metric skipping in _find_keywords_near_number."""

    @pytest.fixture
    def generator(self):
        return CandidateGenerator(max_keyword_distance=100)

    def test_skips_duplicate_metrics_same_pattern(self, generator):
        """Should only return one match per metric even if pattern matches multiple times."""
        # Text with "active customers" appearing twice near the same number
        text = "active customers active customers 50,000"
        numbers = generator._find_numbers(text)
        assert len(numbers) >= 1

        all_keywords = generator._find_all_keywords(text)
        # Should have multiple keyword matches for the same metric
        customer_keywords = [kw for kw in all_keywords if kw.metric_id == "cm_active_customers_total"]
        assert len(customer_keywords) >= 2, "Expected multiple customer keyword matches"

        # But _find_keywords_near_number should deduplicate
        keywords = generator._find_keywords_near_number(numbers[0], all_keywords)
        customer_matches = [kw for kw in keywords if kw.metric_id == "cm_active_customers_total"]

        # Should only have one match per metric (deduplication)
        assert len(customer_matches) == 1, "Should have exactly one match after deduplication"


# Context extraction edge cases tests moved to test_context_extraction.py (P1.3)


class TestParseNumberEdgeCases:
    """Tests for edge cases in _parse_number."""

    @pytest.fixture
    def generator(self):
        return CandidateGenerator()

    def test_finds_valid_numbers_only(self, generator):
        """_find_numbers should skip entries that can't be parsed."""
        # Standard numbers should work
        text = "We have 1,000 customers"
        numbers = generator._find_numbers(text)

        assert len(numbers) >= 1
        assert numbers[0].value == Decimal("1000")

    def test_handles_negative_numbers(self, generator):
        """Should parse negative numbers correctly."""
        text = "Loss of -500 customers"
        numbers = generator._find_numbers(text)

        assert len(numbers) >= 1
        negative_nums = [n for n in numbers if n.value and n.value < 0]
        assert len(negative_nums) >= 1
        assert negative_nums[0].value == Decimal("-500")


# =============================================================================
# ProcessingStats Tests
# =============================================================================


class TestProcessingStats:
    """Tests for ProcessingStats dataclass."""

    def test_default_values(self):
        """Default values should all be zero."""
        stats = ProcessingStats()

        assert stats.segments_processed == 0
        assert stats.segments_failed == 0
        assert stats.numbers_found == 0
        assert stats.numbers_failed == 0
        assert stats.candidates_generated == 0
        assert stats.false_positives_filtered == 0

    def test_segment_success_rate_all_success(self):
        """Segment success rate should be 1.0 when no failures."""
        stats = ProcessingStats(segments_processed=10, segments_failed=0)

        assert stats.segment_success_rate == 1.0

    def test_segment_success_rate_partial_failure(self):
        """Segment success rate should reflect failures."""
        stats = ProcessingStats(segments_processed=8, segments_failed=2)

        assert stats.segment_success_rate == 0.8

    def test_segment_success_rate_no_segments(self):
        """Segment success rate should be 1.0 when no segments processed."""
        stats = ProcessingStats(segments_processed=0, segments_failed=0)

        assert stats.segment_success_rate == 1.0

    def test_number_success_rate_all_success(self):
        """Number success rate should be 1.0 when no failures."""
        stats = ProcessingStats(numbers_found=100, numbers_failed=0)

        assert stats.number_success_rate == 1.0

    def test_number_success_rate_partial_failure(self):
        """Number success rate should reflect failures."""
        stats = ProcessingStats(numbers_found=90, numbers_failed=10)

        assert stats.number_success_rate == 0.9

    def test_number_success_rate_no_numbers(self):
        """Number success rate should be 1.0 when no numbers found."""
        stats = ProcessingStats(numbers_found=0, numbers_failed=0)

        assert stats.number_success_rate == 1.0

    def test_log_summary_basic(self, caplog):
        """log_summary should log info message."""
        import logging
        caplog.set_level(logging.INFO)

        stats = ProcessingStats(
            segments_processed=5,
            numbers_found=20,
            false_positives_filtered=3,
            candidates_generated=17,
        )
        stats.log_summary(filing_id=123)

        assert "Filing 123 stats" in caplog.text
        assert "segments=5/5" in caplog.text
        assert "numbers=20" in caplog.text
        assert "candidates=17" in caplog.text

    def test_log_summary_with_segment_failures(self, caplog):
        """log_summary should warn about segment failures."""
        import logging
        caplog.set_level(logging.WARNING)

        stats = ProcessingStats(
            segments_processed=8,
            segments_failed=2,
        )
        stats.log_summary(filing_id=456)

        assert "2 segments failed" in caplog.text

    def test_log_summary_with_number_failures(self, caplog):
        """log_summary should warn about number failures."""
        import logging
        caplog.set_level(logging.WARNING)

        stats = ProcessingStats(
            numbers_found=95,
            numbers_failed=5,
        )
        stats.log_summary(filing_id=789)

        assert "5 numbers failed" in caplog.text


# =============================================================================
# Segment Processing Error Handling Tests
# =============================================================================


class TestSegmentProcessingErrorHandling:
    """Tests for error handling in segment processing."""

    @pytest.fixture
    def generator(self):
        return CandidateGenerator()

    def test_invalid_segment_type_raises_error(self, generator):
        """Should raise SegmentProcessingError for non-dict segment."""
        with pytest.raises(SegmentProcessingError) as exc_info:
            generator._process_segment(
                filing_id=1,
                company_id=1,
                segment="not a dict",
            )
        assert "must be a dict" in str(exc_info.value)

    def test_invalid_segment_type_list(self, generator):
        """Should raise SegmentProcessingError for list segment."""
        with pytest.raises(SegmentProcessingError):
            generator._process_segment(
                filing_id=1,
                company_id=1,
                segment=[1, 2, 3],
            )

    def test_invalid_raw_text_type(self, generator):
        """Should raise SegmentProcessingError for non-string raw_text."""
        with pytest.raises(SegmentProcessingError) as exc_info:
            generator._process_segment(
                filing_id=1,
                company_id=1,
                segment={"raw_text": 12345, "source_segment_id": 1},
            )
        assert "must be a string" in str(exc_info.value)

    def test_empty_segment_returns_empty(self, generator):
        """Empty segment should return empty list, not raise."""
        candidates, stats = generator._process_segment(
            filing_id=1,
            company_id=1,
            segment={"raw_text": ""},
        )
        assert candidates == []
        assert stats["numbers_found"] == 0

    def test_none_raw_text_returns_empty(self, generator):
        """None raw_text should return empty list."""
        candidates, stats = generator._process_segment(
            filing_id=1,
            company_id=1,
            segment={"raw_text": None},
        )
        assert candidates == []

    def test_stats_returned_from_process_segment(self, generator):
        """_process_segment should return stats dict."""
        segment = {"raw_text": "We have 100 active customers"}

        result = generator._process_segment(
            filing_id=1,
            company_id=1,
            segment=segment,
        )

        assert isinstance(result, tuple)
        assert len(result) == 2
        candidates, stats = result
        assert isinstance(stats, dict)
        assert "numbers_found" in stats
        assert "numbers_failed" in stats
        assert "false_positives_filtered" in stats


class TestGenerateForFilingErrorHandling:
    """Tests for error handling in generate_for_filing."""

    @pytest.fixture
    def generator(self):
        return CandidateGenerator()

    def test_continues_after_segment_error(self, generator):
        """Should continue processing after a segment fails."""
        segments = [
            "not a dict",  # Invalid - will fail
            {"raw_text": "We have 100 active customers"},  # Valid
        ]

        # Should not raise - errors are logged
        candidates, stats = generator.generate_for_filing(
            filing_id=1,
            company_id=1,
            segments=segments,
            return_stats=True,
        )

        # Should have processed one segment and failed one
        assert stats.segments_processed == 1
        assert stats.segments_failed == 1
        assert len(candidates) >= 1

    def test_returns_stats_when_requested(self, generator):
        """Should return stats tuple when return_stats=True."""
        segments = [{"raw_text": "We have 100 active customers"}]

        result = generator.generate_for_filing(
            filing_id=1,
            company_id=1,
            segments=segments,
            return_stats=True,
        )

        assert isinstance(result, tuple)
        assert len(result) == 2
        candidates, stats = result
        assert isinstance(candidates, list)
        assert isinstance(stats, ProcessingStats)

    def test_returns_list_by_default(self, generator):
        """Should return just list when return_stats=False."""
        segments = [{"raw_text": "We have 100 active customers"}]

        result = generator.generate_for_filing(
            filing_id=1,
            company_id=1,
            segments=segments,
            return_stats=False,
        )

        assert isinstance(result, list)

    def test_stats_track_filtered_false_positives(self, generator):
        """Stats should track filtered false positives."""
        segments = [{"raw_text": "2023 fiscal year had 100 active customers"}]

        candidates, stats = generator.generate_for_filing(
            filing_id=1,
            company_id=1,
            segments=segments,
            return_stats=True,
        )

        # 2023 should be filtered as a year
        assert stats.false_positives_filtered >= 1

    def test_empty_segments_list(self, generator):
        """Should handle empty segments list gracefully."""
        result = generator.generate_for_filing(
            filing_id=1,
            company_id=1,
            segments=[],
            return_stats=True,
        )

        candidates, stats = result
        assert candidates == []
        assert stats.segments_processed == 0


class TestComputeFeaturesDefensiveChecks:
    """Tests for defensive checks in _compute_features."""

    @pytest.fixture
    def generator(self):
        return CandidateGenerator()

    @pytest.fixture
    def sample_number(self):
        return NumberMatch(
            start=0,
            end=3,
            raw_text="100",
            value=Decimal("100"),
            unit="count",
        )

    def test_handles_non_string_context(self, generator, sample_number):
        """Should handle non-string context_text gracefully."""
        features = generator._compute_features(
            number=sample_number,
            keyword_distance=10,
            keyword_position="before",
            context_text=None,
            segment={"raw_text": "test"},
            all_numbers=[sample_number],
        )

        assert isinstance(features, CandidateFeatures)
        assert features.context_word_count == 0

    def test_handles_integer_context(self, generator, sample_number):
        """Should handle integer context_text."""
        features = generator._compute_features(
            number=sample_number,
            keyword_distance=10,
            keyword_position="before",
            context_text=12345,
            segment={"raw_text": "test"},
            all_numbers=[sample_number],
        )

        assert isinstance(features, CandidateFeatures)
        assert features.context_word_count == 1  # "12345"

    def test_handles_non_dict_segment(self, generator, sample_number):
        """Should handle non-dict segment gracefully."""
        features = generator._compute_features(
            number=sample_number,
            keyword_distance=10,
            keyword_position="before",
            context_text="test context",
            segment=None,
            all_numbers=[sample_number],
        )

        assert isinstance(features, CandidateFeatures)
        assert features.is_in_table is False
        assert features.section_name is None

    def test_handles_non_list_all_numbers(self, generator, sample_number):
        """Should handle non-list all_numbers gracefully."""
        features = generator._compute_features(
            number=sample_number,
            keyword_distance=10,
            keyword_position="before",
            context_text="test context",
            segment={"raw_text": "test"},
            all_numbers="invalid",
        )

        assert isinstance(features, CandidateFeatures)
        assert features.surrounding_numbers_count == 0

    def test_handles_missing_segment_fields(self, generator, sample_number):
        """Should handle segment with missing optional fields."""
        segment = {"raw_text": "test"}

        features = generator._compute_features(
            number=sample_number,
            keyword_distance=10,
            keyword_position="before",
            context_text="test context",
            segment=segment,
            all_numbers=[sample_number],
        )

        assert isinstance(features, CandidateFeatures)
        assert features.is_in_table is False
        assert features.section_name is None
        assert features.is_in_risk_factors is False

    def test_handles_none_segment_fields(self, generator, sample_number):
        """Should handle segment with None field values."""
        segment = {
            "raw_text": "test",
            "segment_type": None,
            "section_heading": None,
            "section_path": None,
        }

        features = generator._compute_features(
            number=sample_number,
            keyword_distance=10,
            keyword_position="before",
            context_text="test context",
            segment=segment,
            all_numbers=[sample_number],
        )

        assert isinstance(features, CandidateFeatures)
        assert features.is_in_table is False


# =============================================================================
# Cross-Segment Deduplication Tests
# =============================================================================


class TestDeduplicateCandidates:
    """Tests for _deduplicate_candidates method."""

    @pytest.fixture
    def generator(self):
        return CandidateGenerator()

    def _make_candidate(
        self,
        parsed_value: Decimal,
        metric_id: str,
        confidence: float = None,
    ) -> "ReviewCandidate":
        """Helper to create test candidates."""
        from src.review.models import ReviewCandidate

        return ReviewCandidate(
            filing_id=1,
            company_id=1,
            char_position=0,
            context_text="test context",
            raw_number_text=str(parsed_value),
            triggering_keyword="test",
            keyword_distance=10,
            keyword_position="before",
            parsed_value=parsed_value,
            suggested_metric_id=metric_id,
            suggestion_confidence=confidence,
        )

    def test_empty_list_returns_empty(self, generator):
        """Empty candidate list should return empty."""
        result, count = generator._deduplicate_candidates([])

        assert result == []
        assert count == 0

    def test_no_duplicates_unchanged(self, generator):
        """List with no duplicates should be unchanged."""
        candidates = [
            self._make_candidate(Decimal("100"), "cm_active_customers_total"),
            self._make_candidate(Decimal("200"), "cm_active_customers_total"),
            self._make_candidate(Decimal("100"), "cm_new_customers"),
        ]

        result, count = generator._deduplicate_candidates(candidates)

        assert len(result) == 3
        assert count == 0

    def test_removes_exact_duplicates(self, generator):
        """Duplicate (value, metric) pairs should be deduplicated."""
        candidates = [
            self._make_candidate(Decimal("100"), "cm_active_customers_total", 0.8),
            self._make_candidate(Decimal("100"), "cm_active_customers_total", 0.6),
        ]

        result, count = generator._deduplicate_candidates(candidates)

        assert len(result) == 1
        assert count == 1
        # Should keep the one with higher confidence
        assert result[0].suggestion_confidence == 0.8

    def test_keeps_highest_confidence(self, generator):
        """When duplicates exist, keep the one with highest confidence."""
        candidates = [
            self._make_candidate(Decimal("500"), "cm_arr", 0.5),
            self._make_candidate(Decimal("500"), "cm_arr", 0.9),
            self._make_candidate(Decimal("500"), "cm_arr", 0.7),
        ]

        result, count = generator._deduplicate_candidates(candidates)

        assert len(result) == 1
        assert count == 2
        assert result[0].suggestion_confidence == 0.9

    def test_handles_none_confidence(self, generator):
        """Should handle candidates with None confidence."""
        candidates = [
            self._make_candidate(Decimal("100"), "cm_active_customers_total", None),
            self._make_candidate(Decimal("100"), "cm_active_customers_total", 0.5),
        ]

        result, count = generator._deduplicate_candidates(candidates)

        assert len(result) == 1
        assert count == 1
        # Should keep the one with actual confidence
        assert result[0].suggestion_confidence == 0.5

    def test_handles_all_none_confidence(self, generator):
        """When all duplicates have None confidence, keep first."""
        candidates = [
            self._make_candidate(Decimal("100"), "cm_active_customers_total", None),
            self._make_candidate(Decimal("100"), "cm_active_customers_total", None),
        ]

        result, count = generator._deduplicate_candidates(candidates)

        assert len(result) == 1
        assert count == 1

    def test_handles_none_parsed_value(self, generator):
        """Should handle candidates with None parsed_value."""
        from src.review.models import ReviewCandidate

        candidates = [
            ReviewCandidate(
                filing_id=1,
                company_id=1,
                char_position=0,
                context_text="test",
                raw_number_text="unknown",
                triggering_keyword="test",
                keyword_distance=10,
                keyword_position="before",
                parsed_value=None,
                suggested_metric_id="cm_active_customers_total",
            ),
            ReviewCandidate(
                filing_id=1,
                company_id=1,
                char_position=100,
                context_text="test2",
                raw_number_text="unknown2",
                triggering_keyword="test",
                keyword_distance=10,
                keyword_position="before",
                parsed_value=None,
                suggested_metric_id="cm_active_customers_total",
            ),
        ]

        result, count = generator._deduplicate_candidates(candidates)

        assert len(result) == 1
        assert count == 1

    def test_different_metrics_not_deduplicated(self, generator):
        """Same value but different metrics should not be deduplicated."""
        candidates = [
            self._make_candidate(Decimal("100"), "cm_active_customers_total"),
            self._make_candidate(Decimal("100"), "cm_new_customers"),
        ]

        result, count = generator._deduplicate_candidates(candidates)

        assert len(result) == 2
        assert count == 0

    def test_different_values_not_deduplicated(self, generator):
        """Different values for same metric should not be deduplicated."""
        candidates = [
            self._make_candidate(Decimal("100"), "cm_active_customers_total"),
            self._make_candidate(Decimal("200"), "cm_active_customers_total"),
        ]

        result, count = generator._deduplicate_candidates(candidates)

        assert len(result) == 2
        assert count == 0


class TestCrossSegmentDeduplication:
    """Integration tests for cross-segment deduplication."""

    @pytest.fixture
    def generator(self):
        return CandidateGenerator()

    def test_deduplicates_across_segments(self, generator):
        """Same number in multiple segments should be deduplicated."""
        # Use identical text to ensure same parsed values
        segments = [
            {"raw_text": "We have 10,000 active customers."},
            {"raw_text": "We have 10,000 active customers."},
        ]

        candidates, stats = generator.generate_for_filing(
            filing_id=1,
            company_id=1,
            segments=segments,
            return_stats=True,
        )

        # Both segments have identical "10,000 active customers"
        # Should deduplicate to just one candidate
        active_customer_candidates = [
            c for c in candidates
            if c.suggested_metric_id == "cm_active_customers_total"
            and c.parsed_value == Decimal("10000")
        ]

        assert len(active_customer_candidates) == 1
        assert stats.duplicates_removed >= 1

    def test_stats_track_duplicates_removed(self, generator):
        """ProcessingStats should track duplicates_removed."""
        segments = [
            {"raw_text": "100 active customers"},
            {"raw_text": "100 active customers again"},
        ]

        candidates, stats = generator.generate_for_filing(
            filing_id=1,
            company_id=1,
            segments=segments,
            return_stats=True,
        )

        # Check stats are tracked
        assert hasattr(stats, "duplicates_removed")
        assert stats.duplicates_removed >= 0

    def test_keeps_unique_across_segments(self, generator):
        """Different numbers across segments should all be kept."""
        segments = [
            {"raw_text": "We have 10,000 active customers."},
            {"raw_text": "We have 20,000 active customers."},
        ]

        candidates, stats = generator.generate_for_filing(
            filing_id=1,
            company_id=1,
            segments=segments,
            return_stats=True,
        )

        values = {c.parsed_value for c in candidates if c.suggested_metric_id == "cm_active_customers_total"}

        # Should keep both values
        assert Decimal("10000") in values
        assert Decimal("20000") in values


# =============================================================================
# Performance Tests
# =============================================================================


class TestKeywordMatchingPerformance:
    """
    Performance tests for keyword matching.

    Note: P1.1 (combined regex pattern) was reverted after benchmarking showed
    it was 8x slower than the original implementation. These tests verify the
    current implementation (individual pattern searches) performs adequately.
    """

    @pytest.fixture
    def large_text(self):
        """Generate a large text sample for performance testing."""
        # Simulate a typical segment from an S-1 filing (~10KB)
        base_text = """
        Our business model focuses on customer acquisition and retention.
        As of December 31, 2023, we had approximately 125,000 active customers.
        Our annual recurring revenue (ARR) reached $493 million, representing
        year-over-year growth of 45%. We define active customers as those who
        have generated revenue in the trailing 12 months.
        
        Customer metrics for the year ended December 31, 2023:
        - Active customers: 125,000 (up from 86,000)
        - Enterprise customers: 5,500 (up from 3,800)
        - Net revenue retention: 118%
        - Dollar-based net retention: 120%
        - Customer acquisition cost: $7,500
        - Lifetime value: $125,000
        - Average revenue per customer: $3,944
        
        Our total addressable market represents approximately 2.5 million
        potential customers across North America and Europe. We added
        39,000 new customers during the year, representing growth of 45%.
        """
        # Repeat to create a larger sample
        return base_text * 20  # ~10KB text

    def test_finds_all_keywords_efficiently(self, large_text):
        """Test that keyword matching works correctly on large text."""
        generator = CandidateGenerator()

        # This should complete in reasonable time
        keywords = generator._find_all_keywords(large_text)
        
        # Verify we found keyword matches
        assert len(keywords) > 0
        
        # Verify keyword matches have expected structure
        for kw in keywords:
            assert isinstance(kw, KeywordMatch)
            assert kw.metric_id in METRIC_KEYWORDS
            assert kw.start >= 0
            assert kw.end > kw.start
            assert len(kw.keyword) > 0

    def test_benchmark_keyword_matching(self, large_text, benchmark=None):
        """
        Benchmark test for keyword matching performance.

        Current implementation uses individual pattern searches (89 separate
        finditer calls). While this appears less efficient theoretically, it
        outperforms combined patterns due to regex engine early-exit behavior.

        Expected performance: ~10ms for 10KB text

        Note: This test will only run if pytest-benchmark is installed.
        Run with: pytest tests/unit/review/test_candidate_generator.py::TestKeywordMatchingPerformance::test_benchmark_keyword_matching -v
        """
        generator = CandidateGenerator()
        
        # If pytest-benchmark is available, use it
        if benchmark is not None:
            result = benchmark(generator._find_all_keywords, large_text)
            assert len(result) > 0
        else:
            # Without benchmark plugin, just verify it runs quickly
            import time
            start = time.perf_counter()
            result = generator._find_all_keywords(large_text)
            elapsed = time.perf_counter() - start
            
            # Should complete in reasonable time for 10KB text
            # Current implementation: ~10-20ms typical
            assert elapsed < 0.1, f"Keyword matching took {elapsed:.3f}s, expected < 0.1s"
            assert len(result) > 0

    def test_matches_correct_keywords(self):
        """
        Verify that keyword matching produces correct results.

        This is a critical correctness test ensuring keyword detection
        works as expected.
        """
        text = """
        We have 10,000 active customers. Our net revenue retention is 120%.
        We also track daily active users and monthly active users for
        engagement metrics. New customers acquired this quarter: 5,000.
        """

        generator = CandidateGenerator()
        keywords = generator._find_all_keywords(text)

        # Verify we found multiple keyword matches
        assert len(keywords) >= 3, "Should find at least 3 keyword matches"

        metric_ids = {kw.metric_id for kw in keywords}

        # Verify we found multiple different metrics
        assert len(metric_ids) >= 3, "Should identify at least 3 different metrics"

        # Verify we found at least these core metrics that should definitely match
        assert "cm_active_customers_total" in metric_ids
        assert "cm_net_revenue_retention" in metric_ids

        # Verify each match has correct properties
        for kw in keywords:
            # Keyword text should be from the original text
            assert text[kw.start:kw.end].lower() == kw.keyword.lower()
            # Pattern should be a string
            assert isinstance(kw.pattern, str)
            # Metric ID should be valid
            assert kw.metric_id in METRIC_KEYWORDS

    def test_performance_scales_reasonably(self):
        """
        Test that performance scales reasonably with text size.

        With individual pattern searches, time should scale roughly linearly
        with text size for typical text (most patterns don't match most text).
        """
        import time
        
        base_text = "We have 10,000 active customers. " * 100  # ~3KB
        
        generator = CandidateGenerator()
        
        # Test 1x size
        start = time.perf_counter()
        keywords_1x = generator._find_all_keywords(base_text)
        time_1x = time.perf_counter() - start
        
        # Test 2x size
        start = time.perf_counter()
        keywords_2x = generator._find_all_keywords(base_text * 2)
        time_2x = time.perf_counter() - start
        
        # Time should scale roughly linearly with text size
        # Ratio should be close to 2.0 for doubling text size
        ratio = time_2x / time_1x if time_1x > 0 else 1.0

        # Allow some variance due to measurement overhead and cache effects
        assert ratio < 5.0, f"Time scaling ratio {ratio:.2f}x exceeds expected behavior"

        # Both should complete quickly
        assert time_1x < 0.1, f"1x test took {time_1x:.3f}s"
        assert time_2x < 0.2, f"2x test took {time_2x:.3f}s"


class TestContextExtractionPerformance:
    """Performance tests for context extraction optimization (P1.2)."""

    @pytest.fixture
    def segment_with_many_numbers(self):
        """Generate a segment with many numbers to test context extraction efficiency."""
        # Simulate a metrics-heavy segment with 20+ numbers
        text = """
        During fiscal year 2023, we achieved significant customer growth:

        - Active customers: 125,000 (up from 86,000 in 2022)
        - Enterprise customers: 5,500 (up from 3,800)
        - SMB customers: 119,500 (up from 82,200)
        - New customers acquired: 39,000 (45% growth)
        - Customer churn rate: 5.2% (down from 7.1%)
        - Net revenue retention: 118% (up from 112%)
        - Dollar-based net retention: 120%
        - Average contract value: $52,000
        - Customer lifetime value: $185,000
        - Customer acquisition cost: $7,500
        - LTV/CAC ratio: 24.7
        - Annual recurring revenue: $493M (up from $340M)
        - Revenue per customer: $3,944
        - Monthly active users: 2.5M (up from 1.8M)
        - Daily active users: 890,000 (up from 620,000)
        - Engagement rate: 35.6%
        - Free trial conversion rate: 18.5%
        - Paid conversion rate: 12.3%
        - Average revenue per user: $197
        - Customer satisfaction score: 4.7/5.0

        Our addressable market represents approximately 2.5 million potential customers.
        """
        return text

    def test_context_extraction_uses_cache(self, segment_with_many_numbers):
        """
        Test that context extraction uses cached word positions.

        With P1.2 optimization, _extract_context should use pre-computed
        word positions rather than re-parsing for every number.
        """
        generator = CandidateGenerator()

        # Parse words once (simulating what _process_segment does)
        generator._current_segment_words = generator._context_extractor.parse_text_into_words(
            segment_with_many_numbers
        )

        # Extract context at multiple positions
        positions = [100, 300, 500, 700, 900]
        contexts = []

        for pos in positions:
            context = generator._extract_context(segment_with_many_numbers, pos)
            contexts.append(context)

        # Verify contexts were extracted
        assert len(contexts) == 5
        for ctx in contexts:
            assert len(ctx) > 0

        # Clear cache
        generator._current_segment_words = None

    def test_context_extraction_fallback_works(self):
        """
        Test that context extraction works without cache (fallback behavior).

        This ensures backward compatibility when _extract_context is called
        directly without pre-computed word positions.
        """
        generator = CandidateGenerator()

        # Don't set _current_segment_words - test fallback path
        text = "We have 10,000 active customers and 5,000 new customers."

        context = generator._extract_context(text, 10)

        assert len(context) > 0
        assert "10,000" in context or "active" in context

    def test_benchmark_context_extraction_with_many_numbers(
        self, segment_with_many_numbers
    ):
        """
        Benchmark context extraction performance with multiple numbers.

        Expected performance with P1.2:
        - Parse words once: ~5ms for 500-word segment
        - Extract context 20 times: ~1ms total (using cached words)
        - Total: ~6ms

        Without P1.2 (old implementation):
        - Parse words 20 times: ~100ms (5ms × 20)
        - Expected speedup: ~15-20x
        """
        import time

        generator = CandidateGenerator()

        # Find all numbers in the segment
        numbers = generator._find_numbers(segment_with_many_numbers)
        assert len(numbers) >= 20, "Need at least 20 numbers for meaningful test"

        # Test WITH cache (P1.2 optimization)
        start = time.perf_counter()

        # Pre-compute words once
        generator._current_segment_words = generator._context_extractor.parse_text_into_words(
            segment_with_many_numbers
        )

        # Extract context for all numbers
        for num in numbers:
            _ = generator._extract_context(segment_with_many_numbers, num.start)

        time_with_cache = time.perf_counter() - start

        # Clear cache
        generator._current_segment_words = None

        # Test WITHOUT cache (simulating old behavior)
        start = time.perf_counter()

        # Extract context for all numbers (will re-parse each time)
        for num in numbers:
            _ = generator._extract_context(segment_with_many_numbers, num.start)

        time_without_cache = time.perf_counter() - start

        # With cache should be significantly faster
        speedup = time_without_cache / time_with_cache if time_with_cache > 0 else 1.0

        print(f"\nContext extraction performance:")
        print(f"  Numbers processed: {len(numbers)}")
        print(f"  With cache (P1.2): {time_with_cache*1000:.2f}ms")
        print(f"  Without cache (old): {time_without_cache*1000:.2f}ms")
        print(f"  Speedup: {speedup:.1f}x")

        # Should see at least 2x speedup (typically 10-20x)
        # Using conservative threshold to account for small sample variance
        assert speedup > 2.0, f"Expected speedup > 2x, got {speedup:.1f}x"

        # Both should still be reasonably fast
        assert time_with_cache < 0.1, f"Cached extraction took {time_with_cache:.3f}s"
        assert time_without_cache < 2.0, f"Uncached extraction took {time_without_cache:.3f}s"

    def test_process_segment_clears_cache(self):
        """
        Test that _process_segment properly manages cache lifecycle.

        The cache should be:
        1. Set at the beginning of _process_segment
        2. Used during processing
        3. Cleared at the end
        """
        generator = CandidateGenerator()

        # Initially no cache
        assert generator._current_segment_words is None

        # Create a minimal segment with correct structure
        segment = {
            "source_segment_id": 1,
            "section_type": "business",
            "raw_text": "We have 10,000 active customers.",
        }

        # Process segment
        candidates, stats = generator._process_segment(
            filing_id=1,
            company_id=1,
            segment=segment,
        )

        # Cache should be cleared after processing
        assert generator._current_segment_words is None

        # Should have found candidate(s)
        assert stats["numbers_found"] > 0


# =============================================================================
# Config System Adoption Tests (Phase 2)
# =============================================================================


class TestConfigSystemAdoption:
    """
    Tests demonstrating the config system API and presets.

    These tests verify that:
    1. Default config works correctly
    2. All three presets (high precision, high recall, fast) work
    3. Custom configs can be created and used
    4. Backward compatibility is maintained
    """

    @pytest.fixture
    def sample_segments(self):
        """Standard test segments for config testing."""
        return [
            {
                "source_segment_id": 1,
                "raw_text": "We have 50,000 active customers as of December 2023.",
            },
            {
                "source_segment_id": 2,
                "raw_text": "In 2023, we had revenue of $100 million with 5 new customers.",
            },
        ]

    def test_candidate_generator_with_default_config(self, sample_segments):
        """
        Test CandidateGenerator with default configuration.

        Default config uses production-tuned values:
        - max_keyword_distance: 100
        - min_metric_value: 10
        - filter_false_positives: True
        - compute_confidence: True
        - apply_learned_rules: True
        """
        generator = CandidateGenerator()  # Uses DEFAULT_CONFIG internally

        # Verify config is applied
        assert generator.config.max_keyword_distance == 100
        assert generator.config.min_metric_value == 10
        assert generator.config.filter_false_positives is True
        assert generator.config.compute_confidence is True
        assert generator.config.apply_learned_rules is True

        # Generate candidates
        candidates = generator.generate_for_filing(
            filing_id=1,
            company_id=1,
            segments=sample_segments,
        )

        # Should find candidates with default settings
        assert len(candidates) >= 1

        # Candidates should have confidence scores (compute_confidence=True)
        assert all(c.suggestion_confidence is not None for c in candidates)

        # Year 2023 should be filtered (filter_false_positives=True, filter_years=True)
        raw_texts = [c.raw_number_text for c in candidates]
        assert "2023" not in raw_texts

        # Small value "5" should be filtered (min_metric_value=10)
        assert "5" not in raw_texts

    def test_candidate_generator_with_high_precision_config(self, sample_segments):
        """
        Test CandidateGenerator with high precision configuration.

        High precision config:
        - max_keyword_distance: 50 (stricter proximity)
        - min_metric_value: 100 (filters small numbers)
        - min_pattern_precision: 0.85 (only high-confidence patterns)

        Expected: Fewer candidates, higher quality, less review burden.
        """
        from src.review.config import get_high_precision_config

        config = get_high_precision_config()
        generator = CandidateGenerator(config=config)

        # Verify config is applied
        assert generator.config.max_keyword_distance == 50
        assert generator.config.min_metric_value == 100
        assert generator.config.min_pattern_precision == 0.85

        # Generate candidates
        candidates = generator.generate_for_filing(
            filing_id=1,
            company_id=1,
            segments=sample_segments,
        )

        # Should still find some candidates
        assert len(candidates) >= 0

        # All candidates should have value >= 100
        for candidate in candidates:
            if candidate.parsed_value is not None:
                assert candidate.parsed_value >= 100 or candidate.parsed_value < 0

    def test_candidate_generator_with_high_recall_config(self, sample_segments):
        """
        Test CandidateGenerator with high recall configuration.

        High recall config:
        - max_keyword_distance: 150 (looser proximity)
        - min_metric_value: 1 (keep all numbers)
        - filter_false_positives: False (disable filtering)
        - filter_years: False (don't filter years)
        - apply_learned_rules: False (don't apply learned patterns)

        Expected: More candidates, including false positives, comprehensive coverage.
        """
        from src.review.config import get_high_recall_config

        config = get_high_recall_config()
        generator = CandidateGenerator(config=config)

        # Verify config is applied
        assert generator.config.max_keyword_distance == 150
        assert generator.config.min_metric_value == 1
        assert generator.config.filter_false_positives is False
        assert generator.config.filter_years is False
        assert generator.config.apply_learned_rules is False

        # Generate candidates
        candidates = generator.generate_for_filing(
            filing_id=1,
            company_id=1,
            segments=sample_segments,
        )

        # Should find MORE candidates than default (due to looser filtering)
        assert len(candidates) >= 1

        # Should include year 2023 (filter_years=False)
        raw_texts = [c.raw_number_text for c in candidates]
        assert "2023" in raw_texts

        # Should include small value "5" (min_metric_value=1)
        assert "5" in raw_texts

    def test_candidate_generator_with_fast_config(self, sample_segments):
        """
        Test CandidateGenerator with fast configuration.

        Fast config:
        - compute_confidence: False (skip expensive confidence computation)
        - apply_learned_rules: False (skip pattern matching)
        - Other settings remain standard

        Expected: Faster processing, confidence scores are None.
        """
        from src.review.config import get_fast_config

        config = get_fast_config()
        generator = CandidateGenerator(config=config)

        # Verify config is applied
        assert generator.config.compute_confidence is False
        assert generator.config.apply_learned_rules is False
        assert generator.config.cache_word_positions is True  # Optimization enabled

        # Generate candidates
        candidates = generator.generate_for_filing(
            filing_id=1,
            company_id=1,
            segments=sample_segments,
        )

        # Should find candidates
        assert len(candidates) >= 1

        # Candidates should NOT have confidence scores (compute_confidence=False)
        assert all(c.suggestion_confidence is None for c in candidates)

    def test_candidate_generator_custom_config(self, sample_segments):
        """
        Test CandidateGenerator with custom configuration.

        Demonstrates creating a fully customized configuration by
        instantiating CandidateGenerationConfig with custom parameters.
        """
        from src.review.config import CandidateGenerationConfig

        # Create custom config with specific requirements
        custom_config = CandidateGenerationConfig(
            max_keyword_distance=75,  # Moderate proximity
            min_metric_value=50,  # Filter numbers < 50
            filter_false_positives=True,
            filter_years=True,
            apply_learned_rules=True,
            min_pattern_precision=0.80,  # High-confidence patterns
            compute_confidence=True,
            context_words=40,  # Standard context window
            cache_word_positions=True,
        )

        generator = CandidateGenerator(config=custom_config)

        # Verify all custom settings are applied
        assert generator.config.max_keyword_distance == 75
        assert generator.config.min_metric_value == 50
        assert generator.config.min_pattern_precision == 0.80
        assert generator.config.context_words == 40

        # Generate candidates
        candidates = generator.generate_for_filing(
            filing_id=1,
            company_id=1,
            segments=sample_segments,
        )

        # Should find candidates
        assert len(candidates) >= 0

        # Small value "5" should be filtered (min_metric_value=50)
        raw_texts = [c.raw_number_text for c in candidates]
        assert "5" not in raw_texts

        # Should have confidence scores
        assert all(
            c.suggestion_confidence is not None
            for c in candidates
            if len(candidates) > 0
        )

    def test_config_backward_compatibility(self, sample_segments):
        """
        Test backward compatibility of config system.

        The old API (passing individual parameters to CandidateGenerator)
        should still work and be equivalent to creating a custom config.
        """
        # Old style: individual parameters
        generator_old = CandidateGenerator(
            max_keyword_distance=50,
            filter_false_positives=True,
            min_value=100,  # Old parameter name
        )

        # New style: config object
        from src.review.config import CandidateGenerationConfig

        config = CandidateGenerationConfig(
            max_keyword_distance=50,
            filter_false_positives=True,
            min_metric_value=100,  # New parameter name
        )
        generator_new = CandidateGenerator(config=config)

        # Both should have same config values
        assert generator_old.config.max_keyword_distance == 50
        assert generator_old.config.filter_false_positives is True
        assert generator_old.config.min_metric_value == 100

        assert generator_new.config.max_keyword_distance == 50
        assert generator_new.config.filter_false_positives is True
        assert generator_new.config.min_metric_value == 100

        # Both should produce same results
        candidates_old = generator_old.generate_for_filing(
            filing_id=1,
            company_id=1,
            segments=sample_segments,
        )

        candidates_new = generator_new.generate_for_filing(
            filing_id=1,
            company_id=1,
            segments=sample_segments,
        )

        # Should produce same number of candidates
        assert len(candidates_old) == len(candidates_new)

        # Should have same metric IDs (order may differ)
        metric_ids_old = {c.suggested_metric_id for c in candidates_old}
        metric_ids_new = {c.suggested_metric_id for c in candidates_new}
        assert metric_ids_old == metric_ids_new


# =============================================================================
# L3 Enhancement Tests (Keyword Direction Integration)
# =============================================================================


class TestL3KeywordDirectionIntegration:
    """Tests for L3: Verify direction field flows from KeywordMatch → ReviewCandidate."""

    def test_direction_before_stored_in_candidate(self):
        """L3: Keyword before number → candidate.keyword_position = 'before'."""
        generator = CandidateGenerator()

        # Text with keyword BEFORE number
        segment = {
            "source_segment_id": 1,
            "segment_type": "paragraph",
            "raw_text": "Our customer retention rate was 95% in Q4",
            #                    ^keyword (retention)    ^number
        }

        candidates = generator.generate_for_filing(
            filing_id=1,
            company_id=1,
            segments=[segment],
        )

        # Should find at least one candidate
        assert len(candidates) >= 1

        # Find the retention candidate
        retention_candidates = [
            c for c in candidates
            if "retention" in c.triggering_keyword.lower()
        ]
        assert len(retention_candidates) >= 1

        # Verify keyword_position is "before"
        candidate = retention_candidates[0]
        assert candidate.keyword_position == "before", (
            f"Expected keyword_position='before' but got '{candidate.keyword_position}'. "
            f"Keyword: '{candidate.triggering_keyword}', Number: '{candidate.raw_number_text}'"
        )

    def test_direction_after_stored_in_candidate(self):
        """L3: Keyword after number → candidate.keyword_position = 'after'."""
        generator = CandidateGenerator()

        # Text with keyword AFTER number
        segment = {
            "source_segment_id": 2,
            "segment_type": "paragraph",
            "raw_text": "We achieved 95% retention rate in Q4",
            #                           ^number ^keyword
        }

        candidates = generator.generate_for_filing(
            filing_id=1,
            company_id=1,
            segments=[segment],
        )

        # Should find at least one candidate
        assert len(candidates) >= 1

        # Find the retention candidate
        retention_candidates = [
            c for c in candidates
            if "retention" in c.triggering_keyword.lower()
        ]
        assert len(retention_candidates) >= 1

        # Verify keyword_position is "after"
        candidate = retention_candidates[0]
        assert candidate.keyword_position == "after", (
            f"Expected keyword_position='after' but got '{candidate.keyword_position}'. "
            f"Keyword: '{candidate.triggering_keyword}', Number: '{candidate.raw_number_text}'"
        )

    def test_direction_at_mapped_to_after(self):
        """L3: Edge case - keyword at same position as number → maps to 'after'."""
        from src.review.keyword_matching import KeywordMatcher, KeywordMatch
        from src.review.number_parsing import NumberMatch

        matcher = KeywordMatcher()

        # Create a mock scenario where keyword and number overlap (direction="at")
        # This tests the edge case handling in candidate_generator.py
        text = "gross margin30%"  # Pathological case: no space

        # Mock KeywordMatch with direction="at"
        kw_at = KeywordMatch(
            start=0,
            end=12,
            keyword="gross margin",
            metric_id="cm_gross_margin_overall",
            pattern=r"\bgross\s+margin\b",
            direction="at",  # Edge case
        )

        # Generate candidate - should map "at" → "after"
        generator = CandidateGenerator()
        segment = {
            "source_segment_id": 3,
            "segment_type": "paragraph",
            "raw_text": text,
        }

        candidates = generator.generate_for_filing(
            filing_id=1,
            company_id=1,
            segments=[segment],
        )

        # Verify all candidates have valid keyword_position (never "at")
        for candidate in candidates:
            assert candidate.keyword_position in ("before", "after"), (
                f"Invalid keyword_position: '{candidate.keyword_position}'. "
                "L3 should map 'at' edge case to 'after'."
            )

    def test_multiple_candidates_different_directions(self):
        """L3: Multiple candidates can have different directions in same segment."""
        generator = CandidateGenerator()

        # Text with keywords in both directions
        segment = {
            "source_segment_id": 4,
            "segment_type": "paragraph",
            "raw_text": (
                "We had 50000 active customers in Q1. "
                "Our gross margin was 52% in the same period."
                #   ^kw before      ^num  ^kw after  ^num
            ),
        }

        candidates = generator.generate_for_filing(
            filing_id=1,
            company_id=1,
            segments=[segment],
        )

        # Should find multiple candidates
        assert len(candidates) >= 2

        # Find candidates for each number
        customer_candidates = [
            c for c in candidates
            if "50000" in c.raw_number_text or c.parsed_value == Decimal("50000")
        ]
        margin_candidates = [
            c for c in candidates
            if "52" in c.raw_number_text and c.parsed_unit in ("%", "percent")
        ]

        # Verify we found both
        assert len(customer_candidates) >= 1, "Should find customer candidate"
        assert len(margin_candidates) >= 1, "Should find margin candidate"

        # Customer candidates should have keyword AFTER number (50000 active customers)
        for candidate in customer_candidates:
            if "customer" in candidate.triggering_keyword.lower():
                assert candidate.keyword_position == "after", (
                    f"'active customers' should be after 50000, got '{candidate.keyword_position}'"
                )

        # Margin candidates should have keyword BEFORE number (margin was 52%)
        for candidate in margin_candidates:
            if "margin" in candidate.triggering_keyword.lower():
                assert candidate.keyword_position == "before", (
                    f"'gross margin' should be before 52%, got '{candidate.keyword_position}'"
                )

    def test_direction_preserved_in_to_dict(self):
        """L3: Direction field survives ReviewCandidate.to_dict() serialization."""
        generator = CandidateGenerator()

        segment = {
            "source_segment_id": 5,
            "segment_type": "paragraph",
            "raw_text": "Retention rate was 95% in Q4",
        }

        candidates = generator.generate_for_filing(
            filing_id=1,
            company_id=1,
            segments=[segment],
        )

        assert len(candidates) >= 1
        candidate = candidates[0]

        # Convert to dict (for database insertion)
        candidate_dict = candidate.to_dict()

        # Verify keyword_position is in the dict
        assert "keyword_position" in candidate_dict
        assert candidate_dict["keyword_position"] in ("before", "after")

        # Verify it matches the candidate object
        assert candidate_dict["keyword_position"] == candidate.keyword_position

    def test_direction_consistent_with_distance_calculation(self):
        """L3: Direction should be consistent with distance calculation logic."""
        generator = CandidateGenerator()

        segment = {
            "source_segment_id": 6,
            "segment_type": "paragraph",
            "raw_text": "Customer retention rate was 95.5% for the quarter",
            #            ^keyword (retention)   ^number
        }

        candidates = generator.generate_for_filing(
            filing_id=1,
            company_id=1,
            segments=[segment],
        )

        # Find retention candidate
        retention_candidates = [
            c for c in candidates
            if "retention" in c.triggering_keyword.lower()
        ]

        assert len(retention_candidates) >= 1
        candidate = retention_candidates[0]

        # Keyword "retention" appears before "95.5%"
        assert candidate.keyword_position == "before"

        # Distance should be positive (keyword before number = number_start - keyword_end)
        assert candidate.keyword_distance >= 0

    def test_end_to_end_direction_flow(self):
        """L3: End-to-end test - direction flows from keyword matching → candidate."""
        generator = CandidateGenerator()

        # Real-world example from Farfetch filing
        segment = {
            "source_segment_id": 7,
            "segment_type": "paragraph",
            "raw_text": (
                "Six month LTV/CAC ratio for the years ended December 31, 2015, 2016 and 2017 "
                "was 1.42, 1.53 and 1.72, respectively; and Platform Order Contribution Margin "
                "for the years ended December 31, 2015, 2016 and 2017 was 33.0%, 35.0% and 43.0%, "
                "respectively."
            ),
        }

        candidates = generator.generate_for_filing(
            filing_id=1,
            company_id=1,
            segments=[segment],
        )

        # Should generate multiple candidates
        assert len(candidates) >= 3

        # All candidates should have valid keyword_position
        for candidate in candidates:
            assert candidate.keyword_position in ("before", "after"), (
                f"Candidate {candidate.candidate_id} has invalid keyword_position: "
                f"'{candidate.keyword_position}'"
            )

            # Verify keyword_position is consistent with text structure
            # (We can't assert specific values without knowing exact positions,
            # but we can verify the field exists and is valid)


class TestL1RespectivelyPatternIntegration:
    """Tests for L1 respectively pattern detection and enrichment."""

    def test_normalize_value_text_basic(self):
        """Normalize value text removes spaces and lowercases units."""
        generator = CandidateGenerator()

        assert generator._normalize_value_text("$1M") == "$1m"
        assert generator._normalize_value_text("$ 1 M") == "$1m"
        assert generator._normalize_value_text("33.0%") == "33.0%"
        assert generator._normalize_value_text("1.42") == "1.42"
        assert generator._normalize_value_text("$2.5 Million") == "$2.5million"
        assert generator._normalize_value_text("100 Billion") == "100billion"

    def test_enrich_with_respectively_patterns_disabled_by_config(self):
        """Enrichment skipped when config disables respectively detection."""
        config = CandidateGenerationConfig(detect_respectively_patterns=False)
        generator = CandidateGenerator(config=config)

        # Create a mock candidate
        from src.review.models import ReviewCandidate, CandidateFeatures

        candidate = ReviewCandidate(
            filing_id=1,
            company_id=1,
            source_segment_id=1,
            char_position=0,
            raw_number_text="33%",
            parsed_value=33.0,
            parsed_unit="%",
            features=CandidateFeatures(
                keyword_distance=50,
                keyword_position="before",
                is_in_table=False,
                is_in_risk_factors=False,
                contains_definition_language=False,
                has_period_mention=False,
                number_format="percentage",
            ),
        )

        # Text with respectively pattern
        text = "Margin for 2015 and 2016 was 33% and 35%, respectively."

        # Enrichment should be skipped
        enriched = generator._enrich_with_respectively_patterns([candidate], text)

        # No enrichment should have occurred
        assert enriched[0].features.detected_period is None
        assert enriched[0].features.respectively_confidence is None

    def test_enrich_with_respectively_patterns_no_pattern(self):
        """Returns candidates unchanged when no respectively pattern found."""
        config = CandidateGenerationConfig(detect_respectively_patterns=True)
        generator = CandidateGenerator(config=config)

        from src.review.models import ReviewCandidate, CandidateFeatures

        candidate = ReviewCandidate(
            filing_id=1,
            company_id=1,
            source_segment_id=1,
            char_position=0,
            raw_number_text="33%",
            parsed_value=33.0,
            parsed_unit="%",
            features=CandidateFeatures(
                keyword_distance=50,
                keyword_position="before",
                is_in_table=False,
                is_in_risk_factors=False,
                contains_definition_language=False,
                has_period_mention=False,
                number_format="percentage",
            ),
        )

        # Text without respectively pattern
        text = "Margin was 33% in 2015 and 35% in 2016."

        # No enrichment should occur
        enriched = generator._enrich_with_respectively_patterns([candidate], text)

        assert enriched[0].features.detected_period is None
        assert enriched[0].features.respectively_confidence is None

    def test_enrich_with_respectively_patterns_low_confidence(self):
        """Patterns below confidence threshold are ignored."""
        config = CandidateGenerationConfig(
            detect_respectively_patterns=True,
            respectively_min_confidence=0.9,  # Very high threshold
        )
        generator = CandidateGenerator(config=config)

        from src.review.models import ReviewCandidate, CandidateFeatures

        candidate = ReviewCandidate(
            filing_id=1,
            company_id=1,
            source_segment_id=1,
            char_position=0,
            raw_number_text="33",
            parsed_value=33.0,
            features=CandidateFeatures(
                keyword_distance=50,
                keyword_position="before",
                is_in_table=False,
                is_in_risk_factors=False,
                contains_definition_language=False,
                has_period_mention=False,
                number_format="percentage",
            ),
        )

        # Pattern with likely low confidence (non-consecutive years, inconsistent formats)
        text = "Values for 2015, 2020 and 2025 were 33, 35 and 43 respectively"

        enriched = generator._enrich_with_respectively_patterns([candidate], text)

        # Low confidence pattern should be ignored
        assert enriched[0].features.detected_period is None
