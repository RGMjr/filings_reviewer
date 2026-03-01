"""
Unit tests for SegmentEnricher cohort detection patterns (GI-4).

Tests the expanded COHORT_PATTERNS that detect cohort analysis language
in S-1 filings, including:
- Net Dollar Retention Rate (NRR/NDRR)
- Fiscal year cohorts
- ARR/MRR cohort associations
- Enterprise customer terminology
- Expansion and retention metrics
"""

import pytest

from src.extraction.models import SourceSegment
from src.extraction.segment_enricher import SegmentEnricher


@pytest.fixture
def enricher() -> SegmentEnricher:
    """Create a SegmentEnricher instance."""
    return SegmentEnricher()


def _make_segment(text: str) -> SourceSegment:
    """Create a minimal segment for testing cohort detection."""
    return SourceSegment(
        filing_id=1,
        segment_type="paragraph",
        raw_text=text,
        raw_html=f"<p>{text}</p>",
        candidate_metric_ids=[],
    )


# =============================================================================
# Retention Metric Patterns (7 tests)
# =============================================================================


class TestRetentionMetricPatterns:
    """Tests for Net Dollar Retention and related patterns."""

    def test_net_dollar_retention_rate_with_percent(self, enricher: SegmentEnricher) -> None:
        """Matches 'Net Dollar Retention Rate was 143%'."""
        segment = _make_segment("Our Net Dollar Retention Rate was 143% as of January 31, 2019.")
        result = enricher._detect_cohort_breakdowns(
            segment.raw_text, segment.candidate_metric_ids, None
        )
        assert result is True

    def test_nrr_abbreviation(self, enricher: SegmentEnricher) -> None:
        """Matches standalone NRR abbreviation."""
        segment = _make_segment("Our NRR exceeded 130% in the last quarter.")
        result = enricher._detect_cohort_breakdowns(
            segment.raw_text, segment.candidate_metric_ids, None
        )
        assert result is True

    def test_ndrr_abbreviation(self, enricher: SegmentEnricher) -> None:
        """Matches NDRR abbreviation."""
        segment = _make_segment("NDRR improved to 125% year-over-year.")
        result = enricher._detect_cohort_breakdowns(
            segment.raw_text, segment.candidate_metric_ids, None
        )
        assert result is True

    def test_dollar_based_net_retention(self, enricher: SegmentEnricher) -> None:
        """Matches 'dollar-based net retention rate'."""
        segment = _make_segment("Our dollar-based net retention rate was 115%.")
        result = enricher._detect_cohort_breakdowns(
            segment.raw_text, segment.candidate_metric_ids, None
        )
        assert result is True

    def test_dollar_based_expansion(self, enricher: SegmentEnricher) -> None:
        """Matches 'dollar-based expansion rate'."""
        segment = _make_segment("The dollar based expansion rate exceeded expectations.")
        result = enricher._detect_cohort_breakdowns(
            segment.raw_text, segment.candidate_metric_ids, None
        )
        assert result is True

    def test_gross_retention_rate(self, enricher: SegmentEnricher) -> None:
        """Matches 'gross retention rate of 95%'."""
        segment = _make_segment(
            "Our gross retention rate of 95% demonstrates customer satisfaction."
        )
        result = enricher._detect_cohort_breakdowns(
            segment.raw_text, segment.candidate_metric_ids, None
        )
        assert result is True

    def test_retention_rate_alone_is_not_cohort(self, enricher: SegmentEnricher) -> None:
        """'customer retention is important' without metrics is too generic."""
        segment = _make_segment("Customer retention is important to our business strategy.")
        result = enricher._detect_cohort_breakdowns(
            segment.raw_text, segment.candidate_metric_ids, None
        )
        # This should still match "net retention" / "gross retention" but not generic
        # Since we check for "retention" standalone without qualifiers, this is expected
        assert result is False


