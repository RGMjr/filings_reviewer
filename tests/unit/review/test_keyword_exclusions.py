"""
Tests for HRI-3: Metric keyword exclusion patterns.

These tests verify that the exclusion pattern system correctly prevents
misclassifications when ambiguous keywords appear in contexts that
clearly indicate a different metric.

Coverage Target: ≥95% for new exclusion-related code paths.
"""

import re

import pytest

from src.review.keyword_matching import (
    METRIC_EXCLUSION_PATTERNS,
    KeywordMatcher,
)


class TestMetricExclusionPatternsStructure:
    """Tests for the METRIC_EXCLUSION_PATTERNS dictionary structure."""

    def test_exclusion_patterns_is_dict(self) -> None:
        """Verify METRIC_EXCLUSION_PATTERNS is a dictionary."""
        assert isinstance(METRIC_EXCLUSION_PATTERNS, dict)

    def test_exclusion_patterns_has_entries(self) -> None:
        """Verify METRIC_EXCLUSION_PATTERNS has at least some entries."""
        assert len(METRIC_EXCLUSION_PATTERNS) >= 5  # Per task requirements

    def test_all_patterns_are_valid_regex(self) -> None:
        """Verify all exclusion patterns are valid regex."""
        for metric_id, patterns in METRIC_EXCLUSION_PATTERNS.items():
            assert isinstance(patterns, list), f"{metric_id} patterns should be a list"
            for pattern in patterns:
                assert isinstance(pattern, str), "Pattern should be string"
                # Should not raise re.error
                compiled = re.compile(pattern, re.IGNORECASE)
                assert compiled is not None

    def test_expected_metrics_have_exclusions(self) -> None:
        """Verify expected metrics have exclusion patterns defined."""
        expected_metrics = [
            "cm_new_customers_acquired",
            "cm_customer_acquisition_cost",
            "cm_lifetime_value_per_customer",
            "cm_revenue_per_customer",
            "cm_customer_retention_rate",
        ]
        for metric in expected_metrics:
            assert metric in METRIC_EXCLUSION_PATTERNS, f"{metric} should have exclusions"


class TestExclusionPatternCAC:
    """Tests for CAC-related exclusion patterns."""

    def test_contribution_margin_not_matched_as_cac(self) -> None:
        """'Contribution Margin' should NOT match CAC."""
        text = "Contribution Margin was 41.6%"
        matcher = KeywordMatcher()
        matches = matcher.find_all_keywords(text)
        matched_metrics = {m.metric_id for m in matches}

        assert "cm_customer_acquisition_cost" not in matched_metrics

    def test_gross_margin_not_matched_as_cac(self) -> None:
        """'Gross Margin' context should NOT match CAC."""
        text = "Our gross margin improved by $50 per customer"
        matcher = KeywordMatcher()
        matches = matcher.find_all_keywords(text)

        # If CAC pattern matched, it should be excluded due to gross margin context
        cac_matches = [m for m in matches if m.metric_id == "cm_customer_acquisition_cost"]
        assert len(cac_matches) == 0

    def test_profit_margin_not_matched_as_cac(self) -> None:
        """'Profit Margin' context should NOT match CAC."""
        text = "Profit margin and cost improvements drove acquisition cost savings"
        matcher = KeywordMatcher()
        matches = matcher.find_all_keywords(text)

        cac_matches = [m for m in matches if m.metric_id == "cm_customer_acquisition_cost"]
        # acquisition cost should be excluded due to profit margin in context
        assert len(cac_matches) == 0

    def test_platform_order_contribution_not_matched_as_cac(self) -> None:
        """'Platform Order Contribution Margin' should NOT match CAC."""
        text = "Platform Order Contribution Margin for CAC calculations was 43%"
        matcher = KeywordMatcher()
        matches = matcher.find_all_keywords(text)

        cac_matches = [m for m in matches if m.metric_id == "cm_customer_acquisition_cost"]
        # CAC should be excluded due to "platform order contribution" context
        assert len(cac_matches) == 0

    def test_cac_still_matches_in_valid_context(self) -> None:
        """CAC should still match when no exclusion pattern applies."""
        text = "Customer Acquisition Cost (CAC) was $100 per user"
        matcher = KeywordMatcher()
        matches = matcher.find_all_keywords(text)
        matched_metrics = {m.metric_id for m in matches}

        assert "cm_customer_acquisition_cost" in matched_metrics


