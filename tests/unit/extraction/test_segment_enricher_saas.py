"""
Unit tests for SegmentEnricher SaaS-specific detection patterns (GI-5).

Tests the SAAS_PATTERNS that detect SaaS company disclosure terminology
in S-1 filings, including:
- ARR/MRR recurring revenue metrics
- Calculated billings and deferred revenue
- Net expansion rate indicators
- Enterprise customer thresholds (>$100K ARR)
- LTV/CAC unit economics patterns
"""

import pytest

from src.extraction.models import SourceSegment
from src.extraction.segment_enricher import SegmentEnricher


@pytest.fixture
def enricher() -> SegmentEnricher:
    """Create a SegmentEnricher instance."""
    return SegmentEnricher()


def _make_segment(text: str) -> SourceSegment:
    """Create a minimal segment for testing SaaS detection."""
    return SourceSegment(
        filing_id=1,
        segment_type="paragraph",
        raw_text=text,
        raw_html=f"<p>{text}</p>",
        candidate_metric_ids=[],
    )


# =============================================================================
# ARR/MRR Patterns (7 tests)
# =============================================================================


class TestArrMrrPatterns:
    """Tests for ARR/MRR recurring revenue patterns."""

    def test_arr_grew_percentage(self, enricher: SegmentEnricher) -> None:
        """Matches 'Our ARR grew 50% year over year'."""
        segment = _make_segment("Our ARR grew 50% year over year.")
        result = enricher._detect_saas_indicators(segment)
        assert result is True

    def test_arr_of_dollar_amount(self, enricher: SegmentEnricher) -> None:
        """Matches 'ARR of $100 million'."""
        segment = _make_segment("ARR of $100 million as of January 31, 2019.")
        result = enricher._detect_saas_indicators(segment)
        assert result is True

    def test_annual_recurring_revenue_spelled_out(
        self, enricher: SegmentEnricher
    ) -> None:
        """Matches 'annual recurring revenue increased'."""
        segment = _make_segment("Our annual recurring revenue increased by 40%.")
        result = enricher._detect_saas_indicators(segment)
        assert result is True

    def test_mrr_growth(self, enricher: SegmentEnricher) -> None:
        """Matches 'MRR of $8 million'."""
        segment = _make_segment("MRR of $8 million was achieved in Q4.")
        result = enricher._detect_saas_indicators(segment)
        assert result is True

    def test_monthly_recurring_revenue_spelled_out(
        self, enricher: SegmentEnricher
    ) -> None:
        """Matches 'monthly recurring revenue'."""
        segment = _make_segment("Monthly recurring revenue accelerated in Q2.")
        result = enricher._detect_saas_indicators(segment)
        assert result is True

    def test_generic_revenue_no_match(self, enricher: SegmentEnricher) -> None:
        """'Total revenue was $500 million' (no ARR/MRR) should NOT match."""
        segment = _make_segment("Total revenue was $500 million in fiscal 2019.")
        result = enricher._detect_saas_indicators(segment)
        assert result is False

    def test_arr_with_decimal_percentage(self, enricher: SegmentEnricher) -> None:
        """Matches 'ARR increased by 42.5%'."""
        segment = _make_segment("ARR increased by 42.5% compared to last year.")
        result = enricher._detect_saas_indicators(segment)
        assert result is True


# =============================================================================
# Billings Patterns (4 tests)
# =============================================================================


class TestBillingsPatterns:
    """Tests for calculated billings and deferred revenue patterns."""

    def test_calculated_billings(self, enricher: SegmentEnricher) -> None:
        """Matches 'Calculated billings were $200 million'."""
        segment = _make_segment("Calculated billings were $200 million in Q4.")
        result = enricher._detect_saas_indicators(segment)
        assert result is True

    def test_billings_grew(self, enricher: SegmentEnricher) -> None:
        """Matches 'billings grew 40%'."""
        segment = _make_segment("Our billings grew 40% year-over-year.")
        result = enricher._detect_saas_indicators(segment)
        assert result is True

    def test_deferred_revenue_grew(self, enricher: SegmentEnricher) -> None:
        """Matches 'deferred revenue grew by 25%'."""
        segment = _make_segment("Deferred revenue grew by 25% during the period.")
        result = enricher._detect_saas_indicators(segment)
        assert result is True

    def test_bill_customers_no_match(self, enricher: SegmentEnricher) -> None:
        """'We bill customers monthly' (verb form) should NOT match."""
        segment = _make_segment("We bill customers on a monthly basis.")
        result = enricher._detect_saas_indicators(segment)
        assert result is False


