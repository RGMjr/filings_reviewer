from src.extraction_v2.chart.unit_inference import infer_unit_and_currency
from src.extraction_v2.models import Unit


def test_infers_currency_usd_from_dollar_yaxis() -> None:
    unit, currency = infer_unit_and_currency("$ billions")
    assert unit == Unit.CURRENCY
    assert currency == "USD"


def test_infers_percent_from_percent_yaxis() -> None:
    unit, currency = infer_unit_and_currency("% of GMV")
    assert unit == Unit.PERCENT
    assert currency is None


def test_returns_none_for_unknown_unit() -> None:
    unit, currency = infer_unit_and_currency("count")
    assert unit is None
    assert currency is None


def test_ratio_nx_format() -> None:
    unit, currency = infer_unit_and_currency("Ratio", sample_values=["1.8x", "2.4x"])
    assert unit == Unit.RATIO
    assert currency is None


def test_ratio_label_keyword() -> None:
    unit, currency = infer_unit_and_currency("LTV to CAC ratio")
    assert unit == Unit.RATIO
    assert currency is None


def test_count_orders_y_axis() -> None:
    unit, currency = infer_unit_and_currency("Number of orders")
    assert unit == Unit.COUNT
    assert currency is None


def test_precedence_percent_beats_ratio() -> None:
    unit, currency = infer_unit_and_currency("% ratio", sample_values=["1.5x"])
    assert unit == Unit.PERCENT
    assert currency is None


def test_precedence_ratio_beats_count() -> None:
    unit, currency = infer_unit_and_currency("Ratio (orders)", sample_values=["1.8x"])
    assert unit == Unit.RATIO
    assert currency is None


def test_currency_still_wins_when_dollar() -> None:
    unit, currency = infer_unit_and_currency("$ Revenue", sample_values=["1.5x"])
    assert unit == Unit.CURRENCY
    assert currency == "USD"
