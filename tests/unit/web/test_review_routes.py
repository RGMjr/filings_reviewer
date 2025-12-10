"""
Unit tests for Flask review routes (D1).

Tests all routes in src/web/routes/review.py using mocked database.
"""

from datetime import datetime
from decimal import Decimal
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
    with patch("src.web.routes.review.get_db") as mock_get_db:
        mock = MagicMock()
        mock_get_db.return_value = mock
        yield mock


@pytest.fixture(autouse=True)
def mock_render_template():
    """Mock render_template to avoid needing actual templates."""
    with patch("src.web.routes.review.render_template") as mock:
        # Return an empty string to simulate template rendering
        mock.return_value = "mocked template"
        yield mock


# =============================================================================
# Test index() route
# =============================================================================

def test_index_redirects_to_filing_list(client):
    """Test that index redirects to filing list."""
    response = client.get("/")
    assert response.status_code == 302
    assert "/filings" in response.location


# =============================================================================
# Test filing_list() route
# =============================================================================

def test_filing_list_calls_database_methods(client, mock_db, mock_render_template):
    """Test filing list calls correct database methods."""
    mock_db.get_filings_with_candidates_count.return_value = 0
    mock_db.get_filings_with_candidates.return_value = []
    mock_db.get_review_progress.return_value = {
        "total_candidates": 0,
        "pending_count": 0,
        "reviewed_count": 0,
        "skipped_count": 0,
        "review_pct": 0,
        "total_filings": 0,
        "filings_with_pending": 0,
    }

    response = client.get("/filings")

    assert response.status_code == 200
    mock_db.get_filings_with_candidates_count.assert_called_once_with(status=None)
    mock_db.get_filings_with_candidates.assert_called_once_with(
        status=None, limit=50, offset=0
    )
    mock_db.get_review_progress.assert_called_once()
    mock_render_template.assert_called_once()


def test_filing_list_passes_status_filter(client, mock_db):
    """Test filing list passes status filter to database."""
    mock_db.get_filings_with_candidates_count.return_value = 0
    mock_db.get_filings_with_candidates.return_value = []
    mock_db.get_review_progress.return_value = {
        "total_candidates": 0,
        "pending_count": 0,
        "reviewed_count": 0,
        "skipped_count": 0,
        "review_pct": 0,
        "total_filings": 0,
        "filings_with_pending": 0,
    }

    client.get("/filings?status=pending")

    mock_db.get_filings_with_candidates_count.assert_called_once_with(status="pending")
    mock_db.get_filings_with_candidates.assert_called_once_with(
        status="pending", limit=50, offset=0
    )


def test_filing_list_rejects_invalid_status(client, mock_db):
    """Test invalid status is ignored."""
    mock_db.get_filings_with_candidates_count.return_value = 0
    mock_db.get_filings_with_candidates.return_value = []
    mock_db.get_review_progress.return_value = {
        "total_candidates": 0,
        "pending_count": 0,
        "reviewed_count": 0,
        "skipped_count": 0,
        "review_pct": 0,
        "total_filings": 0,
        "filings_with_pending": 0,
    }

    client.get("/filings?status=invalid_status")

    # Should call with None, ignoring invalid status
    mock_db.get_filings_with_candidates_count.assert_called_once_with(status=None)
    mock_db.get_filings_with_candidates.assert_called_once_with(
        status=None, limit=50, offset=0
    )


def test_filing_list_handles_database_errors(client, mock_db, mock_render_template):
    """Test filing list handles database errors gracefully."""
    mock_db.get_filings_with_candidates_count.side_effect = Exception("DB error")

    response = client.get("/filings")

    # Should still return 200 with error message
    assert response.status_code == 200
    mock_render_template.assert_called_once()


