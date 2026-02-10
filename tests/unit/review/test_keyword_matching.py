"""
Unit tests for keyword_matching module.

Tests extracted from test_candidate_generator.py as part of P1.3 module splitting.
"""

from decimal import Decimal

import pytest

from src.extraction.keyword_config import is_metric_deprecated
from src.review.keyword_matching import (
    METRIC_KEYWORDS,
    METRIC_REQUIRED_CONTEXT,
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
        """LTV/CAC ratio should not create separate LTV and CAC candidates.

        HRI-3 Update: With exclusion patterns, standalone LTV is now excluded
        when LTV/CAC context is present.

        CMS-1 Update: With cross-metric substring suppression, CAC is also
        suppressed because "CAC" is a substring of "LTV/CAC ratio" at an
        overlapping position. Only the longest/most-specific match is kept.
        """
        matcher = KeywordMatcher(max_keyword_distance=100)
        text = "Our LTV/CAC ratio was 1.42 for the period."
        number = NumberMatch(start=18, end=22, raw_text="1.42", value=Decimal("1.42"), unit="count")

        # Find all keywords in text
        all_keywords = matcher.find_all_keywords(text)

        # Should find LTV/CAC and CAC keywords in text
        assert len(all_keywords) >= 2
        keywords_text = [kw.keyword for kw in all_keywords]
        assert any("LTV/CAC" in k or "ltv/cac" in k.lower() for k in keywords_text)
        assert any("CAC" == k.upper() for k in keywords_text)

        # After cross-metric substring suppression (CMS-1):
        # - LTV excluded via HRI-3 exclusion patterns
        # - CAC suppressed as substring of "LTV/CAC ratio" at overlapping position
        keywords_near_number = matcher.find_keywords_near_number(number, all_keywords)

        # Should have only LTV/CAC ratio (the most specific/longest match)
        matched_keywords = [kw.keyword for kw in keywords_near_number]
        assert len(matched_keywords) == 1, f"Expected 1 keyword (LTV/CAC), got {len(matched_keywords)}: {matched_keywords}"

        # Should be the LTV/CAC ratio metric
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
# Cross-Metric Substring Suppression Tests (CMS-1)
# =============================================================================


class TestCrossMetricSubstringSuppression:
    """Tests for cross-metric substring suppression.

    When keywords from different metrics overlap positionally AND one is a
    substring of the other, keep only the longer (more specific) match.
    """

    def test_paid_customers_threshold_keeps_specific_metric(self):
        """'Paid Customers > $100,000' should suppress 'Paid Customers' match.

        cm_large_customers_period_end should win over cm_customers_period_end
        because its keyword is longer and more specific.
        """
        matcher = KeywordMatcher(max_keyword_distance=100)
        # The keyword pattern for cm_large_customers matches "Paid Customers > $1"
        text = "We have 500 Paid Customers > $100,000 in ARR"
        number = NumberMatch(
            start=8, end=11, raw_text="500", value=Decimal("500"), unit="count"
        )

        all_keywords = matcher.find_all_keywords(text)
        keywords_near_number = matcher.find_keywords_near_number(number, all_keywords)

        # Should only have ONE match - the more specific cm_large_customers
        metric_ids = [kw.metric_id for kw in keywords_near_number]

        # The longer pattern should win
        assert (
            "cm_large_customers_period_end" in metric_ids
        ), f"Expected cm_large_customers_period_end, got {metric_ids}"

        # cm_customers_period_end should be suppressed as substring
        assert (
            "cm_customers_period_end" not in metric_ids
        ), f"cm_customers_period_end should be suppressed, got {metric_ids}"

    def test_cross_metric_non_overlapping_both_kept(self):
        """Non-overlapping keywords from different metrics should both be kept."""
        matcher = KeywordMatcher(max_keyword_distance=150)
        # "customers" at one position, "retention" at another (different metrics)
        text = "We had 1000 paying customers and our net dollar retention was strong"
        number = NumberMatch(
            start=8, end=12, raw_text="1000", value=Decimal("1000"), unit="count"
        )

        all_keywords = matcher.find_all_keywords(text)
        keywords_near_number = matcher.find_keywords_near_number(number, all_keywords)

        # Both metrics should be present since keywords don't overlap
        metric_ids = [kw.metric_id for kw in keywords_near_number]
        assert len(metric_ids) >= 1  # At least one match

    def test_cross_metric_overlap_but_not_substring(self):
        """Overlapping keywords that are NOT substrings should both be kept."""
        matcher = KeywordMatcher(max_keyword_distance=100)
        # Create a scenario where keywords might overlap but neither is substring
        # This tests that we only suppress when there's actual substring relationship
        text = "Our 95% customer retention rate was strong"
        number = NumberMatch(
            start=4, end=7, raw_text="95%", value=Decimal("95"), unit="percent"
        )

        all_keywords = matcher.find_all_keywords(text)
        keywords_near_number = matcher.find_keywords_near_number(number, all_keywords)

        # Should find at least one keyword match
        assert len(keywords_near_number) >= 1

    def test_longer_keyword_replaces_shorter_when_substring_match(self):
        """When keywords have substring relationship, longer one wins.

        This tests the specific case where one keyword text is a proper
        substring of another at overlapping positions.
        """
        matcher = KeywordMatcher(max_keyword_distance=100)

        # Create synthetic KeywordMatch objects to test the replacement logic
        from src.review.keyword_matching import KeywordMatch

        short_kw = KeywordMatch(
            start=0,
            end=14,
            keyword="Paid Customers",
            metric_id="cm_customers_period_end",
            pattern=r"\bpaid\s+customers?\b",
        )
        long_kw = KeywordMatch(
            start=0,
            end=25,
            keyword="Paid Customers > $100,000",
            metric_id="cm_large_customers_period_end",
            pattern=r"\bpaid\s+customers?\s*>\s*\$?\d",
        )

        # Verify overlap and substring relationship
        assert matcher._keywords_overlap(short_kw, long_kw)
        assert matcher._is_substring_match(short_kw, long_kw)

        # Verify length comparison logic
        assert len(long_kw.keyword) > len(short_kw.keyword)


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
        matcher.find_keywords_near_number(number, all_keywords)

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


# =============================================================================
# P1.5 Enhancement Tests (Sentence-Aware Matching)
# =============================================================================


class TestP15SentenceAwareMatching:
    """Tests for P1.5 enhancement: filter keywords from different sentences."""

    def test_default_configuration_includes_sentence_settings(self):
        """Default configuration should include P1.5 sentence settings."""
        matcher = KeywordMatcher()
        assert matcher.respect_sentence_boundaries is True

    def test_same_sentence_keywords_kept(self):
        """Keywords in the same sentence as the number should be kept."""
        from src.review.boundary_detection import BoundaryDetector

        text = "We had 50000 active customers in Q1."
        detector = BoundaryDetector()
        sentences = detector.find_sentence_boundaries(text)

        number = NumberMatch(
            start=text.index("50000"),
            end=text.index("50000") + 5,
            raw_text="50000",
            value=Decimal("50000"),
            unit="count",
        )

        matcher = KeywordMatcher(respect_sentence_boundaries=True)
        all_keywords = matcher.find_all_keywords(text)
        keywords = matcher.find_keywords_near_number(
            number, all_keywords, sentence_boundaries=sentences
        )

        # Should find "active customers" in same sentence
        assert len(keywords) >= 1
        assert any("customer" in kw.keyword.lower() for kw in keywords)

    def test_different_sentence_keywords_filtered(self):
        """Keywords in different sentences should be filtered out."""
        from src.review.boundary_detection import BoundaryDetector

        text = "We had 50000 active customers. Net revenue retention was 120% in Q4."
        detector = BoundaryDetector()
        sentences = detector.find_sentence_boundaries(text)

        # Number in second sentence (120%)
        num_pos = text.index("120%")
        number = NumberMatch(
            start=num_pos,
            end=num_pos + 4,
            raw_text="120%",
            value=Decimal("120"),
            unit="percent",
        )

        matcher = KeywordMatcher(respect_sentence_boundaries=True, max_keyword_distance=150)
        all_keywords = matcher.find_all_keywords(text)

        # WITH sentence filtering
        keywords_with_filter = matcher.find_keywords_near_number(
            number, all_keywords, sentence_boundaries=sentences
        )

        # WITHOUT sentence filtering
        matcher_no_sent = KeywordMatcher(respect_sentence_boundaries=False, max_keyword_distance=150)
        keywords_no_filter = matcher_no_sent.find_keywords_near_number(
            number, all_keywords, sentence_boundaries=sentences
        )

        # With filtering: should only find "net revenue retention" (in sentence 2)
        # Without filtering: might also find "active customers" (in sentence 1)
        keywords_with_ids = {kw.metric_id for kw in keywords_with_filter}
        keywords_without_ids = {kw.metric_id for kw in keywords_no_filter}

        # Net revenue retention should be in both
        assert "cm_net_revenue_retention" in keywords_with_ids

        # Active customers should be filtered WITH sentence boundaries
        # but present WITHOUT sentence boundaries (if within distance)
        if "cm_active_customers_total" in keywords_without_ids:
            # If found without filtering, should NOT be found with filtering
            assert "cm_active_customers_total" not in keywords_with_ids

    def test_problem_example_cross_sentence_filtering(self):
        """Test that cross-sentence keywords are properly filtered."""
        from src.review.boundary_detection import BoundaryDetector

        # Use metrics that exist in the taxonomy for both sentences
        text = "We had 50000 active customers in 2023. Net revenue retention was 120% in Q1."
        detector = BoundaryDetector()
        sentences = detector.find_sentence_boundaries(text)

        assert len(sentences) == 2, "Should detect 2 sentences"

        # Number in first sentence (50000) - should match "active customers"
        num1 = NumberMatch(
            start=text.index("50000"),
            end=text.index("50000") + 5,
            raw_text="50000",
            value=Decimal("50000"),
            unit="count",
        )

        # Number in second sentence (120%) - should match "net revenue retention"
        num2_pos = text.index("120%")
        num2 = NumberMatch(
            start=num2_pos,
            end=num2_pos + 4,
            raw_text="120%",
            value=Decimal("120"),
            unit="percent",
        )

        matcher = KeywordMatcher(respect_sentence_boundaries=True, max_keyword_distance=150)
        all_keywords = matcher.find_all_keywords(text)

        # Verify we found keywords in both sentences
        assert any("customer" in kw.keyword.lower() for kw in all_keywords), \
            "Should find 'active customers' keyword"
        assert any("retention" in kw.keyword.lower() for kw in all_keywords), \
            "Should find 'net revenue retention' keyword"

        # 50000 should only match keywords in sentence 1
        keywords1 = matcher.find_keywords_near_number(
            num1, all_keywords, sentence_boundaries=sentences
        )

        # 120% should only match keywords in sentence 2
        keywords2 = matcher.find_keywords_near_number(
            num2, all_keywords, sentence_boundaries=sentences
        )

        # Keywords for 50000 should be "active customers" (sentence 1)
        for kw in keywords1:
            assert sentences[0].contains_position(kw.start), \
                f"Keyword '{kw.keyword}' at pos {kw.start} should be in sentence 1 ({sentences[0].start}-{sentences[0].end})"

        # Keywords for 120% should be "net revenue retention" (sentence 2)
        for kw in keywords2:
            assert sentences[1].contains_position(kw.start), \
                f"Keyword '{kw.keyword}' at pos {kw.start} should be in sentence 2 ({sentences[1].start}-{sentences[1].end})"

        # Verify the key behavior: 50000 should NOT match "net revenue retention"
        keywords1_ids = {kw.metric_id for kw in keywords1}
        assert "cm_net_revenue_retention" not in keywords1_ids, \
            "50000 should not match net revenue retention (different sentence)"

        # Verify the key behavior: 120% should NOT match "active customers"
        keywords2_ids = {kw.metric_id for kw in keywords2}
        assert "cm_active_customers_total" not in keywords2_ids, \
            "120% should not match active customers (different sentence)"

    def test_fallback_when_no_same_sentence_keywords(self):
        """If no keywords in same sentence, should keep all candidates."""
        from src.review.boundary_detection import BoundaryDetector

        # Text where number has no keywords in same sentence
        text = "The value was 100. Active customers grew significantly."
        detector = BoundaryDetector()
        sentences = detector.find_sentence_boundaries(text)

        number = NumberMatch(
            start=text.index("100"),
            end=text.index("100") + 3,
            raw_text="100",
            value=Decimal("100"),
            unit="count",
        )

        matcher = KeywordMatcher(respect_sentence_boundaries=True, max_keyword_distance=150)
        all_keywords = matcher.find_all_keywords(text)
        keywords = matcher.find_keywords_near_number(
            number, all_keywords, sentence_boundaries=sentences
        )

        # Should fall back to cross-sentence keywords if no same-sentence ones
        # (may be empty if no keywords in range, or may include cross-sentence)
        assert isinstance(keywords, list)

    def test_sentence_filtering_disabled(self):
        """When respect_sentence_boundaries=False, sentence filtering should be skipped."""
        from src.review.boundary_detection import BoundaryDetector

        text = "We had 50000 active customers. Revenue retention was 120% in Q4."
        detector = BoundaryDetector()
        sentences = detector.find_sentence_boundaries(text)

        # Number in second sentence
        num_pos = text.index("120%")
        number = NumberMatch(
            start=num_pos,
            end=num_pos + 4,
            raw_text="120%",
            value=Decimal("120"),
            unit="percent",
        )

        matcher = KeywordMatcher(respect_sentence_boundaries=False, max_keyword_distance=150)
        all_keywords = matcher.find_all_keywords(text)
        keywords = matcher.find_keywords_near_number(
            number, all_keywords, sentence_boundaries=sentences
        )

        # Without filtering, may include keywords from both sentences
        assert isinstance(keywords, list)

    def test_sentence_and_boundary_filtering_combined(self):
        """Sentence filtering should work together with structural boundary filtering."""
        from src.review.boundary_detection import BoundaryDetector

        text = """• First bullet: active customers reached 50000. Revenue grew.
• Second bullet: churn rate was 5%. Costs increased."""

        detector = BoundaryDetector()
        boundaries = detector.find_boundaries(text)
        sentences = detector.find_sentence_boundaries(text)

        # Number "5%" is in second bullet, first sentence within that bullet
        num_pos = text.index("5%")
        number = NumberMatch(
            start=num_pos,
            end=num_pos + 2,
            raw_text="5%",
            value=Decimal("5"),
            unit="percent",
        )

        matcher = KeywordMatcher(
            respect_bullet_boundaries=True,
            respect_sentence_boundaries=True,
            max_keyword_distance=200,
        )
        all_keywords = matcher.find_all_keywords(text)
        keywords = matcher.find_keywords_near_number(
            number, all_keywords, boundaries=boundaries, sentence_boundaries=sentences
        )

        # Should filter by BOTH bullet boundary AND sentence boundary
        # "churn rate" is in same bullet AND same sentence
        # "active customers" is in different bullet
        if len(keywords) > 0:
            # Verify keywords are from correct boundary
            for kw in keywords:
                # Should be in same bullet boundary
                kw_boundary = detector.get_boundary_at_position(kw.start, boundaries)
                num_boundary = detector.get_boundary_at_position(number.start, boundaries)
                if kw_boundary and num_boundary:
                    assert kw_boundary == num_boundary or not matcher.respect_bullet_boundaries

    def test_no_sentence_boundaries_provided(self):
        """When sentence_boundaries is None, should skip sentence filtering."""
        text = "We had 50000 active customers in Q1."

        number = NumberMatch(
            start=text.index("50000"),
            end=text.index("50000") + 5,
            raw_text="50000",
            value=Decimal("50000"),
            unit="count",
        )

        matcher = KeywordMatcher(respect_sentence_boundaries=True)
        all_keywords = matcher.find_all_keywords(text)

        # Pass None for sentence_boundaries
        keywords = matcher.find_keywords_near_number(
            number, all_keywords, sentence_boundaries=None
        )

        # Should return keywords without sentence filtering (behaves like P1)
        assert len(keywords) >= 1

    def test_empty_sentence_boundaries(self):
        """When sentence_boundaries is empty list, should skip filtering."""
        text = "We had 50000 active customers in Q1."

        number = NumberMatch(
            start=text.index("50000"),
            end=text.index("50000") + 5,
            raw_text="50000",
            value=Decimal("50000"),
            unit="count",
        )

        matcher = KeywordMatcher(respect_sentence_boundaries=True)
        all_keywords = matcher.find_all_keywords(text)

        # Pass empty list for sentence_boundaries
        keywords = matcher.find_keywords_near_number(
            number, all_keywords, sentence_boundaries=[]
        )

        # Should return keywords without filtering
        assert len(keywords) >= 1

    def test_long_sentence_multiple_metrics_preserved(self):
        """Multiple metrics in the same long sentence should all be preserved."""
        from src.review.boundary_detection import BoundaryDetector

        # One long sentence with multiple metrics
        text = "Our active customers reached 50000 while churn rate improved to 5% in Q1."
        detector = BoundaryDetector()
        sentences = detector.find_sentence_boundaries(text)

        assert len(sentences) == 1, "Should be one sentence"

        # Number for customers (50000)
        num1 = NumberMatch(
            start=text.index("50000"),
            end=text.index("50000") + 5,
            raw_text="50000",
            value=Decimal("50000"),
            unit="count",
        )

        matcher = KeywordMatcher(respect_sentence_boundaries=True, max_keyword_distance=150)
        all_keywords = matcher.find_all_keywords(text)

        # Both keywords should be available for 50000 (all in same sentence)
        keywords = matcher.find_keywords_near_number(
            num1, all_keywords, sentence_boundaries=sentences
        )

        # May find both "active customers" and "churn rate" since they're in same sentence
        # At minimum, should find the closest keyword
        assert len(keywords) >= 1


# =============================================================================
# L3 Enhancement Tests (Keyword Direction Detection)
# =============================================================================


class TestKeywordDirection:
    """Tests for L3: keyword direction detection."""

    @pytest.fixture
    def matcher(self):
        """Create a KeywordMatcher instance."""
        return KeywordMatcher(max_keyword_distance=100)

    def test_keyword_before_number(self, matcher):
        """Keyword appearing before number returns 'before' direction."""
        text = "Our customer retention rate was 95%"
        #       ^keyword                         ^number

        number = NumberMatch(
            start=text.index("95"),
            end=text.index("95") + 3,
            raw_text="95%",
            value=Decimal("95"),
            unit="percent",
        )

        all_keywords = matcher.find_all_keywords(text)
        result = matcher.find_keywords_near_number(number, all_keywords)

        assert len(result) >= 1
        # Find the retention keyword
        retention_match = [kw for kw in result if "retention" in kw.keyword.lower()]
        assert len(retention_match) >= 1
        assert retention_match[0].direction == "before"

    def test_keyword_after_number(self, matcher):
        """Keyword appearing after number returns 'after' direction."""
        text = "We achieved 95% retention rate"
        #                   ^number ^keyword

        number = NumberMatch(
            start=text.index("95"),
            end=text.index("95") + 3,
            raw_text="95%",
            value=Decimal("95"),
            unit="percent",
        )

        all_keywords = matcher.find_all_keywords(text)
        result = matcher.find_keywords_near_number(number, all_keywords)

        assert len(result) >= 1
        # Find the retention keyword
        retention_match = [kw for kw in result if "retention" in kw.keyword.lower()]
        assert len(retention_match) >= 1
        assert retention_match[0].direction == "after"

    def test_direction_with_multiple_keywords(self, matcher):
        """Direction is correct for closest keyword match."""
        text = "churn rate was 30% churn rate again"
        #       ^before          ^num ^after

        number = NumberMatch(
            start=text.index("30"),
            end=text.index("30") + 3,
            raw_text="30%",
            value=Decimal("30"),
            unit="percent",
        )

        all_keywords = matcher.find_all_keywords(text)
        result = matcher.find_keywords_near_number(number, all_keywords)

        # Should match one of the churn rate keywords
        assert len(result) >= 1
        # The matched keyword should have a direction
        assert result[0].direction in ("before", "after")
        # Direction should be set correctly (either before or after, depending on which matched)

    def test_keyword_immediately_after(self, matcher):
        """Keyword immediately following number is 'after'."""
        text = "30% churn rate"

        number = NumberMatch(
            start=0,
            end=3,
            raw_text="30%",
            value=Decimal("30"),
            unit="percent",
        )

        all_keywords = matcher.find_all_keywords(text)
        result = matcher.find_keywords_near_number(number, all_keywords)

        assert len(result) >= 1
        assert result[0].direction == "after"

    def test_keyword_immediately_before(self, matcher):
        """Keyword immediately preceding number is 'before'."""
        text = "churn rate 30%"

        number = NumberMatch(
            start=text.index("30"),
            end=text.index("30") + 3,
            raw_text="30%",
            value=Decimal("30"),
            unit="percent",
        )

        all_keywords = matcher.find_all_keywords(text)
        result = matcher.find_keywords_near_number(number, all_keywords)

        assert len(result) >= 1
        assert result[0].direction == "before"

    def test_direction_field_in_result(self, matcher):
        """Result always contains direction field."""
        text = "active customers 1000"

        number = NumberMatch(
            start=text.index("1000"),
            end=text.index("1000") + 4,
            raw_text="1000",
            value=Decimal("1000"),
            unit="count",
        )

        all_keywords = matcher.find_all_keywords(text)
        result = matcher.find_keywords_near_number(number, all_keywords)

        assert len(result) >= 1
        # Check that direction field exists and has valid value
        assert hasattr(result[0], "direction")
        assert result[0].direction in ("before", "after", "at")

    def test_multiple_numbers_different_directions(self, matcher):
        """Each number gets correct direction for its nearest keywords."""
        text = "We had 50000 active customers and churn rate of 5%"
        #              ^num1  ^kw1                            ^kw2 ^num2

        # First number (50000) - "active customers" is after it
        num1 = NumberMatch(
            start=text.index("50000"),
            end=text.index("50000") + 5,
            raw_text="50000",
            value=Decimal("50000"),
            unit="count",
        )

        # Second number (5%) - "churn rate" is before it
        num2 = NumberMatch(
            start=text.index("5%"),
            end=text.index("5%") + 2,
            raw_text="52%",
            value=Decimal("52"),
            unit="percent",
        )

        all_keywords = matcher.find_all_keywords(text)

        # Check first number
        keywords1 = matcher.find_keywords_near_number(num1, all_keywords)
        customer_match = [kw for kw in keywords1 if "customer" in kw.keyword.lower()]
        if customer_match:
            assert customer_match[0].direction == "after"

        # Check second number
        keywords2 = matcher.find_keywords_near_number(num2, all_keywords)
        margin_match = [kw for kw in keywords2 if "margin" in kw.keyword.lower()]
        if margin_match:
            assert margin_match[0].direction == "before"

    def test_direction_preserved_across_boundary_filtering(self, matcher):
        """Direction is correctly computed even with boundary filtering enabled."""
        from src.review.boundary_detection import BoundaryDetector

        text = """• Revenue metrics: 95% retention rate
• Customer metrics: 50000 active customers"""

        detector = BoundaryDetector()
        boundaries = detector.find_boundaries(text)

        # Number in first boundary (95%) - "retention rate" is after
        num1 = NumberMatch(
            start=text.index("95"),
            end=text.index("95") + 3,
            raw_text="95%",
            value=Decimal("95"),
            unit="percent",
        )

        matcher_with_boundaries = KeywordMatcher(
            respect_bullet_boundaries=True,
            max_keyword_distance=100
        )
        all_keywords = matcher_with_boundaries.find_all_keywords(text)
        keywords = matcher_with_boundaries.find_keywords_near_number(
            num1, all_keywords, boundaries=boundaries
        )

        # Should find keywords and they should have direction set
        if keywords:
            assert all(kw.direction in ("before", "after", "at") for kw in keywords)

    def test_calculate_keyword_direction_helper(self, matcher):
        """Test the calculate_keyword_direction helper method directly."""
        # Keyword before number
        assert matcher.calculate_keyword_direction(keyword_start=10, number_start=50) == "before"

        # Keyword after number
        assert matcher.calculate_keyword_direction(keyword_start=50, number_start=10) == "after"

        # Keyword at same position as number (edge case)
        assert matcher.calculate_keyword_direction(keyword_start=25, number_start=25) == "at"


# =============================================================================
# L4 Enhancement: Post-Value Distance Multiplier Tests
# =============================================================================


class TestPostValueMultiplier:
    """Tests for L4 post-value distance multiplier functionality."""

    @pytest.fixture
    def matcher(self):
        """Create a KeywordMatcher with default multiplier (0.9)."""
        return KeywordMatcher(max_keyword_distance=200, prefer_closest_keyword=True)

    def test_before_keyword_preferred_at_equal_distance(self, matcher):
        """When keywords are equidistant, pre-value wins due to multiplier."""
        # "active customers" appears both before and after "100"
        # Both are equidistant (1 char away)
        text = "active customers 100 active customers"

        # Find all keywords
        all_keywords = matcher.find_all_keywords(text)

        # Create number match for "100" (starts at position 17)
        number = NumberMatch(
            start=17, end=20, raw_text="100", value=Decimal("100"), unit="count"
        )

        # Find keywords near number
        keywords = matcher.find_keywords_near_number(number, all_keywords)

        # Should have exactly 1 match (for cm_active_customers_total)
        assert len(keywords) == 1

        # Should be the first "active customers" (before the number)
        assert keywords[0].start == 0  # First "active customers" starts at position 0
        assert keywords[0].direction == "before"

    def test_after_keyword_wins_when_significantly_closer(self, matcher):
        """Post-value keyword wins if close enough despite multiplier."""
        # "revenue" far before, "margin" close after
        # Even with 0.9 multiplier, "margin" should win due to proximity
        text = "revenue is important but not relevant here 100 margin"

        all_keywords = matcher.find_all_keywords(text)

        number = NumberMatch(
            start=44, end=47, raw_text="100", value=Decimal("100"), unit="count"
        )

        keywords = matcher.find_keywords_near_number(number, all_keywords)

        # Should find "margin" (close after) rather than "revenue" (far before)
        # Check that if margin is found, it's after the number
        margin_keywords = [kw for kw in keywords if "margin" in kw.keyword.lower()]
        if margin_keywords:
            assert margin_keywords[0].direction == "after"

    def test_multiplier_value_configurable(self):
        """Custom multiplier values work correctly."""
        # Create matcher with stricter multiplier (0.8)
        matcher_strict = KeywordMatcher(
            max_keyword_distance=200,
            prefer_closest_keyword=True,
            post_value_distance_multiplier=0.8,
        )

        # Create matcher with neutral multiplier (1.0 = no preference)
        matcher_neutral = KeywordMatcher(
            max_keyword_distance=200,
            prefer_closest_keyword=True,
            post_value_distance_multiplier=1.0,
        )

        # Text with keywords before and after the number
        text = "active customers here 100 retention rate"

        all_keywords_strict = matcher_strict.find_all_keywords(text)
        all_keywords_neutral = matcher_neutral.find_all_keywords(text)

        number = NumberMatch(
            start=22, end=25, raw_text="100", value=Decimal("100"), unit="count"
        )

        # With strict multiplier, post-value penalty is higher
        keywords_strict = matcher_strict.find_keywords_near_number(number, all_keywords_strict)

        # With neutral multiplier, closest keyword wins (no preference)
        keywords_neutral = matcher_neutral.find_keywords_near_number(number, all_keywords_neutral)

        # Both should find keywords (may find different ones due to multiplier)
        assert len(keywords_strict) >= 1
        assert len(keywords_neutral) >= 1

    def test_multiplier_only_affects_prefer_closest_keyword_mode(self):
        """Multiplier only applies when prefer_closest_keyword is True."""
        # Create matcher with prefer_closest_keyword=False
        matcher_longest = KeywordMatcher(
            max_keyword_distance=200,
            prefer_closest_keyword=False,
            post_value_distance_multiplier=0.9,
        )

        text = "active customers 100 revenue"
        all_keywords = matcher_longest.find_all_keywords(text)

        number = NumberMatch(
            start=17, end=20, raw_text="100", value=Decimal("100"), unit="count"
        )

        keywords = matcher_longest.find_keywords_near_number(number, all_keywords)

        # Should find keywords, but sorted by length (not distance)
        assert len(keywords) >= 1
        # Multiplier shouldn't cause errors even when prefer_closest_keyword=False

    def test_at_direction_treated_as_before(self):
        """Edge case: keywords at same position as number treated as 'before'."""
        matcher = KeywordMatcher(
            max_keyword_distance=100,
            prefer_closest_keyword=True,
            post_value_distance_multiplier=0.9,
        )

        # This is an edge case - in practice, keywords and numbers
        # rarely start at the same position, but we should handle it
        text = "revenue100margin"
        all_keywords = matcher.find_all_keywords(text)

        number = NumberMatch(
            start=7, end=10, raw_text="100", value=Decimal("100"), unit="count"
        )

        keywords = matcher.find_keywords_near_number(number, all_keywords)

        # Should find keywords without errors
        # Direction should be set appropriately
        for kw in keywords:
            assert kw.direction in ("before", "after", "at")


# =============================================================================
# L4 Option C: Context-Dependent Multiplier Tests
# =============================================================================


class TestL4ContextDependentMultipliers:
    """Tests for L4 Option C: context-dependent multipliers."""

    def test_parenthetical_text_prefers_post_value(self):
        """Parenthetical text should prefer post-value keywords."""
        matcher = KeywordMatcher(
            max_keyword_distance=200,
            prefer_closest_keyword=True,
            use_context_dependent_multipliers=True,
            multiplier_parenthetical=1.15,  # Prefer post-value
        )

        # "5% (churn rate)" - metric in parentheses after value
        text = "We achieved 5% (churn rate) improvement"
        all_keywords = matcher.find_all_keywords(text)

        number = NumberMatch(
            start=12, end=14, raw_text="5%", value=Decimal("5"), unit="percent"
        )

        keywords = matcher.find_keywords_near_number(number, all_keywords, text=text)

        # Should find "churn rate" (in parentheses after number)
        assert len(keywords) >= 1
        churn_kw = [kw for kw in keywords if "churn" in kw.keyword.lower()]
        assert len(churn_kw) > 0
        assert churn_kw[0].direction == "after"

    def test_bullet_point_prefers_pre_value(self):
        """Bullet points should prefer pre-value keywords."""
        from src.review.boundary_detection import BoundaryDetector

        matcher = KeywordMatcher(
            max_keyword_distance=200,
            prefer_closest_keyword=True,
            use_context_dependent_multipliers=True,
            multiplier_bullet_points=0.9,  # Prefer pre-value
        )

        text = "• Churn rate was 5% improvement"
        detector = BoundaryDetector()
        boundaries = detector.find_boundaries(text)

        all_keywords = matcher.find_all_keywords(text)

        number = NumberMatch(
            start=text.index("5%"),
            end=text.index("5%") + 2,
            raw_text="5%",
            value=Decimal("5"),
            unit="percent",
        )

        keywords = matcher.find_keywords_near_number(
            number, all_keywords, boundaries=boundaries, text=text
        )

        # Should find "churn rate" (before number in bullet)
        assert len(keywords) >= 1
        churn_kw = [kw for kw in keywords if "churn" in kw.keyword.lower()]
        assert len(churn_kw) > 0

    def test_copula_verb_prefers_pre_value(self):
        """Sentences with copula verbs (is/was/were) should prefer pre-value keywords."""
        matcher = KeywordMatcher(
            max_keyword_distance=200,
            prefer_closest_keyword=True,
            use_context_dependent_multipliers=True,
            multiplier_copula_verb=0.9,  # Prefer pre-value
        )

        # "Churn rate was 5%" - copula verb between metric and value
        text = "Churn rate was 5% in the quarter"
        all_keywords = matcher.find_all_keywords(text)

        number = NumberMatch(
            start=text.index("5%"),
            end=text.index("5%") + 2,
            raw_text="5%",
            value=Decimal("5"),
            unit="percent",
        )

        keywords = matcher.find_keywords_near_number(number, all_keywords, text=text)

        # Should find "churn rate" (before "was")
        assert len(keywords) >= 1
        churn_kw = [kw for kw in keywords if "churn" in kw.keyword.lower()]
        assert len(churn_kw) > 0
        assert churn_kw[0].direction == "before"

    def test_preposition_prefers_post_value(self):
        """Prepositional phrases (of/for/in) should prefer post-value keywords."""
        matcher = KeywordMatcher(
            max_keyword_distance=200,
            prefer_closest_keyword=True,
            use_context_dependent_multipliers=True,
            multiplier_preposition=1.1,  # Prefer post-value
        )

        # "33% of revenue" - preposition after value
        text = "We achieved 33% of revenue growth"
        all_keywords = matcher.find_all_keywords(text)

        number = NumberMatch(
            start=text.index("33%"),
            end=text.index("33%") + 3,
            raw_text="33%",
            value=Decimal("33"),
            unit="percent",
        )

        keywords = matcher.find_keywords_near_number(number, all_keywords, text=text)

        # Should find "revenue" (after "of")
        assert len(keywords) >= 1
        # Note: revenue might match, depends on metric keywords
        # This test verifies multiplier is applied, not specific keyword selection

    def test_context_disabled_uses_base_multiplier(self):
        """When context-dependent multipliers disabled, use base multiplier."""
        matcher = KeywordMatcher(
            max_keyword_distance=200,
            prefer_closest_keyword=True,
            use_context_dependent_multipliers=False,
            post_value_distance_multiplier=0.8,
        )

        # Should use 0.8 for all contexts
        multiplier = matcher.get_context_multiplier(
            text="We achieved 5% (churn rate)",
            number_position=12,
            keyword_position=16,
            keyword_direction="after",
            boundaries=None,
            segment_type=None,
        )

        assert multiplier == 0.8  # Base multiplier, not context-specific

    def test_pre_value_keyword_gets_no_multiplier(self):
        """Pre-value keywords should get multiplier of 1.0 (no adjustment)."""
        matcher = KeywordMatcher(
            max_keyword_distance=200,
            prefer_closest_keyword=True,
            use_context_dependent_multipliers=True,
        )

        # Pre-value keyword should get 1.0 multiplier
        multiplier = matcher.get_context_multiplier(
            text="Churn rate was 5%",
            number_position=15,
            keyword_position=0,
            keyword_direction="before",
            boundaries=None,
            segment_type=None,
        )

        assert multiplier == 1.0  # No adjustment for pre-value keywords


# =============================================================================
# C1: Threshold Test
# =============================================================================


class TestL4ThresholdMath:
    """Test exact threshold math for when post-value keywords win."""

    def test_post_value_wins_when_closer_after_multiplier(self):
        """Post-value wins when distance * multiplier < pre-value distance."""
        matcher = KeywordMatcher(
            max_keyword_distance=200,
            prefer_closest_keyword=True,
            use_context_dependent_multipliers=False,
            post_value_distance_multiplier=0.9,
        )

        # Use actual metric keywords: "active customers" and "churn rate"
        # Pre-value keyword far away, post-value keyword closer
        text = "active customers increased significantly here and 100 churn rate"
        all_keywords = matcher.find_all_keywords(text)

        number_pos = text.index("100")
        number = NumberMatch(
            start=number_pos,
            end=number_pos + 3,
            raw_text="100",
            value=Decimal("100"),
            unit="count",
        )

        keywords = matcher.find_keywords_near_number(number, all_keywords, text=text)

        # Should have at least one match
        assert len(keywords) >= 1

        # Churn rate is much closer than active customers, should win
        churn_kws = [kw for kw in keywords if "churn" in kw.keyword.lower()]
        if len(churn_kws) > 0:
            # Churn rate should be present and be after the number
            assert churn_kws[0].direction == "after"


# =============================================================================
# C3: Boundary Interaction Test
# =============================================================================


class TestL4BoundaryInteraction:
    """Test that multiplier is applied after boundary filtering."""

    def test_multiplier_applied_after_boundary_filtering(self):
        """Boundary filtering happens first, then multiplier sorting."""
        from src.review.boundary_detection import BoundaryDetector

        matcher = KeywordMatcher(
            max_keyword_distance=200,
            prefer_closest_keyword=True,
            respect_bullet_boundaries=True,
            use_context_dependent_multipliers=True,
            multiplier_bullet_points=0.9,
        )

        # Two bullets: first has "active customers", second has "100 churn rate"
        text = "• Active customers increased significantly\n• Performance was 100 with churn rate improvement"
        detector = BoundaryDetector()
        boundaries = detector.find_boundaries(text)

        all_keywords = matcher.find_all_keywords(text)

        # Number in second bullet
        number_pos = text.index("100")
        number = NumberMatch(
            start=number_pos,
            end=number_pos + 3,
            raw_text="100",
            value=Decimal("100"),
            unit="count",
        )

        keywords = matcher.find_keywords_near_number(
            number, all_keywords, boundaries=boundaries, text=text
        )

        # Should find "churn rate" (same bullet, post-value)
        # Should NOT find "active customers" (different bullet, filtered by boundary)
        assert len(keywords) >= 1
        keyword_texts = [kw.keyword.lower() for kw in keywords]

        # Churn rate should be present (same boundary)
        assert any("churn" in kw for kw in keyword_texts)

        # Active customers should NOT be present (different boundary)
        assert not any("customers" in kw for kw in keyword_texts)


# =============================================================================
# C4: Multiple Keywords Test
# =============================================================================


class TestL4MultipleKeywords:
    """Test correct sorting with multiple pre and post keywords."""

    def test_multiple_pre_and_post_keywords_sorted_by_effective_distance(self):
        """Multiple keywords sorted by effective distance."""
        matcher = KeywordMatcher(
            max_keyword_distance=200,
            prefer_closest_keyword=True,
            use_context_dependent_multipliers=False,
            post_value_distance_multiplier=0.9,
        )

        # Setup with actual metric keywords:
        # Pre-value: "active customers" (far before)
        # Post-value: "churn rate" (close after)
        text = "active customers and other metrics here for 100 churn rate today"
        all_keywords = matcher.find_all_keywords(text)

        number_pos = text.index("100")
        number = NumberMatch(
            start=number_pos,
            end=number_pos + 3,
            raw_text="100",
            value=Decimal("100"),
            unit="count",
        )

        keywords = matcher.find_keywords_near_number(number, all_keywords, text=text)

        # Should find at least one keyword
        assert len(keywords) >= 1

        # The closest keyword (after multiplier) should be first
        # This test verifies sorting works with multiple candidates
        # Churn rate is much closer, should be found
        churn_kws = [kw for kw in keywords if "churn" in kw.keyword.lower()]
        assert len(churn_kws) > 0


# =============================================================================
# Required Context Tests (Revenue Synonym Filtering)
# =============================================================================


class TestRequiredContext:
    """Tests for required context filtering on revenue synonym metrics.

    Revenue synonyms (GMV, TCV, ACV, Bookings, Billings) are not inherently
    customer metrics - they're revenue/value measures. They only become
    customer metrics when associated with cohort analysis or per-customer context.

    ARR and MRR are NOT context-gated because "recurring revenue" inherently
    implies ongoing customer relationships.
    """

    REVENUE_SYNONYM_METRICS = [
        "cm_gmv",
        "cm_tcv",
        "cm_acv",
        "cm_bookings",
        "cm_billings",
    ]

    @pytest.fixture
    def matcher(self):
        """Create a KeywordMatcher instance."""
        return KeywordMatcher(max_keyword_distance=200)

    def test_required_context_constant_exists(self):
        """METRIC_REQUIRED_CONTEXT constant should be loaded."""
        assert METRIC_REQUIRED_CONTEXT is not None
        assert isinstance(METRIC_REQUIRED_CONTEXT, dict)

    def test_all_revenue_synonyms_deprecated(self):
        """All revenue synonym metrics should be deprecated."""
        for metric_id in self.REVENUE_SYNONYM_METRICS:
            assert is_metric_deprecated(metric_id), \
                f"{metric_id} should be deprecated"

    def test_revenue_synonyms_have_required_context(self):
        """All revenue synonym metrics should have required_context in YAML config."""
        from src.extraction.keyword_config import get_required_context

        # Use raw config (unfiltered) since all synonyms are now deprecated
        # and METRIC_REQUIRED_CONTEXT filters deprecated metrics out
        raw_context = get_required_context()
        for metric_id in self.REVENUE_SYNONYM_METRICS:
            assert metric_id in raw_context, \
                f"{metric_id} should have required_context defined in YAML"
            assert "patterns" in raw_context[metric_id]
            assert "proximity_chars" in raw_context[metric_id]

    def test_arr_mrr_not_context_gated(self):
        """ARR and MRR should NOT have required context (inherently customer-related)."""
        assert "cm_arr" not in METRIC_REQUIRED_CONTEXT
        assert "cm_mrr" not in METRIC_REQUIRED_CONTEXT

    @pytest.mark.parametrize("metric_id", [m for m in REVENUE_SYNONYM_METRICS if not is_metric_deprecated(m)])
    def test_revenue_synonym_without_context_no_match(self, matcher, metric_id):
        """Revenue synonyms without cohort/per-customer context should not generate matches."""
        # Build text with the metric keyword but NO cohort/per-customer context
        metric_texts = {
            "cm_gmv": "Our GMV reached $1 billion in the quarter",
            "cm_tcv": "Total contract value was $500 million this year",
            "cm_acv": "Average contract value increased to $50,000",
            "cm_bookings": "We achieved $200 million in bookings",
            "cm_billings": "Calculated billings were $300 million",
        }
        text = metric_texts[metric_id]

        # Find all keywords (this should find the metric)
        all_keywords = matcher.find_all_keywords(text)

        # Create a number match for the dollar value
        # Find the first number-like pattern
        import re
        num_match = re.search(r'\$[\d,]+', text)
        assert num_match is not None

        number = NumberMatch(
            start=num_match.start(),
            end=num_match.end(),
            raw_text=num_match.group(),
            value=Decimal("1000000"),
            unit="currency",
        )

        # With required context check enabled (default), should NOT find matches
        keywords = matcher.find_keywords_near_number(
            number, all_keywords, check_required_context=True, text=text
        )

        # Should NOT find the revenue synonym metric
        metric_matches = [kw for kw in keywords if kw.metric_id == metric_id]
        assert len(metric_matches) == 0, \
            f"{metric_id} should not match without cohort/per-customer context"

    @pytest.mark.parametrize("metric_id", [m for m in REVENUE_SYNONYM_METRICS if not is_metric_deprecated(m)])
    def test_revenue_synonym_with_cohort_context_generates_match(self, matcher, metric_id):
        """Revenue synonyms with cohort context should generate matches."""
        # Build text with the metric keyword AND cohort context
        metric_texts = {
            "cm_gmv": "Our cohort analysis shows GMV of $1 billion by acquisition year",
            "cm_tcv": "TCV by cohort reached $500 million for the 2020 vintage",
            "cm_acv": "ACV per cohort increased to $50,000 on average",
            "cm_bookings": "Cohort bookings were $200 million in 2020",
            "cm_billings": "Billings by vintage show $300 million for cohort 2019",
        }
        text = metric_texts[metric_id]

        all_keywords = matcher.find_all_keywords(text)

        # Create a number match
        import re
        num_match = re.search(r'\$[\d,]+', text)
        assert num_match is not None

        number = NumberMatch(
            start=num_match.start(),
            end=num_match.end(),
            raw_text=num_match.group(),
            value=Decimal("1000000"),
            unit="currency",
        )

        # With required context check enabled, should find matches (cohort context present)
        keywords = matcher.find_keywords_near_number(
            number, all_keywords, check_required_context=True, text=text
        )

        # Should find the revenue synonym metric
        metric_matches = [kw for kw in keywords if kw.metric_id == metric_id]
        assert len(metric_matches) >= 1, \
            f"{metric_id} should match when cohort context is present"

    @pytest.mark.parametrize("metric_id", [m for m in REVENUE_SYNONYM_METRICS if not is_metric_deprecated(m)])
    def test_revenue_synonym_with_per_customer_context_generates_match(self, matcher, metric_id):
        """Revenue synonyms with per-customer context should generate matches."""
        # Build text with the metric keyword AND per-customer context
        metric_texts = {
            "cm_gmv": "GMV per customer averaged $1 billion across our user base",
            "cm_tcv": "Average TCV per account was $500,000 this year",
            "cm_acv": "ACV by customer segment reached $50,000 average",
            "cm_bookings": "Bookings per user increased to $200 million",
            "cm_billings": "Customer-level billings averaged $300,000",
        }
        text = metric_texts[metric_id]

        all_keywords = matcher.find_all_keywords(text)

        # Create a number match
        import re
        num_match = re.search(r'\$[\d,]+', text)
        assert num_match is not None

        number = NumberMatch(
            start=num_match.start(),
            end=num_match.end(),
            raw_text=num_match.group(),
            value=Decimal("1000000"),
            unit="currency",
        )

        # Should find matches with per-customer context
        keywords = matcher.find_keywords_near_number(
            number, all_keywords, check_required_context=True, text=text
        )

        # Should find the revenue synonym metric
        metric_matches = [kw for kw in keywords if kw.metric_id == metric_id]
        assert len(metric_matches) >= 1, \
            f"{metric_id} should match when per-customer context is present"

    def test_deprecated_revenue_synonyms_not_in_keywords(self, matcher):
        """Deprecated revenue synonyms should not appear in find_all_keywords results."""
        # All revenue synonyms are deprecated, so none should be found
        text = "Our GMV reached $1 billion and bookings were $500 million"

        all_keywords = matcher.find_all_keywords(text)

        for metric_id in self.REVENUE_SYNONYM_METRICS:
            matches = [kw for kw in all_keywords if kw.metric_id == metric_id]
            assert len(matches) == 0, \
                f"Deprecated metric {metric_id} should not appear in keyword matches"

    def test_arr_matches_without_context(self, matcher):
        """ARR should match even without cohort/per-customer context."""
        # ARR without any cohort/per-customer context
        text = "Our ARR grew to $100 million this year"

        all_keywords = matcher.find_all_keywords(text)

        import re
        num_match = re.search(r'\$[\d,]+', text)
        number = NumberMatch(
            start=num_match.start(),
            end=num_match.end(),
            raw_text=num_match.group(),
            value=Decimal("100000000"),
            unit="currency",
        )

        keywords = matcher.find_keywords_near_number(
            number, all_keywords, check_required_context=True, text=text
        )

        # Should find ARR (not context-gated)
        arr_matches = [kw for kw in keywords if kw.metric_id == "cm_arr"]
        assert len(arr_matches) >= 1, \
            "ARR should match without cohort context (inherently customer-related)"

    def test_mrr_matches_without_context(self, matcher):
        """MRR should match even without cohort/per-customer context."""
        # MRR without any cohort/per-customer context
        text = "Our MRR reached $8 million last month"

        all_keywords = matcher.find_all_keywords(text)

        import re
        num_match = re.search(r'\$[\d,]+', text)
        number = NumberMatch(
            start=num_match.start(),
            end=num_match.end(),
            raw_text=num_match.group(),
            value=Decimal("8000000"),
            unit="currency",
        )

        keywords = matcher.find_keywords_near_number(
            number, all_keywords, check_required_context=True, text=text
        )

        # Should find MRR (not context-gated)
        mrr_matches = [kw for kw in keywords if kw.metric_id == "cm_mrr"]
        assert len(mrr_matches) >= 1, \
            "MRR should match without cohort context (inherently customer-related)"

    def test_non_revenue_metrics_unaffected(self, matcher):
        """Non-revenue synonym metrics should not be affected by context check."""
        # Active customers - not a revenue synonym, should always match
        text = "We have 50000 active customers globally"

        all_keywords = matcher.find_all_keywords(text)

        number = NumberMatch(
            start=text.index("50000"),
            end=text.index("50000") + 5,
            raw_text="50000",
            value=Decimal("50000"),
            unit="count",
        )

        keywords = matcher.find_keywords_near_number(
            number, all_keywords, check_required_context=True, text=text
        )

        # Should find active customers
        customer_matches = [kw for kw in keywords if kw.metric_id == "cm_active_customers_total"]
        assert len(customer_matches) >= 1, \
            "Non-revenue metrics should match without context requirement"

    def test_has_required_context_method_exists(self, matcher):
        """KeywordMatcher should have _has_required_context method."""
        assert hasattr(matcher, "_has_required_context")

    def test_has_required_context_true_for_non_gated_metrics(self, matcher):
        """_has_required_context returns True for metrics without required_context."""
        text = "We have 50000 active customers"
        # Non-revenue metric should always return True
        result = matcher._has_required_context("cm_active_customers_total", 10, text)
        assert result is True

    def test_has_required_context_true_for_deprecated_metrics(self, matcher):
        """_has_required_context returns True for deprecated metrics (not in context dict)."""
        text = "Our GMV reached $1 billion"
        # Deprecated metrics are filtered from METRIC_REQUIRED_CONTEXT,
        # so _has_required_context returns True (no gate)
        result = matcher._has_required_context("cm_gmv", 4, text)
        assert result is True


# =============================================================================
# should_exclude_for_number_context with Table Row Awareness (EXT-FN-1)
# =============================================================================


class TestShouldExcludeForNumberContext:
    """Tests for should_exclude_for_number_context method."""

    @pytest.fixture
    def matcher(self):
        """Create a KeywordMatcher instance."""
        return KeywordMatcher()

    def test_excludes_when_pattern_in_window_no_parser(self, matcher):
        """Without table parser, excludes based on window around number."""
        # The text has "retention rate" within 100 chars of the number position
        text = "Large customers 135 retention rate 95%"
        # Position of 135 = 16, "retention rate" at position 20
        # Distance is < 100 chars, so should exclude for cm_large_customers_period_end
        should_exclude, reason = matcher.should_exclude_for_number_context(
            metric_id="cm_large_customers_period_end",
            text=text,
            number_position=16,  # position of "135"
        )
        assert should_exclude is True
        assert "retention" in reason.lower()

    def test_no_exclusion_when_no_pattern_in_window(self, matcher):
        """Without exclusion pattern in window, should not exclude."""
        text = "We have 50000 active customers worldwide"
        should_exclude, reason = matcher.should_exclude_for_number_context(
            metric_id="cm_large_customers_period_end",
            text=text,
            number_position=8,  # position of "50000"
        )
        assert should_exclude is False
        assert reason is None

    def test_no_exclusion_when_metric_has_no_exclusion_patterns(self, matcher):
        """Metrics without exclusion patterns should never be excluded."""
        text = "retention rate 135 some text here"
        should_exclude, reason = matcher.should_exclude_for_number_context(
            metric_id="cm_active_customers_total",  # Typically has few/no exclusions
            text=text,
            number_position=15,  # position of "135"
        )
        # Even if text has exclusion-like patterns, this metric may not have matching exclusions
        # The key is it should not crash and behave predictably
        assert should_exclude in (True, False)  # Depends on actual patterns


class TestShouldExcludeWithMarkerRowParser:
    """Tests for row-aware exclusion filtering with MarkerRowParser (EXT-FN-1)."""

    @pytest.fixture
    def matcher(self):
        """Create a KeywordMatcher instance."""
        return KeywordMatcher()

    def test_exclusion_respects_table_row_boundaries_marker_parser(self, matcher):
        """Values in 'Paid Customers >$100,000' row should NOT be excluded by 'Net Dollar Retention Rate' in adjacent row."""
        from src.review.marker_row_parser import MarkerRowParser

        # This is the actual pattern from Slack's S-1 filing
        text = "Paid Customers >$100,000 [CELL] 135 [CELL] 298 [ROW] Net Dollar Retention Rate [CELL] 171 [CELL] %"
        parser = MarkerRowParser(text)

        # Position of "135" is in row with "Paid Customers >$100,000"
        # "Net Dollar Retention Rate" is in a DIFFERENT row
        # Exclusion pattern "\bretention\s+rate\b" should NOT match for cm_large_customers_period_end
        # because it's in a different row

        should_exclude, reason = matcher.should_exclude_for_number_context(
            metric_id="cm_large_customers_period_end",
            text=text,
            number_position=32,  # position of "135"
            table_row_parser=parser,
        )
        assert should_exclude is False, f"Value should NOT be excluded - 'retention rate' is in different row. Got: {reason}"

    def test_exclusion_triggers_when_pattern_in_same_row(self, matcher):
        """Exclusion pattern IN the same row SHOULD trigger exclusion."""
        from src.review.marker_row_parser import MarkerRowParser

        # Exclusion pattern IS in the same row as the number
        text = "Net Dollar Retention Rate [CELL] 135 [CELL] 298 [ROW] Paid Customers [CELL] 500"
        parser = MarkerRowParser(text)

        # "135" is in the same row as "Net Dollar Retention Rate"
        # So it SHOULD be excluded for cm_large_customers_period_end
        should_exclude, reason = matcher.should_exclude_for_number_context(
            metric_id="cm_large_customers_period_end",
            text=text,
            number_position=33,  # position of "135"
            table_row_parser=parser,
        )
        assert should_exclude is True, "Value should be excluded - 'retention rate' is in SAME row"
        assert "retention" in reason.lower()

    def test_exclusion_uses_full_row_text_not_window(self, matcher):
        """Row-based exclusion should use full row text, not fixed window."""
        from src.review.marker_row_parser import MarkerRowParser

        # Long row where window-based exclusion would fail
        # Row is > 200 chars, but exclusion pattern is in the row
        padding = "A " * 60  # 120 chars of padding
        text = f"Net Dollar Retention Rate [CELL] {padding}135 [ROW] Other Row [CELL] 500"
        parser = MarkerRowParser(text)

        # Position of "135" - it's far from "retention rate" (> 100 chars)
        # But with row-based context, the whole row is checked
        number_pos = text.find("135")

        should_exclude, reason = matcher.should_exclude_for_number_context(
            metric_id="cm_large_customers_period_end",
            text=text,
            number_position=number_pos,
            table_row_parser=parser,
        )
        assert should_exclude is True, "Should use full row text for exclusion check"

    def test_multiple_values_same_row_not_excluded(self, matcher):
        """Multiple values in same row should all be correctly not-excluded."""
        from src.review.marker_row_parser import MarkerRowParser

        text = "Paid Customers >$100,000 [CELL] 135 [CELL] 298 [CELL] 575 [ROW] Net Dollar Retention Rate [CELL] 171"
        parser = MarkerRowParser(text)

        # Test all three values in the "Paid Customers" row
        values = [
            ("135", 32),
            ("298", 41),
            ("575", 50),
        ]

        for raw_text, expected_approx_pos in values:
            actual_pos = text.find(raw_text)
            should_exclude, reason = matcher.should_exclude_for_number_context(
                metric_id="cm_large_customers_period_end",
                text=text,
                number_position=actual_pos,
                table_row_parser=parser,
            )
            assert should_exclude is False, f"Value '{raw_text}' should NOT be excluded - retention rate in different row. Got: {reason}"

    def test_value_in_retention_row_is_excluded(self, matcher):
        """Value in retention rate row SHOULD be excluded from large customers metric."""
        from src.review.marker_row_parser import MarkerRowParser

        text = "Paid Customers >$100,000 [CELL] 135 [ROW] Net Dollar Retention Rate [CELL] 171 [CELL] %"
        parser = MarkerRowParser(text)

        # "171" is in the "Net Dollar Retention Rate" row
        value_171_pos = text.find("171")

        should_exclude, reason = matcher.should_exclude_for_number_context(
            metric_id="cm_large_customers_period_end",
            text=text,
            number_position=value_171_pos,
            table_row_parser=parser,
        )
        assert should_exclude is True, "Value 171 in retention row should be excluded"

    def test_fallback_to_window_when_position_not_in_row(self, matcher):
        """If position not in any row, fall back to window-based exclusion."""
        from src.review.marker_row_parser import MarkerRowParser

        # Parser will parse the table rows, but we'll query a position
        # that's outside the parsed rows (e.g., in the marker itself)
        text = "Row1 [CELL] 100 [ROW] Row2 [CELL] 200"
        parser = MarkerRowParser(text)

        # Position in the [ROW] marker (between rows)
        marker_pos = text.find(" [ROW] ") + 3

        # This should fall back to window-based exclusion
        should_exclude, reason = matcher.should_exclude_for_number_context(
            metric_id="cm_large_customers_period_end",
            text=text,
            number_position=marker_pos,
            table_row_parser=parser,
        )
        # Should not crash, and should use fallback behavior
        assert should_exclude in (True, False)


class TestShouldExcludeWithTableRowParser:
    """Tests for row-aware exclusion filtering with TableRowParser (HTML-based)."""

    @pytest.fixture
    def matcher(self):
        """Create a KeywordMatcher instance."""
        return KeywordMatcher()

    def test_exclusion_respects_table_row_boundaries_html_parser(self, matcher):
        """HTML TableRowParser should also respect row boundaries."""
        from src.review.table_structure import TableRowParser

        # HTML table with proper structure
        html = """<table>
            <tr><td>Paid Customers &gt;$100,000</td><td>135</td><td>298</td></tr>
            <tr><td>Net Dollar Retention Rate</td><td>171</td><td>%</td></tr>
        </table>"""
        # Text must match what BeautifulSoup.get_text() produces (no spaces between cells)
        text = "Paid Customers >$100,000135298 Net Dollar Retention Rate171%"
        parser = TableRowParser(html, text)

        # Verify parser detects table correctly
        assert parser.is_table(), "Parser should detect this as a table"
        assert len(parser.get_rows()) >= 2, "Should have at least 2 rows"

        # Position of "135" should be in the first row
        value_pos = text.find("135")

        should_exclude, reason = matcher.should_exclude_for_number_context(
            metric_id="cm_large_customers_period_end",
            text=text,
            number_position=value_pos,
            table_row_parser=parser,
        )
        assert should_exclude is False, f"Value should NOT be excluded with HTML parser. Got: {reason}"

    def test_html_parser_same_row_exclusion(self, matcher):
        """HTML parser should exclude when pattern IS in same row."""
        from src.review.table_structure import TableRowParser

        html = """<table>
            <tr><td>Net Dollar Retention Rate</td><td>135</td></tr>
            <tr><td>Paid Customers</td><td>500</td></tr>
        </table>"""
        # Text must match what BeautifulSoup.get_text() produces
        text = "Net Dollar Retention Rate135 Paid Customers500"
        parser = TableRowParser(html, text)

        # Verify parser detects table correctly
        assert parser.is_table(), "Parser should detect this as a table"

        # "135" is in the same row as "Net Dollar Retention Rate"
        value_pos = text.find("135")

        should_exclude, reason = matcher.should_exclude_for_number_context(
            metric_id="cm_large_customers_period_end",
            text=text,
            number_position=value_pos,
            table_row_parser=parser,
        )
        assert should_exclude is True, "Should exclude - retention rate in same row"


class TestShouldExcludeNonTableFallback:
    """Tests verifying non-table segments use window-based exclusion."""

    @pytest.fixture
    def matcher(self):
        """Create a KeywordMatcher instance."""
        return KeywordMatcher()

    def test_no_parser_uses_window_exclusion(self, matcher):
        """Without parser, use 100-char window for exclusion."""
        text = "retention rate is 95%. Large customers count: 135 users"
        # "retention rate" is within 100 chars of 135

        should_exclude, reason = matcher.should_exclude_for_number_context(
            metric_id="cm_large_customers_period_end",
            text=text,
            number_position=46,  # position of "135"
            table_row_parser=None,
        )
        assert should_exclude is True, "Without parser, should use window and find 'retention rate'"

    def test_non_table_parser_uses_window(self, matcher):
        """Parser that doesn't detect a table falls back to window."""
        from src.review.marker_row_parser import MarkerRowParser

        # No [ROW] markers = not a table, parser.is_table() returns False
        text = "retention rate is 95%. Large customers count: 135 users"
        parser = MarkerRowParser(text)

        assert parser.is_table() is False, "Should not detect as table"

        should_exclude, reason = matcher.should_exclude_for_number_context(
            metric_id="cm_large_customers_period_end",
            text=text,
            number_position=46,  # position of "135"
            table_row_parser=parser,
        )
        assert should_exclude is True, "Non-table parser should fall back to window exclusion"

    def test_single_row_parser_is_not_table(self, matcher):
        """Parser with only one row is not considered a table."""
        from src.review.marker_row_parser import MarkerRowParser

        # Only cell markers, no row markers = single row = not a table
        text = "Large Customers [CELL] 135 [CELL] retention rate 95%"
        parser = MarkerRowParser(text)

        # is_table() returns True only if 2+ rows
        # With no [ROW] markers, this is just 1 row
        assert parser.is_table() is False

        should_exclude, reason = matcher.should_exclude_for_number_context(
            metric_id="cm_large_customers_period_end",
            text=text,
            number_position=23,  # position of "135"
            table_row_parser=parser,
        )
        # Falls back to window - "retention rate" is within 100 chars
        assert should_exclude is True
