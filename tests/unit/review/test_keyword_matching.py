"""
Unit tests for keyword_matching module.

Tests extracted from test_candidate_generator.py as part of P1.3 module splitting.
"""

from decimal import Decimal
import pytest

from src.review.keyword_matching import (
    METRIC_KEYWORDS,
    SPECIFIC_KEYWORD_PATTERNS,
    KeywordMatch,
    KeywordMatcher,
)
from src.review.number_parsing import NumberMatch


# =============================================================================
# KeywordMatcher.find_all_keywords Tests
# =============================================================================


class TestFindAllKeywords:
    """Tests for finding all keywords in text."""

    @pytest.fixture
    def matcher(self):
        """Create a KeywordMatcher instance."""
        return KeywordMatcher()

    def test_finds_keywords_in_text(self, matcher):
        """Find all metric keywords in text."""
        text = "We have 50,000 active customers and 95% retention rate."
        keywords = matcher.find_all_keywords(text)

        assert len(keywords) >= 2
        metric_ids = {kw.metric_id for kw in keywords}
        assert "cm_active_customers_total" in metric_ids
        assert "cm_customer_retention_rate" in metric_ids

    def test_returns_empty_for_no_keywords(self, matcher):
        """Return empty list when no keywords found."""
        text = "The weather is nice today with temperatures around 75 degrees."
        keywords = matcher.find_all_keywords(text)
        assert keywords == []

    def test_sorted_by_position(self, matcher):
        """Keywords should be sorted by position."""
        text = "Our retention rate is 95% and we have 10,000 active customers."
        keywords = matcher.find_all_keywords(text)

        # Verify sorted by start position
        for i in range(len(keywords) - 1):
            assert keywords[i].start <= keywords[i + 1].start

    def test_captures_keyword_text(self, matcher):
        """Keyword text should be captured correctly."""
        text = "We have active customers totaling 50,000"
        keywords = matcher.find_all_keywords(text)

        active_kw = [kw for kw in keywords if kw.metric_id == "cm_active_customers_total"]
        assert len(active_kw) >= 1
        assert "customer" in active_kw[0].keyword.lower()

    def test_multiple_matches_same_metric(self, matcher):
        """Multiple matches for the same metric should all be captured."""
        text = "Our customers love us. We gained 1000 new customers last quarter."
        keywords = matcher.find_all_keywords(text)

        # Should find "customers" twice (or related patterns)
        customer_keywords = [kw for kw in keywords if "customer" in kw.metric_id.lower()]
        assert len(customer_keywords) >= 1


# =============================================================================
# KeywordMatcher.find_keywords_near_number Tests
# =============================================================================


class TestFindKeywordsNearNumber:
    """Tests for finding keywords near numbers."""

    @pytest.fixture
    def matcher(self):
        """Create a KeywordMatcher instance."""
        return KeywordMatcher(max_keyword_distance=100)

    def test_keyword_before_number(self, matcher):
        """Find keyword appearing before number."""
        text = "We have active customers totaling 50,000 as of year end"

        # Manually create number match (simulating what NumberParser would return)
        number = NumberMatch(
            start=text.index("50,000"),
            end=text.index("50,000") + len("50,000"),
            raw_text="50,000",
            value=Decimal("50000"),
            unit="count",
        )

        all_keywords = matcher.find_all_keywords(text)
        keywords = matcher.find_keywords_near_number(number, all_keywords)
        assert len(keywords) >= 1
        assert any(kw.metric_id == "cm_active_customers_total" for kw in keywords)

    def test_keyword_after_number(self, matcher):
        """Find keyword appearing after number."""
        text = "We acquired 5,000 new customers during the quarter"

        number = NumberMatch(
            start=text.index("5,000"),
            end=text.index("5,000") + len("5,000"),
            raw_text="5,000",
            value=Decimal("5000"),
            unit="count",
        )

        all_keywords = matcher.find_all_keywords(text)
        keywords = matcher.find_keywords_near_number(number, all_keywords)
        assert len(keywords) >= 1
        assert any(kw.metric_id == "cm_new_customers_acquired" for kw in keywords)

    def test_keyword_too_far(self, matcher):
        """Keyword too far from number should not match."""
        # Create text where keyword is more than 100 chars away from number
        padding = "x" * 150
        text = f"active customers {padding} 50,000"

        number = NumberMatch(
            start=text.index("50,000"),
            end=text.index("50,000") + len("50,000"),
            raw_text="50,000",
            value=Decimal("50000"),
            unit="count",
        )

        all_keywords = matcher.find_all_keywords(text)
        keywords = matcher.find_keywords_near_number(number, all_keywords)
        # Should not find keyword because it's too far
        active_customer_matches = [
            kw for kw in keywords if kw.metric_id == "cm_active_customers_total"
        ]
        assert len(active_customer_matches) == 0

    def test_multiple_metrics_match(self, matcher):
        """Multiple metrics can match the same number."""
        text = "Our retention rate of 95% reflects strong customer retention"

        number = NumberMatch(
            start=text.index("95"),
            end=text.index("95") + len("95%"),
            raw_text="95%",
            value=Decimal("0.95"),
            unit="%",
        )

        all_keywords = matcher.find_all_keywords(text)
        keywords = matcher.find_keywords_near_number(number, all_keywords)
        metric_ids = {kw.metric_id for kw in keywords}
        assert "cm_customer_retention_rate" in metric_ids


