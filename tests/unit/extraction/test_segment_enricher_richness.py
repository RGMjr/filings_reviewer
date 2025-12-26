"""
Unit tests for SegmentEnricher richness formula calibration (GI-6).

Tests the weight adjustments based on GI-3 distribution analysis:
1. Retention keyword bonus (+1.0) for NRR/NDRR/gross retention
2. Usage keyword bonus (+0.5) for DAU/MAU/WAU metrics
3. Enhanced definition bonus (+1.5 when combined with metrics>=2)
4. Combination bonus (+0.5 for temporal AND cohort together)

Test coverage target: >= 95% for _compute_richness_score() and detection methods.
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
# Component Isolation Tests (8+ tests)
# =============================================================================


class TestComponentIsolation:
    """Test each formula component in isolation."""

    def test_confidence_only(self, enricher: SegmentEnricher) -> None:
        """Base confidence contributes 0-3.0 points."""
        # Low confidence
        segment_low = make_segment(classifier_confidence=0.2)
        score_low = enricher._compute_richness_score(segment_low)
        assert score_low == pytest.approx(0.6, abs=0.01)  # 0.2 * 3.0

        # Medium confidence
        segment_med = make_segment(classifier_confidence=0.5)
        score_med = enricher._compute_richness_score(segment_med)
        assert score_med == pytest.approx(1.5, abs=0.01)  # 0.5 * 3.0

        # Max confidence
        segment_max = make_segment(classifier_confidence=1.0)
        score_max = enricher._compute_richness_score(segment_max)
        assert score_max == pytest.approx(3.0, abs=0.01)  # 1.0 * 3.0

    def test_metric_count_bonus_capped_at_2(self, enricher: SegmentEnricher) -> None:
        """Metric density bonus is capped at 2.0 points."""
        # 1 metric = 0.5 points
        segment_1 = make_segment(classifier_confidence=0, distinct_metric_count=1)
        assert enricher._compute_richness_score(segment_1) == pytest.approx(0.5, abs=0.01)

        # 4 metrics = 2.0 points (capped)
        segment_4 = make_segment(classifier_confidence=0, distinct_metric_count=4)
        assert enricher._compute_richness_score(segment_4) == pytest.approx(2.0, abs=0.01)

        # 10 metrics = still 2.0 points (capped)
        segment_10 = make_segment(classifier_confidence=0, distinct_metric_count=10)
        assert enricher._compute_richness_score(segment_10) == pytest.approx(2.0, abs=0.01)

    def test_temporal_bonus_adds_1_point(self, enricher: SegmentEnricher) -> None:
        """Temporal trend flag adds +1.0 point."""
        segment = make_segment(classifier_confidence=0, contains_temporal_trend=True)
        score = enricher._compute_richness_score(segment)
        assert score == pytest.approx(1.0, abs=0.01)

    def test_cohort_bonus_adds_1_5_points(self, enricher: SegmentEnricher) -> None:
        """Cohort breakdown flag adds +1.5 points."""
        segment = make_segment(classifier_confidence=0, contains_cohort_breakdown=True)
        score = enricher._compute_richness_score(segment)
        assert score == pytest.approx(1.5, abs=0.01)

    def test_definition_only_adds_1_point(self, enricher: SegmentEnricher) -> None:
        """Definition flag alone adds +1.0 point (no metrics)."""
        segment = make_segment(
            classifier_confidence=0,
            contains_definition_flag=True,
            distinct_metric_count=0,
        )
        score = enricher._compute_richness_score(segment)
        assert score == pytest.approx(1.0, abs=0.01)

    def test_definition_with_1_metric_adds_1_point(
        self, enricher: SegmentEnricher
    ) -> None:
        """Definition flag with 1 metric adds +1.0 (standard bonus)."""
        segment = make_segment(
            classifier_confidence=0,
            contains_definition_flag=True,
            distinct_metric_count=1,
        )
        score = enricher._compute_richness_score(segment)
        # 0.5 (metric) + 1.0 (definition) = 1.5
        assert score == pytest.approx(1.5, abs=0.01)

    def test_definition_with_2_plus_metrics_adds_1_5_points(
        self, enricher: SegmentEnricher
    ) -> None:
        """Definition flag with 2+ metrics adds +1.5 (enhanced bonus)."""
        segment = make_segment(
            classifier_confidence=0,
            contains_definition_flag=True,
            distinct_metric_count=2,
        )
        score = enricher._compute_richness_score(segment)
        # 1.0 (2 metrics) + 1.5 (enhanced definition) = 2.5
        assert score == pytest.approx(2.5, abs=0.01)

    def test_retention_keywords_add_1_point(self, enricher: SegmentEnricher) -> None:
        """Retention keyword bonus adds +1.0 point."""
        segment = make_segment(
            classifier_confidence=0,
            extra_metadata={"contains_retention_keywords": True},
        )
        score = enricher._compute_richness_score(segment)
        assert score == pytest.approx(1.0, abs=0.01)

    def test_usage_keywords_add_0_5_points(self, enricher: SegmentEnricher) -> None:
        """Usage keyword bonus adds +0.5 points."""
        segment = make_segment(
            classifier_confidence=0,
            extra_metadata={"contains_usage_keywords": True},
        )
        score = enricher._compute_richness_score(segment)
        assert score == pytest.approx(0.5, abs=0.01)

    def test_saas_indicator_adds_0_5_points(self, enricher: SegmentEnricher) -> None:
        """SaaS indicator bonus adds +0.5 points."""
        segment = make_segment(
            classifier_confidence=0,
            extra_metadata={"contains_saas_indicator": True},
        )
        score = enricher._compute_richness_score(segment)
        assert score == pytest.approx(0.5, abs=0.01)


# =============================================================================
# Combination Tests (5+ tests)
# =============================================================================


class TestCombinationBonuses:
    """Test bonus combinations and stacking."""

    def test_temporal_plus_cohort_gets_combination_bonus(
        self, enricher: SegmentEnricher
    ) -> None:
        """Temporal AND cohort together adds combination bonus (+0.5)."""
        segment = make_segment(
            classifier_confidence=0,
            contains_temporal_trend=True,
            contains_cohort_breakdown=True,
        )
        score = enricher._compute_richness_score(segment)
        # 1.0 (temporal) + 1.5 (cohort) + 0.5 (combination) = 3.0
        assert score == pytest.approx(3.0, abs=0.01)

    def test_temporal_only_no_combination_bonus(
        self, enricher: SegmentEnricher
    ) -> None:
        """Temporal alone does not get combination bonus."""
        segment = make_segment(
            classifier_confidence=0,
            contains_temporal_trend=True,
            contains_cohort_breakdown=False,
        )
        score = enricher._compute_richness_score(segment)
        assert score == pytest.approx(1.0, abs=0.01)  # Just temporal

    def test_cohort_only_no_combination_bonus(
        self, enricher: SegmentEnricher
    ) -> None:
        """Cohort alone does not get combination bonus."""
        segment = make_segment(
            classifier_confidence=0,
            contains_temporal_trend=False,
            contains_cohort_breakdown=True,
        )
        score = enricher._compute_richness_score(segment)
        assert score == pytest.approx(1.5, abs=0.01)  # Just cohort

    def test_all_flags_max_metrics_approaches_max(
        self, enricher: SegmentEnricher
    ) -> None:
        """All bonuses active with max metrics approaches 10.0."""
        segment = make_segment(
            classifier_confidence=1.0,  # +3.0
            distinct_metric_count=4,  # +2.0 (capped)
            contains_temporal_trend=True,  # +1.0
            contains_cohort_breakdown=True,  # +1.5
            contains_definition_flag=True,  # +1.5 (enhanced, metrics>=2)
            image_count=3,  # +1.5 (capped)
            extra_metadata={
                "contains_retention_keywords": True,  # +1.0
                "contains_usage_keywords": True,  # +0.5
                "contains_saas_indicator": True,  # +0.5
            },
        )
        score = enricher._compute_richness_score(segment)
        # 3.0 + 2.0 + 1.0 + 1.5 + 1.5 + 0.5 + 1.0 + 0.5 + 0.5 + 1.5 = 13.0 -> capped to 10.0
        assert score == 10.0

    def test_no_flags_minimal_score(self, enricher: SegmentEnricher) -> None:
        """No flags or metrics gives minimal score (just confidence)."""
        segment = make_segment(
            classifier_confidence=0.2,
            distinct_metric_count=0,
            contains_temporal_trend=False,
            contains_cohort_breakdown=False,
            contains_definition_flag=False,
            image_count=0,
        )
        score = enricher._compute_richness_score(segment)
        assert score == pytest.approx(0.6, abs=0.01)  # Just 0.2 * 3.0

    def test_retention_cohort_temporal_stack(
        self, enricher: SegmentEnricher
    ) -> None:
        """Retention + cohort + temporal all stack correctly."""
        segment = make_segment(
            classifier_confidence=0.5,  # +1.5
            contains_temporal_trend=True,  # +1.0
            contains_cohort_breakdown=True,  # +1.5
            extra_metadata={"contains_retention_keywords": True},  # +1.0
        )
        score = enricher._compute_richness_score(segment)
        # 1.5 + 1.0 + 1.5 + 0.5 (combo) + 1.0 = 5.5
        assert score == pytest.approx(5.5, abs=0.01)

    def test_definition_metrics_retention_stack(
        self, enricher: SegmentEnricher
    ) -> None:
        """Definition with metrics AND retention stack."""
        segment = make_segment(
            classifier_confidence=0.8,  # +2.4
            distinct_metric_count=2,  # +1.0
            contains_definition_flag=True,  # +1.5 (enhanced)
            extra_metadata={"contains_retention_keywords": True},  # +1.0
        )
        score = enricher._compute_richness_score(segment)
        # 2.4 + 1.0 + 1.5 + 1.0 = 5.9
        assert score == pytest.approx(5.9, abs=0.01)


# =============================================================================
# Boundary Tests (4+ tests)
# =============================================================================


class TestBoundaryValues:
    """Test threshold boundaries and edge cases."""

    def test_score_exactly_at_goldmine_threshold(
        self, enricher: SegmentEnricher
    ) -> None:
        """Score can be exactly at 6.0 (goldmine threshold)."""
        # Build segment to hit exactly 6.0
        # 1.5 (conf 0.5) + 1.5 (3 metrics) + 1.0 (temporal) + 1.0 (definition) + 1.0 (retention) = 6.0
        segment = make_segment(
            classifier_confidence=0.5,  # +1.5
            distinct_metric_count=3,  # +1.5
            contains_temporal_trend=True,  # +1.0
            contains_definition_flag=True,  # +1.0 (only 3 metrics, need <2 for standard)
            extra_metadata={"contains_retention_keywords": True},  # +1.0
        )
        _ = enricher._compute_richness_score(segment)
        # 1.5 + 1.5 + 1.0 + 1.5 (enhanced, 3>=2) + 1.0 = 6.5
        # Need to adjust - try different combo
        segment2 = make_segment(
            classifier_confidence=0.5,  # +1.5
            distinct_metric_count=1,  # +0.5
            contains_temporal_trend=True,  # +1.0
            contains_cohort_breakdown=True,  # +1.5 + 0.5 combo = 2.0
            contains_definition_flag=True,  # +1.0 (only 1 metric)
        )
        score2 = enricher._compute_richness_score(segment2)
        # 1.5 + 0.5 + 1.0 + 1.5 + 0.5 + 1.0 = 6.0
        assert score2 == pytest.approx(6.0, abs=0.01)
        assert score2 >= SegmentEnricher.GOLDMINE_THRESHOLD

    def test_score_exactly_at_high_value_threshold(
        self, enricher: SegmentEnricher
    ) -> None:
        """Score can reach 8.0 (high-value threshold)."""
        segment = make_segment(
            classifier_confidence=1.0,  # +3.0
            distinct_metric_count=2,  # +1.0
            contains_temporal_trend=True,  # +1.0
            contains_cohort_breakdown=True,  # +1.5 + 0.5 combo = 2.0
            contains_definition_flag=False,
            extra_metadata={"contains_retention_keywords": True},  # +1.0
        )
        score = enricher._compute_richness_score(segment)
        # 3.0 + 1.0 + 1.0 + 1.5 + 0.5 + 1.0 = 8.0
        assert score == pytest.approx(8.0, abs=0.01)
        assert score >= SegmentEnricher.HIGH_VALUE_THRESHOLD

    def test_maximum_score_capped_at_10(self, enricher: SegmentEnricher) -> None:
        """Score is capped at 10.0 even when theoretical max exceeds it."""
        segment = make_segment(
            classifier_confidence=1.0,  # +3.0
            distinct_metric_count=10,  # +2.0 (capped)
            contains_temporal_trend=True,  # +1.0
            contains_cohort_breakdown=True,  # +1.5 + 0.5 combo
            contains_definition_flag=True,  # +1.5 (enhanced)
            image_count=10,  # +1.5 (capped)
            extra_metadata={
                "contains_retention_keywords": True,  # +1.0
                "contains_usage_keywords": True,  # +0.5
                "contains_saas_indicator": True,  # +0.5
            },
        )
        score = enricher._compute_richness_score(segment)
        assert score == 10.0

    def test_minimum_score_is_zero(self, enricher: SegmentEnricher) -> None:
        """Minimum score is 0.0 (all zeros)."""
        segment = make_segment(
            classifier_confidence=0.0,
            distinct_metric_count=0,
            contains_temporal_trend=False,
            contains_cohort_breakdown=False,
            contains_definition_flag=False,
            image_count=0,
        )
        score = enricher._compute_richness_score(segment)
        assert score == 0.0


# =============================================================================
# Keyword Detection Tests (8+ tests)
# =============================================================================


class TestRetentionKeywordDetection:
    """Test _detect_retention_keywords() method."""

    def test_net_dollar_retention_detected(self, enricher: SegmentEnricher) -> None:
        """'Net Dollar Retention Rate was 143%' triggers retention."""
        segment = make_segment(
            raw_text="Net Dollar Retention Rate was 143% for the year."
        )
        assert enricher._detect_retention_keywords(segment) is True

    def test_ndrr_acronym_detected(self, enricher: SegmentEnricher) -> None:
        """'Our NDRR exceeded 130%' triggers retention."""
        segment = make_segment(raw_text="Our NDRR exceeded 130% last quarter.")
        assert enricher._detect_retention_keywords(segment) is True

    def test_nrr_acronym_detected(self, enricher: SegmentEnricher) -> None:
        """'NRR of 143%' triggers retention."""
        segment = make_segment(raw_text="We achieved NRR of 143%.")
        assert enricher._detect_retention_keywords(segment) is True

    def test_gross_retention_rate_detected(self, enricher: SegmentEnricher) -> None:
        """'gross retention rate' triggers retention."""
        segment = make_segment(
            raw_text="Our gross retention rate remains strong at 95%."
        )
        assert enricher._detect_retention_keywords(segment) is True

    def test_dollar_based_retention_detected(self, enricher: SegmentEnricher) -> None:
        """'dollar-based retention' triggers retention."""
        segment = make_segment(
            raw_text="Dollar-based retention exceeded expectations."
        )
        assert enricher._detect_retention_keywords(segment) is True

    def test_customer_retention_not_detected(self, enricher: SegmentEnricher) -> None:
        """'customer retention' is too generic - not detected."""
        segment = make_segment(
            raw_text="We focus on customer retention initiatives."
        )
        # "customer retention" doesn't match NRR/NDRR/gross retention rate patterns
        assert enricher._detect_retention_keywords(segment) is False

    def test_empty_text_returns_false(self, enricher: SegmentEnricher) -> None:
        """Empty text returns False."""
        segment = make_segment(raw_text="")
        assert enricher._detect_retention_keywords(segment) is False

    def test_none_text_returns_false(self, enricher: SegmentEnricher) -> None:
        """None text returns False."""
        segment = SourceSegment(
            filing_id=1, segment_type="paragraph", raw_text=None
        )
        assert enricher._detect_retention_keywords(segment) is False


class TestUsageKeywordDetection:
    """Test _detect_usage_keywords() method."""

    def test_daily_active_users_detected(self, enricher: SegmentEnricher) -> None:
        """'10 million daily active users' triggers usage."""
        segment = make_segment(raw_text="We reached 10 million daily active users.")
        assert enricher._detect_usage_keywords(segment) is True

    def test_dau_acronym_detected(self, enricher: SegmentEnricher) -> None:
        """'DAU increased 50%' triggers usage."""
        segment = make_segment(raw_text="DAU increased 50% year over year.")
        assert enricher._detect_usage_keywords(segment) is True

    def test_monthly_active_users_detected(self, enricher: SegmentEnricher) -> None:
        """'monthly active users grew' triggers usage."""
        segment = make_segment(raw_text="Monthly active users grew to 50 million.")
        assert enricher._detect_usage_keywords(segment) is True

    def test_mau_acronym_detected(self, enricher: SegmentEnricher) -> None:
        """'MAU' triggers usage."""
        segment = make_segment(raw_text="Our MAU reached 100 million users.")
        assert enricher._detect_usage_keywords(segment) is True

    def test_weekly_active_users_detected(self, enricher: SegmentEnricher) -> None:
        """'weekly active users' triggers usage."""
        segment = make_segment(raw_text="We track weekly active users carefully.")
        assert enricher._detect_usage_keywords(segment) is True

    def test_wau_acronym_detected(self, enricher: SegmentEnricher) -> None:
        """'WAU' triggers usage."""
        segment = make_segment(raw_text="WAU grew by 25% this quarter.")
        assert enricher._detect_usage_keywords(segment) is True

    def test_active_customers_not_detected(self, enricher: SegmentEnricher) -> None:
        """'active customers' is not 'active users' - not detected."""
        segment = make_segment(raw_text="We have 1000 active customers.")
        assert enricher._detect_usage_keywords(segment) is False

    def test_numeric_active_users_detected(self, enricher: SegmentEnricher) -> None:
        """'5 million active users' triggers usage."""
        segment = make_segment(raw_text="We have 5 million active users worldwide.")
        assert enricher._detect_usage_keywords(segment) is True

    def test_empty_text_returns_false(self, enricher: SegmentEnricher) -> None:
        """Empty text returns False."""
        segment = make_segment(raw_text="")
        assert enricher._detect_usage_keywords(segment) is False


# =============================================================================
# Regression Tests (3+ tests)
# =============================================================================


class TestRegressionScenarios:
    """Ensure existing behavior is preserved."""

    def test_farfetch_style_segment_scores_above_7(
        self, enricher: SegmentEnricher
    ) -> None:
        """Farfetch-style high-confidence segment with temporal still scores >= 7.0."""
        # Simulates Farfetch top segment characteristics
        segment = make_segment(
            raw_text="Revenue grew from $500M in 2017 to $1B in 2018, representing 100% growth.",
            classifier_confidence=1.0,
            distinct_metric_count=4,
            contains_temporal_trend=True,
            contains_definition_flag=True,
        )
        # Manually set extra_metadata for enricher simulation
        segment.extra_metadata = {}
        score = enricher._compute_richness_score(segment)
        # 3.0 + 2.0 + 1.0 + 1.5 = 7.5
        assert score >= 7.0

    def test_basic_segment_without_special_flags(
        self, enricher: SegmentEnricher
    ) -> None:
        """Basic segment without special flags scores as expected."""
        segment = make_segment(
            classifier_confidence=0.2,
            distinct_metric_count=0,
            contains_temporal_trend=False,
            contains_cohort_breakdown=False,
            contains_definition_flag=True,
        )
        score = enricher._compute_richness_score(segment)
        # 0.6 + 1.0 = 1.6
        assert score == pytest.approx(1.6, abs=0.01)

    def test_image_bonus_unchanged(self, enricher: SegmentEnricher) -> None:
        """Image bonus still works as expected (+0.5 per image, capped at 1.5)."""
        segment = make_segment(
            classifier_confidence=0,
            image_count=2,
        )
        score = enricher._compute_richness_score(segment)
        assert score == pytest.approx(1.0, abs=0.01)  # 2 * 0.5 = 1.0


# =============================================================================
# Real S-1 Scenarios (3+ tests)
# =============================================================================


class TestRealS1Scenarios:
    """Test against realistic S-1 disclosure patterns."""

    def test_slack_nrr_segment_scores_above_7(
        self, enricher: SegmentEnricher
    ) -> None:
        """Slack NRR segment (143% retention language) should score >= 7.0."""
        segment = make_segment(
            raw_text="Our Net Dollar Retention Rate was 143% for fiscal year 2019, "
            "compared to 152% in 2018.",
            classifier_confidence=0.85,
            distinct_metric_count=4,
            contains_temporal_trend=True,
            contains_cohort_breakdown=True,  # Now detected by GI-4
            contains_definition_flag=True,
            extra_metadata={"contains_retention_keywords": True},
        )
        score = enricher._compute_richness_score(segment)
        # 2.55 + 2.0 + 1.0 + 1.5 + 1.5 + 0.5 + 1.0 = 10.05 -> capped to 10.0
        assert score >= 7.0

    def test_slack_dau_segment_scores_above_4_5(
        self, enricher: SegmentEnricher
    ) -> None:
        """Slack DAU segment should score >= 4.5."""
        segment = make_segment(
            raw_text="We define a daily active user, or DAU, as a user who reads or "
            "posts a message during a calendar day. We had 10 million DAU as of "
            "January 31, 2019.",
            classifier_confidence=0.7,
            distinct_metric_count=2,
            contains_temporal_trend=False,
            contains_definition_flag=True,
            extra_metadata={"contains_usage_keywords": True},
        )
        score = enricher._compute_richness_score(segment)
        # 2.1 + 1.0 + 1.5 (enhanced def) + 0.5 = 5.1
        assert score >= 4.5

    def test_slack_cohort_nrr_temporal_scores_above_8(
        self, enricher: SegmentEnricher
    ) -> None:
        """Slack cohort + NRR + temporal combined should score >= 8.0."""
        segment = make_segment(
            raw_text="Net Dollar Retention Rate was 171% for the fiscal 2017 cohort, "
            "decreasing to 152% in 2018 and 143% in 2019.",
            classifier_confidence=0.95,
            distinct_metric_count=4,
            contains_temporal_trend=True,
            contains_cohort_breakdown=True,
            contains_definition_flag=False,
            extra_metadata={"contains_retention_keywords": True},
        )
        score = enricher._compute_richness_score(segment)
        # 2.85 + 2.0 + 1.0 + 1.5 + 0.5 (combo) + 1.0 = 8.85
        assert score >= 8.0
        assert score >= SegmentEnricher.HIGH_VALUE_THRESHOLD


# =============================================================================
# Edge Case Tests (4+ tests)
# =============================================================================


class TestEdgeCases:
    """Test edge cases in detection and scoring."""

    def test_empty_segment_text(self, enricher: SegmentEnricher) -> None:
        """Empty text segments don't trigger keyword bonuses."""
        segment = make_segment(raw_text="")
        assert enricher._detect_retention_keywords(segment) is False
        assert enricher._detect_usage_keywords(segment) is False

    def test_multiple_retention_keywords_not_stacked(
        self, enricher: SegmentEnricher
    ) -> None:
        """Multiple retention keywords in same segment still only +1.0."""
        segment = make_segment(
            raw_text="Our Net Dollar Retention Rate (NRR) was 143%. NDRR exceeded "
            "130% for the gross retention rate cohort.",
            classifier_confidence=0,
            extra_metadata={"contains_retention_keywords": True},
        )
        score = enricher._compute_richness_score(segment)
        assert score == pytest.approx(1.0, abs=0.01)  # Only +1.0, not +3.0

    def test_overlapping_patterns(self, enricher: SegmentEnricher) -> None:
        """Overlapping patterns (e.g., 'net dollar retention rate') match once."""
        segment = make_segment(
            raw_text="net dollar retention rate of 143%"
        )
        # Should match, but only count once
        assert enricher._detect_retention_keywords(segment) is True

    def test_high_confidence_all_bonuses_caps_at_10(
        self, enricher: SegmentEnricher
    ) -> None:
        """Very high confidence (1.0) + all bonuses still caps at 10.0."""
        segment = make_segment(
            classifier_confidence=1.0,
            distinct_metric_count=10,
            contains_temporal_trend=True,
            contains_cohort_breakdown=True,
            contains_definition_flag=True,
            image_count=10,
            extra_metadata={
                "contains_retention_keywords": True,
                "contains_usage_keywords": True,
                "contains_saas_indicator": True,
            },
        )
        score = enricher._compute_richness_score(segment)
        assert score == 10.0

    def test_none_extra_metadata_handled(self, enricher: SegmentEnricher) -> None:
        """None extra_metadata doesn't cause errors."""
        segment = make_segment(
            classifier_confidence=0.5,
            extra_metadata=None,
        )
        score = enricher._compute_richness_score(segment)
        assert score == pytest.approx(1.5, abs=0.01)  # Just confidence

    def test_missing_metadata_keys_handled(self, enricher: SegmentEnricher) -> None:
        """Missing keys in extra_metadata are treated as False."""
        segment = make_segment(
            classifier_confidence=0,
            extra_metadata={"some_other_key": True},
        )
        score = enricher._compute_richness_score(segment)
        assert score == 0.0