def test_filing_list_pagination_page_2(client, mock_db):
    """Test filing list with page 2."""
    mock_db.get_filings_with_candidates_count.return_value = 100
    mock_db.get_filings_with_candidates.return_value = []
    mock_db.get_review_progress.return_value = {
        "total_candidates": 100,
        "pending_count": 50,
        "reviewed_count": 50,
        "skipped_count": 0,
        "review_pct": 50,
        "total_filings": 100,
        "filings_with_pending": 50,
    }

    response = client.get("/filings?page=2")

    assert response.status_code == 200
    # Page 2 should have offset=50 (page 1 has 0-49, page 2 has 50-99)
    mock_db.get_filings_with_candidates.assert_called_once_with(
        status=None, limit=50, offset=50
    )


def test_filing_list_pagination_custom_per_page(client, mock_db):
    """Test filing list with custom per_page."""
    mock_db.get_filings_with_candidates_count.return_value = 100
    mock_db.get_filings_with_candidates.return_value = []
    mock_db.get_review_progress.return_value = {
        "total_candidates": 100,
        "pending_count": 50,
        "reviewed_count": 50,
        "skipped_count": 0,
        "review_pct": 50,
        "total_filings": 100,
        "filings_with_pending": 50,
    }

    response = client.get("/filings?page=1&per_page=25")

    assert response.status_code == 200
    mock_db.get_filings_with_candidates.assert_called_once_with(
        status=None, limit=25, offset=0
    )


def test_filing_list_pagination_clamps_per_page(client, mock_db):
    """Test filing list clamps per_page to max 100."""
    mock_db.get_filings_with_candidates_count.return_value = 500
    mock_db.get_filings_with_candidates.return_value = []
    mock_db.get_review_progress.return_value = {
        "total_candidates": 500,
        "pending_count": 250,
        "reviewed_count": 250,
        "skipped_count": 0,
        "review_pct": 50,
        "total_filings": 500,
        "filings_with_pending": 250,
    }

    response = client.get("/filings?per_page=200")

    assert response.status_code == 200
    # Validation should clamp to 100, but _paginate also clamps, so final limit=100
    mock_db.get_filings_with_candidates.assert_called_once_with(
        status=None, limit=100, offset=0
    )


# =============================================================================
# Test review_filing() route
# =============================================================================

def test_review_filing_queries_filing_and_candidates(client, mock_db, mock_render_template):
    """Test review_filing queries correct data."""
    # Mock filing query
    mock_db.query.return_value = [{"filing_id": 1, "company_id": 1, "company_name": "Test", "cik": "0001234567", "accession_number": "0001234567-21-000001", "form_type": "S-1", "filing_date": datetime(2021, 1, 1)}]

    # Mock candidates WITH decisions (new optimized method)
    mock_db.get_review_candidates_with_decisions.return_value = [{"candidate_id": 1, "review_status": "pending", "filing_id": 1, "char_position": 100, "context_text": "Test", "raw_number_text": "100", "triggering_keyword": "test", "keyword_distance": 5, "keyword_position": "after", "decision_id": None, "decision": None, "assigned_metric_id": None, "rejection_category": None, "rejection_reason": None, "reviewer_notes": None, "reviewer_id": None, "review_time_seconds": None, "decision_created_at": None}]

    # Mock _get_active_metrics to avoid Flask g context issues
    with patch("src.web.routes.review._get_active_metrics") as mock_metrics:
        mock_metrics.return_value = []

        response = client.get("/review/1")

        assert response.status_code == 200
        mock_db.query.assert_called_once()
        mock_db.get_review_candidates_with_decisions.assert_called_once()


def test_review_filing_redirects_on_not_found(client, mock_db):
    """Test review_filing redirects when filing not found."""
    mock_db.query.return_value = []

    response = client.get("/review/999")

    # Should redirect to filing list (via error handler or exception)
    # abort(404) is caught and handled
    assert response.status_code in [302, 404]


def test_review_filing_handles_database_errors(client, mock_db):
    """Test review_filing handles database errors."""
    mock_db.query.side_effect = Exception("DB error")

    response = client.get("/review/1")

    assert response.status_code == 302
    assert "/filings" in response.location


# =============================================================================
# Test next_candidate() route
# =============================================================================

