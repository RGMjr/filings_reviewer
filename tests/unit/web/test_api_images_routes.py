"""
Unit tests for image review API routes (IMG-1-5).

Tests the JSON API endpoints for image review decision recording.
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
# TestCreateImageDecision - POST /api/image-decisions
# =============================================================================


class TestCreateImageDecision:
    """Test POST /api/image-decisions endpoint."""

    def test_create_relevant_decision_success(self, client, mock_db):
        """Test successful relevant decision with chart_type."""
        mock_db.get_image_review_candidate.return_value = {
            "image_candidate_id": 123,
            "filing_id": 5,
            "review_status": "pending",
            "decision": None,
        }
        mock_db.insert_image_review_decision.return_value = 456
        mock_db.get_next_pending_image_candidate.return_value = {
            "image_candidate_id": 124,
        }

        with patch("src.web.routes.api_images.get_db", return_value=mock_db):
            response = client.post(
                "/api/image-decisions",
                json={
                    "image_candidate_id": 123,
                    "decision": "relevant",
                    "chart_type": "bar_chart",
                    "review_time_seconds": 15,
                },
            )

        assert response.status_code == 201
        data = json.loads(response.data)
        assert data["status"] == "success"
        assert data["decision_id"] == 456
        assert data["next_candidate"]["image_candidate_id"] == 124
        assert "/review/images/5?image_candidate_id=124" in data["next_candidate"]["url"]

        mock_db.insert_image_review_decision.assert_called_once_with(
            image_candidate_id=123,
            decision="relevant",
            chart_type="bar_chart",
            rejection_reason=None,
            reviewer_notes=None,
            review_time_seconds=15,
        )

    def test_create_not_relevant_decision_success(self, client, mock_db):
        """Test successful not_relevant decision with rejection_reason."""
        mock_db.get_image_review_candidate.return_value = {
            "image_candidate_id": 123,
            "filing_id": 5,
            "review_status": "pending",
            "decision": None,
        }
        mock_db.insert_image_review_decision.return_value = 456
        mock_db.get_next_pending_image_candidate.return_value = None  # No more candidates

        with patch("src.web.routes.api_images.get_db", return_value=mock_db):
            response = client.post(
                "/api/image-decisions",
                json={
                    "image_candidate_id": 123,
                    "decision": "not_relevant",
                    "rejection_reason": "decorative",
                    "reviewer_notes": "Company logo",
                },
            )

        assert response.status_code == 201
        data = json.loads(response.data)
        assert data["status"] == "success"
        assert data["decision_id"] == 456
        assert data["next_candidate"] is None
        assert data["message"] == "All candidates reviewed for this filing"

        mock_db.insert_image_review_decision.assert_called_once_with(
            image_candidate_id=123,
            decision="not_relevant",
            chart_type=None,
            rejection_reason="decorative",
            reviewer_notes="Company logo",
            review_time_seconds=None,
        )

    def test_missing_image_candidate_id(self, client, mock_db):
        """Test validation error when image_candidate_id is missing."""
        with patch("src.web.routes.api_images.get_db", return_value=mock_db):
            response = client.post(
                "/api/image-decisions",
                json={
                    "decision": "relevant",
                    "chart_type": "bar_chart",
                },
            )

        assert response.status_code == 400
        data = json.loads(response.data)
        assert data["status"] == "error"
        assert "image_candidate_id is required" in data["message"]

    def test_invalid_image_candidate_id(self, client, mock_db):
        """Test validation error for non-positive image_candidate_id."""
        with patch("src.web.routes.api_images.get_db", return_value=mock_db):
            response = client.post(
                "/api/image-decisions",
                json={
                    "image_candidate_id": -1,
                    "decision": "relevant",
                    "chart_type": "bar_chart",
                },
            )

        assert response.status_code == 400
        data = json.loads(response.data)
        assert data["status"] == "error"
        assert "positive integer" in data["message"]

    def test_missing_decision(self, client, mock_db):
        """Test validation error when decision is missing."""
        with patch("src.web.routes.api_images.get_db", return_value=mock_db):
            response = client.post(
                "/api/image-decisions",
                json={
                    "image_candidate_id": 123,
                    "chart_type": "bar_chart",
                },
            )

        assert response.status_code == 400
        data = json.loads(response.data)
        assert data["status"] == "error"
        assert "decision is required" in data["message"]

    def test_invalid_decision_value(self, client, mock_db):
        """Test validation error for invalid decision value."""
        with patch("src.web.routes.api_images.get_db", return_value=mock_db):
            response = client.post(
                "/api/image-decisions",
                json={
                    "image_candidate_id": 123,
                    "decision": "maybe",
                },
            )

        assert response.status_code == 400
        data = json.loads(response.data)
        assert data["status"] == "error"
        assert "decision must be one of" in data["message"]

    def test_chart_type_required_for_relevant(self, client, mock_db):
        """Test that chart_type is required when decision is 'relevant'."""
        with patch("src.web.routes.api_images.get_db", return_value=mock_db):
            response = client.post(
                "/api/image-decisions",
                json={
                    "image_candidate_id": 123,
                    "decision": "relevant",
                },
            )

        assert response.status_code == 400
        data = json.loads(response.data)
        assert data["status"] == "error"
        assert "chart_type is required when decision is 'relevant'" in data["message"]

    def test_rejection_reason_required_for_not_relevant(self, client, mock_db):
        """Test that rejection_reason is required when decision is 'not_relevant'."""
        with patch("src.web.routes.api_images.get_db", return_value=mock_db):
            response = client.post(
                "/api/image-decisions",
                json={
                    "image_candidate_id": 123,
                    "decision": "not_relevant",
                },
            )

        assert response.status_code == 400
        data = json.loads(response.data)
        assert data["status"] == "error"
        assert "rejection_reason is required when decision is 'not_relevant'" in data["message"]

    def test_invalid_chart_type(self, client, mock_db):
        """Test validation error for invalid chart_type."""
        with patch("src.web.routes.api_images.get_db", return_value=mock_db):
            response = client.post(
                "/api/image-decisions",
                json={
                    "image_candidate_id": 123,
                    "decision": "relevant",
                    "chart_type": "invalid_chart",
                },
            )

        assert response.status_code == 400
        data = json.loads(response.data)
        assert data["status"] == "error"
        assert "chart_type must be one of" in data["message"]

    def test_invalid_rejection_reason(self, client, mock_db):
        """Test validation error for invalid rejection_reason."""
        with patch("src.web.routes.api_images.get_db", return_value=mock_db):
            response = client.post(
                "/api/image-decisions",
                json={
                    "image_candidate_id": 123,
                    "decision": "not_relevant",
                    "rejection_reason": "invalid_reason",
                },
            )

        assert response.status_code == 400
        data = json.loads(response.data)
        assert data["status"] == "error"
        assert "rejection_reason must be one of" in data["message"]

    def test_candidate_not_found(self, client, mock_db):
        """Test 404 when image candidate doesn't exist."""
        mock_db.get_image_review_candidate.return_value = None

        with patch("src.web.routes.api_images.get_db", return_value=mock_db):
            response = client.post(
                "/api/image-decisions",
                json={
                    "image_candidate_id": 999,
                    "decision": "relevant",
                    "chart_type": "bar_chart",
                },
            )

        assert response.status_code == 404
        data = json.loads(response.data)
        assert data["status"] == "error"
        assert "Image candidate not found" in data["message"]

    def test_candidate_already_has_decision(self, client, mock_db):
        """Test 409 when candidate already has a decision."""
        mock_db.get_image_review_candidate.return_value = {
            "image_candidate_id": 123,
            "filing_id": 5,
            "review_status": "reviewed",
            "decision": "relevant",  # Already has decision
        }

        with patch("src.web.routes.api_images.get_db", return_value=mock_db):
            response = client.post(
                "/api/image-decisions",
                json={
                    "image_candidate_id": 123,
                    "decision": "relevant",
                    "chart_type": "bar_chart",
                },
            )

        assert response.status_code == 409
        data = json.loads(response.data)
        assert data["status"] == "error"
        assert "already has a decision" in data["message"]

    def test_request_must_be_json(self, client, mock_db):
        """Test 400 when request is not JSON."""
        with patch("src.web.routes.api_images.get_db", return_value=mock_db):
            response = client.post(
                "/api/image-decisions",
                data="not json",
                content_type="text/plain",
            )

        assert response.status_code == 400
        data = json.loads(response.data)
        assert data["status"] == "error"
        assert "Request must be JSON" in data["message"]

    def test_reviewer_notes_too_long(self, client, mock_db):
        """Test validation error for reviewer_notes exceeding max length."""
        with patch("src.web.routes.api_images.get_db", return_value=mock_db):
            response = client.post(
                "/api/image-decisions",
                json={
                    "image_candidate_id": 123,
                    "decision": "relevant",
                    "chart_type": "bar_chart",
                    "reviewer_notes": "x" * 1001,
                },
            )

        assert response.status_code == 400
        data = json.loads(response.data)
        assert data["status"] == "error"
        assert "1000 characters or less" in data["message"]

    def test_invalid_review_time_seconds(self, client, mock_db):
        """Test validation error for invalid review_time_seconds."""
        with patch("src.web.routes.api_images.get_db", return_value=mock_db):
            response = client.post(
                "/api/image-decisions",
                json={
                    "image_candidate_id": 123,
                    "decision": "relevant",
                    "chart_type": "bar_chart",
                    "review_time_seconds": -5,
                },
            )

        assert response.status_code == 400
        data = json.loads(response.data)
        assert data["status"] == "error"
        assert "non-negative integer" in data["message"]

    def test_database_error_returns_500(self, client, mock_db):
        """Test that database errors return 500."""
        mock_db.get_image_review_candidate.return_value = {
            "image_candidate_id": 123,
            "filing_id": 5,
            "decision": None,
        }
        mock_db.insert_image_review_decision.side_effect = psycopg.DatabaseError("DB error")

        with patch("src.web.routes.api_images.get_db", return_value=mock_db):
            response = client.post(
                "/api/image-decisions",
                json={
                    "image_candidate_id": 123,
                    "decision": "relevant",
                    "chart_type": "bar_chart",
                },
            )

        assert response.status_code == 500
        data = json.loads(response.data)
        assert data["status"] == "error"
        assert "Database error" in data["message"]

    def test_validation_error_from_db_returns_400(self, client, mock_db):
        """Test that ValidationError from db layer returns 400."""
        from src.infra.validation import ValidationError

        mock_db.get_image_review_candidate.return_value = {
            "image_candidate_id": 123,
            "filing_id": 5,
            "decision": None,
        }
        mock_db.insert_image_review_decision.side_effect = ValidationError(
            "Decision 'relevant' requires chart_type"
        )

        with patch("src.web.routes.api_images.get_db", return_value=mock_db):
            response = client.post(
                "/api/image-decisions",
                json={
                    "image_candidate_id": 123,
                    "decision": "relevant",
                    "chart_type": "bar_chart",
                },
            )

        assert response.status_code == 400
        data = json.loads(response.data)
        assert data["status"] == "error"
        assert "requires chart_type" in data["message"]


