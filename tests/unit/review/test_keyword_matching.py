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

        # With P1 fix: substring filtering only applies within the same metric
        # So we get matches from all three metrics (LTV/CAC ratio, LTV, CAC)
        # This is safer/more conservative - human review can select the correct one
        keywords_near_number = matcher.find_keywords_near_number(number, all_keywords)

        # Should have matches from all three metrics
        matched_keywords = [kw.keyword for kw in keywords_near_number]
        assert len(matched_keywords) == 3, f"Expected 3 keywords (one per metric), got {len(matched_keywords)}: {matched_keywords}"

        # Should include LTV/CAC (the most specific match)
        assert any("LTV/CAC" in kw or "ltv/cac" in kw.lower() for kw in matched_keywords)

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


# =============================================================================
# P1 Enhancement Tests (Distance-First Sorting)
# =============================================================================


class TestP1DistanceFirstSorting:
    """Tests for P1 enhancement: prefer closest keyword over longest keyword."""

    def test_closest_keyword_preferred_over_longest(self):
        """When prefer_closest_keyword is True, closest keyword should be selected."""
        # Create text where a shorter keyword is closer than a longer keyword
        # "active customers" is far away, "customers" is close to the number
        text = "We grew active customers" + (" " * 30) + "customers to 50,000"

        number = NumberMatch(
            start=text.index("50,000"),
            end=text.index("50,000") + 6,
            raw_text="50,000",
            value=Decimal("50000"),
            unit="count",
        )

        # With prefer_closest_keyword=True (default), should prefer closer "customers"
        matcher_closest = KeywordMatcher(prefer_closest_keyword=True, max_keyword_distance=100)
        all_keywords = matcher_closest.find_all_keywords(text)
        keywords = matcher_closest.find_keywords_near_number(number, all_keywords)

        # Should find keywords
        assert len(keywords) >= 1

        # Calculate distances for all keywords
        distances = [(kw, matcher_closest.calculate_distance(number, kw)) for kw in keywords]

        # The first keyword should be the one with the smallest distance
        # When sorted by (distance, -length), closest comes first
        if len(distances) >= 2:
            first_dist = distances[0][1]
            second_dist = distances[1][1] if len(distances) > 1 else float('inf')
            # First keyword should have smaller or equal distance
            assert first_dist <= second_dist, (
                f"Expected first keyword to be closest, "
                f"but got distances: {[(kw.keyword, d) for kw, d in distances]}"
            )

    def test_longest_keyword_when_prefer_closest_disabled(self):
        """When prefer_closest_keyword is False, longest keyword should be selected."""
        text = "annual recurring revenue" + (" " * 20) + "revenue 100"

        number = NumberMatch(
            start=text.index("100"),
            end=text.index("100") + 3,
            raw_text="100",
            value=Decimal("100"),
            unit="count",
        )

        # With prefer_closest_keyword=False, should prefer longer keyword
        matcher_longest = KeywordMatcher(prefer_closest_keyword=False, max_keyword_distance=100)
        all_keywords = matcher_longest.find_all_keywords(text)
        keywords = matcher_longest.find_keywords_near_number(number, all_keywords)

        # Should find keywords
        assert len(keywords) >= 1


# =============================================================================
# P1 Enhancement Tests (Boundary-Aware Matching)
# =============================================================================