def test_next_candidate_finds_next(client, mock_db):
    """Test next_candidate finds next pending candidate."""
    mock_db.get_review_candidates_for_filing.return_value = [
        {"candidate_id": 2, "review_status": "pending"},
        {"candidate_id": 3, "review_status": "pending"},
    ]

    response = client.get("/review/1/next?current_id=1")

    assert response.status_code == 302
    assert "/review/1" in response.location
    assert "candidate_id=2" in response.location


def test_next_candidate_uses_db_helper(client, mock_db):
    """Test next_candidate uses DB helper when no current_id."""
    mock_db.get_next_candidate_for_review.return_value = {"candidate_id": 5}

    response = client.get("/review/1/next")

    assert response.status_code == 302
    mock_db.get_next_candidate_for_review.assert_called_once_with(filing_id=1)


def test_next_candidate_redirects_when_complete(client, mock_db):
    """Test next_candidate redirects to filing list when done."""
    mock_db.get_next_candidate_for_review.return_value = None

    response = client.get("/review/1/next")

    assert response.status_code == 302
    assert "/filings" in response.location


# =============================================================================
# Test jump_to_candidate() route
# =============================================================================

def test_jump_to_candidate_validates_and_redirects(client, mock_db):
    """Test jump_to_candidate validates then redirects."""
    mock_db.get_review_candidate.return_value = {"candidate_id": 1, "filing_id": 1}

    response = client.get("/review/1/candidate/1")

    assert response.status_code == 302
    assert "/review/1" in response.location
    assert "candidate_id=1" in response.location
    mock_db.get_review_candidate.assert_called_once_with(1)


def test_jump_to_candidate_handles_not_found(client, mock_db):
    """Test jump_to_candidate handles candidate not found."""
    mock_db.get_review_candidate.return_value = None

    response = client.get("/review/1/candidate/999")

    # Should redirect to filing list with flash message
    assert response.status_code == 302
    assert "/filings" in response.location


def test_jump_to_candidate_validates_filing_match(client, mock_db):
    """Test jump_to_candidate validates filing_id matches."""
    mock_db.get_review_candidate.return_value = {"candidate_id": 1, "filing_id": 2}

    response = client.get("/review/1/candidate/1")

    # Should redirect to filing list with flash message
    assert response.status_code == 302
    assert "/filings" in response.location


# =============================================================================
# Test input validation
# =============================================================================

def test_filing_list_validates_negative_page(client, mock_db):
    """Test filing list rejects negative page numbers."""
    mock_db.get_filings_with_candidates_count.return_value = 100
    mock_db.get_filings_with_candidates.return_value = []
    mock_db.get_review_progress.return_value = {
        "total_candidates": 100,
        "pending_count": 50,
        "reviewed_count": 50,
        "skipped_count": 0,
        "review_pct": 50,
        "total_filings": 100,
        "filings_with_pending": 50,
    }

    response = client.get("/filings?page=-1")

    assert response.status_code == 200
    # Should use default page=1 instead of -1
    mock_db.get_filings_with_candidates.assert_called_once_with(
        status=None, limit=50, offset=0  # offset=0 means page=1
    )


def test_filing_list_validates_zero_page(client, mock_db):
    """Test filing list rejects zero page numbers."""
    mock_db.get_filings_with_candidates_count.return_value = 100
    mock_db.get_filings_with_candidates.return_value = []
    mock_db.get_review_progress.return_value = {
        "total_candidates": 100,
        "pending_count": 50,
        "reviewed_count": 50,
        "skipped_count": 0,
        "review_pct": 50,
        "total_filings": 100,
        "filings_with_pending": 50,
    }

    response = client.get("/filings?page=0")

    assert response.status_code == 200
    # Should use default page=1 instead of 0
    mock_db.get_filings_with_candidates.assert_called_once_with(
        status=None, limit=50, offset=0  # offset=0 means page=1
    )