# =============================================================================
# TestSkipImageCandidate - POST /api/image-candidates/<id>/skip
# =============================================================================


class TestSkipImageCandidate:
    """Test POST /api/image-candidates/<id>/skip endpoint."""

    def test_skip_success(self, client, mock_db):
        """Test successful skip operation."""
        mock_db.get_image_review_candidate.return_value = {
            "image_candidate_id": 123,
            "filing_id": 5,
            "review_status": "pending",
        }
        mock_db.update_image_candidate_status.return_value = True
        mock_db.get_next_pending_image_candidate.return_value = {
            "image_candidate_id": 124,
        }

        with patch("src.web.routes.api_images.get_db", return_value=mock_db):
            response = client.post("/api/image-candidates/123/skip")

        assert response.status_code == 200
        data = json.loads(response.data)
        assert data["status"] == "success"
        assert data["next_candidate"]["image_candidate_id"] == 124

        mock_db.update_image_candidate_status.assert_called_once_with(123, "skipped")

    def test_skip_no_next_candidate(self, client, mock_db):
        """Test skip when no more candidates."""
        mock_db.get_image_review_candidate.return_value = {
            "image_candidate_id": 123,
            "filing_id": 5,
            "review_status": "pending",
        }
        mock_db.update_image_candidate_status.return_value = True
        mock_db.get_next_pending_image_candidate.return_value = None

        with patch("src.web.routes.api_images.get_db", return_value=mock_db):
            response = client.post("/api/image-candidates/123/skip")

        assert response.status_code == 200
        data = json.loads(response.data)
        assert data["status"] == "success"
        assert data["next_candidate"] is None

    def test_skip_candidate_not_found(self, client, mock_db):
        """Test 404 when candidate doesn't exist."""
        mock_db.get_image_review_candidate.return_value = None

        with patch("src.web.routes.api_images.get_db", return_value=mock_db):
            response = client.post("/api/image-candidates/999/skip")

        assert response.status_code == 404
        data = json.loads(response.data)
        assert data["status"] == "error"
        assert "Image candidate not found" in data["message"]

    def test_skip_update_fails(self, client, mock_db):
        """Test 500 when status update fails."""
        mock_db.get_image_review_candidate.return_value = {
            "image_candidate_id": 123,
            "filing_id": 5,
        }
        mock_db.update_image_candidate_status.return_value = False

        with patch("src.web.routes.api_images.get_db", return_value=mock_db):
            response = client.post("/api/image-candidates/123/skip")

        assert response.status_code == 500
        data = json.loads(response.data)
        assert data["status"] == "error"
        assert "Failed to skip candidate" in data["message"]


