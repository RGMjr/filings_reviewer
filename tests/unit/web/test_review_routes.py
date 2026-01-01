"""
Unit tests for Flask review routes (D1).

Tests all routes in src/web/routes/review.py using mocked database.
"""

from datetime import datetime
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
    # Note: Called twice now (once for all candidates, once for filtered)
    mock_db.get_review_candidates_with_decisions.return_value = [{"candidate_id": 1, "review_status": "pending", "filing_id": 1, "char_position": 100, "context_text": "Test", "raw_number_text": "100", "triggering_keyword": "test", "keyword_distance": 5, "keyword_position": "after", "suggested_metric_id": "cm_arr", "decision_id": None, "decision": None, "assigned_metric_id": None, "rejection_category": None, "rejection_reason": None, "reviewer_notes": None, "reviewer_id": None, "review_time_seconds": None, "decision_created_at": None}]

    # Mock _get_active_metrics to avoid Flask g context issues
    with patch("src.web.routes.review._get_active_metrics") as mock_metrics:
        mock_metrics.return_value = []

        response = client.get("/review/1")

        assert response.status_code == 200
        mock_db.query.assert_called_once()
        # Called twice: once for all candidates (unfiltered count), once for filtered results
        assert mock_db.get_review_candidates_with_decisions.call_count == 2


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
# Test review_filing() filtering and sorting (HRI-6)
# =============================================================================

def test_review_filing_applies_status_filter(client, mock_db, mock_render_template):
    """Test review_filing applies status filter to database query."""
    # Mock filing query
    mock_db.query.return_value = [{"filing_id": 1, "company_id": 1, "company_name": "Test", "cik": "0001234567", "accession_number": "0001234567-21-000001", "form_type": "S-1", "filing_date": datetime(2021, 1, 1)}]

    # Mock candidates
    mock_db.get_review_candidates_with_decisions.return_value = [
        {"candidate_id": 1, "review_status": "pending", "suggested_metric_id": "cm_arr", "char_position": 100}
    ]

    with patch("src.web.routes.review._get_active_metrics") as mock_metrics:
        mock_metrics.return_value = []

        response = client.get("/review/1?status=pending")

        assert response.status_code == 200
        # Should be called twice: once for total count, once for filtered
        assert mock_db.get_review_candidates_with_decisions.call_count == 2
        # Second call should have status filter
        second_call_kwargs = mock_db.get_review_candidates_with_decisions.call_args_list[1][1]
        assert second_call_kwargs["status"] == "pending"


def test_review_filing_applies_metric_filter(client, mock_db, mock_render_template):
    """Test review_filing applies metric filter to database query."""
    mock_db.query.return_value = [{"filing_id": 1, "company_id": 1, "company_name": "Test", "cik": "0001234567", "accession_number": "0001234567-21-000001", "form_type": "S-1", "filing_date": datetime(2021, 1, 1)}]
    mock_db.get_review_candidates_with_decisions.return_value = [
        {"candidate_id": 1, "review_status": "pending", "suggested_metric_id": "cm_arr", "char_position": 100}
    ]

    with patch("src.web.routes.review._get_active_metrics") as mock_metrics:
        mock_metrics.return_value = []

        response = client.get("/review/1?metric=cm_arr")

        assert response.status_code == 200
        second_call_kwargs = mock_db.get_review_candidates_with_decisions.call_args_list[1][1]
        assert second_call_kwargs["metric_id"] == "cm_arr"