# =============================================================================
# Integration with _enrich_segment Tests (3+ tests)
# =============================================================================


class TestEnrichSegmentIntegration:
    """Test that _enrich_segment properly populates extra_metadata."""

    def test_retention_keywords_populated_in_metadata(
        self, enricher: SegmentEnricher
    ) -> None:
        """_enrich_segment populates contains_retention_keywords in extra_metadata."""
        segment = SourceSegment(
            filing_id=1,
            segment_type="paragraph",
            raw_text="Net Dollar Retention Rate was 143%.",
            raw_html="<p>Net Dollar Retention Rate was 143%.</p>",
            classifier_confidence=0.9,
            sequence_index=1,
        )
        enricher._enrich_segment(segment)
        assert segment.extra_metadata is not None
        assert segment.extra_metadata.get("contains_retention_keywords") is True

    def test_usage_keywords_populated_in_metadata(
        self, enricher: SegmentEnricher
    ) -> None:
        """_enrich_segment populates contains_usage_keywords in extra_metadata."""
        segment = SourceSegment(
            filing_id=1,
            segment_type="paragraph",
            raw_text="We had 10 million daily active users.",
            raw_html="<p>We had 10 million daily active users.</p>",
            classifier_confidence=0.9,
            sequence_index=1,
        )
        enricher._enrich_segment(segment)
        assert segment.extra_metadata is not None
        assert segment.extra_metadata.get("contains_usage_keywords") is True

    def test_full_enrichment_computes_richness_correctly(
        self, enricher: SegmentEnricher
    ) -> None:
        """Full enrichment flow computes richness score with new bonuses."""
        segment = SourceSegment(
            filing_id=1,
            segment_type="paragraph",
            raw_text="Our Net Dollar Retention Rate was 143% as of fiscal year 2019, "
            "compared to 152% in fiscal year 2018. We define DAU as users who "
            "send at least one message per day.",
            raw_html="<p>Our Net Dollar Retention Rate was 143%...</p>",
            classifier_confidence=0.9,
            candidate_metric_ids=["cm_ndr", "cm_dau"],
            sequence_index=1,
        )
        enricher._enrich_segment(segment)

        # Check metadata was populated
        assert segment.extra_metadata is not None
        assert segment.extra_metadata.get("contains_retention_keywords") is True
        # Note: temporal should be detected (2019 vs 2018)
        assert segment.contains_temporal_trend is True

        # Check richness score includes retention bonus
        assert segment.richness_score is not None
        assert segment.richness_score >= 5.0  # Should be significant with all bonuses


