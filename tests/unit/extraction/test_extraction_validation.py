"""
Tests for extraction validation module.

Tests the validation rules that catch common extraction errors:
- Unit validation
- Range validation
- Keyword validation
- Quote validation
- Quote-keyword validation (new: validates quote contains metric keyword)
"""

import pytest
from src.extraction.extraction_validation import (
    ValidationResult,
    ValidationIssue,
    validate_unit,
    validate_range,
    validate_keyword_in_source,
    validate_quote,
    validate_quote_contains_metric_keyword,
    validate_extraction,
    should_reject_extraction,
    get_rejection_reason,
    normalize_unit,
)


class TestNormalizeUnit:
    """Tests for unit normalization."""

    def test_normalize_dollar_sign(self):
        assert normalize_unit("$") == "dollars"

    def test_normalize_usd(self):
        assert normalize_unit("usd") == "dollars"
        assert normalize_unit("USD") == "dollars"

    def test_normalize_percent(self):
        assert normalize_unit("%") == "percent"
        assert normalize_unit("pct") == "percent"

    def test_normalize_none(self):
        assert normalize_unit(None) is None

    def test_normalize_passthrough(self):
        assert normalize_unit("millions") == "millions"
        assert normalize_unit("count") == "count"


class TestValidateUnit:
    """Tests for unit validation."""

    def test_cac_with_dollars_passes(self):
        result = validate_unit("cm_customer_acquisition_cost", "dollars", 100)
        assert result == ValidationResult.PASS

    def test_cac_with_percent_fails(self):
        result = validate_unit("cm_customer_acquisition_cost", "percent", 100)
        assert result == ValidationResult.FAIL_UNIT

    def test_retention_with_percent_passes(self):
        result = validate_unit("cm_customer_retention_rate", "percent", 85)
        assert result == ValidationResult.PASS

    def test_retention_with_dollars_fails(self):
        result = validate_unit("cm_customer_retention_rate", "dollars", 85)
        assert result == ValidationResult.FAIL_UNIT

    def test_nrr_with_percent_passes(self):
        result = validate_unit("cm_net_revenue_retention", "%", 120)
        assert result == ValidationResult.PASS

    def test_customer_count_with_count_passes(self):
        result = validate_unit("cm_active_customers_total", "count", 10000)
        assert result == ValidationResult.PASS

    def test_customer_count_with_millions_passes(self):
        result = validate_unit("cm_active_customers_total", "millions", 5.2)
        assert result == ValidationResult.PASS

    def test_unknown_metric_passes(self):
        """Unknown metrics should pass (no rule defined)."""
        result = validate_unit("cm_unknown_metric", "random_unit", 100)
        assert result == ValidationResult.PASS

    def test_none_unit_passes(self):
        result = validate_unit("cm_customer_acquisition_cost", None, 100)
        assert result == ValidationResult.PASS


class TestValidateRange:
    """Tests for range validation."""

    def test_retention_in_range_passes(self):
        result = validate_range("cm_customer_retention_rate", 85, "percent")
        assert result == ValidationResult.PASS

    def test_retention_over_100_fails(self):
        result = validate_range("cm_customer_retention_rate", 150, "percent")
        assert result == ValidationResult.FAIL_RANGE

    def test_nrr_over_100_passes(self):
        """NRR can be over 100%."""
        result = validate_range("cm_net_revenue_retention", 130, "percent")
        assert result == ValidationResult.PASS

    def test_churn_rate_valid(self):
        result = validate_range("cm_churn_rate", 5, "percent")
        assert result == ValidationResult.PASS

    def test_churn_rate_over_100_fails(self):
        result = validate_range("cm_churn_rate", 150, "percent")
        assert result == ValidationResult.FAIL_RANGE

    def test_ltv_cac_ratio_valid(self):
        result = validate_range("cm_ltv_cac_ratio", 3.5, "x")
        assert result == ValidationResult.PASS

    def test_ltv_cac_ratio_extreme_fails(self):
        result = validate_range("cm_ltv_cac_ratio", 500, "x")
        assert result == ValidationResult.FAIL_RANGE

    def test_unknown_metric_passes(self):
        result = validate_range("cm_unknown_metric", 99999999, None)
        assert result == ValidationResult.PASS