def test_review_filing_applies_confidence_filter(client, mock_db, mock_render_template):
    """Test review_filing applies confidence filter to database query."""
    mock_db.query.return_value = [{"filing_id": 1, "company_id": 1, "company_name": "Test", "cik": "0001234567", "accession_number": "0001234567-21-000001", "form_type": "S-1", "filing_date": datetime(2021, 1, 1)}]
    mock_db.get_review_candidates_with_decisions.return_value = [
        {"candidate_id": 1, "review_status": "pending", "suggested_metric_id": "cm_arr", "suggestion_confidence": 0.8, "char_position": 100}
    ]

    with patch("src.web.routes.review._get_active_metrics") as mock_metrics:
        mock_metrics.return_value = []

        response = client.get("/review/1?confidence=high")

        assert response.status_code == 200
        second_call_kwargs = mock_db.get_review_candidates_with_decisions.call_args_list[1][1]
        assert second_call_kwargs["confidence_level"] == "high"


def test_review_filing_applies_sort_parameter(client, mock_db, mock_render_template):
    """Test review_filing applies sort parameter to database query."""
    mock_db.query.return_value = [{"filing_id": 1, "company_id": 1, "company_name": "Test", "cik": "0001234567", "accession_number": "0001234567-21-000001", "form_type": "S-1", "filing_date": datetime(2021, 1, 1)}]
    mock_db.get_review_candidates_with_decisions.return_value = [
        {"candidate_id": 1, "review_status": "pending", "suggested_metric_id": "cm_arr", "suggestion_confidence": 0.8, "char_position": 100}
    ]

    with patch("src.web.routes.review._get_active_metrics") as mock_metrics:
        mock_metrics.return_value = []

        response = client.get("/review/1?sort=confidence_desc")

        assert response.status_code == 200
        second_call_kwargs = mock_db.get_review_candidates_with_decisions.call_args_list[1][1]
        assert second_call_kwargs["sort_by"] == "confidence_desc"


def test_review_filing_invalid_filter_values_ignored(client, mock_db, mock_render_template):
    """Test review_filing ignores invalid filter values and uses defaults."""
    mock_db.query.return_value = [{"filing_id": 1, "company_id": 1, "company_name": "Test", "cik": "0001234567", "accession_number": "0001234567-21-000001", "form_type": "S-1", "filing_date": datetime(2021, 1, 1)}]
    mock_db.get_review_candidates_with_decisions.return_value = [
        {"candidate_id": 1, "review_status": "pending", "suggested_metric_id": "cm_arr", "char_position": 100}
    ]

    with patch("src.web.routes.review._get_active_metrics") as mock_metrics:
        mock_metrics.return_value = []

        response = client.get("/review/1?status=invalid&confidence=invalid&sort=invalid")

        assert response.status_code == 200
        second_call_kwargs = mock_db.get_review_candidates_with_decisions.call_args_list[1][1]
        # Invalid values should be ignored (None or default)
        assert second_call_kwargs["status"] is None
        assert second_call_kwargs["confidence_level"] is None
        assert second_call_kwargs["sort_by"] == "position"  # default


def test_review_filing_combined_filters(client, mock_db, mock_render_template):
    """Test review_filing applies multiple filters together."""
    mock_db.query.return_value = [{"filing_id": 1, "company_id": 1, "company_name": "Test", "cik": "0001234567", "accession_number": "0001234567-21-000001", "form_type": "S-1", "filing_date": datetime(2021, 1, 1)}]
    mock_db.get_review_candidates_with_decisions.return_value = [
        {"candidate_id": 1, "review_status": "pending", "suggested_metric_id": "cm_arr", "suggestion_confidence": 0.8, "char_position": 100}
    ]

    with patch("src.web.routes.review._get_active_metrics") as mock_metrics:
        mock_metrics.return_value = []

        response = client.get("/review/1?status=pending&metric=cm_arr&confidence=high&sort=confidence_desc")

        assert response.status_code == 200
        second_call_kwargs = mock_db.get_review_candidates_with_decisions.call_args_list[1][1]
        assert second_call_kwargs["status"] == "pending"
        assert second_call_kwargs["metric_id"] == "cm_arr"
        assert second_call_kwargs["confidence_level"] == "high"
        assert second_call_kwargs["sort_by"] == "confidence_desc"


