"""
Unit tests for V2 unit compatibility filtering.

Tests that metric-unit constraints correctly reject incompatible bindings:
- Count metrics reject currency and percent
- Currency metrics reject count and percent
- Percent metrics reject currency and count
- Unconstrained/unknown metrics accept all units
"""

from __future__ import annotations

import pytest

from src.extraction_v2.models import Unit
from src.extraction_v2.unit_compatibility import (
    METRIC_ALLOWED_UNITS,
    get_allowed_units,
    is_unit_compatible,
)


class TestCountOnlyMetrics:
    """Count-only metrics should reject currency and percent."""

    COUNT_METRICS = [
        "cm_customers_period_end",
        "cm_active_customers_total",
        "cm_large_customers_period_end",
        "cm_new_customers_acquired",
        "cm_customers_period_end_by_tenure",
        "cm_purchase_transactions_overall",
        "cm_transactions_by_cohort",
    ]

    @pytest.mark.parametrize("metric_id", COUNT_METRICS)
    def test_accepts_count(self, metric_id: str) -> None:
        assert is_unit_compatible(metric_id, Unit.COUNT) is True

    @pytest.mark.parametrize("metric_id", COUNT_METRICS)
    def test_accepts_other(self, metric_id: str) -> None:
        assert is_unit_compatible(metric_id, Unit.OTHER) is True

    @pytest.mark.parametrize("metric_id", COUNT_METRICS)
    def test_rejects_currency(self, metric_id: str) -> None:
        assert is_unit_compatible(metric_id, Unit.CURRENCY) is False

    @pytest.mark.parametrize("metric_id", COUNT_METRICS)
    def test_rejects_percent(self, metric_id: str) -> None:
        assert is_unit_compatible(metric_id, Unit.PERCENT) is False

    @pytest.mark.parametrize("metric_id", COUNT_METRICS)
    def test_rejects_ratio(self, metric_id: str) -> None:
        assert is_unit_compatible(metric_id, Unit.RATIO) is False


class TestCurrencyOnlyMetrics:
    """Currency-only metrics should reject count and percent."""

    CURRENCY_METRICS = [
        "cm_tcv",
        "cm_acv",
        "cm_lifetime_value_per_customer",
        "cm_customer_acquisition_cost",
        "cm_average_order_value",
        "cm_deferred_revenue",
        "cm_billings",
        "cm_bookings",
        "cm_gmv",
    ]

    @pytest.mark.parametrize("metric_id", CURRENCY_METRICS)
    def test_accepts_currency(self, metric_id: str) -> None:
        assert is_unit_compatible(metric_id, Unit.CURRENCY) is True

    @pytest.mark.parametrize("metric_id", CURRENCY_METRICS)
    def test_accepts_other(self, metric_id: str) -> None:
        assert is_unit_compatible(metric_id, Unit.OTHER) is True

    @pytest.mark.parametrize("metric_id", CURRENCY_METRICS)
    def test_rejects_count(self, metric_id: str) -> None:
        assert is_unit_compatible(metric_id, Unit.COUNT) is False

    @pytest.mark.parametrize("metric_id", CURRENCY_METRICS)
    def test_rejects_percent(self, metric_id: str) -> None:
        assert is_unit_compatible(metric_id, Unit.PERCENT) is False

    @pytest.mark.parametrize("metric_id", CURRENCY_METRICS)
    def test_rejects_ratio(self, metric_id: str) -> None:
        assert is_unit_compatible(metric_id, Unit.RATIO) is False