# =============================================================================
# HIGH_VALUE_THRESHOLD Constant Test (1 test)
# =============================================================================


class TestThresholdConstants:
    """Test threshold constants are correctly defined."""

    def test_high_value_threshold_is_8(self) -> None:
        """HIGH_VALUE_THRESHOLD is 8.0."""
        assert SegmentEnricher.HIGH_VALUE_THRESHOLD == 8.0

    def test_goldmine_threshold_lowered(self) -> None:
        """GOLDMINE_THRESHOLD is 5.5 (GR-1: lowered from 6.0)."""
        assert SegmentEnricher.GOLDMINE_THRESHOLD == 5.5


# =============================================================================
# Configurable Formula Weights Tests (GR-11)
# =============================================================================


class TestFormulaWeightsDefaults:
    """Test FormulaWeights dataclass defaults and factory methods."""

    def test_default_weights_match_production_values(self) -> None:
        """FormulaWeights.default() returns expected production values."""
        from src.extraction.enricher_config import FormulaWeights

        weights = FormulaWeights.default()

        # Base multipliers
        assert weights.confidence_multiplier == 3.0
        assert weights.metric_count_multiplier == 0.5
        assert weights.metric_count_cap == 2.0
        assert weights.image_multiplier == 0.5
        assert weights.image_cap == 1.5

        # Boolean flag bonuses
        assert weights.temporal_trend_bonus == 1.0
        assert weights.cohort_breakdown_bonus == 1.5
        assert weights.temporal_cohort_combo_bonus == 0.5
        assert weights.retention_keyword_bonus == 1.0
        assert weights.saas_indicator_bonus == 0.5
        assert weights.engagement_keyword_bonus == 0.5
        assert weights.conversion_keyword_bonus == 0.5

        # Definition tiers
        assert weights.definition_high_value_bonus == 2.0
        assert weights.definition_with_context_bonus == 1.5
        assert weights.definition_basic_bonus == 1.0

        # Usage tiers
        assert weights.usage_with_count_bonus == 1.0
        assert weights.usage_with_context_bonus == 0.75
        assert weights.usage_basic_bonus == 0.5

        # Platform tiers
        assert weights.platform_with_count_bonus == 1.0
        assert weights.platform_with_context_bonus == 0.75
        assert weights.platform_basic_bonus == 0.5

        # High-value metrics
        assert weights.high_value_per_metric == 0.5
        assert weights.high_value_cap == 1.5

        # Score boundaries
        assert weights.score_cap == 10.0
        assert weights.goldmine_threshold == 5.5

    def test_enricher_uses_defaults_when_no_weights_passed(self) -> None:
        """SegmentEnricher() with no args uses FormulaWeights.default()."""
        from src.extraction.enricher_config import FormulaWeights

        enricher = SegmentEnricher()
        default_weights = FormulaWeights.default()

        assert enricher.weights.confidence_multiplier == default_weights.confidence_multiplier
        assert enricher.weights.usage_with_count_bonus == default_weights.usage_with_count_bonus

    def test_enricher_accepts_custom_weights(self) -> None:
        """SegmentEnricher accepts custom FormulaWeights."""
        from src.extraction.enricher_config import FormulaWeights

        custom_weights = FormulaWeights(usage_with_count_bonus=2.0)
        enricher = SegmentEnricher(weights=custom_weights)

        assert enricher.weights.usage_with_count_bonus == 2.0
        # Other weights should still be defaults
        assert enricher.weights.confidence_multiplier == 3.0