def test_review_filing_template_receives_filter_context(client, mock_db, mock_render_template):
    """Test review_filing passes filter state to template."""
    mock_db.query.return_value = [{"filing_id": 1, "company_id": 1, "company_name": "Test", "cik": "0001234567", "accession_number": "0001234567-21-000001", "form_type": "S-1", "filing_date": datetime(2021, 1, 1)}]
    mock_db.get_review_candidates_with_decisions.return_value = [
        {"candidate_id": 1, "review_status": "pending", "suggested_metric_id": "cm_arr", "char_position": 100},
        {"candidate_id": 2, "review_status": "pending", "suggested_metric_id": "cm_mrr", "char_position": 200}
    ]

    with patch("src.web.routes.review._get_active_metrics") as mock_metrics:
        mock_metrics.return_value = []

        response = client.get("/review/1?status=pending&metric=cm_arr")

        assert response.status_code == 200
        # Check template context
        template_context = mock_render_template.call_args[1]
        assert "current_filters" in template_context
        assert template_context["current_filters"]["status"] == "pending"
        assert template_context["current_filters"]["metric"] == "cm_arr"
        assert template_context["current_filters"]["has_active_filters"] is True
        assert "available_metrics" in template_context
        # available_metrics should include both cm_arr and cm_mrr from all_candidates
        assert "cm_arr" in template_context["available_metrics"]
        assert "cm_mrr" in template_context["available_metrics"]


def test_review_filing_unfiltered_count_in_context(client, mock_db, mock_render_template):
    """Test review_filing provides both filtered and unfiltered counts."""
    mock_db.query.return_value = [{"filing_id": 1, "company_id": 1, "company_name": "Test", "cik": "0001234567", "accession_number": "0001234567-21-000001", "form_type": "S-1", "filing_date": datetime(2021, 1, 1)}]
    # First call (all candidates): 3 candidates
    # Second call (filtered): 1 candidate
    mock_db.get_review_candidates_with_decisions.side_effect = [
        [
            {"candidate_id": 1, "review_status": "pending", "suggested_metric_id": "cm_arr", "char_position": 100},
            {"candidate_id": 2, "review_status": "reviewed", "suggested_metric_id": "cm_arr", "char_position": 200},
            {"candidate_id": 3, "review_status": "reviewed", "suggested_metric_id": "cm_arr", "char_position": 300}
        ],
        [
            {"candidate_id": 1, "review_status": "pending", "suggested_metric_id": "cm_arr", "char_position": 100}
        ]
    ]

    with patch("src.web.routes.review._get_active_metrics") as mock_metrics:
        mock_metrics.return_value = []

        response = client.get("/review/1?status=pending")

        assert response.status_code == 200
        template_context = mock_render_template.call_args[1]
        assert template_context["total_candidates_unfiltered"] == 3
        assert template_context["total_candidates"] == 1


def test_review_filing_all_status_values_supported(client, mock_db, mock_render_template):
    """Test review_filing supports all valid status values."""
    mock_db.query.return_value = [{"filing_id": 1, "company_id": 1, "company_name": "Test", "cik": "0001234567", "accession_number": "0001234567-21-000001", "form_type": "S-1", "filing_date": datetime(2021, 1, 1)}]
    mock_db.get_review_candidates_with_decisions.return_value = [
        {"candidate_id": 1, "review_status": "skipped", "suggested_metric_id": "cm_arr", "char_position": 100}
    ]

    with patch("src.web.routes.review._get_active_metrics") as mock_metrics:
        mock_metrics.return_value = []

        # Test each valid status value
        for status in ["pending", "reviewed", "in_progress", "skipped"]:
            response = client.get(f"/review/1?status={status}")
            assert response.status_code == 200


# =============================================================================
# Test next_candidate() route
# =============================================================================