# =============================================================================
# Fiscal Year Cohort Patterns (6 tests)
# =============================================================================


class TestFiscalYearCohortPatterns:
    """Tests for fiscal year and year-based cohort references."""

    def test_fiscal_year_cohort(self, enricher: SegmentEnricher) -> None:
        """Matches 'fiscal year 2015 cohort'."""
        segment = _make_segment(
            "For example, the fiscal year 2015 cohort represents all Paid Customers "
            "that purchased their first subscription from us during the fiscal year ended January 31, 2015."
        )
        result = enricher._detect_cohort_breakdowns(
            segment.raw_text, segment.candidate_metric_ids, None
        )
        assert result is True

    def test_the_year_cohort(self, enricher: SegmentEnricher) -> None:
        """Matches 'the 2019 cohort represents'."""
        segment = _make_segment(
            "The 2019 cohort represents customers acquired in that fiscal year."
        )
        result = enricher._detect_cohort_breakdowns(
            segment.raw_text, segment.candidate_metric_ids, None
        )
        assert result is True

    def test_fy_year_cohort(self, enricher: SegmentEnricher) -> None:
        """Matches 'FY2020 cohort'."""
        segment = _make_segment("The FY2020 cohort showed strong growth in the first year.")
        result = enricher._detect_cohort_breakdowns(
            segment.raw_text, segment.candidate_metric_ids, None
        )
        assert result is True

    def test_quarter_year_cohort(self, enricher: SegmentEnricher) -> None:
        """Matches 'Q4 2020 cohort'."""
        segment = _make_segment("The Q4 2020 cohort had the highest average order value.")
        result = enricher._detect_cohort_breakdowns(
            segment.raw_text, segment.candidate_metric_ids, None
        )
        assert result is True

    def test_cohort_acquired_in_year(self, enricher: SegmentEnricher) -> None:
        """Matches 'cohort acquired in 2018'."""
        segment = _make_segment("The cohort acquired in 2018 showed 150% retention.")
        result = enricher._detect_cohort_breakdowns(
            segment.raw_text, segment.candidate_metric_ids, None
        )
        assert result is True

    def test_fiscal_year_without_cohort_is_not_match(self, enricher: SegmentEnricher) -> None:
        """'fiscal year 2020 revenue' without cohort reference is not a match."""
        segment = _make_segment("Our fiscal year 2020 revenue increased by 25%.")
        result = enricher._detect_cohort_breakdowns(
            segment.raw_text, segment.candidate_metric_ids, None
        )
        assert result is False


# =============================================================================
# ARR Cohort Patterns (5 tests)
# =============================================================================


class TestArrCohortPatterns:
    """Tests for ARR/MRR cohort associations."""

    def test_arr_of_each_cohort(self, enricher: SegmentEnricher) -> None:
        """Matches 'ARR of each cohort'."""
        segment = _make_segment(
            "The chart below illustrates the annual recurring revenue, or ARR, of each cohort "
            "over the periods presented."
        )
        result = enricher._detect_cohort_breakdowns(
            segment.raw_text, segment.candidate_metric_ids, None
        )
        assert result is True

    def test_annual_recurring_revenue_by_cohort(self, enricher: SegmentEnricher) -> None:
        """Matches 'annual recurring revenue...cohort'."""
        segment = _make_segment("Annual recurring revenue by cohort shows strong net expansion.")
        result = enricher._detect_cohort_breakdowns(
            segment.raw_text, segment.candidate_metric_ids, None
        )
        assert result is True

    def test_mrr_for_each_cohort(self, enricher: SegmentEnricher) -> None:
        """Matches 'MRR for each cohort'."""
        segment = _make_segment("We track MRR for each cohort on a monthly basis.")
        result = enricher._detect_cohort_breakdowns(
            segment.raw_text, segment.candidate_metric_ids, None
        )
        assert result is True

    def test_arr_grew_without_cohort_is_not_match(self, enricher: SegmentEnricher) -> None:
        """'ARR grew 50%' without cohort reference is not a match."""
        segment = _make_segment("Our ARR grew 50% year-over-year to $100 million.")
        result = enricher._detect_cohort_breakdowns(
            segment.raw_text, segment.candidate_metric_ids, None
        )
        assert result is False

    def test_arr_growth_metric(self, enricher: SegmentEnricher) -> None:
        """Matches 'ARR growth' as expansion metric."""
        segment = _make_segment("ARR growth was driven by enterprise customers.")
        result = enricher._detect_cohort_breakdowns(
            segment.raw_text, segment.candidate_metric_ids, None
        )
        assert result is True


