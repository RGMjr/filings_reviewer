"""
Unit tests for high-value metric detection in SegmentEnricher (GI-7).

Tests the _count_high_value_metrics() method and its integration into
the richness score formula. High-value metrics include NRR, LTV/CAC,
retention rates, and cohort metrics.
"""

import pytest

from src.extraction.models import SourceSegment
from src.extraction.segment_enricher import SegmentEnricher


@pytest.fixture
def enricher() -> SegmentEnricher:
    """Create a SegmentEnricher instance for testing."""
    return SegmentEnricher()


def make_segment(
    candidate_metric_ids: list[str] | None = None,
    raw_text: str = "Sample text",
    classifier_confidence: float = 0.5,
    distinct_metric_count: int | None = None,
    contains_temporal_trend: bool = False,
    contains_cohort_breakdown: bool = False,
    contains_definition_flag: bool = False,
    image_count: int = 0,
) -> SourceSegment:
    """Create a SourceSegment for testing with specified metrics."""
    if distinct_metric_count is None and candidate_metric_ids:
        distinct_metric_count = len(set(candidate_metric_ids))
    elif distinct_metric_count is None:
        distinct_metric_count = 0

    return SourceSegment(
        filing_id=1,
        segment_type="paragraph",
        sequence_index=0,
        raw_text=raw_text,
        raw_html=f"<p>{raw_text}</p>",
        classifier_confidence=classifier_confidence,
        distinct_metric_count=distinct_metric_count,
        candidate_metric_ids=candidate_metric_ids if candidate_metric_ids else [],
        contains_temporal_trend=contains_temporal_trend,
        contains_cohort_breakdown=contains_cohort_breakdown,
        contains_definition_flag=contains_definition_flag,
        image_count=image_count,
    )


class TestHighValueMetricDetection:
    """Tests for _count_high_value_metrics() method."""

    def test_single_nrr_metric(self, enricher: SegmentEnricher) -> None:
        """Segment with cm_net_revenue_retention should count as 1."""
        segment = make_segment(candidate_metric_ids=["cm_net_revenue_retention"])
        assert enricher._count_high_value_metrics(segment) == 1

    def test_two_unit_economics_metrics(self, enricher: SegmentEnricher) -> None:
        """Segment with LTV and CAC should count as 2."""
        segment = make_segment(
            candidate_metric_ids=[
                "cm_ltv_to_cac_ratio",
                "cm_customer_acquisition_cost",
            ]
        )
        assert enricher._count_high_value_metrics(segment) == 2

    def test_non_high_value_metric(self, enricher: SegmentEnricher) -> None:
        """Segment with only regular metrics should count as 0."""
        segment = make_segment(candidate_metric_ids=["cm_active_customers_total"])
        assert enricher._count_high_value_metrics(segment) == 0

    def test_mixed_high_and_regular_metrics(self, enricher: SegmentEnricher) -> None:
        """Segment with 2 high-value + 3 regular metrics should count as 2."""
        segment = make_segment(
            candidate_metric_ids=[
                "cm_net_revenue_retention",  # high-value
                "cm_ltv_to_cac_ratio",  # high-value
                "cm_active_customers_total",  # regular
                "cm_arr",  # regular
                "cm_mrr",  # regular
            ]
        )
        assert enricher._count_high_value_metrics(segment) == 2

    def test_none_candidate_metric_ids(self, enricher: SegmentEnricher) -> None:
        """Segment with None candidate_metric_ids should return 0."""
        segment = make_segment(candidate_metric_ids=None)
        assert enricher._count_high_value_metrics(segment) == 0

    def test_empty_candidate_metric_ids(self, enricher: SegmentEnricher) -> None:
        """Segment with empty candidate_metric_ids list should return 0."""
        segment = make_segment(candidate_metric_ids=[])
        assert enricher._count_high_value_metrics(segment) == 0

    def test_duplicate_metric_ids_counted_once(self, enricher: SegmentEnricher) -> None:
        """Duplicate metric IDs should be deduplicated (count unique only)."""
        segment = make_segment(
            candidate_metric_ids=[
                "cm_net_revenue_retention",
                "cm_net_revenue_retention",
                "cm_net_revenue_retention",
            ]
        )
        assert enricher._count_high_value_metrics(segment) == 1

    def test_all_high_value_metrics(self, enricher: SegmentEnricher) -> None:
        """Segment with all 8 high-value metrics should count as 8."""
        segment = make_segment(
            candidate_metric_ids=[
                "cm_net_revenue_retention",
                "cm_gross_revenue_retention",
                "cm_customer_retention_rate",
                "cm_lifetime_value_per_customer",
                "cm_customer_acquisition_cost",
                "cm_ltv_to_cac_ratio",
                "cm_revenue_by_cohort",
                "cm_customers_period_end_by_tenure",
            ]
        )
        assert enricher._count_high_value_metrics(segment) == 8

    def test_cohort_metrics(self, enricher: SegmentEnricher) -> None:
        """Segment with cohort-related high-value metrics should count correctly."""
        segment = make_segment(
            candidate_metric_ids=[
                "cm_revenue_by_cohort",
                "cm_customers_period_end_by_tenure",
            ]
        )
        assert enricher._count_high_value_metrics(segment) == 2