class TestCustomWeightsModifyScores:
    """Test that custom weights produce different scores."""

    def test_higher_confidence_multiplier_increases_score(self) -> None:
        """Higher confidence_multiplier produces higher scores."""
        from src.extraction.enricher_config import FormulaWeights

        default_enricher = SegmentEnricher()
        custom_enricher = SegmentEnricher(
            weights=FormulaWeights(confidence_multiplier=5.0)
        )

        segment = make_segment(classifier_confidence=0.5)

        default_score = default_enricher._compute_richness_score(segment)
        custom_score = custom_enricher._compute_richness_score(segment)

        # Default: 0.5 * 3.0 = 1.5
        assert default_score == pytest.approx(1.5, abs=0.01)
        # Custom: 0.5 * 5.0 = 2.5
        assert custom_score == pytest.approx(2.5, abs=0.01)

    def test_zero_bonus_disables_component(self) -> None:
        """Setting a bonus to 0.0 disables that component."""
        from src.extraction.enricher_config import FormulaWeights

        # Enricher with temporal bonus disabled
        custom_enricher = SegmentEnricher(
            weights=FormulaWeights(temporal_trend_bonus=0.0)
        )

        segment = make_segment(
            classifier_confidence=0,
            contains_temporal_trend=True,
        )

        score = custom_enricher._compute_richness_score(segment)
        assert score == 0.0  # No temporal bonus applied

    def test_custom_usage_bonus_affects_score(self) -> None:
        """Custom usage bonus values affect final score."""
        from src.extraction.enricher_config import FormulaWeights

        custom_enricher = SegmentEnricher(
            weights=FormulaWeights(usage_with_count_bonus=3.0)
        )

        segment = make_segment(
            classifier_confidence=0,
            extra_metadata={"contains_usage_with_count": True},
        )

        score = custom_enricher._compute_richness_score(segment)
        assert score == pytest.approx(3.0, abs=0.01)

    def test_custom_score_cap_limits_maximum(self) -> None:
        """Custom score_cap limits the maximum score."""
        from src.extraction.enricher_config import FormulaWeights

        # Lower the cap to 5.0
        custom_enricher = SegmentEnricher(
            weights=FormulaWeights(score_cap=5.0)
        )

        # Segment that would normally score > 5
        segment = make_segment(
            classifier_confidence=1.0,  # +3.0
            contains_temporal_trend=True,  # +1.0
            contains_cohort_breakdown=True,  # +1.5
        )

        score = custom_enricher._compute_richness_score(segment)
        # Would be 5.5 but capped at 5.0
        assert score == 5.0


