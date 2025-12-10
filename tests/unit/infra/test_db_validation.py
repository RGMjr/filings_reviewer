"""
Unit tests for DatabaseAdapter validation logic.

Tests input validation for review table methods.
"""

import pytest

from src.infra.db import DatabaseAdapter
from src.infra.validation import ValidationError, validate_enum, validate_score
from src.review.models import (
    DECISION_TYPES,
    KEYWORD_POSITIONS,
    PATTERN_STATUSES,
    PATTERN_TYPES,
    REJECTION_CATEGORIES,
    REVIEW_STATUSES,
)


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


class TestInsertReviewCandidateValidation:
    """Tests for insert_review_candidate validation."""

    @pytest.fixture
    def mock_db(self):
        """Create a DatabaseAdapter with mocked connection."""
        db = DatabaseAdapter("postgresql://test")
        return db

    def test_invalid_keyword_position_raises(self, mock_db):
        """Invalid keyword_position should raise ValidationError before DB call."""
        with pytest.raises(ValidationError) as exc_info:
            mock_db.insert_review_candidate(
                filing_id=1,
                company_id=1,
                char_position=100,
                context_text="test",
                raw_number_text="100",
                triggering_keyword="customers",
                keyword_distance=10,
                keyword_position="invalid",  # Invalid value
            )

        assert "keyword_position" in str(exc_info.value)
        assert "invalid" in str(exc_info.value)

    def test_invalid_suggestion_confidence_too_high(self, mock_db):
        """suggestion_confidence > 1 should raise ValidationError."""
        with pytest.raises(ValidationError) as exc_info:
            mock_db.insert_review_candidate(
                filing_id=1,
                company_id=1,
                char_position=100,
                context_text="test",
                raw_number_text="100",
                triggering_keyword="customers",
                keyword_distance=10,
                keyword_position="after",
                suggestion_confidence=1.5,  # Invalid: > 1
            )

        assert "suggestion_confidence" in str(exc_info.value)
        assert "between 0.0 and 1.0" in str(exc_info.value)

    def test_invalid_suggestion_confidence_negative(self, mock_db):
        """Negative suggestion_confidence should raise ValueError."""
        with pytest.raises(ValueError) as exc_info:
            mock_db.insert_review_candidate(
                filing_id=1,
                company_id=1,
                char_position=100,
                context_text="test",
                raw_number_text="100",
                triggering_keyword="customers",
                keyword_distance=10,
                keyword_position="before",
                suggestion_confidence=-0.1,  # Invalid: < 0
            )

        assert "suggestion_confidence" in str(exc_info.value)


class TestUpdateCandidateStatusValidation:
    """Tests for update_candidate_status validation."""

    @pytest.fixture
    def mock_db(self):
        """Create a DatabaseAdapter with mocked connection."""
        return DatabaseAdapter("postgresql://test")

    def test_invalid_status_raises(self, mock_db):
        """Invalid status should raise ValidationError before DB call."""
        with pytest.raises(ValidationError) as exc_info:
            mock_db.update_candidate_status(1, "invalid_status")

        assert "review_status" in str(exc_info.value)
        assert "invalid_status" in str(exc_info.value)

    def test_valid_status_passes_validation(self, mock_db):
        """Valid status should pass validation (fail on DB, not validation)."""
        for status in REVIEW_STATUSES:
            with pytest.raises(Exception) as exc_info:
                mock_db.update_candidate_status(1, status)
            assert not isinstance(exc_info.value, ValidationError)


class TestGetReviewCandidatesForFilingValidation:
    """Tests for get_review_candidates_for_filing validation."""

    @pytest.fixture
    def mock_db(self):
        """Create a DatabaseAdapter with mocked connection."""
        return DatabaseAdapter("postgresql://test")

    def test_invalid_status_raises(self, mock_db):
        """Invalid status filter should raise ValidationError."""
        with pytest.raises(ValidationError) as exc_info:
            mock_db.get_review_candidates_for_filing(
                filing_id=1,
                status="invalid_status",
            )

        assert "review_status" in str(exc_info.value)
        assert "invalid_status" in str(exc_info.value)


