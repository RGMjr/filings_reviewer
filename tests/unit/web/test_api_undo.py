"""
Unit tests for undo decision API endpoint (HRI-7).

Tests DELETE /api/decisions/<decision_id> endpoint using mocked database.
"""

from unittest.mock import MagicMock, patch

import pytest

from src.web.app import create_app


@pytest.fixture
def app():
    """Create Flask app for testing."""
    app = create_app("testing")
    app.config["TESTING"] = True
    app.config["DATABASE_URL"] = "postgresql://test"
    return app


@pytest.fixture
def client(app):
    """Create test client."""
    return app.test_client()


@pytest.fixture
def mock_db():
    """Create mock database adapter."""
    with patch("src.web.routes.api.get_db") as mock_get_db:
        mock = MagicMock()
        mock_get_db.return_value = mock
        yield mock


# =============================================================================
# Test undo_decision() endpoint - DELETE /api/decisions/<decision_id>
# =============================================================================


def test_undo_decision_success(client, mock_db):
    """Test successful undo returns 200 and candidate URL."""
    # Mock get_decision_by_id to return decision
    mock_db.get_decision_by_id.return_value = {
        "decision_id": 123,
        "candidate_id": 456,
        "filing_id": 789,
        "decision": "accept",
    }

    # Mock delete_review_decision to return True
    mock_db.delete_review_decision.return_value = True

    response = client.delete("/api/decisions/123")

    assert response.status_code == 200
    data = response.get_json()
    assert data["status"] == "success"
    assert data["message"] == "Decision reverted"
    assert data["candidate_id"] == 456
    assert data["candidate_url"] == "/review/789/candidate/456"

    # Verify database methods called
    mock_db.get_decision_by_id.assert_called_once_with(123)
    mock_db.delete_review_decision.assert_called_once_with(123)


def test_undo_decision_not_found(client, mock_db):
    """Test undo non-existent decision returns 404."""
    # Mock get_decision_by_id to return None
    mock_db.get_decision_by_id.return_value = None

    response = client.delete("/api/decisions/999")

    assert response.status_code == 404
    data = response.get_json()
    assert data["status"] == "error"
    assert data["message"] == "Decision not found"

    # Verify only get was called, not delete
    mock_db.get_decision_by_id.assert_called_once_with(999)
    mock_db.delete_review_decision.assert_not_called()


def test_undo_decision_delete_fails(client, mock_db):
    """Test undo when delete fails returns 500."""
    # Mock get_decision_by_id to return decision
    mock_db.get_decision_by_id.return_value = {
        "decision_id": 123,
        "candidate_id": 456,
        "filing_id": 789,
        "decision": "reject",
    }

    # Mock delete_review_decision to return False (failure)
    mock_db.delete_review_decision.return_value = False

    response = client.delete("/api/decisions/123")

    assert response.status_code == 500
    data = response.get_json()
    assert data["status"] == "error"
    assert data["message"] == "Failed to undo decision"

    # Verify both methods called
    mock_db.get_decision_by_id.assert_called_once_with(123)
    mock_db.delete_review_decision.assert_called_once_with(123)


def test_undo_decision_database_error(client, mock_db):
    """Test undo handles database error gracefully."""
    # Mock get_decision_by_id to raise database error
    import psycopg

    mock_db.get_decision_by_id.side_effect = psycopg.DatabaseError("Connection lost")

    response = client.delete("/api/decisions/123")

    assert response.status_code == 500
    data = response.get_json()
    assert data["status"] == "error"
    assert data["message"] == "Database error occurred"
    assert data["error_type"] == "database_error"


def test_undo_decision_unexpected_error(client, mock_db):
    """Test undo handles unexpected errors gracefully."""
    # Mock get_decision_by_id to raise unexpected error
    mock_db.get_decision_by_id.side_effect = ValueError("Unexpected")

    response = client.delete("/api/decisions/123")

    assert response.status_code == 500
    data = response.get_json()
    assert data["status"] == "error"
    assert data["message"] == "Internal server error"
    assert data["error_type"] == "internal_error"


def test_undo_decision_different_filing(client, mock_db):
    """Test undo works for decision from any filing."""
    # Mock get_decision_by_id to return decision from different filing
    mock_db.get_decision_by_id.return_value = {
        "decision_id": 111,
        "candidate_id": 222,
        "filing_id": 333,
        "decision": "reclassify",
    }

    mock_db.delete_review_decision.return_value = True

    response = client.delete("/api/decisions/111")

    assert response.status_code == 200
    data = response.get_json()
    assert data["status"] == "success"
    assert data["candidate_url"] == "/review/333/candidate/222"