# =============================================================================
# Net Expansion Patterns (4 tests)
# =============================================================================


class TestNetExpansionPatterns:
    """Tests for net expansion rate and related patterns."""

    def test_net_expansion_rate(self, enricher: SegmentEnricher) -> None:
        """Matches 'net expansion rate of 130%'."""
        segment = _make_segment("Our net expansion rate of 130% reflects strong growth.")
        result = enricher._detect_saas_indicators(segment)
        assert result is True

    def test_net_revenue_expansion_rate(self, enricher: SegmentEnricher) -> None:
        """Matches 'net revenue expansion rate'."""
        segment = _make_segment("Net revenue expansion rate exceeded expectations.")
        result = enricher._detect_saas_indicators(segment)
        assert result is True

    def test_international_expansion_no_match(self, enricher: SegmentEnricher) -> None:
        """'international expansion' (geographic) should NOT match."""
        segment = _make_segment("We plan to invest in international expansion.")
        result = enricher._detect_saas_indicators(segment)
        assert result is False

    def test_expansion_without_net_no_match(self, enricher: SegmentEnricher) -> None:
        """'expansion' alone should NOT match (too generic)."""
        segment = _make_segment("Expansion of our team continued in Q3.")
        result = enricher._detect_saas_indicators(segment)
        assert result is False


# =============================================================================
# Enterprise Customer Patterns (5 tests)
# =============================================================================


class TestEnterpriseCustomerPatterns:
    """Tests for enterprise customer threshold patterns."""

    def test_paid_customers_threshold_greater_than(
        self, enricher: SegmentEnricher
    ) -> None:
        """Matches 'Paid Customers > $100,000 of ARR'."""
        segment = _make_segment(
            "We had 575 Paid Customers > $100,000 of ARR as of January."
        )
        result = enricher._detect_saas_indicators(segment)
        assert result is True

    def test_customers_arr_over_100k(self, enricher: SegmentEnricher) -> None:
        """Matches 'customers with ARR over $100K'."""
        segment = _make_segment("The number of customers with ARR over $100K doubled.")
        result = enricher._detect_saas_indicators(segment)
        assert result is True

    def test_enterprise_customers_count(self, enricher: SegmentEnricher) -> None:
        """Matches '575 enterprise customers'."""
        segment = _make_segment("We serve 575 enterprise customers worldwide.")
        result = enricher._detect_saas_indicators(segment)
        assert result is True

    def test_exceeding_threshold(self, enricher: SegmentEnricher) -> None:
        """Matches 'exceeding $50,000 of ARR'."""
        segment = _make_segment("Customers exceeding $50,000 of ARR grew 60%.")
        result = enricher._detect_saas_indicators(segment)
        assert result is True

    def test_generic_paid_customers_no_match(self, enricher: SegmentEnricher) -> None:
        """'We had 88,000 paid customers' (lowercase, no threshold) should NOT match."""
        segment = _make_segment("We had 88,000 paid customers in 2019.")
        result = enricher._detect_saas_indicators(segment)
        assert result is False


# =============================================================================
# LTV/CAC Patterns (4 tests)
# =============================================================================


class TestLtvCacPatterns:
    """Tests for LTV/CAC unit economics patterns."""

    def test_customer_acquisition_cost(self, enricher: SegmentEnricher) -> None:
        """Matches 'customer acquisition cost decreased'."""
        segment = _make_segment("Customer acquisition cost decreased by 15%.")
        result = enricher._detect_saas_indicators(segment)
        assert result is True

    def test_cac_standalone_metric(self, enricher: SegmentEnricher) -> None:
        """Matches 'CAC of $X'."""
        segment = _make_segment("CAC of $50 per customer was achieved.")
        result = enricher._detect_saas_indicators(segment)
        assert result is True

    def test_payback_period(self, enricher: SegmentEnricher) -> None:
        """Matches 'payback period of 12 months'."""
        segment = _make_segment("Our payback period is approximately 12 months.")
        result = enricher._detect_saas_indicators(segment)
        assert result is True

    def test_high_lifetime_value(self, enricher: SegmentEnricher) -> None:
        """Matches 'high lifetime value'."""
        segment = _make_segment("We believe customers have a high lifetime value.")
        result = enricher._detect_saas_indicators(segment)
        assert result is True


# =============================================================================
# Negative Cases - Prevent False Positives (4 tests)
# =============================================================================


