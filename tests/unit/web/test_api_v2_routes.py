"""
Unit tests for V2 API routes.

Tests the JSON API endpoints for V2 review decision recording.
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
# TestCreateDecision - POST /api/v2/decisions
# =============================================================================


class TestCreateDecision:
    """Test POST /api/v2/decisions endpoint."""

    def test_create_accept_decision_success(self, client, mock_db):
        """Happy path: valid fact_id + accept decision returns 201."""
        fact_id = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
        decision_id = "11111111-2222-3333-4444-555555555555"

        mock_db.get_v2_fact_by_id.return_value = {
            "fact_id": fact_id,
            "doc_id": 42,
            "decision_id": None,
        }
        mock_db.insert_v2_review_decision.return_value = decision_id
        mock_db.get_v2_facts_for_filing.return_value = []

        with patch("src.web.routes.api_v2.get_db", return_value=mock_db):
            response = client.post(
                "/api/v2/decisions",
                json={
                    "fact_id": fact_id,
                    "decision": "accept",
                    "review_time_seconds": 30,
                },
            )

        assert response.status_code == 201
        data = json.loads(response.data)
        assert data["status"] == "success"
        assert data["decision_id"] == decision_id
        assert data["fact_id"] == fact_id

    def test_create_reject_decision_success(self, client, mock_db):
        """Happy path: valid fact_id + reject decision with category returns 201."""
        fact_id = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
        decision_id = "11111111-2222-3333-4444-555555555555"

        mock_db.get_v2_fact_by_id.return_value = {
            "fact_id": fact_id,
            "doc_id": 42,
            "decision_id": None,
        }
        mock_db.insert_v2_review_decision.return_value = decision_id
        mock_db.get_v2_facts_for_filing.return_value = []

        with patch("src.web.routes.api_v2.get_db", return_value=mock_db):
            response = client.post(
                "/api/v2/decisions",
                json={
                    "fact_id": fact_id,
                    "decision": "reject",
                    "rejection_category": "wrong_metric",
                    "rejection_reason": "This is not a customer metric.",
                },
            )

        assert response.status_code == 201
        data = json.loads(response.data)
        assert data["status"] == "success"

        mock_db.insert_v2_review_decision.assert_called_once_with(
            fact_id=fact_id,
            decision="reject",
            assigned_metric_id=None,
            corrected_value=None,
            rejection_reason="This is not a customer metric.",
            rejection_category="wrong_metric",
            reviewer_notes=None,
            review_time_seconds=None,
        )

    def test_create_correct_decision_success(self, client, mock_db):
        """Happy path: correct decision with assigned_metric_id and corrected_value returns 201."""
        fact_id = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
        decision_id = "11111111-2222-3333-4444-555555555555"

        mock_db.get_v2_fact_by_id.return_value = {
            "fact_id": fact_id,
            "doc_id": 42,
            "decision_id": None,
        }
        mock_db.insert_v2_review_decision.return_value = decision_id
        mock_db.get_v2_facts_for_filing.return_value = []

        with patch("src.web.routes.api_v2.get_db", return_value=mock_db):
            response = client.post(
                "/api/v2/decisions",
                json={
                    "fact_id": fact_id,
                    "decision": "correct",
                    "assigned_metric_id": "paying_customers",
                    "corrected_value": 1500000,
                },
            )

        assert response.status_code == 201
        data = json.loads(response.data)
        assert data["status"] == "success"

    def test_missing_fact_id_returns_400(self, client, mock_db):
        """Missing fact_id field returns 400 with validation errors."""
        with patch("src.web.routes.api_v2.get_db", return_value=mock_db):
            response = client.post(
                "/api/v2/decisions",
                json={"decision": "accept"},
            )

        assert response.status_code == 400
        data = json.loads(response.data)
        assert data["status"] == "error"
        assert "fact_id" in data["errors"]

    def test_missing_decision_returns_400(self, client, mock_db):
        """Missing decision field returns 400 with validation errors."""
        with patch("src.web.routes.api_v2.get_db", return_value=mock_db):
            response = client.post(
                "/api/v2/decisions",
                json={"fact_id": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"},
            )

        assert response.status_code == 400
        data = json.loads(response.data)
        assert data["status"] == "error"
        assert "decision" in data["errors"]

    def test_invalid_decision_type_returns_400(self, client, mock_db):
        """Invalid decision type returns 400 with validation errors."""
        with patch("src.web.routes.api_v2.get_db", return_value=mock_db):
            response = client.post(
                "/api/v2/decisions",
                json={
                    "fact_id": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
                    "decision": "approve",  # not a valid V2 decision type
                },
            )

        assert response.status_code == 400
        data = json.loads(response.data)
        assert data["status"] == "error"
        assert "decision" in data["errors"]

    def test_non_json_request_returns_400(self, client, mock_db):
        """Non-JSON content type returns 400."""
        with patch("src.web.routes.api_v2.get_db", return_value=mock_db):
            response = client.post(
                "/api/v2/decisions",
                data="fact_id=abc&decision=accept",
                content_type="application/x-www-form-urlencoded",
            )

        assert response.status_code == 400
        data = json.loads(response.data)
        assert data["status"] == "error"

    def test_fact_not_found_returns_404(self, client, mock_db):
        """Fact not found in DB returns 404."""
        mock_db.get_v2_fact_by_id.return_value = None

        with patch("src.web.routes.api_v2.get_db", return_value=mock_db):
            response = client.post(
                "/api/v2/decisions",
                json={
                    "fact_id": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
                    "decision": "accept",
                },
            )

        assert response.status_code == 404
        data = json.loads(response.data)
        assert data["status"] == "error"
        assert "not found" in data["message"].lower()

    def test_duplicate_decision_returns_409_via_existing_decision_id(self, client, mock_db):
        """Fact already has a decision_id in the record returns 409."""
        fact_id = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
        existing_decision_id = "99999999-8888-7777-6666-555555555555"

        mock_db.get_v2_fact_by_id.return_value = {
            "fact_id": fact_id,
            "doc_id": 42,
            "decision_id": existing_decision_id,
        }

        with patch("src.web.routes.api_v2.get_db", return_value=mock_db):
            response = client.post(
                "/api/v2/decisions",
                json={
                    "fact_id": fact_id,
                    "decision": "accept",
                },
            )

        assert response.status_code == 409
        data = json.loads(response.data)
        assert data["status"] == "error"
        assert data["existing_decision_id"] == str(existing_decision_id)

    def test_duplicate_decision_returns_409_via_unique_violation(self, client, mock_db):
        """UniqueViolation from DB layer returns 409."""
        fact_id = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"

        mock_db.get_v2_fact_by_id.return_value = {
            "fact_id": fact_id,
            "doc_id": 42,
            "decision_id": None,
        }
        mock_db.insert_v2_review_decision.side_effect = psycopg.errors.UniqueViolation()

        with patch("src.web.routes.api_v2.get_db", return_value=mock_db):
            response = client.post(
                "/api/v2/decisions",
                json={
                    "fact_id": fact_id,
                    "decision": "accept",
                },
            )

        assert response.status_code == 409
        data = json.loads(response.data)
        assert data["status"] == "error"

    def test_db_error_returns_500(self, client, mock_db):
        """Generic DB error returns 500."""
        fact_id = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"

        mock_db.get_v2_fact_by_id.return_value = {
            "fact_id": fact_id,
            "doc_id": 42,
            "decision_id": None,
        }
        mock_db.insert_v2_review_decision.side_effect = psycopg.DatabaseError("connection lost")

        with patch("src.web.routes.api_v2.get_db", return_value=mock_db):
            response = client.post(
                "/api/v2/decisions",
                json={
                    "fact_id": fact_id,
                    "decision": "accept",
                },
            )

        assert response.status_code == 500
        data = json.loads(response.data)
        assert data["status"] == "error"

    def test_next_fact_included_in_response(self, client, mock_db):
        """Response includes next_fact when another pending fact exists in the same filing."""
        fact_id = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
        next_fact_id = "ffffffff-eeee-dddd-cccc-bbbbbbbbbbbb"
        decision_id = "11111111-2222-3333-4444-555555555555"
        filing_id = 42

        mock_db.get_v2_fact_by_id.return_value = {
            "fact_id": fact_id,
            "doc_id": filing_id,
            "decision_id": None,
        }
        mock_db.insert_v2_review_decision.return_value = decision_id
        mock_db.get_v2_facts_for_filing.return_value = [
            {"fact_id": next_fact_id},
        ]

        with patch("src.web.routes.api_v2.get_db", return_value=mock_db):
            response = client.post(
                "/api/v2/decisions",
                json={"fact_id": fact_id, "decision": "accept"},
            )

        assert response.status_code == 201
        data = json.loads(response.data)
        assert data["next_fact"] is not None
        assert data["next_fact"]["fact_id"] == str(next_fact_id)
        assert str(filing_id) in data["next_fact"]["url"]

    def test_next_fact_none_when_no_pending(self, client, mock_db):
        """Response next_fact is None when no more pending facts exist."""
        fact_id = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
        decision_id = "11111111-2222-3333-4444-555555555555"

        mock_db.get_v2_fact_by_id.return_value = {
            "fact_id": fact_id,
            "doc_id": 42,
            "decision_id": None,
        }
        mock_db.insert_v2_review_decision.return_value = decision_id
        mock_db.get_v2_facts_for_filing.return_value = []

        with patch("src.web.routes.api_v2.get_db", return_value=mock_db):
            response = client.post(
                "/api/v2/decisions",
                json={"fact_id": fact_id, "decision": "accept"},
            )

        assert response.status_code == 201
        data = json.loads(response.data)
        assert data["next_fact"] is None


# =============================================================================
# TestUndoDecision - DELETE /api/v2/decisions/<decision_id>
# =============================================================================


class TestUndoDecision:
    """Test DELETE /api/v2/decisions/<decision_id> endpoint."""

    def test_undo_decision_success(self, client, mock_db):
        """Happy path: existing decision deleted returns 200."""
        decision_id = "11111111-2222-3333-4444-555555555555"
        fact_id = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
        filing_id = 42

        mock_db.delete_v2_review_decision.return_value = {
            "fact_id": fact_id,
            "filing_id": filing_id,
        }

        with patch("src.web.routes.api_v2.get_db", return_value=mock_db):
            response = client.delete(f"/api/v2/decisions/{decision_id}")

        assert response.status_code == 200
        data = json.loads(response.data)
        assert data["status"] == "success"
        assert data["message"] == "Decision reverted"
        assert data["fact_id"] == fact_id
        assert data["filing_id"] == filing_id

        mock_db.delete_v2_review_decision.assert_called_once_with(decision_id)

    def test_undo_decision_not_found_returns_404(self, client, mock_db):
        """Decision not found in DB returns 404."""
        decision_id = "11111111-2222-3333-4444-555555555555"
        mock_db.delete_v2_review_decision.return_value = None

        with patch("src.web.routes.api_v2.get_db", return_value=mock_db):
            response = client.delete(f"/api/v2/decisions/{decision_id}")

        assert response.status_code == 404
        data = json.loads(response.data)
        assert data["status"] == "error"
        assert "not found" in data["message"].lower()

    def test_undo_decision_db_error_returns_500(self, client, mock_db):
        """Generic DB error during delete returns 500."""
        decision_id = "11111111-2222-3333-4444-555555555555"
        mock_db.delete_v2_review_decision.side_effect = psycopg.DatabaseError("timeout")

        with patch("src.web.routes.api_v2.get_db", return_value=mock_db):
            response = client.delete(f"/api/v2/decisions/{decision_id}")

        assert response.status_code == 500
        data = json.loads(response.data)
        assert data["status"] == "error"
        assert data["message"] == "Database error"
