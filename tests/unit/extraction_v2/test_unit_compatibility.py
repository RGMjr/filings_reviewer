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
        "cm_daily_active_users",
        "cm_monthly_active_users",
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
        "cm_arr",
        "cm_mrr",
        "cm_tcv",
        "cm_acv",
        "cm_lifetime_value_per_customer",
        "cm_customer_acquisition_cost",
        "cm_revenue_per_customer",
        "cm_average_order_value",
        "cm_expansion_revenue",
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
    def test_rejects_count(self, metric_id: str) -> None:
        assert is_unit_compatible(metric_id, Unit.COUNT) is False


class TestUnconstrainedMetrics:
    """Metrics not in any constraint group accept all units."""

    @pytest.mark.parametrize(
        "unit",
        [Unit.COUNT, Unit.CURRENCY, Unit.PERCENT, Unit.RATIO, Unit.OTHER, Unit.BASIS_POINTS],
    )
    def test_unknown_metric_accepts_all(self, unit: Unit) -> None:
        assert is_unit_compatible("cm_revenue_by_cohort", unit) is True

    @pytest.mark.parametrize(
        "unit",
        [Unit.COUNT, Unit.CURRENCY, Unit.PERCENT, Unit.RATIO, Unit.OTHER, Unit.BASIS_POINTS],
    )
    def test_nonexistent_metric_accepts_all(self, unit: Unit) -> None:
        assert is_unit_compatible("cm_totally_fake_metric", unit) is True

    def test_cac_payback_period_unconstrained(self) -> None:
        assert is_unit_compatible("cm_cac_payback_period", Unit.COUNT) is True
        assert is_unit_compatible("cm_cac_payback_period", Unit.CURRENCY) is True


class TestGetAllowedUnits:
    """Tests for get_allowed_units()."""

    def test_count_metric_returns_count_and_other(self) -> None:
        allowed = get_allowed_units("cm_customers_period_end")
        assert allowed is not None
        assert Unit.COUNT in allowed
        assert Unit.OTHER in allowed
        assert Unit.CURRENCY not in allowed

    def test_currency_metric_returns_currency_and_other(self) -> None:
        allowed = get_allowed_units("cm_arr")
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

    def test_ratio_metric_returns_percent_ratio_and_other(self) -> None:
        allowed = get_allowed_units("cm_ltv_to_cac_ratio")
        assert allowed is not None
        assert Unit.PERCENT in allowed
        assert Unit.RATIO in allowed
        assert Unit.OTHER in allowed
        assert len(allowed) == 3

    def test_unknown_metric_returns_none(self) -> None:
        assert get_allowed_units("cm_unknown_metric") is None

    def test_lookup_dict_not_empty(self) -> None:
        assert len(METRIC_ALLOWED_UNITS) > 0
        # Should have count + currency + percent + ratio metrics
        assert len(METRIC_ALLOWED_UNITS) == 9 + 13 + 7 + 3  # 32 total