class TestNegativeCases:
    """Tests to ensure patterns don't match too broadly."""

    def test_generic_business_text_no_match(self, enricher: SegmentEnricher) -> None:
        """Generic business text without SaaS indicators returns False."""
        segment = _make_segment(
            "Our customers are satisfied with our products and services."
        )
        result = enricher._detect_saas_indicators(segment)
        assert result is False

    def test_revenue_grew_no_match(self, enricher: SegmentEnricher) -> None:
        """'Revenue grew 50%' (no ARR/MRR) should NOT match."""
        segment = _make_segment("Revenue grew 50% in the fourth quarter.")
        result = enricher._detect_saas_indicators(segment)
        assert result is False

    def test_subscription_revenue_no_match(self, enricher: SegmentEnricher) -> None:
        """'subscription revenue' without ARR/MRR should NOT match."""
        segment = _make_segment("Subscription revenue increased this year.")
        result = enricher._detect_saas_indicators(segment)
        assert result is False

    def test_arr_as_word_part_no_match(self, enricher: SegmentEnricher) -> None:
        """'ARRANGE' should NOT match (ARR as part of larger word)."""
        segment = _make_segment("We will arrange for delivery next week.")
        result = enricher._detect_saas_indicators(segment)
        assert result is False


# =============================================================================
# Real S-1 Snippets from GI-1 (4 tests)
# =============================================================================


class TestRealS1Snippets:
    """Tests using actual text from S-1 filings (GI-1 analysis)."""

    def test_slack_paid_customers_arr_threshold(
        self, enricher: SegmentEnricher
    ) -> None:
        """Slack S-1: Paid Customers > $100,000 of ARR."""
        segment = _make_segment(
            "We measure the number of Paid Customers > $100,000 of annual recurring "
            "revenue, or ARR, as a gauge of adoption within and expansion into "
            "large enterprises."
        )
        result = enricher._detect_saas_indicators(segment)
        assert result is True

    def test_slack_575_paid_customers_arr(self, enricher: SegmentEnricher) -> None:
        """Slack S-1: 575 Paid Customers with ARR threshold."""
        segment = _make_segment(
            "We had 575 Paid Customers >$100,000 of ARR as of January 31, 2019, "
            "which accounted for approximately 40% of our revenue in fiscal year 2019."
        )
        result = enricher._detect_saas_indicators(segment)
        assert result is True

    def test_slack_high_lifetime_value(self, enricher: SegmentEnricher) -> None:
        """Slack S-1: high lifetime value reference."""
        segment = _make_segment(
            "We believe that all of these factors will contribute to a high lifetime "
            "value of an organization on Slack."
        )
        result = enricher._detect_saas_indicators(segment)
        assert result is True

    def test_farfetch_ltv_cac_monitoring(self, enricher: SegmentEnricher) -> None:
        """Farfetch S-1: LTV/CAC monitoring with payback period."""
        segment = _make_segment(
            "In determining how successful our consumer acquisition and retention "
            "strategy is, we closely monitor the initial Customer Acquisition Cost, "
            "the Lifetime Value of a Consumer, and payback period metrics."
        )
        result = enricher._detect_saas_indicators(segment)
        assert result is True


# =============================================================================
# Edge Cases and Variations (7 tests)
# =============================================================================


class TestEdgeCasesAndVariations:
    """Tests for edge cases: case variations, boundaries, empty segments."""

    def test_lowercase_arr_with_dollar(self, enricher: SegmentEnricher) -> None:
        """Mixed case: 'arr of $100 million' (lowercase arr)."""
        segment = _make_segment("Our arr of $100 million exceeded targets.")
        result = enricher._detect_saas_indicators(segment)
        assert result is True

    def test_pattern_at_start_of_string(self, enricher: SegmentEnricher) -> None:
        """Pattern at start of string."""
        segment = _make_segment("ARR of $50M demonstrates strong growth.")
        result = enricher._detect_saas_indicators(segment)
        assert result is True

    def test_pattern_at_end_of_string(self, enricher: SegmentEnricher) -> None:
        """Pattern at end of string."""
        segment = _make_segment("Our key metric is calculated billings.")
        result = enricher._detect_saas_indicators(segment)
        assert result is True

    def test_very_long_text_with_pattern(self, enricher: SegmentEnricher) -> None:
        """Pattern in middle of long text."""
        prefix = "Lorem ipsum dolor sit amet. " * 50
        suffix = " Consectetur adipiscing elit." * 50
        segment = _make_segment(
            f"{prefix}Our ARR of $100 million grew 50%.{suffix}"
        )
        result = enricher._detect_saas_indicators(segment)
        assert result is True

    def test_none_raw_text(self, enricher: SegmentEnricher) -> None:
        """Returns False when raw_text is None."""
        segment = SourceSegment(
            filing_id=1,
            segment_type="paragraph",
            raw_text=None,
            candidate_metric_ids=[],
        )
        result = enricher._detect_saas_indicators(segment)
        assert result is False

    def test_empty_raw_text(self, enricher: SegmentEnricher) -> None:
        """Returns False when raw_text is empty string."""
        segment = SourceSegment(
            filing_id=1,
            segment_type="paragraph",
            raw_text="",
            candidate_metric_ids=[],
        )
        result = enricher._detect_saas_indicators(segment)
        assert result is False

    def test_non_string_raw_text(self, enricher: SegmentEnricher) -> None:
        """Returns False when raw_text is non-string (with warning)."""
        segment = SourceSegment(
            filing_id=1,
            segment_type="paragraph",
            raw_text=None,
            candidate_metric_ids=[],
        )
        # Set raw_text to non-string after construction
        segment.raw_text = 12345  # type: ignore[assignment]
        result = enricher._detect_saas_indicators(segment)
        assert result is False