# =============================================================================
# Enterprise Customer Patterns (4 tests)
# =============================================================================


class TestEnterpriseCustomerPatterns:
    """Tests for enterprise customer terminology (Paid Customer proper noun)."""

    def test_paid_customer_base_expansion(self, enricher: SegmentEnricher) -> None:
        """Matches 'Paid Customer base expansion' (proper noun)."""
        segment = _make_segment("Paid Customer base expansion drove revenue growth.")
        result = enricher._detect_cohort_breakdowns(
            segment.raw_text, segment.candidate_metric_ids, None
        )
        assert result is True

    def test_paid_customers_proper_noun(self, enricher: SegmentEnricher) -> None:
        """Matches 'Paid Customers' as defined term."""
        segment = _make_segment(
            "We had 575 Paid Customers >$100,000 of ARR as of January 31, 2019."
        )
        result = enricher._detect_cohort_breakdowns(
            segment.raw_text, segment.candidate_metric_ids, None
        )
        assert result is True

    def test_lowercase_paid_customers_is_not_match(self, enricher: SegmentEnricher) -> None:
        """'paid customers increased' (lowercase) should not match proper noun pattern."""
        segment = _make_segment("Our paid customers increased by 20%.")
        # This won't match the "Paid Customer" proper noun pattern (case-sensitive)
        # but may match other patterns - check it doesn't match if no other patterns apply
        result = enricher._detect_cohort_breakdowns(
            segment.raw_text, segment.candidate_metric_ids, None
        )
        # Generic "paid customers" lowercase shouldn't be a cohort signal
        assert result is False

    def test_expansion_within_paid_customer_base(self, enricher: SegmentEnricher) -> None:
        """Matches 'expansion within our Paid Customer base'."""
        segment = _make_segment("We measure the rate of expansion within our Paid Customer base.")
        result = enricher._detect_cohort_breakdowns(
            segment.raw_text, segment.candidate_metric_ids, None
        )
        assert result is True


# =============================================================================
# Negative Cases - Prevent False Positives (5 tests)
# =============================================================================


class TestNegativeCases:
    """Tests to ensure patterns don't match too broadly."""

    def test_generic_business_text_no_match(self, enricher: SegmentEnricher) -> None:
        """Generic business text without cohort indicators returns False."""
        segment = _make_segment(
            "Our company provides software solutions to enterprise customers worldwide."
        )
        result = enricher._detect_cohort_breakdowns(
            segment.raw_text, segment.candidate_metric_ids, None
        )
        assert result is False

    def test_retained_market_position_no_match(self, enricher: SegmentEnricher) -> None:
        """'The company retained its market position' is not cohort language."""
        segment = _make_segment("The company retained its market position in the industry.")
        result = enricher._detect_cohort_breakdowns(
            segment.raw_text, segment.candidate_metric_ids, None
        )
        assert result is False

    def test_revenue_growth_alone_no_match(self, enricher: SegmentEnricher) -> None:
        """'revenue growth' alone is not a cohort signal."""
        segment = _make_segment("Revenue growth was strong in the fourth quarter.")
        result = enricher._detect_cohort_breakdowns(
            segment.raw_text, segment.candidate_metric_ids, None
        )
        assert result is False

    def test_arr_in_unrelated_context_no_match(self, enricher: SegmentEnricher) -> None:
        """'ARR' in an unrelated context (no cohort, growth, etc.)."""
        segment = _make_segment(
            "Our subscription arrangements generally have annual contractual terms."
        )
        result = enricher._detect_cohort_breakdowns(
            segment.raw_text, segment.candidate_metric_ids, None
        )
        assert result is False

    def test_fiscal_year_financial_reporting_no_match(self, enricher: SegmentEnricher) -> None:
        """'fiscal year ended January 31' without cohort is not a match."""
        segment = _make_segment(
            "For the fiscal year ended January 31, 2019, we recorded net losses of $138.9 million."
        )
        result = enricher._detect_cohort_breakdowns(
            segment.raw_text, segment.candidate_metric_ids, None
        )
        assert result is False


