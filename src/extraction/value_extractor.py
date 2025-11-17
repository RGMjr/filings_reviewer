"""
Value Extractor - Extract numeric metric values from segments.

This module extracts quantitative metric values from classified segments,
particularly focusing on table data with cohort breakdowns.
"""

import logging
import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import List, Optional, Tuple
from bs4 import BeautifulSoup

from .models import SourceSegment, MetricValue

logger = logging.getLogger(__name__)


class ValueExtractor:
    """
    Extract metric values from source segments.

    Focuses on:
    1. Table extraction (most reliable for cohort breakdowns)
    2. Text extraction (fallback for simple disclosures)
    3. Period parsing (fiscal quarters, years)
    4. Cohort label normalization
    """

    # Number patterns
    NUMBER_PATTERN = r'[-]?\$?\s*(\d{1,3}(?:,\d{3})*(?:\.\d+)?)\s*(?:million|billion|thousand|%)?'

    # Period patterns
    QUARTER_PATTERN = r'[qQ]([1-4])\s+(\d{4})'
    YEAR_PATTERN = r'(?:FY|fy)?\s*(\d{4})'

    # Cohort patterns
    ACQUISITION_COHORT_PATTERN = r'(\d{4})\s+[Cc]ohort'
    TENURE_COHORT_PATTERNS = [
        (r'(\d+)\s*-\s*(\d+)\s+(?:months?|mos?)', 'months'),
        (r'(\d+)\s*-\s*(\d+)\s+years?', 'years'),
        (r'(\d+)\+\s+years?', 'years_plus'),
        (r'<\s*(\d+)\s+(?:months?|years?)', 'less_than'),
    ]

    def __init__(self):
        """Initialize the value extractor."""
        self._number_regex = re.compile(self.NUMBER_PATTERN, re.IGNORECASE)
        self._quarter_regex = re.compile(self.QUARTER_PATTERN)
        self._year_regex = re.compile(self.YEAR_PATTERN)
        self._acquisition_cohort_regex = re.compile(self.ACQUISITION_COHORT_PATTERN)

    def extract_from_segment(
        self,
        segment: SourceSegment,
        company_id: int
    ) -> List[MetricValue]:
        """
        Extract all metric values from a segment.

        Args:
            segment: Classified source segment
            company_id: Company ID for the filing

        Returns:
            List of MetricValue objects (may be multiple per segment)
        """
        # Only extract from segments with numeric disclosure flag
        if not segment.contains_numeric_disclosure_flag:
            return []

        # Route to appropriate extractor
        if segment.segment_type == 'table':
            return self.extract_from_table(segment, company_id)
        else:
            return self.extract_from_text(segment, company_id)

    def extract_from_table(
        self,
        segment: SourceSegment,
        company_id: int
    ) -> List[MetricValue]:
        """
        Extract structured data from table segments.

        Args:
            segment: Table segment
            company_id: Company ID

        Returns:
            List of MetricValue objects extracted from the table
        """
        if not segment.raw_html:
            logger.warning(f"No raw HTML for table segment {segment.source_segment_id}")
            return []

        # Parse table with BeautifulSoup
        soup = BeautifulSoup(segment.raw_html, 'html.parser')
        table = soup.find('table')
        if not table:
            logger.warning(f"No table found in segment {segment.source_segment_id}")
            return []

        # Extract table structure
        rows = table.find_all('tr')
        if len(rows) < 2:  # Need at least header + 1 data row
            return []

        # Parse header row to identify columns
        header_row = rows[0]
        headers = [self._clean_text(cell.get_text()) for cell in header_row.find_all(['th', 'td'])]

        # Identify column types
        column_info = self._identify_columns(headers)

        # Parse data rows
        values = []
        for row in rows[1:]:
            cells = row.find_all(['td', 'th'])
            if len(cells) != len(headers):
                continue  # Skip malformed rows

            row_values = self._parse_table_row(
                cells,
                headers,
                column_info,
                segment,
                company_id
            )
            values.extend(row_values)

        logger.info(f"Extracted {len(values)} values from table segment {segment.source_segment_id}")
        return values

    def extract_from_text(
        self,
        segment: SourceSegment,
        company_id: int
    ) -> List[MetricValue]:
        """
        Extract values from text segments using pattern matching.

        Args:
            segment: Text segment
            company_id: Company ID

        Returns:
            List of MetricValue objects
        """
        values = []

        # For each candidate metric, look for associated numbers
        for metric_id in segment.candidate_metric_ids:
            # Find numbers in the text
            numbers = self._number_regex.findall(segment.raw_text)

            if numbers:
                # Create a value for the first number found
                # (in production, would use more sophisticated matching)
                value_str = numbers[0]
                numeric_value = self._parse_number(value_str)

                if numeric_value is not None:
                    # Try to extract period
                    period_end = self._extract_period_from_text(segment.raw_text)

                    value = MetricValue(
                        filing_id=segment.filing_id,
                        company_id=company_id,
                        metric_id=metric_id,
                        source_segment_id=segment.sequence_index,  # Store sequence_index temporarily
                        source_type='text',
                        extraction_method='rule_text',
                        value_numeric=numeric_value,
                        value_text=value_str,
                        period_end=period_end,
                        qa_status='unreviewed',
                    )
                    values.append(value)
                    break  # Only extract one value per segment for now

        return values

    def _identify_columns(self, headers: List[str]) -> dict:
        """
        Identify the type of each column based on header text.

        Returns:
            Dictionary mapping column index to column type:
            - 'cohort': Column contains cohort labels
            - 'period': Column contains period labels
            - 'value': Column contains numeric values
        """
        column_info = {}

        for i, header in enumerate(headers):
            header_lower = header.lower()

            # Cohort column indicators
            if any(kw in header_lower for kw in ['cohort', 'vintage', 'year acquired']):
                column_info[i] = {'type': 'cohort'}

            # Period column indicators (Q1 2024, FY 2023, etc.)
            elif re.search(r'[qQ]\d|FY|20\d{2}', header):
                period_end = self._extract_period_from_text(header)
                column_info[i] = {'type': 'value', 'period_end': period_end}

            # Default to value column
            else:
                column_info[i] = {'type': 'value', 'period_end': None}

        return column_info

    def _parse_table_row(
        self,
        cells: list,
        headers: List[str],
        column_info: dict,
        segment: SourceSegment,
        company_id: int
    ) -> List[MetricValue]:
        """
        Parse a single table row to extract metric values.

        Args:
            cells: List of table cells
            headers: List of header labels
            column_info: Column type information
            segment: Source segment
            company_id: Company ID

        Returns:
            List of MetricValue objects from this row
        """
        values = []

        # Extract cohort label from first column if it's a cohort column
        cohort_label = None
        cohort_type = None
        cohort_normalized = None

        for i, info in column_info.items():
            if info['type'] == 'cohort' and i < len(cells):
                cohort_label = self._clean_text(cells[i].get_text())
                cohort_type, cohort_normalized = self.parse_cohort_label(cohort_label)
                break

        # Extract values from value columns
        for i, info in column_info.items():
            if info['type'] != 'value' or i >= len(cells):
                continue

            cell_text = self._clean_text(cells[i].get_text())
            numeric_value = self._parse_number(cell_text)

            if numeric_value is None:
                continue  # Skip non-numeric cells

            # Determine which metric this value belongs to
            metric_id = self._infer_metric_from_context(segment, headers, i)
            if not metric_id:
                continue

            # Create MetricValue
            value = MetricValue(
                filing_id=segment.filing_id,
                company_id=company_id,
                metric_id=metric_id,
                source_segment_id=segment.source_segment_id or 0,
                source_type='table',
                extraction_method='rule_table',
                value_numeric=numeric_value,
                value_text=cell_text,
                unit=self._infer_unit(cell_text, metric_id),
                period_end=info.get('period_end'),
                cohort_type=cohort_type,
                cohort_bucket_raw=cohort_label,
                cohort_bucket_normalized=cohort_normalized,
                qa_status='unreviewed',
            )

            values.append(value)

        return values

    def _infer_metric_from_context(
        self,
        segment: SourceSegment,
        headers: List[str],
        column_index: int
    ) -> Optional[str]:
        """
        Infer which metric a value belongs to based on context.

        Uses:
        1. Candidate metrics from segment
        2. Header text
        3. Section path

        Returns:
            Metric ID or None
        """
        # If only one candidate metric, use it
        if len(segment.candidate_metric_ids) == 1:
            return segment.candidate_metric_ids[0]

        # Check header text for metric keywords
        if column_index < len(headers):
            header = headers[column_index].lower()

            # Revenue keywords
            if 'revenue' in header and 'cm_revenue_by_cohort' in segment.candidate_metric_ids:
                return 'cm_revenue_by_cohort'

            # Transaction keywords
            if 'transaction' in header and 'cm_transactions_by_cohort' in segment.candidate_metric_ids:
                return 'cm_transactions_by_cohort'

            # Customer count keywords
            if any(kw in header for kw in ['customers', 'users']) and 'cm_customers_period_end_by_tenure' in segment.candidate_metric_ids:
                return 'cm_customers_period_end_by_tenure'

        # Fall back to first candidate metric
        if segment.candidate_metric_ids:
            return segment.candidate_metric_ids[0]

        return None

    def _infer_unit(self, value_text: str, metric_id: str) -> Optional[str]:
        """Infer the unit from value text and metric type."""
        value_lower = value_text.lower()

        # Currency
        if '$' in value_text or 'usd' in value_lower:
            return 'usd'

        # Percentage
        if '%' in value_text or 'percent' in value_lower:
            return 'percent'

        # From metric type
        if 'revenue' in metric_id or 'cost' in metric_id or 'value' in metric_id:
            return 'usd'

        if 'rate' in metric_id:
            return 'percent'

        # Default to count for customer/user metrics
        if 'customer' in metric_id or 'user' in metric_id or 'transaction' in metric_id:
            return 'count'

        return None

    def parse_cohort_label(self, raw_label: str) -> Tuple[Optional[str], Optional[str]]:
        """
        Parse cohort label into type and normalized bucket.

        Args:
            raw_label: Raw cohort label from filing

        Returns:
            (cohort_type, cohort_bucket_normalized)

        Examples:
            "2021 Cohort" -> ("acquisition", "2021")
            "0-12 months" -> ("tenure", "0-1y")
            "2+ years" -> ("tenure", "2y+")
        """
        if not raw_label:
            return None, None

        # Check for acquisition cohort (year-based)
        match = self._acquisition_cohort_regex.search(raw_label)
        if match:
            year = match.group(1)
            return 'acquisition', year

        # Check for tenure cohorts
        for pattern, cohort_subtype in self.TENURE_COHORT_PATTERNS:
            match = re.search(pattern, raw_label, re.IGNORECASE)
            if match:
                if cohort_subtype == 'months':
                    start, end = match.groups()
                    # Convert to year buckets
                    start_years = int(start) // 12
                    end_years = int(end) // 12
                    return 'tenure', f"{start_years}-{end_years}y"

                elif cohort_subtype == 'years':
                    start, end = match.groups()
                    return 'tenure', f"{start}-{end}y"

                elif cohort_subtype == 'years_plus':
                    years = match.group(1)
                    return 'tenure', f"{years}y+"

                elif cohort_subtype == 'less_than':
                    value = match.group(1)
                    if 'month' in raw_label.lower():
                        years = int(value) // 12
                        return 'tenure', f"<{years}y"
                    else:
                        return 'tenure', f"<{value}y"

        # Could not parse
        return 'other', raw_label

    def _parse_number(self, text: str) -> Optional[Decimal]:
        """
        Parse numeric value from text.

        Handles:
        - Comma separators: 1,234,567
        - Currency symbols: $1.2M
        - Negative numbers: -123
        - Scale indicators: million, billion

        Returns:
            Decimal value or None if unparseable
        """
        # Remove currency symbols and whitespace
        cleaned = text.replace('$', '').replace(',', '').strip()

        # Check for scale indicators
        scale = 1
        if 'billion' in cleaned.lower():
            scale = 1_000_000_000
            cleaned = re.sub(r'billion', '', cleaned, flags=re.IGNORECASE).strip()
        elif 'million' in cleaned.lower():
            scale = 1_000_000
            cleaned = re.sub(r'million', '', cleaned, flags=re.IGNORECASE).strip()
        elif 'thousand' in cleaned.lower():
            scale = 1_000
            cleaned = re.sub(r'thousand', '', cleaned, flags=re.IGNORECASE).strip()

        # Remove percentage signs
        cleaned = cleaned.replace('%', '').strip()

        # Try to convert to Decimal
        try:
            value = Decimal(cleaned) * scale
            return value
        except (InvalidOperation, ValueError):
            return None

    def _extract_period_from_text(self, text: str) -> Optional[date]:
        """
        Extract period end date from text.

        Looks for patterns like:
        - Q1 2024 -> 2024-03-31
        - Q4 2023 -> 2023-12-31
        - FY 2023 -> 2023-12-31
        """
        # Try quarter pattern first
        match = self._quarter_regex.search(text)
        if match:
            quarter = int(match.group(1))
            year = int(match.group(2))

            # Map quarter to month
            quarter_end_months = {1: 3, 2: 6, 3: 9, 4: 12}
            month = quarter_end_months.get(quarter, 12)

            # Last day of quarter
            if month in [3, 6, 9]:
                day = 30 if month == 6 or month == 9 else 31
            else:
                day = 31

            try:
                return date(year, month, day)
            except ValueError:
                return None

        # Try year pattern
        match = self._year_regex.search(text)
        if match:
            year = int(match.group(1))
            try:
                return date(year, 12, 31)
            except ValueError:
                return None

        return None

    def _clean_text(self, text: str) -> str:
        """Clean text content."""
        return re.sub(r'\s+', ' ', text).strip()


# Convenience function
def extract_values(segment: SourceSegment, company_id: int) -> List[MetricValue]:
    """
    Convenience function to extract values from a segment.

    Args:
        segment: Source segment
        company_id: Company ID

    Returns:
        List of MetricValue objects
    """
    extractor = ValueExtractor()
    return extractor.extract_from_segment(segment, company_id)
