"""Unit tests for src/shared/extraction_exceptions.py."""

import pytest

from src.shared.extraction_exceptions import (
    EncodingError,
    ExtractionError,
    HTMLParsingError,
    ValidationError,
)


def test_extraction_error_is_base_class():
    assert issubclass(HTMLParsingError, ExtractionError)
    assert issubclass(EncodingError, ExtractionError)
    assert issubclass(ValidationError, ExtractionError)


def test_html_parsing_error_stores_context():
    err = HTMLParsingError("bad html", filing_id=42, html_path="/tmp/f.htm")
    assert str(err) == "bad html"
    assert err.filing_id == 42
    assert err.html_path == "/tmp/f.htm"


def test_html_parsing_error_allows_missing_context():
    err = HTMLParsingError("bad html")
    assert err.filing_id is None
    assert err.html_path is None


def test_encoding_error_stores_attempted_encodings():
    err = EncodingError(
        "decode failed",
        file_path="/tmp/f.htm",
        attempted_encodings=["utf-8", "latin-1"],
        position=1024,
    )
    assert err.file_path == "/tmp/f.htm"
    assert err.attempted_encodings == ["utf-8", "latin-1"]
    assert err.position == 1024


def test_encoding_error_defaults_attempted_encodings_to_empty_list():
    err = EncodingError("decode failed", file_path="/tmp/f.htm")
    assert err.attempted_encodings == []
    assert err.position is None


def test_validation_error_stores_field_metadata():
    err = ValidationError("bad value", field_name="filing_id", invalid_value=-1)
    assert err.field_name == "filing_id"
    assert err.invalid_value == -1


def test_validation_error_raises_cleanly():
    with pytest.raises(ValidationError) as excinfo:
        raise ValidationError("oops", field_name="x", invalid_value=0)
    assert "oops" in str(excinfo.value)
    assert excinfo.value.field_name == "x"
