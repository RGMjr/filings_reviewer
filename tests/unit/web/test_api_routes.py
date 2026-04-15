"""
Unit tests for API routes (D2).

Tests the JSON API endpoints for review decision recording.
Uses mocked database to isolate route logic.
"""

import json
from unittest.mock import MagicMock, patch

import psycopg
import pytest

from src.web.app import create_app


@pytest.fixture
def app():
    """Create Flask test app."""
    app = create_app(
        config_name="testing",
        config_override={
            "DATABASE_URL": "postgresql://test:test@localhost/test",
        },
    )
    return app


@pytest.fixture
def client(app):
    """Create Flask test client."""
    return app.test_client()


@pytest.fixture
def mock_db():
    """Create mock database adapter."""
    return MagicMock()


# =============================================================================
# TestCreateDecision - Main endpoint tests
# =============================================================================


class TestCreateDecision:
    """Test POST /api/decisions endpoint."""

    def test_create_accept_decision_success(self, client, mock_db):
        """Test successful accept decision creation."""
        # Setup mock
        mock_db.get_review_candidate.return_value = {
            "candidate_id": 123,
            "filing_id": 5,
            "review_status": "pending",
        }
        mock_db.get_decision_for_candidate.return_value = None
        mock_db.get_metric_by_id.return_value = {
            "metric_id": "active_customers",
            "status": "active",
        }
        mock_db.insert_review_decision.return_value = 456
        # Mock next candidate navigation (lightweight ID-only query)
        mock_db.get_next_pending_candidate_id.return_value = 124

        # Make request
        with patch("src.web.routes.api.get_db", return_value=mock_db):
            response = client.post(
                "/api/decisions",
                json={
                    "candidate_id": 123,
                    "decision": "accept",
                    "assigned_metric_id": "active_customers",
                    "review_time_seconds": 45,
                },
            )

        # Verify response
        assert response.status_code == 201
        data = json.loads(response.data)
        assert data["status"] == "success"
        assert data["decision_id"] == 456
        assert data["candidate_id"] == 123
        assert data["next_candidate"]["candidate_id"] == 124
        # URL now uses query params format with filter preservation
        assert "/review/5?candidate_id=124" in data["next_candidate"]["url"]

        # Verify database calls
        mock_db.get_review_candidate.assert_called_once_with(123)
        mock_db.get_decision_for_candidate.assert_called_once_with(123)
        mock_db.insert_review_decision.assert_called_once_with(
            candidate_id=123,
            decision="accept",
            assigned_metric_id="active_customers",
            rejection_category=None,
            rejection_reason=None,
            reviewer_id=None,
            reviewer_notes=None,
            review_time_seconds=45,
        )
        # Status update happens atomically inside insert_review_decision()
        # No separate update_candidate_status call expected

    def test_create_reject_decision_success(self, client, mock_db):
        """Test successful reject decision creation."""
        # Setup mock
        mock_db.get_review_candidate.return_value = {
            "candidate_id": 123,
            "filing_id": 5,
            "review_status": "pending",
        }
        mock_db.get_decision_for_candidate.return_value = None
        mock_db.insert_review_decision.return_value = 456
        mock_db.get_next_pending_candidate_id.return_value = None  # No next candidate

        # Make request
        with patch("src.web.routes.api.get_db", return_value=mock_db):
            response = client.post(
                "/api/decisions",
                json={
                    "candidate_id": 123,
                    "decision": "reject",
                    "rejection_category": "wrong_metric",
                    "rejection_reason": "This is ARR, not CAC",
                    "reviewer_notes": "Checked definition",
                },
            )

        # Verify response
        assert response.status_code == 201
        data = json.loads(response.data)
        assert data["status"] == "success"
        assert data["decision_id"] == 456
        assert data["next_candidate"] is None

        # Verify database calls
        mock_db.insert_review_decision.assert_called_once_with(
            candidate_id=123,
            decision="reject",
            assigned_metric_id=None,
            rejection_category="wrong_metric",
            rejection_reason="This is ARR, not CAC",
            reviewer_id=None,
            reviewer_notes="Checked definition",
            review_time_seconds=None,
        )

    def test_create_reclassify_decision_success(self, client, mock_db):
        """Test successful reclassify decision creation."""
        # Setup mock
        mock_db.get_review_candidate.return_value = {
            "candidate_id": 123,
            "filing_id": 5,
            "review_status": "pending",
        }
        mock_db.get_decision_for_candidate.return_value = None
        mock_db.get_metric_by_id.return_value = {
            "metric_id": "arr",
            "status": "active",
        }
        mock_db.insert_review_decision.return_value = 456
        mock_db.get_next_pending_candidate_id.return_value = 124

        # Make request
        with patch("src.web.routes.api.get_db", return_value=mock_db):
            response = client.post(
                "/api/decisions",
                json={
                    "candidate_id": 123,
                    "decision": "reclassify",
                    "assigned_metric_id": "arr",
                },
            )

        # Verify response
        assert response.status_code == 201
        data = json.loads(response.data)
        assert data["status"] == "success"

        # Verify database calls
        mock_db.insert_review_decision.assert_called_once_with(
            candidate_id=123,
            decision="reclassify",
            assigned_metric_id="arr",
            rejection_category=None,
            rejection_reason=None,
            reviewer_id=None,
            reviewer_notes=None,
            review_time_seconds=None,
        )

    def test_missing_candidate_id(self, client, mock_db):
        """Test validation error when candidate_id is missing."""
        with patch("src.web.routes.api.get_db", return_value=mock_db):
            response = client.post(
                "/api/decisions",
                json={
                    "decision": "accept",
                    "assigned_metric_id": "active_customers",
                },
            )

        assert response.status_code == 400
        data = json.loads(response.data)
        assert data["status"] == "error"
        assert "candidate_id" in data["errors"]

    def test_missing_decision(self, client, mock_db):
        """Test validation error when decision is missing."""
        with patch("src.web.routes.api.get_db", return_value=mock_db):
            response = client.post(
                "/api/decisions",
                json={"candidate_id": 123},
            )

        assert response.status_code == 400
        data = json.loads(response.data)
        assert data["status"] == "error"
        assert "decision" in data["errors"]

    def test_invalid_decision_type(self, client, mock_db):
        """Test validation error when decision type is invalid."""
        with patch("src.web.routes.api.get_db", return_value=mock_db):
            response = client.post(
                "/api/decisions",
                json={
                    "candidate_id": 123,
                    "decision": "invalid_decision",
                },
            )

        assert response.status_code == 400
        data = json.loads(response.data)
        assert data["status"] == "error"
        assert "decision" in data["errors"]
        assert "invalid_decision" in data["errors"]["decision"]

    def test_accept_missing_metric_id(self, client, mock_db):
        """Test validation error when accept decision is missing metric_id."""
        with patch("src.web.routes.api.get_db", return_value=mock_db):
            response = client.post(
                "/api/decisions",
                json={
                    "candidate_id": 123,
                    "decision": "accept",
                },
            )

        assert response.status_code == 400
        data = json.loads(response.data)
        assert data["status"] == "error"
        assert "assigned_metric_id" in data["errors"]

    def test_reject_missing_category(self, client, mock_db):
        """Test validation error when reject decision is missing category."""
        with patch("src.web.routes.api.get_db", return_value=mock_db):
            response = client.post(
                "/api/decisions",
                json={
                    "candidate_id": 123,
                    "decision": "reject",
                },
            )

        assert response.status_code == 400
        data = json.loads(response.data)
        assert data["status"] == "error"
        assert "rejection_category" in data["errors"]

    def test_reject_invalid_category(self, client, mock_db):
        """Test validation error when rejection category is invalid."""
        with patch("src.web.routes.api.get_db", return_value=mock_db):
            response = client.post(
                "/api/decisions",
                json={
                    "candidate_id": 123,
                    "decision": "reject",
                    "rejection_category": "invalid_category",
                },
            )

        assert response.status_code == 400
        data = json.loads(response.data)
        assert data["status"] == "error"
        assert "rejection_category" in data["errors"]

    def test_candidate_not_found(self, client, mock_db):
        """Test 404 error when candidate doesn't exist."""
        # Setup mock
        mock_db.get_review_candidate.return_value = None

        # Make request
        with patch("src.web.routes.api.get_db", return_value=mock_db):
            response = client.post(
                "/api/decisions",
                json={
                    "candidate_id": 999,
                    "decision": "accept",
                    "assigned_metric_id": "active_customers",
                },
            )

        # Verify response
        assert response.status_code == 404
        data = json.loads(response.data)
        assert data["status"] == "error"
        assert "not found" in data["message"].lower()

    def test_candidate_already_reviewed(self, client, mock_db):
        """Test 409 conflict when candidate already has a decision."""
        # Setup mock
        mock_db.get_review_candidate.return_value = {
            "candidate_id": 123,
            "filing_id": 5,
            "review_status": "reviewed",
        }
        mock_db.get_decision_for_candidate.return_value = {
            "decision_id": 789,
            "decision": "accept",
        }

        # Make request
        with patch("src.web.routes.api.get_db", return_value=mock_db):
            response = client.post(
                "/api/decisions",
                json={
                    "candidate_id": 123,
                    "decision": "accept",
                    "assigned_metric_id": "active_customers",
                },
            )

        # Verify response
        assert response.status_code == 409
        data = json.loads(response.data)
        assert data["status"] == "error"
        assert "already has a decision" in data["message"]
        assert data["existing_decision_id"] == 789

    def test_invalid_json(self, client, mock_db):
        """Test 400 error when request is not JSON."""
        with patch("src.web.routes.api.get_db", return_value=mock_db):
            response = client.post(
                "/api/decisions",
                data="not json",
                content_type="text/plain",
            )

        assert response.status_code == 400
        data = json.loads(response.data)
        assert data["status"] == "error"
        assert "JSON" in data["message"]

    def test_database_error(self, client, mock_db):
        """Test 500 error when database operation fails."""
        # Setup mock to raise exception
        mock_db.get_review_candidate.side_effect = Exception("Database error")

        # Make request
        with patch("src.web.routes.api.get_db", return_value=mock_db):
            response = client.post(
                "/api/decisions",
                json={
                    "candidate_id": 123,
                    "decision": "accept",
                    "assigned_metric_id": "active_customers",
                },
            )

        # Verify response
        assert response.status_code == 500
        data = json.loads(response.data)
        assert data["status"] == "error"
        assert "Internal server error" in data["message"]

    def test_foreign_key_violation(self, client, mock_db):
        """Test 400 error when invalid metric_id is provided."""
        # Setup mock to raise ForeignKeyViolation
        mock_db.get_review_candidate.return_value = {
            "candidate_id": 123,
            "filing_id": 5,
            "review_status": "pending",
        }
        mock_db.get_decision_for_candidate.return_value = None
        mock_db.insert_review_decision.side_effect = (
            psycopg.errors.ForeignKeyViolation("Foreign key violation")
        )

        # Make request
        with patch("src.web.routes.api.get_db", return_value=mock_db):
            response = client.post(
                "/api/decisions",
                json={
                    "candidate_id": 123,
                    "decision": "accept",
                    "assigned_metric_id": "invalid_metric",
                },
            )

        # Verify response
        assert response.status_code == 400
        data = json.loads(response.data)
        assert data["status"] == "error"
        assert "Invalid metric_id" in data["message"]
        assert "invalid_metric" in data["message"]
        assert data["error_type"] == "foreign_key_violation"

    def test_unique_violation(self, client, mock_db):
        """Test 409 error when duplicate decision is created (race condition)."""
        # Setup mock to raise UniqueViolation
        mock_db.get_review_candidate.return_value = {
            "candidate_id": 123,
            "filing_id": 5,
            "review_status": "pending",
        }
        mock_db.get_decision_for_candidate.return_value = None
        mock_db.insert_review_decision.side_effect = psycopg.errors.UniqueViolation(
            "Unique constraint violation"
        )

        # Make request
        with patch("src.web.routes.api.get_db", return_value=mock_db):
            response = client.post(
                "/api/decisions",
                json={
                    "candidate_id": 123,
                    "decision": "accept",
                    "assigned_metric_id": "active_customers",
                },
            )

        # Verify response
        assert response.status_code == 409
        data = json.loads(response.data)
        assert data["status"] == "error"
        assert "already exists" in data["message"]
        assert data["error_type"] == "duplicate_decision"

    def test_not_null_violation(self, client, mock_db):
        """Test 400 error when NOT NULL constraint is violated."""
        # Setup mock to raise NotNullViolation
        mock_db.get_review_candidate.return_value = {
            "candidate_id": 123,
            "filing_id": 5,
            "review_status": "pending",
        }
        mock_db.get_decision_for_candidate.return_value = None
        mock_db.insert_review_decision.side_effect = psycopg.errors.NotNullViolation(
            "NOT NULL constraint violation"
        )

        # Make request
        with patch("src.web.routes.api.get_db", return_value=mock_db):
            response = client.post(
                "/api/decisions",
                json={
                    "candidate_id": 123,
                    "decision": "accept",
                    "assigned_metric_id": "active_customers",
                },
            )

        # Verify response
        assert response.status_code == 400
        data = json.loads(response.data)
        assert data["status"] == "error"
        assert "Missing required field" in data["message"]
        assert data["error_type"] == "not_null_violation"

    def test_check_violation(self, client, mock_db):
        """Test 400 error when CHECK constraint is violated."""
        # Setup mock to raise CheckViolation
        mock_db.get_review_candidate.return_value = {
            "candidate_id": 123,
            "filing_id": 5,
            "review_status": "pending",
        }
        mock_db.get_decision_for_candidate.return_value = None
        mock_db.insert_review_decision.side_effect = psycopg.errors.CheckViolation(
            "CHECK constraint violation"
        )

        # Make request
        with patch("src.web.routes.api.get_db", return_value=mock_db):
            response = client.post(
                "/api/decisions",
                json={
                    "candidate_id": 123,
                    "decision": "accept",
                    "assigned_metric_id": "active_customers",
                },
            )

        # Verify response
        assert response.status_code == 400
        data = json.loads(response.data)
        assert data["status"] == "error"
        assert "Data validation failed" in data["message"]
        assert data["error_type"] == "check_violation"

    def test_integrity_error(self, client, mock_db):
        """Test 400 error for other integrity constraint violations."""
        # Setup mock to raise generic IntegrityError
        mock_db.get_review_candidate.return_value = {
            "candidate_id": 123,
            "filing_id": 5,
            "review_status": "pending",
        }
        mock_db.get_decision_for_candidate.return_value = None
        mock_db.insert_review_decision.side_effect = psycopg.IntegrityError(
            "Integrity constraint violation"
        )

        # Make request
        with patch("src.web.routes.api.get_db", return_value=mock_db):
            response = client.post(
                "/api/decisions",
                json={
                    "candidate_id": 123,
                    "decision": "accept",
                    "assigned_metric_id": "active_customers",
                },
            )

        # Verify response
        assert response.status_code == 400
        data = json.loads(response.data)
        assert data["status"] == "error"
        assert "integrity constraint" in data["message"]
        assert data["error_type"] == "integrity_error"

    def test_operational_error(self, client, mock_db):
        """Test 503 error when database is unavailable."""
        # Setup mock to raise OperationalError
        mock_db.get_review_candidate.return_value = {
            "candidate_id": 123,
            "filing_id": 5,
            "review_status": "pending",
        }
        mock_db.get_decision_for_candidate.return_value = None
        mock_db.insert_review_decision.side_effect = psycopg.OperationalError(
            "Database connection failed"
        )

        # Make request
        with patch("src.web.routes.api.get_db", return_value=mock_db):
            response = client.post(
                "/api/decisions",
                json={
                    "candidate_id": 123,
                    "decision": "accept",
                    "assigned_metric_id": "active_customers",
                },
            )

        # Verify response
        assert response.status_code == 503
        data = json.loads(response.data)
        assert data["status"] == "error"
        assert "temporarily unavailable" in data["message"]
        assert data["error_type"] == "database_unavailable"

    def test_database_error_generic(self, client, mock_db):
        """Test 500 error for other database errors."""
        # Setup mock to raise generic DatabaseError
        mock_db.get_review_candidate.return_value = {
            "candidate_id": 123,
            "filing_id": 5,
            "review_status": "pending",
        }
        mock_db.get_decision_for_candidate.return_value = None
        mock_db.insert_review_decision.side_effect = psycopg.DatabaseError(
            "Unexpected database error"
        )

        # Make request
        with patch("src.web.routes.api.get_db", return_value=mock_db):
            response = client.post(
                "/api/decisions",
                json={
                    "candidate_id": 123,
                    "decision": "accept",
                    "assigned_metric_id": "active_customers",
                },
            )

        # Verify response
        assert response.status_code == 500
        data = json.loads(response.data)
        assert data["status"] == "error"
        assert "Database error" in data["message"]
        assert data["error_type"] == "database_error"

    def test_next_candidate_returned(self, client, mock_db):
        """Test that next candidate info is returned in response."""
        # Setup mock
        mock_db.get_review_candidate.return_value = {
            "candidate_id": 123,
            "filing_id": 5,
            "review_status": "pending",
        }
        mock_db.get_decision_for_candidate.return_value = None
        mock_db.get_metric_by_id.return_value = {
            "metric_id": "active_customers",
            "status": "active",
        }
        mock_db.insert_review_decision.return_value = 456
        mock_db.get_next_pending_candidate_id.return_value = 999

        # Make request
        with patch("src.web.routes.api.get_db", return_value=mock_db):
            response = client.post(
                "/api/decisions",
                json={
                    "candidate_id": 123,
                    "decision": "accept",
                    "assigned_metric_id": "active_customers",
                },
            )

        # Verify next candidate in response
        data = json.loads(response.data)
        assert data["next_candidate"]["candidate_id"] == 999
        # URL now uses query params format
        assert "/review/5?candidate_id=999" in data["next_candidate"]["url"]

    def test_last_candidate_no_next(self, client, mock_db):
        """Test that next_candidate is null when no more pending."""
        # Setup mock
        mock_db.get_review_candidate.return_value = {
            "candidate_id": 123,
            "filing_id": 5,
            "review_status": "pending",
        }
        mock_db.get_decision_for_candidate.return_value = None
        mock_db.get_metric_by_id.return_value = {
            "metric_id": "active_customers",
            "status": "active",
        }
        mock_db.insert_review_decision.return_value = 456
        mock_db.get_next_pending_candidate_id.return_value = None  # No next candidate

        # Make request
        with patch("src.web.routes.api.get_db", return_value=mock_db):
            response = client.post(
                "/api/decisions",
                json={
                    "candidate_id": 123,
                    "decision": "accept",
                    "assigned_metric_id": "active_customers",
                },
            )

        # Verify next_candidate is null
        data = json.loads(response.data)
        assert data["next_candidate"] is None

    def test_invalid_metric_id(self, client, mock_db):
        """Test 500 error when assigned_metric_id doesn't exist (caught by DB foreign key)."""
        # Setup mock - simulate database foreign key error
        mock_db.get_review_candidate.return_value = {
            "candidate_id": 123,
            "filing_id": 5,
            "review_status": "pending",
        }
        mock_db.get_decision_for_candidate.return_value = None
        # Simulate foreign key constraint violation
        mock_db.insert_review_decision.side_effect = Exception(
            "foreign key constraint violation"
        )

        # Make request
        with patch("src.web.routes.api.get_db", return_value=mock_db):
            response = client.post(
                "/api/decisions",
                json={
                    "candidate_id": 123,
                    "decision": "accept",
                    "assigned_metric_id": "invalid_metric",
                },
            )

        # Verify response - database error returns 500
        assert response.status_code == 500
        data = json.loads(response.data)
        assert data["status"] == "error"