# =============================================================================
# Real S-1 Snippets from GI-1 Analysis (5 tests)
# =============================================================================


class TestRealS1Snippets:
    """Tests using actual text from S-1 filings (GI-1 analysis)."""

    def test_slack_arr_cohort_chart(self, enricher: SegmentEnricher) -> None:
        """Slack S-1 cohort chart description."""
        segment = _make_segment(
            "The chart below illustrates the annual recurring revenue, or ARR, of each cohort "
            "over the periods presented, with each cohort representing Paid Customers who made "
            "their first purchase from us in a given fiscal year."
        )
        result = enricher._detect_cohort_breakdowns(
            segment.raw_text, segment.candidate_metric_ids, None
        )
        assert result is True

    def test_slack_fiscal_year_cohort_definition(self, enricher: SegmentEnricher) -> None:
        """Slack S-1 cohort definition."""
        segment = _make_segment(
            "For example, the fiscal year 2015 cohort represents all Paid Customers that "
            "purchased their first subscription from us during the fiscal year ended January 31, 2015."
        )
        result = enricher._detect_cohort_breakdowns(
            segment.raw_text, segment.candidate_metric_ids, None
        )
        assert result is True

    def test_slack_net_dollar_retention_metric(self, enricher: SegmentEnricher) -> None:
        """Slack S-1 NDRR metric disclosure."""
        segment = _make_segment(
            "We measure the rate of expansion within our Paid Customer base, both sales-driven "
            "and through organic growth, by Net Dollar Retention Rate."
        )
        result = enricher._detect_cohort_breakdowns(
            segment.raw_text, segment.candidate_metric_ids, None
        )
        assert result is True

    def test_slack_ndrr_143_percent(self, enricher: SegmentEnricher) -> None:
        """Slack S-1 143% NDRR disclosure."""
        segment = _make_segment("Our Net Dollar Retention Rate was 143% as of January 31, 2019.")
        result = enricher._detect_cohort_breakdowns(
            segment.raw_text, segment.candidate_metric_ids, None
        )
        assert result is True

    def test_farfetch_ltv_cac_cohort(self, enricher: SegmentEnricher) -> None:
        """Farfetch S-1 LTV/CAC cohort disclosure."""
        segment = _make_segment(
            "We deploy our demand generation expense across a variety of channels, such as search "
            "engine marketing, search engine optimization, display advertising and affiliate marketing, "
            "and we monitor on a real-time basis the aggregate LTV of each cohort and the return on CAC "
            "across each channel."
        )
        result = enricher._detect_cohort_breakdowns(
            segment.raw_text, segment.candidate_metric_ids, None
        )
        assert result is True


# =============================================================================
# Edge Cases and Variations (6 tests)
# =============================================================================