def test_next_candidate_finds_next(client, mock_db):
    """Test next_candidate finds next pending candidate in sorted order."""
    # Navigation now uses get_review_candidates_with_decisions with filter-aware sorting
    mock_db.get_review_candidates_with_decisions.return_value = [
        {"candidate_id": 2, "review_status": "pending"},
        {"candidate_id": 3, "review_status": "pending"},
    ]

    response = client.get("/review/1/next?current_id=1")

    assert response.status_code == 302
    assert "/review/1" in response.location
    # First candidate in filtered list (since current_id=1 is not in list)
    assert "candidate_id=2" in response.location


def test_next_candidate_uses_db_helper(client, mock_db):
    """Test next_candidate finds first pending when no current_id."""
    mock_db.get_review_candidates_with_decisions.return_value = [
        {"candidate_id": 5, "review_status": "pending"},
    ]

    response = client.get("/review/1/next")

    assert response.status_code == 302
    assert "candidate_id=5" in response.location
    mock_db.get_review_candidates_with_decisions.assert_called_once()


def test_next_candidate_redirects_when_complete(client, mock_db):
    """Test next_candidate redirects to filing list when done."""
    mock_db.get_review_candidates_with_decisions.return_value = []

    response = client.get("/review/1/next")

    assert response.status_code == 302
    assert "/filings" in response.location


def test_next_candidate_wraps_around(client, mock_db):
    """Test next_candidate wraps around to beginning of filtered list.

    Note: Navigation now follows the user's sort order (default: document position),
    not candidate_id order. Wrap-around goes to first item in sorted list.
    """
    # DB returns candidates in document position order
    mock_db.get_review_candidates_with_decisions.return_value = [
        {"candidate_id": 1, "review_status": "pending"},
        {"candidate_id": 50, "review_status": "pending"},
    ]

    # current_id=100 is not in the list, so returns first candidate
    response = client.get("/review/1/next?current_id=100")

    assert response.status_code == 302
    # Returns first in filtered list
    assert "candidate_id=1" in response.location


def test_next_candidate_sequential_order(client, mock_db):
    """Test next_candidate goes to next item in sorted list order.

    Note: Order is now based on user's sort preference (default: document position),
    not candidate_id. Test verifies advancing through sorted list.
    """
    # current is #10, DB returns candidates in position order: [5, 15]
    mock_db.get_review_candidates_with_decisions.return_value = [
        {"candidate_id": 5, "review_status": "pending"},
        {"candidate_id": 15, "review_status": "pending"},
    ]

    # current_id=10 is not in list, returns first candidate
    response = client.get("/review/1/next?current_id=10")

    assert response.status_code == 302
    # Returns first in sorted list since current not found
    assert "candidate_id=5" in response.location


def test_next_candidate_handles_unsorted_db_results(client, mock_db):
    """Test next_candidate navigates in sort order from database.

    Navigation respects the sort order specified in filters (default: position).
    The DB now returns already-sorted results based on user preferences.
    """
    # DB returns candidates already sorted by position order
    mock_db.get_review_candidates_with_decisions.return_value = [
        {"candidate_id": 84, "review_status": "pending"},  # char_position=100
        {"candidate_id": 10, "review_status": "pending"},  # char_position=200
        {"candidate_id": 15, "review_status": "pending"},  # char_position=300
    ]

    # current_id=9 is not in list, returns first candidate
    response = client.get("/review/1/next?current_id=9")

    assert response.status_code == 302
    # Returns first in sorted list (position order)
    assert "candidate_id=84" in response.location


def test_next_candidate_preserves_filter_params(client, mock_db):
    """Test next_candidate preserves filter parameters in redirect URL."""
    mock_db.get_review_candidates_with_decisions.return_value = [
        {"candidate_id": 5, "review_status": "pending"},
    ]

    # Request with filter parameters
    response = client.get("/review/1/next?status=pending&metric=cm_arr&confidence=high&sort=confidence_desc")

    assert response.status_code == 302
    # Filter params should be preserved in redirect
    assert "status=pending" in response.location
    assert "metric=cm_arr" in response.location
    assert "confidence=high" in response.location
    assert "sort=confidence_desc" in response.location


