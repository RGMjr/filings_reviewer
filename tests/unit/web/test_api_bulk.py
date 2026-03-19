"""
Unit tests for bulk decisions API endpoint (HRI-8).

Tests validation, safety limits, and error handling for the
POST /api/bulk-decisions endpoint.
"""

import json
from unittest.mock import Mock, patch

import pytest
from flask import Flask

from src.web.routes.api import api_bp


@pytest.fixture
def app():
    """Create Flask app for testing."""
    app = Flask(__name__)
    app.config["TESTING"] = True
    app.config["API_KEY_REQUIRED"] = False  # Disable auth for unit tests
    app.register_blueprint(api_bp, url_prefix="/api")
    return app


@pytest.fixture
def client(app):
    """Create test client."""
    return app.test_client()


@pytest.fixture
def mock_db():
    """Mock database adapter."""
    with patch("src.web.routes.api.get_db") as mock_get_db:
        db = Mock()
        mock_get_db.return_value = db
        yield db


class TestBulkDecisionValidation:
    """Test request validation for bulk decisions."""

    def test_empty_candidate_ids_returns_400(self, client, mock_db):
        """Empty candidate_ids array should return 400."""
        response = client.post(
            "/api/bulk-decisions",
            json={
                "candidate_ids": [],
                "decision": "accept",
                "assigned_metric_id": "cm_arr",
            },
        )
        assert response.status_code == 400
        data = json.loads(response.data)
        assert data["status"] == "error"
        assert "candidate_ids" in data["errors"]

    def test_missing_candidate_ids_returns_400(self, client, mock_db):
        """Missing candidate_ids field should return 400."""
        response = client.post(
            "/api/bulk-decisions",
            json={
                "decision": "accept",
                "assigned_metric_id": "cm_arr",
            },
        )
        assert response.status_code == 400
        data = json.loads(response.data)
        assert data["status"] == "error"
        assert "candidate_ids" in data["errors"]

    def test_over_50_candidates_returns_403(self, client, mock_db):
        """More than 50 candidates should return 403."""
        candidate_ids = list(range(1, 52))  # 51 candidates
        response = client.post(
            "/api/bulk-decisions",
            json={
                "candidate_ids": candidate_ids,
                "decision": "accept",
                "assigned_metric_id": "cm_arr",
            },
        )
        assert response.status_code == 403
        data = json.loads(response.data)
        assert data["status"] == "error"
        assert "Maximum 50 candidates" in data["message"]

    def test_reclassify_not_allowed_returns_400(self, client, mock_db):
        """Bulk reclassify should return 400."""
        response = client.post(
            "/api/bulk-decisions",
            json={
                "candidate_ids": [1, 2, 3],
                "decision": "reclassify",
                "assigned_metric_id": "cm_arr",
            },
        )
        assert response.status_code == 400
        data = json.loads(response.data)
        assert data["status"] == "error"
        assert "decision" in data["errors"]

    def test_accept_without_metric_id_returns_400(self, client, mock_db):
        """Bulk accept without assigned_metric_id should return 400."""
        response = client.post(
            "/api/bulk-decisions",
            json={
                "candidate_ids": [1, 2, 3],
                "decision": "accept",
            },
        )
        assert response.status_code == 400
        data = json.loads(response.data)
        assert data["status"] == "error"
        assert "assigned_metric_id" in data["errors"]

    def test_reject_without_category_returns_400(self, client, mock_db):
        """Bulk reject without rejection_category should return 400."""
        response = client.post(
            "/api/bulk-decisions",
            json={
                "candidate_ids": [1, 2, 3],
                "decision": "reject",
            },
        )
        assert response.status_code == 400
        data = json.loads(response.data)
        assert data["status"] == "error"
        assert "rejection_category" in data["errors"]

    def test_invalid_rejection_category_returns_400(self, client, mock_db):
        """Invalid rejection_category should return 400."""
        response = client.post(
            "/api/bulk-decisions",
            json={
                "candidate_ids": [1, 2, 3],
                "decision": "reject",
                "rejection_category": "not_a_valid_category",
            },
        )
        assert response.status_code == 400
        data = json.loads(response.data)
        assert data["status"] == "error"
        assert "rejection_category" in data["errors"]
        assert "Must be one of:" in data["errors"]["rejection_category"]