class TestHighValueBonusCalculation:
    """Tests for high-value metric bonus in richness score."""

    def test_one_high_value_metric_adds_0_5(self, enricher: SegmentEnricher) -> None:
        """1 high-value metric should add +0.5 to richness score."""
        segment_without = make_segment(
            candidate_metric_ids=["cm_active_customers_total"],
            classifier_confidence=0.5,
        )
        segment_with = make_segment(
            candidate_metric_ids=["cm_net_revenue_retention"],
            classifier_confidence=0.5,
        )

        enricher._enrich_segment(segment_without)
        enricher._enrich_segment(segment_with)

        # Both have 1 metric (0.5 density bonus), 0.5 confidence * 3 = 1.5
        # segment_with gets additional +0.5 high-value bonus
        assert segment_with.richness_score is not None
        assert segment_without.richness_score is not None
        assert segment_with.richness_score - segment_without.richness_score == pytest.approx(0.5)

    def test_two_high_value_metrics_add_1_0(self, enricher: SegmentEnricher) -> None:
        """2 high-value metrics should add +1.0 to richness score."""
        segment = make_segment(
            candidate_metric_ids=[
                "cm_net_revenue_retention",
                "cm_ltv_to_cac_ratio",
            ],
            classifier_confidence=0.5,
        )
        enricher._enrich_segment(segment)

        # Base: 0.5 * 3 = 1.5
        # Metric density: 2 * 0.5 = 1.0
        # High-value: 2 * 0.5 = 1.0
        expected = 1.5 + 1.0 + 1.0
        assert segment.richness_score == pytest.approx(expected)

    def test_three_or_more_high_value_metrics_capped_at_1_5(
        self, enricher: SegmentEnricher
    ) -> None:
        """3+ high-value metrics should be capped at +1.5 bonus."""
        segment = make_segment(
            candidate_metric_ids=[
                "cm_net_revenue_retention",
                "cm_ltv_to_cac_ratio",
                "cm_customer_acquisition_cost",
                "cm_lifetime_value_per_customer",
            ],
            classifier_confidence=0.5,
        )
        enricher._enrich_segment(segment)

        # Base: 0.5 * 3 = 1.5
        # Metric density: 4 * 0.5 = 2.0 (capped)
        # High-value: 4 * 0.5 = 2.0 -> capped at 1.5
        expected = 1.5 + 2.0 + 1.5
        assert segment.richness_score == pytest.approx(expected)

    def test_zero_high_value_metrics_no_bonus(self, enricher: SegmentEnricher) -> None:
        """0 high-value metrics should add +0 bonus."""
        segment = make_segment(
            candidate_metric_ids=["cm_active_customers_total", "cm_arr"],
            classifier_confidence=0.5,
        )
        enricher._enrich_segment(segment)

        # Base: 0.5 * 3 = 1.5
        # Metric density: 2 * 0.5 = 1.0
        # High-value: 0
        expected = 1.5 + 1.0
        assert segment.richness_score == pytest.approx(expected)


class TestRetentionKeywordDetection:
    """Tests for _detect_retention_keywords() method (GI-6)."""

    def test_net_dollar_retention_phrase(self, enricher: SegmentEnricher) -> None:
        """Text with 'Net Dollar Retention Rate' should return True."""
        segment = make_segment(raw_text="Our Net Dollar Retention Rate was 143%")
        assert enricher._detect_retention_keywords(segment.raw_text) is True

    def test_ndrr_acronym(self, enricher: SegmentEnricher) -> None:
        """Text with 'NDRR' acronym should return True."""
        segment = make_segment(raw_text="Our NDRR was 143% for the period")
        assert enricher._detect_retention_keywords(segment.raw_text) is True

    def test_no_retention_keywords(self, enricher: SegmentEnricher) -> None:
        """Text without retention keywords should return False."""
        segment = make_segment(raw_text="Customer growth increased 20%")
        assert enricher._detect_retention_keywords(segment.raw_text) is False