def test_next_candidate_passes_filters_to_db(client, mock_db):
    """Test next_candidate passes filter parameters to database query."""
    mock_db.get_review_candidates_with_decisions.return_value = []

    client.get("/review/1/next?metric=cm_dau&confidence=low&sort=value_asc")

    # Verify database was called with correct parameters
    mock_db.get_review_candidates_with_decisions.assert_called_once()
    call_kwargs = mock_db.get_review_candidates_with_decisions.call_args[1]
    assert call_kwargs["filing_id"] == 1
    assert call_kwargs["metric_id"] == "cm_dau"
    assert call_kwargs["confidence_level"] == "low"
    assert call_kwargs["sort_by"] == "value_asc"


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


# =============================================================================
# Helper Function Tests: _highlight_context()
# =============================================================================


def test_highlight_context_basic():
    """Test basic number and keyword highlighting."""
    from src.web.routes.review import _highlight_context

    context = "We had 1,234 active customers in Q1 2023."
    result = _highlight_context(context, "1,234", "customers")

    # Check that result is Markup
    from markupsafe import Markup

    assert isinstance(result, Markup)

    # Check number is highlighted with <mark>
    assert '<mark class="extracted-number">1,234</mark>' in result

    # Check keyword is underlined with <u>
    assert '<u class="triggering-keyword">customers</u>' in result

    # Check basic text is preserved
    assert "We had" in result
    assert "in Q1 2023" in result


def test_highlight_context_escapes_html():
    """Test HTML escaping for XSS protection."""
    from src.web.routes.review import _highlight_context

    context = "We had <script>alert('xss')</script> 1,234 customers."
    result = _highlight_context(context, "1,234", "customers")

    # Check that script tags are escaped
    assert "<script>" not in result
    assert "&lt;script&gt;" in result
    assert "&lt;/script&gt;" in result

    # Check number is still highlighted
    assert '<mark class="extracted-number">1,234</mark>' in result


def test_highlight_context_number_not_found():
    """Test handling when number is not found in context."""
    from src.web.routes.review import _highlight_context

    context = "We had many active customers in Q1."
    result = _highlight_context(context, "1,234", "customers")

    # Number should not be highlighted (not found)
    assert '<mark class="extracted-number">1,234</mark>' not in result

    # Keyword should still be highlighted
    assert '<u class="triggering-keyword">customers</u>' in result

    # Context should be preserved
    assert "We had many active" in result


def test_highlight_context_keyword_not_found():
    """Test handling when keyword is not found in context."""
    from src.web.routes.review import _highlight_context

    context = "The total was 1,234 in the last quarter."
    result = _highlight_context(context, "1,234", "customers")

    # Number should be highlighted
    assert '<mark class="extracted-number">1,234</mark>' in result

    # Keyword should not be highlighted (not found)
    assert '<u class="triggering-keyword">customers</u>' not in result

    # Context should be preserved
    assert "The total was" in result


def test_highlight_context_case_insensitive_keyword():
    """Test that keyword matching is case-insensitive."""
    from src.web.routes.review import _highlight_context

    context = "We had 1,234 Active Customers in Q1."
    result = _highlight_context(context, "1,234", "customers")

    # Keyword should match case-insensitively and preserve original case
    assert '<u class="triggering-keyword">Customers</u>' in result

    # Number should also be highlighted
    assert '<mark class="extracted-number">1,234</mark>' in result


def test_highlight_context_with_special_chars():
    """Test highlighting with special characters in number."""
    from src.web.routes.review import _highlight_context

    context = "Our revenue was $493M in fiscal year 2023."
    result = _highlight_context(context, "$493M", "revenue")

    # Check number with special chars is highlighted
    assert '<mark class="extracted-number">$493M</mark>' in result

    # Check keyword is highlighted
    assert '<u class="triggering-keyword">revenue</u>' in result