class TestEdgeCasesAndVariations:
    """Tests for edge cases: case variations, spacing, punctuation."""

    def test_mixed_case_net_dollar_retention(self, enricher: SegmentEnricher) -> None:
        """Case insensitive: 'Net dollar Retention Rate'."""
        segment = _make_segment("Net dollar Retention Rate improved this quarter.")
        result = enricher._detect_cohort_breakdowns(
            segment.raw_text, segment.candidate_metric_ids, None
        )
        assert result is True

    def test_all_caps_ndr(self, enricher: SegmentEnricher) -> None:
        """All caps: 'NET DOLLAR RETENTION'."""
        segment = _make_segment("NET DOLLAR RETENTION exceeded 140%.")
        result = enricher._detect_cohort_breakdowns(
            segment.raw_text, segment.candidate_metric_ids, None
        )
        assert result is True

    def test_pattern_at_start_of_string(self, enricher: SegmentEnricher) -> None:
        """Pattern at start of string."""
        segment = _make_segment("NRR is our key metric for customer expansion.")
        result = enricher._detect_cohort_breakdowns(
            segment.raw_text, segment.candidate_metric_ids, None
        )
        assert result is True

    def test_pattern_at_end_of_string(self, enricher: SegmentEnricher) -> None:
        """Pattern at end of string."""
        segment = _make_segment("Our primary KPI is NRR.")
        result = enricher._detect_cohort_breakdowns(
            segment.raw_text, segment.candidate_metric_ids, None
        )
        assert result is True

    def test_pattern_with_punctuation(self, enricher: SegmentEnricher) -> None:
        """Pattern with surrounding punctuation."""
        segment = _make_segment("(Net Dollar Retention Rate: 143%)")
        result = enricher._detect_cohort_breakdowns(
            segment.raw_text, segment.candidate_metric_ids, None
        )
        assert result is True

    def test_very_long_text_with_pattern(self, enricher: SegmentEnricher) -> None:
        """Pattern in middle of long text."""
        prefix = "Lorem ipsum dolor sit amet. " * 50
        suffix = " Consectetur adipiscing elit." * 50
        segment = _make_segment(f"{prefix}Our Net Dollar Retention Rate was 143%.{suffix}")
        result = enricher._detect_cohort_breakdowns(
            segment.raw_text, segment.candidate_metric_ids, None
        )
        assert result is True


# =============================================================================
# Expansion and Growth Language (4 tests)
# =============================================================================


class TestExpansionLanguage:
    """Tests for expansion and growth terminology."""

    def test_expansion_within_customer_base(self, enricher: SegmentEnricher) -> None:
        """Matches 'expansion within...customer base'."""
        segment = _make_segment("Expansion within our customer base drove growth.")
        result = enricher._detect_cohort_breakdowns(
            segment.raw_text, segment.candidate_metric_ids, None
        )
        assert result is True

    def test_land_and_expand(self, enricher: SegmentEnricher) -> None:
        """Matches 'land and expand' strategy."""
        segment = _make_segment("We employ a land and expand sales strategy.")
        result = enricher._detect_cohort_breakdowns(
            segment.raw_text, segment.candidate_metric_ids, None
        )
        assert result is True

    def test_expansion_revenue(self, enricher: SegmentEnricher) -> None:
        """Matches 'expansion revenue'."""
        segment = _make_segment("Expansion revenue contributed 30% of total revenue.")
        result = enricher._detect_cohort_breakdowns(
            segment.raw_text, segment.candidate_metric_ids, None
        )
        assert result is True

    def test_churn_rate_metric(self, enricher: SegmentEnricher) -> None:
        """Matches 'churn rate' as retention inverse."""
        segment = _make_segment("Our churn rate decreased to 5% annually.")
        result = enricher._detect_cohort_breakdowns(
            segment.raw_text, segment.candidate_metric_ids, None
        )
        assert result is True


# =============================================================================
# LTV/CAC Patterns (3 tests)
# =============================================================================