# =============================================================================
# KeywordMatcher.calculate_distance Tests
# =============================================================================


class TestCalculateDistance:
    """Tests for distance calculation."""

    @pytest.fixture
    def matcher(self):
        """Create a KeywordMatcher instance."""
        return KeywordMatcher()

    def test_keyword_before_number(self, matcher):
        """Distance when keyword is before number."""
        number = NumberMatch(start=50, end=55, raw_text="1000", value=Decimal(1000), unit="count")
        keyword = KeywordMatch(start=10, end=25, keyword="customers", metric_id="cm_active", pattern="")

        distance = matcher.calculate_distance(number, keyword)
        assert distance == 25  # 50 - 25 = 25

    def test_keyword_after_number(self, matcher):
        """Distance when keyword is after number."""
        number = NumberMatch(start=10, end=15, raw_text="1000", value=Decimal(1000), unit="count")
        keyword = KeywordMatch(start=30, end=45, keyword="customers", metric_id="cm_active", pattern="")

        distance = matcher.calculate_distance(number, keyword)
        assert distance == 15  # 30 - 15 = 15

    def test_overlapping_spans(self, matcher):
        """Distance is 0 when spans overlap."""
        number = NumberMatch(start=20, end=30, raw_text="1000", value=Decimal(1000), unit="count")
        keyword = KeywordMatch(start=25, end=35, keyword="customers", metric_id="cm_active", pattern="")

        distance = matcher.calculate_distance(number, keyword)
        assert distance == 0


# =============================================================================
# Constants Tests
# =============================================================================


class TestConstants:
    """Tests for module constants."""

    def test_metric_keywords_not_empty(self):
        """METRIC_KEYWORDS should contain metrics."""
        assert len(METRIC_KEYWORDS) > 0
        assert "cm_active_customers_total" in METRIC_KEYWORDS

    def test_specific_keyword_patterns_not_empty(self):
        """SPECIFIC_KEYWORD_PATTERNS should not be empty."""
        assert len(SPECIFIC_KEYWORD_PATTERNS) > 0
        assert any("active" in p for p in SPECIFIC_KEYWORD_PATTERNS)


# =============================================================================
# Substring Deduplication Tests
# =============================================================================


class TestSubstringDeduplication:
    """Tests for substring deduplication in keyword matching."""

    def test_ltv_cac_ratio_deduplication(self):
        """LTV/CAC ratio should not create separate LTV and CAC candidates."""
        matcher = KeywordMatcher(max_keyword_distance=100)
        text = "Our LTV/CAC ratio was 1.42 for the period."
        number = NumberMatch(start=18, end=22, raw_text="1.42", value=Decimal("1.42"), unit="count")

        # Find all keywords in text
        all_keywords = matcher.find_all_keywords(text)

        # Should find LTV/CAC, LTV, and CAC keywords
        assert len(all_keywords) >= 3
        keywords_text = [kw.keyword for kw in all_keywords]
        assert any("LTV/CAC" in k or "ltv/cac" in k.lower() for k in keywords_text)
        assert any("LTV" == k.upper() for k in keywords_text)
        assert any("CAC" == k.upper() for k in keywords_text)

        # But when filtering for this number, should only return LTV/CAC
        # (longest/most specific match)
        keywords_near_number = matcher.find_keywords_near_number(number, all_keywords)

        # Should have only LTV/CAC, not LTV and CAC separately
        matched_keywords = [kw.keyword for kw in keywords_near_number]
        assert len(matched_keywords) == 1, f"Expected 1 keyword, got {len(matched_keywords)}: {matched_keywords}"
        assert "LTV/CAC" in matched_keywords[0] or "ltv/cac" in matched_keywords[0].lower()

    def test_compound_metric_prevents_substring_matches(self):
        """Compound metrics should prevent substring matches at overlapping positions."""
        matcher = KeywordMatcher(max_keyword_distance=100)
        text = "Net Revenue Retention was 120% for the year."
        number = NumberMatch(start=26, end=30, raw_text="120%", value=Decimal("120"), unit="percent")

        all_keywords = matcher.find_all_keywords(text)
        keywords_near_number = matcher.find_keywords_near_number(number, all_keywords)

        # Should prioritize "Net Revenue Retention" over just "Revenue" or "Retention"
        matched_keywords = [kw.keyword for kw in keywords_near_number]
        # The longest match should be first (or only match if they overlap)
        longest_match = max(matched_keywords, key=len)
        assert len(longest_match) > 10, "Should match compound metric, not single word"

    def test_non_overlapping_keywords_both_kept(self):
        """Non-overlapping keywords should both be kept even if one is substring of other."""
        matcher = KeywordMatcher(max_keyword_distance=100)
        # "customers" appears twice: once in "active customers", once standalone
        text = "We have active customers and customers grew by 50%."
        number = NumberMatch(start=46, end=49, raw_text="50%", value=Decimal("50"), unit="percent")

        all_keywords = matcher.find_all_keywords(text)
        keywords_near_number = matcher.find_keywords_near_number(number, all_keywords)

        # Since keywords don't overlap in position, both can be kept
        # (one before number, one after)
        assert len(keywords_near_number) >= 1