# =============================================================================
# Richness Score Integration (3 tests)
# =============================================================================


class TestRichnessScoreIntegration:
    """Tests for SaaS indicator bonus in richness score calculation."""

    def test_saas_indicator_adds_half_point(self, enricher: SegmentEnricher) -> None:
        """SaaS indicator adds +0.5 to richness score."""
        segment = SourceSegment(
            filing_id=1,
            segment_type="paragraph",
            raw_text="Our ARR of $100 million grew significantly.",
            raw_html="<p>Our ARR of $100 million grew significantly.</p>",
            candidate_metric_ids=[],
            classifier_confidence=1.0,  # Base: 3.0 points
        )
        enricher._enrich_segment(segment)

        # With SaaS indicator: 3.0 (confidence) + 0.5 (saas) = 3.5
        assert segment.richness_score == 3.5
        assert segment.extra_metadata is not None
        assert segment.extra_metadata.get("contains_saas_indicator") is True

    def test_combined_cohort_and_saas_bonus(self, enricher: SegmentEnricher) -> None:
        """Combined cohort (+1.5) and SaaS (+0.5) bonuses stack."""
        segment = SourceSegment(
            filing_id=1,
            segment_type="paragraph",
            raw_text=(
                "Our Net Dollar Retention Rate was 143%. "
                "ARR of $100 million was achieved."
            ),
            raw_html=(
                "<p>Our Net Dollar Retention Rate was 143%. "
                "ARR of $100 million was achieved.</p>"
            ),
            candidate_metric_ids=[],
            classifier_confidence=1.0,  # Base: 3.0 points
        )
        enricher._enrich_segment(segment)

        # Expected (GI-6 calibrated):
        # 3.0 (confidence) + 1.5 (cohort) + 0.5 (saas) + 1.0 (retention keywords) = 6.0
        assert segment.richness_score == 6.0
        assert segment.contains_cohort_breakdown is True
        assert segment.extra_metadata is not None
        assert segment.extra_metadata.get("contains_saas_indicator") is True
        assert segment.extra_metadata.get("contains_retention_keywords") is True

    def test_no_saas_indicator_no_bonus(self, enricher: SegmentEnricher) -> None:
        """No SaaS indicator means no +0.5 bonus."""
        segment = SourceSegment(
            filing_id=1,
            segment_type="paragraph",
            raw_text="Our customers are happy with our services.",
            raw_html="<p>Our customers are happy with our services.</p>",
            candidate_metric_ids=[],
            classifier_confidence=1.0,  # Base: 3.0 points
        )
        enricher._enrich_segment(segment)

        # No SaaS indicator: 3.0 (confidence) only
        assert segment.richness_score == 3.0
        assert segment.extra_metadata is not None
        assert segment.extra_metadata.get("contains_saas_indicator") is False


# =============================================================================
# Pattern Count Verification (1 test)
# =============================================================================


class TestPatternCount:
    """Verify the expected number of patterns."""

    def test_saas_patterns_count(self, enricher: SegmentEnricher) -> None:
        """Verify we have at least 8 SaaS patterns (requirement: 8+)."""
        assert len(enricher.SAAS_PATTERNS) >= 8, (
            f"Expected at least 8 SaaS patterns, got {len(enricher.SAAS_PATTERNS)}"
        )

    def test_saas_patterns_are_compiled(self, enricher: SegmentEnricher) -> None:
        """Verify all patterns are compiled regex objects."""
        import re
        for pattern in enricher.SAAS_PATTERNS:
            assert isinstance(pattern, re.Pattern), (
                f"Pattern {pattern} is not a compiled regex"
            )
