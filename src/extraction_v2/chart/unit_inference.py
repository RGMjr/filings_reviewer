from __future__ import annotations

from src.extraction_v2.models import Unit


def infer_unit_and_currency(y_axis_label: str) -> tuple[Unit | None, str | None]:
    if "$" in y_axis_label:
        return (Unit.CURRENCY, "USD")
    if "%" in y_axis_label:
        return (Unit.PERCENT, None)
    return (None, None)