class TestBulkAccept:
    """Test bulk accept functionality."""

    def test_bulk_accept_success(self, client, mock_db):
        """Successful bulk accept should return 200 with decision_ids."""
        # Mock candidate retrieval
        mock_db.get_review_candidate.side_effect = [
            {"candidate_id": 1, "filing_id": 100},
            {"candidate_id": 2, "filing_id": 100},
            {"candidate_id": 3, "filing_id": 100},
        ]

        # Mock bulk insert
        mock_db.insert_bulk_review_decisions.return_value = ([101, 102, 103], [])

        response = client.post(
            "/api/bulk-decisions",
            json={
                "candidate_ids": [1, 2, 3],
                "decision": "accept",
                "assigned_metric_id": "cm_arr",
            },
        )

        assert response.status_code == 200
        data = json.loads(response.data)
        assert data["status"] == "success"
        assert data["processed_count"] == 3
        assert data["decision_ids"] == [101, 102, 103]
        assert data["failed_candidates"] == []

        # Verify database was called correctly
        mock_db.insert_bulk_review_decisions.assert_called_once_with(
            candidate_ids=[1, 2, 3],
            decision="accept",
            assigned_metric_id="cm_arr",
            rejection_category=None,
            rejection_reason=None,
        )

    def test_bulk_accept_deduplicates_ids(self, client, mock_db):
        """Duplicate candidate IDs should be deduplicated."""
        mock_db.get_review_candidate.side_effect = [
            {"candidate_id": 1, "filing_id": 100},
            {"candidate_id": 2, "filing_id": 100},
        ]
        mock_db.insert_bulk_review_decisions.return_value = ([101, 102], [])

        response = client.post(
            "/api/bulk-decisions",
            json={
                "candidate_ids": [1, 2, 1, 2],  # Duplicates
                "decision": "accept",
                "assigned_metric_id": "cm_arr",
            },
        )

        assert response.status_code == 200
        # Should only process unique IDs
        call_args = mock_db.insert_bulk_review_decisions.call_args[1]
        assert len(call_args["candidate_ids"]) == 2

    def test_exactly_50_candidates_succeeds(self, client, mock_db):
        """Exactly 50 candidates should succeed (edge case at limit)."""
        candidate_ids = list(range(1, 51))  # Exactly 50 candidates

        # Mock all 50 candidates from same filing
        mock_db.get_review_candidate.side_effect = [
            {"candidate_id": i, "filing_id": 100} for i in candidate_ids
        ]

        # Mock successful bulk insert returning 50 decision IDs
        decision_ids = list(range(1001, 1051))
        mock_db.insert_bulk_review_decisions.return_value = (decision_ids, [])

        response = client.post(
            "/api/bulk-decisions",
            json={
                "candidate_ids": candidate_ids,
                "decision": "accept",
                "assigned_metric_id": "cm_arr",
            },
        )

        assert response.status_code == 200
        data = json.loads(response.data)
        assert data["status"] == "success"
        assert data["processed_count"] == 50
        assert len(data["decision_ids"]) == 50


