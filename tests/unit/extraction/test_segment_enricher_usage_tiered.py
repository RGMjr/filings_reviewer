"""
Unit tests for SegmentEnricher tiered usage metric bonus (GI-10).

Tests the tiered usage bonus enhancement that differentiates between:
1. Usage metrics with numeric values (+1.0): "10 million daily active users"
2. Usage keywords with context (+0.75): "DAU" in definition or with metrics
3. Basic usage keywords (+0.5): "daily active users" alone

Test coverage target: >= 95% for _detect_usage_with_count() and tiered bonus logic.
"""

import pytest

from src.extraction.models import SourceSegment
from src.extraction.segment_enricher import SegmentEnricher


@pytest.fixture
def enricher() -> SegmentEnricher:
    """Create a SegmentEnricher instance."""
    return SegmentEnricher()


def make_segment(
    raw_text: str = "",
    raw_html: str = "",
    classifier_confidence: float = 0.5,
    distinct_metric_count: int = 0,
    candidate_metric_ids: list[str] | None = None,
    contains_temporal_trend: bool = False,
    contains_cohort_breakdown: bool = False,
    contains_definition_flag: bool = False,
    image_count: int = 0,
    extra_metadata: dict[str, bool] | None = None,
) -> SourceSegment:
    """Factory for creating test segments with specified attributes."""
    segment = SourceSegment(
        filing_id=1,
        segment_type="paragraph",
        raw_text=raw_text,
        raw_html=raw_html or f"<p>{raw_text}</p>",
        classifier_confidence=classifier_confidence,
        distinct_metric_count=distinct_metric_count,
        candidate_metric_ids=candidate_metric_ids or [],
        contains_temporal_trend=contains_temporal_trend,
        contains_cohort_breakdown=contains_cohort_breakdown,
        contains_definition_flag=contains_definition_flag,
        image_count=image_count,
        extra_metadata=extra_metadata,
    )
    return segment


# =============================================================================
# Usage With Count Detection Tests (10 tests)
# =============================================================================


class TestUsageWithCountDetection:
    """Test _detect_usage_with_count() method for numeric usage metrics."""

    def test_dau_with_count_million(self, enricher: SegmentEnricher) -> None:
        """Detect '10 million daily active users'."""
        segment = make_segment(
            raw_text="As of January 31, 2019, Slack had more than 10 million daily active users."
        )
        assert enricher._detect_usage_with_count(segment.raw_text) is True

    def test_mau_with_count_abbreviation(self, enricher: SegmentEnricher) -> None:
        """Detect '5M MAU'."""
        segment = make_segment(raw_text="We reached 5M MAU in Q4 2018.")
        assert enricher._detect_usage_with_count(segment.raw_text) is True

    def test_dau_with_percentage_growth(self, enricher: SegmentEnricher) -> None:
        """Detect 'daily active users grew 50%'."""
        segment = make_segment(raw_text="Our daily active users grew 50% year-over-year.")
        assert enricher._detect_usage_with_count(segment.raw_text) is True

    def test_organizations_with_dau_count(self, enricher: SegmentEnricher) -> None:
        """Detect '600,000 organizations with daily active users'."""
        segment = make_segment(raw_text="We serve 600,000 organizations with daily active users.")
        assert enricher._detect_usage_with_count(segment.raw_text) is True

    def test_dau_of_millions(self, enricher: SegmentEnricher) -> None:
        """Detect 'DAU of 8.5 million'."""
        segment = make_segment(raw_text="Our platform achieved DAU of 8.5 million.")
        assert enricher._detect_usage_with_count(segment.raw_text) is True

    def test_reverse_pattern_million_mau(self, enricher: SegmentEnricher) -> None:
        """Detect '12.3 million MAU'."""
        segment = make_segment(raw_text="The service has 12.3 million MAU.")
        assert enricher._detect_usage_with_count(segment.raw_text) is True

    def test_percentage_growth_in_wau(self, enricher: SegmentEnricher) -> None:
        """Detect '35% growth in weekly active users'."""
        segment = make_segment(raw_text="We saw 35% growth in weekly active users this quarter.")
        assert enricher._detect_usage_with_count(segment.raw_text) is True

    def test_basic_dau_keyword_no_count(self, enricher: SegmentEnricher) -> None:
        """Basic 'daily active users' without count should return False."""
        segment = make_segment(raw_text="We measure daily active users as a key metric.")
        assert enricher._detect_usage_with_count(segment.raw_text) is False

    def test_dau_acronym_alone(self, enricher: SegmentEnricher) -> None:
        """DAU acronym alone without count should return False."""
        segment = make_segment(raw_text="DAU is an important engagement metric.")
        assert enricher._detect_usage_with_count(segment.raw_text) is False

    def test_empty_text(self, enricher: SegmentEnricher) -> None:
        """Empty text should return False."""
        segment = make_segment(raw_text="")
        assert enricher._detect_usage_with_count(segment.raw_text) is False

    def test_none_text(self, enricher: SegmentEnricher) -> None:
        """None text should return False."""
        segment = make_segment(raw_text="")
        segment.raw_text = None  # type: ignore
        assert enricher._detect_usage_with_count(segment.raw_text) is False

    def test_over_prefix(self, enricher: SegmentEnricher) -> None:
        """Detect 'over 20 million monthly active users'."""
        segment = make_segment(raw_text="Our platform has over 20 million monthly active users.")
        assert enricher._detect_usage_with_count(segment.raw_text) is True

    def test_approximately_prefix(self, enricher: SegmentEnricher) -> None:
        """Detect 'approximately 15M daily active users'."""
        segment = make_segment(raw_text="The network has approximately 15M daily active users.")
        assert enricher._detect_usage_with_count(segment.raw_text) is True


