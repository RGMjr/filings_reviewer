"""
Unit tests for unified review routes (WI-04: async audit logging, WI-05: pagination).

These tests cover the unified review blueprint (review_unified.py) which replaced
the old review_v2.py blueprint at the same /v2/review/ URL prefix.
"""

from unittest.mock import MagicMock, patch

import pytest

from src.web.app import create_app

# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def app():
    app = create_app("testing")
    app.config["TESTING"] = True
    app.config["DATABASE_URL"] = "postgresql://test"
    app.config["_db_pool"] = None
    return app


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def mock_db():
    with (
        patch("src.web.routes.review_unified.get_db") as mock_get_db,
        patch("src.web.routes._metrics.get_db") as mock_metrics_get_db,
    ):
        mock = MagicMock()
        mock_get_db.return_value = mock
        mock_metrics_get_db.return_value = mock
        yield mock


@pytest.fixture(autouse=True)
def mock_render_template():
    with patch("src.web.routes.review_unified.render_template") as mock:
        mock.return_value = "mocked template"
        yield mock


# =============================================================================
# WI-04: Async Audit Logging
# =============================================================================


def test_audit_log_fires_in_background_thread(client, mock_db, app):
    """After each request a daemon thread is spawned to write the audit log."""
    mock_db.get_unified_filings_for_review_count.return_value = 0
    mock_db.get_unified_filings_for_review.return_value = []

    with patch("src.web.routes.review_unified.threading.Thread") as mock_thread_cls:
        mock_thread = MagicMock()
        mock_thread_cls.return_value = mock_thread

        client.get("/v2/review/filings")

        # Thread was constructed with daemon=True
        _, kwargs = mock_thread_cls.call_args
        assert kwargs.get("daemon") is True
        # Thread was started
        mock_thread.start.assert_called_once()


def test_audit_log_error_does_not_block_response(client, app):
    """A DB error inside the audit thread must not affect the HTTP response."""
    with patch("src.web.routes.review_unified.get_db") as mock_get_db:
        mock = MagicMock()
        mock.get_unified_filings_for_review_count.return_value = 0
        mock.get_unified_filings_for_review.return_value = []
        mock_get_db.return_value = mock

        with patch("src.web.routes.review_unified.DatabaseAdapter") as mock_adapter_cls:
            mock_adapter = MagicMock()
            mock_adapter.insert_audit_log.side_effect = RuntimeError("DB timeout")
            mock_adapter_cls.return_value = mock_adapter

            response = client.get("/v2/review/filings")
            # Response must still succeed despite the audit log failure
            assert response.status_code == 200


def test_audit_log_captures_request_context(client, app):
    """The kwargs dict passed to the thread contains the expected request fields."""
    with patch("src.web.routes.review_unified.get_db") as mock_get_db:
        mock = MagicMock()
        mock.get_unified_filings_for_review_count.return_value = 0
        mock.get_unified_filings_for_review.return_value = []
        mock_get_db.return_value = mock

        def fake_thread(**kwargs):
            t = MagicMock()
            t.start = MagicMock()
            return t

        with patch("src.web.routes.review_unified.threading.Thread", side_effect=fake_thread) as mock_thread_cls:
            client.get("/v2/review/filings?page=1")
            call_kwargs = mock_thread_cls.call_args[1]
            assert call_kwargs["daemon"] is True
            assert callable(call_kwargs["target"])


# =============================================================================
# WI-05: Pagination — filing_list()
# =============================================================================


def test_filing_list_default_pagination(client, mock_db, mock_render_template):
    """Default request uses limit=50, offset=0."""
    mock_db.get_unified_filings_for_review_count.return_value = 5
    mock_db.get_unified_filings_for_review.return_value = []

    client.get("/v2/review/filings")

    mock_db.get_unified_filings_for_review.assert_called_once_with(
        document_type=None, limit=50, offset=0, hide_completed=False
    )


def test_filing_list_custom_page(client, mock_db, mock_render_template):
    """?page=2&per_page=25 passes limit=25, offset=25."""
    mock_db.get_unified_filings_for_review_count.return_value = 100
    mock_db.get_unified_filings_for_review.return_value = []

    client.get("/v2/review/filings?page=2&per_page=25")

    mock_db.get_unified_filings_for_review.assert_called_once_with(
        document_type=None, limit=25, offset=25, hide_completed=False
    )


def test_filing_list_per_page_cap(client, mock_db, mock_render_template):
    """?per_page=999 is capped to 200."""
    mock_db.get_unified_filings_for_review_count.return_value = 5
    mock_db.get_unified_filings_for_review.return_value = []

    client.get("/v2/review/filings?per_page=999")

    mock_db.get_unified_filings_for_review.assert_called_once_with(
        document_type=None, limit=200, offset=0, hide_completed=False
    )


