"""Unit tests for the shared input-validation helpers used by the DB adapter."""

import pytest

from src.infra.validation import ValidationError, validate_enum, validate_score
from src.review.models import KEYWORD_POSITIONS


class TestValidateEnum:
    """Tests for the validate_enum helper function."""

    def test_valid_value_passes(self):
        """Valid enum value should not raise."""
        result = validate_enum("before", KEYWORD_POSITIONS, "keyword_position")
        assert result == "before"

        result = validate_enum("after", KEYWORD_POSITIONS, "keyword_position")
        assert result == "after"

    def test_invalid_value_raises(self):
        """Invalid enum value should raise ValidationError."""
        with pytest.raises(ValidationError) as exc_info:
            validate_enum("invalid", KEYWORD_POSITIONS, "keyword_position")

        assert "Invalid keyword_position 'invalid'" in str(exc_info.value)
        assert "before" in str(exc_info.value)
        assert "after" in str(exc_info.value)

    def test_case_sensitive(self):
        """Enum validation should be case-sensitive."""
        with pytest.raises(ValidationError):
            validate_enum("Before", KEYWORD_POSITIONS, "keyword_position")

    def test_validation_error_is_value_error(self):
        """ValidationError should be a subclass of ValueError."""
        assert issubclass(ValidationError, ValueError)


class TestValidateScore:
    """Tests for the validate_score helper function."""

    def test_valid_score_passes(self):
        """Valid score values should pass and return the value."""
        assert validate_score(0.0, "confidence") == 0.0
        assert validate_score(0.5, "confidence") == 0.5
        assert validate_score(1.0, "confidence") == 1.0

    def test_none_passes_through(self):
        """None should pass through unchanged."""
        assert validate_score(None, "confidence") is None

    def test_too_high_raises(self):
        """Score > 1 should raise ValidationError."""
        with pytest.raises(ValidationError) as exc_info:
            validate_score(1.5, "confidence")

        assert "confidence" in str(exc_info.value)
        assert "between 0.0 and 1.0" in str(exc_info.value)
        assert "1.5" in str(exc_info.value)

    def test_negative_raises(self):
        """Negative score should raise ValidationError."""
        with pytest.raises(ValidationError) as exc_info:
            validate_score(-0.1, "precision_score")

        assert "precision_score" in str(exc_info.value)
        assert "-0.1" in str(exc_info.value)

    def test_context_included_in_error(self):
        """Context string should appear in error message."""
        with pytest.raises(ValidationError) as exc_info:
            validate_score(2.0, "suggestion_confidence", context="candidate 5")

        assert "candidate 5" in str(exc_info.value)

    def test_custom_range(self):
        """Custom min/max range should be respected."""
        # Valid within custom range
        assert validate_score(50.0, "percentage", min_val=0.0, max_val=100.0) == 50.0

        # Invalid for custom range
        with pytest.raises(ValidationError) as exc_info:
            validate_score(150.0, "percentage", min_val=0.0, max_val=100.0)

        assert "between 0.0 and 100.0" in str(exc_info.value)

    def test_boundary_values(self):
        """Boundary values should be accepted."""
        assert validate_score(0.0, "score") == 0.0
        assert validate_score(1.0, "score") == 1.0

        # Just outside boundaries
        with pytest.raises(ValidationError):
            validate_score(-0.0001, "score")

        with pytest.raises(ValidationError):
            validate_score(1.0001, "score")