def test_filing_list_validates_negative_per_page(client, mock_db):
    """Test filing list rejects negative per_page values."""
    mock_db.get_filings_with_candidates_count.return_value = 100
    mock_db.get_filings_with_candidates.return_value = []
    mock_db.get_review_progress.return_value = {
        "total_candidates": 100,
        "pending_count": 50,
        "reviewed_count": 50,
        "skipped_count": 0,
        "review_pct": 50,
        "total_filings": 100,
        "filings_with_pending": 50,
    }

    response = client.get("/filings?per_page=-10")

    assert response.status_code == 200
    # Should use default per_page=50 instead of -10
    mock_db.get_filings_with_candidates.assert_called_once_with(
        status=None, limit=50, offset=0
    )


def test_filing_list_validates_excessive_per_page(client, mock_db):
    """Test filing list clamps per_page > 100 to max 100."""
    mock_db.get_filings_with_candidates_count.return_value = 500
    mock_db.get_filings_with_candidates.return_value = []
    mock_db.get_review_progress.return_value = {
        "total_candidates": 500,
        "pending_count": 250,
        "reviewed_count": 250,
        "skipped_count": 0,
        "review_pct": 50,
        "total_filings": 500,
        "filings_with_pending": 250,
    }

    response = client.get("/filings?per_page=500")

    assert response.status_code == 200
    # Should clamp to max per_page=100 instead of 500
    mock_db.get_filings_with_candidates.assert_called_once_with(
        status=None, limit=100, offset=0
    )


def test_filing_list_handles_page_overflow(client, mock_db):
    """Test filing list redirects when page exceeds total_pages."""
    # 10 filings = 1 page at 50 per_page, requesting page 100
    mock_db.get_filings_with_candidates_count.return_value = 10
    mock_db.get_review_progress.return_value = {
        "total_candidates": 10,
        "pending_count": 5,
        "reviewed_count": 5,
        "skipped_count": 0,
        "review_pct": 50,
        "total_filings": 10,
        "filings_with_pending": 5,
    }

    response = client.get("/filings?page=100")

    # Should redirect to page 1
    assert response.status_code == 302
    assert "/filings" in response.location
    # Should preserve per_page if provided
    assert "per_page" not in response.location or "per_page=50" in response.location


def test_filing_list_handles_empty_page_2(client, mock_db):
    """Test filing list redirects when page 2 exceeds total pages."""
    # 5 filings = 1 page at 50 per_page, requesting page 2 (which doesn't exist)
    mock_db.get_filings_with_candidates_count.return_value = 5
    # Note: get_filings_with_candidates is NOT called because redirect happens first
    mock_db.get_review_progress.return_value = {
        "total_candidates": 5,
        "pending_count": 5,
        "reviewed_count": 0,
        "skipped_count": 0,
        "review_pct": 0,
        "total_filings": 5,
        "filings_with_pending": 5,
    }

    response = client.get("/filings?page=2")

    # Should redirect to page 1 (caught by page overflow check - improvement #1)
    assert response.status_code == 302
    assert "/filings" in response.location
    # Database query should NOT be called because redirect happens before query
    mock_db.get_filings_with_candidates.assert_not_called()


# =============================================================================
# Test audit logging (improvement #7)
# =============================================================================


def test_audit_log_records_filing_list_request(client, mock_db):
    """Test that audit log is created for filing list requests."""
    mock_db.get_filings_with_candidates.return_value = []
    mock_db.get_filings_with_candidates_count.return_value = 0
    mock_db.get_review_progress.return_value = {
        "total_candidates": 0,
        "pending_count": 0,
        "reviewed_count": 0,
        "skipped_count": 0,
        "review_pct": 0,
        "total_filings": 0,
        "filings_with_pending": 0,
    }

    response = client.get("/filings?page=2&per_page=25&status=pending")

    assert response.status_code == 200

    # Verify audit log was called
    mock_db.insert_audit_log.assert_called_once()
    call_args = mock_db.insert_audit_log.call_args[1]

    # Verify audit log parameters
    assert call_args["route_name"] == "review.filing_list"
    assert call_args["http_method"] == "GET"
    assert call_args["url_path"] == "/filings"
    assert call_args["response_status"] == 200
    assert call_args["filing_id"] is None  # No filing_id in this route
    assert call_args["candidate_id"] is None  # No candidate_id in this route

    # Verify query params were captured
    assert call_args["query_params"] == {
        "page": "2",
        "per_page": "25",
        "status": "pending",
    }

    # Verify response time was captured
    assert call_args["response_time_ms"] is not None
    assert isinstance(call_args["response_time_ms"], int)
    assert call_args["response_time_ms"] >= 0


