"""
Unit tests for API audit logging (HRI-2).

Tests the audit logging hooks for the API blueprint to ensure all API calls
are captured in review_audit_log for compliance and debugging.
"""

import json
import time
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
# TestAuditHookRegistration - Hook setup tests
# =============================================================================


class TestAuditHookRegistration:
    """Test that audit logging hooks are properly registered."""

    def test_before_request_sets_start_time(self, client, mock_db):
        """Verify before_request hook sets g.request_start_time."""
        # Track if g.request_start_time was set
        start_time_captured = {}

        def capture_start_time(*args, **kwargs):
            # This mock is called after before_request runs
            from flask import g
            if hasattr(g, "request_start_time"):
                start_time_captured["value"] = g.request_start_time

        # Setup mock - capture start time when get_db is called
        mock_db.get_review_candidate.return_value = None
        mock_db.insert_audit_log = MagicMock()

        with patch("src.web.routes.api.get_db") as mock_get_db:
            mock_get_db.return_value = mock_db
            mock_get_db.side_effect = lambda: (
                capture_start_time() or mock_db
            )

            # Make any API request
            client.post(
                "/api/decisions",
                json={"candidate_id": 123, "decision": "accept", "assigned_metric_id": "test"},
            )

        # Verify start time was captured (value should be a float timestamp)
        assert "value" in start_time_captured
        assert isinstance(start_time_captured["value"], float)
        # Should be recent (within last 5 seconds)
        assert time.time() - start_time_captured["value"] < 5

    def test_after_request_returns_response_unchanged(self, client, mock_db):
        """Verify after_request hook returns response unchanged."""
        # Setup mock
        mock_db.get_review_candidate.return_value = None
        mock_db.insert_audit_log = MagicMock()

        with patch("src.web.routes.api.get_db", return_value=mock_db):
            response = client.post(
                "/api/decisions",
                json={"candidate_id": 999, "decision": "accept", "assigned_metric_id": "test"},
            )

        # Response should be 404 (candidate not found) - unmodified by audit hook
        assert response.status_code == 404
        data = json.loads(response.data)
        assert data["status"] == "error"
        assert "not found" in data["message"].lower()


# =============================================================================
# TestAuditLogContent - Content verification tests
# =============================================================================