class TestValidateKeywordInSource:
    """Tests for keyword validation."""

    def test_cac_keyword_present(self):
        source = "Our customer acquisition cost was $150 per customer."
        result = validate_keyword_in_source("cm_customer_acquisition_cost", source)
        assert result == ValidationResult.PASS

    def test_cac_abbreviation_present(self):
        source = "Our CAC was $150."
        result = validate_keyword_in_source("cm_customer_acquisition_cost", source)
        assert result == ValidationResult.PASS

    def test_cac_keyword_missing(self):
        source = "Our revenue grew by 50% year over year."
        result = validate_keyword_in_source("cm_customer_acquisition_cost", source)
        assert result == ValidationResult.FAIL_KEYWORD

    def test_retention_keyword_present(self):
        source = "We achieved a customer retention rate of 92%."
        result = validate_keyword_in_source("cm_customer_retention_rate", source)
        assert result == ValidationResult.PASS

    def test_nrr_keyword_present(self):
        source = "Net revenue retention was 130% for the year."
        result = validate_keyword_in_source("cm_net_revenue_retention", source)
        assert result == ValidationResult.PASS

    def test_nrr_abbreviation_present(self):
        source = "Our NRR exceeded 120%."
        result = validate_keyword_in_source("cm_net_revenue_retention", source)
        assert result == ValidationResult.PASS

    def test_new_customers_keyword_present(self):
        source = "We acquired 50,000 new customers during the quarter."
        result = validate_keyword_in_source("cm_new_customers_acquired", source)
        assert result == ValidationResult.PASS

    def test_unknown_metric_passes(self):
        result = validate_keyword_in_source("cm_unknown_metric", "any text")
        assert result == ValidationResult.PASS


class TestValidateQuote:
    """Tests for quote validation."""

    def test_valid_quote_with_value(self):
        result = validate_quote(
            quote="We had 10,000 active customers.",
            value=10000,
            source_text="We had 10,000 active customers last quarter."
        )
        assert result == ValidationResult.PASS

    def test_empty_quote_fails(self):
        result = validate_quote(
            quote="",
            value=100,
            source_text="Some source text."
        )
        assert result == ValidationResult.FAIL_QUOTE

    def test_none_quote_fails(self):
        result = validate_quote(
            quote=None,
            value=100,
            source_text="Some source text."
        )
        assert result == ValidationResult.FAIL_QUOTE

    def test_short_quote_fails(self):
        result = validate_quote(
            quote="short",
            value=100,
            source_text="Some source text."
        )
        assert result == ValidationResult.FAIL_QUOTE

    def test_quote_with_formatted_number(self):
        result = validate_quote(
            quote="Revenue was $1,500,000 for the quarter.",
            value=1500000,
            source_text="Revenue was $1,500,000 for the quarter."
        )
        assert result == ValidationResult.PASS


class TestValidateExtraction:
    """Integration tests for full extraction validation."""

    def test_valid_extraction_no_issues(self):
        issues = validate_extraction(
            metric_id="cm_customer_retention_rate",
            value=92,
            unit="percent",
            quote="Customer retention rate was 92% for fiscal 2023.",
            source_text="Our customer retention rate was 92% for fiscal 2023."
        )
        assert len(issues) == 0

    def test_wrong_unit_creates_issue(self):
        issues = validate_extraction(
            metric_id="cm_customer_acquisition_cost",
            value=150,
            unit="percent",
            quote="CAC was 150%.",
            source_text="Our CAC was 150%."
        )
        assert len(issues) >= 1
        assert any(i.result == ValidationResult.FAIL_UNIT for i in issues)

    def test_out_of_range_creates_issue(self):
        issues = validate_extraction(
            metric_id="cm_customer_retention_rate",
            value=250,
            unit="percent",
            quote="Retention was 250%.",
            source_text="Retention was 250%."
        )
        assert len(issues) >= 1
        assert any(i.result == ValidationResult.FAIL_RANGE for i in issues)

    def test_missing_keyword_creates_issue(self):
        issues = validate_extraction(
            metric_id="cm_customer_acquisition_cost",
            value=150,
            unit="dollars",
            quote="We spent $150 on marketing.",
            source_text="We spent $150 on marketing this quarter."
        )
        assert len(issues) >= 1
        assert any(i.result == ValidationResult.FAIL_KEYWORD for i in issues)

    def test_missing_quote_creates_issue(self):
        issues = validate_extraction(
            metric_id="cm_customer_retention_rate",
            value=92,
            unit="percent",
            quote="",
            source_text="Our customer retention rate was 92%."
        )
        assert len(issues) >= 1
        assert any(i.result == ValidationResult.FAIL_QUOTE for i in issues)