class TestUsageKeywordDetection:
    """Tests for _detect_usage_keywords() method (GI-6)."""

    def test_daily_active_users_phrase(self, enricher: SegmentEnricher) -> None:
        """Text with 'daily active users' should return True."""
        segment = make_segment(raw_text="We have 10 million daily active users")
        assert enricher._detect_usage_keywords(segment.raw_text) is True

    def test_mau_acronym(self, enricher: SegmentEnricher) -> None:
        """Text with 'MAU' acronym should return True."""
        segment = make_segment(raw_text="MAU increased 20% year-over-year")
        assert enricher._detect_usage_keywords(segment.raw_text) is True

    def test_no_usage_keywords(self, enricher: SegmentEnricher) -> None:
        """Text without usage keywords should return False."""
        segment = make_segment(raw_text="Total users reached 5 million")
        assert enricher._detect_usage_keywords(segment.raw_text) is False


class TestFormulaIntegration:
    """Tests for richness formula with high-value metrics and keyword bonuses."""

    def test_high_value_metric_and_retention_keyword_both_applied(
        self, enricher: SegmentEnricher
    ) -> None:
        """Segment with high-value metric AND retention keyword gets both bonuses."""
        segment = make_segment(
            candidate_metric_ids=["cm_net_revenue_retention"],
            raw_text="Net Dollar Retention Rate was 143%",
            classifier_confidence=0.5,
        )
        enricher._enrich_segment(segment)

        # Base: 0.5 * 3 = 1.5
        # Metric density: 1 * 0.5 = 0.5
        # Retention keyword: +1.0
        # High-value metric: +0.5
        # Note: cohort patterns may also match due to "Net Dollar Retention"
        assert segment.richness_score is not None
        assert segment.richness_score >= 3.5  # At minimum

    def test_full_score_reaching_near_10(self, enricher: SegmentEnricher) -> None:
        """Segment with all features can reach near 10.0 (capped)."""
        segment = make_segment(
            candidate_metric_ids=[
                "cm_net_revenue_retention",
                "cm_ltv_to_cac_ratio",
                "cm_customer_retention_rate",
                "cm_revenue_by_cohort",
            ],
            raw_text="Net Dollar Retention Rate increased to 143% in fiscal year 2023 "
            "compared to prior year. Our LTV/CAC ratio improved to 4.5x with "
            "10 million daily active users.",
            classifier_confidence=1.0,
            contains_temporal_trend=True,
            contains_cohort_breakdown=True,
            contains_definition_flag=True,
            image_count=3,
        )
        enricher._enrich_segment(segment)

        assert segment.richness_score is not None
        assert segment.richness_score == 10.0  # Capped at maximum

    def test_regression_without_high_value_metrics(
        self, enricher: SegmentEnricher
    ) -> None:
        """Segments without high-value metrics still score correctly (regression)."""
        segment = make_segment(
            candidate_metric_ids=["cm_arr", "cm_mrr", "cm_active_customers_total"],
            raw_text="ARR grew 50% year-over-year to $100 million",
            classifier_confidence=0.8,
        )
        enricher._enrich_segment(segment)

        # Base: 0.8 * 3 = 2.4
        # Metric density: 3 * 0.5 = 1.5
        # Temporal trend (year-over-year): +1.0
        # SaaS indicator (ARR grew X%): +0.5
        # High-value: 0 (none of these are in HIGH_VALUE_METRICS)
        assert segment.richness_score is not None
        assert segment.richness_score >= 4.0  # Should score well even without high-value


class TestHighValueMetricsFrozenset:
    """Tests for HIGH_VALUE_METRICS class attribute."""

    def test_high_value_metrics_is_frozenset(self) -> None:
        """HIGH_VALUE_METRICS should be a frozenset for O(1) lookups."""
        assert isinstance(SegmentEnricher.HIGH_VALUE_METRICS, frozenset)

    def test_high_value_metrics_contains_expected_ids(self) -> None:
        """HIGH_VALUE_METRICS should contain the expected metric IDs."""
        expected = {
            "cm_net_revenue_retention",
            "cm_gross_revenue_retention",
            "cm_customer_retention_rate",
            "cm_lifetime_value_per_customer",
            "cm_customer_acquisition_cost",
            "cm_ltv_to_cac_ratio",
            "cm_revenue_by_cohort",
            "cm_customers_period_end_by_tenure",
        }
        assert SegmentEnricher.HIGH_VALUE_METRICS == expected

    def test_high_value_metrics_count(self) -> None:
        """HIGH_VALUE_METRICS should contain 8 metrics."""
        assert len(SegmentEnricher.HIGH_VALUE_METRICS) == 8
