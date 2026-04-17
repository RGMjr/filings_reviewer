from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date

from dateutil.relativedelta import relativedelta

from src.extraction_v2.models import ChartData, ChartSeries, DataPoint

_YEAR_RE = re.compile(r"(?:19|20)\d{2}")
_COHORT_SUFFIX_RE = re.compile(r"\s*(?:cohort|vintage|class)\s*", re.IGNORECASE)
_ELAPSED_YEAR_RE = re.compile(r"^(?:Year|Yr|Y)\s*(\d+)$", re.IGNORECASE)
_ELAPSED_MONTH_RE = re.compile(r"^(?:Month|Mo|M)\s*(\d+)$", re.IGNORECASE)


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
        result = self._parse_series_year_regime(chart, series, point, filing_date)
        if result is not None:
            return result
        result = self._parse_elapsed_period_regime(chart, series, point, filing_date)
        if result is not None:
            return result
        return self._parse_annotations_regime(chart, series, point, filing_date)

    def _parse_series_year_regime(
        self,
        chart: ChartData,
        series: ChartSeries | None,
        point: DataPoint | None,
        filing_date: date,
    ) -> CohortPeriod | None:
        if series is None or not chart.series:
            return None
        year_match = _YEAR_RE.search(series.name)
        if not year_match:
            return None
        cohort_year = int(year_match.group())
        cohort_def = _COHORT_SUFFIX_RE.sub("", series.name).strip()
        if point is not None:
            x_str = str(point.x)
            if _ELAPSED_YEAR_RE.match(x_str) or _ELAPSED_MONTH_RE.match(x_str):
                return None
            x_match = _YEAR_RE.search(x_str)
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

    def _parse_elapsed_period_regime(
        self,
        chart: ChartData,
        series: ChartSeries | None,
        point: DataPoint | None,
        filing_date: date,
    ) -> CohortPeriod | None:
        if series is None or point is None:
            return None
        year_match = _YEAR_RE.search(series.name)
        if not year_match:
            return None
        x_str = str(point.x)
        year_elapsed = _ELAPSED_YEAR_RE.match(x_str)
        month_elapsed = _ELAPSED_MONTH_RE.match(x_str)
        if year_elapsed:
            n = int(year_elapsed.group(1))
            cohort_year = int(year_match.group())
            cohort_start = date(cohort_year, 1, 1)
            period_end = cohort_start + relativedelta(years=n)
            cohort_def = f"{cohort_year} cohort, Year {n}"
        elif month_elapsed:
            n = int(month_elapsed.group(1))
            cohort_year = int(year_match.group())
            cohort_start = date(cohort_year, 1, 1)
            period_end = cohort_start + relativedelta(months=n)
            cohort_def = f"{cohort_year} cohort, Month {n}"
        else:
            return None
        return CohortPeriod(
            cohort_def=cohort_def,
            period_start=cohort_start,
            period_end=period_end,
            confidence=0.80,
            requires_review=False,
        )

    def _parse_annotations_regime(
        self,
        chart: ChartData,
        series: ChartSeries | None,
        point: DataPoint | None,
        filing_date: date,
    ) -> CohortPeriod | None:
        if chart.series and any(s.points for s in chart.series):
            return None  # series path should have handled this
        if not chart.annotations:
            return None
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
