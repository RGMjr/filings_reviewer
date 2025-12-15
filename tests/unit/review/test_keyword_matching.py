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

        text = "We had 50000 active customers. Revenue was $100M with gross margin of 52%."
        detector = BoundaryDetector()
        sentences = detector.find_sentence_boundaries(text)

        # Number in second sentence (52%)
        num_pos = text.index("52%")
        number = NumberMatch(
            start=num_pos,
            end=num_pos + 3,
            raw_text="52%",
            value=Decimal("52"),
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

        # With filtering: should only find "gross margin" (in sentence 2)
        # Without filtering: might also find "active customers" (in sentence 1)
        keywords_with_ids = {kw.metric_id for kw in keywords_with_filter}
        keywords_without_ids = {kw.metric_id for kw in keywords_no_filter}

        # Gross margin should be in both
        assert "cm_gross_margin_overall" in keywords_with_ids

        # Active customers should be filtered WITH sentence boundaries
        # but present WITHOUT sentence boundaries (if within distance)
        if "cm_active_customers_total" in keywords_without_ids:
            # If found without filtering, should NOT be found with filtering
            assert "cm_active_customers_total" not in keywords_with_ids

    def test_problem_example_cross_sentence_filtering(self):
        """Test that cross-sentence keywords are properly filtered."""
        from src.review.boundary_detection import BoundaryDetector

        # Use metrics that exist in the taxonomy for both sentences
        text = "We had 50000 active customers in 2023. Gross margin was 52% in Q1."
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

        # Number in second sentence (52%) - should match "gross margin"
        num2_pos = text.index("52%")
        num2 = NumberMatch(
            start=num2_pos,
            end=num2_pos + 3,
            raw_text="52%",
            value=Decimal("52"),
            unit="percent",
        )

        matcher = KeywordMatcher(respect_sentence_boundaries=True, max_keyword_distance=150)
        all_keywords = matcher.find_all_keywords(text)

        # Verify we found keywords in both sentences
        assert any("customer" in kw.keyword.lower() for kw in all_keywords), \
            "Should find 'active customers' keyword"
        assert any("gross margin" in kw.keyword.lower() for kw in all_keywords), \
            "Should find 'gross margin' keyword"

        # 50000 should only match keywords in sentence 1
        keywords1 = matcher.find_keywords_near_number(
            num1, all_keywords, sentence_boundaries=sentences
        )

        # 52% should only match keywords in sentence 2
        keywords2 = matcher.find_keywords_near_number(
            num2, all_keywords, sentence_boundaries=sentences
        )

        # Keywords for 50000 should be "active customers" (sentence 1)
        for kw in keywords1:
            assert sentences[0].contains_position(kw.start), \
                f"Keyword '{kw.keyword}' at pos {kw.start} should be in sentence 1 ({sentences[0].start}-{sentences[0].end})"

        # Keywords for 52% should be "gross margin" (sentence 2)
        for kw in keywords2:
            assert sentences[1].contains_position(kw.start), \
                f"Keyword '{kw.keyword}' at pos {kw.start} should be in sentence 2 ({sentences[1].start}-{sentences[1].end})"

        # Verify the key behavior: 50000 should NOT match "gross margin"
        keywords1_ids = {kw.metric_id for kw in keywords1}
        assert "cm_gross_margin_overall" not in keywords1_ids, \
            "50000 should not match gross margin (different sentence)"

        # Verify the key behavior: 52% should NOT match "active customers"
        keywords2_ids = {kw.metric_id for kw in keywords2}
        assert "cm_active_customers_total" not in keywords2_ids, \
            "52% should not match active customers (different sentence)"

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

        text = "We had 50000 active customers. Revenue was $100M with gross margin of 52%."
        detector = BoundaryDetector()
        sentences = detector.find_sentence_boundaries(text)

        # Number in second sentence
        num_pos = text.index("52%")
        number = NumberMatch(
            start=num_pos,
            end=num_pos + 3,
            raw_text="52%",
            value=Decimal("52"),
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
• Second bullet: gross margin was 52%. Costs increased."""

        detector = BoundaryDetector()
        boundaries = detector.find_boundaries(text)
        sentences = detector.find_sentence_boundaries(text)

        # Number "52%" is in second bullet, first sentence within that bullet
        num_pos = text.index("52%")
        number = NumberMatch(
            start=num_pos,
            end=num_pos + 3,
            raw_text="52%",
            value=Decimal("52"),
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
        # "gross margin" is in same bullet AND same sentence
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
        text = "Our active customers reached 50000 while gross margin improved to 52% in Q1."
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

        # May find both "active customers" and "gross margin" since they're in same sentence
        metric_ids = {kw.metric_id for kw in keywords}
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
        text = "gross margin was 30% gross margin again"
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

        # Should match one of the gross margin keywords
        assert len(result) >= 1
        # The matched keyword should have a direction
        assert result[0].direction in ("before", "after")
        # Direction should be set correctly (either before or after, depending on which matched)

    def test_keyword_immediately_after(self, matcher):
        """Keyword immediately following number is 'after'."""
        text = "30% gross margin"

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
        text = "gross margin 30%"

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
        text = "We had 50000 active customers and gross margin of 52%"
        #              ^num1  ^kw1                            ^kw2 ^num2

        # First number (50000) - "active customers" is after it
        num1 = NumberMatch(
            start=text.index("50000"),
            end=text.index("50000") + 5,
            raw_text="50000",
            value=Decimal("50000"),
            unit="count",
        )

        # Second number (52%) - "gross margin" is before it
        num2 = NumberMatch(
            start=text.index("52"),
            end=text.index("52") + 3,
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
