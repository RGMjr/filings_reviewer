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
from datetime import date, datetime
from typing import TYPE_CHECKING

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
    # FY 2024, FY24, FY'24, FY'25, Fiscal Year 2024, Fiscal 2024, fiscal year '25
    # Also: "full year 2025", "full year results" (common transcript language)
    FISCAL_YEAR_PATTERN = re.compile(
        r"""
        (?:FY|Fiscal\s+(?:Year\s+)?|fy|full\s+year)[\s]*['\u2019]?[\s]*(\d{4}|\d{2})(?!\d)
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

    # Quarter-without-year pattern — standalone Q1, Q2, Q3, Q4 (no year attached)
    # Used in transcripts where "in Q4" is said without specifying the year
    QUARTER_STANDALONE_PATTERN = re.compile(
        r"\b[Qq]([1-4])\b(?!\s*[\'\u2019]?\s*\d)",
    )

    # Relative period patterns — "this quarter", "last quarter", "prior quarter"
    RELATIVE_QUARTER_PATTERN = re.compile(
        r"\b(this|last|prior|previous|current)\s+quarter\b",
        re.IGNORECASE,
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
        start_time = datetime.utcnow()
        periods_inferred = 0
        ambiguous_count = 0
        errors: list[str] = []
        warnings: list[str] = []

        # Get filing fiscal period for fallback
        fiscal_year = context.document.fiscal_year if context.document else None
        fiscal_period = context.document.fiscal_period if context.document else ""

        # Get document_date for transcript quarter inference (must be a real date)
        raw_doc_date = getattr(context, "document_date", None)
        document_date: date | None = raw_doc_date if isinstance(raw_doc_date, date) else None

        # Load fiscal year end metadata from document (set by IngestionStage)
        self._fy_end_month = context.document.fiscal_year_end_month if context.document else None
        self._fy_end_day = context.document.fiscal_year_end_day if context.document else None

        # Build lookup for segments and tables
        segment_lookup = {s.segment_id: s for s in context.segments}
        table_lookup = {t.table_id: t for t in context.tables}

        # Process each bound value
        for bound_value in context.bound_values:
            try:
                period = self._infer_period(
                    bound_value,
                    segment_lookup,
                    table_lookup,
                    fiscal_year,
                    fiscal_period,
                    document_date=document_date,
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
                    warnings.append(f"No period found for bound value {bound_value.bound_value_id}")
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

    def _infer_period(
        self,
        bound_value: BoundValue,
        segment_lookup: dict[str, Segment],
        table_lookup: dict[str, Table],
        fiscal_year: int | None,
        fiscal_period: str,
        document_date: date | None = None,
    ) -> ParsedPeriod | None:
        """
        Infer the period for a single bound value.

        Args:
            bound_value: The bound value to process
            segment_lookup: Segment ID -> Segment mapping
            table_lookup: Table ID -> Table mapping
            fiscal_year: Filing fiscal year for fallback
            fiscal_period: Filing fiscal period for fallback
            document_date: Document date (for transcript quarter inference)

        Returns:
            ParsedPeriod if found, None otherwise
        """
        # Get the evidence pack for header_path if available
        # Note: BoundValue doesn't directly have header_path, but we can get it from the table
        loc = bound_value.source_locator

        # Strategy 1: Check table header_path (primary for table values)
        if loc.table_id:
            table = table_lookup.get(loc.table_id)
            if table and loc.cell_col is not None:
                header_path = table.get_header_path(loc.cell_col)
                period = self._parse_period_from_headers(header_path)
                if period:
                    return period

        # Strategy 2: Check text context for text-bound values
        if loc.segment_id:
            segment = segment_lookup.get(loc.segment_id)
            if segment and segment.text:
                period = self._parse_period_from_text(
                    segment.text,
                    loc.text_span,
                    document_date=document_date,
                )
                if period:
                    return period

        # Strategy 3: Filing fiscal period fallback
        if fiscal_year:
            period = self._create_fiscal_fallback(fiscal_year, fiscal_period)
            if period:
                return period

        # Strategy 4: Document-date fallback (for transcripts without fiscal metadata)
        if document_date:
            period = self._create_document_date_fallback(document_date)
            if period:
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
        # Combine all headers for searching
        combined_text = " ".join(header_path)

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
        document_date: date | None = None,
    ) -> ParsedPeriod | None:
        """
        Parse period from text context around a value.

        Args:
            text: Full segment text
            text_span: (start, end) character offsets of the value
            document_date: Document date for resolving standalone quarters and relative periods

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

            # Try transcript-specific patterns (standalone quarter, relative quarter)
            if document_date:
                period = self._try_parse_standalone_quarter(same_sentence_text, document_date)
                if period:
                    period.source = "text_context"
                    period.confidence = self.SAME_SENTENCE_CONFIDENCE
                    return period

                period = self._try_parse_relative_quarter(same_sentence_text, document_date)
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

        # Try transcript-specific patterns in extended context
        if document_date:
            period = self._try_parse_standalone_quarter(search_text, document_date)
            if period:
                period.source = "text_context"
                period.confidence = self.EXTENDED_CONTEXT_CONFIDENCE
                return period

            period = self._try_parse_relative_quarter(search_text, document_date)
            if period:
                period.source = "text_context"
                period.confidence = self.EXTENDED_CONTEXT_CONFIDENCE
                return period

        return None

    def _try_parse_all_patterns(self, text: str) -> ParsedPeriod | None:
        """Try all text period patterns on text, returning most specific match."""
        for method_name in self._text_patterns:
            parser = getattr(self, method_name)
            period = parser(text)
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

        # Determine period type from the pattern prefix
        text_lower = text.lower()

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
            # Calculate start as 3 months before end
            if month >= 4:
                start = date(year, month - 3, 1)
            else:
                start = date(year - 1, month + 9, 1)
        elif any(x in text_lower[: match.end()] for x in ["nine months", "9 months"]):
            period_type = PeriodType.YTD
            # Calculate start as 9 months before end
            if month >= 10:
                start = date(year, month - 9, 1)
            else:
                start = date(year - 1, month + 3, 1)
        elif any(x in text_lower[: match.end()] for x in ["six months", "6 months"]):
            period_type = PeriodType.YTD
            # Calculate start as 6 months before end
            if month >= 7:
                start = date(year, month - 6, 1)
            else:
                start = date(year - 1, month + 6, 1)
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
            # Use current year as fallback
            year = date.today().year

        # Determine period length from pattern
        text_lower = match.group(0).lower()
        today = date.today()

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
            end_month = ((today.month - 1) // 3 + 1) * 3

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
                    # TTM is 12 months trailing
                    start = (
                        date(year - 1, month, day + 1)
                        if day < 28
                        else date(year - 1, month + 1, 1)
                        if month < 12
                        else date(year - 1, 1, 1)
                    )
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

        # Without a reference date, we can't determine the exact period
        # Return a placeholder with today's date (will be lower confidence)
        today = date.today()
        start = date(today.year - 1, today.month, today.day)
        return ParsedPeriod(
            period_type=PeriodType.TRAILING,
            start=start,
            end=today,
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

    def _try_parse_standalone_quarter(
        self, text: str, document_date: date
    ) -> ParsedPeriod | None:
        """
        Parse standalone quarter (e.g., "in Q4") using document_date for the year.

        Only used when document_date is available (typically transcripts).

        Args:
            text: Text to search
            document_date: Document date to infer year

        Returns:
            ParsedPeriod with QUARTERLY type, or None
        """
        match = self.QUARTER_STANDALONE_PATTERN.search(text)
        if not match:
            return None

        quarter = int(match.group(1))
        year = document_date.year

        try:
            start_month = self.QUARTER_START_MONTHS[quarter]
            end_month = self.QUARTER_END_MONTHS[quarter]
            start = date(year, start_month, 1)
            end = date(year, end_month, self._last_day_of_month(year, end_month))
            return ParsedPeriod(
                period_type=PeriodType.QUARTERLY,
                start=start,
                end=end,
                confidence=0.0,  # Set by caller
                source="",
                raw_text=match.group(0),
            )
        except ValueError:
            return None

    def _try_parse_relative_quarter(
        self, text: str, document_date: date
    ) -> ParsedPeriod | None:
        """
        Parse relative quarter patterns ("this quarter", "last quarter").

        Args:
            text: Text to search
            document_date: Document date to resolve relative references

        Returns:
            ParsedPeriod with QUARTERLY type, or None
        """
        match = self.RELATIVE_QUARTER_PATTERN.search(text)
        if not match:
            return None

        relative = match.group(1).lower()

        # Current quarter from document_date
        current_q = (document_date.month - 1) // 3 + 1
        year = document_date.year

        if relative in ("this", "current"):
            quarter = current_q
        elif relative in ("last", "prior", "previous"):
            quarter = current_q - 1
            if quarter < 1:
                quarter = 4
                year -= 1
        else:
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
                confidence=0.0,
                source="",
                raw_text=match.group(0),
            )
        except ValueError:
            return None

    def _create_document_date_fallback(
        self, document_date: date
    ) -> ParsedPeriod | None:
        """
        Create a period from document_date as last-resort fallback.

        Infers the current quarter from the document date.

        Args:
            document_date: Document date

        Returns:
            ParsedPeriod with FILING_FALLBACK_CONFIDENCE, or None
        """
        quarter = (document_date.month - 1) // 3 + 1
        year = document_date.year

        try:
            start_month = self.QUARTER_START_MONTHS[quarter]
            end_month = self.QUARTER_END_MONTHS[quarter]
            return ParsedPeriod(
                period_type=PeriodType.QUARTERLY,
                start=date(year, start_month, 1),
                end=date(year, end_month, self._last_day_of_month(year, end_month)),
                confidence=self.FILING_FALLBACK_CONFIDENCE,
                source="document_date_fallback",
                raw_text=f"Q{quarter} {year} (from document date)",
            )
        except ValueError:
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
        end_time = datetime.utcnow()
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
