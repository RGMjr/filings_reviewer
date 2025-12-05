"""
Centralized input validation utilities.

Provides reusable validation functions for SEC filing data including
CIKs, accession numbers, SIC codes, dates, and form types.
"""

import re
from datetime import datetime
from typing import Tuple


class ValidationError(ValueError):
    """Raised when input validation fails."""

    pass


def validate_cik(cik: str) -> str:
    """
    Validate and normalize CIK to 10-digit zero-padded format.

    Args:
        cik: SEC Central Index Key (may be with or without leading zeros)

    Returns:
        Normalized 10-digit zero-padded CIK

    Raises:
        ValidationError: If CIK is invalid
    """
    if not cik:
        raise ValidationError("CIK cannot be empty")

    # Security: Check for path traversal characters
    if ".." in cik or "/" in cik or "\\" in cik:
        raise ValidationError("Invalid CIK: contains path traversal characters")

    # Must be numeric
    if not cik.isdigit():
        raise ValidationError("Invalid CIK: must be numeric")

    # Normalize to 10-digit zero-padded
    normalized = cik.zfill(10)

    # Validate length (SEC CIKs are max 10 digits)
    if len(normalized) > 10:
        raise ValidationError(f"Invalid CIK: too many digits (max 10): {cik}")

    return normalized


def validate_accession_number(accession: str) -> str:
    """
    Validate accession number format.

    SEC accession numbers are in format: NNNNNNNNNN-NN-NNNNNN
    (10 digits - 2 digits - 6 digits)

    Args:
        accession: SEC accession number

    Returns:
        Validated accession number (unchanged if valid)

    Raises:
        ValidationError: If accession number is invalid
    """
    if not accession:
        raise ValidationError("Accession number cannot be empty")

    # Security: Check for path traversal characters
    if ".." in accession or "\\" in accession:
        raise ValidationError(
            "Invalid accession number: contains path traversal characters"
        )

    # Check for slashes (allowing dashes which are part of format)
    if "/" in accession.replace("-", ""):
        raise ValidationError(
            "Invalid accession number: contains path traversal characters"
        )

    # Remove dashes for alphanumeric check
    accession_clean = accession.replace("-", "")
    if not accession_clean.isalnum():
        raise ValidationError("Invalid accession number: must be alphanumeric")

    # Validate format pattern (NNNNNNNNNN-NN-NNNNNN)
    pattern = r"^\d{10}-\d{2}-\d{6}$"
    if not re.match(pattern, accession):
        raise ValidationError(
            f"Invalid accession number format: expected NNNNNNNNNN-NN-NNNNNN, got {accession}"
        )

    return accession


def validate_sic_code(sic: str) -> str:
    """
    Validate SIC (Standard Industrial Classification) code.

    SIC codes are 4-digit codes ranging from 0100 to 9999.

    Args:
        sic: SIC code string

    Returns:
        Validated 4-digit SIC code

    Raises:
        ValidationError: If SIC code is invalid
    """
    if not sic:
        raise ValidationError("SIC code cannot be empty")

    # Must be numeric
    if not sic.isdigit():
        raise ValidationError(f"Invalid SIC code: must be numeric: {sic}")

    # Normalize to 4 digits
    normalized = sic.zfill(4)

    if len(normalized) != 4:
        raise ValidationError(f"Invalid SIC code: must be 4 digits: {sic}")

    # Validate range (0100-9999 are valid SIC codes)
    sic_int = int(normalized)
    if sic_int < 100 or sic_int > 9999:
        raise ValidationError(
            f"Invalid SIC code: must be between 0100 and 9999: {normalized}"
        )

    return normalized


def validate_date(date_str: str, field_name: str = "date") -> datetime:
    """
    Validate and parse an ISO format date string.

    Args:
        date_str: Date string in ISO format (YYYY-MM-DD)
        field_name: Name of the field for error messages

    Returns:
        Parsed datetime object

    Raises:
        ValidationError: If date string is invalid
    """
    if not date_str:
        raise ValidationError(f"{field_name} cannot be empty")

    try:
        return datetime.fromisoformat(date_str)
    except ValueError as e:
        raise ValidationError(
            f"Invalid {field_name} format: expected YYYY-MM-DD, got '{date_str}': {e}"
        )


def validate_date_range(
    start_date: str, end_date: str
) -> Tuple[datetime, datetime]:
    """
    Validate a date range ensuring start <= end.

    Args:
        start_date: Start date in ISO format (YYYY-MM-DD)
        end_date: End date in ISO format (YYYY-MM-DD)

    Returns:
        Tuple of (start_datetime, end_datetime)

    Raises:
        ValidationError: If dates are invalid or start > end
    """
    start = validate_date(start_date, "start_date")
    end = validate_date(end_date, "end_date")

    if start > end:
        raise ValidationError(
            f"Invalid date range: start_date ({start_date}) is after end_date ({end_date})"
        )

    return start, end


def validate_form_type(form_type: str) -> str:
    """
    Validate SEC form type.

    Args:
        form_type: SEC form type (e.g., "S-1", "S-1/A", "F-1", "F-1/A")

    Returns:
        Validated form type (uppercase)

    Raises:
        ValidationError: If form type is invalid
    """
    if not form_type:
        raise ValidationError("Form type cannot be empty")

    # Normalize to uppercase
    normalized = form_type.upper().strip()

    # Valid S-1/F-1 related form types
    valid_form_types = {
        "S-1",
        "S-1/A",
        "F-1",
        "F-1/A",
        "S-11",
        "S-11/A",
        "10-K",
        "10-K/A",
        "10-Q",
        "10-Q/A",
        "8-K",
        "8-K/A",
    }

    if normalized not in valid_form_types:
        raise ValidationError(
            f"Invalid form type: '{form_type}'. "
            f"Expected one of: {', '.join(sorted(valid_form_types))}"
        )

    return normalized