class TestShouldRejectExtraction:
    """Tests for rejection decision logic."""

    def test_no_issues_not_rejected(self):
        assert should_reject_extraction([]) is False

    def test_fail_unit_rejected(self):
        issues = [
            ValidationIssue(
                result=ValidationResult.FAIL_UNIT,
                metric_id="cm_cac",
                value=100,
                unit="percent",
                message="Wrong unit"
            )
        ]
        assert should_reject_extraction(issues) is True

    def test_fail_range_rejected(self):
        issues = [
            ValidationIssue(
                result=ValidationResult.FAIL_RANGE,
                metric_id="cm_retention",
                value=500,
                unit="percent",
                message="Out of range"
            )
        ]
        assert should_reject_extraction(issues) is True

    def test_fail_keyword_rejected(self):
        issues = [
            ValidationIssue(
                result=ValidationResult.FAIL_KEYWORD,
                metric_id="cm_cac",
                value=100,
                unit="dollars",
                message="Keyword missing"
            )
        ]
        assert should_reject_extraction(issues) is True

    def test_warn_not_rejected(self):
        issues = [
            ValidationIssue(
                result=ValidationResult.WARN,
                metric_id="cm_cac",
                value=100,
                unit="dollars",
                message="Minor issue"
            )
        ]
        assert should_reject_extraction(issues) is False


class TestGetRejectionReason:
    """Tests for rejection reason formatting."""

    def test_empty_issues_empty_reason(self):
        assert get_rejection_reason([]) == ""

    def test_single_issue_reason(self):
        issues = [
            ValidationIssue(
                result=ValidationResult.FAIL_UNIT,
                metric_id="cm_cac",
                value=100,
                unit="percent",
                message="Unit 'percent' not valid for cm_cac"
            )
        ]
        reason = get_rejection_reason(issues)
        assert "Unit 'percent' not valid" in reason

    def test_multiple_issues_joined(self):
        issues = [
            ValidationIssue(
                result=ValidationResult.FAIL_UNIT,
                metric_id="cm_cac",
                value=100,
                unit="percent",
                message="Wrong unit"
            ),
            ValidationIssue(
                result=ValidationResult.FAIL_RANGE,
                metric_id="cm_cac",
                value=100,
                unit="percent",
                message="Out of range"
            ),
        ]
        reason = get_rejection_reason(issues)
        assert ";" in reason
        assert "Wrong unit" in reason
        assert "Out of range" in reason