class TestLtvCacPatterns:
    """Tests for LTV/CAC ratio patterns."""

    def test_ltv_cac_ratio_slash(self, enricher: SegmentEnricher) -> None:
        """Matches 'LTV/CAC' ratio."""
        segment = _make_segment("Our LTV/CAC ratio exceeds 3x.")
        result = enricher._detect_cohort_breakdowns(
            segment.raw_text, segment.candidate_metric_ids, None
        )
        assert result is True

    def test_ltv_cac_ratio_colon(self, enricher: SegmentEnricher) -> None:
        """Matches 'LTV:CAC' ratio."""
        segment = _make_segment("LTV:CAC improved to 4:1.")
        result = enricher._detect_cohort_breakdowns(
            segment.raw_text, segment.candidate_metric_ids, None
        )
        assert result is True

    def test_lifetime_value_cac(self, enricher: SegmentEnricher) -> None:
        """Matches 'lifetime value / CAC'."""
        segment = _make_segment("Customer lifetime value relative to CAC is strong.")
        result = enricher._detect_cohort_breakdowns(
            segment.raw_text, segment.candidate_metric_ids, None
        )
        assert result is True


# =============================================================================
# Edge Cases for Coverage (5 tests)
# =============================================================================


class TestCoverageEdgeCases:
    """Tests for edge cases to ensure high coverage of _detect_cohort_breakdowns."""

    def test_none_raw_text(self, enricher: SegmentEnricher) -> None:
        """Returns False when raw_text is None."""
        segment = SourceSegment(
            filing_id=1,
            segment_type="paragraph",
            raw_text=None,
            candidate_metric_ids=[],
        )
        result = enricher._detect_cohort_breakdowns(
            segment.raw_text, segment.candidate_metric_ids, None
        )
        assert result is False

    def test_empty_raw_text(self, enricher: SegmentEnricher) -> None:
        """Returns False when raw_text is empty string."""
        segment = SourceSegment(
            filing_id=1,
            segment_type="paragraph",
            raw_text="",
            candidate_metric_ids=[],
        )
        result = enricher._detect_cohort_breakdowns(
            segment.raw_text, segment.candidate_metric_ids, None
        )
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
        result = enricher._detect_cohort_breakdowns(
            segment.raw_text, segment.candidate_metric_ids, None
        )
        assert result is False

    def test_multiple_cohort_metric_ids_triggers_detection(self, enricher: SegmentEnricher) -> None:
        """Returns True when 2+ metric IDs contain 'cohort' or 'tenure'."""
        segment = SourceSegment(
            filing_id=1,
            segment_type="paragraph",
            raw_text="Some generic text without cohort patterns.",
            candidate_metric_ids=[
                "cm_customer_cohort_analysis",
                "cm_customer_tenure_months",
            ],
        )
        result = enricher._detect_cohort_breakdowns(
            segment.raw_text, segment.candidate_metric_ids, None
        )
        assert result is True

    def test_single_cohort_metric_id_does_not_trigger(self, enricher: SegmentEnricher) -> None:
        """Returns False when only 1 metric ID contains 'cohort'."""
        segment = SourceSegment(
            filing_id=1,
            segment_type="paragraph",
            raw_text="Some generic text without cohort patterns.",
            candidate_metric_ids=["cm_customer_cohort_analysis", "cm_revenue_total"],
        )
        result = enricher._detect_cohort_breakdowns(
            segment.raw_text, segment.candidate_metric_ids, None
        )
        assert result is False


# =============================================================================
# Pattern Count Verification (1 test)
# =============================================================================


class TestPatternCount:
    """Verify the expected number of patterns."""

    def test_cohort_patterns_count(self, enricher: SegmentEnricher) -> None:
        """Verify we have added 19+ new patterns (28+ total)."""
        # Original: 9 patterns
        # GI-4 added: 19 patterns (9 P1 + 6 P2 + 4 P3)
        # Total should be 28
        assert len(enricher.COHORT_PATTERNS) >= 28, (
            f"Expected at least 28 patterns, got {len(enricher.COHORT_PATTERNS)}"
        )