class TestInsertReviewDecisionValidation:
    """Tests for insert_review_decision validation."""

    @pytest.fixture
    def mock_db(self):
        """Create a DatabaseAdapter with mocked connection."""
        return DatabaseAdapter("postgresql://test")

    def test_invalid_decision_raises(self, mock_db):
        """Invalid decision type should raise ValidationError."""
        with pytest.raises(ValidationError) as exc_info:
            mock_db.insert_review_decision(
                candidate_id=1,
                decision="invalid_decision",
            )

        assert "decision" in str(exc_info.value)
        assert "invalid_decision" in str(exc_info.value)

    def test_invalid_rejection_category_raises(self, mock_db):
        """Invalid rejection_category should raise ValidationError."""
        with pytest.raises(ValidationError) as exc_info:
            mock_db.insert_review_decision(
                candidate_id=1,
                decision="reject",
                rejection_category="invalid_category",
            )

        assert "rejection_category" in str(exc_info.value)

    def test_accept_without_metric_raises(self, mock_db):
        """Accept decision without assigned_metric_id should raise."""
        with pytest.raises(ValidationError) as exc_info:
            mock_db.insert_review_decision(
                candidate_id=1,
                decision="accept",
                # Missing assigned_metric_id
            )

        assert "accept" in str(exc_info.value)
        assert "assigned_metric_id" in str(exc_info.value)

    def test_reclassify_without_metric_raises(self, mock_db):
        """Reclassify decision without assigned_metric_id should raise."""
        with pytest.raises(ValidationError) as exc_info:
            mock_db.insert_review_decision(
                candidate_id=1,
                decision="reclassify",
                # Missing assigned_metric_id
            )

        assert "reclassify" in str(exc_info.value)
        assert "assigned_metric_id" in str(exc_info.value)

    def test_rejection_category_with_accept_raises(self, mock_db):
        """rejection_category with non-reject decision should raise."""
        with pytest.raises(ValidationError) as exc_info:
            mock_db.insert_review_decision(
                candidate_id=1,
                decision="accept",
                assigned_metric_id="test_metric",
                rejection_category="wrong_metric",  # Invalid for accept
            )

        assert "rejection_category" in str(exc_info.value)
        assert "reject" in str(exc_info.value)


class TestInsertLearnedPatternValidation:
    """Tests for insert_learned_pattern validation."""

    @pytest.fixture
    def mock_db(self):
        """Create a DatabaseAdapter with mocked connection."""
        return DatabaseAdapter("postgresql://test")

    def test_invalid_pattern_type_raises(self, mock_db):
        """Invalid pattern_type should raise ValidationError."""
        with pytest.raises(ValidationError) as exc_info:
            mock_db.insert_learned_pattern(
                pattern_type="invalid_type",
                pattern_name="test",
                pattern_definition={},
            )

        assert "pattern_type" in str(exc_info.value)

    def test_invalid_precision_score_raises(self, mock_db):
        """precision_score > 1 should raise ValueError."""
        with pytest.raises(ValueError) as exc_info:
            mock_db.insert_learned_pattern(
                pattern_type="accept_rule",
                pattern_name="test",
                pattern_definition={},
                precision_score=1.5,
            )

        assert "precision_score" in str(exc_info.value)

    def test_invalid_recall_score_raises(self, mock_db):
        """Negative recall_score should raise ValueError."""
        with pytest.raises(ValueError) as exc_info:
            mock_db.insert_learned_pattern(
                pattern_type="reject_rule",
                pattern_name="test",
                pattern_definition={},
                recall_score=-0.1,
            )

        assert "recall_score" in str(exc_info.value)

    def test_invalid_f1_score_raises(self, mock_db):
        """f1_score > 1 should raise ValueError."""
        with pytest.raises(ValueError) as exc_info:
            mock_db.insert_learned_pattern(
                pattern_type="feature_weight",
                pattern_name="test",
                pattern_definition={},
                f1_score=2.0,
            )

        assert "f1_score" in str(exc_info.value)


class TestUpdatePatternStatusValidation:
    """Tests for update_pattern_status validation."""

    @pytest.fixture
    def mock_db(self):
        """Create a DatabaseAdapter with mocked connection."""
        return DatabaseAdapter("postgresql://test")

    def test_invalid_status_raises(self, mock_db):
        """Invalid pattern status should raise ValidationError."""
        with pytest.raises(ValidationError) as exc_info:
            mock_db.update_pattern_status(1, "invalid_status")

        assert "pattern_status" in str(exc_info.value)

    def test_valid_status_passes_validation(self, mock_db):
        """Valid pattern status should pass validation (fail on DB, not validation)."""
        for status in PATTERN_STATUSES:
            with pytest.raises(Exception) as exc_info:
                mock_db.update_pattern_status(1, status)
            assert not isinstance(exc_info.value, ValidationError)


