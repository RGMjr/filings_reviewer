"""
Unit tests for SegmentEnricher definition bonus enhancement (GI-9).

Tests the tiered definition bonus system:
- +2.0 for definitions of high-value metrics (NRR, LTV, CAC, etc.)
- +1.5 for definitions with distinct_metric_count >= 2
- +1.0 for generic definitions

Coverage target: >= 95% for definition bonus logic.

Business rationale: GI-8 validation showed 6/12 false negatives in Slack
were definition sections scoring 3.9-5.5 (below 6.0 goldmine threshold).
The +2.0 tier pushes these critical disclosures above threshold.
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
    classifier_confidence: float = 0.0,
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
# Helper Method Tests (3 tests)
# =============================================================================


class TestHasHighValueMetric:
    """Test the _has_high_value_metric() helper method."""

    def test_returns_true_for_nrr(self, enricher: SegmentEnricher) -> None:
        """High-value metric NRR is detected."""
        segment = make_segment(
            candidate_metric_ids=["cm_net_revenue_retention"]
        )
        assert enricher._has_high_value_metric(segment) is True

    def test_returns_true_for_ltv(self, enricher: SegmentEnricher) -> None:
        """High-value metric LTV is detected."""
        segment = make_segment(
            candidate_metric_ids=["cm_lifetime_value_per_customer"]
        )
        assert enricher._has_high_value_metric(segment) is True

    def test_returns_true_for_cac(self, enricher: SegmentEnricher) -> None:
        """High-value metric CAC is detected."""
        segment = make_segment(
            candidate_metric_ids=["cm_customer_acquisition_cost"]
        )
        assert enricher._has_high_value_metric(segment) is True

    def test_returns_true_for_mixed_metrics(self, enricher: SegmentEnricher) -> None:
        """Returns True if ANY metric is high-value."""
        segment = make_segment(
            candidate_metric_ids=[
                "cm_total_customers",  # Not high-value
                "cm_net_revenue_retention",  # High-value
                "cm_revenue",  # Not high-value
            ]
        )
        assert enricher._has_high_value_metric(segment) is True

    def test_returns_false_for_non_high_value_metrics(
        self, enricher: SegmentEnricher
    ) -> None:
        """Non-high-value metrics return False."""
        segment = make_segment(
            candidate_metric_ids=["cm_total_customers", "cm_revenue"]
        )
        assert enricher._has_high_value_metric(segment) is False

    def test_returns_false_for_empty_list(self, enricher: SegmentEnricher) -> None:
        """Empty candidate_metric_ids returns False."""
        segment = make_segment(candidate_metric_ids=[])
        assert enricher._has_high_value_metric(segment) is False

    def test_returns_false_for_none(self, enricher: SegmentEnricher) -> None:
        """None candidate_metric_ids returns False."""
        segment = make_segment(candidate_metric_ids=None)
        assert enricher._has_high_value_metric(segment) is False


# =============================================================================
# High-Value Definition Bonus Tests (6 tests)
# =============================================================================


class TestHighValueDefinitionBonus:
    """Test +2.0 bonus for high-value metric definitions."""

    def test_nrr_definition_gets_2_point_bonus(
        self, enricher: SegmentEnricher
    ) -> None:
        """Definition of NRR receives +2.0 bonus."""
        segment = make_segment(
            classifier_confidence=0.0,
            contains_definition_flag=True,
            candidate_metric_ids=["cm_net_revenue_retention"],
            distinct_metric_count=1,
        )
        score = enricher._compute_richness_score(segment)
        # Base (0.0) + metric density (0.5) + definition (+2.0) + HV metric bonus (0.5) = 3.0
        assert score == pytest.approx(3.0, abs=0.01)

    def test_ltv_definition_gets_2_point_bonus(
        self, enricher: SegmentEnricher
    ) -> None:
        """Definition of LTV receives +2.0 bonus."""
        segment = make_segment(
            classifier_confidence=0.0,
            contains_definition_flag=True,
            candidate_metric_ids=["cm_lifetime_value_per_customer"],
            distinct_metric_count=1,
        )
        score = enricher._compute_richness_score(segment)
        # Base (0.0) + metric density (0.5) + definition (+2.0) + HV metric bonus (0.5) = 3.0
        assert score == pytest.approx(3.0, abs=0.01)

    def test_cac_definition_gets_2_point_bonus(
        self, enricher: SegmentEnricher
    ) -> None:
        """Definition of CAC receives +2.0 bonus."""
        segment = make_segment(
            classifier_confidence=0.0,
            contains_definition_flag=True,
            candidate_metric_ids=["cm_customer_acquisition_cost"],
            distinct_metric_count=1,
        )
        score = enricher._compute_richness_score(segment)
        # Base (0.0) + metric density (0.5) + definition (+2.0) + HV metric bonus (0.5) = 3.0
        assert score == pytest.approx(3.0, abs=0.01)

    def test_grr_definition_gets_2_point_bonus(
        self, enricher: SegmentEnricher
    ) -> None:
        """Definition of GRR receives +2.0 bonus."""
        segment = make_segment(
            classifier_confidence=0.0,
            contains_definition_flag=True,
            candidate_metric_ids=["cm_gross_revenue_retention"],
            distinct_metric_count=1,
        )
        score = enricher._compute_richness_score(segment)
        # Base (0.0) + metric density (0.5) + definition (+2.0) + HV metric bonus (0.5) = 3.0
        assert score == pytest.approx(3.0, abs=0.01)

    def test_mixed_metrics_with_one_high_value_gets_2_point_bonus(
        self, enricher: SegmentEnricher
    ) -> None:
        """Definition with mixed metrics (including one HV) gets +2.0."""
        segment = make_segment(
            classifier_confidence=0.0,
            contains_definition_flag=True,
            candidate_metric_ids=[
                "cm_total_customers",  # Not high-value
                "cm_net_revenue_retention",  # High-value
            ],
            distinct_metric_count=2,
        )
        score = enricher._compute_richness_score(segment)
        # Base (0.0) + metric density (1.0) + definition (+2.0) + HV metric bonus (0.5) = 3.5
        # Note: HV metric bonus is +0.5 for 1 high-value metric (not 2 total metrics)
        assert score == pytest.approx(3.5, abs=0.01)

    def test_non_high_value_metric_definition_falls_back(
        self, enricher: SegmentEnricher
    ) -> None:
        """Definition of non-high-value metric gets standard bonus."""
        segment = make_segment(
            classifier_confidence=0.0,
            contains_definition_flag=True,
            candidate_metric_ids=["cm_total_customers"],
            distinct_metric_count=1,
        )
        score = enricher._compute_richness_score(segment)
        # Base (0.0) + metric density (0.5) + definition (+1.0) = 1.5
        assert score == pytest.approx(1.5, abs=0.01)


# =============================================================================
# Bonus Hierarchy Tests (5 tests)
# =============================================================================


class TestBonusHierarchy:
    """Test that definition bonuses follow correct priority."""

    def test_high_value_definition_beats_multi_metric_definition(
        self, enricher: SegmentEnricher
    ) -> None:
        """HV definition (1 metric) gets +2.0, not +1.5."""
        segment = make_segment(
            classifier_confidence=0.0,
            contains_definition_flag=True,
            candidate_metric_ids=["cm_net_revenue_retention"],
            distinct_metric_count=1,  # Only 1 metric
        )
        score = enricher._compute_richness_score(segment)
        # Should get +2.0 (HV bonus), not +1.0 (single metric fallback)
        # Base (0.0) + metric density (0.5) + definition (+2.0) + HV metric (0.5) = 3.0
        assert score == pytest.approx(3.0, abs=0.01)

    def test_high_value_definition_with_multiple_metrics(
        self, enricher: SegmentEnricher
    ) -> None:
        """HV definition with multiple HV metrics still gets +2.0 (not cumulative)."""
        segment = make_segment(
            classifier_confidence=0.0,
            contains_definition_flag=True,
            candidate_metric_ids=[
                "cm_net_revenue_retention",
                "cm_gross_revenue_retention",
            ],
            distinct_metric_count=2,
        )
        score = enricher._compute_richness_score(segment)
        # Base (0.0) + metric density (1.0) + definition (+2.0) + HV metric bonus (1.0) = 4.0
        assert score == pytest.approx(4.0, abs=0.01)

    def test_multi_metric_definition_no_high_value_gets_1_5(
        self, enricher: SegmentEnricher
    ) -> None:
        """Definition with 2+ non-HV metrics gets +1.5."""
        segment = make_segment(
            classifier_confidence=0.0,
            contains_definition_flag=True,
            candidate_metric_ids=["cm_total_customers", "cm_revenue", "cm_arr"],
            distinct_metric_count=3,
        )
        score = enricher._compute_richness_score(segment)
        # Base (0.0) + metric density (1.5) + definition (+1.5) = 3.0
        assert score == pytest.approx(3.0, abs=0.01)

    def test_single_generic_metric_definition_gets_1_0(
        self, enricher: SegmentEnricher
    ) -> None:
        """Definition with 1 non-HV metric gets +1.0."""
        segment = make_segment(
            classifier_confidence=0.0,
            contains_definition_flag=True,
            candidate_metric_ids=["cm_total_customers"],
            distinct_metric_count=1,
        )
        score = enricher._compute_richness_score(segment)
        # Base (0.0) + metric density (0.5) + definition (+1.0) = 1.5
        assert score == pytest.approx(1.5, abs=0.01)

    def test_high_value_metric_without_definition_flag_no_2_0_bonus(
        self, enricher: SegmentEnricher
    ) -> None:
        """High-value metric without definition flag doesn't get +2.0."""
        segment = make_segment(
            classifier_confidence=0.0,
            contains_definition_flag=False,  # No definition
            candidate_metric_ids=["cm_net_revenue_retention"],
            distinct_metric_count=1,
        )
        score = enricher._compute_richness_score(segment)
        # Base (0.0) + metric density (0.5) + HV metric bonus (0.5) = 1.0
        # NO definition bonus
        assert score == pytest.approx(1.0, abs=0.01)