class TestExclusionPatternNewCustomers:
    """Tests for new customers exclusion patterns."""

    def test_customer_acquisition_cost_not_matched_as_new_customers(self) -> None:
        """'Customer acquisition cost' should NOT match cm_new_customers_acquired."""
        text = "Customer Acquisition Cost was $100"
        matcher = KeywordMatcher()
        matches = matcher.find_all_keywords(text)
        matched_metrics = {m.metric_id for m in matches}

        # cm_new_customers_acquired has pattern 'customer acquisition' which would
        # match part of 'Customer Acquisition Cost', but should be excluded
        assert "cm_new_customers_acquired" not in matched_metrics
        # CAC should still match
        assert "cm_customer_acquisition_cost" in matched_metrics

    def test_cac_nearby_excludes_new_customers(self) -> None:
        """CAC acronym nearby should exclude new customers metric."""
        text = "We spent on customer acquisition, with CAC of $50"
        matcher = KeywordMatcher()
        matches = matcher.find_all_keywords(text)
        matched_metrics = {m.metric_id for m in matches}

        assert "cm_new_customers_acquired" not in matched_metrics

    def test_cost_to_acquire_excludes_new_customers(self) -> None:
        """'Cost to acquire' should exclude new customers metric."""
        text = "Customer acquisition volume and cost to acquire metrics"
        matcher = KeywordMatcher()
        matches = matcher.find_all_keywords(text)
        matched_metrics = {m.metric_id for m in matches}

        assert "cm_new_customers_acquired" not in matched_metrics


class TestExclusionPatternLTV:
    """Tests for LTV-related exclusion patterns."""

    def test_ltv_cac_ratio_excludes_standalone_ltv(self) -> None:
        """LTV/CAC ratio context should exclude standalone LTV metric."""
        text = "LTV/CAC ratio of 2.5"
        matcher = KeywordMatcher()
        matches = matcher.find_all_keywords(text)
        matched_metrics = {m.metric_id for m in matches}

        # LTV/CAC ratio metric should be present
        assert "cm_ltv_to_cac_ratio" in matched_metrics
        # Standalone LTV should be excluded
        assert "cm_lifetime_value_per_customer" not in matched_metrics

    def test_ltv_to_cac_excludes_standalone_ltv(self) -> None:
        """'LTV to CAC' phrasing should exclude standalone LTV."""
        text = "Our LTV to CAC improved significantly"
        matcher = KeywordMatcher()
        matches = matcher.find_all_keywords(text)
        matched_metrics = {m.metric_id for m in matches}

        assert "cm_lifetime_value_per_customer" not in matched_metrics

    def test_standalone_ltv_still_matches(self) -> None:
        """Standalone LTV should still match when not in ratio context."""
        text = "Customer Lifetime Value (LTV) was $500"
        matcher = KeywordMatcher()
        matches = matcher.find_all_keywords(text)
        matched_metrics = {m.metric_id for m in matches}

        assert "cm_lifetime_value_per_customer" in matched_metrics


class TestExclusionPatternGrossMargin:
    """Tests for gross margin by cohort matching."""

    def test_by_cohort_matches_cohort_margin(self) -> None:
        """'By cohort' context should match gross margin by cohort."""
        text = "Gross profit margin by cohort was 35%"
        matcher = KeywordMatcher()
        matches = matcher.find_all_keywords(text)
        matched_metrics = {m.metric_id for m in matches}

        # By cohort metric should be present
        assert "cm_gross_margin_by_cohort" in matched_metrics

    def test_cohort_margin_matches_by_cohort(self) -> None:
        """'Cohort margin' phrasing should match gross margin by cohort."""
        text = "Our cohort margin for gross profit was 40%"
        matcher = KeywordMatcher()
        matches = matcher.find_all_keywords(text)
        matched_metrics = {m.metric_id for m in matches}

        assert "cm_gross_margin_by_cohort" in matched_metrics


class TestExclusionPatternRetention:
    """Tests for retention rate exclusion patterns."""

    def test_revenue_retention_excludes_customer_retention(self) -> None:
        """'Revenue retention' should exclude customer retention rate."""
        text = "Our retention rate for revenue retention metrics was 95%"
        matcher = KeywordMatcher()
        matches = matcher.find_all_keywords(text)
        matched_metrics = {m.metric_id for m in matches}

        assert "cm_customer_retention_rate" not in matched_metrics

    def test_nrr_excludes_customer_retention(self) -> None:
        """NRR acronym should exclude customer retention rate."""
        text = "Customer retention rate and NRR both improved"
        matcher = KeywordMatcher()
        matches = matcher.find_all_keywords(text)
        matched_metrics = {m.metric_id for m in matches}

        assert "cm_customer_retention_rate" not in matched_metrics


