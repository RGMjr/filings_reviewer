"""
Unit tests for API routes (D2).

Tests the JSON API endpoints for review decision recording.
Uses mocked database to isolate route logic.
"""

import json
from unittest.mock import MagicMock, patch

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
        mock_db.query.return_value = [{"candidate_id": 124}]

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
        assert data["next_candidate"]["url"] == "/review/5/candidate/124"

        # Verify database calls
        mock_db.get_review_candidate.assert_called_once_with(123)
        mock_db.get_decision_for_candidate.assert_called_once_with(123)
        mock_db.insert_review_decision.assert_called_once_with(
            candidate_id=123,
            decision="accept",
            assigned_metric_id="active_customers",
            rejection_category=None,
            rejection_reason=None,
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
        mock_db.query.return_value = []  # No next candidate

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
        mock_db.query.return_value = [{"candidate_id": 124}]

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
        mock_db.query.return_value = [{"candidate_id": 999}]

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
        assert "/review/5/candidate/999" in data["next_candidate"]["url"]

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
        mock_db.query.return_value = []  # No next candidate

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
        mock_db.query.return_value = []

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
