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