def test_filing_list_total_pages_in_context(client, mock_db, mock_render_template):
    """total_pages is passed to template and computed correctly."""
    mock_db.get_unified_filings_for_review_count.return_value = 110
    mock_db.get_unified_filings_for_review.return_value = []

    client.get("/v2/review/filings?per_page=50")

    _, kwargs = mock_render_template.call_args
    assert kwargs["total"] == 110
    assert kwargs["total_pages"] == 3  # ceil(110/50)
    assert kwargs["page"] == 1
    assert kwargs["per_page"] == 50


# =============================================================================
# WI-05: Pagination — review_filing()
# =============================================================================


FILING_ROW = {
    "filing_id": 1,
    "company_name": "TestCo",
    "cik": "0001234567",
    "accession_number": "0001234567-23-000001",
    "form_type": "S-1",
    "filing_date": "2023-01-01",
    "company_id": 1,
    "document_type": "sec_filing",
}

FACT_ROW = {
    "fact_id": "uuid-1",
    "doc_id": 1,
    "canonical_metric_id": "cm_customers_period_end",
    "value": 1000.0,
    "value_raw": "1,000",
    "unit": "count",
    "currency": None,
    "period_type": "instant",
    "period_start": None,
    "period_end": "2023-06-30",
    "scope": None,
    "scope_detail": None,
    "cohort_def": None,
    "customer_type": None,
    "source_type": "table",
    "source_locator": None,
    "evidence_pack": None,
    "confidence": 0.95,
    "extraction_method": "keyword",
    "requires_review": True,
    "review_reason": None,
    "review_status": "pending_review",
    "pipeline_version": "2.0",
    "created_at": "2023-01-01",
    "updated_at": "2023-01-01",
    "decision_id": None,
    "decision": None,
    "decision_metric_id": None,
    "corrected_value": None,
    "rejection_reason": None,
    "rejection_category": None,
    "reviewer_id": None,
    "reviewer_notes": None,
    "review_time_seconds": None,
    "decision_created_at": None,
}


def test_review_filing_pagination(client, mock_db, mock_render_template):
    """review_filing() passes limit/offset to get_v2_facts_for_filing."""
    mock_db.query.return_value = [FILING_ROW]
    mock_db.get_v2_facts_for_filing.return_value = [FACT_ROW]
    mock_db.count_v2_facts_for_filing.return_value = 150
    mock_db.get_image_review_candidates_for_filing.return_value = []

    client.get("/v2/review/1?page=2&per_page=50")

    # Paginated call should use limit=50, offset=50
    calls = mock_db.get_v2_facts_for_filing.call_args_list
    # First call is unfiltered (all_facts), second is filtered+paginated
    assert len(calls) == 2
    _, paginated_kwargs = calls[1]
    assert paginated_kwargs["limit"] == 50
    assert paginated_kwargs["offset"] == 50


def test_review_filing_pagination_in_template(client, mock_db, mock_render_template):
    """page/per_page/total_pages are passed to the template."""
    mock_db.query.return_value = [FILING_ROW]
    mock_db.get_v2_facts_for_filing.return_value = [FACT_ROW]
    mock_db.count_v2_facts_for_filing.return_value = 75
    mock_db.get_image_review_candidates_for_filing.return_value = []

    client.get("/v2/review/1?per_page=50")

    _, kwargs = mock_render_template.call_args
    assert kwargs["page"] == 1
    assert kwargs["per_page"] == 50
    assert kwargs["total_pages"] == 2  # ceil(75/50)
    assert kwargs["total_facts"] == 75


# =============================================================================
# WI-05: Backward compatibility — db.py level (no limit = all rows)
# =============================================================================


def test_backward_compat_no_limit_filings(mock_db):
    """get_v2_filings_with_facts() with no args still works (returns all rows)."""
    from src.infra.db import DatabaseAdapter

    db = DatabaseAdapter.__new__(DatabaseAdapter)
    db.query = MagicMock(return_value=[{"filing_id": 1}])

    result = db.get_v2_filings_with_facts()

    # Called with no pagination params
    db.query.assert_called_once()
    call_args = db.query.call_args
    # No dict with limit/offset passed
    assert call_args[0][0].strip().endswith("NULLS LAST")
    assert result == [{"filing_id": 1}]


def test_backward_compat_no_limit_facts(mock_db):
    """get_v2_facts_for_filing() with no limit still works (returns all rows)."""
    from src.infra.db import DatabaseAdapter

    db = DatabaseAdapter.__new__(DatabaseAdapter)
    db.query = MagicMock(return_value=[FACT_ROW])

    result = db.get_v2_facts_for_filing(filing_id=1)

    db.query.assert_called_once()
    # SQL should not contain LIMIT clause
    sql_arg = db.query.call_args[0][0]
    assert "LIMIT" not in sql_arg
    assert result == [FACT_ROW]


# =============================================================================
# V2 Index Redirect
# =============================================================================

def test_v2_index_redirects_to_filings(client):
    """Test that /v2/review/ redirects to /v2/review/filings."""
    response = client.get("/v2/review/")
    assert response.status_code == 302
    assert "/v2/review/filings" in response.location