# =============================================================================
# TestUnskipImageCandidate - POST /api/image-candidates/<id>/unskip
# =============================================================================


class TestUnskipImageCandidate:
    """Test POST /api/image-candidates/<id>/unskip endpoint."""

    def test_unskip_success(self, client, mock_db):
        """Test successful unskip resets status to pending and returns URL."""
        mock_db.get_image_review_candidate.return_value = {
            "image_candidate_id": 123,
            "filing_id": 5,
            "review_status": "skipped",
        }
        mock_db.update_image_candidate_status.return_value = True

        with patch("src.web.routes.api_images.get_db", return_value=mock_db):
            response = client.post("/api/image-candidates/123/unskip")

        assert response.status_code == 200
        data = json.loads(response.data)
        assert data["status"] == "success"
        assert data["candidate_id"] == 123
        assert "/review/images/5" in data["url"]
        mock_db.update_image_candidate_status.assert_called_once_with(123, "pending")

    def test_unskip_candidate_not_found(self, client, mock_db):
        """Test 404 when candidate doesn't exist."""
        mock_db.get_image_review_candidate.return_value = None

        with patch("src.web.routes.api_images.get_db", return_value=mock_db):
            response = client.post("/api/image-candidates/999/unskip")

        assert response.status_code == 404
        data = json.loads(response.data)
        assert data["status"] == "error"

    def test_unskip_candidate_not_skipped(self, client, mock_db):
        """Test 400 when candidate is not in skipped state."""
        mock_db.get_image_review_candidate.return_value = {
            "image_candidate_id": 123,
            "filing_id": 5,
            "review_status": "pending",
        }

        with patch("src.web.routes.api_images.get_db", return_value=mock_db):
            response = client.post("/api/image-candidates/123/unskip")

        assert response.status_code == 400
        data = json.loads(response.data)
        assert data["status"] == "error"
        assert "not skipped" in data["message"]

    def test_unskip_update_fails(self, client, mock_db):
        """Test 500 when status update fails."""
        mock_db.get_image_review_candidate.return_value = {
            "image_candidate_id": 123,
            "filing_id": 5,
            "review_status": "skipped",
        }
        mock_db.update_image_candidate_status.return_value = False

        with patch("src.web.routes.api_images.get_db", return_value=mock_db):
            response = client.post("/api/image-candidates/123/unskip")

        assert response.status_code == 500
        data = json.loads(response.data)
        assert data["status"] == "error"