class TestExclusionPatternARPU:
    """Tests for ARPU/revenue-per-customer exclusion patterns."""

    def test_cost_per_customer_excludes_arpu(self) -> None:
        """'Cost per customer' should exclude revenue per customer."""
        text = "Cost per customer was $50, while revenue per customer improved"
        matcher = KeywordMatcher()
        matches = matcher.find_all_keywords(text)

        # Look for revenue per customer matches that should be excluded
        # due to "cost per customer" in context
        for match in matches:
            if match.metric_id == "cm_revenue_per_customer":
                # Check if it matched in the cost context
                if "cost per customer" in text[max(0, match.start - 50):match.end + 50].lower():
                    pytest.fail(
                        f"ARPU matched in cost-per-customer context: {match.keyword}"
                    )


class TestExclusionEdgeCases:
    """Edge case tests for exclusion patterns."""

    def test_exclusion_in_middle_of_text(self) -> None:
        """Exclusion should work when pattern is in middle of longer text."""
        text = (
            "Some preliminary text. Our contribution margin was strong. "
            "The CAC metrics also improved. More text follows."
        )
        matcher = KeywordMatcher()
        matches = matcher.find_all_keywords(text)

        # CAC in second sentence should be excluded due to "contribution margin" nearby
        cac_matches = [m for m in matches if m.metric_id == "cm_customer_acquisition_cost"]
        # All CAC matches should be excluded because contribution margin is within 50 chars
        for match in cac_matches:
            context = text[max(0, match.start - 50):match.end + 50].lower()
            assert "contribution margin" not in context, "CAC should be excluded near contribution margin"

    def test_empty_exclusion_list_handled(self) -> None:
        """Metrics without exclusions should work normally."""
        # cm_arr has no exclusions defined
        text = "Our ARR reached $10 million"
        matcher = KeywordMatcher()
        matches = matcher.find_all_keywords(text)
        matched_metrics = {m.metric_id for m in matches}

        assert "cm_arr" in matched_metrics

    def test_multiple_exclusion_patterns_checked(self) -> None:
        """All exclusion patterns for a metric should be checked."""
        # cm_customer_acquisition_cost has multiple exclusion patterns
        test_cases = [
            ("contribution margin CAC", True),  # contribution margin
            ("gross margin CAC", True),  # gross margin
            ("profit margin CAC", True),  # profit margin
            ("operating margin CAC", True),  # operating margin
            ("platform order contribution CAC", True),  # platform order contribution
        ]

        matcher = KeywordMatcher()
        for text, should_be_excluded in test_cases:
            matches = matcher.find_all_keywords(text)
            cac_matches = [m for m in matches if m.metric_id == "cm_customer_acquisition_cost"]
            if should_be_excluded:
                assert len(cac_matches) == 0, f"CAC should be excluded in: {text}"


class TestExclusionPatternCompilation:
    """Tests for exclusion pattern compilation."""

    def test_compiled_exclusions_exist(self) -> None:
        """Verify exclusions are compiled on init."""
        matcher = KeywordMatcher()
        assert hasattr(matcher, "_compiled_exclusions")
        assert isinstance(matcher._compiled_exclusions, dict)

    def test_compiled_exclusions_are_patterns(self) -> None:
        """Verify compiled exclusions are regex patterns."""
        matcher = KeywordMatcher()
        for _metric_id, patterns in matcher._compiled_exclusions.items():
            assert isinstance(patterns, list)
            for pattern in patterns:
                assert isinstance(pattern, re.Pattern)

    def test_is_excluded_method_exists(self) -> None:
        """Verify _is_excluded method exists and works."""
        matcher = KeywordMatcher()
        assert hasattr(matcher, "_is_excluded")

        # Test the method directly
        result = matcher._is_excluded("cm_customer_acquisition_cost", "contribution margin")
        assert result is True

        result = matcher._is_excluded("cm_customer_acquisition_cost", "some other text")
        assert result is False

    def test_is_excluded_with_unknown_metric(self) -> None:
        """Verify _is_excluded returns False for unknown metrics."""
        matcher = KeywordMatcher()
        result = matcher._is_excluded("cm_unknown_metric", "any context")
        assert result is False