class TestPercentOnlyMetrics:
    """Percent-only metrics should reject currency, count, and OTHER."""

    PERCENT_METRICS = [
        "cm_net_revenue_retention",
        "cm_gross_revenue_retention",
        "cm_customer_retention_rate",
        "cm_customer_churn_rate",
        "cm_revenue_concentration",
        "cm_gross_margin_by_cohort",
        "cm_gross_margin_overall",
    ]

    @pytest.mark.parametrize("metric_id", PERCENT_METRICS)
    def test_accepts_percent(self, metric_id: str) -> None:
        assert is_unit_compatible(metric_id, Unit.PERCENT) is True

    @pytest.mark.parametrize("metric_id", PERCENT_METRICS)
    def test_accepts_ratio(self, metric_id: str) -> None:
        assert is_unit_compatible(metric_id, Unit.RATIO) is True

    @pytest.mark.parametrize("metric_id", PERCENT_METRICS)
    def test_rejects_currency(self, metric_id: str) -> None:
        assert is_unit_compatible(metric_id, Unit.CURRENCY) is False

    @pytest.mark.parametrize("metric_id", PERCENT_METRICS)
    def test_rejects_other(self, metric_id: str) -> None:
        """Unit.OTHER rejected for percent-only metrics to prevent bare numbers
        (e.g., 37000 near NRR keyword) from being accepted as percentages."""
        assert is_unit_compatible(metric_id, Unit.OTHER) is False

    @pytest.mark.parametrize("metric_id", PERCENT_METRICS)
    def test_rejects_count(self, metric_id: str) -> None:
        assert is_unit_compatible(metric_id, Unit.COUNT) is False


class TestRatioMetrics:
    """Ratio metrics accept percent, ratio, AND other (bare decimals like 1.42x)."""

    RATIO_METRICS = [
        "cm_ltv_to_cac_ratio",
        "cm_ltv_to_cac_ratio_by_cohort",
        "cm_repeat_purchase_rate",
    ]

    @pytest.mark.parametrize("metric_id", RATIO_METRICS)
    def test_accepts_percent(self, metric_id: str) -> None:
        assert is_unit_compatible(metric_id, Unit.PERCENT) is True

    @pytest.mark.parametrize("metric_id", RATIO_METRICS)
    def test_accepts_ratio(self, metric_id: str) -> None:
        assert is_unit_compatible(metric_id, Unit.RATIO) is True

    @pytest.mark.parametrize("metric_id", RATIO_METRICS)
    def test_accepts_other(self, metric_id: str) -> None:
        """Ratio metrics like LTV/CAC naturally appear as bare decimals (1.42)."""
        assert is_unit_compatible(metric_id, Unit.OTHER) is True

    @pytest.mark.parametrize("metric_id", RATIO_METRICS)
    def test_rejects_currency(self, metric_id: str) -> None:
        assert is_unit_compatible(metric_id, Unit.CURRENCY) is False

    @pytest.mark.parametrize("metric_id", RATIO_METRICS)
    def test_accepts_count(self, metric_id: str) -> None:
        # COUNT is accepted because bare decimals like "1.42" parse as Unit.COUNT.
        # Year-like integers (2015, 2016) pass this filter but are removed by the
        # v2_year_value FP rule downstream.
        assert is_unit_compatible(metric_id, Unit.COUNT) is True


class TestNewConstraints:
    """Tests for constraints added in WP-04."""

    def test_cac_payback_period_constrained_to_count(self) -> None:
        assert is_unit_compatible("cm_cac_payback_period", Unit.COUNT) is True
        assert is_unit_compatible("cm_cac_payback_period", Unit.OTHER) is True
        assert is_unit_compatible("cm_cac_payback_period", Unit.CURRENCY) is False
        assert is_unit_compatible("cm_cac_payback_period", Unit.PERCENT) is False
        assert is_unit_compatible("cm_cac_payback_period", Unit.RATIO) is False

    def test_revenue_by_cohort_unconstrained(self) -> None:
        # cm_revenue_by_cohort is intentionally unconstrained — some filings
        # express cohort revenue in dollars (Farfetch), others as percentages
        # (Snowflake: "94% of revenue from existing customers").
        assert is_unit_compatible("cm_revenue_by_cohort", Unit.CURRENCY) is True
        assert is_unit_compatible("cm_revenue_by_cohort", Unit.PERCENT) is True
        assert is_unit_compatible("cm_revenue_by_cohort", Unit.COUNT) is True
        assert is_unit_compatible("cm_revenue_by_cohort", Unit.OTHER) is True
        assert get_allowed_units("cm_revenue_by_cohort") is None