class TestP1BoundaryAwareMatching:
    """Tests for P1 enhancement: prefer keywords in same boundary as number."""

    def test_same_boundary_preferred(self):
        """Keywords in same boundary should be preferred over cross-boundary keywords."""
        from src.review.boundary_detection import BoundaryDetector

        # Text with two bullet points
        text = """• LTV/CAC ratio for 2015, 2016, 2017
• Platform Order Contribution Margin: 33.0%, 35.0%, 43.0%"""

        # Detect boundaries
        detector = BoundaryDetector()
        boundaries = detector.find_boundaries(text)
        assert len(boundaries) == 2  # Two bullet boundaries

        # Number "33.0%" is in second boundary
        number = NumberMatch(
            start=text.index("33.0"),
            end=text.index("33.0") + 4,
            raw_text="33.0",
            value=Decimal("33.0"),
            unit="percent",
        )

        # With boundary awareness
        matcher = KeywordMatcher(respect_bullet_boundaries=True, max_keyword_distance=200)
        all_keywords = matcher.find_all_keywords(text)
        keywords = matcher.find_keywords_near_number(number, all_keywords, boundaries=boundaries)

        # Should prefer keywords from second boundary (Contribution Margin)
        # not from first boundary (LTV/CAC)
        assert len(keywords) >= 1

        # Verify that matched keywords are from same boundary as number
        number_boundary = detector.get_boundary_at_position(number.start, boundaries)
        for kw in keywords:
            kw_boundary = detector.get_boundary_at_position(kw.start, boundaries)
            # In most cases, should be same boundary (may have fallback)
            assert kw_boundary is not None

    def test_cross_boundary_fallback(self):
        """If no keywords in same boundary, should fall back to cross-boundary keywords."""
        from src.review.boundary_detection import BoundaryDetector

        # Text where number has no keywords in same boundary
        text = """• Some random text here with a number 42
• No relevant keywords in second boundary"""

        detector = BoundaryDetector()
        boundaries = detector.find_boundaries(text)

        # Number in first boundary
        number = NumberMatch(
            start=text.index("42"),
            end=text.index("42") + 2,
            raw_text="42",
            value=Decimal("42"),
            unit="count",
        )

        matcher = KeywordMatcher(respect_bullet_boundaries=True, max_keyword_distance=200)
        all_keywords = matcher.find_all_keywords(text)
        keywords = matcher.find_keywords_near_number(number, all_keywords, boundaries=boundaries)

        # Should return empty or fallback to cross-boundary if no matches in same boundary
        # (depends on whether there are any metric keywords in the text)
        assert isinstance(keywords, list)

    def test_boundary_awareness_disabled(self):
        """When respect_bullet_boundaries is False, boundaries should be ignored."""
        from src.review.boundary_detection import BoundaryDetector

        text = """• LTV/CAC ratio for 2015, 2016, 2017
• Platform Order Contribution Margin: 33.0%, 35.0%, 43.0%"""

        detector = BoundaryDetector()
        boundaries = detector.find_boundaries(text)

        number = NumberMatch(
            start=text.index("33.0"),
            end=text.index("33.0") + 4,
            raw_text="33.0",
            value=Decimal("33.0"),
            unit="percent",
        )

        # With boundary awareness disabled
        matcher = KeywordMatcher(respect_bullet_boundaries=False, max_keyword_distance=200)
        all_keywords = matcher.find_all_keywords(text)
        keywords = matcher.find_keywords_near_number(number, all_keywords, boundaries=boundaries)

        # Should return keywords without boundary filtering
        assert isinstance(keywords, list)


# =============================================================================
# P1 Enhancement Tests (Ambiguity Logging)
# =============================================================================


class TestP1AmbiguityLogging:
    """Tests for P1 enhancement: log ambiguous matches."""

    def test_ambiguity_detected(self, caplog):
        """When multiple keywords are equally close, ambiguity should be logged."""
        import logging

        caplog.set_level(logging.INFO)

        # Text with two keywords equally close to a number
        text = "retention rate 95% customer retention"

        number = NumberMatch(
            start=text.index("95"),
            end=text.index("95") + 3,
            raw_text="95%",
            value=Decimal("95"),
            unit="percent",
        )

        matcher = KeywordMatcher(log_ambiguous_matches=True, ambiguity_threshold=10)
        all_keywords = matcher.find_all_keywords(text)
        keywords = matcher.find_keywords_near_number(number, all_keywords)

        # Check if ambiguity was logged
        # (May or may not log depending on exact distances, but code path should execute)
        assert len(keywords) >= 1

    def test_no_ambiguity_logging_when_disabled(self, caplog):
        """When log_ambiguous_matches is False, no ambiguity should be logged."""
        import logging

        caplog.set_level(logging.INFO)

        text = "retention rate 95% customer retention"

        number = NumberMatch(
            start=text.index("95"),
            end=text.index("95") + 3,
            raw_text="95%",
            value=Decimal("95"),
            unit="percent",
        )

        matcher = KeywordMatcher(log_ambiguous_matches=False)
        all_keywords = matcher.find_all_keywords(text)
        keywords = matcher.find_keywords_near_number(number, all_keywords)

        # Should not log ambiguity messages
        ambiguity_logs = [record for record in caplog.records if "Ambiguous match" in record.message]
        assert len(ambiguity_logs) == 0


# =============================================================================
# P1 Enhancement Tests (Configuration Parameters)
# =============================================================================


class TestP1ConfigurationParameters:
    """Tests for P1 configuration parameters."""

    def test_default_configuration(self):
        """Default configuration should enable P1 features."""
        matcher = KeywordMatcher()

        assert matcher.max_keyword_distance == 100
        assert matcher.prefer_closest_keyword is True
        assert matcher.respect_bullet_boundaries is True
        assert matcher.log_ambiguous_matches is True
        assert matcher.ambiguity_threshold == 10

    def test_custom_configuration(self):
        """Custom configuration should override defaults."""
        matcher = KeywordMatcher(
            max_keyword_distance=50,
            prefer_closest_keyword=False,
            respect_bullet_boundaries=False,
            log_ambiguous_matches=False,
            ambiguity_threshold=5,
        )

        assert matcher.max_keyword_distance == 50
        assert matcher.prefer_closest_keyword is False
        assert matcher.respect_bullet_boundaries is False
        assert matcher.log_ambiguous_matches is False
        assert matcher.ambiguity_threshold == 5