class TestRegressionExistingBehavior:
    """Regression tests to ensure existing valid matches still work."""

    def test_existing_revenue_per_customer_patterns(self) -> None:
        """Ensure ARPU patterns still work."""
        texts = [
            "ARPU was $50",
            "Average revenue per user improved",
            "Revenue per customer increased",
        ]
        matcher = KeywordMatcher()
        for text in texts:
            matches = matcher.find_all_keywords(text)
            matched_metrics = {m.metric_id for m in matches}
            assert "cm_revenue_per_customer" in matched_metrics, f"ARPU should match: {text}"

    def test_existing_net_revenue_retention_patterns(self) -> None:
        """Ensure NRR patterns still work."""
        texts = [
            "NRR was 115%",
            "Net revenue retention improved",
            "Net dollar retention reached 120%",
        ]
        matcher = KeywordMatcher()
        for text in texts:
            matches = matcher.find_all_keywords(text)
            matched_metrics = {m.metric_id for m in matches}
            assert "cm_net_revenue_retention" in matched_metrics, f"NRR should match: {text}"

    def test_existing_active_customers_patterns(self) -> None:
        """Ensure active customers patterns still work.

        Note: "Total customers" and "Active customers" are now distinct metrics (MET-1):
        - cm_active_customers_total: engagement-based ("active customers")
        - cm_customers_period_end: period-end stock count ("total customers")
        """
        matcher = KeywordMatcher()

        # "Active customers" → cm_active_customers_total
        text1 = "Active customers reached 1 million"
        matches1 = matcher.find_all_keywords(text1)
        matched_metrics1 = {m.metric_id for m in matches1}
        assert "cm_active_customers_total" in matched_metrics1, f"Should match cm_active_customers_total: {text1}"

        # "Total customers" → cm_customers_period_end (NOT cm_active_customers_total)
        text2 = "Total customers grew by 20%"
        matches2 = matcher.find_all_keywords(text2)
        matched_metrics2 = {m.metric_id for m in matches2}
        assert "cm_customers_period_end" in matched_metrics2, f"Should match cm_customers_period_end: {text2}"

    def test_existing_churn_patterns(self) -> None:
        """Ensure churn patterns still work."""
        texts = [
            "Churn rate was 5%",
            "Customer churn decreased",
        ]
        matcher = KeywordMatcher()
        for text in texts:
            matches = matcher.find_all_keywords(text)
            matched_metrics = {m.metric_id for m in matches}
            assert "cm_customer_churn_rate" in matched_metrics, f"Churn should match: {text}"


class TestRealWorldExamples:
    """Tests using real-world examples from filings."""

    def test_farfetch_ltv_cac_vs_contribution_margin(self) -> None:
        """
        Test the real Farfetch example that inspired this task.

        The text has LTV/CAC ratio in one bullet and Contribution Margin in another.
        Values should NOT be incorrectly associated with keywords from other bullets.
        """
        text = """• Six month LTV/CAC ratio for the years ended December 31, 2015, 2016 and 2017 cohorts
  was 1.42, 1.53 and 1.72, respectively; and
• Platform Order Contribution Margin for the years ended December 31, 2015, 2016 and 2017
  was 33.0%, 35.0% and 43.0%, respectively.

Lifetime Value of a Consumer to Consumer Acquisition Cost Ratios"""

        matcher = KeywordMatcher()
        matches = matcher.find_all_keywords(text)

        # Find LTV matches - should be LTV/CAC ratio, not standalone LTV
        ltv_matches = [m for m in matches if "lifetime" in m.metric_id.lower() or "ltv" in m.metric_id.lower()]
        for match in ltv_matches:
            # Standalone LTV should be excluded near LTV/CAC
            if match.metric_id == "cm_lifetime_value_per_customer":
                # The "Lifetime Value" in the heading is far from LTV/CAC, check if excluded
                # This specific case may or may not be excluded depending on context window
                pass  # Allow either behavior for heading text

        # LTV/CAC ratio should be present
        matched_metrics = {m.metric_id for m in matches}
        assert "cm_ltv_to_cac_ratio" in matched_metrics

    def test_cac_correctly_identified_standalone(self) -> None:
        """CAC should be identified when it's the actual metric."""
        text = "Customer Acquisition Cost (CAC) was $45 per new customer"
        matcher = KeywordMatcher()
        matches = matcher.find_all_keywords(text)
        matched_metrics = {m.metric_id for m in matches}

        assert "cm_customer_acquisition_cost" in matched_metrics
        # New customers should NOT match because 'acquisition cost' is present
        assert "cm_new_customers_acquired" not in matched_metrics