# =============================================================================
# TestGetCandidate - Future enhancement
# =============================================================================


class TestGetCandidate:
    """Test GET /api/candidates/<id> endpoint (future enhancement)."""

    def test_not_implemented(self, client):
        """Test that endpoint returns 501 Not Implemented."""
        response = client.get("/api/candidates/123")
        assert response.status_code == 501
        data = json.loads(response.data)
        assert data["status"] == "error"
        assert "Not implemented" in data["message"]


# =============================================================================
# TestGetFilingProgress - Future enhancement
# =============================================================================


class TestGetFilingProgress:
    """Test GET /api/filings/<id>/progress endpoint (future enhancement)."""

    def test_not_implemented(self, client):
        """Test that endpoint returns 501 Not Implemented."""
        response = client.get("/api/filings/5/progress")
        assert response.status_code == 501
        data = json.loads(response.data)
        assert data["status"] == "error"
        assert "Not implemented" in data["message"]


# =============================================================================
# TestValidationHelpers - Validation logic tests
# =============================================================================


class TestValidationHelpers:
    """Test validation helper functions."""

    def test_validate_accept_decision(self, client, mock_db):
        """Test that accept decision requires metric_id."""
        with patch("src.web.routes.api.get_db", return_value=mock_db):
            response = client.post(
                "/api/decisions",
                json={
                    "candidate_id": 123,
                    "decision": "accept",
                    # Missing assigned_metric_id
                },
            )

        assert response.status_code == 400
        data = json.loads(response.data)
        assert "assigned_metric_id" in data["errors"]

    def test_validate_reject_decision(self, client, mock_db):
        """Test that reject decision requires category."""
        with patch("src.web.routes.api.get_db", return_value=mock_db):
            response = client.post(
                "/api/decisions",
                json={
                    "candidate_id": 123,
                    "decision": "reject",
                    # Missing rejection_category
                },
            )

        assert response.status_code == 400
        data = json.loads(response.data)
        assert "rejection_category" in data["errors"]

    def test_validate_reclassify_decision(self, client, mock_db):
        """Test that reclassify decision requires metric_id."""
        with patch("src.web.routes.api.get_db", return_value=mock_db):
            response = client.post(
                "/api/decisions",
                json={
                    "candidate_id": 123,
                    "decision": "reclassify",
                    # Missing assigned_metric_id
                },
            )

        assert response.status_code == 400
        data = json.loads(response.data)
        assert "assigned_metric_id" in data["errors"]

    def test_invalid_decision_type_validation(self, client, mock_db):
        """Test validation of invalid decision type."""
        with patch("src.web.routes.api.get_db", return_value=mock_db):
            response = client.post(
                "/api/decisions",
                json={
                    "candidate_id": 123,
                    "decision": "skip",  # Invalid
                },
            )

        assert response.status_code == 400
        data = json.loads(response.data)
        assert "decision" in data["errors"]

    def test_invalid_rejection_category_validation(self, client, mock_db):
        """Test validation of invalid rejection category."""
        with patch("src.web.routes.api.get_db", return_value=mock_db):
            response = client.post(
                "/api/decisions",
                json={
                    "candidate_id": 123,
                    "decision": "reject",
                    "rejection_category": "bad_category",
                },
            )

        assert response.status_code == 400
        data = json.loads(response.data)
        assert "rejection_category" in data["errors"]

    def test_negative_review_time(self, client, mock_db):
        """Test validation of negative review_time_seconds."""
        with patch("src.web.routes.api.get_db", return_value=mock_db):
            response = client.post(
                "/api/decisions",
                json={
                    "candidate_id": 123,
                    "decision": "accept",
                    "assigned_metric_id": "active_customers",
                    "review_time_seconds": -5,
                },
            )

        assert response.status_code == 400
        data = json.loads(response.data)
        assert "review_time_seconds" in data["errors"]

    def test_all_optional_fields(self, client, mock_db):
        """Test accept with all optional fields."""
        # Setup mock
        mock_db.get_review_candidate.return_value = {
            "candidate_id": 123,
            "filing_id": 5,
            "review_status": "pending",
        }
        mock_db.get_decision_for_candidate.return_value = None
        mock_db.get_metric_by_id.return_value = {
            "metric_id": "active_customers",
            "status": "active",
        }
        mock_db.insert_review_decision.return_value = 456
        mock_db.get_next_pending_candidate_id.return_value = None

        # Make request
        with patch("src.web.routes.api.get_db", return_value=mock_db):
            response = client.post(
                "/api/decisions",
                json={
                    "candidate_id": 123,
                    "decision": "accept",
                    "assigned_metric_id": "active_customers",
                    "reviewer_notes": "Looks good",
                    "review_time_seconds": 45,
                },
            )

        assert response.status_code == 201
        mock_db.insert_review_decision.assert_called_once_with(
            candidate_id=123,
            decision="accept",
            assigned_metric_id="active_customers",
            rejection_category=None,
            rejection_reason=None,
            reviewer_id=None,
            reviewer_notes="Looks good",
            review_time_seconds=45,
        )

    def test_empty_request(self, client, mock_db):
        """Test validation errors for empty request."""
        with patch("src.web.routes.api.get_db", return_value=mock_db):
            response = client.post(
                "/api/decisions",
                json={},
            )

        assert response.status_code == 400
        data = json.loads(response.data)
        assert "candidate_id" in data["errors"]
        assert "decision" in data["errors"]

    def test_rejection_reason_too_long(self, client, mock_db):
        """Test validation of rejection_reason max length."""
        with patch("src.web.routes.api.get_db", return_value=mock_db):
            response = client.post(
                "/api/decisions",
                json={
                    "candidate_id": 123,
                    "decision": "reject",
                    "rejection_category": "wrong_metric",
                    "rejection_reason": "x" * 501,  # Too long
                },
            )

        assert response.status_code == 400
        data = json.loads(response.data)
        assert "rejection_reason" in data["errors"]

    def test_reviewer_notes_too_long(self, client, mock_db):
        """Test validation of reviewer_notes max length."""
        with patch("src.web.routes.api.get_db", return_value=mock_db):
            response = client.post(
                "/api/decisions",
                json={
                    "candidate_id": 123,
                    "decision": "accept",
                    "assigned_metric_id": "active_customers",
                    "reviewer_notes": "x" * 1001,  # Too long
                },
            )

        assert response.status_code == 400
        data = json.loads(response.data)
        assert "reviewer_notes" in data["errors"]