class TestBackwardCompatibility:
    """Test that default weights produce identical scores to original implementation."""

    def test_basic_segment_score_unchanged(self) -> None:
        """Basic segment produces same score as before GR-11."""
        enricher = SegmentEnricher()

        segment = make_segment(
            classifier_confidence=0.5,
            distinct_metric_count=2,
        )

        score = enricher._compute_richness_score(segment)
        # 0.5 * 3.0 + min(2 * 0.5, 2.0) = 1.5 + 1.0 = 2.5
        assert score == pytest.approx(2.5, abs=0.01)

    def test_goldmine_segment_score_unchanged(self) -> None:
        """Goldmine segment produces same score as before GR-11."""
        enricher = SegmentEnricher()

        segment = make_segment(
            classifier_confidence=0.8,
            distinct_metric_count=3,
            contains_temporal_trend=True,
            contains_cohort_breakdown=True,
            contains_definition_flag=True,
        )

        score = enricher._compute_richness_score(segment)
        # 0.8 * 3.0 = 2.4 (confidence)
        # min(3 * 0.5, 2.0) = 1.5 (metrics)
        # +1.0 (temporal)
        # +1.5 (cohort)
        # +0.5 (temporal+cohort combo)
        # +1.5 (definition with 3 metrics)
        # = 2.4 + 1.5 + 1.0 + 1.5 + 0.5 + 1.5 = 8.4
        assert score == pytest.approx(8.4, abs=0.01)


