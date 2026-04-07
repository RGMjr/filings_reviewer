"""
Unit tests for Flask review routes (D1).

Tests all routes in src/web/routes/review.py using mocked database.
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
    with patch("src.web.routes.review.get_db") as mock_get_db, \
         patch("src.web.app.get_db") as mock_app_get_db:
        mock = MagicMock()
        mock_get_db.return_value = mock
        mock_app_get_db.return_value = mock
        yield mock


@pytest.fixture
def mock_render_template():
    """Mock render_template for tests that still render templates."""
    with patch("src.web.routes.review.render_template") as mock:
        mock.return_value = "mocked template"
        yield mock


# =============================================================================
# Test index() route
# =============================================================================

def test_index_redirects_to_v2_filing_list(client):
    """Test that index redirects to V2 filing list."""
    response = client.get("/")
    assert response.status_code == 302
    assert "/v2/review/filings" in response.location


def test_v1_filings_redirects_to_unified(client):
    """/filings now permanently redirects to the unified filing list."""
    response = client.get("/filings")
    assert response.status_code == 301
    assert "/v2/review/filings" in response.location


# =============================================================================
# Test filing_list() route — now a redirect
# =============================================================================


def test_filing_list_redirects_to_unified(client):
    """/filings permanently redirects to unified filing list."""
    response = client.get("/filings")
    assert response.status_code == 301
    assert "/v2/review/filings" in response.location


# =============================================================================
# Test review_filing() route — now a redirect
# =============================================================================


def test_review_filing_redirects_to_unified_text_tab(client):
    """/review/<id> permanently redirects to unified review (text tab)."""
    response = client.get("/review/1")
    assert response.status_code == 301
    assert "/v2/review/1" in response.location
    assert "tab=text" in response.location


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
# Test stats() route — now a redirect
# =============================================================================


def test_stats_redirects_to_unified(client):
    """/stats permanently redirects to unified stats."""
    response = client.get("/stats")
    assert response.status_code == 301
    assert "/v2/review/stats" in response.location


# =============================================================================
# Test _build_metric_order_clause() (MET-8)
# =============================================================================


class TestBuildMetricOrderClause:
    """Tests for _build_metric_order_clause SQL generation."""

    def test_generates_valid_case_statement(self):
        """Verify generated SQL has correct structure."""
        from src.web.routes.review import _build_metric_order_clause

        clause = _build_metric_order_clause()

        assert clause.startswith("CASE metric_id")
        assert "ELSE 99" in clause
        assert clause.endswith("END")

    def test_includes_all_metrics_from_dict(self):
        """Verify every metric in METRIC_DISPLAY_ORDER appears in SQL."""
        from src.web.routes.review import METRIC_DISPLAY_ORDER, _build_metric_order_clause

        clause = _build_metric_order_clause()

        for metric_id, order in METRIC_DISPLAY_ORDER.items():
            assert f"WHEN '{metric_id}' THEN {order}" in clause

    def test_ordering_values_are_integers(self):
        """Verify all THEN values are valid integers."""
        import re

        from src.web.routes.review import _build_metric_order_clause

        clause = _build_metric_order_clause()
        then_values = re.findall(r"THEN (\d+)", clause)

        assert len(then_values) > 0
        for val in then_values:
            assert val.isdigit()

    def test_no_user_input_in_clause(self):
        """Verify the clause only contains hardcoded metric IDs from METRIC_DISPLAY_ORDER."""
        import re

        from src.web.routes.review import METRIC_DISPLAY_ORDER, _build_metric_order_clause

        clause = _build_metric_order_clause()

        # Extract all metric IDs from the generated SQL
        metric_ids_in_clause = re.findall(r"WHEN '([^']+)' THEN", clause)

        # All should match entries in METRIC_DISPLAY_ORDER
        for metric_id in metric_ids_in_clause:
            assert metric_id in METRIC_DISPLAY_ORDER, f"Unexpected metric_id: {metric_id}"

    def test_clause_count_matches_dict_count(self):
        """Verify number of WHEN clauses matches dict entries."""
        import re

        from src.web.routes.review import METRIC_DISPLAY_ORDER, _build_metric_order_clause

        clause = _build_metric_order_clause()
        when_clauses = re.findall(r"WHEN '[^']+' THEN \d+", clause)

        assert len(when_clauses) == len(METRIC_DISPLAY_ORDER)


class TestGetUniqueMetricsForFiling:
    """Tests for _get_unique_metrics_for_filing filter dropdown helper."""

    def test_semantic_ordering(self):
        """Verify filter dropdown uses semantic ordering, not alphabetical."""
        from src.web.routes.review import _get_unique_metrics_for_filing

        # Create candidates with metrics from different categories
        candidates = [
            {"suggested_metric_id": "cm_arr"},  # Revenue (21)
            {"suggested_metric_id": "cm_customers_period_end"},  # Customer Count (1)
            {"suggested_metric_id": "cm_net_revenue_retention"},  # Retention (31)
            {"suggested_metric_id": "cm_customer_acquisition_cost"},  # Unit Economics (42)
        ]

        result = _get_unique_metrics_for_filing(candidates)

        # Should be ordered by category, not alphabetically
        assert result == [
            "cm_customers_period_end",  # Category 1
            "cm_arr",  # Category 3
            "cm_net_revenue_retention",  # Category 4
            "cm_customer_acquisition_cost",  # Category 5
        ]

    def test_deduplicates(self):
        """Verify duplicate metric IDs are removed."""
        from src.web.routes.review import _get_unique_metrics_for_filing

        candidates = [
            {"suggested_metric_id": "cm_arr"},
            {"suggested_metric_id": "cm_arr"},
            {"suggested_metric_id": "cm_arr"},
        ]

        result = _get_unique_metrics_for_filing(candidates)

        assert result == ["cm_arr"]
        assert len(result) == 1

    def test_unknown_metric_at_end(self):
        """Unknown metrics should sort to end (order 99)."""
        from src.web.routes.review import _get_unique_metrics_for_filing

        candidates = [
            {"suggested_metric_id": "cm_unknown_metric"},
            {"suggested_metric_id": "cm_customers_period_end"},
        ]

        result = _get_unique_metrics_for_filing(candidates)

        assert result[0] == "cm_customers_period_end"
        assert result[-1] == "cm_unknown_metric"
