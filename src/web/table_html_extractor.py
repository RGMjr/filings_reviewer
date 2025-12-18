"""
Smart HTML extraction for table display in review interface.

Ensures that when displaying table HTML, we show the portion that actually
contains the extracted value and keyword, not just the first N bytes.
"""

import logging
from typing import Optional, Tuple

from bs4 import BeautifulSoup, Tag

logger = logging.getLogger(__name__)


def extract_relevant_table_html(
    full_html: str,
    value_text: str,
    keyword_text: str,
    max_length: int = 25000,
    context_rows: int = 3,
) -> str:
    """
    Extract the relevant portion of table HTML that contains the value and keyword.

    For large tables, the first N bytes of HTML may not include the data rows
    where the extracted value appears. This function intelligently extracts
    the portion of the table that includes:
    - Table headers
    - The row containing the value
    - Context rows above and below

    Args:
        full_html: Complete HTML of the segment (may be very large)
        value_text: The extracted number text to locate (e.g., "17,235")
        keyword_text: The triggering keyword to locate (e.g., "Contract liabilities")
        max_length: Maximum length of extracted HTML (default: 25000)
        context_rows: Number of rows to include above/below the value row (default: 3)

    Returns:
        Extracted HTML string containing the relevant portion of the table

    Example:
        >>> html = "<table>...</table>"  # Large table
        >>> extracted = extract_relevant_table_html(html, "450,069", "Gross profit")
        >>> # extracted contains table headers + row with 450,069 + context rows
    """
    # If HTML is already small enough, return as-is
    if len(full_html) <= max_length:
        return full_html

    soup = BeautifulSoup(full_html, 'html.parser')
    table = soup.find('table')

    # If no table found, just truncate the HTML
    if not table:
        logger.debug("No table found in HTML, truncating to max_length")
        return full_html[:max_length]

    # Find all table rows
    rows = table.find_all('tr', recursive=True)

    if not rows:
        logger.debug("No rows found in table, truncating to max_length")
        return full_html[:max_length]

    # Find the row containing the value
    value_row_idx = None
    keyword_row_idx = None

    for idx, row in enumerate(rows):
        row_text = row.get_text()

        if value_text in row_text and value_row_idx is None:
            value_row_idx = idx
            logger.debug(f"Found value '{value_text}' in row {idx}")

        if keyword_text in row_text and keyword_row_idx is None:
            keyword_row_idx = idx
            logger.debug(f"Found keyword '{keyword_text}' in row {idx}")

        # If we found both, we can stop searching
        if value_row_idx is not None and keyword_row_idx is not None:
            break

    # If we didn't find the value, fall back to truncating
    if value_row_idx is None:
        logger.warning(f"Value '{value_text}' not found in any table row, truncating HTML")
        return full_html[:max_length]

    # Determine which rows to include
    # Start from first non-header row, or a few rows before value row
    start_row = max(0, value_row_idx - context_rows)

    # Include keyword row if it's nearby
    if keyword_row_idx is not None:
        end_row = max(value_row_idx, keyword_row_idx) + context_rows + 1
    else:
        end_row = value_row_idx + context_rows + 1

    end_row = min(end_row, len(rows))

    # Extract header rows (usually first 1-3 rows with th elements or specific patterns)
    header_rows = []
    for idx, row in enumerate(rows[:min(5, len(rows))]):
        # Consider it a header if it has th elements or is in first few rows
        has_th = row.find('th') is not None
        has_header_style = 'border-bottom' in str(row.get('style', ''))

        if has_th or has_header_style or idx < 2:
            header_rows.append(row)
        else:
            # Stop looking for headers once we hit data rows
            break

    # Build the extracted table
    # Create a new table with the same attributes as the original
    new_table = BeautifulSoup(f"<table {_extract_attrs(table)}></table>", 'html.parser').table

    # Add header rows
    for row in header_rows:
        new_table.append(row.__copy__())

    # Add data rows (skip headers if they're already included)
    header_count = len(header_rows)
    for idx in range(start_row, end_row):
        if idx >= header_count:  # Don't duplicate header rows
            new_table.append(rows[idx].__copy__())

    # Convert back to HTML string
    extracted_html = str(new_table)

    # If still too long, truncate
    if len(extracted_html) > max_length:
        logger.debug(f"Extracted HTML still too long ({len(extracted_html)}), truncating to {max_length}")
        extracted_html = extracted_html[:max_length]

    logger.debug(
        f"Extracted table: {len(header_rows)} header rows, "
        f"rows {start_row}-{end_row} ({end_row - start_row} data rows), "
        f"final length: {len(extracted_html)}"
    )

    return extracted_html


def _extract_attrs(tag: Tag) -> str:
    """Extract HTML attributes from a BeautifulSoup tag as a string."""
    if not tag.attrs:
        return ""

    parts = []
    for key, value in tag.attrs.items():
        if isinstance(value, list):
            value = ' '.join(value)
        parts.append(f'{key}="{value}"')

    return ' '.join(parts)
