from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date

from src.extraction_v2.models import ChartData, ChartSeries, DataPoint

_YEAR_RE = re.compile(r"(?:19|20)\d{2}")
_COHORT_SUFFIX_RE = re.compile(r"\s*(?:cohort|vintage|class)\s*", re.IGNORECASE)


@dataclass
class CohortPeriod:
    cohort_def: str
    period_start: date
    period_end: date
    confidence: float
    requires_review: bool


class CohortParser:
    def parse(
        self,
        chart: ChartData,
        series: ChartSeries | None,
        point: DataPoint | None,
        filing_date: date,
    ) -> CohortPeriod | None:
        if series is not None and chart.series:
            year_match = _YEAR_RE.search(series.name)
            if year_match:
                cohort_year = int(year_match.group())
                cohort_def = _COHORT_SUFFIX_RE.sub("", series.name).strip()
                if point is not None:
                    x_match = _YEAR_RE.search(str(point.x))
                    end_year = int(x_match.group()) if x_match else filing_date.year
                else:
                    end_year = filing_date.year
                return CohortPeriod(
                    cohort_def=cohort_def,
                    period_start=date(cohort_year, 1, 1),
                    period_end=date(end_year, 12, 31),
                    confidence=0.85,
                    requires_review=False,
                )

        if (series is None or not chart.series) and chart.annotations:
            for ann in chart.annotations:
                if not ann.period:
                    continue
                period_match = _YEAR_RE.search(ann.period)
                if not period_match:
                    continue
                period_year = int(period_match.group())
                cohort_def = ann.category if ann.category else period_match.group()
                return CohortPeriod(
                    cohort_def=cohort_def,
                    period_start=date(period_year, 1, 1),
                    period_end=date(period_year, 12, 31),
                    confidence=0.55,
                    requires_review=True,
                )

        return None