class TestBulkReject:
    """Test bulk reject functionality."""

    def test_bulk_reject_success(self, client, mock_db):
        """Successful bulk reject should return 200."""
        # After deduplication, candidate_ids becomes a list (converted from set)
        # Need to mock for both possible orderings: [1, 2] or [2, 1]
        mock_db.get_review_candidate.side_effect = lambda cid: {
            1: {"candidate_id": 1, "filing_id": 100},
            2: {"candidate_id": 2, "filing_id": 100},
        }.get(cid)

        mock_db.insert_bulk_review_decisions.return_value = ([201, 202], [])

        response = client.post(
            "/api/bulk-decisions",
            json={
                "candidate_ids": [1, 2],
                "decision": "reject",
                "rejection_category": "wrong_metric",
                "rejection_reason": "Test reason",
            },
        )

        assert response.status_code == 200
        data = json.loads(response.data)
        assert data["status"] == "success"
        assert data["processed_count"] == 2

        # Verify call was made with correct parameters
        # (candidate_ids order may vary after set deduplication)
        call_kwargs = mock_db.insert_bulk_review_decisions.call_args[1]
        assert sorted(call_kwargs["candidate_ids"]) == [1, 2]
        assert call_kwargs["decision"] == "reject"
        assert call_kwargs["assigned_metric_id"] is None
        assert call_kwargs["rejection_category"] == "wrong_metric"
        assert call_kwargs["rejection_reason"] == "Test reason"


class TestBulkEdgeCases:
    """Test edge cases and error handling."""

    def test_mixed_filing_ids_returns_400(self, client, mock_db):
        """Candidates from different filings should return 400."""
        mock_db.get_review_candidate.side_effect = [
            {"candidate_id": 1, "filing_id": 100},
            {"candidate_id": 2, "filing_id": 200},  # Different filing
        ]

        response = client.post(
            "/api/bulk-decisions",
            json={
                "candidate_ids": [1, 2],
                "decision": "accept",
                "assigned_metric_id": "cm_arr",
            },
        )

        assert response.status_code == 400
        data = json.loads(response.data)
        assert "same filing" in data["message"]

    def test_no_valid_candidates_returns_400(self, client, mock_db):
        """No valid candidates should return 400."""
        mock_db.get_review_candidate.return_value = None

        response = client.post(
            "/api/bulk-decisions",
            json={
                "candidate_ids": [999],
                "decision": "accept",
                "assigned_metric_id": "cm_arr",
            },
        )

        assert response.status_code == 400
        data = json.loads(response.data)
        assert "No valid candidates" in data["message"]

    def test_partial_success_returns_successes_and_failures(self, client, mock_db):
        """Partial success should return both successes and failures."""
        mock_db.get_review_candidate.side_effect = [
            {"candidate_id": 1, "filing_id": 100},
            {"candidate_id": 2, "filing_id": 100},
        ]
        mock_db.insert_bulk_review_decisions.return_value = (
            [101],  # Only one succeeded
            [{"candidate_id": 2, "error": "Already reviewed"}],  # One failed
        )

        response = client.post(
            "/api/bulk-decisions",
            json={
                "candidate_ids": [1, 2],
                "decision": "accept",
                "assigned_metric_id": "cm_arr",
            },
        )

        assert response.status_code == 200
        data = json.loads(response.data)
        assert data["processed_count"] == 1
        assert len(data["failed_candidates"]) == 1
        assert data["failed_candidates"][0]["candidate_id"] == 2

    def test_invalid_metric_id_returns_400(self, client, mock_db):
        """Invalid metric_id should return 400 with foreign key error."""
        import psycopg.errors

        # Mock candidate retrieval to pass filing check
        mock_db.get_review_candidate.side_effect = [
            {"candidate_id": 1, "filing_id": 100}
        ]

        # Mock bulk insert to raise foreign key violation
        mock_db.insert_bulk_review_decisions.side_effect = (
            psycopg.errors.ForeignKeyViolation("metric_id constraint")
        )

        response = client.post(
            "/api/bulk-decisions",
            json={
                "candidate_ids": [1],
                "decision": "accept",
                "assigned_metric_id": "cm_nonexistent",
            },
        )

        assert response.status_code == 400
        data = json.loads(response.data)
        assert "Invalid metric_id" in data["message"]