# =============================================================================
# TestDeleteImageDecision - DELETE /api/image-decisions/<id>
# =============================================================================


class TestDeleteImageDecision:
    """Test DELETE /api/image-decisions/<id> endpoint."""

    def test_delete_success(self, client, mock_db):
        """Test successful decision deletion (undo)."""
        mock_db.get_image_decision_by_id.return_value = {
            "image_decision_id": 456,
            "image_candidate_id": 123,
            "decision": "relevant",
        }
        mock_db.delete_image_review_decision.return_value = True

        with patch("src.web.routes.api_images.get_db", return_value=mock_db):
            response = client.delete("/api/image-decisions/456")

        assert response.status_code == 200
        data = json.loads(response.data)
        assert data["status"] == "success"
        assert data["candidate_id"] == 123

        mock_db.delete_image_review_decision.assert_called_once_with(456)

    def test_delete_decision_not_found(self, client, mock_db):
        """Test 404 when decision doesn't exist."""
        mock_db.get_image_decision_by_id.return_value = None

        with patch("src.web.routes.api_images.get_db", return_value=mock_db):
            response = client.delete("/api/image-decisions/999")

        assert response.status_code == 404
        data = json.loads(response.data)
        assert data["status"] == "error"
        assert "Decision not found" in data["message"]

    def test_delete_fails(self, client, mock_db):
        """Test 500 when deletion fails."""
        mock_db.get_image_decision_by_id.return_value = {
            "image_decision_id": 456,
            "image_candidate_id": 123,
        }
        mock_db.delete_image_review_decision.return_value = False

        with patch("src.web.routes.api_images.get_db", return_value=mock_db):
            response = client.delete("/api/image-decisions/456")

        assert response.status_code == 500
        data = json.loads(response.data)
        assert data["status"] == "error"
        assert "Failed to delete decision" in data["message"]

    def test_delete_database_error(self, client, mock_db):
        """Test 500 on database error during deletion."""
        mock_db.get_image_decision_by_id.return_value = {
            "image_decision_id": 456,
            "image_candidate_id": 123,
        }
        mock_db.delete_image_review_decision.side_effect = psycopg.DatabaseError("DB error")

        with patch("src.web.routes.api_images.get_db", return_value=mock_db):
            response = client.delete("/api/image-decisions/456")

        assert response.status_code == 500
        data = json.loads(response.data)
        assert data["status"] == "error"
        assert "Database error" in data["message"]