# =============================================================================
# Tiered Bonus Calculation Tests (8 tests)
# =============================================================================


class TestTieredUsageBonus:
    """Test tiered bonus calculation in _compute_richness_score()."""

    def test_usage_with_count_gets_1_0_bonus(self, enricher: SegmentEnricher) -> None:
        """Usage metric with count should get +1.0 bonus (not +0.5 or +0.75)."""
        segment = make_segment(
            raw_text="We had 10 million daily active users in 2019.",
            classifier_confidence=0.0,
            extra_metadata={
                "contains_usage_with_count": True,
                "contains_usage_keywords": True,  # Should be ignored (highest tier wins)
            },
        )
        score = enricher._compute_richness_score(segment)
        assert score == pytest.approx(1.0, abs=0.01)

    def test_usage_keyword_with_definition_gets_0_75(self, enricher: SegmentEnricher) -> None:
        """Usage keyword + definition flag should get +0.75 bonus."""
        segment = make_segment(
            raw_text="We define daily active users as authenticated users who log in.",
            classifier_confidence=0.0,
            contains_definition_flag=True,
            extra_metadata={
                "contains_usage_keywords": True,
                "contains_usage_with_count": False,
            },
        )
        score = enricher._compute_richness_score(segment)
        # Expected: 1.0 (definition) + 0.75 (usage mid-tier) = 1.75
        assert score == pytest.approx(1.75, abs=0.01)

    def test_usage_keyword_with_metric_gets_0_75(self, enricher: SegmentEnricher) -> None:
        """Usage keyword + metric_count >= 1 should get +0.75 bonus."""
        segment = make_segment(
            raw_text="Daily active users and retention are key metrics.",
            classifier_confidence=0.0,
            distinct_metric_count=1,
            extra_metadata={
                "contains_usage_keywords": True,
                "contains_usage_with_count": False,
            },
        )
        score = enricher._compute_richness_score(segment)
        # 0.5 (metric count) + 0.75 (usage mid-tier) = 1.25
        assert score == pytest.approx(1.25, abs=0.01)

    def test_basic_usage_keyword_only_gets_0_5(self, enricher: SegmentEnricher) -> None:
        """Basic usage keyword alone should get +0.5 bonus."""
        segment = make_segment(
            raw_text="Our platform tracks daily active users.",
            classifier_confidence=0.0,
            contains_definition_flag=False,
            distinct_metric_count=0,
            extra_metadata={
                "contains_usage_keywords": True,
                "contains_usage_with_count": False,
            },
        )
        score = enricher._compute_richness_score(segment)
        assert score == pytest.approx(0.5, abs=0.01)

    def test_no_usage_keyword_gets_0_0(self, enricher: SegmentEnricher) -> None:
        """No usage keyword should get +0.0 bonus."""
        segment = make_segment(
            raw_text="Revenue grew 50% in 2019.",
            classifier_confidence=0.0,
            extra_metadata={
                "contains_usage_keywords": False,
                "contains_usage_with_count": False,
            },
        )
        score = enricher._compute_richness_score(segment)
        assert score == pytest.approx(0.0, abs=0.01)

    def test_tiers_are_mutually_exclusive_highest_wins(self, enricher: SegmentEnricher) -> None:
        """When multiple tiers match, highest tier should win (not cumulative)."""
        segment = make_segment(
            raw_text="We define DAU as users logging in daily. We had 10 million DAU.",
            classifier_confidence=0.0,
            contains_definition_flag=True,
            distinct_metric_count=1,
            extra_metadata={
                "contains_usage_with_count": True,
                "contains_usage_keywords": True,
            },
        )
        score = enricher._compute_richness_score(segment)
        # Expected: 1.0 (definition) + 0.5 (metric) + 1.0 (usage with count) = 2.5
        # The usage tiers are mutually exclusive (only +1.0, not +1.0 + 0.75)
        assert score == pytest.approx(2.5, abs=0.01)

    def test_usage_with_count_ignores_definition_flag(self, enricher: SegmentEnricher) -> None:
        """Usage with count gets +1.0 regardless of definition flag."""
        segment = make_segment(
            raw_text="10 million daily active users",
            classifier_confidence=0.0,
            contains_definition_flag=True,  # Should not affect bonus
            extra_metadata={
                "contains_usage_with_count": True,
                "contains_usage_keywords": True,
            },
        )
        score = enricher._compute_richness_score(segment)
        # 1.0 (definition) + 1.0 (usage with count) = 2.0
        assert score == pytest.approx(2.0, abs=0.01)

    def test_missing_extra_metadata_defaults_to_zero(self, enricher: SegmentEnricher) -> None:
        """Missing extra_metadata should default to no bonus."""
        segment = make_segment(
            raw_text="Some text",
            classifier_confidence=0.0,
            extra_metadata=None,  # Missing metadata
        )
        score = enricher._compute_richness_score(segment)
        assert score == pytest.approx(0.0, abs=0.01)