def test_audit_log_records_review_filing_request(client, mock_db):
    """Test that audit log captures filing_id from URL path."""
    # Mock filing data
    mock_db.query.return_value = [
        {
            "filing_id": 123,
            "company_id": 1,
            "company_name": "Test Co",
            "cik": "0001234567",
            "accession_number": "0001234567-24-000001",
            "form_type": "S-1",
            "filing_date": datetime(2024, 1, 1),
            "file_path": "/path/to/file",
            "status": "fetched",
            "total_pages": 100,
            "html_fetched": True,
            "created_at": datetime(2024, 1, 1),
            "updated_at": datetime(2024, 1, 1),
        }
    ]
    mock_db.get_review_candidates_for_filing.return_value = []

    response = client.get("/review/123?candidate_id=456")

    assert response.status_code == 200

    # Verify audit log was called
    mock_db.insert_audit_log.assert_called_once()
    call_args = mock_db.insert_audit_log.call_args[1]

    # Verify filing_id and candidate_id were captured
    assert call_args["filing_id"] == 123  # From URL path
    assert call_args["candidate_id"] == 456  # From query param
    assert call_args["route_name"] == "review.review_filing"

    # Verify query params include candidate_id
    assert call_args["query_params"]["candidate_id"] == "456"


def test_audit_log_handles_missing_table_gracefully(client, mock_db):
    """Test that requests succeed even if audit log insert fails."""
    # Simulate audit log table not existing
    mock_db.insert_audit_log.side_effect = Exception("relation 'review_audit_log' does not exist")

    mock_db.get_filings_with_candidates.return_value = []
    mock_db.get_filings_with_candidates_count.return_value = 0
    mock_db.get_review_progress.return_value = {
        "total_candidates": 0,
        "pending_count": 0,
        "reviewed_count": 0,
        "skipped_count": 0,
        "review_pct": 0,
        "total_filings": 0,
        "filings_with_pending": 0,
    }

    # Request should still succeed
    response = client.get("/filings")

    assert response.status_code == 200
    # Audit log was attempted but failed gracefully
    mock_db.insert_audit_log.assert_called_once()


def test_audit_log_captures_session_and_user_agent(client, mock_db):
    """Test that audit log captures session ID and user agent."""
    mock_db.get_filings_with_candidates.return_value = []
    mock_db.get_filings_with_candidates_count.return_value = 0
    mock_db.get_review_progress.return_value = {
        "total_candidates": 0,
        "pending_count": 0,
        "reviewed_count": 0,
        "skipped_count": 0,
        "review_pct": 0,
        "total_filings": 0,
        "filings_with_pending": 0,
    }

    # Make request with custom user agent
    response = client.get(
        "/filings",
        headers={"User-Agent": "TestClient/1.0"},
    )

    assert response.status_code == 200

    # Verify audit log captured user agent
    call_args = mock_db.insert_audit_log.call_args[1]
    assert call_args["user_agent"] == "TestClient/1.0"

    # Session ID is captured (may be None in test client, non-None in real browser)
    # Just verify the field exists in the call
    assert "session_id" in call_args


def test_audit_log_captures_redirect_status(client, mock_db):
    """Test that audit log captures 302 redirect status codes."""
    mock_db.get_filings_with_candidates_count.return_value = 10
    mock_db.get_review_progress.return_value = {
        "total_candidates": 10,
        "pending_count": 5,
        "reviewed_count": 5,
        "skipped_count": 0,
        "review_pct": 50,
        "total_filings": 10,
        "filings_with_pending": 5,
    }

    # Request page that doesn't exist (triggers redirect)
    response = client.get("/filings?page=100")

    assert response.status_code == 302

    # Verify audit log captured redirect status
    call_args = mock_db.insert_audit_log.call_args[1]
    assert call_args["response_status"] == 302