# =============================================================================
# TestValidChartTypes - Verify all valid chart types are accepted
# =============================================================================


class TestValidChartTypes:
    """Test that all valid chart types are accepted."""

    @pytest.mark.parametrize(
        "chart_type",
        [
            "cohort_table",
            "cohort_parfait",
            "line_chart",
            "bar_chart",
            "stacked_bar",
            "other_chart",
            "mixed",
        ],
    )
    def test_valid_chart_types(self, client, mock_db, chart_type):
        """Test all valid chart types are accepted for relevant decisions."""
        mock_db.get_image_review_candidate.return_value = {
            "image_candidate_id": 123,
            "filing_id": 5,
            "decision": None,
        }
        mock_db.insert_image_review_decision.return_value = 456
        mock_db.get_next_pending_image_candidate.return_value = None

        with patch("src.web.routes.api_images.get_db", return_value=mock_db):
            response = client.post(
                "/api/image-decisions",
                json={
                    "image_candidate_id": 123,
                    "decision": "relevant",
                    "chart_type": chart_type,
                },
            )

        assert response.status_code == 201
        data = json.loads(response.data)
        assert data["status"] == "success"


# =============================================================================
# TestValidRejectionReasons - Verify all valid rejection reasons are accepted
# =============================================================================


class TestValidRejectionReasons:
    """Test that all valid rejection reasons are accepted."""

    @pytest.mark.parametrize(
        "rejection_reason",
        [
            "decorative",
            "not_a_chart",
            "wrong_subject",
            "duplicate",
            "unreadable",
            "other",
        ],
    )
    def test_valid_rejection_reasons(self, client, mock_db, rejection_reason):
        """Test all valid rejection reasons are accepted for not_relevant decisions."""
        mock_db.get_image_review_candidate.return_value = {
            "image_candidate_id": 123,
            "filing_id": 5,
            "decision": None,
        }
        mock_db.insert_image_review_decision.return_value = 456
        mock_db.get_next_pending_image_candidate.return_value = None

        with patch("src.web.routes.api_images.get_db", return_value=mock_db):
            response = client.post(
                "/api/image-decisions",
                json={
                    "image_candidate_id": 123,
                    "decision": "not_relevant",
                    "rejection_reason": rejection_reason,
                },
            )

        assert response.status_code == 201
        data = json.loads(response.data)
        assert data["status"] == "success"
