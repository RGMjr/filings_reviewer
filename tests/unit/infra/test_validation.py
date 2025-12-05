"""Tests for centralized input validation utilities."""

import pytest
from datetime import datetime

from src.infra.validation import (
    ValidationError,
    validate_cik,
    validate_accession_number,
    validate_sic_code,
    validate_date,
    validate_date_range,
    validate_form_type,
)


class TestValidateCik:
    """Tests for CIK validation."""

    def test_valid_cik_numeric(self):
        """Test valid numeric CIK."""
        assert validate_cik("1234567890") == "1234567890"

    def test_valid_cik_zero_padded(self):
        """Test CIK is zero-padded to 10 digits."""
        assert validate_cik("12345") == "0000012345"

    def test_valid_cik_single_digit(self):
        """Test single digit CIK is zero-padded."""
        assert validate_cik("1") == "0000000001"

    def test_empty_cik_raises(self):
        """Test empty CIK raises ValidationError."""
        with pytest.raises(ValidationError, match="cannot be empty"):
            validate_cik("")

    def test_path_traversal_dots_raises(self):
        """Test path traversal with .. raises ValidationError."""
        with pytest.raises(ValidationError, match="path traversal"):
            validate_cik("123..456")

    def test_path_traversal_slash_raises(self):
        """Test path traversal with / raises ValidationError."""
        with pytest.raises(ValidationError, match="path traversal"):
            validate_cik("123/456")

    def test_path_traversal_backslash_raises(self):
        """Test path traversal with \\ raises ValidationError."""
        with pytest.raises(ValidationError, match="path traversal"):
            validate_cik("123\\456")

    def test_non_numeric_raises(self):
        """Test non-numeric CIK raises ValidationError."""
        with pytest.raises(ValidationError, match="must be numeric"):
            validate_cik("123abc")

    def test_too_many_digits_raises(self):
        """Test CIK with more than 10 digits raises ValidationError."""
        with pytest.raises(ValidationError, match="too many digits"):
            validate_cik("12345678901")


class TestValidateAccessionNumber:
    """Tests for accession number validation."""

    def test_valid_accession_number(self):
        """Test valid accession number format."""
        assert validate_accession_number("0001193125-20-326144") == "0001193125-20-326144"

    def test_empty_accession_raises(self):
        """Test empty accession number raises ValidationError."""
        with pytest.raises(ValidationError, match="cannot be empty"):
            validate_accession_number("")

    def test_path_traversal_dots_raises(self):
        """Test path traversal with .. raises ValidationError."""
        with pytest.raises(ValidationError, match="path traversal"):
            validate_accession_number("0001193125..326144")

    def test_path_traversal_slash_raises(self):
        """Test path traversal with / raises ValidationError."""
        with pytest.raises(ValidationError, match="path traversal"):
            validate_accession_number("0001193125/20/326144")

    def test_path_traversal_backslash_raises(self):
        """Test path traversal with \\ raises ValidationError."""
        with pytest.raises(ValidationError, match="path traversal"):
            validate_accession_number("0001193125\\20\\326144")

    def test_non_alphanumeric_raises(self):
        """Test non-alphanumeric characters raise ValidationError."""
        with pytest.raises(ValidationError, match="must be alphanumeric"):
            validate_accession_number("0001193125-20-32614!")

    def test_wrong_format_raises(self):
        """Test wrong format raises ValidationError."""
        with pytest.raises(ValidationError, match="Invalid accession number format"):
            validate_accession_number("1234-56-789")

    def test_missing_dashes_raises(self):
        """Test missing dashes raises ValidationError."""
        with pytest.raises(ValidationError, match="Invalid accession number format"):
            validate_accession_number("000119312520326144")