class TestAuditLogContent:
    """Test that audit log entries contain correct data."""

    def test_accept_decision_logs_candidate_id(self, client, mock_db):
        """POST /api/decisions logs audit entry with correct candidate_id."""
        # Setup mock
        mock_db.get_review_candidate.return_value = {
            "candidate_id": 123,
            "filing_id": 5,
            "review_status": "pending",
        }
        mock_db.get_decision_for_candidate.return_value = None
        mock_db.insert_review_decision.return_value = 456
        mock_db.query.return_value = []
        mock_db.get_review_candidates_with_decisions.return_value = []  # For next candidate navigation
        mock_db.insert_audit_log = MagicMock(return_value=1)

        with patch("src.web.routes.api.get_db", return_value=mock_db):
            response = client.post(
                "/api/decisions",
                json={
                    "candidate_id": 123,
                    "decision": "accept",
                    "assigned_metric_id": "active_customers",
                },
            )

        # Verify audit log was called with candidate_id
        assert response.status_code == 201
        mock_db.insert_audit_log.assert_called_once()
        call_kwargs = mock_db.insert_audit_log.call_args[1]
        assert call_kwargs["candidate_id"] == 123

    def test_decision_type_captured_in_query_params(self, client, mock_db):
        """Decision type (accept/reject/reclassify) captured in query_params."""
        # Setup mock
        mock_db.get_review_candidate.return_value = {
            "candidate_id": 123,
            "filing_id": 5,
            "review_status": "pending",
        }
        mock_db.get_decision_for_candidate.return_value = None
        mock_db.insert_review_decision.return_value = 456
        mock_db.query.return_value = []
        mock_db.get_review_candidates_with_decisions.return_value = []  # For next candidate navigation
        mock_db.insert_audit_log = MagicMock(return_value=1)

        with patch("src.web.routes.api.get_db", return_value=mock_db):
            response = client.post(
                "/api/decisions",
                json={
                    "candidate_id": 123,
                    "decision": "accept",
                    "assigned_metric_id": "cm_arr",
                },
            )

        # Verify query_params contains decision details
        assert response.status_code == 201
        call_kwargs = mock_db.insert_audit_log.call_args[1]
        query_params = call_kwargs["query_params"]
        assert query_params["decision"] == "accept"
        assert query_params["assigned_metric_id"] == "cm_arr"

    def test_reject_decision_captures_rejection_category(self, client, mock_db):
        """Rejection category captured in query_params for reject decisions."""
        # Setup mock
        mock_db.get_review_candidate.return_value = {
            "candidate_id": 123,
            "filing_id": 5,
            "review_status": "pending",
        }
        mock_db.get_decision_for_candidate.return_value = None
        mock_db.insert_review_decision.return_value = 456
        mock_db.query.return_value = []
        mock_db.get_review_candidates_with_decisions.return_value = []  # For next candidate navigation
        mock_db.insert_audit_log = MagicMock(return_value=1)

        with patch("src.web.routes.api.get_db", return_value=mock_db):
            response = client.post(
                "/api/decisions",
                json={
                    "candidate_id": 123,
                    "decision": "reject",
                    "rejection_category": "wrong_metric",
                },
            )

        # Verify query_params contains rejection details
        assert response.status_code == 201
        call_kwargs = mock_db.insert_audit_log.call_args[1]
        query_params = call_kwargs["query_params"]
        assert query_params["decision"] == "reject"
        assert query_params["rejection_category"] == "wrong_metric"

    def test_response_status_201_captured(self, client, mock_db):
        """Response status 201 captured for successful decision creation."""
        # Setup mock
        mock_db.get_review_candidate.return_value = {
            "candidate_id": 123,
            "filing_id": 5,
            "review_status": "pending",
        }
        mock_db.get_decision_for_candidate.return_value = None
        mock_db.insert_review_decision.return_value = 456
        mock_db.query.return_value = []
        mock_db.get_review_candidates_with_decisions.return_value = []  # For next candidate navigation
        mock_db.insert_audit_log = MagicMock(return_value=1)

        with patch("src.web.routes.api.get_db", return_value=mock_db):
            response = client.post(
                "/api/decisions",
                json={
                    "candidate_id": 123,
                    "decision": "accept",
                    "assigned_metric_id": "active_customers",
                },
            )

        assert response.status_code == 201
        call_kwargs = mock_db.insert_audit_log.call_args[1]
        assert call_kwargs["response_status"] == 201

    def test_response_status_400_captured(self, client, mock_db):
        """Response status 400 captured for validation errors."""
        mock_db.insert_audit_log = MagicMock(return_value=1)

        with patch("src.web.routes.api.get_db", return_value=mock_db):
            response = client.post(
                "/api/decisions",
                json={
                    # Missing required fields
                },
            )

        assert response.status_code == 400
        call_kwargs = mock_db.insert_audit_log.call_args[1]
        assert call_kwargs["response_status"] == 400

    def test_response_status_404_captured(self, client, mock_db):
        """Response status 404 captured when candidate not found."""
        mock_db.get_review_candidate.return_value = None
        mock_db.insert_audit_log = MagicMock(return_value=1)

        with patch("src.web.routes.api.get_db", return_value=mock_db):
            response = client.post(
                "/api/decisions",
                json={
                    "candidate_id": 999,
                    "decision": "accept",
                    "assigned_metric_id": "test",
                },
            )

        assert response.status_code == 404
        call_kwargs = mock_db.insert_audit_log.call_args[1]
        assert call_kwargs["response_status"] == 404

    def test_response_status_409_captured(self, client, mock_db):
        """Response status 409 captured when candidate already reviewed."""
        mock_db.get_review_candidate.return_value = {
            "candidate_id": 123,
            "filing_id": 5,
            "review_status": "reviewed",
        }
        mock_db.get_decision_for_candidate.return_value = {
            "decision_id": 789,
            "decision": "accept",
        }
        mock_db.insert_audit_log = MagicMock(return_value=1)

        with patch("src.web.routes.api.get_db", return_value=mock_db):
            response = client.post(
                "/api/decisions",
                json={
                    "candidate_id": 123,
                    "decision": "accept",
                    "assigned_metric_id": "test",
                },
            )

        assert response.status_code == 409
        call_kwargs = mock_db.insert_audit_log.call_args[1]
        assert call_kwargs["response_status"] == 409

    def test_response_time_calculated(self, client, mock_db):
        """Response time in milliseconds is calculated and stored."""
        # Setup mock
        mock_db.get_review_candidate.return_value = {
            "candidate_id": 123,
            "filing_id": 5,
            "review_status": "pending",
        }
        mock_db.get_decision_for_candidate.return_value = None
        mock_db.insert_review_decision.return_value = 456
        mock_db.query.return_value = []
        mock_db.get_review_candidates_with_decisions.return_value = []  # For next candidate navigation
        mock_db.insert_audit_log = MagicMock(return_value=1)

        with patch("src.web.routes.api.get_db", return_value=mock_db):
            response = client.post(
                "/api/decisions",
                json={
                    "candidate_id": 123,
                    "decision": "accept",
                    "assigned_metric_id": "active_customers",
                },
            )

        assert response.status_code == 201
        call_kwargs = mock_db.insert_audit_log.call_args[1]
        response_time_ms = call_kwargs["response_time_ms"]
        # Should be a non-negative integer
        assert isinstance(response_time_ms, int)
        assert response_time_ms >= 0
        # Should be reasonable (less than 5 seconds for unit test)
        assert response_time_ms < 5000

    def test_route_name_captured(self, client, mock_db):
        """Route name (endpoint) is captured in audit log."""
        mock_db.get_review_candidate.return_value = None
        mock_db.insert_audit_log = MagicMock(return_value=1)

        with patch("src.web.routes.api.get_db", return_value=mock_db):
            client.post(
                "/api/decisions",
                json={
                    "candidate_id": 123,
                    "decision": "accept",
                    "assigned_metric_id": "test",
                },
            )

        call_kwargs = mock_db.insert_audit_log.call_args[1]
        # Should contain 'api' in route name
        assert "api" in call_kwargs["route_name"]
        assert call_kwargs["http_method"] == "POST"
        assert call_kwargs["url_path"] == "/api/decisions"