# =============================================================================
# Edge Cases (4 tests)
# =============================================================================


class TestDefinitionBonusEdgeCases:
    """Test edge cases for definition bonus logic."""

    def test_definition_with_no_candidate_metric_ids(
        self, enricher: SegmentEnricher
    ) -> None:
        """Definition flag without candidate_metric_ids gets +1.0 fallback."""
        segment = make_segment(
            classifier_confidence=0.0,
            contains_definition_flag=True,
            candidate_metric_ids=None,
            distinct_metric_count=0,
        )
        score = enricher._compute_richness_score(segment)
        # Base (0.0) + definition (+1.0) = 1.0
        assert score == pytest.approx(1.0, abs=0.01)

    def test_definition_with_empty_candidate_metric_ids(
        self, enricher: SegmentEnricher
    ) -> None:
        """Definition flag with empty list gets +1.0 fallback."""
        segment = make_segment(
            classifier_confidence=0.0,
            contains_definition_flag=True,
            candidate_metric_ids=[],
            distinct_metric_count=0,
        )
        score = enricher._compute_richness_score(segment)
        # Base (0.0) + definition (+1.0) = 1.0
        assert score == pytest.approx(1.0, abs=0.01)

    def test_no_definition_flag_no_bonus_regardless_of_metrics(
        self, enricher: SegmentEnricher
    ) -> None:
        """No definition flag = +0.0 bonus, even with high-value metrics."""
        segment = make_segment(
            classifier_confidence=0.0,
            contains_definition_flag=False,
            candidate_metric_ids=["cm_net_revenue_retention"],
            distinct_metric_count=1,
        )
        score = enricher._compute_richness_score(segment)
        # Base (0.0) + metric density (0.5) + HV metric bonus (0.5) = 1.0
        # NO definition bonus
        assert score == pytest.approx(1.0, abs=0.01)

    def test_definition_of_metric_not_in_high_value_set(
        self, enricher: SegmentEnricher
    ) -> None:
        """Metric close to but not in HIGH_VALUE_METRICS gets standard bonus."""
        segment = make_segment(
            classifier_confidence=0.0,
            contains_definition_flag=True,
            candidate_metric_ids=["cm_churn_rate"],  # Not in HIGH_VALUE_METRICS
            distinct_metric_count=1,
        )
        score = enricher._compute_richness_score(segment)
        # Base (0.0) + metric density (0.5) + definition (+1.0) = 1.5
        assert score == pytest.approx(1.5, abs=0.01)