# =============================================================================
# TestExpandedContext - Context expansion endpoint tests (HRI-9)
# =============================================================================


class TestExpandedContext:
    """Test GET /api/candidates/<id>/expanded-context endpoint."""

    def test_expanded_context_success(self, client, mock_db):
        """Test successful expanded context fetch."""
        # Setup mock
        mock_db.get_expanded_context_for_candidate.return_value = {
            "expanded_context": "This is expanded context with more surrounding text...",
            "segment_count": 5,
            "can_expand": True,
        }

        # Make request
        with patch("src.web.routes.api.get_db", return_value=mock_db):
            response = client.get("/api/candidates/123/expanded-context")

        # Verify response
        assert response.status_code == 200
        data = json.loads(response.data)
        assert data["status"] == "success"
        assert data["expanded_context"] == "This is expanded context with more surrounding text..."
        assert data["segment_count"] == 5
        assert data["can_expand"] is True

        # Verify database call
        mock_db.get_expanded_context_for_candidate.assert_called_once_with(123)

    def test_expanded_context_no_source_segment(self, client, mock_db):
        """Test expanded context when candidate has no source_segment_id."""
        # Setup mock - returns current context only when no source segment
        mock_db.get_expanded_context_for_candidate.return_value = {
            "expanded_context": "Current context only",
            "segment_count": 0,
            "can_expand": False,
        }

        # Make request
        with patch("src.web.routes.api.get_db", return_value=mock_db):
            response = client.get("/api/candidates/456/expanded-context")

        # Verify response
        assert response.status_code == 200
        data = json.loads(response.data)
        assert data["status"] == "success"
        assert data["can_expand"] is False
        assert data["segment_count"] == 0

    def test_expanded_context_candidate_not_found(self, client, mock_db):
        """Test expanded context when candidate doesn't exist."""
        # Setup mock - returns None when candidate not found
        mock_db.get_expanded_context_for_candidate.return_value = None

        # Make request
        with patch("src.web.routes.api.get_db", return_value=mock_db):
            response = client.get("/api/candidates/999/expanded-context")

        # Verify response
        assert response.status_code == 404
        data = json.loads(response.data)
        assert data["status"] == "error"
        assert data["message"] == "Candidate not found"

    def test_expanded_context_database_error(self, client, mock_db):
        """Test expanded context handles database errors."""
        # Setup mock to raise database error
        mock_db.get_expanded_context_for_candidate.side_effect = psycopg.DatabaseError(
            "Connection lost"
        )

        # Make request
        with patch("src.web.routes.api.get_db", return_value=mock_db):
            response = client.get("/api/candidates/123/expanded-context")

        # Verify response
        assert response.status_code == 500
        data = json.loads(response.data)
        assert data["status"] == "error"
        assert data["error_type"] == "database_error"

    def test_expanded_context_at_filing_boundary(self, client, mock_db):
        """Test expanded context when segment is at beginning/end of filing."""
        # Setup mock - fewer segments available at boundary
        mock_db.get_expanded_context_for_candidate.return_value = {
            "expanded_context": "Limited context at filing start...",
            "segment_count": 2,  # Only 2 segments available instead of 5
            "can_expand": True,
        }

        # Make request
        with patch("src.web.routes.api.get_db", return_value=mock_db):
            response = client.get("/api/candidates/789/expanded-context")

        # Verify response
        assert response.status_code == 200
        data = json.loads(response.data)
        assert data["status"] == "success"
        assert data["segment_count"] == 2
        assert data["can_expand"] is True