# =============================================================================
# Test stats() route (HRI-11)
# =============================================================================

def test_stats_returns_200(client, mock_db, mock_render_template):
    """Test that /review/stats route returns 200 status."""
    # Mock all required database methods
    mock_db.get_decision_statistics.return_value = {
        "total_decisions": 10,
        "accept_count": 6,
        "reject_count": 3,
        "reclassify_count": 1,
        "accept_pct": 60.0,
        "reject_pct": 30.0,
        "avg_review_time_seconds": 25.5,
    }
    mock_db.get_decision_stats_by_metric.return_value = []
    mock_db.get_daily_decision_counts.return_value = []
    mock_db.get_review_progress.return_value = {
        "total_candidates": 100,
        "pending_count": 50,
        "reviewed_count": 50,
        "skipped_count": 0,
        "review_pct": 50.0,
        "total_filings": 5,
        "filings_with_pending": 3,
    }

    response = client.get("/stats")

    assert response.status_code == 200
    mock_render_template.assert_called_once()


def test_stats_passes_correct_context(client, mock_db, mock_render_template):
    """Test that stats route passes expected context variables to template."""
    overall_stats = {
        "total_decisions": 10,
        "accept_count": 6,
        "reject_count": 3,
        "reclassify_count": 1,
        "accept_pct": 60.0,
        "reject_pct": 30.0,
        "avg_review_time_seconds": 25.5,
    }
    metric_stats = [
        {"suggested_metric": "cm_new_customers_acquired", "decision": "accept", "decision_count": 5, "pct_of_metric": 100.0}
    ]
    daily_counts = [
        {"date": "2025-12-17", "count": 3},
        {"date": "2025-12-16", "count": 2},
    ]
    progress = {
        "total_candidates": 100,
        "pending_count": 50,
        "reviewed_count": 50,
        "skipped_count": 0,
        "review_pct": 50.0,
        "total_filings": 5,
        "filings_with_pending": 3,
    }

    mock_db.get_decision_statistics.return_value = overall_stats
    mock_db.get_decision_stats_by_metric.return_value = metric_stats
    mock_db.get_daily_decision_counts.return_value = daily_counts
    mock_db.get_review_progress.return_value = progress

    response = client.get("/stats")

    assert response.status_code == 200

    # Verify render_template was called with correct context
    mock_render_template.assert_called_once_with(
        "stats.html",
        overall_stats=overall_stats,
        metric_stats=metric_stats,
        daily_counts=daily_counts,
        progress=progress,
    )


def test_stats_handles_empty_database(client, mock_db, mock_render_template):
    """Test that stats route handles empty database gracefully."""
    # Mock empty statistics
    mock_db.get_decision_statistics.return_value = {
        "total_decisions": 0,
        "accept_count": 0,
        "reject_count": 0,
        "reclassify_count": 0,
        "accept_pct": 0,
        "reject_pct": 0,
        "avg_review_time_seconds": None,
    }
    mock_db.get_decision_stats_by_metric.return_value = []
    mock_db.get_daily_decision_counts.return_value = [
        {"date": f"2025-12-{17-i}", "count": 0} for i in range(7)
    ]
    mock_db.get_review_progress.return_value = {
        "total_candidates": 0,
        "pending_count": 0,
        "reviewed_count": 0,
        "skipped_count": 0,
        "review_pct": 0,
        "total_filings": 0,
        "filings_with_pending": 0,
    }

    response = client.get("/stats")

    assert response.status_code == 200
    mock_render_template.assert_called_once()

    # Verify template was called with empty data
    call_args = mock_render_template.call_args
    assert call_args[1]["overall_stats"]["total_decisions"] == 0
    assert call_args[1]["metric_stats"] == []