# =============================================================================
# Integration Tests (3 tests)
# =============================================================================


class TestDefinitionBonusIntegration:
    """Test definition bonus in full richness calculations."""

    def test_full_richness_with_high_value_definition(
        self, enricher: SegmentEnricher
    ) -> None:
        """High-value definition bonus integrates correctly in full score."""
        segment = make_segment(
            classifier_confidence=0.5,
            contains_definition_flag=True,
            candidate_metric_ids=["cm_net_revenue_retention"],
            distinct_metric_count=1,
            contains_temporal_trend=True,
            contains_cohort_breakdown=False,
        )
        score = enricher._compute_richness_score(segment)
        # Base (1.5) + metric density (0.5) + temporal (1.0) + definition (+2.0) + HV metric (0.5) = 5.5
        assert score == pytest.approx(5.5, abs=0.01)

    def test_score_capped_at_10_with_high_value_definition(
        self, enricher: SegmentEnricher
    ) -> None:
        """Score stays capped at 10.0 even with +2.0 definition bonus."""
        segment = make_segment(
            classifier_confidence=1.0,  # 3.0
            contains_definition_flag=True,  # +2.0
            candidate_metric_ids=[
                "cm_net_revenue_retention",
                "cm_gross_revenue_retention",
            ],
            distinct_metric_count=4,  # 2.0 (capped)
            contains_temporal_trend=True,  # 1.0
            contains_cohort_breakdown=True,  # 1.5
            image_count=3,  # 1.5 (capped)
            extra_metadata={
                "contains_retention_keywords": True,  # 1.0
                "contains_usage_keywords": True,  # 0.5
                "contains_saas_indicator": True,  # 0.5
            },
        )
        score = enricher._compute_richness_score(segment)
        # Total would be: 3.0 + 2.0 + 1.0 + 1.5 + 2.0 + 0.5 + 1.0 + 0.5 + 1.0 + 0.5 + 1.5 = 14.5
        # But capped at 10.0
        assert score == pytest.approx(10.0, abs=0.01)

    def test_slack_dau_definition_example_improved_score(
        self, enricher: SegmentEnricher
    ) -> None:
        """Real-world example: Slack DAU definition now scores higher.

        Before GI-9: ~3.9 (below goldmine threshold)
        After GI-9: Should be higher due to +2.0 bonus (if DAU were in HIGH_VALUE_METRICS)

        Note: This test assumes DAU is NOT in HIGH_VALUE_METRICS (as of GI-7),
        so it tests the fallback behavior. If DAU is added later, update this test.
        """
        segment = make_segment(
            raw_text='Daily Active Users ("DAU") represents the number of unique users...',
            classifier_confidence=0.8,
            contains_definition_flag=True,
            candidate_metric_ids=["cm_daily_active_users"],  # Not in HIGH_VALUE_METRICS
            distinct_metric_count=1,
        )
        score = enricher._compute_richness_score(segment)
        # Base (2.4) + metric density (0.5) + definition (+1.0) = 3.9
        # (DAU is not in HIGH_VALUE_METRICS, so standard +1.0 bonus)
        assert score == pytest.approx(3.9, abs=0.01)

        # If we had a high-value metric definition with similar characteristics:
        segment_hv = make_segment(
            raw_text='Net Revenue Retention ("NRR") is calculated as...',
            classifier_confidence=0.8,
            contains_definition_flag=True,
            candidate_metric_ids=["cm_net_revenue_retention"],
            distinct_metric_count=1,
        )
        score_hv = enricher._compute_richness_score(segment_hv)
        # Base (2.4) + metric density (0.5) + definition (+2.0) + HV metric (0.5) = 5.4
        assert score_hv == pytest.approx(5.4, abs=0.01)
        # This is a significant improvement, though still below 6.0 goldmine threshold
        # Additional features (temporal trends, cohort, etc.) would push it over


# =============================================================================
# Regression Tests (2 tests)
# =============================================================================


class TestDefinitionBonusRegression:
    """Ensure existing behavior is preserved."""

    def test_no_definition_flag_behavior_unchanged(
        self, enricher: SegmentEnricher
    ) -> None:
        """Segments without definition flag work as before."""
        segment = make_segment(
            classifier_confidence=0.5,
            contains_definition_flag=False,
            candidate_metric_ids=["cm_total_customers"],
            distinct_metric_count=1,
        )
        score = enricher._compute_richness_score(segment)
        # Base (1.5) + metric density (0.5) = 2.0
        assert score == pytest.approx(2.0, abs=0.01)

    def test_multi_metric_definition_behavior_preserved(
        self, enricher: SegmentEnricher
    ) -> None:
        """Multi-metric definition (non-HV) still gets +1.5 as before."""
        segment = make_segment(
            classifier_confidence=0.5,
            contains_definition_flag=True,
            candidate_metric_ids=["cm_total_customers", "cm_revenue"],
            distinct_metric_count=2,
        )
        score = enricher._compute_richness_score(segment)
        # Base (1.5) + metric density (1.0) + definition (+1.5) = 4.0
        assert score == pytest.approx(4.0, abs=0.01)
