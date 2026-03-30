"""
Unit tests for Flask image review page routes (IMG-1-4).

Tests all routes in src/web/routes/review_images.py using mocked database.
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
    with patch("src.web.routes.review_images.get_db") as mock_get_db:
        mock = MagicMock()
        mock_get_db.return_value = mock
        yield mock


@pytest.fixture(autouse=True)
def mock_render_template():
    """Mock render_template to avoid needing actual templates."""
    with patch("src.web.routes.review_images.render_template") as mock:
        mock.return_value = "mocked template"
        yield mock


# =============================================================================
# Sample Data Fixtures
# =============================================================================


@pytest.fixture
def sample_filing():
    """Sample filing data for review routes."""
    return {
        "filing_id": 123,
        "company_id": 456,
        "company_name": "Test Corp",
        "cik": "0001234567",
        "accession_number": "0001234567-21-000001",
        "form_type": "S-1",
        "filing_date": datetime(2021, 1, 15),
        "file_path": "/path/to/filing.html",
        "status": "processed",
    }


@pytest.fixture
def sample_candidates():
    """Sample image candidates for review routes."""
    return [
        {
            "image_candidate_id": 1,
            "filing_id": 123,
            "company_id": 456,
            "image_src": "chart1.jpg",
            "image_url": "https://example.com/chart1.jpg",
            "image_width": 800,
            "image_height": 600,
            "image_alt": "Cohort Chart",
            "image_index": 0,
            "preceding_text": "As shown in the chart below",
            "detected_keywords": ["cohort"],
            "cohort_confidence": 0.85,
            "detection_tier": "tier_1_cohort",
            "review_status": "pending",
            "created_at": datetime(2021, 1, 16),
            "image_decision_id": None,
            "decision": None,
            "chart_type": None,
            "rejection_reason": None,
            "decision_notes": None,
            "review_time_seconds": None,
            "decision_created_at": None,
        },
        {
            "image_candidate_id": 2,
            "filing_id": 123,
            "company_id": 456,
            "image_src": "chart2.png",
            "image_url": None,
            "image_width": 600,
            "image_height": 400,
            "image_alt": None,
            "image_index": 1,
            "preceding_text": "Revenue by cohort",
            "detected_keywords": ["revenue", "cohort"],
            "cohort_confidence": 0.72,
            "detection_tier": "tier_2_large",
            "review_status": "reviewed",
            "created_at": datetime(2021, 1, 16),
            "image_decision_id": 10,
            "decision": "relevant",
            "chart_type": "cohort_table",
            "rejection_reason": None,
            "decision_notes": "Good chart",
            "review_time_seconds": 15,
            "decision_created_at": datetime(2021, 1, 17),
        },
    ]


@pytest.fixture
def sample_progress():
    """Sample progress data."""
    return {
        "total_candidates": 100,
        "pending_count": 60,
        "reviewed_count": 35,
        "skipped_count": 5,
        "review_pct": 35.0,
        "total_filings": 10,
        "filings_with_pending": 8,
        "by_tier": {
            "tier_1_cohort": {"total": 30, "pending": 15, "reviewed": 15},
            "tier_2_large": {"total": 40, "pending": 25, "reviewed": 10},
            "tier_3_all": {"total": 30, "pending": 20, "reviewed": 10},
        },
    }


# =============================================================================
# Test index() route
# =============================================================================


def test_index_redirects_to_filing_list(client):
    """Test that /review/images/ redirects to /review/images/filings."""
    response = client.get("/review/images/")
    assert response.status_code == 302
    assert "/review/images/filings" in response.location


# =============================================================================
# Test filing_list() route - Filing List Tests
# =============================================================================


def test_filing_list_returns_filings_with_counts(client, mock_db, mock_render_template):
    """Test filing list renders with correct context."""
    mock_db.get_filings_with_image_candidates_count.return_value = 5
    mock_db.get_filings_with_image_candidates.return_value = [
        {
            "filing_id": 1,
            "accession_number": "0001-21-001",
            "form_type": "S-1",
            "filing_date": datetime(2021, 1, 1),
            "company_name": "Test Corp",
            "cik": "0001234567",
            "total_candidates": 10,
            "pending_count": 5,
            "reviewed_count": 3,
            "skipped_count": 2,
            "first_candidate_date": datetime(2021, 1, 2),
        }
    ]
    mock_db.get_image_review_progress.return_value = {
        "total_candidates": 10,
        "pending_count": 5,
        "reviewed_count": 3,
        "skipped_count": 2,
        "review_pct": 30.0,
        "total_filings": 1,
        "filings_with_pending": 1,
        "by_tier": {},
    }

    response = client.get("/review/images/filings")

    assert response.status_code == 200
    mock_db.get_filings_with_image_candidates.assert_called_once_with(
        status=None, limit=50, offset=0
    )
    mock_db.get_filings_with_image_candidates_count.assert_called_once_with(status=None)
    mock_db.get_image_review_progress.assert_called_once()

    # Verify template was called with correct context
    call_args = mock_render_template.call_args
    assert call_args[0][0] == "image_filing_list.html"
    assert "filings" in call_args[1]
    assert "progress" in call_args[1]
    assert "pagination" in call_args[1]


def test_filing_list_pagination_works(client, mock_db, mock_render_template):
    """Test filing list respects pagination parameters."""
    mock_db.get_filings_with_image_candidates_count.return_value = 100
    mock_db.get_filings_with_image_candidates.return_value = []
    mock_db.get_image_review_progress.return_value = {
        "total_candidates": 0,
        "pending_count": 0,
        "reviewed_count": 0,
        "skipped_count": 0,
        "review_pct": 0,
        "total_filings": 0,
        "filings_with_pending": 0,
        "by_tier": {},
    }

    response = client.get("/review/images/filings?page=2&per_page=25")

    assert response.status_code == 200
    mock_db.get_filings_with_image_candidates.assert_called_once_with(
        status=None, limit=25, offset=25
    )


def test_filing_list_status_filter_works(client, mock_db):
    """Test filing list filters by status."""
    mock_db.get_filings_with_image_candidates_count.return_value = 0
    mock_db.get_filings_with_image_candidates.return_value = []
    mock_db.get_image_review_progress.return_value = {
        "total_candidates": 0,
        "pending_count": 0,
        "reviewed_count": 0,
        "skipped_count": 0,
        "review_pct": 0,
        "total_filings": 0,
        "filings_with_pending": 0,
        "by_tier": {},
    }

    client.get("/review/images/filings?status=pending")

    mock_db.get_filings_with_image_candidates_count.assert_called_once_with(status="pending")
    mock_db.get_filings_with_image_candidates.assert_called_once_with(
        status="pending", limit=50, offset=0
    )


def test_filing_list_invalid_status_shows_warning(client, mock_db):
    """Test invalid status filter is rejected with flash warning."""
    mock_db.get_filings_with_image_candidates_count.return_value = 0
    mock_db.get_filings_with_image_candidates.return_value = []
    mock_db.get_image_review_progress.return_value = {
        "total_candidates": 0,
        "pending_count": 0,
        "reviewed_count": 0,
        "skipped_count": 0,
        "review_pct": 0,
        "total_filings": 0,
        "filings_with_pending": 0,
        "by_tier": {},
    }

    response = client.get("/review/images/filings?status=invalid_status")

    # Should use status=None when invalid
    mock_db.get_filings_with_image_candidates_count.assert_called_once_with(status=None)
    assert response.status_code == 200


def test_filing_list_handles_database_error(client, mock_db, mock_render_template):
    """Test filing list handles database errors gracefully."""
    mock_db.get_filings_with_image_candidates_count.side_effect = Exception("DB error")

    response = client.get("/review/images/filings")

    assert response.status_code == 200
    # Should render template with empty data
    mock_render_template.assert_called_once()


def test_filing_list_page_exceeds_total_redirects(client, mock_db):
    """Test requesting page beyond total redirects to page 1."""
    mock_db.get_filings_with_image_candidates_count.return_value = 5  # Only 1 page
    mock_db.get_filings_with_image_candidates.return_value = []
    mock_db.get_image_review_progress.return_value = {
        "total_candidates": 0,
        "pending_count": 0,
        "reviewed_count": 0,
        "skipped_count": 0,
        "review_pct": 0,
        "total_filings": 0,
        "filings_with_pending": 0,
        "by_tier": {},
    }

    response = client.get("/review/images/filings?page=999")

    assert response.status_code == 302
    # Should redirect to filing list (without page param = page 1)
    assert "/review/images/filings" in response.location
    # Should NOT include page=999
    assert "page=999" not in response.location


# =============================================================================
# Test review_filing() route - Review Interface Tests
# =============================================================================


def test_review_filing_renders_with_valid_candidate(
    client, mock_db, mock_render_template, sample_filing, sample_candidates
):
    """Test review interface renders correctly."""
    mock_db.query.return_value = [sample_filing]
    mock_db.get_image_review_candidates_for_filing.return_value = sample_candidates

    response = client.get("/review/images/123")

    assert response.status_code == 200

    # Verify template called with correct args
    call_args = mock_render_template.call_args
    assert call_args[0][0] == "review_images.html"
    assert "filing" in call_args[1]
    assert "current_candidate" in call_args[1]
    assert "candidates" in call_args[1]
    assert "progress" in call_args[1]
    assert "chart_types" in call_args[1]
    assert "rejection_reasons" in call_args[1]


def test_review_filing_selects_first_pending_when_no_id(
    client, mock_db, mock_render_template, sample_filing, sample_candidates
):
    """Test review interface selects first pending candidate by default."""
    mock_db.query.return_value = [sample_filing]
    mock_db.get_image_review_candidates_for_filing.return_value = sample_candidates

    response = client.get("/review/images/123")

    assert response.status_code == 200

    # First candidate (pending) should be selected
    call_args = mock_render_template.call_args
    current = call_args[1]["current_candidate"]
    assert current["image_candidate_id"] == 1
    assert current["review_status"] == "pending"


def test_review_filing_selects_specific_candidate_when_requested(
    client, mock_db, mock_render_template, sample_filing, sample_candidates
):
    """Test review interface selects specific candidate when ID provided."""
    mock_db.query.return_value = [sample_filing]
    mock_db.get_image_review_candidates_for_filing.return_value = sample_candidates

    response = client.get("/review/images/123?image_candidate_id=2")

    assert response.status_code == 200

    call_args = mock_render_template.call_args
    current = call_args[1]["current_candidate"]
    assert current["image_candidate_id"] == 2


def test_review_filing_404_for_invalid_filing(client, mock_db):
    """Test 404 returned for non-existent filing."""
    mock_db.query.return_value = []

    response = client.get("/review/images/99999")

    assert response.status_code == 404


def test_review_filing_redirects_when_no_candidates(client, mock_db, sample_filing):
    """Test redirect to filing list when filing has no candidates."""
    mock_db.query.return_value = [sample_filing]
    mock_db.get_image_review_candidates_for_filing.return_value = []

    response = client.get("/review/images/123")

    assert response.status_code == 302
    assert "/review/images/filings" in response.location


def test_review_filing_handles_database_error(client, mock_db, sample_filing):
    """Test review interface handles database errors."""
    mock_db.query.return_value = [sample_filing]
    mock_db.get_image_review_candidates_for_filing.side_effect = Exception("DB error")

    response = client.get("/review/images/123")

    assert response.status_code == 302
    assert "/review/images/filings" in response.location


def test_review_filing_filters_by_status(
    client, mock_db, mock_render_template, sample_filing, sample_candidates
):
    """Test review interface respects status filter."""
    mock_db.query.return_value = [sample_filing]
    mock_db.get_image_review_candidates_for_filing.return_value = sample_candidates

    response = client.get("/review/images/123?status=pending")

    assert response.status_code == 200
    # Should call db method twice - once unfiltered, once filtered
    calls = mock_db.get_image_review_candidates_for_filing.call_args_list
    assert len(calls) == 2
    # Second call should have status filter
    assert calls[1][1]["status"] == "pending"


def test_review_filing_sorts_by_parameter(
    client, mock_db, mock_render_template, sample_filing, sample_candidates
):
    """Test review interface respects sort parameter."""
    mock_db.query.return_value = [sample_filing]
    mock_db.get_image_review_candidates_for_filing.return_value = sample_candidates

    response = client.get("/review/images/123?sort=confidence")

    assert response.status_code == 200
    calls = mock_db.get_image_review_candidates_for_filing.call_args_list
    # Second call should have sort_by=confidence
    assert calls[1][1]["sort_by"] == "confidence"


# =============================================================================
# Test next_candidate() route - Navigation Tests
# =============================================================================


def test_next_candidate_redirects_correctly(client, mock_db):
    """Test next candidate navigation redirects to correct URL."""
    mock_db.get_next_pending_image_candidate.return_value = {
        "image_candidate_id": 5,
        "image_src": "next.jpg",
        "image_url": None,
        "detection_tier": "tier_1_cohort",
        "cohort_confidence": 0.9,
        "image_index": 2,
    }

    response = client.get("/review/images/123/next?current=3")

    assert response.status_code == 302
    assert "/review/images/123" in response.location
    assert "image_candidate_id=5" in response.location

    mock_db.get_next_pending_image_candidate.assert_called_once_with(
        filing_id=123, current_candidate_id=3
    )


def test_next_candidate_handles_all_done(client, mock_db):
    """Test next candidate navigation when all candidates reviewed."""
    mock_db.get_next_pending_image_candidate.return_value = None

    response = client.get("/review/images/123/next?current=10")

    assert response.status_code == 302
    assert "/review/images/filings" in response.location


def test_next_candidate_error_handling(client, mock_db):
    """Test next candidate navigation handles database errors."""
    mock_db.get_next_pending_image_candidate.side_effect = Exception("DB error")

    response = client.get("/review/images/123/next")

    assert response.status_code == 302
    assert "/review/images/filings" in response.location


def test_next_candidate_without_current_id(client, mock_db):
    """Test next candidate works without current_id parameter."""
    mock_db.get_next_pending_image_candidate.return_value = {
        "image_candidate_id": 1,
        "image_src": "first.jpg",
        "image_url": None,
        "detection_tier": "tier_1_cohort",
        "cohort_confidence": 0.8,
        "image_index": 0,
    }

    response = client.get("/review/images/123/next")

    assert response.status_code == 302
    mock_db.get_next_pending_image_candidate.assert_called_once_with(
        filing_id=123, current_candidate_id=None
    )


# =============================================================================
# Test Helper Functions
# =============================================================================


def test_build_sec_filing_url():
    """Test SEC URL building."""
    from src.web.routes.review_images import _build_sec_filing_url

    url = _build_sec_filing_url("0001234567", "0001234567-21-000001")

    assert url == "https://www.sec.gov/Archives/edgar/data/1234567/000123456721000001/"


def test_build_sec_filing_url_strips_leading_zeros():
    """Test SEC URL strips leading zeros from CIK."""
    from src.web.routes.review_images import _build_sec_filing_url

    url = _build_sec_filing_url("0000000123", "0000000123-21-000001")

    assert "/data/123/" in url


def test_paginate_calculates_correctly():
    """Test pagination calculation."""
    from src.web.routes.review_images import _paginate

    result = _paginate(page=3, per_page=25, total_count=100)

    assert result["page"] == 3
    assert result["per_page"] == 25
    assert result["offset"] == 50
    assert result["limit"] == 25
    assert result["total_count"] == 100
    assert result["total_pages"] == 4
    assert result["has_prev"] is True
    assert result["has_next"] is True


def test_paginate_handles_first_page():
    """Test pagination on first page."""
    from src.web.routes.review_images import _paginate

    result = _paginate(page=1, per_page=50, total_count=100)

    assert result["has_prev"] is False
    assert result["has_next"] is True


def test_paginate_handles_last_page():
    """Test pagination on last page."""
    from src.web.routes.review_images import _paginate

    result = _paginate(page=2, per_page=50, total_count=100)

    assert result["has_prev"] is True
    assert result["has_next"] is False


def test_calculate_progress():
    """Test progress calculation from candidates."""
    from src.web.routes.review_images import _calculate_progress

    candidates = [
        {"review_status": "pending"},
        {"review_status": "pending"},
        {"review_status": "reviewed"},
        {"review_status": "skipped"},
    ]

    result = _calculate_progress(candidates)

    assert result["total"] == 4
    assert result["pending"] == 2
    assert result["reviewed"] == 1
    assert result["skipped"] == 1


def test_select_current_candidate_finds_requested():
    """Test selecting specific candidate by ID."""
    from src.web.routes.review_images import _select_current_candidate

    candidates = [
        {"image_candidate_id": 1, "review_status": "pending"},
        {"image_candidate_id": 2, "review_status": "reviewed"},
    ]

    # Need to mock flash for this test since we're calling function directly
    with patch("src.web.routes.review_images.flash"):
        result = _select_current_candidate(candidates, 2)

    assert result["image_candidate_id"] == 2


def test_select_current_candidate_returns_first_pending():
    """Test default selection returns first pending."""
    from src.web.routes.review_images import _select_current_candidate

    candidates = [
        {"image_candidate_id": 1, "review_status": "reviewed"},
        {"image_candidate_id": 2, "review_status": "pending"},
        {"image_candidate_id": 3, "review_status": "pending"},
    ]

    with patch("src.web.routes.review_images.flash"):
        result = _select_current_candidate(candidates, None)

    assert result["image_candidate_id"] == 2


def test_select_current_candidate_empty_list():
    """Test selection returns None for empty list."""
    from src.web.routes.review_images import _select_current_candidate

    with patch("src.web.routes.review_images.flash"):
        result = _select_current_candidate([], None)

    assert result is None


def test_validate_positive_int_valid():
    """Test validation passes for valid integers."""
    from src.web.routes.review_images import _validate_positive_int

    result = _validate_positive_int("test", 5, default=1)

    assert result == 5


def test_validate_positive_int_none():
    """Test validation returns default for None."""
    from src.web.routes.review_images import _validate_positive_int

    result = _validate_positive_int("test", None, default=1)

    assert result == 1


def test_validate_positive_int_below_min():
    """Test validation returns default for value below minimum."""
    from src.web.routes.review_images import _validate_positive_int

    with patch("src.web.routes.review_images.flash"):
        result = _validate_positive_int("test", -5, default=1, min_value=1)

    assert result == 1


def test_validate_positive_int_above_max():
    """Test validation caps value at maximum."""
    from src.web.routes.review_images import _validate_positive_int

    with patch("src.web.routes.review_images.flash"):
        result = _validate_positive_int("test", 200, default=50, min_value=1, max_value=100)

    assert result == 100


# =============================================================================
# Sample data constants for TestImageStats
# =============================================================================

_SAMPLE_OVERALL_STATS = {
    "total_decisions": 25,
    "relevant_count": 18,
    "not_relevant_count": 7,
    "relevant_pct": 72.0,
    "not_relevant_pct": 28.0,
    "avg_review_time_seconds": 12.5,
}

_SAMPLE_TIER_STATS = [
    {
        "detection_tier": "tier_1_cohort",
        "relevant_count": 15,
        "not_relevant_count": 3,
        "total_decisions": 18,
        "precision_pct": 83.3,
    }
]

_SAMPLE_DAILY_COUNTS = [
    {"date": "2026-03-24", "count": 3},
    {"date": "2026-03-25", "count": 5},
]

_SAMPLE_PROGRESS = {
    "total_candidates": 50,
    "pending_count": 25,
    "reviewed_count": 20,
    "skipped_count": 5,
    "review_pct": 40.0,
    "total_filings": 10,
    "filings_with_pending": 7,
    "by_tier": {"tier_1_cohort": {"total": 20, "pending": 10, "reviewed": 10}},
}

_SAMPLE_CHART_TYPE_STATS = [
    {"chart_type": "cohort_parfait", "chart_count": 10, "pct_of_relevant": 55.6}
]

_SAMPLE_REJECTION_STATS = [
    {
        "detection_tier": "tier_2_large",
        "rejection_reason": "not_a_chart",
        "rejection_count": 4,
        "pct_of_tier_rejections": 57.1,
    }
]


# =============================================================================
# Test image_stats() route - Stats Dashboard Tests
# =============================================================================


class TestImageStats:
    """Tests for the /review/images/stats route."""

    def test_image_stats_returns_200(self, client, mock_db, mock_render_template):
        """Stats page returns 200 when all DB methods succeed."""
        mock_db.get_image_overall_decision_statistics.return_value = _SAMPLE_OVERALL_STATS
        mock_db.get_image_decision_statistics.return_value = _SAMPLE_TIER_STATS
        mock_db.get_image_daily_decision_counts.return_value = _SAMPLE_DAILY_COUNTS
        mock_db.get_image_review_progress.return_value = _SAMPLE_PROGRESS
        mock_db.get_image_chart_type_distribution.return_value = _SAMPLE_CHART_TYPE_STATS
        mock_db.get_image_rejection_reason_stats.return_value = _SAMPLE_REJECTION_STATS

        response = client.get("/review/images/stats")
        assert response.status_code == 200

    def test_image_stats_passes_correct_context(self, client, mock_db, mock_render_template):
        """Stats route passes all 8 expected template variables."""
        mock_db.get_image_overall_decision_statistics.return_value = _SAMPLE_OVERALL_STATS
        mock_db.get_image_decision_statistics.return_value = _SAMPLE_TIER_STATS
        mock_db.get_image_daily_decision_counts.return_value = _SAMPLE_DAILY_COUNTS
        mock_db.get_image_review_progress.return_value = _SAMPLE_PROGRESS
        mock_db.get_image_chart_type_distribution.return_value = _SAMPLE_CHART_TYPE_STATS
        mock_db.get_image_rejection_reason_stats.return_value = _SAMPLE_REJECTION_STATS

        client.get("/review/images/stats")

        mock_render_template.assert_called_once()
        call_args = mock_render_template.call_args
        assert call_args.args[0] == "image_stats.html"
        kwargs = call_args.kwargs
        assert kwargs["overall_stats"] == _SAMPLE_OVERALL_STATS
        assert kwargs["tier_stats"] == _SAMPLE_TIER_STATS
        assert kwargs["daily_counts"] == _SAMPLE_DAILY_COUNTS
        assert kwargs["progress"] == _SAMPLE_PROGRESS
        assert kwargs["chart_type_stats"] == _SAMPLE_CHART_TYPE_STATS
        assert kwargs["rejection_stats"] == _SAMPLE_REJECTION_STATS
        assert "chart_type_labels" in kwargs
        assert "rejection_reason_labels" in kwargs

    def test_image_stats_redirects_on_db_error(self, client, mock_db, mock_render_template):
        """Stats route redirects to filing list when DB raises an exception."""
        mock_db.get_image_overall_decision_statistics.side_effect = Exception(
            "DB connection failed"
        )

        response = client.get("/review/images/stats")
        assert response.status_code == 302
        assert "/review/images" in response.headers["Location"]