# =============================================================================
# Integration with Full Score Tests (6 tests)
# =============================================================================


class TestIntegrationWithFullScore:
    """Test tiered usage bonus integration with full richness scoring."""

    def test_slack_dau_segment_high_score(self, enricher: SegmentEnricher) -> None:
        """Real Slack S-1 snippet should score high with usage count bonus."""
        segment = make_segment(
            raw_text="As of January 31, 2019, Slack had more than 10 million daily active users, "
            "representing organizations in more than 150 countries.",
            classifier_confidence=0.8,
            distinct_metric_count=1,
            contains_temporal_trend=True,
            extra_metadata={
                "contains_usage_with_count": True,
                "contains_usage_keywords": True,
            },
        )
        score = enricher._compute_richness_score(segment)
        # Expect: 2.4 (conf) + 0.5 (metric) + 1.0 (temporal) + 1.0 (usage count) = 4.9
        assert score >= 4.5  # Should be significantly higher than old 3.9

    def test_usage_count_temporal_definition_combination(self, enricher: SegmentEnricher) -> None:
        """Segment with usage count + temporal + definition should score high."""
        segment = make_segment(
            raw_text="In 2018, we had 5 million daily active users. We define DAU as users "
            "logging in at least once per day during the measurement period.",
            classifier_confidence=0.9,
            distinct_metric_count=1,
            contains_temporal_trend=True,
            contains_definition_flag=True,
            extra_metadata={
                "contains_usage_with_count": True,
                "contains_usage_keywords": True,
            },
        )
        score = enricher._compute_richness_score(segment)
        # Expect: 2.7 (conf) + 0.5 (metric) + 1.0 (temporal) + 1.0 (def) + 1.0 (usage count) = 6.2
        assert score >= 6.0  # Should reach goldmine threshold

    def test_usage_keyword_only_lower_score(self, enricher: SegmentEnricher) -> None:
        """Basic usage keyword should score lower than usage with count."""
        segment = make_segment(
            raw_text="We track daily active users as our primary engagement metric.",
            classifier_confidence=0.8,
            distinct_metric_count=1,
            extra_metadata={
                "contains_usage_keywords": True,
                "contains_usage_with_count": False,
            },
        )
        score = enricher._compute_richness_score(segment)
        # Expect: 2.4 (conf) + 0.5 (metric) + 0.75 (usage mid-tier) = 3.65
        assert 3.5 <= score <= 4.0

    def test_mid_tier_with_definition(self, enricher: SegmentEnricher) -> None:
        """Usage keyword + definition should use mid-tier (+0.75)."""
        segment = make_segment(
            raw_text="We define monthly active users as the number of unique users "
            "who access the platform at least once during a calendar month.",
            classifier_confidence=0.7,
            distinct_metric_count=0,
            contains_definition_flag=True,
            extra_metadata={
                "contains_usage_keywords": True,
                "contains_usage_with_count": False,
            },
        )
        score = enricher._compute_richness_score(segment)
        # Expect: 2.1 (conf) + 1.0 (def) + 0.75 (usage mid-tier) = 3.85
        assert score == pytest.approx(3.85, abs=0.01)

    def test_all_bonuses_combined(self, enricher: SegmentEnricher) -> None:
        """Test segment with multiple bonus components."""
        segment = make_segment(
            raw_text="In 2018 and 2019, our 10 million daily active users were segmented "
            "by cohort. NRR increased to 130%.",
            classifier_confidence=1.0,
            distinct_metric_count=2,
            contains_temporal_trend=True,
            contains_cohort_breakdown=True,
            contains_definition_flag=False,
            extra_metadata={
                "contains_usage_with_count": True,
                "contains_usage_keywords": True,
                "contains_retention_keywords": True,
            },
        )
        score = enricher._compute_richness_score(segment)
        # 3.0 (conf) + 1.0 (metrics) + 1.0 (temporal) + 1.5 (cohort)
        # + 0.5 (combo) + 1.0 (retention) + 1.0 (usage count) = 9.0
        assert score >= 8.5

    def test_verification_against_old_score(self, enricher: SegmentEnricher) -> None:
        """Verify new score is higher than old flat +0.5 bonus."""
        segment = make_segment(
            raw_text="We had 10 million daily active users as of December 31, 2018.",
            classifier_confidence=0.6,
            distinct_metric_count=1,
            contains_temporal_trend=True,
            extra_metadata={
                "contains_usage_with_count": True,
                "contains_usage_keywords": True,
            },
        )
        score = enricher._compute_richness_score(segment)
        # New: 1.8 (conf) + 0.5 (metric) + 1.0 (temporal) + 1.0 (usage count) = 4.3
        # Old would have been: 1.8 + 0.5 + 1.0 + 0.5 = 3.8
        assert score >= 4.0


