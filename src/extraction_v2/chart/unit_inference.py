from __future__ import annotations

import re

from src.extraction_v2.models import Unit

_RATIO_VALUE_RE = re.compile(r"^\d+(\.\d+)?\s*x$", re.IGNORECASE)
_RATIO_LABEL_RE = re.compile(r"\b(ratio|multiple)\b", re.IGNORECASE)
_COUNT_LABEL_RE = re.compile(r"\b(orders|transactions|#)\b", re.IGNORECASE)


def infer_unit_and_currency(
    y_axis_label: str, sample_values: list[str] | None = None
) -> tuple[Unit | None, str | None]:
    if "$" in y_axis_label:
        return (Unit.CURRENCY, "USD")
    if "%" in y_axis_label:
        return (Unit.PERCENT, None)
    has_ratio_values = sample_values is not None and any(
        _RATIO_VALUE_RE.match(v) for v in sample_values
    )
    if has_ratio_values or _RATIO_LABEL_RE.search(y_axis_label):
        return (Unit.RATIO, None)
    if _COUNT_LABEL_RE.search(y_axis_label):
        return (Unit.COUNT, None)
    return (None, None)