class TestFormulaWeightsValidation:
    """Test FormulaWeights validation and immutability."""

    def test_dataclass_is_frozen(self) -> None:
        """FormulaWeights is immutable (frozen dataclass)."""
        from src.extraction.enricher_config import FormulaWeights

        weights = FormulaWeights.default()

        with pytest.raises(Exception):  # FrozenInstanceError
            weights.confidence_multiplier = 5.0  # type: ignore

    def test_negative_values_raise_error(self) -> None:
        """Negative weight values raise ValueError."""
        from src.extraction.enricher_config import FormulaWeights

        with pytest.raises(ValueError):
            FormulaWeights(confidence_multiplier=-1.0)

    def test_high_precision_preset(self) -> None:
        """FormulaWeights.high_precision() returns precision-tuned weights."""
        from src.extraction.enricher_config import FormulaWeights

        weights = FormulaWeights.high_precision()

        # Precision preset reduces basic keyword bonuses
        assert weights.usage_basic_bonus == 0.25
        assert weights.platform_basic_bonus == 0.25

    def test_high_recall_preset(self) -> None:
        """FormulaWeights.high_recall() returns recall-tuned weights."""
        from src.extraction.enricher_config import FormulaWeights

        weights = FormulaWeights.high_recall()

        # Recall preset increases keyword bonuses
        assert weights.usage_basic_bonus == 0.75
        assert weights.goldmine_threshold == 5.0