# =============================================================================
# TestSkipCandidate - Skip endpoint tests (UXI-3)
# =============================================================================


class TestSkipCandidate:
    """Test POST /api/candidates/<id>/skip endpoint."""

    def test_skip_pending_candidate_success(self, client, mock_db):
        """Test successful skip of a pending candidate."""
        # Setup mock
        mock_db.get_review_candidate.return_value = {
            "candidate_id": 123,
            "filing_id": 5,
            "review_status": "pending",
        }
        mock_db.update_candidate_status.return_value = True
        # Mock next candidate navigation (lightweight ID-only query)
        mock_db.get_next_pending_candidate_id.return_value = 124

        # Make request
        with patch("src.web.routes.api.get_db", return_value=mock_db):
            response = client.post(
                "/api/candidates/123/skip",
                json={
                    "filter_status": "pending",
                    "filter_metric": "all",
                    "filter_confidence": "all",
                    "filter_sort": "position",
                },
            )

        # Verify response
        assert response.status_code == 200
        data = json.loads(response.data)
        assert data["status"] == "success"
        assert data["candidate_id"] == 123
        assert data["next_candidate"]["candidate_id"] == 124
        assert "/review/5?candidate_id=124" in data["next_candidate"]["url"]

        # Verify database calls
        mock_db.get_review_candidate.assert_called_once_with(123)
        mock_db.update_candidate_status.assert_called_once_with(123, "skipped")

    def test_skip_returns_next_candidate_with_filters_preserved(self, client, mock_db):
        """Test skip returns next candidate URL with filter parameters preserved."""
        # Setup mock
        mock_db.get_review_candidate.return_value = {
            "candidate_id": 123,
            "filing_id": 5,
            "review_status": "pending",
        }
        mock_db.update_candidate_status.return_value = True
        mock_db.get_next_pending_candidate_id.return_value = 124

        # Make request with custom filters
        with patch("src.web.routes.api.get_db", return_value=mock_db):
            response = client.post(
                "/api/candidates/123/skip",
                json={
                    "filter_status": "pending",
                    "filter_metric": "cm_average_order_value",
                    "filter_confidence": "high",
                    "filter_sort": "confidence_desc",
                },
            )

        # Verify response
        assert response.status_code == 200
        data = json.loads(response.data)
        assert data["status"] == "success"
        assert "metric=cm_average_order_value" in data["next_candidate"]["url"]
        assert "confidence=high" in data["next_candidate"]["url"]
        assert "sort=confidence_desc" in data["next_candidate"]["url"]

    def test_skip_with_no_next_candidate(self, client, mock_db):
        """Test skip returns null next_candidate when no more pending candidates."""
        # Setup mock
        mock_db.get_review_candidate.return_value = {
            "candidate_id": 123,
            "filing_id": 5,
            "review_status": "pending",
        }
        mock_db.update_candidate_status.return_value = True
        mock_db.get_next_pending_candidate_id.return_value = None  # No more candidates

        # Make request
        with patch("src.web.routes.api.get_db", return_value=mock_db):
            response = client.post("/api/candidates/123/skip", json={})

        # Verify response
        assert response.status_code == 200
        data = json.loads(response.data)
        assert data["status"] == "success"
        assert data["candidate_id"] == 123
        assert data["next_candidate"] is None

    def test_skip_invalid_candidate_returns_404(self, client, mock_db):
        """Test skip with non-existent candidate returns 404."""
        # Setup mock
        mock_db.get_review_candidate.return_value = None

        # Make request
        with patch("src.web.routes.api.get_db", return_value=mock_db):
            response = client.post("/api/candidates/999/skip", json={})

        # Verify response
        assert response.status_code == 404
        data = json.loads(response.data)
        assert data["status"] == "error"
        assert "not found" in data["message"].lower()

    def test_skip_reviewed_candidate_returns_400(self, client, mock_db):
        """Test skip of already-reviewed candidate returns 400 error."""
        # Setup mock - candidate is already reviewed
        mock_db.get_review_candidate.return_value = {
            "candidate_id": 123,
            "filing_id": 5,
            "review_status": "reviewed",  # Already has a decision
        }

        # Make request
        with patch("src.web.routes.api.get_db", return_value=mock_db):
            response = client.post("/api/candidates/123/skip", json={})

        # Verify response
        assert response.status_code == 400
        data = json.loads(response.data)
        assert data["status"] == "error"
        assert "reviewed" in data["message"].lower()
        # Should NOT call update_candidate_status
        mock_db.update_candidate_status.assert_not_called()

    def test_skip_already_skipped_candidate_succeeds(self, client, mock_db):
        """Test re-skipping an already-skipped candidate succeeds (idempotent)."""
        # Setup mock - candidate is already skipped
        mock_db.get_review_candidate.return_value = {
            "candidate_id": 123,
            "filing_id": 5,
            "review_status": "skipped",  # Already skipped
        }
        mock_db.update_candidate_status.return_value = True
        mock_db.get_next_pending_candidate_id.return_value = 124

        # Make request
        with patch("src.web.routes.api.get_db", return_value=mock_db):
            response = client.post("/api/candidates/123/skip", json={})

        # Verify response - should succeed (idempotent)
        assert response.status_code == 200
        data = json.loads(response.data)
        assert data["status"] == "success"
        # Status update should still be called (no-op but safe)
        mock_db.update_candidate_status.assert_called_once_with(123, "skipped")

    def test_skip_database_error_returns_500(self, client, mock_db):
        """Test skip returns 500 on unexpected database error."""
        # Setup mock - database throws exception
        mock_db.get_review_candidate.side_effect = Exception("Database connection lost")

        # Make request
        with patch("src.web.routes.api.get_db", return_value=mock_db):
            response = client.post("/api/candidates/123/skip", json={})

        # Verify response
        assert response.status_code == 500
        data = json.loads(response.data)
        assert data["status"] == "error"
        assert "internal server error" in data["message"].lower()