class TestValidateQuoteContainsMetricKeyword:
    """
    Tests for quote-keyword validation.

    This is the critical check that prevents extracting unrelated nearby numbers.
    The quote must contain BOTH the metric keyword AND the extracted value.
    """

    def test_valid_cac_quote_with_keyword_and_value(self):
        """Quote with CAC keyword and value should pass."""
        result, reason = validate_quote_contains_metric_keyword(
            metric_id="cm_customer_acquisition_cost",
            quote="Our customer acquisition cost was $150 per customer.",
            value=150,
        )
        assert result == ValidationResult.PASS
        assert "contains" in reason.lower()

    def test_valid_cac_with_abbreviation(self):
        """Quote with CAC abbreviation should pass."""
        result, reason = validate_quote_contains_metric_keyword(
            metric_id="cm_customer_acquisition_cost",
            quote="CAC decreased to $120 during the quarter.",
            value=120,
        )
        assert result == ValidationResult.PASS

    def test_reject_quote_missing_keyword(self):
        """Quote with value but no metric keyword should fail."""
        result, reason = validate_quote_contains_metric_keyword(
            metric_id="cm_customer_acquisition_cost",
            quote="Growth of 83% YoY",
            value=83,
        )
        assert result == ValidationResult.FAIL_KEYWORD
        assert "missing" in reason.lower() or "expected" in reason.lower()

    def test_reject_revenue_quoted_as_cac(self):
        """The Samsara bug: revenue/growth quoted as CAC should fail."""
        result, reason = validate_quote_contains_metric_keyword(
            metric_id="cm_customer_acquisition_cost",
            quote="Revenue grew 83% year over year",
            value=83,
        )
        assert result == ValidationResult.FAIL_KEYWORD

    def test_reject_customer_count_quoted_as_cac(self):
        """Customer count quoted as CAC should fail."""
        result, reason = validate_quote_contains_metric_keyword(
            metric_id="cm_customer_acquisition_cost",
            quote="We had 13,000 Core Customers",
            value=13000,
        )
        assert result == ValidationResult.FAIL_KEYWORD

    def test_warn_when_value_not_in_quote(self):
        """Quote with keyword but missing value should warn."""
        result, reason = validate_quote_contains_metric_keyword(
            metric_id="cm_customer_acquisition_cost",
            quote="Our CAC improved significantly during the year.",
            value=150,
        )
        # Should pass the keyword check but warn about missing value
        assert result == ValidationResult.WARN or result == ValidationResult.PASS
        # If it warns, the reason should mention value
        if result == ValidationResult.WARN:
            assert "value" in reason.lower()

    def test_empty_quote_fails(self):
        """Empty quote should fail."""
        result, reason = validate_quote_contains_metric_keyword(
            metric_id="cm_customer_acquisition_cost",
            quote="",
            value=150,
        )
        assert result == ValidationResult.FAIL_QUOTE

    def test_none_quote_fails(self):
        """None quote should fail."""
        result, reason = validate_quote_contains_metric_keyword(
            metric_id="cm_customer_acquisition_cost",
            quote=None,
            value=150,
        )
        assert result == ValidationResult.FAIL_QUOTE

    def test_valid_nrr_quote(self):
        """Quote with NRR keyword and value should pass."""
        result, reason = validate_quote_contains_metric_keyword(
            metric_id="cm_net_revenue_retention",
            quote="Net revenue retention was 115% for the fiscal year.",
            value=115,
        )
        assert result == ValidationResult.PASS

    def test_valid_nrr_abbreviation(self):
        """Quote with NRR abbreviation should pass."""
        result, reason = validate_quote_contains_metric_keyword(
            metric_id="cm_net_revenue_retention",
            quote="Our NRR exceeded 120%.",
            value=120,
        )
        assert result == ValidationResult.PASS

    def test_case_insensitive_keyword_matching(self):
        """Keyword matching should be case insensitive."""
        result, reason = validate_quote_contains_metric_keyword(
            metric_id="cm_net_revenue_retention",
            quote="NET REVENUE RETENTION reached 120%.",
            value=120,
        )
        assert result == ValidationResult.PASS

    def test_value_with_comma_formatting(self):
        """Value with comma formatting should match."""
        result, reason = validate_quote_contains_metric_keyword(
            metric_id="cm_new_customers_acquired",
            quote="We acquired 1,500,000 new customers last year.",
            value=1500000,
        )
        assert result == ValidationResult.PASS

    def test_unknown_metric_passes(self):
        """Unknown metrics without keyword rules should pass."""
        result, reason = validate_quote_contains_metric_keyword(
            metric_id="cm_unknown_metric_without_rules",
            quote="Some quote with 100 value",
            value=100,
        )
        assert result == ValidationResult.PASS
        assert "no keyword rules" in reason.lower()

    def test_retention_rate_valid(self):
        """Valid retention rate quote should pass."""
        result, reason = validate_quote_contains_metric_keyword(
            metric_id="cm_customer_retention_rate",
            quote="Our customer retention rate was 92%.",
            value=92,
        )
        assert result == ValidationResult.PASS

    def test_churn_rate_valid(self):
        """Valid churn rate quote should pass."""
        result, reason = validate_quote_contains_metric_keyword(
            metric_id="cm_churn_rate",
            quote="Monthly churn rate was 2.5%.",
            value=2.5,
        )
        assert result == ValidationResult.PASS

    def test_active_customers_valid(self):
        """Valid active customers quote should pass."""
        result, reason = validate_quote_contains_metric_keyword(
            metric_id="cm_active_customers_total",
            quote="We had 500,000 active customers as of year end.",
            value=500000,
        )
        assert result == ValidationResult.PASS

    def test_expansion_revenue_valid(self):
        """Valid expansion revenue quote should pass."""
        result, reason = validate_quote_contains_metric_keyword(
            metric_id="cm_expansion_revenue",
            quote="Expansion revenue from existing customers was $50 million.",
            value=50,
        )
        assert result == ValidationResult.PASS