class TestBulkInsertValidation:
    """Tests for bulk_insert_review_candidates validation."""

    @pytest.fixture
    def mock_db(self):
        """Create a DatabaseAdapter with mocked connection."""
        return DatabaseAdapter("postgresql://test")

    def test_invalid_keyword_position_in_bulk_raises(self, mock_db):
        """Invalid keyword_position in any candidate should raise."""
        candidates = [
            {
                "filing_id": 1,
                "company_id": 1,
                "char_position": 0,
                "context_text": "test",
                "raw_number_text": "100",
                "triggering_keyword": "test",
                "keyword_distance": 10,
                "keyword_position": "after",  # Valid
            },
            {
                "filing_id": 1,
                "company_id": 1,
                "char_position": 100,
                "context_text": "test 2",
                "raw_number_text": "200",
                "triggering_keyword": "test",
                "keyword_distance": 5,
                "keyword_position": "invalid",  # Invalid - should fail
            },
        ]

        with pytest.raises(ValidationError) as exc_info:
            mock_db.bulk_insert_review_candidates(candidates)

        assert "keyword_position" in str(exc_info.value)
        assert "candidate 1" in str(exc_info.value)  # Should identify which candidate

    def test_invalid_confidence_in_bulk_raises(self, mock_db):
        """Invalid suggestion_confidence in any candidate should raise."""
        candidates = [
            {
                "filing_id": 1,
                "company_id": 1,
                "char_position": 0,
                "context_text": "test",
                "raw_number_text": "100",
                "triggering_keyword": "test",
                "keyword_distance": 10,
                "keyword_position": "after",
                "suggestion_confidence": 1.5,  # Invalid
            },
        ]

        with pytest.raises(ValueError) as exc_info:
            mock_db.bulk_insert_review_candidates(candidates)

        assert "suggestion_confidence" in str(exc_info.value)
        assert "candidate 0" in str(exc_info.value)


class TestGetApprovedPatternsValidation:
    """Tests for get_approved_patterns validation."""

    @pytest.fixture
    def mock_db(self):
        """Create a DatabaseAdapter with mocked connection."""
        return DatabaseAdapter("postgresql://test")

    def test_invalid_pattern_type_raises(self, mock_db):
        """Invalid pattern_type should raise ValidationError before DB call."""
        with pytest.raises(ValidationError) as exc_info:
            mock_db.get_approved_patterns(pattern_type="invalid_type")

        assert "pattern_type" in str(exc_info.value)
        assert "invalid_type" in str(exc_info.value)

    def test_valid_pattern_type_passes_validation(self, mock_db):
        """Valid pattern_type should pass validation (fail on DB, not validation)."""
        for pattern_type in PATTERN_TYPES:
            with pytest.raises(Exception) as exc_info:
                mock_db.get_approved_patterns(pattern_type=pattern_type)
            assert not isinstance(exc_info.value, ValidationError)


class TestGetFilingsWithCandidatesValidation:
    """Tests for get_filings_with_candidates validation."""

    @pytest.fixture
    def mock_db(self):
        """Create a DatabaseAdapter with mocked connection."""
        return DatabaseAdapter("postgresql://test")

    def test_invalid_status_raises(self, mock_db):
        """Invalid status should raise ValidationError before DB call."""
        with pytest.raises(ValidationError) as exc_info:
            mock_db.get_filings_with_candidates(status="invalid_status")

        assert "review_status" in str(exc_info.value)
        assert "invalid_status" in str(exc_info.value)

    def test_valid_status_passes_validation(self, mock_db):
        """Valid status should pass validation (fail on DB, not validation)."""
        for status in REVIEW_STATUSES:
            with pytest.raises(Exception) as exc_info:
                mock_db.get_filings_with_candidates(status=status)
            assert not isinstance(exc_info.value, ValidationError)


class TestNonePassthroughValidation:
    """Tests that None values skip validation without raising errors."""

    @pytest.fixture
    def mock_db(self):
        """Create a DatabaseAdapter with mocked connection."""
        return DatabaseAdapter("postgresql://test")

    def test_get_review_candidates_for_filing_none_status(self, mock_db):
        """None status should not raise ValidationError."""
        # Will fail on DB connection, but should NOT raise ValidationError
        with pytest.raises(Exception) as exc_info:
            mock_db.get_review_candidates_for_filing(filing_id=1, status=None)

        # Should fail on connection, not validation
        assert not isinstance(exc_info.value, ValidationError)

    def test_get_approved_patterns_none_pattern_type(self, mock_db):
        """None pattern_type should not raise ValidationError."""
        with pytest.raises(Exception) as exc_info:
            mock_db.get_approved_patterns(pattern_type=None)

        assert not isinstance(exc_info.value, ValidationError)

    def test_get_filings_with_candidates_none_status(self, mock_db):
        """None status should not raise ValidationError."""
        with pytest.raises(Exception) as exc_info:
            mock_db.get_filings_with_candidates(status=None)

        assert not isinstance(exc_info.value, ValidationError)
