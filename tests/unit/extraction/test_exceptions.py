"""
Tests for extraction exceptions.
"""


from src.extraction.exceptions import (
    EncodingError,
    ExtractionError,
    HTMLParsingError,
    ValidationError,
)


class TestHTMLParsingError:
    """Tests for HTMLParsingError exception."""

    def test_html_parsing_error_with_context(self):
        """Test HTMLParsingError stores filing ID and file path."""
        error = HTMLParsingError("Missing BODY tag", filing_id=123, html_path="/path/to/filing.html")

        assert str(error) == "Missing BODY tag"
        assert error.filing_id == 123
        assert error.html_path == "/path/to/filing.html"
        assert isinstance(error, ExtractionError)

    def test_html_parsing_error_without_context(self):
        """Test HTMLParsingError works without optional fields."""
        error = HTMLParsingError("Malformed HTML")

        assert str(error) == "Malformed HTML"
        assert error.filing_id is None
        assert error.html_path is None


class TestEncodingError:
    """Tests for EncodingError exception."""

    def test_encoding_error_with_full_context(self):
        """Test EncodingError stores all contextual information."""
        error = EncodingError(
            "Cannot decode file", file_path="/path/to/file.html", attempted_encodings=["utf-8", "latin-1"], position=1234
        )

        assert str(error) == "Cannot decode file"
        assert error.file_path == "/path/to/file.html"
        assert error.attempted_encodings == ["utf-8", "latin-1"]
        assert error.position == 1234
        assert isinstance(error, ExtractionError)

    def test_encoding_error_defaults(self):
        """Test EncodingError with minimal parameters."""
        error = EncodingError("Encoding failed", file_path="/path/to/file.html")

        assert error.file_path == "/path/to/file.html"
        assert error.attempted_encodings == []
        assert error.position is None


class TestValidationError:
    """Tests for ValidationError exception."""

    def test_validation_error_with_field_context(self):
        """Test ValidationError stores field name and invalid value."""
        error = ValidationError("Filing ID must be positive", field_name="filing_id", invalid_value=-1)

        assert str(error) == "Filing ID must be positive"
        assert error.field_name == "filing_id"
        assert error.invalid_value == -1
        assert isinstance(error, ExtractionError)

    def test_validation_error_without_context(self):
        """Test ValidationError works without optional fields."""
        error = ValidationError("Invalid input")

        assert str(error) == "Invalid input"
        assert error.field_name is None
        assert error.invalid_value is None


class TestExceptionHierarchy:
    """Tests for exception inheritance."""

    def test_all_extraction_errors_inherit_from_base(self):
        """Test all custom exceptions inherit from ExtractionError."""
        exceptions = [
            HTMLParsingError("test"),
            EncodingError("test", "path"),
            ValidationError("test"),
        ]

        for exc in exceptions:
            assert isinstance(exc, ExtractionError)
            assert isinstance(exc, Exception)