# =============================================================================
# TestAuditEdgeCases - Edge case handling tests
# =============================================================================


class TestAuditEdgeCases:
    """Test edge cases in audit logging."""

    def test_non_json_request_handled_gracefully(self, client, mock_db):
        """Non-JSON request body handled gracefully (empty query_params)."""
        mock_db.insert_audit_log = MagicMock(return_value=1)

        with patch("src.web.routes.api.get_db", return_value=mock_db):
            response = client.post(
                "/api/decisions",
                data="not json",
                content_type="text/plain",
            )

        # Should still return 400 and log the request
        assert response.status_code == 400
        mock_db.insert_audit_log.assert_called_once()
        call_kwargs = mock_db.insert_audit_log.call_args[1]
        # query_params should be None for non-JSON requests
        assert call_kwargs["query_params"] is None
        assert call_kwargs["candidate_id"] is None

    def test_database_error_in_logging_does_not_break_response(self, client, mock_db):
        """Database error in audit logging doesn't break API response."""
        # Setup mock - main operations succeed
        mock_db.get_review_candidate.return_value = {
            "candidate_id": 123,
            "filing_id": 5,
            "review_status": "pending",
        }
        mock_db.get_decision_for_candidate.return_value = None
        mock_db.insert_review_decision.return_value = 456
        mock_db.query.return_value = []
        mock_db.get_review_candidates_with_decisions.return_value = []  # For next candidate navigation
        # Audit log fails
        mock_db.insert_audit_log.side_effect = Exception("Database connection lost")

        with patch("src.web.routes.api.get_db", return_value=mock_db):
            response = client.post(
                "/api/decisions",
                json={
                    "candidate_id": 123,
                    "decision": "accept",
                    "assigned_metric_id": "active_customers",
                },
            )

        # Response should still be successful despite audit log failure
        assert response.status_code == 201
        data = json.loads(response.data)
        assert data["status"] == "success"
        assert data["decision_id"] == 456

    def test_get_endpoint_extracts_url_params(self, client, mock_db):
        """GET endpoints extract filing_id and candidate_id from URL params."""
        mock_db.insert_audit_log = MagicMock(return_value=1)

        with patch("src.web.routes.api.get_db", return_value=mock_db):
            # Call the GET candidate endpoint (501 Not Implemented)
            response = client.get("/api/candidates/456")

        assert response.status_code == 501
        mock_db.insert_audit_log.assert_called_once()
        call_kwargs = mock_db.insert_audit_log.call_args[1]
        # candidate_id should be extracted from URL
        assert call_kwargs["candidate_id"] == 456
        assert call_kwargs["http_method"] == "GET"

    def test_filing_progress_endpoint_extracts_filing_id(self, client, mock_db):
        """GET filing progress extracts filing_id from URL params."""
        mock_db.insert_audit_log = MagicMock(return_value=1)

        with patch("src.web.routes.api.get_db", return_value=mock_db):
            response = client.get("/api/filings/789/progress")

        assert response.status_code == 501
        mock_db.insert_audit_log.assert_called_once()
        call_kwargs = mock_db.insert_audit_log.call_args[1]
        assert call_kwargs["filing_id"] == 789
        assert call_kwargs["http_method"] == "GET"

    def test_empty_json_request_handled(self, client, mock_db):
        """Empty JSON request body handled (no decision fields in query_params)."""
        mock_db.insert_audit_log = MagicMock(return_value=1)

        with patch("src.web.routes.api.get_db", return_value=mock_db):
            response = client.post(
                "/api/decisions",
                json={},
            )

        assert response.status_code == 400
        mock_db.insert_audit_log.assert_called_once()
        call_kwargs = mock_db.insert_audit_log.call_args[1]
        # query_params should be None when no decision fields present
        assert call_kwargs["query_params"] is None
        assert call_kwargs["candidate_id"] is None


