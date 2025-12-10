"""
Unit tests for candidate_generator module.
"""

from decimal import Decimal
import pytest

from src.review.candidate_generator import (
    CandidateGenerator,
    NumberMatch,
    KeywordMatch,
    NUMBER_REGEX,
    METRIC_KEYWORDS,
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
        text = "From 1,000 to 5,000 customers in 2023"
        matches = list(NUMBER_REGEX.finditer(text))
        assert len(matches) >= 2
        numbers = [m.group("number") for m in matches]
        assert "1,000" in numbers
        assert "5,000" in numbers


# =============================================================================
# CandidateGenerator._parse_number Tests
# =============================================================================


class TestParseNumber:
    """Tests for number parsing."""

    @pytest.fixture
    def generator(self):
        return CandidateGenerator()

    def test_parse_simple_integer(self, generator):
        """Parse simple integer."""
        text = "1234"
        match = NUMBER_REGEX.search(text)
        value, unit = generator._parse_number(match)
        assert value == Decimal("1234")
        assert unit == "count"

    def test_parse_with_commas(self, generator):
        """Parse number with comma separators."""
        text = "1,234,567"
        match = NUMBER_REGEX.search(text)
        value, unit = generator._parse_number(match)
        assert value == Decimal("1234567")
        assert unit == "count"

    def test_parse_decimal(self, generator):
        """Parse decimal number."""
        text = "12.345"
        match = NUMBER_REGEX.search(text)
        value, unit = generator._parse_number(match)
        assert value == Decimal("12.345")
        assert unit == "count"

    def test_parse_currency(self, generator):
        """Parse currency amount."""
        text = "$500"
        match = NUMBER_REGEX.search(text)
        value, unit = generator._parse_number(match)
        assert value == Decimal("500")
        assert unit == "usd"

    def test_parse_percentage(self, generator):
        """Parse percentage."""
        text = "95%"
        match = NUMBER_REGEX.search(text)
        value, unit = generator._parse_number(match)
        assert value == Decimal("95")
        assert unit == "%"

    def test_parse_million_multiplier(self, generator):
        """Parse million multiplier."""
        text = "50 million"
        match = NUMBER_REGEX.search(text)
        value, unit = generator._parse_number(match)
        assert value == Decimal("50000000")
        assert unit == "count"

    def test_parse_billion_multiplier(self, generator):
        """Parse billion multiplier."""
        text = "$2.5 billion"
        match = NUMBER_REGEX.search(text)
        value, unit = generator._parse_number(match)
        assert value == Decimal("2500000000")
        assert unit == "usd"

    def test_parse_thousand_multiplier(self, generator):
        """Parse thousand multiplier."""
        text = "100 thousand"
        match = NUMBER_REGEX.search(text)
        value, unit = generator._parse_number(match)
        assert value == Decimal("100000")
        assert unit == "count"


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
# CandidateGenerator._find_keywords_near_number Tests
# =============================================================================


class TestFindKeywordsNearNumber:
    """Tests for finding keywords near numbers."""

    @pytest.fixture
    def generator(self):
        return CandidateGenerator(max_keyword_distance=100)

    def test_keyword_before_number(self, generator):
        """Find keyword appearing before number."""
        text = "We have active customers totaling 50,000 as of year end"
        numbers = generator._find_numbers(text)
        assert len(numbers) >= 1

        keywords = generator._find_keywords_near_number(text, numbers[0])
        assert len(keywords) >= 1
        assert any(kw.metric_id == "cm_active_customers_total" for kw in keywords)

    def test_keyword_after_number(self, generator):
        """Find keyword appearing after number."""
        text = "We acquired 5,000 new customers during the quarter"
        numbers = generator._find_numbers(text)
        assert len(numbers) >= 1

        keywords = generator._find_keywords_near_number(text, numbers[0])
        assert len(keywords) >= 1
        assert any(kw.metric_id == "cm_new_customers_acquired" for kw in keywords)

    def test_keyword_too_far(self, generator):
        """Keyword too far from number should not match."""
        # Create text where keyword is more than 100 chars away from number
        padding = "x" * 150
        text = f"active customers {padding} 50,000"
        numbers = generator._find_numbers(text)
        assert len(numbers) >= 1

        keywords = generator._find_keywords_near_number(text, numbers[0])
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

        keywords = generator._find_keywords_near_number(text, numbers[0])
        metric_ids = {kw.metric_id for kw in keywords}
        assert "cm_customer_retention_rate" in metric_ids


# =============================================================================
# CandidateGenerator._calculate_distance Tests
# =============================================================================


class TestCalculateDistance:
    """Tests for distance calculation."""

    @pytest.fixture
    def generator(self):
        return CandidateGenerator()

    def test_keyword_before_number(self, generator):
        """Distance when keyword is before number."""
        number = NumberMatch(start=50, end=55, raw_text="1000", value=Decimal(1000), unit="count")
        keyword = KeywordMatch(start=10, end=25, keyword="customers", metric_id="cm_active", pattern="")

        distance = generator._calculate_distance(number, keyword)
        assert distance == 25  # 50 - 25 = 25

    def test_keyword_after_number(self, generator):
        """Distance when keyword is after number."""
        number = NumberMatch(start=10, end=15, raw_text="1000", value=Decimal(1000), unit="count")
        keyword = KeywordMatch(start=30, end=45, keyword="customers", metric_id="cm_active", pattern="")

        distance = generator._calculate_distance(number, keyword)
        assert distance == 15  # 30 - 15 = 15

    def test_overlapping_spans(self, generator):
        """Distance is 0 when spans overlap."""
        number = NumberMatch(start=20, end=30, raw_text="1000", value=Decimal(1000), unit="count")
        keyword = KeywordMatch(start=25, end=35, keyword="customers", metric_id="cm_active", pattern="")

        distance = generator._calculate_distance(number, keyword)
        assert distance == 0


# =============================================================================
# CandidateGenerator._extract_context Tests
# =============================================================================


class TestExtractContext:
    """Tests for context extraction."""

    @pytest.fixture
    def generator(self):
        return CandidateGenerator(context_words=5)  # Small for testing

    def test_context_around_position(self, generator):
        """Extract context around a position."""
        text = "one two three four five TARGET six seven eight nine ten"
        position = text.index("TARGET")

        context = generator._extract_context(text, position)
        assert "TARGET" in context
        # Should have some words before and after
        assert len(context.split()) >= 3

    def test_context_at_start(self, generator):
        """Extract context when position is near start."""
        text = "TARGET one two three four five six seven eight nine ten"
        position = 0

        context = generator._extract_context(text, position)
        assert "TARGET" in context

    def test_context_at_end(self, generator):
        """Extract context when position is near end."""
        text = "one two three four five six seven eight nine TARGET"
        position = text.index("TARGET")

        context = generator._extract_context(text, position)
        assert "TARGET" in context


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
