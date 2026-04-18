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
            {"suggested_metric_id": "cm_revenue_per_customer"},  # Revenue (23)
            {"suggested_metric_id": "cm_customers_period_end"},  # Customer Count (1)
            {"suggested_metric_id": "cm_net_revenue_retention"},  # Retention (31)
            {"suggested_metric_id": "cm_customer_acquisition_cost"},  # Unit Economics (42)
        ]

        result = _get_unique_metrics_for_filing(candidates)

        # Should be ordered by category, not alphabetically
        assert result == [
            "cm_customers_period_end",  # Category 1
            "cm_revenue_per_customer",  # Category 3
            "cm_net_revenue_retention",  # Category 4
            "cm_customer_acquisition_cost",  # Category 5
        ]

    def test_deduplicates(self):
        """Verify duplicate metric IDs are removed."""
        from src.web.routes.review import _get_unique_metrics_for_filing

        candidates = [
            {"suggested_metric_id": "cm_average_order_value"},
            {"suggested_metric_id": "cm_average_order_value"},
            {"suggested_metric_id": "cm_average_order_value"},
        ]

        result = _get_unique_metrics_for_filing(candidates)

        assert result == ["cm_average_order_value"]
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