# =============================================================================
# TestAuditLogMetadata - Request metadata tests
# =============================================================================


class TestAuditLogMetadata:
    """Test that request metadata is captured correctly."""

    def test_ip_address_captured(self, client, mock_db):
        """Client IP address is captured in audit log."""
        mock_db.get_review_candidate.return_value = None
        mock_db.insert_audit_log = MagicMock(return_value=1)

        with patch("src.web.routes.api.get_db", return_value=mock_db):
            client.post(
                "/api/decisions",
                json={"candidate_id": 123, "decision": "accept", "assigned_metric_id": "test"},
            )

        call_kwargs = mock_db.insert_audit_log.call_args[1]
        # Should have an IP address (test client uses 127.0.0.1)
        assert call_kwargs["ip_address"] is not None

    def test_user_agent_captured(self, client, mock_db):
        """User agent is captured in audit log."""
        mock_db.get_review_candidate.return_value = None
        mock_db.insert_audit_log = MagicMock(return_value=1)

        with patch("src.web.routes.api.get_db", return_value=mock_db):
            client.post(
                "/api/decisions",
                json={"candidate_id": 123, "decision": "accept", "assigned_metric_id": "test"},
                headers={"User-Agent": "TestBrowser/1.0"},
            )

        call_kwargs = mock_db.insert_audit_log.call_args[1]
        assert call_kwargs["user_agent"] == "TestBrowser/1.0"