class TestUnconstrainedMetrics:
    """Metrics not in any constraint group accept all units."""

    @pytest.mark.parametrize(
        "unit",
        [Unit.COUNT, Unit.CURRENCY, Unit.PERCENT, Unit.RATIO, Unit.OTHER, Unit.BASIS_POINTS],
    )
    def test_unknown_metric_accepts_all(self, unit: Unit) -> None:
        assert is_unit_compatible("cm_some_unrecognized_metric", unit) is True

    @pytest.mark.parametrize(
        "unit",
        [Unit.COUNT, Unit.CURRENCY, Unit.PERCENT, Unit.RATIO, Unit.OTHER, Unit.BASIS_POINTS],
    )
    def test_nonexistent_metric_accepts_all(self, unit: Unit) -> None:
        assert is_unit_compatible("cm_totally_fake_metric", unit) is True

    @pytest.mark.parametrize(
        "unit",
        [Unit.COUNT, Unit.CURRENCY, Unit.PERCENT, Unit.RATIO, Unit.OTHER],
    )
    def test_mau_unconstrained(self, unit: Unit) -> None:
        """MAU/DAU are unconstrained — transcript annotations include growth rates."""
        assert is_unit_compatible("cm_monthly_active_users", unit) is True
        assert is_unit_compatible("cm_daily_active_users", unit) is True

    @pytest.mark.parametrize(
        "unit",
        [Unit.COUNT, Unit.CURRENCY, Unit.PERCENT, Unit.RATIO, Unit.OTHER],
    )
    def test_revenue_per_customer_unconstrained(self, unit: Unit) -> None:
        """revenue_per_customer/revenue_by_cohort are unconstrained for transcripts."""
        assert is_unit_compatible("cm_revenue_per_customer", unit) is True
        assert is_unit_compatible("cm_revenue_by_cohort", unit) is True



class TestGetAllowedUnits:
    """Tests for get_allowed_units()."""

    def test_count_metric_returns_count_and_other(self) -> None:
        allowed = get_allowed_units("cm_customers_period_end")
        assert allowed is not None
        assert Unit.COUNT in allowed
        assert Unit.OTHER in allowed
        assert Unit.CURRENCY not in allowed

    def test_currency_metric_returns_currency_and_other(self) -> None:
        allowed = get_allowed_units("cm_tcv")
        assert allowed is not None
        assert Unit.CURRENCY in allowed
        assert Unit.OTHER in allowed
        assert len(allowed) == 2

    def test_percent_metric_returns_percent_and_ratio_only(self) -> None:
        allowed = get_allowed_units("cm_net_revenue_retention")
        assert allowed is not None
        assert Unit.PERCENT in allowed
        assert Unit.RATIO in allowed
        assert Unit.OTHER not in allowed
        assert len(allowed) == 2

    def test_ratio_metric_returns_percent_ratio_other_and_count(self) -> None:
        # COUNT is included so that bare decimals like "1.42" (which parse as
        # Unit.COUNT) are accepted for ratio metrics like LTV/CAC.
        allowed = get_allowed_units("cm_ltv_to_cac_ratio")
        assert allowed is not None
        assert Unit.PERCENT in allowed
        assert Unit.RATIO in allowed
        assert Unit.OTHER in allowed
        assert Unit.COUNT in allowed
        assert len(allowed) == 4

    def test_unknown_metric_returns_none(self) -> None:
        assert get_allowed_units("cm_unknown_metric") is None

    def test_lookup_dict_not_empty(self) -> None:
        assert len(METRIC_ALLOWED_UNITS) > 0
        # count(8) + currency(9) + percent(7) + ratio(3)
        # cm_revenue_by_cohort removed from currency-only — now unconstrained
        # cm_arr and cm_mrr removed (deprecated)
        assert len(METRIC_ALLOWED_UNITS) == 8 + 9 + 7 + 3  # 27 total
