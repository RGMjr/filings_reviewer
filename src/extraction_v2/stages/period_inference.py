"""
V2 Period Inference Stage

Stage 8 of the V2 extraction pipeline. Determines time periods for bound values
by analyzing table headers, text context, and filing metadata.

Design principles:
- Rule-based only (no LLM calls)
- Table headers are primary source for table values
- Text context is secondary for text-bound values
- Filing fiscal period is fallback when no context period found
- Conservative approach: flag ambiguous periods for review
"""

from __future__ import annotations

import calendar
import logging
import re
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import TYPE_CHECKING

from src.extraction_v2.exceptions import V2FatalError
from src.extraction_v2.models import (
    BoundValue,
    PeriodType,
)
from src.extraction_v2.text_utils import find_sentence_bounds

if TYPE_CHECKING:
    from src.extraction_v2.models import Segment, Table
    from src.extraction_v2.pipeline import PipelineContext, StageResult

logger = logging.getLogger(__name__)


@dataclass
class ParsedPeriod:
    """Intermediate representation of a parsed period."""

    period_type: PeriodType
    start: date
    end: date
    confidence: float  # 0.0 - 1.0
    source: str  # "header_path", "text_context", "filing_fallback"
    raw_text: str = ""  # Original text that matched


class PeriodInferenceStage:
    """
    Stage 8: Period Inference.

    Determines time periods for bound values using:
    1. Table header_path patterns (primary for table values)
    2. Text context patterns (for text-bound values)
    3. Filing fiscal period fallback

    Confidence scoring:
    - 0.9: Period found in direct header_path
    - 0.7: Period found in nearby text context (same sentence)
    - 0.5: Period found in extended text context
    - 0.3: Filing fiscal period fallback

    Flags ambiguous=True when:
    - No period found at all
    - Multiple conflicting periods detected
    """

    # Confidence levels
    HEADER_PATH_CONFIDENCE: float = 0.9
    SAME_SENTENCE_CONFIDENCE: float = 0.7
    EXTENDED_CONTEXT_CONFIDENCE: float = 0.5
    FILING_FALLBACK_CONFIDENCE: float = 0.3

    # Text search window
    DEFAULT_CONTEXT_CHARS: int = 200

    # Quarter patterns
    # Q1 2024, Q1'24, Q3 '25, 1Q24, 1Q 2024
    QUARTER_PATTERN = re.compile(
        r"""
        (?:
            [Qq]([1-4])[\s']*(\d{4}|\d{2})(?!\d)   # Q1 2024, Q1'24, Q3 '25 (prefer 4-digit)
            |
            ([1-4])[Qq][\s]*(\d{4}|\d{2})(?!\d)    # 1Q24, 1Q 2024
        )
        """,
        re.VERBOSE,
    )

    # Fiscal year patterns
    # FY 2024, FY24, FY'24, Fiscal Year 2024, Fiscal 2024
    FISCAL_YEAR_PATTERN = re.compile(
        r"""
        (?:FY|Fiscal\s+(?:Year\s+)?|fy)[\s']*(\d{4}|\d{2})(?!\d)
        """,
        re.VERBOSE | re.IGNORECASE,
    )

    # Date range patterns
    # Year Ended December 31, 2024
    # For the year ended March 31, 2025
    # Nine Months Ended September 30, 2024
    # Quarter ended June 30, 2024
    PERIOD_ENDED_PATTERN = re.compile(
        r"""
        (?:
            (?:for\s+the\s+)?
            (?:year|quarter|period|
               (?:three|six|nine|twelve|3|6|9|12)\s*months?)
            \s+ended?
        )
        \s+
        (\w+)                                      # Month name
        \s+
        (\d{1,2})                                  # Day
        ,?\s*
        (\d{4})                                    # Year
        """,
        re.VERBOSE | re.IGNORECASE,
    )

    # YTD patterns
    # YTD, Year-to-date, Nine months ended
    YTD_PATTERN = re.compile(
        r"""
        (?:
            YTD
            |
            year[\s-]*to[\s-]*date
            |
            (?:three|six|nine|3|6|9)\s*months?\s+ended?
        )
        """,
        re.VERBOSE | re.IGNORECASE,
    )

    # Trailing patterns
    # TTM, LTM, Trailing Twelve Months, Last Twelve Months
    TRAILING_PATTERN = re.compile(
        r"""
        (?:
            TTM
            |
            LTM
            |
            trailing\s+(?:twelve|12)\s+months?
            |
            last\s+(?:twelve|12)\s+months?
        )
        """,
        re.VERBOSE | re.IGNORECASE,
    )

    # As of date pattern
    # As of December 31, 2024
    # At December 31, 2024
    AS_OF_PATTERN = re.compile(
        r"""
        (?:as\s+of|at)
        \s+
        (\w+)                                      # Month name
        \s+
        (\d{1,2})                                  # Day
        ,?\s*
        (\d{4})                                    # Year
        """,
        re.VERBOSE | re.IGNORECASE,
    )

    # Bare date pattern — matches "Month Day, Year" or "Month Day Year" without prefix.
    # Used only in table header context to recognize quarter-end dates like "January 31, 2017".
    BARE_DATE_PATTERN = re.compile(
        r"""
        (?<!\w)                                    # Word boundary at start
        (january|february|march|april|may|june|july|august|
         september|october|november|december|
         jan|feb|mar|apr|jun|jul|aug|sep|sept|oct|nov|dec)  # Month name
        \s+
        (\d{1,2})                                  # Day (1-31)
        (?:,\s*|\s+)                               # Comma or space separator
        ((?:19|20)\d{2})                           # 4-digit year
        (?!\d)                                     # Not followed by digit
        """,
        re.VERBOSE | re.IGNORECASE,
    )

    # Plain year pattern (with fiscal context required)
    # 2024, 2023 (only when in fiscal context like column headers)
    PLAIN_YEAR_PATTERN = re.compile(r"\b(20\d{2})\b")

    # Month name mapping
    MONTH_NAMES: dict[str, int] = {
        "january": 1,
        "jan": 1,
        "february": 2,
        "feb": 2,
        "march": 3,
        "mar": 3,
        "april": 4,
        "apr": 4,
        "may": 5,
        "june": 6,
        "jun": 6,
        "july": 7,
        "jul": 7,
        "august": 8,
        "aug": 8,
        "september": 9,
        "sep": 9,
        "sept": 9,
        "october": 10,
        "oct": 10,
        "november": 11,
        "nov": 11,
        "december": 12,
        "dec": 12,
    }

    # Quarter end months (calendar year)
    QUARTER_END_MONTHS: dict[int, int] = {1: 3, 2: 6, 3: 9, 4: 12}
    QUARTER_START_MONTHS: dict[int, int] = {1: 1, 2: 4, 3: 7, 4: 10}

    def __init__(self, context_chars: int = 200) -> None:
        """
        Initialize the period inference stage.

        Args:
            context_chars: Number of characters to search around text values (default: 200)
        """
        self.context_chars = context_chars
        # Fiscal year end metadata — set from document in process()
        self._fy_end_month: int | None = None
        self._fy_end_day: int | None = None
        # Filing date — set from document in process(); used instead of date.today()
        self._filing_date: date | None = None

        # Pattern registries: list of (parser_method, confidence_offset) tuples.
        # Ordered by specificity — first match wins.
        # confidence_offset is added to the base confidence for the context.
        self._header_patterns: list[tuple[str, float]] = [
            ("_try_parse_period_ended", 0.0),
            ("_try_parse_quarter", 0.0),
            ("_try_parse_trailing", 0.0),
            ("_try_parse_ytd", 0.0),
            ("_try_parse_fiscal_year", 0.0),
            ("_try_parse_as_of", 0.0),
            ("_try_parse_bare_date", 0.0),
            ("_try_parse_plain_year", -0.1),
        ]

        # Text patterns: subset used for text context (no bare_date or plain_year).
        self._text_patterns: list[str] = [
            "_try_parse_period_ended",
            "_try_parse_quarter",
            "_try_parse_trailing",
            "_try_parse_ytd",
            "_try_parse_fiscal_year",
            "_try_parse_as_of",
        ]

    def process(self, context: PipelineContext) -> StageResult:
        """
        Infer time periods for all bound values.

        Args:
            context: Pipeline context with bound_values and document metadata

        Returns:
            StageResult with processing metrics
        """
        try:
            start_time = datetime.now(UTC)
            periods_inferred = 0
            ambiguous_count = 0
            errors: list[str] = []
            warnings: list[str] = []

            # Get filing fiscal period for fallback
            fiscal_year = context.document.fiscal_year if context.document else None
            fiscal_period = context.document.fiscal_period if context.document else ""

            # Load fiscal year end metadata from document (set by IngestionStage)
            self._fy_end_month = (
                context.document.fiscal_year_end_month if context.document else None
            )
            self._fy_end_day = context.document.fiscal_year_end_day if context.document else None
            # Prefer filing date from document over date.today() for determinism
            self._filing_date = context.document.filing_date if context.document else None

            # Process each bound value
            for bound_value in context.bound_values:
                try:
                    period = self._infer_period(
                        bound_value,
                        context,
                        fiscal_year,
                        fiscal_period,
                    )
                    if period:
                        bound_value.period_type = period.period_type
                        bound_value.period_start = period.start
                        bound_value.period_end = period.end
                        bound_value.period_confidence = period.confidence
                        bound_value.period_source = period.source
                        bound_value.period_ambiguous = False
                        periods_inferred += 1
                    else:
                        # No period found - flag as ambiguous
                        bound_value.period_type = PeriodType.OTHER
                        bound_value.period_ambiguous = True
                        ambiguous_count += 1
                        warnings.append(
                            f"No period found for bound value {bound_value.bound_value_id}"
                        )
                except Exception as e:
                    error_msg = f"Error inferring period for {bound_value.bound_value_id}: {e}"
                    logger.error(error_msg)
                    errors.append(error_msg)

            logger.info(
                f"Period inference complete: {periods_inferred} inferred, "
                f"{ambiguous_count} ambiguous from {len(context.bound_values)} values"
            )

            return self._make_result(
                start_time,
                len(context.bound_values),
                periods_inferred,
                errors,
                warnings,
                ambiguous_count,
            )
        except V2FatalError:
            raise
        except Exception as e:
            raise V2FatalError(str(e), stage_name="period_inference") from e

    def _infer_period(
        self,
        bound_value: BoundValue,
        context: PipelineContext,
        fiscal_year: int | None,
        fiscal_period: str,
    ) -> ParsedPeriod | None:
        """
        Infer the period for a single bound value.

        Args:
            bound_value: The bound value to process
            context: Pipeline context with segment_by_id and table_by_id lookups
            fiscal_year: Filing fiscal year for fallback
            fiscal_period: Filing fiscal period for fallback

        Returns:
            ParsedPeriod if found, None otherwise
        """
        # Get the evidence pack for header_path if available
        # Note: BoundValue doesn't directly have header_path, but we can get it from the table
        loc = bound_value.source_locator

        # Strategy 0: Use pre-parsed period_hint from respectively pattern
        if bound_value.period_hint:
            period = self._parse_period_from_hint(bound_value.period_hint)
            if period:
                return period

        # Strategy 1: Check table header_path (primary for table values)
        if loc.table_id:
            table = context.table_by_id.get(loc.table_id)
            if table and loc.cell_col is not None:
                header_path = table.get_header_path(loc.cell_col)
                period = self._parse_period_from_headers(header_path)
                if period:
                    return period

        # Strategy 2: Check text context for text-bound values
        if loc.segment_id:
            segment = context.segment_by_id.get(loc.segment_id)
            if segment and segment.text:
                period = self._parse_period_from_text(
                    segment.text,
                    loc.text_span,
                )
                if period:
                    return period

        # Strategy 3: Filing fiscal period fallback
        if fiscal_year:
            period = self._create_fiscal_fallback(fiscal_year, fiscal_period)
            if period:
                return period

        return None

    def _parse_period_from_hint(self, hint: str) -> ParsedPeriod | None:
        """
        Parse a period from a pre-extracted hint string (e.g., "2017", "Q1").

        Used by Strategy 0 to resolve periods pre-associated by the respectively parser.
        Sets confidence=0.85 and source="respectively_hint".
        """
        # Try standard text patterns first (handles "Q1 2017", "FY 2017", etc.)
        period = self._try_parse_all_patterns(hint)
        if period is None:
            # Fall back to plain year pattern (handles bare "2017")
            period = self._try_parse_plain_year(hint)
        if period:
            period.confidence = 0.85
            period.source = "respectively_hint"
            return period
        return None

    def _parse_period_from_headers(self, header_path: list[str]) -> ParsedPeriod | None:
        """
        Parse period from table header path.

        Searches all header levels, preferring more specific periods (quarters over years).

        Args:
            header_path: List of header texts from column headers

        Returns:
            ParsedPeriod if found, None otherwise
        """
        # Combine all headers for searching; strip zero-width spaces
        combined_text = self._normalize_text(" ".join(header_path))

        # Try patterns in order of specificity (first match wins)
        for method_name, confidence_offset in self._header_patterns:
            parser = getattr(self, method_name)
            period = parser(combined_text)
            if period:
                period.source = "header_path"
                period.confidence = self.HEADER_PATH_CONFIDENCE + confidence_offset
                return period

        return None

    def _parse_period_from_text(
        self,
        text: str,
        text_span: tuple[int, int] | None,
    ) -> ParsedPeriod | None:
        """
        Parse period from text context around a value.

        Args:
            text: Full segment text
            text_span: (start, end) character offsets of the value

        Returns:
            ParsedPeriod if found, None otherwise
        """
        if text_span:
            start, end = text_span
            # Search in window around the value
            window_start = max(0, start - self.context_chars)
            window_end = min(len(text), end + self.context_chars)
            search_text = text[window_start:window_end]

            # Check if match is in same sentence for higher confidence
            sentence_start, sentence_end = find_sentence_bounds(text, start)
            same_sentence_text = text[sentence_start:sentence_end]
        else:
            search_text = text[: self.context_chars * 2]
            same_sentence_text = ""

        # Try to find period in same sentence first (higher confidence)
        if same_sentence_text:
            period = self._try_parse_all_patterns(same_sentence_text)
            if period:
                period.source = "text_context"
                period.confidence = self.SAME_SENTENCE_CONFIDENCE
                return period

        # Try extended context (lower confidence)
        period = self._try_parse_all_patterns(search_text)
        if period:
            period.source = "text_context"
            period.confidence = self.EXTENDED_CONTEXT_CONFIDENCE
            return period

        return None

    @staticmethod
    def _normalize_text(text: str) -> str:
        """Strip zero-width spaces and collapse surrounding whitespace for pattern matching."""
        return text.replace("\u200b", "")

    def _try_parse_all_patterns(self, text: str) -> ParsedPeriod | None:
        """Try all text period patterns on text, returning most specific match."""
        normalized = self._normalize_text(text)
        for method_name in self._text_patterns:
            parser = getattr(self, method_name)
            period = parser(normalized)
            if period:
                return period
        return None

    def _try_parse_quarter(self, text: str) -> ParsedPeriod | None:
        """
        Parse quarter pattern from text.

        Examples: Q1 2024, Q1'24, 1Q24

        Returns:
            ParsedPeriod with QUARTERLY type, or None
        """
        match = self.QUARTER_PATTERN.search(text)
        if not match:
            return None

        # Determine which group matched
        if match.group(1):  # Q1 2024 format
            quarter = int(match.group(1))
            year_str = match.group(2)
        else:  # 1Q24 format
            quarter = int(match.group(3))
            year_str = match.group(4)

        year = self._normalize_year(year_str)
        if not year:
            return None

        try:
            start_month = self.QUARTER_START_MONTHS[quarter]
            end_month = self.QUARTER_END_MONTHS[quarter]
            start = date(year, start_month, 1)
            end = date(year, end_month, self._last_day_of_month(year, end_month))
            return ParsedPeriod(
                period_type=PeriodType.QUARTERLY,
                start=start,
                end=end,
                confidence=0.0,  # Will be set by caller
                source="",  # Will be set by caller
                raw_text=match.group(0),
            )
        except ValueError:
            return None

    def _try_parse_fiscal_year(self, text: str) -> ParsedPeriod | None:
        """
        Parse fiscal year pattern from text.

        Examples: FY 2024, FY24, Fiscal Year 2024

        Uses filing metadata (fiscal_year_end_month/day) when available to compute
        accurate non-calendar fiscal year boundaries. Falls back to calendar year
        (Jan 1 - Dec 31) when metadata is unavailable.

        Returns:
            ParsedPeriod with ANNUAL type, or None
        """
        match = self.FISCAL_YEAR_PATTERN.search(text)
        if not match:
            return None

        year = self._normalize_year(match.group(1))
        if not year:
            return None

        try:
            fy_end_month = self._fy_end_month
            fy_end_day = self._fy_end_day

            if fy_end_month is not None:
                # Use filing-specific fiscal year end date
                end_day = (
                    fy_end_day
                    if fy_end_day is not None
                    else calendar.monthrange(year, fy_end_month)[1]
                )
                end = date(year, fy_end_month, end_day)

                if fy_end_month == 12 and end_day == 31:
                    # Standard calendar year ending Dec 31
                    start = date(year, 1, 1)
                else:
                    # Non-calendar FY: starts on the first day of the month
                    # after the fiscal year end month, one year prior.
                    # e.g., FY2020 ending Jan 31 2020 → starts Feb 1 2019
                    # e.g., FY2020 ending Mar 31 2020 → starts Apr 1 2019
                    start_month = (fy_end_month % 12) + 1  # next month (wraps 12→1)
                    start_year = year - 1 if fy_end_month < 12 else year
                    start = date(start_year, start_month, 1)
            else:
                # Calendar year fallback (Jan 1 - Dec 31)
                start = date(year, 1, 1)
                end = date(year, 12, 31)

            return ParsedPeriod(
                period_type=PeriodType.ANNUAL,
                start=start,
                end=end,
                confidence=0.0,
                source="",
                raw_text=match.group(0),
            )
        except ValueError:
            return None

    def _try_parse_period_ended(self, text: str) -> ParsedPeriod | None:
        """
        Parse "period ended" patterns from text.

        Examples:
        - Year Ended December 31, 2024
        - Nine Months Ended September 30, 2024
        - Quarter ended June 30, 2024

        Returns:
            ParsedPeriod with appropriate type, or None
        """
        match = self.PERIOD_ENDED_PATTERN.search(text)
        if not match:
            return None

        month_name = match.group(1).lower()
        day = int(match.group(2))
        year = int(match.group(3))

        month = self.MONTH_NAMES.get(month_name)
        if not month:
            return None

        try:
            end = date(year, month, day)
        except ValueError:
            return None

        # Determine period type from the pattern prefix.
        # Normalize NBSP (\xa0) so "six\xa0months" matches "six months" etc.
        text_lower = text.lower().replace("\xa0", " ")

        if "year" in text_lower[: match.end()]:
            period_type = PeriodType.ANNUAL
            # Adjust for calendar year
            if month == 12 and day == 31:
                start = date(year, 1, 1)
            else:
                # Non-calendar fiscal year: start is the day after the previous year's end
                # e.g., "year ended March 31, 2025" starts April 1, 2024
                if month < 12:
                    start = date(year - 1, month + 1, 1)
                else:
                    start = date(year, 1, 1)
        elif any(x in text_lower[: match.end()] for x in ["quarter", "three months", "3 months"]):
            period_type = PeriodType.QUARTERLY
            start = self._period_start(month, year, 3)
        elif any(x in text_lower[: match.end()] for x in ["nine months", "9 months"]):
            period_type = PeriodType.YTD
            start = self._period_start(month, year, 9)
        elif any(x in text_lower[: match.end()] for x in ["six months", "6 months"]):
            period_type = PeriodType.YTD
            start = self._period_start(month, year, 6)
        else:
            # Default to annual
            period_type = PeriodType.ANNUAL
            start = date(year, 1, 1)

        return ParsedPeriod(
            period_type=period_type,
            start=start,
            end=end,
            confidence=0.0,
            source="",
            raw_text=match.group(0),
        )

    def _period_start(self, end_month: int, end_year: int, n_months: int) -> date:
        """Return the first day of the period that ends in end_month/end_year and spans n_months.

        Uses start_month = end_month - (n_months - 1) so that the period includes
        end_month itself (e.g., 3-month period ending June → starts April 1).
        """
        start_month = end_month - (n_months - 1)
        start_year = end_year
        if start_month <= 0:
            start_month += 12
            start_year -= 1
        return date(start_year, start_month, 1)

    def _try_parse_ytd(self, text: str) -> ParsedPeriod | None:
        """
        Parse YTD patterns from text.

        Note: YTD patterns often need additional context to determine the end date.
        Returns a partial period that may need filing date to complete.

        Returns:
            ParsedPeriod with YTD type, or None
        """
        match = self.YTD_PATTERN.search(text)
        if not match:
            return None

        # Try to find an associated year in nearby text
        year_match = self.PLAIN_YEAR_PATTERN.search(text)
        if year_match:
            year = int(year_match.group(1))
        else:
            # Use filing date (or date.today() as last resort) for determinism
            reference = self._filing_date or date.today()
            year = reference.year

        # Determine period length from pattern
        text_lower = match.group(0).lower()
        reference = self._filing_date or date.today()

        if "nine" in text_lower or "9" in text_lower:
            # Nine months YTD (typically ends Sep 30)
            end_month = 9
        elif "six" in text_lower or "6" in text_lower:
            # Six months YTD (typically ends Jun 30)
            end_month = 6
        elif "three" in text_lower or "3" in text_lower:
            # Three months YTD (typically ends Mar 31)
            end_month = 3
        else:
            # Generic YTD - use current quarter end or filing date
            end_month = ((reference.month - 1) // 3 + 1) * 3

        try:
            start = date(year, 1, 1)
            end = date(year, end_month, self._last_day_of_month(year, end_month))
            return ParsedPeriod(
                period_type=PeriodType.YTD,
                start=start,
                end=end,
                confidence=0.0,
                source="",
                raw_text=match.group(0),
            )
        except ValueError:
            return None

    def _try_parse_trailing(self, text: str) -> ParsedPeriod | None:
        """
        Parse trailing period patterns (TTM, LTM).

        Note: Trailing periods need a reference date. We look for an associated date
        or use filing date context.

        Returns:
            ParsedPeriod with TRAILING type, or None
        """
        match = self.TRAILING_PATTERN.search(text)
        if not match:
            return None

        # Try to find an associated date in nearby text
        as_of_match = self.AS_OF_PATTERN.search(text)
        if as_of_match:
            month_name = as_of_match.group(1).lower()
            day = int(as_of_match.group(2))
            year = int(as_of_match.group(3))
            month = self.MONTH_NAMES.get(month_name)
            if month:
                try:
                    end = date(year, month, day)
                    # TTM is 12 months trailing: start is the day after the
                    # same date one year prior. Clamp day to the last valid
                    # day of that month (handles Feb 29 → Feb 28 in non-leap).
                    prev_year = year - 1
                    max_day = calendar.monthrange(prev_year, month)[1]
                    same_day_prev_year = date(prev_year, month, min(day, max_day))
                    start = same_day_prev_year + timedelta(days=1)
                    return ParsedPeriod(
                        period_type=PeriodType.TRAILING,
                        start=start,
                        end=end,
                        confidence=0.0,
                        source="",
                        raw_text=match.group(0),
                    )
                except ValueError:
                    pass

        # Without a reference date, use filing date (or date.today() as last resort)
        reference = self._filing_date or date.today()
        prev_year = reference.year - 1
        max_day = calendar.monthrange(prev_year, reference.month)[1]
        same_day_prev_year = date(prev_year, reference.month, min(reference.day, max_day))
        start = same_day_prev_year + timedelta(days=1)
        return ParsedPeriod(
            period_type=PeriodType.TRAILING,
            start=start,
            end=reference,
            confidence=0.0,
            source="",
            raw_text=match.group(0),
        )

    def _try_parse_as_of(self, text: str) -> ParsedPeriod | None:
        """
        Parse "as of" date patterns.

        Examples: As of December 31, 2024

        Returns:
            ParsedPeriod with POINT_IN_TIME type, or None
        """
        match = self.AS_OF_PATTERN.search(text)
        if not match:
            return None

        month_name = match.group(1).lower()
        day = int(match.group(2))
        year = int(match.group(3))

        month = self.MONTH_NAMES.get(month_name)
        if not month:
            return None

        try:
            point_date = date(year, month, day)
            return ParsedPeriod(
                period_type=PeriodType.POINT_IN_TIME,
                start=point_date,
                end=point_date,
                confidence=0.0,
                source="",
                raw_text=match.group(0),
            )
        except ValueError:
            return None

    def _try_parse_bare_date(self, text: str) -> ParsedPeriod | None:
        """
        Parse bare date patterns without a leading "As of" or period-type prefix.

        Examples: "January 31, 2017", "Jan 31 2017"

        Used only in table header context to recognise quarter-end / year-end column
        headings that omit the "As of" prefix (common in Slack-style quarterly tables).

        Returns:
            ParsedPeriod with POINT_IN_TIME type, or None
        """
        match = self.BARE_DATE_PATTERN.search(text)
        if not match:
            return None

        month_name = match.group(1).lower()
        day = int(match.group(2))
        year = int(match.group(3))

        month = self.MONTH_NAMES.get(month_name)
        if not month:
            return None

        try:
            point_date = date(year, month, day)
            return ParsedPeriod(
                period_type=PeriodType.POINT_IN_TIME,
                start=point_date,
                end=point_date,
                confidence=0.0,
                source="",
                raw_text=match.group(0),
            )
        except ValueError:
            return None

    def _try_parse_plain_year(self, text: str) -> ParsedPeriod | None:
        """
        Parse plain year as fiscal year (only in header context).

        Examples: 2024, 2023

        Returns:
            ParsedPeriod with ANNUAL type, or None
        """
        match = self.PLAIN_YEAR_PATTERN.search(text)
        if not match:
            return None

        year = int(match.group(1))

        try:
            start = date(year, 1, 1)
            end = date(year, 12, 31)
            return ParsedPeriod(
                period_type=PeriodType.ANNUAL,
                start=start,
                end=end,
                confidence=0.0,
                source="",
                raw_text=match.group(0),
            )
        except ValueError:
            return None

    def _create_fiscal_fallback(self, fiscal_year: int, fiscal_period: str) -> ParsedPeriod | None:
        """
        Create a period from filing fiscal metadata as fallback.

        Args:
            fiscal_year: Filing fiscal year
            fiscal_period: Filing fiscal period (FY, Q1, Q2, Q3, Q4)

        Returns:
            ParsedPeriod with FILING_FALLBACK_CONFIDENCE, or None
        """
        fiscal_period_upper = fiscal_period.upper()

        try:
            if fiscal_period_upper in ("FY", ""):
                return ParsedPeriod(
                    period_type=PeriodType.ANNUAL,
                    start=date(fiscal_year, 1, 1),
                    end=date(fiscal_year, 12, 31),
                    confidence=self.FILING_FALLBACK_CONFIDENCE,
                    source="filing_fallback",
                    raw_text=f"FY {fiscal_year}",
                )
            elif fiscal_period_upper in ("Q1", "Q2", "Q3", "Q4"):
                quarter = int(fiscal_period_upper[1])
                start_month = self.QUARTER_START_MONTHS[quarter]
                end_month = self.QUARTER_END_MONTHS[quarter]
                return ParsedPeriod(
                    period_type=PeriodType.QUARTERLY,
                    start=date(fiscal_year, start_month, 1),
                    end=date(
                        fiscal_year, end_month, self._last_day_of_month(fiscal_year, end_month)
                    ),
                    confidence=self.FILING_FALLBACK_CONFIDENCE,
                    source="filing_fallback",
                    raw_text=f"{fiscal_period_upper} {fiscal_year}",
                )
        except ValueError:
            return None

        return None

    def _normalize_year(self, year_str: str) -> int | None:
        """
        Normalize 2-digit or 4-digit year string to 4-digit year.

        Args:
            year_str: Year string like "24" or "2024"

        Returns:
            4-digit year integer, or None if invalid
        """
        try:
            year = int(year_str)
            if year < 100:
                # 2-digit year: 00-30 -> 2000-2030, 31-99 -> 1931-1999
                if year <= 30:
                    year += 2000
                else:
                    year += 1900
            return year if 1900 <= year <= 2100 else None
        except ValueError:
            return None

    def _last_day_of_month(self, year: int, month: int) -> int:
        """Get the last day of a month."""
        return calendar.monthrange(year, month)[1]

    def _make_result(
        self,
        start_time: datetime,
        items_processed: int,
        items_output: int,
        errors: list[str],
        warnings: list[str],
        ambiguous_count: int,
    ) -> StageResult:
        """Create a StageResult with timing info."""
        end_time = datetime.now(UTC)
        duration_ms = int((end_time - start_time).total_seconds() * 1000)

        # Import at runtime to avoid circular import
        from src.extraction_v2.pipeline import PipelineStage, StageResult

        return StageResult(
            stage=PipelineStage.PERIOD_INFERENCE,
            success=len(errors) == 0,
            duration_ms=duration_ms,
            items_processed=items_processed,
            items_output=items_output,
            errors=errors,
            warnings=warnings,
            metadata={
                "ambiguous_count": ambiguous_count,
                "periods_by_type": {},  # Could track counts per period type
            },
        )