class TestValidateSicCode:
    """Tests for SIC code validation."""

    def test_valid_sic_code_4_digits(self):
        """Test valid 4-digit SIC code."""
        assert validate_sic_code("7372") == "7372"

    def test_valid_sic_code_zero_padded(self):
        """Test SIC code is zero-padded to 4 digits."""
        assert validate_sic_code("100") == "0100"

    def test_valid_sic_code_minimum(self):
        """Test minimum valid SIC code (0100)."""
        assert validate_sic_code("100") == "0100"

    def test_valid_sic_code_maximum(self):
        """Test maximum valid SIC code (9999)."""
        assert validate_sic_code("9999") == "9999"

    def test_empty_sic_raises(self):
        """Test empty SIC code raises ValidationError."""
        with pytest.raises(ValidationError, match="cannot be empty"):
            validate_sic_code("")

    def test_non_numeric_raises(self):
        """Test non-numeric SIC code raises ValidationError."""
        with pytest.raises(ValidationError, match="must be numeric"):
            validate_sic_code("73AB")

    def test_too_low_raises(self):
        """Test SIC code below 0100 raises ValidationError."""
        with pytest.raises(ValidationError, match="must be between 0100 and 9999"):
            validate_sic_code("99")

    def test_too_many_digits_raises(self):
        """Test SIC code with more than 4 digits raises ValidationError."""
        with pytest.raises(ValidationError, match="must be 4 digits"):
            validate_sic_code("12345")


class TestValidateDate:
    """Tests for date validation."""

    def test_valid_date(self):
        """Test valid ISO date."""
        result = validate_date("2024-01-15")
        assert result == datetime(2024, 1, 15)

    def test_valid_date_with_time(self):
        """Test valid ISO datetime."""
        result = validate_date("2024-01-15T10:30:00")
        assert result == datetime(2024, 1, 15, 10, 30, 0)

    def test_empty_date_raises(self):
        """Test empty date raises ValidationError."""
        with pytest.raises(ValidationError, match="cannot be empty"):
            validate_date("")

    def test_invalid_format_raises(self):
        """Test invalid format raises ValidationError."""
        with pytest.raises(ValidationError, match="Invalid.*format"):
            validate_date("01/15/2024")

    def test_invalid_date_raises(self):
        """Test invalid date (Feb 30) raises ValidationError."""
        with pytest.raises(ValidationError, match="Invalid.*format"):
            validate_date("2024-02-30")

    def test_custom_field_name_in_error(self):
        """Test custom field name appears in error message."""
        with pytest.raises(ValidationError, match="filing_date"):
            validate_date("invalid", field_name="filing_date")


class TestValidateDateRange:
    """Tests for date range validation."""

    def test_valid_date_range(self):
        """Test valid date range."""
        start, end = validate_date_range("2024-01-01", "2024-12-31")
        assert start == datetime(2024, 1, 1)
        assert end == datetime(2024, 12, 31)

    def test_same_day_range(self):
        """Test same day is valid range."""
        start, end = validate_date_range("2024-06-15", "2024-06-15")
        assert start == end

    def test_start_after_end_raises(self):
        """Test start date after end date raises ValidationError."""
        with pytest.raises(ValidationError, match="start_date.*is after"):
            validate_date_range("2024-12-31", "2024-01-01")

    def test_invalid_start_date_raises(self):
        """Test invalid start date raises ValidationError."""
        with pytest.raises(ValidationError, match="start_date"):
            validate_date_range("invalid", "2024-12-31")

    def test_invalid_end_date_raises(self):
        """Test invalid end date raises ValidationError."""
        with pytest.raises(ValidationError, match="end_date"):
            validate_date_range("2024-01-01", "invalid")


class TestValidateFormType:
    """Tests for SEC form type validation."""

    def test_valid_s1(self):
        """Test valid S-1 form type."""
        assert validate_form_type("S-1") == "S-1"

    def test_valid_s1_amendment(self):
        """Test valid S-1/A form type."""
        assert validate_form_type("S-1/A") == "S-1/A"

    def test_valid_f1(self):
        """Test valid F-1 form type."""
        assert validate_form_type("F-1") == "F-1"

    def test_valid_f1_amendment(self):
        """Test valid F-1/A form type."""
        assert validate_form_type("F-1/A") == "F-1/A"

    def test_lowercase_normalized(self):
        """Test lowercase form type is normalized to uppercase."""
        assert validate_form_type("s-1") == "S-1"

    def test_with_whitespace(self):
        """Test form type with whitespace is trimmed."""
        assert validate_form_type("  S-1  ") == "S-1"

    def test_empty_raises(self):
        """Test empty form type raises ValidationError."""
        with pytest.raises(ValidationError, match="cannot be empty"):
            validate_form_type("")

    def test_invalid_form_type_raises(self):
        """Test invalid form type raises ValidationError."""
        with pytest.raises(ValidationError, match="Invalid form type"):
            validate_form_type("INVALID-FORM")

    def test_error_lists_valid_types(self):
        """Test error message includes valid form types."""
        with pytest.raises(ValidationError, match="S-1"):
            validate_form_type("INVALID")