# =============================================================================
# Edge Cases Tests (3 tests)
# =============================================================================


class TestEdgeCases:
    """Test edge cases for tiered usage bonus."""

    def test_both_usage_patterns_only_counts_once(self, enricher: SegmentEnricher) -> None:
        """Segment with both base and count patterns should only count highest tier."""
        segment = make_segment(
            raw_text="Daily active users are important. We had 10 million daily active users.",
            classifier_confidence=0.0,
            extra_metadata={
                "contains_usage_with_count": True,
                "contains_usage_keywords": True,
            },
        )
        score = enricher._compute_richness_score(segment)
        # Should only get +1.0, not +1.0 + 0.5 or +1.0 + 0.75
        assert score == pytest.approx(1.0, abs=0.01)

    def test_usage_keyword_false_usage_count_true_impossible_but_handled(
        self, enricher: SegmentEnricher
    ) -> None:
        """Handle impossible case where count=True but keyword=False gracefully."""
        segment = make_segment(
            raw_text="Some text",
            classifier_confidence=0.0,
            extra_metadata={
                "contains_usage_with_count": True,
                "contains_usage_keywords": False,  # Logically inconsistent
            },
        )
        score = enricher._compute_richness_score(segment)
        # Should still apply highest tier (+1.0)
        assert score == pytest.approx(1.0, abs=0.01)

    def test_empty_extra_metadata_dict(self, enricher: SegmentEnricher) -> None:
        """Empty extra_metadata dict should default to no bonus."""
        segment = make_segment(
            raw_text="Some text",
            classifier_confidence=0.0,
            extra_metadata={},  # Empty dict
        )
        score = enricher._compute_richness_score(segment)
        assert score == pytest.approx(0.0, abs=0.01)


# =============================================================================
# Backward Compatibility Tests (2 tests)
# =============================================================================


class TestBackwardCompatibility:
    """Ensure tiered bonus maintains backward compatibility with GI-6."""

    def test_basic_usage_still_gets_0_5(self, enricher: SegmentEnricher) -> None:
        """Basic usage keywords should still get +0.5 bonus (GI-6 behavior)."""
        segment = make_segment(
            raw_text="We monitor daily active users.",
            classifier_confidence=0.0,
            extra_metadata={
                "contains_usage_keywords": True,
                "contains_usage_with_count": False,
            },
        )
        score = enricher._compute_richness_score(segment)
        assert score == pytest.approx(0.5, abs=0.01)

    def test_no_regression_on_other_bonuses(self, enricher: SegmentEnricher) -> None:
        """Other bonuses should remain unchanged."""
        segment = make_segment(
            raw_text="NRR increased to 120% in Q4 2019.",
            classifier_confidence=0.5,
            distinct_metric_count=1,
            contains_temporal_trend=True,
            extra_metadata={
                "contains_retention_keywords": True,
                "contains_usage_keywords": False,
            },
        )
        score = enricher._compute_richness_score(segment)
        # 1.5 (conf) + 0.5 (metric) + 1.0 (temporal) + 1.0 (retention) = 4.0
        assert score == pytest.approx(4.0, abs=0.01)
